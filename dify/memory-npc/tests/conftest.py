"""Test fixtures: run a real PowerContext Server on SQLite per session."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from app.main import create_app
from app.settings import ServiceSettings

REPO_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class PowerContextServer:
    def __init__(self, home: Path, port: int) -> None:
        self.home = home
        self.port = port
        self.process: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        env = {**os.environ, "POWERCONTEXT_HOME": str(self.home)}
        python = REPO_ROOT / ".venv/bin/python"
        cli = REPO_ROOT / ".venv/bin/powercontext"
        self.process = subprocess.Popen(
            [str(python), str(cli), "server", "run",
             "--host", "127.0.0.1", "--port", str(self.port), "--no-env-file"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if httpx.get(f"{self.url}/health/ready", timeout=1.0).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if self.process.poll() is not None:
                raise RuntimeError(f"PowerContext server exited with {self.process.returncode}")
            time.sleep(0.5)
        raise RuntimeError("PowerContext server did not become ready in time")

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.send_signal(signal.SIGTERM)
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)
        self.process = None


@pytest.fixture()
def pcx_home(tmp_path: Path) -> Path:
    home = tmp_path / "powercontext-home"
    home.mkdir()
    return home


@pytest.fixture()
def pcx_server(pcx_home: Path) -> PowerContextServer:
    server = PowerContextServer(pcx_home, _free_port())
    server.start()
    yield server
    server.stop()


@pytest.fixture()
async def client(pcx_server: PowerContextServer):
    settings = ServiceSettings(
        powercontext_url=pcx_server.url,
        history_window_turns=12,
        request_timeout_seconds=30.0,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://npc-memory") as ac:
            yield ac


@pytest.fixture()
async def client_on_home(pcx_home: Path):
    """Build an npc-memory HTTP facade against a server started on an existing home."""

    def make(url: str, window: int | None = None):
        cfg = ServiceSettings(
            powercontext_url=url,
            history_window_turns=window if window is not None else 12,
        )
        app = create_app(cfg)

        class _Ctx:
            async def __aenter__(self):
                self._cm = app.router.lifespan_context(app)
                await self._cm.__aenter__()
                self._ac = httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://npc-memory"
                )
                return self._ac

            async def __aexit__(self, *args):
                await self._ac.aclose()
                await self._cm.__aexit__(*args)

        return _Ctx()

    return make
