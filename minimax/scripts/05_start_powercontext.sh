#!/usr/bin/env bash
# 启动本地 PowerContext Server（SQLite、显式记忆模式，无需模型 API）。
# 用法：bash scripts/05_start_powercontext.sh
set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "$0")/_common.sh"
pc_start
