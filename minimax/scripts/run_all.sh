#!/usr/bin/env bash
# 一键复现：启动 PowerContext → 导入 seekdb → 生成上下文 → 修改前测试 →
# 修改后测试 + 状态入库 → 重启后状态复用 → 规格更新演示。
# 用法：bash scripts/run_all.sh
# 可选：KEEP_RUNTIME=1 保留已有 .runtime；默认每次清空运行时目录（全部为本地生成的临时数据）。
set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "$0")/_common.sh"
cd "$MINIMAX_DIR"

if [ ! -x "$MINIMAX_DIR/.venv/bin/python" ]; then
  die "缺少 .venv，请先运行 bash scripts/00_setup.sh"
fi

if [ "${KEEP_RUNTIME:-0}" != "1" ]; then
  log "清空运行时目录 $RUNTIME_DIR（KEEP_RUNTIME=1 可保留）"
  rm -rf "$RUNTIME_DIR"
fi
mkdir -p "$RUNTIME_DIR" "$LOG_DIR"

log "========== 1/7 启动 PowerContext Server =========="
bash "$MINIMAX_DIR/scripts/05_start_powercontext.sh"

log "========== 2/7 初始化 + 导入 seekdb =========="
bash "$MINIMAX_DIR/scripts/10_ingest.sh"

log "========== 3/7 生成任务上下文 =========="
bash "$MINIMAX_DIR/scripts/20_context.sh"

log "========== 4/7 修改前测试（目标测试失败 / 回归测试通过） =========="
bash "$MINIMAX_DIR/scripts/30_tests_before.sh"

log "========== 5/7 修改后测试（全部通过）+ 验证结果写入 PowerContext =========="
bash "$MINIMAX_DIR/scripts/40_tests_after.sh"

log "========== 6/7 重启后状态复用 =========="
bash "$MINIMAX_DIR/scripts/50_state_restart.sh"

log "========== 7/7 规格更新 + 重新导入演示 =========="
bash "$MINIMAX_DIR/scripts/60_spec_update_demo.sh"

log "全部验证通过。"
log "  上下文：$RUNTIME_DIR/context.md"
log "  测试日志：$LOG_DIR/tests-before-*.log、$LOG_DIR/tests-after-*.log"
log "  状态复用：$LOG_DIR/state-restart.log"
log "  规格更新：$LOG_DIR/spec-update-demo.log"
log "  数据库脚本：$LOG_DIR/db-query.log（运行时）"
log "如需停止 PowerContext：bash scripts/99_stop_powercontext.sh"
