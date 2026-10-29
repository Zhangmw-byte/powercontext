#!/usr/bin/env bash
# 修改前验证：目标功能测试必须失败，回归测试必须通过；结果写入 PowerContext。
# 用法：bash scripts/30_tests_before.sh
set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "$0")/_common.sh"
cd "$MINIMAX_DIR"

AFTER_BACKUP="$RUNTIME_DIR/orders.after.py"
cp sample-app/order_service/orders.py "$AFTER_BACKUP"
cp sample-task/before/orders.py sample-app/order_service/orders.py
trap 'cp "$AFTER_BACKUP" sample-app/order_service/orders.py 2>/dev/null || true' EXIT
BEFORE_SHA="$(sha256sum sample-app/order_service/orders.py | cut -d' ' -f1)"
log "已切换到修改前代码（sha256=$BEFORE_SHA）"

LAST_CODE=0
run_test() {
  local name="$1"
  local file="$2"
  local expected="$3"
  local out="$LOG_DIR/tests-before-$name.log"
  local code=0
  {
    echo "# 修改前测试：$name（期望退出码 $expected）"
    echo "# command: cd sample-app && python -m pytest $file -q -o addopts=''"
    echo "# code_version: sample-app/order_service/orders.py sha256=$BEFORE_SHA"
    echo "# python: $("$PYTHON_BIN" --version 2>&1)"
    echo "# time: $(date -Is)"
  } > "$out"
  set +e
  ( cd sample-app && "$PYTHON_BIN" -m pytest "$file" -q -o addopts='' ) >> "$out" 2>&1
  code=$?
  set -e
  echo "# exit_code=$code" >> "$out"
  log "$name 退出码=$code（期望 $expected）"
  if [ "$code" -ne "$expected" ]; then
    cp "$AFTER_BACKUP" sample-app/order_service/orders.py
    die "$name 退出码 $code 与期望 $expected 不符，详见 $out"
  fi
  LAST_CODE="$code"
}

run_test target tests/test_target_feature.py 1
TARGET_BEFORE_CODE="$LAST_CODE"
run_test regression tests/test_regression.py 0
REGRESSION_BEFORE_CODE="$LAST_CODE"

cp "$AFTER_BACKUP" sample-app/order_service/orders.py
log "已恢复修改后的代码"

py state-record-test --name target-before \
  --command "cd sample-app && python -m pytest tests/test_target_feature.py -q" \
  --exit-code "$TARGET_BEFORE_CODE" --passed 0 --code-sha "$BEFORE_SHA" >/dev/null
py state-record-test --name regression-before \
  --command "cd sample-app && python -m pytest tests/test_regression.py -q" \
  --exit-code "$REGRESSION_BEFORE_CODE" --passed 1 --code-sha "$BEFORE_SHA" >/dev/null
log "修改前验证结果已写入 PowerContext"
