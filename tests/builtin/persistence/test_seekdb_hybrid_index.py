# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at https://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pyobvector import VECTOR
from sqlalchemy.dialects.mysql import dialect

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import (
    CapabilityNotSupportedError,
    EmbeddingProfile,
    MemorySearchChannels,
    MemorySearchRequest,
)
from powercontext.builtin.persistence.memory_index import CompositeMemoryIndex
from powercontext.builtin.persistence.seekdb.memory_index import SeekDBMemoryIndex
from powercontext.builtin.tags import TagFilter

PROFILE = EmbeddingProfile(profile_id="hybrid-unit-v1", model="test", dimension=3, distance="l2", normalization="unit")
MEMORY = ArtifactRef(family="memory", artifact_id="memory", revision=7)


def _request(**changes):
    return MemorySearchRequest(
        query="alpha",
        analyzed_query="alpha",
        memories=(MEMORY,),
        mode="hybrid",
        query_vector=(1.0, 0.0, 0.0),
        embedding_profile=PROFILE,
        candidate_limit=16,
        **changes,
    )


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self.rows)


class _Connection:
    def __init__(self, rows=()):
        self.rows = rows
        self.calls = []

    async def execute(self, statement, parameters):
        self.calls.append((statement, parameters))
        return _Rows(self.rows)


def _row(channel, entry="one", artifact="memory", revision=2, distance=None):
    return {
        "channel": channel,
        "memory_artifact_id": artifact,
        "head_revision": revision,
        "entry_id": entry,
        "entry_version_id": entry + "-version",
        "text": "Literal " + entry,
        "distance": distance,
        "fts_score": 1.0 if channel == "fts" else None,
    }


@pytest.mark.asyncio
async def test_one_candidate_statement_preserves_separate_channels_and_validated_current_refs(monkeypatch):
    index = SeekDBMemoryIndex(PROFILE)
    monkeypatch.setattr(index, "vector_complete", AsyncMock(return_value=True))
    rows = (
        _row("fts", "one"),
        _row("fts", "two"),
        _row("vector", "one", distance=0.0),
        _row("vector", "three", distance=0.5),
    )
    connection = _Connection(rows)
    result = await index.search(connection, "scope", _request())
    assert len(connection.calls) == 1
    assert [h.entry_id for h in result.fts] == ["one", "two"]
    assert [h.entry_id for h in result.vector] == ["one", "three"]
    assert all(hit.memory_ref == MEMORY for hit in (*result.fts, *result.vector))
    assert result.vector[0].distance == 0.0
    assert result.vector[1].text == "Literal three"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tag_filter",
    [
        None,
        TagFilter(tags=("selected",)),
        TagFilter(tags=("one", "two"), match="all"),
        TagFilter(tags=("one", "two"), match="any"),
    ],
)
async def test_native_branches_bind_filters_and_candidate_limits_before_union(tag_filter, monkeypatch):
    index = SeekDBMemoryIndex(PROFILE)
    monkeypatch.setattr(index, "vector_complete", AsyncMock(return_value=True))
    connection = _Connection()
    request = _request(tag_filter=tag_filter)
    assert await index.search(connection, "scope'quoted", request) == MemorySearchChannels()
    assert len(connection.calls) == 1
    statement, parameters = connection.calls[0]
    sql = str(statement)
    assert sql.count("UNION ALL") == 1 and ";" not in sql
    assert "MATCH(m.searchable_text) AGAINST" in sql
    assert "l2_distance(m.embedding, :query_vector)" in sql
    assert ("APPROXIMATE" in sql) == (tag_filter is None)
    assert sql.count("m.scope_id = :scope_id") == 2
    assert sql.count("m.memory_artifact_id IN") == 2
    assert sql.count("LIMIT :candidate_limit") == 2
    assert "m.head_revision =" not in sql
    assert parameters["scope_id"] == "scope'quoted" and "scope'quoted" not in sql
    assert parameters["candidate_limit"] == 16
    assert parameters["query_vector"] == (1.0, 0.0, 0.0)
    compiled = statement.params(**parameters).compile(dialect=dialect(), compile_kwargs={"render_postcompile": True})
    assert isinstance(compiled.binds["query_vector"].type, VECTOR)
    if tag_filter is None:
        assert "pc_artifact_tags" not in sql
    else:
        assert sql.count("FROM pc_artifact_tags") == 2
        assert parameters["tag_minimum"] == (len(tag_filter.keys) if tag_filter.match == "all" else 1)
        assert parameters["tag_keys"] == tag_filter.keys
        assert all(len(digest) == 32 for digest in parameters["tag_hashes"])


@pytest.mark.asyncio
@pytest.mark.parametrize("vector, profile", [(None, PROFILE), ((1.0, 0.0, 0.0), None)])
async def test_embedding_profile_rejection_precedes_candidate_access(vector, profile):
    index = SeekDBMemoryIndex(PROFILE)
    connection = _Connection()
    request = _request().model_copy(update={"query_vector": vector, "embedding_profile": profile})
    with pytest.raises(CapabilityNotSupportedError, match="embedding-profile"):
        await index.search(connection, "scope", request)
    assert not connection.calls


@pytest.mark.asyncio
async def test_incomplete_embeddings_remain_rejected(monkeypatch):
    index = SeekDBMemoryIndex(PROFILE)
    monkeypatch.setattr(index, "vector_complete", AsyncMock(return_value=False))
    connection = _Connection()
    with pytest.raises(CapabilityNotSupportedError, match="vector"):
        await index.search(connection, "scope", _request())
    assert not connection.calls


@pytest.mark.asyncio
async def test_head_validation_errors_are_not_normalized_to_empty_hits(monkeypatch):
    index = SeekDBMemoryIndex(PROFILE)
    monkeypatch.setattr(index, "vector_complete", AsyncMock(side_effect=CapabilityNotSupportedError("head")))
    connection = _Connection()
    with pytest.raises(CapabilityNotSupportedError, match="head"):
        await index.search(connection, "scope", _request())
    assert not connection.calls


@pytest.mark.asyncio
async def test_multiple_memory_refs_and_empty_channels_keep_exact_identities(monkeypatch):
    second = ArtifactRef(family="memory", artifact_id="second", revision=12)
    index = SeekDBMemoryIndex(PROFILE)
    monkeypatch.setattr(index, "vector_complete", AsyncMock(return_value=True))
    connection = _Connection((_row("vector", artifact="second", distance=0.1),))
    result = await index.search(connection, "scope", _request().model_copy(update={"memories": (MEMORY, second)}))
    assert result.fts == ()
    assert result.vector[0].memory_ref == second
    assert connection.calls[0][1]["memory_artifact_ids"] == ("memory", "second")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fts", "vector"])
async def test_single_channel_searches_delegate_to_existing_implementation(mode, monkeypatch):
    index = SeekDBMemoryIndex(PROFILE)
    original = AsyncMock(return_value=MemorySearchChannels())
    monkeypatch.setattr(CompositeMemoryIndex, "search", original)
    connection = _Connection()
    request = _request().model_copy(update={"mode": mode})
    assert await index.search(connection, "scope", request) == MemorySearchChannels()
    original.assert_awaited_once_with(connection, "scope", request)
    assert not connection.calls
