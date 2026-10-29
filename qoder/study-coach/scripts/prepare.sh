#!/usr/bin/env bash
# 准备锁定依赖(可从任意工作目录调用)。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "错误:未找到 uv。请先安装 uv(https://docs.astral.sh/uv/)。" >&2
  exit 1
fi

echo "==> 项目目录:$PROJECT_DIR"
echo "==> 依据 uv.lock 安装锁定依赖到 .venv(Python 3.12)"
uv sync --frozen

echo "==> 依赖就绪。运行 test.sh 执行测试,start.sh 启动服务。"
