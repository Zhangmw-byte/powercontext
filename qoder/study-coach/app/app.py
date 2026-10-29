"""复习记忆助手 — FastAPI 应用入口。

lifespan 打开并持有 PowerContext 持久化 store(真实 SQLite 后端),
整个应用生命周期共享;进程重启后重新打开同一数据库文件即恢复记忆。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import review
from app.memory_repo import StudyCoachStore, learner_scope_id, open_store
from app.models import (
    LearnerCreate,
    PreferenceIn,
    RecordIn,
    ReviewResultIn,
)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_DB = BASE_DIR / ".data" / "study_coach.db"


def _db_path() -> str:
    return os.environ.get("STUDY_COACH_DB", str(DEFAULT_DB))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    async with open_store(path) as store:
        app.state.store = store
        app.state.db_path = path
        yield


app = FastAPI(title="复习记忆助手", version="0.1.0", lifespan=lifespan)


def _store(request: Request) -> StudyCoachStore:
    return request.app.state.store


async def _require_learner(store: StudyCoachStore, learner_id: str) -> dict:
    learner = await store.get_learner(learner_id)
    if learner is None:
        raise HTTPException(status_code=404, detail=f"学习者不存在: {learner_id}")
    return learner


def _today(raw: str | None) -> date:
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="date 必须为 YYYY-MM-DD") from None


# --------------------------------------------------------------------------- #
# 学习者
# --------------------------------------------------------------------------- #
@app.get("/api/learners")
async def list_learners(request: Request) -> list[dict]:
    return await _store(request).list_learners()


@app.post("/api/learners", status_code=201)
async def create_learner(payload: LearnerCreate, request: Request) -> dict:
    return await _store(request).add_learner(payload.learner_id, payload.name)


@app.get("/api/learners/{learner_id}/overview")
async def overview(learner_id: str, request: Request) -> dict:
    store = _store(request)
    learner = await _require_learner(store, learner_id)
    pref = await store.get_preference(learner_id)
    records = await store.list_records(learner_id)
    today = date.today()
    items, budget, _ = review.generate_plan(records, pref, today)
    mastered = sum(1 for r in records if int(r.get("mastery", 0)) >= 4)
    weak = sum(1 for r in records if int(r.get("mastery", 0)) <= 2)
    return {
        "learner": learner,
        "record_count": len(records),
        "mastered_count": mastered,
        "weak_count": weak,
        "due_count": len(items),
        "daily_minutes": budget,
        "has_preference": pref is not None,
    }


# --------------------------------------------------------------------------- #
# 偏好
# --------------------------------------------------------------------------- #
@app.get("/api/learners/{learner_id}/preference")
async def get_preference(learner_id: str, request: Request) -> dict:
    store = _store(request)
    await _require_learner(store, learner_id)
    pref = await store.get_preference(learner_id)
    return {"learner_id": learner_id, "preference": pref}


@app.put("/api/learners/{learner_id}/preference")
async def put_preference(learner_id: str, payload: PreferenceIn, request: Request) -> dict:
    store = _store(request)
    await _require_learner(store, learner_id)
    saved = await store.put_preference(learner_id, payload)
    return {"learner_id": learner_id, "preference": saved}


# --------------------------------------------------------------------------- #
# 学习记录
# --------------------------------------------------------------------------- #
@app.get("/api/learners/{learner_id}/records")
async def list_records(learner_id: str, request: Request) -> dict:
    store = _store(request)
    await _require_learner(store, learner_id)
    return {"records": await store.list_records(learner_id)}


@app.post("/api/learners/{learner_id}/records", status_code=201)
async def add_record(learner_id: str, payload: RecordIn, request: Request) -> dict:
    store = _store(request)
    await _require_learner(store, learner_id)
    return {"record": await store.add_record(learner_id, payload)}


# --------------------------------------------------------------------------- #
# 复习清单与结果回写
# --------------------------------------------------------------------------- #
@app.get("/api/learners/{learner_id}/review-plan")
async def review_plan(learner_id: str, request: Request) -> dict:
    store = _store(request)
    await _require_learner(store, learner_id)
    today = _today(request.query_params.get("date"))
    records = await store.list_records(learner_id)
    pref = await store.get_preference(learner_id)
    items, budget, note = review.generate_plan(records, pref, today)
    total = sum(i.est_minutes for i in items)
    return {
        "learner_id": learner_id,
        "generated_on": today.isoformat(),
        "daily_minutes": budget,
        "total_est_minutes": total,
        "items": [i.model_dump() for i in items],
        "note": note,
    }


@app.post("/api/learners/{learner_id}/review-result")
async def review_result(learner_id: str, payload: ReviewResultIn, request: Request) -> dict:
    store = _store(request)
    await _require_learner(store, learner_id)
    result = await store.apply_review_result(learner_id, payload)
    if result is None:
        raise HTTPException(status_code=404, detail=f"未找到知识点记录: {payload.topic}")
    return {"learner_id": learner_id, "result": result}


# --------------------------------------------------------------------------- #
# 记忆验证视图与历史(真实 SDK 回查)
# --------------------------------------------------------------------------- #
@app.get("/api/learners/{learner_id}/memory")
async def memory_view(learner_id: str, request: Request) -> dict:
    store = _store(request)
    await _require_learner(store, learner_id)
    return await store.verification(learner_id)


@app.get("/api/learners/{learner_id}/memory/history")
async def memory_history(learner_id: str, request: Request) -> dict:
    store = _store(request)
    await _require_learner(store, learner_id)
    return {"scope_id": learner_scope_id(learner_id), "revisions": await store.history(learner_id)}


# --------------------------------------------------------------------------- #
# 健康检查与前端
# --------------------------------------------------------------------------- #
@app.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    store = _store(request)
    learners = await store.list_learners()  # 真实读取后端
    return JSONResponse({"status": "ok", "db": request.app.state.db_path, "learners": len(learners)})


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
