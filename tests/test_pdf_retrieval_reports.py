# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Page retrieval regressions with independent, constructed financial reports."""

from __future__ import annotations

from hashlib import sha256

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    SourceDefinitionRegistry,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.pdf_pages import PDF_PAGE_SOURCE_DEFINITION, PDFPageInput, search_pdf_pages


class _LiteralPipeline:
    async def extract(self, request, /):
        return tuple(
            MemoryEntryInput(
                kind="source-evidence",
                text=source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"],
                sources=(source,),
            )
            for source in request.sources
        )


async def _store(tmp_path, reports):
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'reports.db'}"))
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    locations = {}
    async with open_builtin_runtime(config, candidate_pipeline=_LiteralPipeline()) as runtime:
        scope = await runtime.scopes.create(ScopeDraft(title="Reports", summary="Evidence", idempotency_key="reports"))
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for document, bodies in reports.items():
            digest = sha256("\n".join(bodies).encode()).hexdigest()
            for index, body in enumerate(bodies, start=1):
                page = PDFPageInput(document_id=document, document_sha256=digest, page_number=index, text=body)
                source = await registry.resolve(page)
                locations[source.name] = (document, index, document + "\n" + body)
                await runtime.ingestion.submit(
                    SubmitSourceObservation(
                        scope_id=scope.scope_id, observation=project_source_for_transport(registry, source)
                    )
                )
        while (await runtime.memory.for_scope(scope.scope_id).flush()).processed:
            pass
    return config, scope.scope_id, locations


async def _search(config, scope_id, locations, question, limit=20):
    # Reopen the actual SQLite Runtime; no ranking test doubles or synthetic citations.
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(memory, question, limit=limit)
        found = []
        for citation in citations:
            record = await memory.get(GetMemoryEntryRequest(citation=citation))
            assert len(record.entry.sources) == 1
            location = locations[record.entry.sources[0].source_id]
            assert record.entry.text == location[2]
            found.append(location[:2])
        assert len(found) == len(set(found))
        return found


async def test_named_report_cannot_be_crowded_out_by_other_company(tmp_path):
    config, scope_id, locations = await _store(
        tmp_path,
        {
            "ACME_2022_10K": [
                "Consolidated Statements of Cash Flows\n2022 2021\n"
                "Net cash provided by operating activities 1000. Purchases of property and equipment 200."
            ],
            "BETA_2022_10K": [
                "Consolidated Statements of Cash Flows\n2022\n"
                "Free cash flow, operating activities, depreciation, amortization, capital expenditures, "
                f"property plant and equipment. The free cash flow for division {i} was 100."
                for i in range(32)
            ],
            "GAMMA_2022_10K": [f"Personnel policies and employee appointments {i}." for i in range(100)],
        },
    )
    found = await _search(config, scope_id, locations, "What was Acme's free cash flow in 2022?")
    assert ("ACME_2022_10K", 1) in found


async def test_working_capital_question_retrieves_balance_sheet(tmp_path):
    config, scope_id, locations = await _store(
        tmp_path,
        {
            "DELTA_2022_10K": [
                "Consolidated Balance Sheets\n2022 2021\nTotal current assets 500. Total current liabilities 200."
            ]
            + [f"Working capital strategy and management overview for segment {i} in 2022." for i in range(32)],
            "GAMMA_2022_10K": [f"Personnel policies and employee appointments {i}." for i in range(100)],
        },
    )
    found = await _search(config, scope_id, locations, "What was Delta's working capital in 2022?")
    assert ("DELTA_2022_10K", 1) in found


async def test_explicit_report_year_distinguishes_company_revisions(tmp_path):
    config, scope_id, locations = await _store(
        tmp_path,
        {
            "ACME_2022_10K": ["Consolidated Statements of Income\n2022\nRevenue 500. Net income 50."],
            "ACME_2019_10K": [
                f"Consolidated Statements of Income\n2019\nRevenue growth, earnings and net income for segment {i}."
                for i in range(24)
            ],
        },
    )
    found = await _search(config, scope_id, locations, "What was Acme's net income in FY2022?")
    assert ("ACME_2022_10K", 1) in found


async def test_multi_company_question_keeps_both_named_reports(tmp_path):
    config, scope_id, locations = await _store(
        tmp_path,
        {
            "ACME_2022_10K": ["Consolidated Statements of Income\n2022\nRevenue 500."],
            "BETA_2022_10K": ["Consolidated Statements of Income\n2022\nRevenue 600."],
            "DELTA_2022_10K": ["Consolidated Statements of Income\n2022\nRevenue 700."],
        },
    )
    found = await _search(config, scope_id, locations, "Compare Acme and Beta revenue for 2022.")
    assert {("ACME_2022_10K", 1), ("BETA_2022_10K", 1)} <= set(found)
