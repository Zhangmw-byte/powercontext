# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at https://www.apache.org/licenses/LICENSE-2.0

"""Measure selection against public SciFact training annotations, outside product code.

This diagnostic does not reproduce the platform's held-out 24-claim workload.
Run: PYTHONPATH=src competition/.venv/bin/python benchmark/evidence_selection/measure.py
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from pathlib import Path

from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput, MemoryHit
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.prepared_context import PreparedContextBuilder, PreparedMemoryCandidates
from powercontext.builtin.scope import ScopeDraft
from powercontext.builtin.sources import ContentSource


class LiteralPipeline:
    async def extract(self, request: MemoryCandidateRequest, /):
        return tuple(
            MemoryEntryInput(kind="document", text=source.content, sources=(source,))
            for source in request.sources
            if isinstance(source, ContentSource)
        )


def tokens(text):
    return Counter(re.findall(r"[a-z]+|\d+", text.lower()))


def merged(spans):
    result = []
    for start, end in sorted(spans):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


async def measure():
    sample = json.loads((Path(__file__).parent / "data/scifact-train-sample.json").read_text())
    observations = []
    async with open_builtin_runtime(BuiltinConfig(), candidate_pipeline=LiteralPipeline()) as runtime:
        for index, case in enumerate(sample["cases"]):
            scope = await runtime.scopes.create(
                ScopeDraft(
                    title="SciFact training diagnostic",
                    summary="Literal evidence",
                    idempotency_key=f"evidence-training-{index}",
                )
            )
            sources = runtime.sources.for_scope(scope.scope_id)
            memory = runtime.memory.for_scope(scope.scope_id)
            for document in case["documents"]:
                await sources.capture(CaptureSource(source_id=document["id"], content=document["text"], metadata={}))
            while (await memory.flush()).processed:
                pass
            page = await memory.list()
            by_text = {record.entry.text: record for record in page.entries}
            if len(by_text) != 3:
                raise RuntimeError("Expected three distinct persisted candidate documents")  # noqa: TRY003
            # All three already-recalled candidates are passed without annotations.
            hits = tuple(
                MemoryHit(
                    memory_ref=page.memory_ref,
                    entry_id=by_text[d["text"]].entry.entry_id,
                    entry_version_id=by_text[d["text"]].entry.entry_version_id,
                    text=d["text"],
                    score=1.0,
                    matched_by=("fts",),
                )
                for d in case["documents"]
            )
            group = PreparedMemoryCandidates(scope_id=scope.scope_id, memory_ref=page.memory_ref, hits=hits)
            evidence = next(d for d in case["documents"] if d["id"] == case["evidence_document_id"])
            evidence_entry_id = by_text[evidence["text"]].entry.entry_id
            reference = tokens(" ".join(evidence["text"][start:end] for start, end in case["evidence_spans"]))
            for budget in (1400, 1800):
                result = PreparedContextBuilder().build_scopes_result(
                    request=PrepareContextRequest(query=case["query"], max_bytes=budget, evidence_selection=True),
                    current_scope_id=scope.scope_id,
                    memory_candidates=(group,),
                )
                if not result.context.content_bytes == len((result.context.content or "").encode()) <= budget:
                    raise RuntimeError("Serialized context violates its declared byte budget")  # noqa: TRY003
                spans = merged([(f.start, f.end) for f in result.fragments if f.address.entry_id == evidence_entry_id])
                selected = tokens(" ".join(evidence["text"][start:end] for start, end in spans))
                recall = sum((reference & selected).values()) / sum(reference.values())
                complete = all(
                    any(left <= start and right >= end for left, right in spans)
                    for start, end in case["evidence_spans"]
                )
                for fragment in result.fragments:
                    from powercontext.artifacts import MemoryCitation

                    record = await memory.get(
                        GetMemoryEntryRequest(
                            citation=MemoryCitation(
                                memory_ref=fragment.address.memory.artifact,
                                entry_id=fragment.address.entry_id,
                                entry_version_id=fragment.address.entry_version_id,
                            )
                        )
                    )
                    if fragment.text != record.entry.text[fragment.start : fragment.end]:
                        raise RuntimeError("Fragment does not match its persisted original citation")  # noqa: TRY003
                observations.append({
                    "claim_id": case["claim_id"],
                    "max_bytes": budget,
                    "content_bytes": result.context.content_bytes,
                    "token_recall": recall,
                    "complete": complete,
                })
    return {
        "workload": sample["source"],
        "requests": len(observations),
        "mean_evidence_token_recall": sum(o["token_recall"] for o in observations) / len(observations),
        "complete_evidence_fraction": sum(o["complete"] for o in observations) / len(observations),
        "observations": observations,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(measure()), ensure_ascii=False, indent=2))
