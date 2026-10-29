#!/usr/bin/env bash
# Run the real PowerContext-backend test suite (temp database, non-zero exit on failure).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

[ -x "$NPC_PROJECT_DIR/.venv/bin/python" ] || {
    echo "缺少 .venv，请先运行 scripts/prepare.sh" >&2
    exit 1
}

cd "$NPC_PROJECT_DIR"
exec .venv/bin/python -m pytest tests/ -q "$@"
