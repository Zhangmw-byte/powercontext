"""PowerContext 状态层：任务进展 / 待办 / 验证结果 的保存与复用。

使用 PowerContext 1.4.1 的显式 Memory（无需配置生成/embedding 模型）：
- 一个 Scope 对应一个交付任务的上下文空间；
- 每次保存写入一条 kind="state" 的显式 Memory，正文为 ``SDD_STATE_V1:{json}``；
- 读取时列出该 Scope 的 active Memory，取最新 revision 的状态记录。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from powercontext.client import PowerContextClient
from powercontext.http import CreateScopeRequest, ListMemoryEntriesRequest, RememberMemoryRequest

STATE_MARKER = "SDD_STATE_V1:"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _ensure_scope_async(url: str, scope_file: Path, title: str, fresh: bool) -> dict:
    if scope_file.exists() and not fresh:
        try:
            record = json.loads(scope_file.read_text(encoding="utf-8"))
            async with PowerContextClient(url) as client:
                scope = await client.get_scope(record["scope_id"])
            record["title"] = getattr(scope, "title", record.get("title", title))
            return record
        except Exception:
            pass  # scope 不存在或服务不可用 → 重新创建

    async with PowerContextClient(url) as client:
        scope = await client.create_scope(
            CreateScopeRequest(
                title=title,
                summary="SDD 上下文管理系统的任务状态空间",
                idempotency_key=f"sdd-context-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            )
        )
    record = {
        "scope_id": scope.scope_id,
        "title": title,
        "powercontext_url": url,
        "created_at": _now_iso(),
    }
    scope_file.parent.mkdir(parents=True, exist_ok=True)
    scope_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def ensure_scope(url: str, scope_file: Path, title: str = "SDD 上下文任务", fresh: bool = False) -> dict:
    return _run(_ensure_scope_async(url, scope_file, title, fresh))


async def _save_state_async(url: str, scope_id: str, state: dict) -> dict:
    state = dict(state)
    state["updated_at"] = _now_iso()
    text = STATE_MARKER + json.dumps(state, ensure_ascii=False)
    async with PowerContextClient(url) as client:
        response = await client.remember_memory(
            RememberMemoryRequest(
                scope_id=scope_id,
                kind="state",
                text=text,
                reason="SDD 上下文模块保存任务进展",
            )
        )
    record = response.records[0] if getattr(response, "records", None) else None
    return {
        "artifact_id": getattr(getattr(record, "artifact", None), "artifact_id", None),
        "revision": getattr(getattr(record, "artifact", None), "revision", None),
        "changed": getattr(response, "changed", None),
        "saved_at": _now_iso(),
    }


def save_state(url: str, scope_id: str, state: dict) -> dict:
    return _run(_save_state_async(url, scope_id, state))


async def _load_state_async(url: str, scope_id: str) -> dict | None:
    async with PowerContextClient(url) as client:
        entries = await client.list_memory_entries(
            ListMemoryEntriesRequest(scope_id=scope_id, limit=100)
        )
    records = getattr(entries, "entries", None) or []
    candidates = []
    for record in records:
        text = getattr(record, "text", "") or ""
        if not text.startswith(STATE_MARKER):
            continue
        artifact = getattr(record, "artifact", None)
        revision = getattr(artifact, "revision", 0) or 0
        try:
            payload = json.loads(text[len(STATE_MARKER) :])
        except json.JSONDecodeError:
            continue
        candidates.append((revision, payload, record))
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            str(item[1].get("updated_at") or ""),
            len(item[1].get("verifications") or []),
            item[0],
        )
    )
    revision, payload, record = candidates[-1]
    payload = dict(payload)
    payload["_powercontext"] = {
        "scope_id": scope_id,
        "artifact_id": getattr(getattr(record, "artifact", None), "artifact_id", None),
        "revision": revision,
        "url": url,
    }
    return payload


def load_state(url: str, scope_id: str) -> dict | None:
    return _run(_load_state_async(url, scope_id))


def record_test_result(
    url: str,
    scope_id: str,
    *,
    name: str,
    command: str,
    exit_code: int,
    passed: bool,
    code_sha: str,
) -> dict:
    """把测试结果合并进状态并保存（用于“验证结果复用”）。"""
    state = load_state(url, scope_id) or {
        "task": "订单列表增加状态筛选与分页",
        "done": [],
        "todo": [],
        "verifications": [],
    }
    state.setdefault("verifications", []).append(
        {
            "name": name,
            "command": command,
            "exit_code": exit_code,
            "passed": bool(passed),
            "code_sha": code_sha,
            "recorded_at": _now_iso(),
        }
    )
    saved = save_state(url, scope_id, state)
    state["_saved"] = saved
    return state

def update_state_fields(
    url: str,
    scope_id: str,
    *,
    task: str | None = None,
    done: list[str] | None = None,
    todo: list[str] | None = None,
) -> dict:
    """更新已完成 / 待办等字段，保留已有验证结果。"""
    state = load_state(url, scope_id) or {
        "task": "订单列表增加状态筛选与分页",
        "done": [],
        "todo": [],
        "verifications": [],
    }
    if task is not None:
        state["task"] = task
    if done is not None:
        state["done"] = list(done)
    if todo is not None:
        state["todo"] = list(todo)
    saved = save_state(url, scope_id, state)
    state["_saved"] = saved
    return state
