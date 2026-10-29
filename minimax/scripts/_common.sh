#!/usr/bin/env bash
# 公共变量与函数（由其它脚本 source）
set -euo pipefail

MINIMAX_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${RUNTIME_DIR:-$MINIMAX_DIR/.runtime}"
LOG_DIR="$MINIMAX_DIR/logs"
PC_URL="${POWERCONTEXT_CLIENT_SERVER_URL:-http://127.0.0.1:18080}"
PC_ENV_FILE="$RUNTIME_DIR/powercontext.env"
PC_PID_FILE="$RUNTIME_DIR/powercontext.pid"

if [ -x "$MINIMAX_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="${PYTHON_BIN:-$MINIMAX_DIR/.venv/bin/python}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

export PYTHONPATH="$MINIMAX_DIR/sdd-context${PYTHONPATH:+:$PYTHONPATH}"
export POWERCONTEXT_CLIENT_SERVER_URL="$PC_URL"
mkdir -p "$RUNTIME_DIR" "$LOG_DIR"

log() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

# 调用 sdd_context CLI（自动带上运行时目录）
py() { "$PYTHON_BIN" -m sdd_context --runtime "$RUNTIME_DIR" "$@"; }

# 调用 powercontext CLI（自动指向本地 Server）
pc() {
  if [ -x "$MINIMAX_DIR/.venv/bin/powercontext" ]; then
    "$MINIMAX_DIR/.venv/bin/powercontext" --server-url "$PC_URL" "$@"
  else
    powercontext --server-url "$PC_URL" "$@"
  fi
}

pc_live() { pc live >/dev/null 2>&1; }

pc_start() {
  if pc_live; then
    log "PowerContext 已在运行：$PC_URL"
    return 0
  fi
  local port="${PC_URL##*:}"
  cat > "$PC_ENV_FILE" <<EOF
POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1
POWERCONTEXT_SERVER_HTTP_PORT=${port}
POWERCONTEXT_SERVER_DASHBOARD_ENABLED=true
POWERCONTEXT_SERVER_ACCESS_MODE=disabled
EOF
  local pc_bin="$MINIMAX_DIR/.venv/bin/powercontext"
  [ -x "$pc_bin" ] || pc_bin="powercontext"
  "$pc_bin" config validate --env-file "$PC_ENV_FILE" >/dev/null
  nohup "$pc_bin" server run --env-file "$PC_ENV_FILE" > "$RUNTIME_DIR/powercontext.log" 2>&1 &
  echo $! > "$PC_PID_FILE"
  local i=0
  while [ "$i" -lt 60 ]; do
    if pc_live; then
      log "PowerContext 已就绪：$PC_URL"
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  cat "$RUNTIME_DIR/powercontext.log" >&2 || true
  die "PowerContext 启动超时（60s）"
}

pc_stop() {
  if [ -f "$PC_PID_FILE" ]; then
    local pid
    pid="$(cat "$PC_PID_FILE" 2>/dev/null || true)"
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 1
    fi
    rm -f "$PC_PID_FILE"
    log "PowerContext 已停止（PID $pid）"
  else
    log "未发现由本脚本启动的 PowerContext（若为外部启动，保持不动）"
  fi
}
