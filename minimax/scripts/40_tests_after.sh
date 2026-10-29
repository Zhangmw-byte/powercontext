#!/usr/bin/env bash
# 修改后验证：目标功能测试与回归测试必须全部通过；结果写入 PowerContext 并收尾状态。
# 用法：bash scripts/40_tests_after.sh
set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "$0")/_common.sh"
cd "$MINIMAX_DIR"

AFTER_SHA="$(sha256sum sample-app/order_service/orders.py | cut -d' ' -f1)"
log "当前（修改后）代码 sha256=$AFTER_SHA"

LAST_CODE=0
run_test() {
  local name="$1"
  local file="$2"
  local out="$LOG_DIR/tests-after-$name.log"
  local code=0
  {
    echo "# 修改后测试：$name（期望退出码 0）"
    echo "# command: cd sample-app && python -m pytest $file -q -o addopts=''"
    echo "# code_version: sample-app/order_service/orders.py sha256=$AFTER_SHA"
    echo "# python: $("$PYTHON_BIN" --version 2>&1)"
    echo "# time: $(date -Is)"
  } > "$out"
  set +e
  ( cd sample-app && "$PYTHON_BIN" -m pytest "$file" -q -o addopts='' ) >> "$out" 2>&1
  code=$?
  set -e
  echo "# exit_code=$code" >> "$out"
  log "$name 退出码=$code（期望 0）"
  if [ "$code" -ne 0 ]; then
    die "$name 未通过，详见 $out"
  fi
  LAST_CODE="$code"
}

run_test target tests/test_target_feature.py
TARGET_AFTER_CODE="$LAST_CODE"
run_test regression tests/test_regression.py
REGRESSION_AFTER_CODE="$LAST_CODE"

py state-record-test --name target-after \
  --command "cd sample-app && python -m pytest tests/test_target_feature.py -q" \
  --exit-code "$TARGET_AFTER_CODE" --passed 1 --code-sha "$AFTER_SHA" >/dev/null
py state-record-test --name regression-after \
  --command "cd sample-app && python -m pytest tests/test_regression.py -q" \
  --exit-code "$REGRESSION_AFTER_CODE" --passed 1 --code-sha "$AFTER_SHA" >/dev/null

py state-finalize \
  --task "订单列表增加状态筛选与分页（SPEC-003 / SPEC-004）" \
  --done "锁定任务与适用规格：SPEC-001 ~ SPEC-005 已导入 seekdb 并可检索" \
  --done "上下文模块生成任务上下文包，并交给 MiniMax M3.1 Flash 完成代码修改" \
  --done "目标功能测试修改前失败、修改后全部通过；回归测试修改前后均通过" \
  --done "验证结果已写入 PowerContext，可被 Module 重启后的新进程读取复用" \
  --todo "训练营评测提交并在提测记录中确认结果" > "$RUNTIME_DIR/state-final.json"
log "修改后验证结果已写入 PowerContext，状态已收尾（见 .runtime/state-final.json）"
