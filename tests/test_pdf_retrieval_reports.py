# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Page retrieval regressions with independent, constructed financial reports."""

from __future__ import annotations

import asyncio
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
        assert runtime.scopes is not None
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


async def _store_and_search(tmp_path, reports, question):
    config, scope_id, locations = await _store(tmp_path, reports)
    return await _search(config, scope_id, locations, question)


def test_named_report_cannot_be_crowded_out_by_other_company(tmp_path):
    reports = {
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
    }
    found = asyncio.run(_store_and_search(tmp_path, reports, "What was Acme's free cash flow in 2022?"))
    assert ("ACME_2022_10K", 1) in found


def test_working_capital_question_retrieves_balance_sheet(tmp_path):
    reports = {
        "DELTA_2022_10K": [
            "Consolidated Balance Sheets\n2022 2021\nTotal current assets 500. Total current liabilities 200."
        ]
        + [f"Working capital strategy and management overview for segment {i} in 2022." for i in range(32)],
        "GAMMA_2022_10K": [f"Personnel policies and employee appointments {i}." for i in range(100)],
    }
    found = asyncio.run(_store_and_search(tmp_path, reports, "What was Delta's working capital in 2022?"))
    assert ("DELTA_2022_10K", 1) in found


def test_explicit_report_year_distinguishes_company_revisions(tmp_path):
    reports = {
        "ACME_2022_10K": ["Consolidated Statements of Income\n2022\nRevenue 500. Net income 50."],
        "ACME_2019_10K": [
            f"Consolidated Statements of Income\n2019\nRevenue growth, earnings and net income for segment {i}."
            for i in range(24)
        ],
    }
    found = asyncio.run(_store_and_search(tmp_path, reports, "What was Acme's net income in FY2022?"))
    assert ("ACME_2022_10K", 1) in found


def test_multi_company_question_keeps_both_named_reports(tmp_path):
    reports = {
        "ACME_2022_10K": ["Consolidated Statements of Income\n2022\nRevenue 500."],
        "BETA_2022_10K": ["Consolidated Statements of Income\n2022\nRevenue 600."],
        "DELTA_2022_10K": ["Consolidated Statements of Income\n2022\nRevenue 700."],
    }
    found = asyncio.run(_store_and_search(tmp_path, reports, "Compare Acme and Beta revenue for 2022."))
    assert {("ACME_2022_10K", 1), ("BETA_2022_10K", 1)} <= set(found)


def test_dense_page_beyond_eight_kibibytes_is_stored_and_cited_exactly(tmp_path):
    rows = "\n".join(
        f"10.{i} Indenture supplement {i} incorporated by reference to Form 8-K filed 2018." for i in range(140)
    )
    assert len(rows.encode()) > 8192
    reports = {"ACME_2022_10K": ["Exhibit Index\n" + rows, "Personnel policies and employee appointments."]}
    found = asyncio.run(_store_and_search(tmp_path, reports, "Which indenture supplements did Acme file?"))
    assert found[0] == ("ACME_2022_10K", 1)


def test_metric_question_returns_primary_statements_over_narrative_mentions(tmp_path):
    statements = [
        "Acme Corporation\nConsolidated Statements of Income\n(Millions, except per share amounts) 2022 2021 2020\n"
        "Net sales 34,229 35,355 32,184\nOperating income 6,539 7,369 6,772\nNet income 5,791 5,929 5,453\n"
        "Earnings per share 10.18 10.12 9.36",
        "Acme Corporation\nConsolidated Balance Sheet\n(Millions) 2022 2021\nProperty, plant and equipment 9,178 9,429\n"
        "Total assets 46,455 47,072\nTotal current liabilities 9,523 9,035\nTotal liabilities 31,685 31,955",
        "Acme Corporation\nConsolidated Statement of Cash Flows\n(Millions) 2022 2021 2020\n"
        "Net cash provided by operating activities 5,591 7,454 8,113\nPurchases of property, plant and equipment "
        "(1,749) (1,603) (1,501)\nNet cash used in investing activities (1,046) (1,317) (580)\n"
        "Net cash used in financing activities (4,656) (6,145) (5,300)",
    ]
    narrative = [
        f"Acme discusses whether its business is capital intensive in 2022 in risk factor {i}; capital intensive "
        "operations, capital spending priorities and the intensity of business investment are described here."
        for i in range(40)
    ]
    reports = {"ACME_2022_10K": narrative + statements}
    found = asyncio.run(
        _store_and_search(tmp_path, reports, "Is Acme a capital-intensive business based on FY2022 data?")
    )
    assert {("ACME_2022_10K", 41), ("ACME_2022_10K", 42), ("ACME_2022_10K", 43)} <= set(found)
