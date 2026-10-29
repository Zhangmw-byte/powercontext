# Shared configuration for dify/memory-npc scripts.
# Resolve everything from this file's location so scripts work from any CWD.

set -euo pipefail

NPC_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Pinned versions -- never silently move to latest.
DIFY_VERSION="${DIFY_VERSION:-1.13.3}"
POWERCONTEXT_VERSION="${POWERCONTEXT_VERSION:-1.2.0}"

DIFY_RUNTIME_DIR="${DIFY_RUNTIME_DIR:-$HOME/dify-runtime-$DIFY_VERSION}"
DIFY_COMPOSE_DIR="$DIFY_RUNTIME_DIR/docker"
DIFY_GIT_URL="${DIFY_GIT_URL:-https://github.com/langgenius/dify.git}"

# Fixed compose project name, per competition requirement.
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-difyfun}"
export COMPOSE_NETWORK_NAME="${COMPOSE_NETWORK_NAME:-${COMPOSE_PROJECT_NAME}_default}"

# Runtime data on the (D-drive) Ubuntu home by default; override via env.
NPC_MEMORY_DATA_DIR="${NPC_MEMORY_DATA_DIR:-$HOME/difyfun-data/npc-memory}"
NPC_MEMORY_PROJECT_DIR="$NPC_PROJECT_DIR"
NPC_MEMORY_BIND_ADDR="${NPC_MEMORY_BIND_ADDR:-127.0.0.1}"
NPC_MEMORY_URL="${NPC_MEMORY_URL:-http://127.0.0.1:8877}"
DIFY_WEB_PORT="${DIFY_WEB_PORT:-8080}"
export NPC_MEMORY_DATA_DIR NPC_MEMORY_PROJECT_DIR NPC_MEMORY_BIND_ADDR

# Official compose + companion compose, always used together.
npc_compose() {
    [ -f "$DIFY_COMPOSE_DIR/docker-compose.yaml" ] || {
        echo "缺少 Dify ${DIFY_VERSION} 源码（$DIFY_COMPOSE_DIR）。请先运行 scripts/prepare.sh" >&2
        exit 1
    }
    ( cd "$DIFY_COMPOSE_DIR" && docker compose \
        --project-name "$COMPOSE_PROJECT_NAME" \
        --env-file "$DIFY_COMPOSE_DIR/.env" \
        -f "$DIFY_COMPOSE_DIR/docker-compose.yaml" \
        -f "$NPC_PROJECT_DIR/compose.memory.yaml" "$@" )
}
