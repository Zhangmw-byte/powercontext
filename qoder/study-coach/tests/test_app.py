"""复习记忆助手 — 集成测试。

每个测试使用独立的临时 SQLite 数据库(通过 STUDY_COACH_DB 环境变量指定),
绝不触碰用户已有数据。覆盖:真实写入、重启恢复、学习者隔离、偏好影响清单、
薄弱优先、复习结果回写与历史、幂等去重、非法字段拒绝、中文保存与回查。
"""

from __future__ import annotations

import socket
import tempfile
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.app import app
from app import review


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_coach.db")


@pytest.fixture()
def client(db_path: str, monkeypatch):
    monkeypatch.setenv("STUDY_COACH_DB", db_path)
    with TestClient(app) as c:
        yield c


def _mk(client, lid="a", name="小明"):
    return client.post("/api/learners", json={"learner_id": lid, "name": name})


# --------------------------------------------------------------------------- #
def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_learner_and_record_persist(client, db_path):
    assert _mk(client).status_code == 201
    assert client.put("/api/learners/a/preference", json={"daily_minutes": 30, "goal": "期中"}).status_code == 200
    rec = {"course": "数学", "topic": "分数", "note": "通分", "mastery": 1, "studied_on": "2026-10-01"}
    assert client.post("/api/learners/a/records", json=rec).status_code == 201

    # 记忆验证视图确认真实写入(带 scope/revision/正文)
    ver = client.get("/api/learners/a/memory").json()
    assert ver["scope_id"] == "learner-a"
    assert ver["revision"] >= 2
    texts = [e["text"] for e in ver["entries"]]
    assert any("分数" in t for t in texts)
    assert any("通分" in t for t in texts)  # 中文正文回查正确

    # 重启:关闭 store,重新打开同一 DB 文件
    with TestClient(app) as c2:
        c2.app  # noqa
    import os
    os.environ["STUDY_COACH_DB"] = db_path
    with TestClient(app) as c3:
        assert client.get  # silence
        learners = c3.get("/api/learners").json()
        assert any(l["learner_id"] == "a" for l in learners)
        records = c3.get("/api/learners/a/records").json()["records"]
        assert any(r["topic"] == "分数" for r in records)
        pref = c3.get("/api/learners/a/preference").json()["preference"]
        assert pref["daily_minutes"] == 30


def test_learner_registry_persist_across_restart(client, db_path):
    _mk(client, "u1", "甲")
    _mk(client, "u2", "乙")
    import os
    os.environ["STUDY_COACH_DB"] = db_path
    with TestClient(app) as c2:
        ids = {l["learner_id"] for l in c2.get("/api/learners").json()}
    assert {"u1", "u2"} <= ids


def test_learner_isolation(client):
    _mk(client, "a", "A")
    _mk(client, "b", "B")
    client.post("/api/learners/a/records", json={"course": "数学", "topic": "分数", "mastery": 2})
    b_records = client.get("/api/learners/b/records").json()["records"]
    assert b_records == []
    b_mem = client.get("/api/learners/b/memory").json()
    assert all("分数" not in e["text"] for e in b_mem["entries"])


def test_preference_changes_plan(client):
    _mk(client)
    client.post("/api/learners/a/records", json={"course": "数学", "topic": "分数", "mastery": 1, "studied_on": "2026-10-01"})
    client.post("/api/learners/a/records", json={"course": "数学", "topic": "小数", "mastery": 1, "studied_on": "2026-10-01"})
    client.post("/api/learners/a/records", json={"course": "数学", "topic": "几何", "mastery": 1, "studied_on": "2026-10-01"})
    # 极小预算 → 只能容纳少数条目
    client.put("/api/learners/a/preference", json={"daily_minutes": 8, "goal": "", "preferences": ""})
    small = client.get("/api/learners/a/review-plan", params={"date": "2026-10-29"}).json()
    assert small["daily_minutes"] == 8
    assert small["total_est_minutes"] <= 8
    # 扩大预算 → 清单条目增多
    client.put("/api/learners/a/preference", json={"daily_minutes": 60, "goal": "", "preferences": ""})
    big = client.get("/api/learners/a/review-plan", params={"date": "2026-10-29"}).json()
    assert len(big["items"]) >= len(small["items"])
    assert len(big["items"]) == 3


def test_weak_first_ordering(client):
    _mk(client)
    client.put("/api/learners/a/preference", json={"daily_minutes": 60, "goal": "", "preferences": ""})
    client.post("/api/learners/a/records", json={"course": "c", "topic": "强项", "mastery": 5, "studied_on": "2026-10-01"})
    client.post("/api/learners/a/records", json={"course": "c", "topic": "中等", "mastery": 3, "studied_on": "2026-10-01"})
    client.post("/api/learners/a/records", json={"course": "c", "topic": "薄弱", "mastery": 0, "studied_on": "2026-10-01"})
    items = client.get("/api/learners/a/review-plan", params={"date": "2026-10-29"}).json()["items"]
    assert items[0]["topic"] == "薄弱"
    assert items[0]["mastery"] <= items[-1]["mastery"]


def test_review_result_updates_and_history(client):
    _mk(client)
    client.post("/api/learners/a/records", json={"course": "c", "topic": "分数", "mastery": 1, "studied_on": "2026-10-01"})
    r = client.post("/api/learners/a/review-result", json={"topic": "分数", "quality": 4, "review_date": "2026-10-20"})
    assert r.status_code == 200
    assert r.json()["result"]["mastery"] == 4
    # 更新后清单使用最新进度
    recs = client.get("/api/learners/a/records").json()["records"]
    frac = next(x for x in recs if x["topic"] == "分数")
    assert frac["mastery"] == 4
    assert frac["last_review"] == "2026-10-20"
    # 历史仍可读取(SDK 逐修订回查)
    hist = client.get("/api/learners/a/memory/history").json()["revisions"]
    texts = [e["text"] for rev in hist for e in rev["entries"]]
    assert any('"mastery":1' in t or "mastery\u00031" in t or '"mastery":1,' in t for t in texts)  # 旧掌握度1仍在历史
    assert any('"mastery":4' in t for t in texts)  # 新掌握度4也在


def test_duplicate_submit_no_duplicate(client):
    _mk(client)
    rec = {"course": "数学", "topic": "分数", "note": "通分", "mastery": 1, "studied_on": "2026-10-01"}
    client.post("/api/learners/a/records", json=rec)
    client.post("/api/learners/a/records", json=rec)
    client.post("/api/learners/a/records", json=rec)
    assert len(client.get("/api/learners/a/records").json()["records"]) == 1
    # 复习结果重复提交不推进
    client.post("/api/learners/a/review-result", json={"topic": "分数", "quality": 1, "review_date": "2026-10-20"})
    first = client.get("/api/learners/a/records").json()["records"][0]
    client.post("/api/learners/a/review-result", json={"topic": "分数", "quality": 1, "review_date": "2026-10-20"})
    second = client.get("/api/learners/a/records").json()["records"][0]
    assert first["lapses"] == second["lapses"] and first["interval"] == second["interval"]


@pytest.mark.parametrize(
    "bad",
    [
        {"course": "", "topic": "x", "mastery": 3},
        {"course": "c", "topic": "x", "mastery": 6},
        {"course": "c", "topic": "x", "mastery": -1},
        {"course": "c", "topic": "x", "mastery": 3, "studied_on": "2026-13-40"},
        {"course": "c", "topic": "x", "mastery": "high"},
    ],
)
def test_illegal_fields_rejected(client, bad):
    _mk(client)
    r = client.post("/api/learners/a/records", json=bad)
    assert r.status_code == 422
    assert client.get("/api/learners/a/records").json()["records"] == []


def test_preference_illegal_rejected(client):
    _mk(client)
    assert client.put("/api/learners/a/preference", json={"daily_minutes": 0}).status_code == 422
    assert client.put("/api/learners/a/preference", json={"daily_minutes": 9999}).status_code == 422


def test_chinese_roundtrip(client):
    _mk(client, name="张三")
    client.post("/api/learners/a/records", json={"course": "语文", "topic": "古诗鉴赏", "note": "意象与意境", "mastery": 2, "studied_on": "2026-10-05"})
    ver = client.get("/api/learners/a/memory").json()
    joined = "".join(e["text"] for e in ver["entries"])
    assert "古诗鉴赏" in joined and "意象与意境" in joined
    plan = client.get("/api/learners/a/review-plan", params={"date": "2026-10-29"}).json()
    assert any("古诗鉴赏" in it["topic"] for it in plan["items"])


def test_unknown_learner_404(client):
    assert client.get("/api/learners/nope/records").status_code == 404


def test_review_result_unknown_topic_404(client):
    _mk(client)
    r = client.post("/api/learners/a/review-result", json={"topic": "不存在", "quality": 3, "review_date": "2026-10-20"})
    assert r.status_code == 404


def test_review_units_sm2():
    today = date(2026, 10, 29)
    rec = {"_entry_id": "e", "course": "c", "topic": "t", "mastery": 1, "studied_on": "2026-10-01",
           "last_review": None, "review_count": 0, "interval": 0, "ease": 2.5, "lapses": 0}
    up = review.apply_quality(rec, 4, "2026-10-20")
    assert up["mastery"] == 4 and up["interval"] == 1 and up["review_count"] == 1
    up2 = review.apply_quality(up, 4, "2026-10-21")
    assert up2["interval"] == 6  # 第二次成功复习间隔到 6 天
    items, budget, _ = review.generate_plan([rec], {"daily_minutes": 30}, today)
    assert budget == 30 and len(items) == 1
