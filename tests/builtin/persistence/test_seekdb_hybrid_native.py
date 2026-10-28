# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at https://www.apache.org/licenses/LICENSE-2.0

"""Required native SeekDB checks; failures are not replaced with mock execution."""

from __future__ import annotations

import hashlib
import json
import math
import re
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import Engine, event

from powercontext.builtin.artifacts.memory import EmbeddingProfile, MemoryEntryInput
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.persistence.memory_index import CompositeMemoryIndex
from powercontext.builtin.persistence.seekdb import SeekDBConfig
from powercontext.builtin.persistence.seekdb.memory_index import SeekDBMemoryIndex
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts
from powercontext.builtin.tags import MemoryEntryTagTarget, TagFilter

PROFILE = EmbeddingProfile(
    profile_id="native-hybrid-diagnostic-v1",
    model="offline-token-hash",
    dimension=384,
    distance="l2",
    normalization="unit",
)


class _Embedding:
    profile = PROFILE

    async def embed(self, texts, /):
        vectors = []
        for text in texts:
            vector = [0.0] * 384
            for token in re.findall(r"[a-z]+|\d+", text.casefold()):
                index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4]) % 384
                vector[index] += 1.0
            norm = math.sqrt(sum(value * value for value in vector))
            if not norm:
                vector[0] = norm = 1.0
            vectors.append(tuple(value / norm for value in vector))
        return EmbeddingResult(vectors=tuple(vectors))


@contextmanager
def _statements():
    statements = []

    def record(_connection, _cursor, statement, parameters, _context, _executemany):
        statements.append((statement, parameters))

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", record)


def _identity(hit):
    ref = hit.memory_ref
    return ref.family, ref.artifact_id, ref.revision, hit.entry_id, hit.entry_version_id, hit.text, hit.matched_by


@pytest.mark.asyncio
async def test_384_dimension_native_search_keeps_frozen_channel_candidates_scopes_and_plans(tmp_path, monkeypatch):
    data = (
        Path(__file__).parents[3]
        / "competition/challenges/retrieval-02-hybrid-search/workload/public/scifact-sample.json"
    )
    sample = json.loads(data.read_text())
    documents = [d["title"] + " " + d["text"] for d in sample["documents"]]
    queries = [sample["queries"][0]["text"], "stem cell tracking", "Fanconi anemia mutations", "methane cancer bowel"]
    plan_checked = False
    async with open_builtin_contexts(
        BuiltinConfig(database=SeekDBConfig(path=tmp_path / "db")), embedding_model=_Embedding()
    ) as contexts:
        identities = set()
        for scope_id in ("scope-one", "scope-two", "scope-three"):
            memory = (await contexts.get(scope_id)).artifacts.memory
            head = await memory.remember(
                memory=None,
                entries=tuple(MemoryEntryInput(kind="document", text=text) for text in documents),
                mode="append",
            )
            assert head is not None
            current = {entry.entry_id for entry in await memory.entries(head)}
            for query in queries:
                with _statements() as statements:
                    candidate = await memory.search(query, memories=(head,), mode="hybrid", limit=10)
                candidates = [
                    (sql, params)
                    for sql, params in statements
                    if "AGAINST" in sql.upper() and "l2_distance" in sql.lower()
                ]
                assert len(candidates) == 1
                assert len({(h.entry_id, h.entry_version_id) for h in candidate.hits}) == len(candidate.hits)
                assert all(
                    h.memory_ref == head.as_ref() and h.entry_id in current and h.text in documents and h.matched_by
                    for h in candidate.hits
                )
                repeated = await memory.search(query, memories=(head,), mode="hybrid", limit=10)
                assert tuple(map(_identity, repeated.hits)) == tuple(map(_identity, candidate.hits))
                # Exercise the frozen two-statement strategy in the same database,
                # with identical scope, head, query and deterministic embeddings.
                with monkeypatch.context() as baseline_patch:
                    baseline_patch.setattr(SeekDBMemoryIndex, "search", CompositeMemoryIndex.search)
                    control = await memory.search(query, memories=(head,), mode="hybrid", limit=10)
                assert {_identity(h) for h in candidate.hits} == {_identity(h) for h in control.hits}
                if not plan_checked:
                    sql, params = candidates[0]
                    async with contexts.database.transaction() as connection:
                        plan = "\n".join(
                            str(row[0]) for row in (await connection.exec_driver_sql("EXPLAIN " + sql, params)).all()
                        )
                    assert "TEXT RETRIEVAL SCAN" in plan and "VECTOR INDEX" in plan
                    print("\nNative 384-dimensional hybrid plan:\n" + plan)
                    plan_checked = True
            current = {entry.entry_id for entry in await memory.entries(head)}
            assert not identities.intersection(current)
            identities.update(current)


@pytest.mark.asyncio
@pytest.mark.parametrize("match", ["all", "any"])
async def test_native_tag_filters_precede_each_candidate_limit(tmp_path, match):
    async with open_builtin_contexts(
        BuiltinConfig(database=SeekDBConfig(path=tmp_path / "db")), embedding_model=_Embedding()
    ) as contexts:
        memory = (await contexts.get("tags")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=tuple(
                MemoryEntryInput(
                    kind="fact",
                    text=(
                        f"Alpha sensor reading {i}."
                        if i < 47
                        else "Alpha sensor low confidence. " + "Alpha unrelated background. " * 60
                    ),
                )
                for i in range(48)
            ),
            mode="append",
        )
        assert head is not None
        entries = await memory.entries(head)
        selected = next(entry for entry in entries if "low confidence" in entry.text)
        target = MemoryEntryTagTarget(artifact_id=head.artifact_id, entry_id=selected.entry_id)
        empty = await contexts.records.get_tags("tags", target)
        await contexts.records.replace_tags("tags", target, ("selected", "calibrated"), expected_etag=empty.etag)
        tag_filter = TagFilter(tags=("selected", "calibrated"), match=match)
        result = await memory.search("alpha sensor", memories=(head,), mode="hybrid", limit=1, tag_filter=tag_filter)
        assert [h.entry_id for h in result.hits] == [selected.entry_id]
        assert result.hits[0].matched_by == ("fts", "vector")
