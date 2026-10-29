#!/usr/bin/env bash
# 状态复用演示：新进程（模块重启）从 PowerContext 读取任务状态，并用于后续上下文。
# 用法：bash scripts/50_state_restart.sh
set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "$0")/_common.sh"
cd "$MINIMAX_DIR"

RESTART_JSON="$RUNTIME_DIR/state-restart.json"
OUT="$LOG_DIR/state-restart.log"
{
  echo "# 模块重启后读取 PowerContext 状态（每次 CLI 调用都是一个新进程）"
  echo "# command: python -m sdd_context --runtime .runtime state-show"
  echo "# time: $(date -Is)"
} > "$OUT"

py state-show > "$RESTART_JSON"
"$PYTHON_BIN" - "$RESTART_JSON" >> "$OUT" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
state = d.get("state") or {}
verifications = state.get("verifications") or []
print("scope_id:", d["scope"]["scope_id"])
print("updated_at:", state.get("updated_at"))
print("verifications:", len(verifications))
for v in verifications:
    print(" -", v["name"], "exit", v["exit_code"], "passed", v["passed"])
assert len(verifications) == 4, f"期望 4 条验证结果，实际 {len(verifications)}"
names = {v["name"] for v in verifications}
expected = {"target-before", "regression-before", "target-after", "regression-after"}
assert expected <= names, f"缺少验证项: {expected - names}"
assert all(v["passed"] for v in verifications if v["name"].endswith("after")), "修改后测试应全部通过"
print("OK: 重启后的新进程成功读取并复用 PowerContext 状态")
PY

py context > /dev/null
{
  echo
  echo "# 重新生成上下文（新进程）后，PowerContext 状态段落："
  sed -n '/## 5. 任务状态/,/## 6/p' "$RUNTIME_DIR/context.md"
} >> "$OUT"
grep -q "已从 PowerContext 读取任务状态" "$RUNTIME_DIR/context.md" || die "上下文未包含 PowerContext 状态"
grep -q "target-after" "$RUNTIME_DIR/context.md" || die "上下文状态中缺少修改后验证结果"
cp "$RUNTIME_DIR/context.md" "$LOG_DIR/context-snapshot-with-state.md"
cp "$RUNTIME_DIR/context.json" "$LOG_DIR/context-snapshot-with-state.json"
log "状态复用演示通过：$OUT"
