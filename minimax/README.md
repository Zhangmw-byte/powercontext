# 规有所依：面向软件持续演进的 SDD 上下文管理系统（`minimax/`）

> MiniMax × OceanBase 赛题作品材料。作品目标：围绕规格驱动开发（SDD）实现一个工程上下文模块，
> 完成一次真实代码修改，并让三项指定技术实际参与：**MiniMax**（开发期生成/修改代码）、
> **seekdb**（工程资料存储与检索）、**PowerContext**（任务状态保存与复用）。

## 0. 一句话说明

本目录包含：一个**可运行的 SDD 上下文模块**（CLI）、一个**带测试的小型业务工程**、一个**验证样例**
（修改前失败 → 修改后通过）、以及**三种技术的真实使用记录**。全流程可一键复现。

- 上下文模块从 seekdb 检索**适用规格 / 相关代码 / 验证测试**，合并 PowerContext 中的**任务状态**，输出上下文包；
- 上下文包交给使用 **MiniMax-M3.1-Flash** 的开发助手（经 DeepSeek Harness headless 会话）完成代码修改；
- 修改后的目标测试从 8 失败 / 2 通过变为 **10 全通过**，回归测试修改前后均为 **16 全通过**；
- 任务状态写入 PowerContext，模块换成新进程后仍能读取并用于后续上下文。

## 1. 目录结构

```text
minimax/
├── README.md                     # 本文件（运行说明）
├── requirements.txt              # 依赖版本
├── scripts/                      # 一键复现脚本（安装/启动/导入/上下文/测试/状态/规格更新）
├── sdd-context/                  # SDD 上下文模块（Python 包 + CLI）
│   └── sdd_context/
│       ├── cli.py                # 调用入口：init / ingest / context / state-* / doctor / verify
│       ├── seekdb_store.py       # seekdb（embedded）存储 + FULLTEXT 检索
│       ├── ingest.py             # 规格/代码/测试 → seekdb
│       ├── select.py             # 任务 → 上下文包（context.md / context.json）
│       ├── state.py              # PowerContext 显式 Memory 读写（状态保存/复用）
│       └── tokenize.py           # 轻量分词（无外部模型依赖）
├── sample-app/                   # 被修改的业务工程（Python + pytest，可运行）
│   ├── order_service/orders.py   # 业务代码（final：已由 MiniMax 完成修改）
│   └── tests/                    # 目标功能测试 / 回归测试
├── sample-task/                  # 验证样例
│   ├── task.md                   # 任务描述（要改什么、哪些行为必须保持）
│   ├── specs/                    # 规格条目 SPEC-001 ~ SPEC-005
│   ├── spec-updates/             # 规格更新演示用的 v2 规格
│   ├── before/orders.py          # 修改前代码快照
│   ├── after/orders.py           # 修改后代码快照
│   ├── diff.patch                # 修改前后 diff
│   └── state-initial.json        # 初始任务状态
├── docs/                         # 技术说明与使用记录（评分核对用）
│   ├── tech-note.md              # 一页技术说明
│   ├── minimax-dev-record.md     # MiniMax 开发记录（含会话证据与 diff 映射）
│   ├── db-usage-record.md        # seekdb 使用记录
│   ├── powercontext-record.md    # PowerContext 状态写入与复用记录
│   ├── verification.md           # 六项必做验收对照
│   └── session-logs/             # MiniMax 会话原始日志 / 时间线 / 提示词
└── logs/                         # 本仓库内已提交的测试与运行日志（复现时会被覆盖为最新）
```

## 2. 环境要求

- Linux / macOS；Python **3.11–3.14**（本机验证版本：3.14.4）；pip 可访问网络。
- 依赖版本见 `requirements.txt`：`powercontext[cli,server]==1.4.1`、`pylibseekdb==1.4.0.post2`、
  `PyMySQL==1.2.0`、`numpy==2.5.4`、`pytest==9.2.0` 等。
- 需要 `powercontext` 与 `pyseekdb` 的 **embedded** 能力；`pyseekdb` 由安装脚本用 `--no-deps` 安装，
  原因见下。

> ⚠️ 关于 `pyseekdb` 安装：Python 3.14 下 `pip install pyseekdb` 的默认依赖会拉取
> `sentence-transformers → torch → nvidia-cudnn`（数 GB）。本项目只使用 pyseekdb 的 embedded SQL 能力，
> 不需要默认 embedding 依赖，因此 `scripts/00_setup.sh` 使用
> `pip install --no-deps pyseekdb==1.4.0.post1`，并显式安装运行所需的最小依赖（见 `requirements.txt`）。

## 3. 一键复现（评测路径）

```bash
cd minimax

# 1) 创建 .venv 并安装依赖（只需一次，需联网）
bash scripts/00_setup.sh

# 2) 全流程验证（约 30 秒；会自动清空 .runtime 并新建 PowerContext Scope）
bash scripts/run_all.sh
```

`run_all.sh` 依次执行并输出每一步结果：

| 步骤 | 脚本 | 产物 / 证据 |
|---|---|---|
| 1/7 启动本地 PowerContext Server（SQLite、显式记忆） | `05_start_powercontext.sh` | `logs/powercontext-server.log` |
| 2/7 初始化运行时 + 导入规格/代码/测试到 seekdb | `10_ingest.sh` | `logs/doctor.json`、`logs/db-query.log` |
| 3/7 按任务生成上下文包 | `20_context.sh` | `logs/context-snapshot.md/json` |
| 4/7 修改前测试（目标失败 / 回归通过）+ 写状态 | `30_tests_before.sh` | `logs/tests-before-*.log` |
| 5/7 修改后测试（全部通过）+ 状态收尾 | `40_tests_after.sh` | `logs/tests-after-*.log`、`logs/state-final.json` |
| 6/7 重启后状态复用（新进程读取） | `50_state_restart.sh` | `logs/state-restart.log`、`logs/context-snapshot-with-state.md` |
| 7/7 规格更新 + 重新导入演示 | `60_spec_update_demo.sh` | `logs/spec-update-demo.log` |

结束时输出「全部验证通过」，并留下上述日志。停止本地 PowerContext：`bash scripts/99_stop_powercontext.sh`。

一键复现的退出码为 0 表示六项必做项对应的验证全部成功（见 `docs/verification.md`）。

## 4. 上下文模块调用入口

模块包：`sdd-context/`（通过 `PYTHONPATH=minimax/sdd-context` 使用）。

```bash
cd minimax
export PYTHONPATH="$PWD/sdd-context" POWERCONTEXT_CLIENT_SERVER_URL=http://127.0.0.1:18080

python -m sdd_context --runtime .runtime init          # 建 seekdb 库表 + PowerContext Scope
python -m sdd_context --runtime .runtime ingest        # 规格/代码/测试 → seekdb
python -m sdd_context --runtime .runtime context       # 任务 → 上下文包
python -m sdd_context --runtime .runtime state-show    # 读取 PowerContext 状态
python -m sdd_context --runtime .runtime doctor        # 环境/文档/Scope/查询记录
python -m sdd_context --runtime .runtime verify        # 校验上下文覆盖
```

**输入**：`sample-task/task.md`（任务描述）+ seekdb 中的工程资料 + PowerContext 中的任务状态。
**输出**：`.runtime/context.md`（给开发助手的上下文包）与 `.runtime/context.json`（结构化上下文）。

`context.json` 关键字段：

| 字段 | 含义 |
|---|---|
| `task` | 任务描述 |
| `specs[]` | 适用规格：`title` / `path` / `spec id` / `score` / `excerpt` |
| `code[]` | 需要修改的代码：`path` / `symbols` / `excerpt` |
| `tests.target[]` / `tests.regression[]` | 目标功能测试 / 回归测试来源 |
| `state` | PowerContext 中的任务状态：`done[]` / `todo[]` / `verifications[]`（含 scope/revision） |
| `seekdb.query_id` / `retrieval.terms` | 本次检索的数据库查询 ID 与检索词 |
| `coverage` | 覆盖校验：引用的 SPEC ID 是否齐全、代码/目标/回归是否都选出 |

## 5. 三种技术如何参与（对照题面 2.2）

| 技术 | 必须承担的作用 | 本作品中的实际参与 | 证据 |
|---|---|---|---|
| **MiniMax** | 参与代码生成/修改 | 开发期由 **MiniMax-M3.1-Flash**（经 DeepSeek Harness 0.2.1-rc.2 的 headless 会话，`minimax-cn` 路由/Anthropic Messages 协议）读取本模块输出的上下文包并完成 `orders.py` 修改 | `docs/minimax-dev-record.md`、`docs/session-logs/`、`sample-task/diff.patch` |
| **seekdb** | 存储工程资料/索引，查询检索用于上下文 | embedded seekdb（pyseekdb 1.4.0.post1）建表 + FULLTEXT(IK) 索引，保存 5 规格 + 2 代码 + 2 测试，按任务 `MATCH ... AGAINST` 检索并用于上下文 | `docs/db-usage-record.md`、`logs/db-query.log`、`logs/doctor.json` |
| **PowerContext** | 保存任务进展/验证结果，后续运行读取使用 | 本地 1.4.1 Server（SQLite、显式 Memory）；保存初始状态、4 条测试验证结果、最终 done/todo；新进程重启后读取并写入上下文 | `docs/powercontext-record.md`、`logs/state-restart.log`、`logs/state-final.json` |

## 6. 验证样例

- 任务：`sample-task/task.md` —— 在订单服务 `list_orders` 上实现**状态筛选（SPEC-003）**与**分页（SPEC-004）**，
  并保持既有行为（SPEC-001/002/005）。
- 初始（修改前）代码：`sample-task/before/orders.py`；最终代码：`sample-app/order_service/orders.py`
  （= `sample-task/after/orders.py`）；差异：`sample-task/diff.patch`。
- 测试结果（命令、退出码、代码版本均记录在日志中）：

| 阶段 | 目标测试 `test_target_feature.py` | 回归测试 `test_regression.py` | 代码 sha256 |
|---|---|---|---|
| 修改前 | **8 failed, 2 passed**（exit 1） | **16 passed**（exit 0） | `8112087d38…708729` |
| 修改后 | **10 passed**（exit 0） | **16 passed**（exit 0） | `aaa2f4d17a…003887` |

- 重置方法：`bash scripts/30_tests_before.sh` 会自动切换到修改前代码并在结束后恢复修改后代码。

## 7. 六项必做验收对照（摘要）

| 验收项 | 本作品情况 | 证据 |
|---|---|---|
| 能够运行 | 干净环境 `00_setup.sh` + `run_all.sh` 退出码 0 | `logs/run-all.log` |
| MiniMax 实际参与 | 完整会话记录（含模型 config）、上下文输入、代码修改与 diff 对应 | `docs/minimax-dev-record.md` |
| 上下文正确 | 规格/代码/测试/状态齐全；规格更新并重导入后上下文跟随变化 | `logs/context-snapshot-with-state.md`、`logs/spec-update-demo.log` |
| 数据库实际参与 | 9 条工程资料入库，检索结果用于上下文；SQL 记录 88 条 | `logs/db-query.log`、`logs/doctor.json` |
| 状态能够复用 | 新进程读取到 4 条验证结果并写入上下文 | `logs/state-restart.log` |
| 代码修改有效 | 修改前目标测试失败、修改后全通过，回归保持通过；测试文件未改 | `logs/tests-*.log`、`sample-task/diff.patch` |

完整对照见 `docs/verification.md`。

## 8. 已知限制

- PowerContext 未配置生成/embedding 模型，因此只启用「显式 Memory + 全文召回」能力；本题只需要显式保存/读取任务状态，满足要求。
- 题面说明「任务状态复用」只要求模块重启后读取并使用保存的状态，本作品不恢复完整 Agent 会话（题面不要求）。
- 上下文检索使用 seekdb 全文索引（IK 分词）而非向量 embedding：可复现、无需下载模型、无网络依赖；对本题的工程资料检索足够。
- 依赖安装需要网络；Python 3.14 下请严格按 `00_setup.sh` 的方式安装 pyseekdb（避免 torch 依赖）。

## 9. 关键约束：不提交真实凭据

本目录所有文件均不含真实 Token / API Key：MiniMax 的 Token Plan 密钥只通过运行环境变量
`MINIMAX_CN_API_KEY` 注入（未写入仓库）；PowerContext 本地 Server 关闭鉴权；seekdb 使用本地 embedded 模式，
无数据库密码。
