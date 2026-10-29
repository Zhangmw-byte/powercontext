# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at https://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import asyncio
import io
import json
from hashlib import sha256
from typing import Any, cast

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sources import SourceRepository
from powercontext.builtin.persistence.sqlite import SQLiteConfig, SQLiteProfile
from powercontext.builtin.persistence.tables import SHARED_TABLES
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    RetireMemoryEntryRequest,
    SubmitSourceObservation,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    SourceDefinitionRegistry,
    SourceMaterialization,
    SourceRef,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    PDFPageInput,
    PDFPageSource,
    parse_pdf_document,
    pdf_page_source_id,
    search_pdf_pages,
)


def _pdf(*texts, password=None, title=None, broken_last=False):
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
    )
    for index, text in enumerate(texts):
        page = writer.add_blank_page(width=612, height=792)
        if not text:
            continue
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
        })
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content = f"BT /F1 12 Tf 20 720 Td ({escaped}) Tj ET".encode("ascii")
        if broken_last and index == len(texts) - 1:
            content = b"BT /F1 12 Tf (unterminated"
        stream = DecodedStreamObject()
        stream.set_data(content)
        page[NameObject("/Contents")] = writer._add_object(stream)
    if password is not None:
        writer.encrypt(user_password=password, owner_password="owner")  # noqa: S106
    if title is not None:
        writer.add_metadata({"/Title": title})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_full_physical_page_order_blank_pages_numbers_and_long_text():
    long = "Full original accounting evidence 12345. " * 400
    raw = _pdf("Physical first page, printed page 88.", "", "Revenue 2022: 123.45; 2021: 98.76.", long)
    pages = parse_pdf_document(PDFDocumentInput(document_id="financial", content=raw))
    assert isinstance(pages, tuple)
    assert [p.page_number for p in pages] == [1, 2, 3, 4]
    assert pages[1].text == ""
    assert "123.45" in pages[2].text and "98.76" in pages[2].text
    assert pages[3].text == long
    assert all(p.document_sha256 == sha256(raw).hexdigest() and p.document_id == "financial" for p in pages)


@pytest.mark.parametrize("raw", [b"", b"not PDF", b"%PDF-1.7\ntruncated", b"%PDF-1.7\n%%EOF", b"\x00%PDF-1.7"])
def test_invalid_documents_are_value_errors(raw):
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="invalid", content=raw))


def test_late_broken_content_does_not_return_partial_pages():
    with pytest.raises(ValueError):
        parse_pdf_document(
            PDFDocumentInput(
                document_id="broken", content=_pdf("Valid first page.", "Broken last page.", broken_last=True)
            )
        )


def test_truncated_trailer_and_wrong_password_are_rejected():
    raw = _pdf("Original evidence.")
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="cut", content=raw[:-20]))
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="locked", content=_pdf("Private evidence.", password="secret")))  # noqa: S106


def test_empty_password_permissions_preserve_page_text():
    pages = parse_pdf_document(
        PDFDocumentInput(document_id="permission", content=_pdf("Readable evidence 987.", password=""))
    )
    assert len(pages) == 1 and "987" in pages[0].text


@pytest.mark.parametrize("document_id", ["", " ", "\n\t"])
def test_blank_document_ids_are_rejected(document_id):
    with pytest.raises(ValueError):
        PDFDocumentInput(document_id=document_id, content=b"%PDF-")


@pytest.mark.parametrize(
    "changes",
    [
        {"document_sha256": "A" * 64},
        {"document_sha256": "a" * 63},
        {"document_sha256": "z" * 64},
        {"page_number": 0},
        {"page_number": -1},
        {"page_number": True},
        {"page_number": 1.0},
        {"page_number": "1"},
    ],
)
def test_page_identity_fields_are_strict(changes):
    with pytest.raises(ValueError):
        PDFPageInput(**({"document_id": "doc", "document_sha256": "a" * 64, "page_number": 1, "text": ""} | changes))


def test_long_unicode_ids_are_preserved_and_tuple_identities_do_not_collide():
    def page(document_id, digest="a" * 64, number=1):
        return PDFPageInput(document_id=document_id, document_sha256=digest, page_number=number, text="")

    values = [
        page(" report "),
        page("财报:/%_" * 1000),
        page("a:b"),
        page("a"),
        page("a:b", number=2),
        page("a:b", digest="b" * 64),
    ]
    identities = [pdf_page_source_id(p) for p in values]
    assert len(set(identities)) == len(values)
    assert all(len(identity) <= 256 for identity in identities)
    assert all(pdf_page_source_id(p) == identity for p, identity in zip(values, identities, strict=True))
    assert values[0].document_id == " report "


def test_source_definition_projection_roundtrip_and_document_revisions():
    async def scenario():
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        first = parse_pdf_document(
            PDFDocumentInput(document_id="doc", content=_pdf("Original table 100.", title="one"))
        )
        second = parse_pdf_document(
            PDFDocumentInput(document_id="doc", content=_pdf("Original table 100.", title="two"))
        )
        original, revised = await registry.resolve(first[0]), await registry.resolve(second[0])
        assert original.materialization == SourceMaterialization.CAPTURED and original.definition_version == "1"
        assert original.name != revised.name
        assert await registry.read(original) == first[0]
        assert PDFPageSource.model_validate_json(original.model_dump_json()) == original
        observation = project_source_for_transport(registry, original)
        text = observation.projection(TEXT_EVIDENCE_PROJECTION_KEY)
        assert text == {
            "source_type": "pdf-page",
            "source_id": original.name,
            "content": "doc\n" + first[0].text,
            "metadata": {"document_id": "doc", "document_sha256": first[0].document_sha256, "page_number": 1},
        }
        payload = json.loads(original.model_dump_json())
        payload["name"] = "pdf:wrong"
        with pytest.raises(ValueError):
            PDFPageSource.model_validate_json(json.dumps(payload))

    asyncio.run(scenario())


def test_original_page_source_remains_readable_after_persistence_reopen(tmp_path):
    async def scenario():
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        originals = parse_pdf_document(PDFDocumentInput(document_id="doc", content=_pdf("Income table 200.", "")))
        repository = SourceRepository(registry)
        config = SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'source.db'}")
        sources = [await registry.resolve(page) for page in originals]
        async with (
            SQLiteProfile.open(config, tables=SHARED_TABLES) as profile,
            profile.database.transaction() as connection,
        ):
            for source in sources:
                await repository.add(connection, "scope", source)
            await repository.add(connection, "scope", sources[0])
            assert await repository.journal_position(connection, "scope") == 2
        async with (
            SQLiteProfile.open(config, tables=SHARED_TABLES) as profile,
            profile.database.transaction() as connection,
        ):
            for source, page in zip(sources, originals, strict=True):
                reference = SourceRef(source_type="pdf-page", source_id=source.name)
                stored = await repository.get(connection, "scope", reference)
                assert await registry.read(stored.value) == page

    asyncio.run(scenario())


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


def test_real_scoped_search_restart_distinct_pages_citations_and_current_state(tmp_path):
    async def scenario():
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"))
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        pages = parse_pdf_document(
            PDFDocumentInput(
                document_id="ACME_2022_10K",
                content=_pdf(
                    "General administrative history and employee meeting agenda.",
                    "Consolidated Statements of Cash Flows. Capital expenditures for 2022 were 123. Depreciation was 45.",
                    "",
                    "Legal Proceedings. Litigation was settled in 2022 for 10.",
                    "Geographic operations include North America, Europe and Asia Pacific.",
                ),
            )
        )
        observations = [project_source_for_transport(registry, await registry.resolve(page)) for page in pages]
        async with open_builtin_runtime(config, candidate_pipeline=_LiteralPipeline()) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(
                ScopeDraft(title="Report", summary="Evidence", idempotency_key="report")
            )
            other = await runtime.scopes.create(ScopeDraft(title="Other", summary="Isolated", idempotency_key="other"))
            await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
            for observation in observations:
                await runtime.ingestion.submit(
                    SubmitSourceObservation(scope_id=scope.scope_id, observation=observation)
                )
            await runtime.ingestion.submit(
                SubmitSourceObservation(scope_id=scope.scope_id, observation=observations[0])
            )
            memory = runtime.memory.for_scope(scope.scope_id)
            while (await memory.flush()).processed:
                pass
            assert await search_pdf_pages(runtime.memory.for_scope(other.scope_id), "capital expenditure", 20) == ()
        async with open_builtin_contexts(config) as contexts:
            journal = await (await contexts.get(scope.scope_id)).sources.journal.entries()
            assert len(journal) == 5
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope.scope_id)
            question = "How much did Acme spend on capital expenditures for 2022?"
            citations = await search_pdf_pages(memory, question, limit=20)
            assert citations and citations == await search_pdf_pages(memory, question, limit=20)
            assert len(citations) <= 20
            source_pages = {observation.name: page for observation, page in zip(observations, pages, strict=True)}
            seen = set()
            for citation in citations:
                record = await memory.get(GetMemoryEntryRequest(citation=citation))
                assert len(record.entry.sources) == 1
                original = source_pages[record.entry.sources[0].source_id]
                assert record.entry.text == (original.document_id + "\n" + original.text).strip()
                assert original.page_number not in seen
                seen.add(original.page_number)
            best = await memory.get(GetMemoryEntryRequest(citation=citations[0]))
            assert best.entry.sources[0].source_id == observations[1].name
            for query, expected_source in (
                ("What legal battles did Acme disclose?", observations[3].name),
                ("Which geographies does Acme operate in?", observations[4].name),
            ):
                selected = await search_pdf_pages(memory, query, 1)
                assert len(selected) == 1
                exact = await memory.get(GetMemoryEntryRequest(citation=selected[0]))
                assert exact.entry.sources[0].source_id == expected_source
            assert await search_pdf_pages(memory, question, 0) == ()
            await memory.retire(RetireMemoryEntryRequest(citation=citations[0]))
            remaining = await search_pdf_pages(memory, question, 20)
            assert all(c.entry_id != citations[0].entry_id for c in remaining)

    asyncio.run(scenario())


@pytest.mark.parametrize("question, limit", [(" ", 20), (None, 20), ("report", True), ("report", 1.5), ("report", -1)])
def test_invalid_search_requests_fail_before_reading_memory(question, limit):
    with pytest.raises(ValueError):
        asyncio.run(search_pdf_pages(cast(Any, None), question, limit))
