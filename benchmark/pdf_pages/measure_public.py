# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at https://www.apache.org/licenses/LICENSE-2.0

"""Measure complete public-PDF ingestion and inspect exact page retrieval.

The published questions have no evidence labels. This report measures coverage,
reference checks and elapsed time; it does not report evidence-page Recall@20.
Run with PYTHONPATH=src:competition using the fixed competition environment.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import time
from pathlib import Path

from selftest_support.source_acceptance import persist

from powercontext.builtin.runtime import GetMemoryEntryRequest, open_builtin_runtime
from powercontext.sources import SourceDefinitionRegistry, project_source_for_transport
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY

_ROOT = Path(__file__).resolve().parents[2]


async def measure():
    root = _ROOT
    workload = root / "competition/challenges/source-03-pdf-retrieval/workload/public"
    cases = json.loads((workload / "cases.json").read_text())["cases"]
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    observations = []
    documents = []
    started = time.monotonic()
    for case in cases:
        pages = parse_pdf_document(
            PDFDocumentInput(document_id=case["document_id"], content=(workload / case["file"]).read_bytes())
        )
        if len(pages) != case["page_count"] or any(p.document_sha256 != case["sha256"] for p in pages):
            raise ValueError("Full-document page count or digest mismatch")  # noqa: TRY003
        for page in pages:
            observations.append(project_source_for_transport(registry, await registry.resolve(page)))
        counts = [len(re.findall(r"[a-z]+|\d+", page.text.lower())) for page in pages]
        documents.append({
            "document_id": case["document_id"],
            "physical_pages": len(pages),
            "blank_pages": sum(not p.text.strip() for p in pages),
            "min_page_tokens": min(counts),
            "max_page_tokens": max(counts),
            "total_tokens": sum(counts),
        })
    parse_seconds = time.monotonic() - started
    results = []
    with tempfile.TemporaryDirectory(prefix="pc-pdf-benchmark-") as directory:
        started = time.monotonic()
        config, scope_id, stored = await persist(Path(directory), PDF_PAGE_SOURCE_DEFINITION, observations)
        persist_seconds = time.monotonic() - started
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            for case in cases:
                for question in case["questions"]:
                    started = time.monotonic()
                    citations = await search_pdf_pages(memory, question["question"], limit=20)
                    seconds = time.monotonic() - started
                    pages = []
                    for citation in citations:
                        entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
                        if len(entry.sources) != 1:
                            raise ValueError("Expected one exact original page per citation")  # noqa: TRY003
                        observation = stored[entry.sources[0].source_id]
                        projection = observation.projection(TEXT_EVIDENCE_PROJECTION_KEY)
                        if entry.text != projection["content"].strip():
                            raise ValueError("Citation text is not the full persisted page")  # noqa: TRY003
                        pages.append(projection["metadata"])
                    results.append({
                        "question": question["question"],
                        "returned_citations": len(citations),
                        "search_seconds": seconds,
                        "pages": pages,
                    })
    return {
        "documents": documents,
        "parse_seconds": parse_seconds,
        "persist_seconds": persist_seconds,
        "questions": results,
        "evidence_page_recall_at_20": None,
        "quality_status": "Not measured: official public questions do not include evidence-page labels",
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(measure()), ensure_ascii=False, indent=2))
