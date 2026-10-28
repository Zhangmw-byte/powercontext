# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Durable evidence DAG eligibility and resumable native Memory transitions."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator
from sqlalchemy import insert, select, update

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.persistence.database import AsyncDatabase
from powercontext.builtin.persistence.sources import SourceRepository
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_NODES_TABLE
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.builtin.sources.journal import validate_scope_id
from powercontext.sources import SourceMaterialization, SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import BuiltinRuntime


class SourceLifecycleError(ValueError):
    """A registration, event, or generation reference violates the lifecycle contract."""

    def __init__(self, issue: str) -> None:
        super().__init__(f"Invalid source lifecycle: {issue}")


def _nonblank(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceLifecycleError("lifecycle-identity-reason-must-be-a-nonblank-string")
    return value


class SourceLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    node_id: str
    revision: int = Field(gt=0)
    sequence: int = Field(gt=0)
    available: bool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        return _nonblank(value)


class _Node(BaseModel):
    kind: Literal["source", "memory", "topic"]
    reference: dict[str, JsonValue]
    parents: tuple[str, ...] = ()
    policy: Literal["all", "any"] = "all"
    revision: int = 1
    available: bool = True
    last_event: SourceLifecycleEvent | None = None

    def binding(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json", exclude={"available", "last_event"})

    def original(self) -> SourceRef | MemoryCitation | ArtifactRef:
        model = {"source": SourceRef, "memory": MemoryCitation, "topic": ArtifactRef}[self.kind]
        return model.model_validate(self.reference)


def _propagate(nodes: dict[str, _Node]) -> None:
    remaining = set(nodes)
    done: set[str] = set()
    while remaining:
        ready = sorted(key for key in remaining if set(nodes[key].parents) <= done)
        if not ready:
            raise SourceLifecycleError("lifecycle-graph-has-a-cycle-or-missing-parent")
        for key in ready:
            node = nodes[key]
            if node.kind != "source":
                parents = [nodes[parent].available for parent in node.parents]
                node.available = all(parents) if node.policy == "all" else any(parents)
            done.add(key)
            remaining.remove(key)


class SourceLifecycleApplication:
    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase, sources: SourceRepository) -> None:
        self.runtime = runtime
        self.database = database
        self.sources = sources
        # The supported deployment has one writer per graph. This lock also
        # serializes separate service handles in this Runtime without a growing
        # per-scope lock registry or holding a DB transaction during Memory work.
        self.lock = asyncio.Lock()

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self, validate_scope_id(scope_id))


class ScopedSourceLifecycle:
    def __init__(self, application: SourceLifecycleApplication, scope_id: str) -> None:
        self._application = application
        self.scope_id = scope_id

    async def _load(self) -> dict[str, _Node]:
        table = SOURCE_LIFECYCLE_NODES_TABLE
        async with self._application.database.transaction() as connection:
            rows = await connection.execute(
                select(table.c.node_id, table.c.payload).where(table.c.scope_id == self.scope_id)
            )
            return {key: _Node.model_validate_json(bytes(payload)) for key, payload in rows}

    async def _save(self, nodes: dict[str, _Node]) -> None:
        table = SOURCE_LIFECYCLE_NODES_TABLE
        async with self._application.database.transaction() as connection:
            for key, node in nodes.items():
                values = {
                    "kind": node.kind,
                    "artifact_id": node.reference.get("artifact_id") if node.kind == "topic" else None,
                    "available": node.available,
                    "payload": node.model_dump_json().encode(),
                }
                found = await connection.scalar(
                    select(table.c.node_id).where(table.c.scope_id == self.scope_id, table.c.node_id == key)
                )
                if found is None:
                    await connection.execute(insert(table).values(scope_id=self.scope_id, node_id=key, **values))
                else:
                    await connection.execute(
                        update(table).where(table.c.scope_id == self.scope_id, table.c.node_id == key).values(**values)
                    )

    async def register_source(self, node_id: str, source_ref: SourceRef, *, revision: int = 1) -> None:
        if type(revision) is not int or revision < 1:
            raise SourceLifecycleError("lifecycle-revision-must-be-a-positive-integer")
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("expected-a-sourceref")
        await self._register(
            node_id, _Node(kind="source", reference=source_ref.model_dump(mode="json"), revision=revision)
        )

    async def register_memory(
        self, node_id: str, citation: MemoryCitation, *, parents: tuple[str, ...], policy: Literal["all", "any"] = "all"
    ) -> None:
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("expected-a-memorycitation")
        await self._register_derivative(node_id, "memory", citation.model_dump(mode="json"), parents, policy)

    async def register_topic(
        self,
        node_id: str,
        artifact_ref: ArtifactRef,
        *,
        parents: tuple[str, ...],
        policy: Literal["all", "any"] = "all",
    ) -> None:
        if not isinstance(artifact_ref, ArtifactRef) or artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("expected-a-topic-memory-artifactref")
        await self._register_derivative(node_id, "topic", artifact_ref.model_dump(mode="json"), parents, policy)

    async def _register_derivative(
        self,
        node_id: str,
        kind: Literal["memory", "topic"],
        reference: dict[str, JsonValue],
        parents: tuple[str, ...],
        policy: Literal["all", "any"],
    ) -> None:
        if (
            not isinstance(policy, str)
            or policy not in {"all", "any"}
            or not isinstance(parents, (tuple, list))
            or not parents
        ):
            raise SourceLifecycleError("derived-nodes-require-parents-and-an-all-any-policy")
        parents = tuple(sorted(_nonblank(parent) for parent in parents))
        if len(set(parents)) != len(parents) or node_id in parents:
            raise SourceLifecycleError("duplicate-parent-or-self-dependency")
        await self._register(node_id, _Node(kind=kind, reference=reference, parents=parents, policy=policy))

    async def _validate_reference(self, node: _Node) -> None:
        runtime = self._application.runtime
        try:
            if node.kind == "source":
                ref = SourceRef.model_validate(node.reference)
                async with self._application.database.transaction() as connection:
                    stored = await self._application.sources.get(connection, self.scope_id, ref)
                if stored.value.materialization is not SourceMaterialization.CAPTURED:
                    raise SourceLifecycleError("source-must-be-captured")
            elif node.kind == "memory":
                await runtime.memory.for_scope(self.scope_id).get(
                    GetMemoryEntryRequest(citation=MemoryCitation.model_validate(node.reference))
                )
            else:
                ref = ArtifactRef.model_validate(node.reference)
                await runtime.records.for_scope(self.scope_id).get_artifact_revision(
                    ref.family, ref.artifact_id, ref.revision
                )
        except (LookupError, ValueError) as error:
            raise SourceLifecycleError("registered-reference-is-not-readable-in-this-scope") from error

    async def _register(self, node_id: str, node: _Node) -> None:
        node_id = _nonblank(node_id)
        async with self._application.runtime._scope_operation(self.scope_id), self._application.lock:
            nodes = await self._load()
            old = nodes.get(node_id)
            if old is not None and old.binding() != node.binding():
                raise SourceLifecycleError("node-identity-is-already-bound-differently")
            if any(parent not in nodes for parent in node.parents):
                raise SourceLifecycleError("parents-must-be-registered-first")
            await self._validate_reference(node)
            if old is None:
                nodes[node_id] = node
                _propagate(nodes)
                await self._save(nodes)
            await self._reconcile(nodes, reason="source lifecycle registration")

    async def apply(self, event: SourceLifecycleEvent) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("expected-a-sourcelifecycleevent")
        async with self._application.runtime._scope_operation(self.scope_id), self._application.lock:
            nodes = await self._load()
            source = nodes.get(event.node_id)
            if source is None or source.kind != "source" or source.revision != event.revision:
                raise SourceLifecycleError("unknown-source-or-mismatched-lifecycle-revision")
            previous = source.last_event
            if previous is not None and (
                event.sequence < previous.sequence or (event.sequence == previous.sequence and event != previous)
            ):
                raise SourceLifecycleError("stale-or-conflicting-lifecycle-event")
            source.last_event = event
            source.available = event.available
            _propagate(nodes)
            # Commit desired eligibility and event identity first. A failed
            # native transition remains retryable with this exact event.
            await self._save(nodes)
            await self._reconcile(nodes, reason=event.reason)
            return sorted(key for key, node in nodes.items() if node.available)

    async def _reconcile(self, nodes: dict[str, _Node], *, reason: str) -> None:
        runtime = self._application.runtime
        for node in nodes.values():
            if node.kind != "memory":
                continue
            citation = MemoryCitation.model_validate(node.reference)
            async with runtime._context(self.scope_id) as context, runtime._locked(self.scope_id):
                service = context.artifacts.memory
                current = await service.head(context.artifacts.memory_artifact_id)
                item = next(
                    (item for item in current.content.manifest.entries if item.entry_id == citation.entry_id), None
                )
                if item is None or item.entry_version_id != citation.entry_version_id:
                    raise SourceLifecycleError("registered-memory-body-version-changed")
                if (item.state == "active") == node.available:
                    continue
                entry = next(entry for entry in await service.entries(current) if entry.entry_id == citation.entry_id)
                transition = service.reactivate if node.available else service.forget
                await transition(current, entries=(entry,), reason=reason)

    async def resolve(self, node_id: str, *, purpose: str = "generation") -> SourceRef | MemoryCitation | ArtifactRef:
        if not isinstance(purpose, str) or purpose not in {"generation", "audit"}:
            raise SourceLifecycleError("unknown-lifecycle-reference-purpose")
        async with self._application.runtime._scope_operation(self.scope_id), self._application.lock:
            node = (await self._load()).get(_nonblank(node_id))
            if node is None or (purpose == "generation" and not node.available):
                raise SourceLifecycleError("node-is-unknown-or-unavailable-for-generation")
            return node.original()


__all__ = ["SourceLifecycleError", "SourceLifecycleEvent"]
