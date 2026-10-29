#!/usr/bin/env bash
# 规格更新 + 重新导入演示：证明上下文不是固定答案，而是跟随 seekdb 中的最新规格。
# 用法：bash scripts/60_spec_update_demo.sh
set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "$0")/_common.sh"
cd "$MINIMAX_DIR"

ORIG="sample-task/specs/SPEC-003-filter.md"
UPDATED="sample-task/spec-updates/SPEC-003-filter-v2.md"
BACKUP="$RUNTIME_DIR/SPEC-003-filter.original.md"
OUT="$LOG_DIR/spec-update-demo.log"

{
  echo "# 规格更新 + 重新导入演示"
  echo "# command: cp $UPDATED $ORIG; python -m sdd_context ingest; python -m sdd_context context"
  echo "# time: $(date -Is)"
} > "$OUT"

cp "$ORIG" "$BACKUP"
trap 'cp "$BACKUP" "$ORIG" 2>/dev/null || true' EXIT
py context > /dev/null
if grep -q "v2 更新" "$RUNTIME_DIR/context.md"; then
  die "演示前置条件失败：原始规格的上下文中不应包含 v2 内容"
fi
echo "[更新前] context.md 不含 v2 更新内容" >> "$OUT"

cp "$UPDATED" "$ORIG"
py ingest > /dev/null
py context > /dev/null
grep -n "v2 更新" "$RUNTIME_DIR/context.md" >> "$OUT" || die "规格更新并重新导入后，上下文未使用新内容"
echo "[更新并重新导入后] 上下文命中 v2 更新内容（见上）" >> "$OUT"

cp "$BACKUP" "$ORIG"
py ingest > /dev/null
py context > /dev/null
if grep -q "v2 更新" "$RUNTIME_DIR/context.md"; then
  die "恢复原始规格后，上下文仍包含 v2 内容"
fi
echo "[恢复原始规格并重新导入后] context.md 不再包含 v2 更新内容" >> "$OUT"
echo "OK: 规格更新 → 上下文跟随变化 → 恢复后回到原内容。" >> "$OUT"

cat "$OUT"
log "规格更新演示通过：$OUT"
