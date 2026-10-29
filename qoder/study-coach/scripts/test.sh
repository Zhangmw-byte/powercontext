#!/usr/bin/env bash
# 运行测试(可从任意工作目录调用)。测试失败返回非零退出码。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
  echo "==> 未发现 .venv,先执行 prepare.sh 安装依赖"
  bash "$SCRIPT_DIR/prepare.sh"
fi

echo "==> 运行测试(独立临时数据库,不触碰用户数据)"
set +e
.venv/bin/python -m pytest -q "$@"
code=$?
set -e

if [ "$code" -ne 0 ]; then
  echo "==> 测试失败(退出码 $code)" >&2
  exit "$code"
fi
echo "==> 全部测试通过"
