#!/usr/bin/env bash
# Stop this project's containers. Data volumes are kept (never `down -v`).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

echo "== 停止项目 '$COMPOSE_PROJECT_NAME' 容器（保留数据）=="
npc_compose down
echo "已停止。数据保留在 $DIFY_COMPOSE_DIR/volumes 与 $NPC_MEMORY_DATA_DIR"
