#!/usr/bin/env bash
# 初始化运行时（seekdb 库表 + PowerContext Scope）并导入工程资料。
# 用法：bash scripts/10_ingest.sh
set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "$0")/_common.sh"
cd "$MINIMAX_DIR"

log "初始化运行时 / seekdb 库表 / PowerContext Scope"
py init

log "导入工程资料到 seekdb（规格 / 代码 / 测试）"
py ingest > "$RUNTIME_DIR/ingest.json"
"$PYTHON_BIN" - "$RUNTIME_DIR/ingest.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
print("导入文档数:", d["documents"], "| 分类:", d["by_kind"])
PY

log "从空状态保存初始任务记录到 PowerContext"
py state-save --file sample-task/state-initial.json > "$RUNTIME_DIR/state-initial.json"

py doctor > "$RUNTIME_DIR/doctor.json"
log "seekdb 初始化与导入完成（明细见 .runtime/doctor.json）"
