"""PowerContext 记忆持久化层。

本文件是项目与 ``powercontext[builtin]==1.2.0`` 真实公开 API 的唯一交互点。
学习者注册表、学习偏好、学习记录、复习结果全部落到 SQLite 文件后端,
服务重启后仍可读取。所有方法均为 async。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from powercontext.builtin.artifacts.memory import Memory, MemoryEntryInput, MemoryEntryVersion
from powercontext.builtin.artifacts.memory.service import MemoryService
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import open_builtin_contexts
from powercontext.builtin.runtime.config import BuiltinConfig
from powercontext.errors import ArtifactNotFoundError

from app import review
from app.models import (
    KIND_LEARNER,
    KIND_PREFERENCE,
    KIND_RECORD,
    PreferenceIn,
    RecordIn,
    ReviewResultIn,
    decode_payload,
    encode_payload,
)

MEMORY_ARTIFACT_ID = "memory"
REGISTRY_SCOPE_ID = "study-coach-registry"


def learner_scope_id(learner_id: str) -> str:
    return f"learner-{learner_id}"


def _active_versions(mem: Memory, versions: tuple[MemoryEntryVersion, ...]) -> list[MemoryEntryVersion]:
    """按 manifest 的 state 过滤,只保留 active 条目(forget 会置 inactive)。"""
    state_by_id = {item.entry_id: item.state for item in mem.content.manifest.entries}
    return [v for v in versions if state_by_id.get(v.entry_id, "active") == "active"]


@dataclass
class StoredEntry:
    version: MemoryEntryVersion
    payload: dict[str, Any]


class StudyCoachStore:
    """持有 RelationalContexts,提供按 scope 的记忆读写用例。"""

    def __init__(self, contexts: Any) -> None:
        self._contexts = contexts

    async def _memory(self, scope_id: str) -> MemoryService:
        ctx = await self._contexts.get(scope_id)
        return ctx.artifacts.memory

    async def _head_entries(
        self, ms: MemoryService
    ) -> tuple[Memory | None, list[StoredEntry]]:
        try:
            mem, versions = await ms.head_entries(MEMORY_ARTIFACT_ID)
        except ArtifactNotFoundError:
            return None, []
        active = _active_versions(mem, versions)
        return mem, [StoredEntry(v, decode_payload(v.text)) for v in active]

    # ------------------------------------------------------------------ #
    # 学习者注册表(本身也持久化,可重启恢复)
    # ------------------------------------------------------------------ #
    async def list_learners(self) -> list[dict[str, Any]]:
        ms = await self._memory(REGISTRY_SCOPE_ID)
        _, entries = await self._head_entries(ms)
        learners = [
            e.payload
            for e in entries
            if e.payload.get("kind") == KIND_LEARNER
        ]
        learners.sort(key=lambda p: p.get("learner_id", ""))
        return learners

    async def add_learner(self, learner_id: str, name: str) -> dict[str, Any]:
        ms = await self._memory(REGISTRY_SCOPE_ID)
        payload = {"kind": KIND_LEARNER, "learner_id": learner_id, "name": name}
        mem, entries = await self._head_entries(ms)
        existing = next(
            (e for e in entries if e.payload.get("learner_id") == learner_id), None
        )
        if existing is not None:
            if existing.payload == payload:
                return payload  # 内容相同,幂等:不写新版本
            entry = await ms.remember(
                memory=mem,
                mode="append",
                entries=[MemoryEntryInput(kind=KIND_LEARNER, text=encode_payload(payload), entry=existing.version)],
            )
            del entry
        else:
            await ms.remember(
                memory=mem,
                mode="append",
                entries=[MemoryEntryInput(kind=KIND_LEARNER, text=encode_payload(payload))],
            )
        return payload

    async def get_learner(self, learner_id: str) -> dict[str, Any] | None:
        for learner in await self.list_learners():
            if learner.get("learner_id") == learner_id:
                return learner
        return None

    # ------------------------------------------------------------------ #
    # 学习偏好
    # ------------------------------------------------------------------ #
    async def get_preference(self, learner_id: str) -> dict[str, Any] | None:
        ms = await self._memory(learner_scope_id(learner_id))
        _, entries = await self._head_entries(ms)
        pref = next((e.payload for e in entries if e.payload.get("kind") == KIND_PREFERENCE), None)
        return pref

    async def put_preference(self, learner_id: str, preference: PreferenceIn) -> dict[str, Any]:
        ms = await self._memory(learner_scope_id(learner_id))
        payload = preference.to_payload()
        mem, entries = await self._head_entries(ms)
        existing = next((e for e in entries if e.payload.get("kind") == KIND_PREFERENCE), None)
        if existing is not None:
            if existing.payload == payload:
                return payload  # 重复提交同一偏好,幂等
            await ms.remember(
                memory=mem,
                mode="append",
                entries=[MemoryEntryInput(kind=KIND_PREFERENCE, text=encode_payload(payload), entry=existing.version)],
            )
        else:
            await ms.remember(
                memory=mem,
                mode="append",
                entries=[MemoryEntryInput(kind=KIND_PREFERENCE, text=encode_payload(payload))],
            )
        return payload

    # ------------------------------------------------------------------ #
    # 学习记录
    # ------------------------------------------------------------------ #
    async def add_record(self, learner_id: str, record: RecordIn) -> dict[str, Any]:
        ms = await self._memory(learner_scope_id(learner_id))
        payload = {
            **record.to_payload(),
            "last_review": None,
            "review_count": 0,
            "interval": 0,
            "ease": 2.5,
            "lapses": 0,
        }
        mem, _ = await self._head_entries(ms)
        await ms.remember(
            memory=mem,
            mode="append",
            entries=[MemoryEntryInput(kind=KIND_RECORD, text=encode_payload(payload))],
        )
        return payload

    async def _records(self, ms: MemoryService) -> tuple[Memory | None, list[StoredEntry]]:
        mem, entries = await self._head_entries(ms)
        records = [e for e in entries if e.payload.get("kind") == KIND_RECORD]
        return mem, records

    async def list_records(self, learner_id: str) -> list[dict[str, Any]]:
        ms = await self._memory(learner_scope_id(learner_id))
        _, records = await self._records(ms)
        out: list[dict[str, Any]] = []
        for r in records:
            payload = {k: v for k, v in r.payload.items() if k not in ("_v", "_last_result")}
            out.append({"_entry_id": r.version.entry_id, "_version": r.version.version, **payload})
        out.sort(key=lambda p: (p.get("course", ""), p.get("topic", "")))
        return out

    # ------------------------------------------------------------------ #
    # 复习结果回写(revise 记录条目,旧版本仍可由 revisions/changes 读取)
    # ------------------------------------------------------------------ #
    async def apply_review_result(self, learner_id: str, result: ReviewResultIn) -> dict[str, Any] | None:
        ms = await self._memory(learner_scope_id(learner_id))
        mem, records = await self._records(ms)
        target = None
        for r in records:
            if r.payload.get("topic") == result.topic:
                if target is None or r.version.created_in_revision > target.version.created_in_revision:
                    target = r
        if target is None:
            return None
        # 幂等:同一 (topic, quality, review_date, mastery) 指纹的重放不再推进 SM-2
        fingerprint = {
            "topic": result.topic,
            "quality": result.quality,
            "review_date": result.review_date,
            "mastery": result.mastery,
        }
        if target.payload.get("_last_result") == fingerprint:
            return {"entry_id": target.version.entry_id, **target.payload, "changed": False}
        new_payload = review.apply_quality(target.payload, result.quality, result.review_date)
        if result.mastery is not None:
            new_payload["mastery"] = result.mastery
        new_payload["_last_result"] = fingerprint
        await ms.remember(
            memory=mem,
            mode="append",
            entries=[MemoryEntryInput(kind=KIND_RECORD, text=encode_payload(new_payload), entry=target.version)],
        )
        return {"entry_id": target.version.entry_id, **new_payload, "changed": True}

    # ------------------------------------------------------------------ #
    # 记忆验证视图 + 历史
    # ------------------------------------------------------------------ #
    async def verification(self, learner_id: str) -> dict[str, Any]:
        scope_id = learner_scope_id(learner_id)
        ms = await self._memory(scope_id)
        try:
            mem, versions = await ms.head_entries(MEMORY_ARTIFACT_ID)
        except ArtifactNotFoundError:
            return {"scope_id": scope_id, "memory_artifact_id": MEMORY_ARTIFACT_ID, "revision": 0, "entry_count": 0, "entries": []}
        state_by_id = {item.entry_id: item.state for item in mem.content.manifest.entries}
        entries = []
        for v in versions:
            entries.append(
                {
                    "entry_id": v.entry_id,
                    "entry_version_id": v.entry_version_id,
                    "version": v.version,
                    "kind": v.kind,
                    "text": v.text,
                    "state": state_by_id.get(v.entry_id, "active"),
                    "created_in_revision": v.created_in_revision,
                    "payload": decode_payload(v.text),
                }
            )
        return {
            "scope_id": scope_id,
            "memory_artifact_id": mem.artifact_id,
            "revision": mem.revision,
            "entry_count": len(entries),
            "entries": entries,
        }

    async def history(self, learner_id: str) -> list[dict[str, Any]]:
        ms = await self._memory(learner_scope_id(learner_id))
        try:
            mem, _ = await ms.head_entries(MEMORY_ARTIFACT_ID)
        except ArtifactNotFoundError:
            return []
        revisions = await ms.revisions(mem)
        change_map = {c.memory_ref.revision: c.changes for c in await ms.changes(mem)}
        snapshots: list[dict[str, Any]] = []
        for rev in revisions:
            versions = await ms.entries(rev)
            snapshots.append(
                {
                    "revision": rev.revision,
                    "changes": [
                        {
                            "op": ch.op,
                            "entry_id": ch.entry_id,
                            "from_entry_version_id": ch.from_entry_version_id,
                            "to_entry_version_id": ch.to_entry_version_id,
                        }
                        for ch in change_map.get(rev.revision, ())
                    ],
                    "entries": [
                        {"entry_id": v.entry_id, "kind": v.kind, "text": v.text, "version": v.version}
                        for v in versions
                    ],
                }
            )
        return snapshots


@asynccontextmanager
async def open_store(db_path: str) -> AsyncIterator[StudyCoachStore]:
    """打开(必要时创建)持久化 store;退出时关闭 DB 所有权,不删数据文件。"""
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{db_path}"))
    async with open_builtin_contexts(config) as contexts:
        yield StudyCoachStore(contexts)
