"""End-to-end tests against a real PowerContext Server (SQLite backend)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from tests.conftest import PowerContextServer, _free_port

PLAYER = "hero-001"

MULTI_LINE_REPLY = (
    "管理员压低声音：“契约已生效。”\n"
    "她把刻着『月光钥匙』的木牌挂上第三排书架。\n"
    "1. 追问暗号的来历\n"
    "2. 前往禁止区入口"
)


async def _commit(client: httpx.AsyncClient, turn_no: int, action: str, reply: str, revision=None):
    body = {"player_id": PLAYER, "turn_no": turn_no, "action": action, "reply": reply}
    if revision is not None:
        body["expected_revision"] = revision
    return await client.post("/v1/turns/commit", json=body)


async def _prepare(client: httpx.AsyncClient, turn_no: int, action: str, player: str = PLAYER):
    return await client.post(
        "/v1/turns/prepare", json={"player_id": player, "turn_no": turn_no, "action": action}
    )


async def test_healthz(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["powercontext_readiness"] == "ready"


async def test_prepare_on_fresh_player_does_not_write(client: httpx.AsyncClient) -> None:
    prepared = await _prepare(client, 1, "寄存一把生锈的钥匙")
    assert prepared.status_code == 200
    body = prepared.json()
    assert body["scope_exists"] is False
    assert body["revision"] == 0
    assert body["saved_result"] is None
    assert "无历史记录" in body["history_context"]
    # reading must not have created a story record or scope
    memory = await client.get(f"/v1/players/{PLAYER}/memory")
    assert memory.json()["scope_exists"] is False
    assert memory.json()["turn_count"] == 0


async def test_commit_persists_chinese_quotes_and_multiline(client: httpx.AsyncClient) -> None:
    prepared = (await _prepare(client, 1, "寄存一把生锈的钥匙")).json()
    committed = await _commit(
        client, 1, "寄存一把生锈的钥匙", MULTI_LINE_REPLY, prepared["revision"]
    )
    assert committed.status_code == 200
    body = committed.json()
    assert body["status"] == "committed"
    assert body["replayed"] is False
    assert body["reply"] == MULTI_LINE_REPLY
    assert body["sdk_call"] == "remember_memory"
    assert body["citation"]["entry_id"]

    memory = (await client.get(f"/v1/players/{PLAYER}/memory")).json()
    assert memory["turn_count"] == 1
    assert memory["turns"][0]["action"] == "寄存一把生锈的钥匙"
    assert memory["turns"][0]["reply"] == MULTI_LINE_REPLY


async def test_prepare_exposes_saved_history(client: httpx.AsyncClient) -> None:
    await _commit(client, 1, "约定暗号“夜莺”", "管理员记下了暗号。")
    prepared = (await _prepare(client, 2, "说出暗号试试")).json()
    assert prepared["scope_exists"] is True
    assert prepared["revision"] >= 1
    assert "夜莺" in prepared["history_context"]
    assert prepared["known_turns"] == [1]


async def test_duplicate_turn_same_action_returns_saved_result(client: httpx.AsyncClient) -> None:
    reply = "第 3 排书架亮起微光。“暗号确认。”"
    await _commit(client, 2, "约定暗号“夜莺”", reply)
    replay = await _commit(client, 2, "约定暗号“夜莺”", reply)
    assert replay.status_code == 200
    body = replay.json()
    assert body["status"] == "already_committed"
    assert body["replayed"] is True
    assert body["reply"] == reply
    memory = (await client.get(f"/v1/players/{PLAYER}/memory")).json()
    assert memory["turn_count"] == 1


async def test_same_turn_number_different_action_rejected(client: httpx.AsyncClient) -> None:
    await _commit(client, 1, "寄存火焰剑", "管理员收下了火焰剑。")
    conflict = await _commit(client, 1, "寄存寒冰盾", "不该写入。")
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "turn_conflict"
    memory = (await client.get(f"/v1/players/{PLAYER}/memory")).json()
    assert memory["turn_count"] == 1
    assert memory["turns"][0]["action"] == "寄存火焰剑"


async def test_out_of_order_turn_rejected(client: httpx.AsyncClient) -> None:
    await _commit(client, 2, "进入内廊", "门缓缓打开。")
    stale = await _commit(client, 1, "回到大厅", "不该写入。")
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "out_of_order_turn"


async def test_stale_expected_revision_rejected(client: httpx.AsyncClient) -> None:
    prepared = (await _prepare(client, 1, "寄存提灯")).json()
    await _commit(client, 1, "寄存提灯", "提灯上架。")
    await _commit(client, 2, "点亮提灯", "光晕扩散。")
    second_commit = await _commit(
        client, 3, "循光而行", "走廊显现。", prepared["revision"]
    )
    assert second_commit.status_code == 409
    assert second_commit.json()["detail"]["code"] == "stale_revision"


async def test_players_are_isolated(client: httpx.AsyncClient) -> None:
    await _commit(client, 1, "寄存火焰剑", "管理员收下了火焰剑。")
    other = await _prepare(client, 1, "寄存寒冰盾", player="hero-002")
    assert other.json()["scope_exists"] is False
    assert "无历史记录" in other.json()["history_context"]
    other_memory = (await client.get("/v1/players/hero-002/memory")).json()
    assert other_memory["turn_count"] == 0
    mine = (await client.get(f"/v1/players/{PLAYER}/memory")).json()
    assert mine["turn_count"] == 1


async def test_concurrent_same_turn_writes_exactly_once(client: httpx.AsyncClient) -> None:
    prepared = (await _prepare(client, 1, "同步寄存两把剑")).json()
    results = await asyncio.gather(
        *(
            _commit(client, 1, "同步寄存两把剑", "两把剑并排上架。", prepared["revision"])
            for _ in range(5)
        )
    )
    assert all(r.status_code == 200 for r in results)
    statuses = [r.json()["status"] for r in results]
    assert statuses.count("committed") == 1
    memory = (await client.get(f"/v1/players/{PLAYER}/memory")).json()
    assert memory["turn_count"] == 1


async def test_concurrent_conflicting_turn_rejects_later_writer(client: httpx.AsyncClient) -> None:
    first, second = await asyncio.gather(
        _commit(client, 1, "寄存火焰剑", "火焰剑上架。"),
        _commit(client, 1, "寄存寒冰盾", "寒冰盾不该上架。"),
    )
    codes = sorted([first.status_code, second.status_code])
    assert codes == [200, 409]
    memory = (await client.get(f"/v1/players/{PLAYER}/memory")).json()
    assert memory["turn_count"] == 1


async def test_history_window_limits_context_but_keeps_archive(
    client_on_home, pcx_home
) -> None:
    server = PowerContextServer(pcx_home, _free_port())
    server.start()
    try:
        async with client_on_home(server.url, window=2) as scoped_client:
            for turn in range(1, 5):
                response = await _commit(
                    scoped_client, turn, f"第{turn}次行动", f"第{turn}次回应“{turn}”"
                )
                assert response.status_code == 200
            prepared = (await _prepare(scoped_client, 5, "下一次行动")).json()
            assert "第 3 回合" in prepared["history_context"]
            assert "第 4 回合" in prepared["history_context"]
            assert "第 2 回合" not in prepared["history_context"]
            assert "更早的 2 个回合仍完整保存在存档中" in prepared["history_context"]
            memory = (await scoped_client.get(f"/v1/players/{PLAYER}/memory")).json()
            assert memory["turn_count"] == 4
    finally:
        server.stop()


async def test_restart_recovery(client_on_home, pcx_home) -> None:
    server = PowerContextServer(pcx_home, _free_port())
    server.start()
    try:
        async with client_on_home(server.url) as scoped_client:
            await _commit(scoped_client, 1, "约定暗号“夜莺”", MULTI_LINE_REPLY)
    finally:
        server.stop()

    restarted = PowerContextServer(pcx_home, _free_port())
    restarted.start()
    try:
        async with client_on_home(restarted.url) as scoped_client:
            memory = (await scoped_client.get(f"/v1/players/{PLAYER}/memory")).json()
            assert memory["turn_count"] == 1
            assert memory["turns"][0]["reply"] == MULTI_LINE_REPLY
            prepared = (await _prepare(scoped_client, 2, "说出暗号")).json()
            assert "夜莺" in prepared["history_context"]
            assert prepared["revision"] >= 1
    finally:
        restarted.stop()


async def test_invalid_inputs_rejected(client: httpx.AsyncClient) -> None:
    bad_prepare = await client.post(
        "/v1/turns/prepare", json={"player_id": "bad id/!!", "turn_no": 1, "action": "x"}
    )
    assert bad_prepare.status_code == 400
    zero_turn = await client.post(
        "/v1/turns/prepare", json={"player_id": PLAYER, "turn_no": 0, "action": "x"}
    )
    assert zero_turn.status_code == 422
    empty_reply = await client.post(
        "/v1/turns/commit",
        json={"player_id": PLAYER, "turn_no": 1, "action": "x", "reply": ""},
    )
    assert empty_reply.status_code == 422


async def test_healthz_reports_backend_down(client_on_home) -> None:
    async with client_on_home("http://127.0.0.1:1") as dead_client:
        response = await dead_client.get("/healthz")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "powercontext_unreachable"
