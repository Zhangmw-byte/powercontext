# 六项必做验收对照（评审核对用）

题面：六项必做全部通过得 20 分，任一项不通过得 0 分。以下逐项给出本作品的做法与可核对证据。

## 总览

| # | 验收项 | 是否满足 | 核对方式（评审可直接执行/查看） |
|---|---|---|---|
| 1 | 能够运行 | ✅ | 干净环境执行 `bash scripts/00_setup.sh && bash scripts/run_all.sh`，退出码 0；见 `logs/run-all.log` |
| 2 | MiniMax 实际参与 | ✅ | `docs/minimax-dev-record.md` + `docs/session-logs/`（原始会话含模型 config、上下文输入、39 次工具调用）+ `sample-task/diff.patch` |
| 3 | 上下文正确 | ✅ | `logs/context-snapshot-with-state.md`（规格/代码/测试/状态齐全）；`logs/spec-update-demo.log`（规格更新后上下文跟随变化） |
| 4 | 数据库实际参与 | ✅ | `docs/db-usage-record.md`；`logs/db-query.log`（88 条 SQL：56 SELECT / 32 REPLACE）；`logs/doctor.json`（9 条文档） |
| 5 | 状态能够复用 | ✅ | `logs/state-restart.log`：新进程读取到 4 条验证结果并写入上下文 |
| 6 | 代码修改有效 | ✅ | `logs/tests-before-*.log`（目标 8 失败 / 回归 16 通过）→ `logs/tests-after-*.log`（目标 10 通过 / 回归 16 通过）；`sample-task/diff.patch` |

## 逐项说明

### 1. 能够运行

- 运行说明：`README.md` 第 3 节。
- 初始化：`00_setup.sh` 创建 `.venv` 并按锁定版本安装依赖（无需任何未交付的本地文件或状态）。
- 运行：`run_all.sh` 从空 `.runtime` 开始：启动 PowerContext → 建 seekdb 库表 → 导入资料 → 生成上下文 →
  修改前测试 → 修改后测试 → 状态复用 → 规格更新演示。
- 退出码 0（`logs/run-all.log` 末行「全部验证通过」）。

### 2. MiniMax 实际参与

- 接入方式：DeepSeek Harness 0.2.1-rc.2，自定义 headless profile `minimax-dev`；
  provider `minimax-cn`（pi-ai 内置 MiniMax CN 路由，Anthropic Messages 协议，
  目录默认 endpoint `https://api.minimaxi.com/anthropic`），模型 **`MiniMax-M3.1-Flash`**；
  密钥通过启动环境变量 `MINIMAX_CN_API_KEY` 注入（Token Plan），未进入仓库。
- 开发记录：`docs/minimax-dev-record.md`。
- 原始证据：`docs/session-logs/minimax-session-162c5a15.jsonl`（231 事件、39 次工具调用、模型 config 明示
  `{"provider":"minimax-cn","model":"MiniMax-M3.1-Flash"}`）；时间线见同目录 `minimax-session-timeline.md`；
  提供的提示词（含任务与上下文包）见 `minimax-task-prompt.md`。
- 与提交 diff 的对应：`sample-task/diff.patch`（98 行），实现 SPEC-003（筛选）与 SPEC-004（分页），
  其余函数未改；测试文件未改。

### 3. 上下文正确

- 上下文包含任务要求的四类来源：
  - 适用规格：SPEC-001 ~ SPEC-005（覆盖校验 `missing_spec_ids=[]`）；
  - 需要修改的代码：`sample-app/order_service/orders.py`（符号 `list_orders` 等）；
  - 验证测试：目标功能测试 `test_target_feature.py` + 回归测试 `test_regression.py`；
  - 已完成 / 待办 / 已有验证结果（来自 PowerContext）。
- 输出位置：`.runtime/context.md`、`.runtime/context.json`；提交快照：`logs/context-snapshot*.md/json`。
- 更新后跟随：`60_spec_update_demo.sh` 把 SPEC-003 换成 v2 版本并重新导入，上下文命中 v2 新增内容；
  恢复后不再出现（`logs/spec-update-demo.log`）。

### 4. 数据库实际参与

- seekdb（pyseekdb 1.4.0.post1，embedded）中实际保存 9 条工程资料：
  5 条规格 + 2 条代码 + 2 条测试（`logs/doctor.json` 的 `doc_counts` 与 sha256）。
- 表结构：`sdd_documents`（含 `FULLTEXT INDEX ... WITH PARSER ik`）、`sdd_queries`（查询审计）。
- 实际查询：`MATCH(content) AGAINST(... IN NATURAL LANGUAGE MODE)` 检索结果写入上下文；
  `logs/db-query.log` 共 88 条 SQL 记录，每条含时间、耗时、行数、SQL。
- 详见 `docs/db-usage-record.md`。

### 5. 状态能够复用

- 从空状态开始：`10_ingest.sh` 保存初始状态（done/todo/verifications=[]）。
- 4 次测试结果写入：`30_tests_before.sh` / `40_tests_after.sh` 调用 `state-record-test`，
  每条记录命令、退出码、passed、代码 sha256、时间。
- 「重启」：`50_state_restart.sh` 启动**新的 CLI 进程**（每次 CLI 调用都是新进程）读取 PowerContext，
  得到 4 条验证结果（`logs/state-restart.log`）；随后重新生成上下文，状态段落包含这些结果
  （`logs/context-snapshot-with-state.md`）。
- 详见 `docs/powercontext-record.md`。

### 6. 代码修改有效

| 阶段 | 命令 | 退出码 | 结果 | 代码版本（sha256） |
|---|---|---|---|---|
| 修改前·目标 | `pytest tests/test_target_feature.py -q` | 1 | 8 failed, 2 passed | `8112087d38…708729` |
| 修改前·回归 | `pytest tests/test_regression.py -q` | 0 | 16 passed | `8112087d38…708729` |
| 修改后·目标 | `pytest tests/test_target_feature.py -q` | 0 | 10 passed | `aaa2f4d17a…003887` |
| 修改后·回归 | `pytest tests/test_regression.py -q` | 0 | 16 passed | `aaa2f4d17a…003887` |

- 目标测试修改前失败的原因是**功能未实现**（`list_orders` 忽略 status/page/page_size），不是环境错误；
- 测试集修改前后一致（测试文件未被修改）；未删除断言、未跳过测试；
- 修改前代码快照 `sample-task/before/orders.py`、修改后 `sample-task/after/orders.py`、diff `sample-task/diff.patch`。

## 评审快速复现

```bash
cd minimax
bash scripts/00_setup.sh
bash scripts/run_all.sh          # 期望退出码 0、末行“全部验证通过”
bash scripts/99_stop_powercontext.sh
```

若只核对上下文（不重启 PowerContext）：保持 Server 运行后执行
`PYTHONPATH=sdd-context .venv/bin/python -m sdd_context --runtime .runtime context`。
