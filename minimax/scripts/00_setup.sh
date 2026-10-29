#!/usr/bin/env bash
# 一次性环境安装：创建 minimax/.venv 并安装依赖。
# 用法：bash scripts/00_setup.sh
set -euo pipefail

MINIMAX_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$MINIMAX_DIR"
PYTHON3="${PYTHON3:-python3}"

"$PYTHON3" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"需要 Python >= 3.11，当前 {sys.version.split()[0]}")
print("使用 Python:", sys.version.split()[0])
PY

if [ ! -x "$MINIMAX_DIR/.venv/bin/python" ]; then
  echo "[setup] 创建 .venv"
  "$PYTHON3" -m venv "$MINIMAX_DIR/.venv"
fi

# shellcheck disable=SC1091
. "$MINIMAX_DIR/.venv/bin/activate"
python -m pip install -q -U pip wheel
echo "[setup] 安装 requirements.txt（powercontext / pytest / seekdb 运行依赖）"
python -m pip install -q -r "$MINIMAX_DIR/requirements.txt"
echo "[setup] 安装 pyseekdb（--no-deps，避免 Python 3.14 拉取 torch/CUDA）"
python -m pip install -q --no-deps "pyseekdb==1.4.0.post1"

python - <<'PY'
import pyseekdb, powercontext, pytest  # noqa: F401
print("[setup] pyseekdb:", getattr(pyseekdb, "__version__", "ok"))
print("[setup] powercontext:", getattr(powercontext, "__version__", "ok"))
print("[setup] pytest:", pytest.__version__)
PY

echo "[setup] 完成。下一步：bash scripts/run_all.sh"
