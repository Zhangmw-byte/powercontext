# Dify 部署与运行手册

目标版本：Dify **1.13.3**（官方 Docker Compose）+ 配套服务 **npc-memory**。
正式 DSL：`workflows/memory-npc.yml`（**从实际运行的 Dify 1.13.3 界面导出**，
原件 `/mnt/d/DifyEvidence/memory-npc-export.yml`）。

## 1. 固定版本清单

| 组件 | 版本 |
|---|---|
| Dify | 1.13.3（标签检出 commit `59639ca9b2ba2ba4b32b5feff5149cfc1ad0ba74`） |
| Dify 镜像 | `langgenius/dify-web:1.13.3`、`langgenius/dify-api:1.13.3`、`langgenius/dify-sandbox:0.2.14`、`langgenius/dify-plugin-daemon:0.5.3-local`、`postgres:15-alpine`、`redis:6-alpine`、`ubuntu/squid:latest` |
| DSL | `version: "0.6.0"`（Dify 1.13.3 `CURRENT_DSL_VERSION`） |
| 模型供应商插件 | `langgenius/deepseek` **0.0.26**（唯一标识哈希 `@bdf47cb41e9062bba00d26625d2a795c1874011d8ce64bff738c44b5a31787ea`，随 DSL `dependencies` 声明） |
| 模型 | `deepseek-v4-flash`（chat，temperature 0.7，provider id `langgenius/deepseek/deepseek`） |
| PowerContext SDK | `powercontext[builtin,server]==1.2.0`（`builtin` 不含运行 Server 的 fastmcp 等运行时，故追加 `server`；版本同为 1.2.0） |
| Python | 3.12（服务与测试） |

Dify 使用官方默认数据库（Postgres），未被替换；游戏记忆全部在
PowerContext（真实 SDK + SQLite 持久化，数据目录 `/home/hp/difyfun-data/npc-memory`，D 盘）。

## 2. 部署

```bash
scripts/prepare.sh   # venv+锁定依赖、1.13.3 源码、.env（首次随机密钥，重跑保留；页面端口 8080）
scripts/up.sh        # 官方 compose + compose.memory.yaml，项目名 difyfun，构建并启动
scripts/status.sh    # 容器、/healthz、版本信息
```

| 入口 | 地址 |
|---|---|
| Dify Web | http://127.0.0.1:8080 |
| npc-memory | http://127.0.0.1:8877（仅绑定 127.0.0.1，供验收回查） |
| PowerContext Server | npc-memory 容器内 127.0.0.1:8878，不对宿主机暴露 |

网络：`npc-memory` 加入与 Dify 相同的 compose 网络（`difyfun_default`）；
Dify HTTP 节点经官方 `ssrf_proxy`（squid）转发，`compose.memory.yaml` 仅注入
`docker/squid-npc-memory.conf`（`dstdomain npc-memory` 单目标放行，
squid 只 include `*.conf` 后缀），未全局关闭防护。
容器内访问必须用 `http://npc-memory:8877`，不要写 localhost。

## 3. 导入 DSL 与绑定（每次重新导入都要做）

1. http://127.0.0.1:8080 初始化并登录 → 工作室 → 「导入 DSL 文件」上传
   `workflows/memory-npc.yml`。`dependencies` 声明会提示安装
   `langgenius/deepseek` 0.0.26 插件。
2. 「集成 → 模型供应商」安装/确认 DeepSeek 插件，**在界面填写 API Key**
   （DSL 与仓库不含任何密钥）。
3. 打开「LLM 生成剧情」节点确认模型为 `deepseek-v4-flash`；若显示未授权/
   未安装，重新选择该模型。
4. 确认两个 HTTP 节点地址为 `http://npc-memory:8877/v1/turns/prepare` 与
   `.../v1/turns/commit`（若记忆服务另行部署需改为对应可达地址）。

### 正式导出版 vs 手写初始版的差异（重新导入注意事项）

正式版本以 Dify 导出为准，与初始手稿的运行相关差异：

- LLM 节点：手稿占位 `openai / gpt-4o-mini` → 实际绑定
  `langgenius/deepseek/deepseek / deepseek-v4-flash`；
  顶层 `dependencies` 增加 deepseek 插件声明（含哈希）。
- `http_prepare` / `http_commit`：启用了界面默认重试
  `retry_config {retry_enabled: true, max_retries: 3, retry_interval: 100ms}`。
  注意：commit 节点重试只在请求异常时发生；业务 409（冲突/过期版本）不会被
  当作假成功写入。
- 其余差异仅为画布表现（节点宽高、viewport、features 字段被 Dify 规范化补全），
  不影响行为。

重新导入到其他环境时：模型供应商凭据必须重新绑定；若目标环境未安装
deepseek 插件，导入时勾选依赖安装或手动替换 LLM 节点模型。

## 4. 玩法与操作顺序

工作流表单输入：`player_id`（玩家标识）、`turn_no`（从 1 递增）、`action`（本轮行动）。

初始玩家标识（本次真实运行使用的存档，可直接沿用或换新）：

- `demo-player-a`：已寄存蓝色徽章、约定暗号「月光奶茶」，当前 3 回合。
- `demo-player-b`：全新玩家，1 回合（询问历史，NPC 如实回答无记录）。
- `evidence-squid` / `net-test` / `evidence-direct`：连通测试数据，玩法验收请忽略。

验收操作顺序与预期表现：

1. `demo-player-a`，turn_no=4，任意行动 → NPC 回答应引用「蓝色徽章 / 月光奶茶」
   （来自已保存历史）。
2. **全新** `player_id`（如 `demo-player-c`），turn_no=1，问「我之前来过吗？」
   → 必须回答没有记录，不得编造。
3. 同一 `player_id` + 同一 `turn_no` + 同一 `action` 重复运行 → 返回原结果
   （commit 响应 `already_committed`，不重复写入；`GET /v1/players/{id}/memory`
   的 `turn_count` 不变）。
4. 同一 `turn_no` 但 `action` 不同 → commit 返回 409 `turn_conflict`，
   工作流在该节点失败，不产生新记录。
5. 运行后回查：`curl http://127.0.0.1:8877/v1/players/demo-player-a/memory`。

## 5. DSL 结构校验（可选，导入前）

```bash
docker run --rm -v "$PWD:/work" --entrypoint python \
  langgenius/dify-api:1.13.3 /work/scripts/validate_dsl.py
```

## 6. 常见检查

```bash
scripts/status.sh
curl -s http://127.0.0.1:8877/healthz
scripts/restart-memory.sh   # 只重启记忆服务，存档保留
scripts/down.sh             # 停止但保留数据（无 down -v）
```
