#!/usr/bin/env bash
# 启动服务(可从任意工作目录调用)。默认 127.0.0.1:8765。
# 正常启动/重启不清空数据库。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
  echo "==> 未发现 .venv,先执行 prepare.sh 安装依赖"
  bash "$SCRIPT_DIR/prepare.sh"
fi

HOST="${STUDY_COACH_HOST:-127.0.0.1}"
PORT="${STUDY_COACH_PORT:-8765}"
export STUDY_COACH_DB="${STUDY_COACH_DB:-$PROJECT_DIR/.data/study_coach.db}"
mkdir -p "$(dirname "$STUDY_COACH_DB")"

echo "==> 启动复习记忆助手 http://$HOST:$PORT"
echo "==> 持久化数据库:$STUDY_COACH_DB(已存在则复用,不清空)"
exec .venv/bin/python -m uvicorn app.app:app --host "$HOST" --port "$PORT"
