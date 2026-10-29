#!/usr/bin/env bash
# Show containers, memory-service health and version pins.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

echo "== Dify 源码 =="
if [ -d "$DIFY_RUNTIME_DIR/.git" ]; then
    echo "$DIFY_RUNTIME_DIR -> $(git -C "$DIFY_RUNTIME_DIR" describe --tags 2>/dev/null || echo '?') $(git -C "$DIFY_RUNTIME_DIR" log -1 --format='%H')"
else
    echo "(尚未下载，请运行 scripts/prepare.sh)"
fi

echo
echo "== 容器（项目 $COMPOSE_PROJECT_NAME）=="
npc_compose ps || true

echo
echo "== npc-memory /healthz =="
curl -sf --max-time 5 "$NPC_MEMORY_URL/healthz" && echo || echo "(不可达)"

echo
echo "== 运行中的镜像标签 =="
docker ps --filter "name=dify" --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | head -20 || true
