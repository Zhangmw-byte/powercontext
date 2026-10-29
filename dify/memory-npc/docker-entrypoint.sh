#!/bin/sh
# Runs one container with two processes:
#   1. a real PowerContext Server (SQLite backend under $POWERCONTEXT_HOME=/data)
#      bound to loopback only, and
#   2. the npc-memory FastAPI facade on 0.0.0.0:8877 which talks to it
#      through the official powercontext Python SDK.
set -eu

PCX_PORT="${POWERCONTEXT_INTERNAL_PORT:-8878}"
NPC_MEMORY_PORT="${NPC_MEMORY_PORT:-8877}"

echo "[npc-memory] starting PowerContext server on 127.0.0.1:${PCX_PORT}"
powercontext server run --host 127.0.0.1 --port "${PCX_PORT}" --no-env-file &
PCX_PID=$!
trap 'kill "${PCX_PID}" 2>/dev/null || true' TERM INT

i=0
while ! python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:${PCX_PORT}/health/ready', timeout=2)" </dev/null >/dev/null 2>&1; do
    i=$((i + 1))
    if ! kill -0 "${PCX_PID}" 2>/dev/null; then
        echo "[npc-memory] PowerContext server exited during startup" >&2
        exit 1
    fi
    if [ "${i}" -gt 120 ]; then
        echo "[npc-memory] PowerContext server not ready after 120s" >&2
        exit 1
    fi
    sleep 1
done
echo "[npc-memory] PowerContext server ready; starting FastAPI facade on 0.0.0.0:${NPC_MEMORY_PORT}"

POWERCONTEXT_SERVER_URL="http://127.0.0.1:${PCX_PORT}" \
    exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port "${NPC_MEMORY_PORT}"
