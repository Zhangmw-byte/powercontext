# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Lifecycle retry, isolation, native Topic eligibility, and exact history."""

import sqlite3

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.records import ArtifactWrite
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    GetTopicMemoryRequest,
    RememberMemoryRequest,
    SearchTopicMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleError, SourceLifecycleEvent
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceRef


def _event(**changes):
    fields = {"node_id": "root", "revision": 3, "sequence": 1, "available": False, "reason": "withdrawn"}
    return SourceLifecycleEvent(**(fields | changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"node_id": " "},
        {"node_id": 1},
        {"reason": "\t"},
        {"reason": False},
        {"revision": True},
        {"revision": "3"},
        {"revision": 1.0},
        {"revision": 0},
        {"sequence": True},
        {"sequence": "1"},
        {"sequence": 1.0},
        {"sequence": -1},
        {"available": 1},
        {"available": "false"},
        {"extra": True},
    ],
)
def test_event_fields_are_strict_and_extra_fields_fail(changes):
    with pytest.raises(ValidationError):
        _event(**changes)


async def _build(runtime, name="one"):
    sid = (await runtime.scopes.create(ScopeDraft(title=name, summary="evidence", idempotency_key=name))).scope_id
    life = runtime.lifecycle.for_scope(sid)
    source = (
        await runtime.sources.for_scope(sid).capture(
            CaptureSource(source_id="raw", content="raw evidence", metadata={})
        )
    ).source_ref
    await life.register_source("root", source, revision=3)
    citations = {}
    for name in ("a", "b"):
        result = await runtime.memory.for_scope(sid).remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=f"{name} independent evidence"),))
        )
        citations[name] = result.entry.citation
        await life.register_memory(name, result.entry.citation, parents=("root",), policy="all")
    return sid, life, source, citations


async def _topic(runtime, sid, life, node, *, parents=("a",)):
    created = await runtime.records.for_scope(sid).create_artifact(
        "topic-memory",
        ArtifactWrite(
            content={
                "title": "lifecycle topic",
                "summary": f"{node} evidence summary",
                "detail": f"{node} exact historical detail",
            }
        ),
    )
    ref = ArtifactRef(family="topic-memory", artifact_id=created.artifact_id, revision=created.revision)
    await life.register_topic(node, ref, parents=parents, policy="all")
    return ref


async def test_registration_references_parents_and_bindings_are_validated():
    async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
        sid, life, source, citations = await _build(runtime)
        before = (await runtime.memory.for_scope(sid).list()).memory_ref
        await life.register_source("root", source, revision=3)
        await life.register_memory("a", citations["a"], parents=("root",), policy="all")
        assert (await runtime.memory.for_scope(sid).list()).memory_ref == before
        with pytest.raises(SourceLifecycleError):
            await life.register_source("missing", SourceRef(source_type="content", source_id="absent"))
        for parents, policy in [(("absent",), "all"), (("root", "root"), "any"), (("root",), "invalid")]:
            with pytest.raises(SourceLifecycleError):
                await life.register_memory("bad", citations["a"], parents=parents, policy=policy)
        with pytest.raises(SourceLifecycleError):
            await life.register_source("root", source, revision=4)
        await life.register_source("other", source, revision=3)
        await life.register_memory("ordered", citations["a"], parents=("root", "other"), policy="all")
        await life.register_memory("ordered", citations["a"], parents=("other", "root"), policy="all")
        with pytest.raises(SourceLifecycleError):
            await life.apply(_event(node_id="a"))
        for purpose in ("unknown", ""):
            with pytest.raises(SourceLifecycleError):
                await life.resolve("a", purpose=purpose)


async def test_same_ids_in_different_scopes_are_independent_and_replay_has_no_revision():
    async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
        left, life, _, references = await _build(runtime, "left")
        right, other, _, _ = await _build(runtime, "right")
        await life.apply(_event())
        assert not (await runtime.memory.for_scope(left).list()).entries
        assert len((await runtime.memory.for_scope(right).list()).entries) == 2
        assert await other.resolve("a", purpose="generation")
        before = (await runtime.memory.for_scope(left).list()).memory_ref
        await life.apply(_event())
        assert (await runtime.memory.for_scope(left).list()).memory_ref == before
        with pytest.raises(SourceLifecycleError):
            await life.apply(_event(reason="different content at the same sequence"))
        assert await life.resolve("a", purpose="audit") == references["a"]
        assert await life.apply(_event(sequence=2, available=True)) == ["a", "b", "root"]


async def test_topic_browse_vector_search_and_exact_reads_obey_eligibility(tmp_path):
    from powercontext.builtin.artifacts.memory import EmbeddingProfile
    from powercontext.builtin.inference import EmbeddingResult
    from powercontext.builtin.runtime.composition import open_builtin_contexts

    class Embedding:
        profile = EmbeddingProfile(profile_id="lifecycle-vector", model="offline", dimension=2)

        async def embed(self, texts):
            return EmbeddingResult(vectors=tuple((1.0, 0.0) for _ in texts))

    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'topics.db'}"))
    async with open_builtin_runtime(config, embedding_model=Embedding()) as runtime:
        sid, life, _, _ = await _build(runtime)
        ref = await _topic(runtime, sid, life, "topic")
        await life.apply(_event())
        topics = runtime.topic_memory.for_scope(sid)
        assert await topics.browse(limit=20) == ()
        assert not (await topics.search(SearchTopicMemoryRequest(query="lifecycle", limit=1))).hits
        exact = await topics.get(GetTopicMemoryRequest(artifact=ref))
        assert exact.topic.content.detail == "topic exact historical detail"
        assert await life.resolve("topic", purpose="audit") == ref
    async with open_builtin_contexts(config, embedding_model=Embedding()) as contexts:
        result = await contexts.search_topic_memories(
            sid, "lifecycle", limit=1, mode="vector", query_vector=(1.0, 0.0), embedding_profile=Embedding.profile
        )
        assert result.hits == ()
    async with open_builtin_runtime(config, embedding_model=Embedding()) as runtime:
        await runtime.lifecycle.for_scope(sid).apply(_event(sequence=2, available=True))
        assert len(await runtime.topic_memory.for_scope(sid).browse(limit=20)) == 1
        assert await runtime.lifecycle.for_scope(sid).resolve("topic") == ref


@pytest.mark.parametrize("restart", [False, True])
async def test_actual_storage_failure_mid_propagation_retries_without_duplicate_revisions(tmp_path, restart):
    database = tmp_path / "interrupted.db"
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{database}"))
    async with open_builtin_runtime(config) as runtime:
        sid, life, _, refs = await _build(runtime)
        before = (await runtime.memory.for_scope(sid).list()).memory_ref.revision
        with sqlite3.connect(database) as connection:
            connection.executescript("""
                CREATE TABLE lifecycle_failure_count(n INTEGER);
                INSERT INTO lifecycle_failure_count VALUES(0);
                CREATE TRIGGER lifecycle_fail_second BEFORE INSERT ON pc_artifacts
                WHEN NEW.family = 'memory'
                BEGIN
                    UPDATE lifecycle_failure_count SET n = n + 1;
                    SELECT CASE WHEN (SELECT n FROM lifecycle_failure_count) = 2
                    THEN RAISE(ABORT, 'controlled lifecycle interruption') END;
                END;
            """)
        with pytest.raises(IntegrityError):
            await life.apply(_event())
        page = await runtime.memory.for_scope(sid).list(include_inactive=True)
        assert sorted(row.state for row in page.entries) == ["active", "inactive"]
        assert page.memory_ref.revision == before + 1
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TRIGGER lifecycle_fail_second")
        if not restart:
            await life.apply(_event())
            assert not (await runtime.memory.for_scope(sid).list()).entries
            assert (await runtime.memory.for_scope(sid).list()).memory_ref.revision == before + 2
    async with open_builtin_runtime(config) as runtime:
        life = runtime.lifecycle.for_scope(sid)
        await life.apply(_event())
        assert not (await runtime.memory.for_scope(sid).list()).entries
        assert (await runtime.memory.for_scope(sid).list()).memory_ref.revision == before + 2
        await life.apply(_event())
        assert (await runtime.memory.for_scope(sid).list()).memory_ref.revision == before + 2
        await life.apply(_event(sequence=2, available=True))
        assert len((await runtime.memory.for_scope(sid).list()).entries) == 2
        for name, citation in refs.items():
            assert await life.resolve(name) == citation
            original = await runtime.memory.for_scope(sid).get(GetMemoryEntryRequest(citation=citation))
            assert original.entry.text == f"{name} independent evidence"
