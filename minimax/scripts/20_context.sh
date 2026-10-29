#!/usr/bin/env bash
# 按任务描述从 seekdb 检索工程资料，生成上下文包（context.md / context.json）。
# 用法：bash scripts/20_context.sh
set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "$0")/_common.sh"
cd "$MINIMAX_DIR"

log "按任务描述生成上下文包"
py context > "$RUNTIME_DIR/context-run.json"
"$PYTHON_BIN" - "$RUNTIME_DIR/context-run.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
c = d["coverage"]
print("规格覆盖:", c["selected_spec_ids"], "| 缺失:", c["missing_spec_ids"])
print("代码条目:", c["code"], "| 目标测试:", c["target_tests"], "| 回归测试:", c["regression_tests"])
assert c["ok"], "上下文覆盖校验失败"
PY

cp "$RUNTIME_DIR/context.md" "$LOG_DIR/context-snapshot.md"
cp "$RUNTIME_DIR/context.json" "$LOG_DIR/context-snapshot.json"
log "上下文已生成：.runtime/context.md（快照 logs/context-snapshot.md）"
