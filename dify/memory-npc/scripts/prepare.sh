#!/usr/bin/env bash
# Prepare the memory-npc project: Python env, pinned Dify runtime source,
# compose .env with first-run secrets (existing keys/data are preserved).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

echo "== npc-memory prepare (Dify ${DIFY_VERSION}, powercontext ${POWERCONTEXT_VERSION}) =="

# 1. Python 3.12 virtualenv with locked dependencies.
if [ ! -x "$NPC_PROJECT_DIR/.venv/bin/python" ]; then
    UV_BIN="$(command -v uv || true)"
    [ -n "$UV_BIN" ] || { echo "需要 uv（https://docs.astral.sh/uv/）" >&2; exit 1; }
    "$UV_BIN" venv --python 3.12 "$NPC_PROJECT_DIR/.venv"
fi
UV_BIN="$(command -v uv || true)"
if [ -n "$UV_BIN" ]; then
    "$UV_BIN" pip install --python "$NPC_PROJECT_DIR/.venv/bin/python" -r "$NPC_PROJECT_DIR/requirements.lock"
else
    "$NPC_PROJECT_DIR/.venv/bin/python" -m pip install -r "$NPC_PROJECT_DIR/requirements.lock"
fi
echo "Python venv 就绪: $("$NPC_PROJECT_DIR/.venv/bin/python" --version)"

# 2. Pinned official Dify runtime source at tag 1.13.3.
if [ ! -d "$DIFY_RUNTIME_DIR/.git" ]; then
    echo "下载 Dify ${DIFY_VERSION} 源码到 $DIFY_RUNTIME_DIR ..."
    git clone --branch "$DIFY_VERSION" --depth 1 "$DIFY_GIT_URL" "$DIFY_RUNTIME_DIR"
else
    DETACHED_TAG="$(git -C "$DIFY_RUNTIME_DIR" describe --tags --exact-match 2>/dev/null || true)"
    if [ "$DETACHED_TAG" != "$DIFY_VERSION" ]; then
        echo "警告: $DIFY_RUNTIME_DIR 当前不在标签 $DIFY_VERSION（当前: ${DETACHED_TAG:-非标签}）。不自动切换。" >&2
    fi
fi
echo "Dify 源码 commit: $(git -C "$DIFY_RUNTIME_DIR" log -1 --format='%H (%d)')"

# 3. Compose .env: copy example, then rotate only still-placeholder secrets.
ENV_FILE="$DIFY_COMPOSE_DIR/.env"
gen_secret() {
    head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c "${1:-32}"
}
if [ ! -f "$ENV_FILE" ]; then
    cp "$DIFY_COMPOSE_DIR/.env.example" "$ENV_FILE"
    echo "已创建 $ENV_FILE"
    # 按变量名替换（不依赖官方示例中的占位字符串）；本分支仅在首次创建时执行。
    sed -E -i \
        -e "s|^SECRET_KEY=.*|SECRET_KEY=$(gen_secret 43)|" \
        -e "s|^PLUGIN_DAEMON_KEY=.*|PLUGIN_DAEMON_KEY=$(gen_secret 42)|" \
        -e "s|^(PLUGIN_DIFY_INNER_API_KEY=).*|\1$(gen_secret 40)|" \
        "$ENV_FILE"
    NEW_DB_PW="$(gen_secret 24)"
    # 同样按变量名轮换示例中的默认口令（含 URL 内嵌口令），不依赖占位字符串本身。
    sed -E -i \
        -e "s|^(DB_PASSWORD=).*|\1${NEW_DB_PW}|" \
        -e "s|^(REDIS_PASSWORD=).*|\1${NEW_DB_PW}|" \
        -e "s|^(OCEANBASE_VECTOR_PASSWORD=).*|\1${NEW_DB_PW}|" \
        -e "s|^(QDRANT_API_KEY=).*|\1${NEW_DB_PW}|" \
        -e "s|^(PGVECTOR_PASSWORD=).*|\1${NEW_DB_PW}|" \
        -e "s|^(PGVECTO_RS_PASSWORD=).*|\1${NEW_DB_PW}|" \
        -e "s|^(PGVECTOR_POSTGRES_PASSWORD=).*|\1${NEW_DB_PW}|" \
        -e "s|^(ALIBABACLOUD_MYSQL_PASSWORD=).*|\1${NEW_DB_PW}|" \
        -e "s|^(RELYT_PASSWORD=).*|\1${NEW_DB_PW}|" \
        -e "s|^(CHROMA_SERVER_AUTHN_CREDENTIALS=).*|\1${NEW_DB_PW}|" \
        -e "s|^(CELERY_BROKER_URL=.*://:)[^@/]+(@.*)|\1${NEW_DB_PW}\2|" \
        "$ENV_FILE"
    echo "已生成随机 SECRET_KEY / PLUGIN_DAEMON_KEY / PLUGIN_DIFY_INNER_API_KEY / 数据库口令（仅首次）"
else
    echo "保留现有 $ENV_FILE 中的密钥与数据"
fi
grep -q "^EXPOSE_NGINX_PORT=" "$ENV_FILE" && \
    sed -E -i "s|^EXPOSE_NGINX_PORT=.*|EXPOSE_NGINX_PORT=${DIFY_WEB_PORT}|" "$ENV_FILE" || \
    echo "EXPOSE_NGINX_PORT=${DIFY_WEB_PORT}" >>"$ENV_FILE"

# 4. Companion runtime data directory (D-drive via $HOME by default).
mkdir -p "$NPC_MEMORY_DATA_DIR"
echo "记忆服务数据目录: $NPC_MEMORY_DATA_DIR"

echo "== prepare 完成 =="
