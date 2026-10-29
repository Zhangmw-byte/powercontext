#!/usr/bin/env bash
# Build and start the full stack: official Dify compose + npc-memory companion.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

[ -f "$DIFY_COMPOSE_DIR/.env" ] || {
    echo "缺少 $DIFY_COMPOSE_DIR/.env，请先运行 scripts/prepare.sh" >&2
    exit 1
}
mkdir -p "$NPC_MEMORY_DATA_DIR"

echo "== 启动项目 '$COMPOSE_PROJECT_NAME'（官方 Dify + npc-memory）=="
npc_compose up -d --build

echo "== 等待 npc-memory 健康 =="
for _ in $(seq 1 60); do
    if curl -sf --max-time 3 "$NPC_MEMORY_URL/healthz" >/dev/null 2>&1; then
        echo "npc-memory 正常: $NPC_MEMORY_URL/healthz"
        break
    fi
    sleep 2
done
if ! curl -sf --max-time 3 "$NPC_MEMORY_URL/healthz" >/dev/null 2>&1; then
    echo "npc-memory 未就绪，请查看: docker logs npc-memory" >&2
    exit 1
fi

echo "== 状态 =="
npc_compose ps
echo "Dify 页面: http://127.0.0.1:${DIFY_WEB_PORT}  （模型凭据请在 Dify 界面配置）"
