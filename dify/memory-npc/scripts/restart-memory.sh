#!/usr/bin/env bash
# Recreate ONLY the npc-memory companion service. Archive data lives in the
# host volume ($NPC_MEMORY_DATA_DIR) and is never deleted here.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

echo "== 重启记忆服务（保留存档）=="
npc_compose up -d --force-recreate npc-memory

for _ in $(seq 1 60); do
    if curl -sf --max-time 3 "$NPC_MEMORY_URL/healthz" >/dev/null 2>&1; then
        echo "npc-memory 已恢复: $NPC_MEMORY_URL/healthz"
        exit 0
    fi
    sleep 2
done
echo "npc-memory 未就绪，请查看: docker logs npc-memory" >&2
exit 1
