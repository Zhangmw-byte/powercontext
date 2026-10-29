"""配置与路径解析。

所有路径默认相对交付目录 ``minimax/``（即本文件所在包的上两层）。
运行时数据（seekdb 数据、PowerContext scope 记录、生成的上下文、日志）
统一放在 ``minimax/.runtime/``，可在命令行用 ``--runtime`` 覆盖。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# minimax/ 目录：<minimax>/sdd-context/sdd_context/config.py
MINIMAX_DIR = Path(__file__).resolve().parents[2]

DEFAULT_RUNTIME = MINIMAX_DIR / ".runtime"
SAMPLES_DIR = MINIMAX_DIR / "sample-task"
SAMPLE_APP_DIR = MINIMAX_DIR / "sample-app"
LOGS_DIR = MINIMAX_DIR / "logs"

DEFAULT_POWERCONTEXT_URL = "http://127.0.0.1:18080"


@dataclass(frozen=True)
class Settings:
    minimax_dir: Path
    runtime_dir: Path
    seekdb_dir: Path
    database: str
    powercontext_url: str
    scope_file: Path
    context_json: Path
    context_md: Path
    db_query_log: Path
    ingest_log: Path


def settings(runtime: str | os.PathLike | None = None, powercontext_url: str | None = None) -> Settings:
    runtime_dir = Path(runtime).expanduser().resolve() if runtime else DEFAULT_RUNTIME
    url = powercontext_url or os.environ.get("POWERCONTEXT_CLIENT_SERVER_URL") or DEFAULT_POWERCONTEXT_URL
    return Settings(
        minimax_dir=MINIMAX_DIR,
        runtime_dir=runtime_dir,
        seekdb_dir=runtime_dir / "seekdb",
        database="sdd",
        powercontext_url=url.rstrip("/"),
        scope_file=runtime_dir / "scope.json",
        context_json=runtime_dir / "context.json",
        context_md=runtime_dir / "context.md",
        db_query_log=runtime_dir / "db-query.log",
        ingest_log=runtime_dir / "ingest.log",
    )


def ensure_runtime(settings_obj: Settings) -> None:
    settings_obj.runtime_dir.mkdir(parents=True, exist_ok=True)
    settings_obj.seekdb_dir.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
