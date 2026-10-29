"""FastAPI facade exposing the PowerContext-backed NPC memory service.

Endpoints
---------
GET  /healthz
POST /v1/turns/prepare   read archive + context for a turn (no writes)
POST /v1/turns/commit    persist a model reply for a turn (idempotent)
GET  /v1/players/{player_id}/memory  full archive for verification
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from powercontext.client import PowerContextClient, ServerResponseError

from .settings import ServiceSettings
from .store import MemoryServiceError, MemoryStore, _validate_player_id


class TurnRequest(BaseModel):
    player_id: str = Field(min_length=1, max_length=64)
    turn_no: int = Field(ge=1)
    action: str = Field(min_length=1)


class CommitRequest(TurnRequest):
    reply: str = Field(min_length=1)
    expected_revision: int | None = Field(default=None, ge=0)


def _error(exc: MemoryServiceError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    settings = settings or ServiceSettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = PowerContextClient(
            settings.powercontext_url, timeout=settings.request_timeout_seconds
        )
        app.state.client = client
        app.state.store = MemoryStore(client)
        app.state.settings = settings
        try:
            yield
        finally:
            await client.aclose()

    app = FastAPI(title="npc-memory", version="1.0.0", lifespan=lifespan)

    def store(request: Request) -> MemoryStore:
        return request.app.state.store

    def cfg(request: Request) -> ServiceSettings:
        return request.app.state.settings

    @app.get("/healthz")
    async def healthz(request: Request) -> dict:
        client: PowerContextClient = request.app.state.client
        try:
            readiness = await client.get_readiness()
        except Exception as error:  # noqa: BLE001 - report backend state
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "powercontext_unreachable",
                    "message": f"无法连接 PowerContext Server: {error}",
                },
            ) from error
        return {
            "status": "ok",
            "powercontext_url": settings.powercontext_url,
            "powercontext_readiness": str(readiness.status.value),
            "checks": {k: str(v) for k, v in readiness.checks.items()},
        }

    @app.post("/v1/turns/prepare")
    async def prepare_turn(request: Request, payload: TurnRequest = Body(...)) -> dict:
        try:
            player_id = _validate_player_id(payload.player_id)
            if len(payload.action) > cfg(request).max_action_chars:
                raise MemoryServiceError(
                    "action_too_long",
                    f"action 最长 {cfg(request).max_action_chars} 字符",
                )
            return await store(request).prepare_turn(
                player_id, payload.turn_no, payload.action, cfg(request).history_window_turns
            )
        except MemoryServiceError as exc:
            raise _error(exc) from exc

    @app.post("/v1/turns/commit")
    async def commit_turn(request: Request, payload: CommitRequest = Body(...)) -> dict:
        try:
            if len(payload.action) > cfg(request).max_action_chars:
                raise MemoryServiceError(
                    "action_too_long",
                    f"action 最长 {cfg(request).max_action_chars} 字符",
                )
            if len(payload.reply) > cfg(request).max_reply_chars:
                raise MemoryServiceError(
                    "reply_too_long",
                    f"reply 最长 {cfg(request).max_reply_chars} 字符",
                )
            result = await store(request).commit_turn(
                payload.player_id,
                payload.turn_no,
                payload.action,
                payload.reply,
                payload.expected_revision,
            )
            return result
        except MemoryServiceError as exc:
            raise _error(exc) from exc
        except ServerResponseError as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": f"powercontext_{exc.code or 'error'}",
                    "message": str(exc),
                },
            ) from exc

    @app.get("/v1/players/{player_id}/memory")
    async def player_memory(request: Request, player_id: str) -> dict:
        try:
            archive = await store(request).read_archive(player_id)
        except MemoryServiceError as exc:
            raise _error(exc) from exc
        if archive is None:
            return {
                "player_id": player_id.strip(),
                "scope_exists": False,
                "revision": 0,
                "turn_count": 0,
                "turns": [],
            }
        return {
            "player_id": player_id.strip(),
            "scope_exists": True,
            "scope_id": archive.scope_id,
            "revision": archive.revision,
            "turn_count": len(archive.turns),
            "turns": [
                {
                    "turn_no": t.turn_no,
                    "action": t.action,
                    "reply": t.reply,
                    "committed_at": t.committed_at,
                    "entry_version": t.entry_version,
                }
                for t in archive.turns
            ],
        }

    return app
