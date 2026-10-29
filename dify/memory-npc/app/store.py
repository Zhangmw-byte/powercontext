"""PowerContext-backed memory store for the campus-isekai library NPC.

All persistent game state lives in a real PowerContext Server (SQLite
backend) reached through the official ``powercontext`` Python SDK.
Each player owns one PowerContext scope; each committed turn is one
memory entry whose text is a JSON payload.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from powercontext.client import PowerContextClient, ServerResponseError
from powercontext.http._generated.models import (
    CreateScopeRequest,
    GetMemoryCapacityRequest,
    ListMemoryEntriesRequest,
    RememberMemoryRequest,
    ScopeExternalReference,
)

ENTRY_KIND = "npc_turn"
ENTRY_SCHEMA_VERSION = 1
PLAYER_REF_KIND = "npc-memory-player"
SCOPE_SUMMARY = "校园异世界图书馆 NPC 记忆存档"
PLAYER_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class MemoryServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class Turn:
    turn_no: int
    action: str
    reply: str
    committed_at: str
    entry_version: int


@dataclass(frozen=True)
class PlayerArchive:
    scope_id: str
    revision: int
    turns: tuple[Turn, ...]


def _validate_player_id(player_id: str) -> str:
    player_id = player_id.strip()
    if not PLAYER_ID_RE.match(player_id):
        raise MemoryServiceError(
            "invalid_player_id",
            "player_id 只能包含字母、数字、下划线、点、冒号、短横线，长度 1-64",
        )
    return player_id


def _entry_payload(turn_no: int, action: str, reply: str) -> str:
    return json.dumps(
        {
            "schema_version": ENTRY_SCHEMA_VERSION,
            "turn_no": turn_no,
            "action": action,
            "reply": reply,
            "committed_at": datetime.now(timezone.utc).isoformat(),
        },
        ensure_ascii=False,
    )


def _parse_entry(text: str) -> Turn | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("schema_version") != ENTRY_SCHEMA_VERSION:
        return None
    try:
        return Turn(
            turn_no=int(data["turn_no"]),
            action=str(data["action"]),
            reply=str(data["reply"]),
            committed_at=str(data.get("committed_at", "")),
            entry_version=0,
        )
    except (KeyError, TypeError, ValueError):
        return None


class MemoryStore:
    def __init__(self, client: PowerContextClient) -> None:
        self._client = client
        self._player_locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _player_lock(self, player_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._player_locks.get(player_id)
            if lock is None:
                lock = asyncio.Lock()
                self._player_locks[player_id] = lock
            return lock

    async def _find_scope(self, player_id: str) -> str | None:
        cursor: str | None = None
        while True:
            page = await self._client.list_scopes(
                external_reference_kind=PLAYER_REF_KIND, limit=100, cursor=cursor
            )
            for scope in page.items:
                for ref in scope.external_references:
                    if ref.kind == PLAYER_REF_KIND and ref.value == player_id:
                        return scope.scope_id
            if page.next_cursor is None:
                return None
            cursor = page.next_cursor

    async def _get_or_create_scope(self, player_id: str) -> str:
        existing = await self._find_scope(player_id)
        if existing is not None:
            return existing
        request = CreateScopeRequest(
            title=f"player:{player_id}",
            summary=SCOPE_SUMMARY,
            idempotency_key=f"{PLAYER_REF_KIND}:{player_id}",
            external_references=[
                ScopeExternalReference(kind=PLAYER_REF_KIND, value=player_id)
            ],
        )
        try:
            scope = await self._client.create_scope(request)
            return scope.scope_id
        except ServerResponseError as error:
            if error.code == "scope_idempotency_conflict":
                raced = await self._find_scope(player_id)
                if raced is not None:
                    return raced
            raise

    async def _load_turns(self, scope_id: str) -> tuple[Turn, ...]:
        try:
            response = await self._client.list_memory_entries(
                ListMemoryEntriesRequest(scope_id=scope_id, include_inactive=False)
            )
        except ServerResponseError as error:
            if error.code == "artifact_not_found":
                return ()
            raise
        turns: list[Turn] = []
        for entry in response.entries:
            if entry.kind != ENTRY_KIND:
                continue
            turn = _parse_entry(entry.text)
            if turn is not None:
                turns.append(
                    Turn(
                        turn_no=turn.turn_no,
                        action=turn.action,
                        reply=turn.reply,
                        committed_at=turn.committed_at,
                        entry_version=entry.version,
                    )
                )
        turns.sort(key=lambda t: t.turn_no)
        return tuple(turns)

    async def _current_revision(self, scope_id: str) -> int:
        try:
            capacity = await self._client.get_memory_capacity(
                GetMemoryCapacityRequest(scope_id=scope_id)
            )
        except ServerResponseError as error:
            if error.code == "artifact_not_found":
                return 0
            raise
        return capacity.memory_ref.revision

    async def read_archive(self, player_id: str) -> PlayerArchive | None:
        """Read-only archive lookup. Never creates a scope or an entry."""
        player_id = _validate_player_id(player_id)
        scope_id = await self._find_scope(player_id)
        if scope_id is None:
            return None
        turns = await self._load_turns(scope_id)
        revision = await self._current_revision(scope_id)
        return PlayerArchive(scope_id=scope_id, revision=revision, turns=turns)

    def build_context(self, turns: tuple[Turn, ...], window: int) -> str:
        if not turns:
            return "（无历史记录：这是本玩家的第一次互动，没有任何已保存的事件、物品、暗号或选择。）"
        recent = turns[-window:]
        lines = [f"已保存的历史记录（共 {len(turns)} 个回合，以下展示最近 {len(recent)} 个）："]
        for turn in recent:
            lines.append(f"第 {turn.turn_no} 回合")
            lines.append(f"玩家行动：{turn.action}")
            lines.append(f"NPC 回应：{turn.reply}")
        omitted = len(turns) - len(recent)
        if omitted > 0:
            lines.insert(1, f"（更早的 {omitted} 个回合仍完整保存在存档中，此处未送入模型。）")
        return "\n".join(lines)

    async def prepare_turn(
        self, player_id: str, turn_no: int, action: str, window: int
    ) -> dict:
        archive = await self.read_archive(player_id)
        scope_exists = archive is not None
        revision = archive.revision if archive else 0
        turns = archive.turns if archive else ()
        saved = next((t for t in turns if t.turn_no == turn_no), None)
        return {
            "player_id": player_id,
            "scope_exists": scope_exists,
            "revision": revision,
            "turn_no": turn_no,
            "action": action,
            "known_turns": [t.turn_no for t in turns],
            "latest_turn_no": turns[-1].turn_no if turns else 0,
            "history_context": self.build_context(turns, window),
            "saved_result": (
                {
                    "reply": saved.reply,
                    "action_matches": saved.action == action,
                    "committed_at": saved.committed_at,
                    "entry_version": saved.entry_version,
                }
                if saved
                else None
            ),
        }

    async def commit_turn(
        self,
        player_id: str,
        turn_no: int,
        action: str,
        reply: str,
        expected_revision: int | None,
    ) -> dict:
        player_id = _validate_player_id(player_id)
        if turn_no < 1:
            raise MemoryServiceError("invalid_turn_no", "turn_no 必须是从 1 开始的正整数")
        lock = await self._player_lock(player_id)
        async with lock:
            return await self._commit_locked(player_id, turn_no, action, reply, expected_revision)

    async def _commit_locked(
        self,
        player_id: str,
        turn_no: int,
        action: str,
        reply: str,
        expected_revision: int | None,
    ) -> dict:
        scope_id = await self._get_or_create_scope(player_id)

        for _attempt in range(3):
            turns = await self._load_turns(scope_id)
            by_no = {t.turn_no: t for t in turns}
            saved = by_no.get(turn_no)
            if saved is not None:
                if saved.action == action:
                    return {
                        "status": "already_committed",
                        "replayed": True,
                        "reply": saved.reply,
                        "revision": await self._current_revision(scope_id),
                        "citation": {
                            "family": "memory",
                            "entry_version": saved.entry_version,
                            "committed_at": saved.committed_at,
                        },
                        "sdk_call": "list_memory_entries",
                    }
                raise MemoryServiceError(
                    "turn_conflict",
                    f"第 {turn_no} 回合已存在不同行动的存档结果，拒绝覆盖",
                    status_code=409,
                )
            if turns and turn_no <= turns[-1].turn_no:
                raise MemoryServiceError(
                    "out_of_order_turn",
                    f"turn_no 必须大于已保存的最大回合号 {turns[-1].turn_no}",
                    status_code=409,
                )
            revision = await self._current_revision(scope_id)
            if expected_revision is not None and expected_revision != revision:
                raise MemoryServiceError(
                    "stale_revision",
                    f"读取版本 {expected_revision} 已过期，当前版本 {revision}，请重新 prepare",
                    status_code=409,
                )
            try:
                mutation = await self._client.remember_memory(
                    RememberMemoryRequest(
                        scope_id=scope_id,
                        kind=ENTRY_KIND,
                        text=_entry_payload(turn_no, action, reply),
                        expected_revision=None if revision == 0 else revision,
                    )
                )
            except ServerResponseError as error:
                if error.code == "revision_conflict":
                    continue
                raise
            saved_turn = _parse_entry(mutation.entry.text) if mutation.entry else None
            return {
                "status": "committed",
                "replayed": False,
                "reply": saved_turn.reply if saved_turn else reply,
                "revision": await self._current_revision(scope_id),
                "citation": {
                    "family": mutation.memory.family,
                    "artifact_id": mutation.memory.artifact_id,
                    "revision": mutation.memory.revision,
                    "entry_id": mutation.entry.citation.entry_id if mutation.entry else None,
                    "entry_version": mutation.entry.version if mutation.entry else None,
                    "committed_at": saved_turn.committed_at if saved_turn else None,
                },
                "sdk_call": "remember_memory",
            }
        raise MemoryServiceError(
            "revision_conflict", "并发写入导致版本冲突，请重试本回合", status_code=409
        )
