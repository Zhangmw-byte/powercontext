# 会记住你的校园冒险 NPC（Dify × OceanBase 赛道作品）

校园异世界图书馆管理员 NPC。玩家寄存物品、约定暗号、作出选择；
管理员之后的每一句回应都基于 **真实存档**——没有记录的历史绝不编造。

## 架构

```
Dify 1.13.3 工作流 (workflows/memory-npc.yml)
   │  HTTP 读取存档 → 解析 → 判断已有结果?
   │    ├─ 是 → 直接返回已保存的正式回复
   │    └─ 否 → LLM 依据存档生成剧情 → HTTP 保存 → 返回保存结果
   ▼
npc-memory 配套服务 (FastAPI, 端口 8877, 仅绑定 127.0.0.1)
   ▼  官方 powercontext Python SDK（HTTP 客户端）
PowerContext Server（同容器内拉起, 127.0.0.1:8878）
   ▼
真实 SQLite 持久化（卷: $NPC_MEMORY_DATA_DIR → /data）
```

- 每个玩家一个 PowerContext scope（玩家间天然隔离）。
- 每个已保存回合是一条 memory entry（JSON 载荷，完整保留中文、引号、多行）。
- Dify 默认数据库不受影响（官方 Postgres）；游戏记忆全部在 PowerContext。
- 固定版本：Dify `1.13.3`（commit `59639ca9b2ba2ba4b32b5feff5149cfc1ad0ba74`，
  镜像 `langgenius/dify-api:1.13.3` / `langgenius/dify-web:1.13.3`）、
  Python 3.12、`powercontext[builtin,server]==1.2.0`。
- 实际运行模型：`deepseek-v4-flash`（chat 模式），经官方插件
  `langgenius/deepseek` 版本 `0.0.26@bdf47cb4…31787ea` 调用；
  模型凭据由使用者在 Dify 界面配置，未随仓库分发。

> 说明：`builtin` extra 不含运行 PowerContext Server 所需的 fastmcp 等运行时，
> 因此锁定文件在 `powercontext==1.2.0` 上追加 `server` extra；主存储仍是真实 SDK + SQLite。

## 快速开始

```bash
scripts/prepare.sh        # 依赖、1.13.3 源码、.env（首次生成随机密钥，重跑保留）
scripts/test.sh           # 真实 PowerContext 后端测试（临时数据库）
scripts/up.sh             # 官方 Compose + 配套服务，项目名 difyfun
scripts/status.sh         # 容器与记忆服务状态
scripts/restart-memory.sh # 只重启记忆服务，不删存档
scripts/down.sh           # 停止容器，保留数据（绝不 down -v）
```

Dify 页面：`http://127.0.0.1:8080`；记忆服务：`http://127.0.0.1:8877`（仅本机）。

## 玩法输入

工作流表单输入三项：

| 字段 | 含义 |
|---|---|
| `player_id` | 玩家标识（字母数字及 `_.:-`，≤64） |
| `turn_no` | 从 1 开始递增的正整数 |
| `action` | 本轮行动或对话 |

## 记忆服务 API

- `GET /healthz` — 探测 PowerContext Server readiness。
- `POST /v1/turns/prepare` — 只读：返回上下文、当前 revision、该回合是否已有已保存结果（读取不创建任何记录）。
- `POST /v1/turns/commit` — 写入本轮回复；幂等重放、冲突拒绝、版本防覆盖；返回已保存的正式回复与引用。
- `GET /v1/players/{player_id}/memory` — 回查玩家存档、回合与版本。

规则：同一回合重复提交返回原结果不重复写入；同回合号不同行动返回 409；
turn_no 必须大于已保存最大回合号；`expected_revision` 过期返回 409。
模型调用失败时 Dify 不会调用 commit，因此不会写入假成功记录。

历史窗口：默认仅最近 12 回合送入模型（`NPC_MEMORY_HISTORY_WINDOW`），
完整存档始终保留在 PowerContext（`GET /v1/players/{id}/memory` 可回查全部）。

## 工作流 DSL

`workflows/memory-npc.yml` 为 **Dify 界面实际运行后导出的版本**（正式版），
已在本作品 Docker 环境的官方镜像内完成节点 schema 校验。
导入后需在界面重新绑定 DeepSeek 模型凭据，并在设置中确认 HTTP 节点
使用 `http://npc-memory:8877`（同网络服务名）。差异与重绑清单见
`docs/dify-setup.md`。

## 文档

- `docs/dify-setup.md` — 正式运行手册：Docker 部署、DSL 导入、模型与地址绑定、初始玩家、操作顺序与预期。
- `docs/verification.md` — 已执行/未执行验证清单（不夸大）。
- `docs/evidence/` — 验证证据（测试输出、DSL 校验、真实运行回查记录）。

## 边界声明

- 后端测试、容器连通测试、DSL 官方镜像校验均已实际执行，结果见 `docs/verification.md`。
- Dify 工作流由使用者在实际环境中完成导入、模型绑定与真实模型运行；
  运行记录（玩家 `demo-player-a` / `demo-player-b` 的记忆回查、隔离、重启恢复）
  已整理至 `docs/evidence/runtime-recall.txt`。
- 模型凭据始终由使用者在界面配置，本仓库不包含任何密钥、运行数据库或运行日志。
