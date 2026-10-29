#!/usr/bin/env bash
# 停止由本套脚本启动的 PowerContext Server。
# 用法：bash scripts/99_stop_powercontext.sh
set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "$0")/_common.sh"
pc_stop
