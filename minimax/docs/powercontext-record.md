# 技术使用记录：PowerContext（任务状态保存与复用）

## 1. 使用方式与版本

| 项 | 值 |
|---|---|
| 组件 | **PowerContext 1.4.1**（Python 包 `powercontext[cli,server]==1.4.1`） |
| 运行方式 | 本地 Server：`powercontext server run --env-file .runtime/powercontext.env` |
| 存储 | 默认 SQLite（`~/.local/share/powercontext/powercontext.db`；未配置外部数据库） |
| 鉴权 | 本地关闭（`POWERCONTEXT_SERVER_ACCESS_MODE=disabled`） |
| 推理能力 | **未配置** generation / embedding 模型；只使用「显式 Memory + 基础读取」能力（题面不需要自动抽取/生成） |
| API | 官方 Python Client（`PowerContextClient`：`create_scope` / `remember_memory` / `list_memory_entries` / `get_scope`） |

配置（脚本 `05_start_powercontext.sh` 自动生成）：

```dotenv
POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1
POWERCONTEXT_SERVER_HTTP_PORT=18080
POWERCONTEXT_SERVER_DASHBOARD_ENABLED=true
POWERCONTEXT_SERVER_ACCESS_MODE=disabled
```

## 2. 状态模型

- 一个交付任务 = 一个 **Scope**（每次 `run_all` 新建，scope_id 写入 `.runtime/scope.json`）。
- 任务状态保存为一条 `kind="state"` 的**显式 Memory**，正文格式：

```text
SDD_STATE_V1:{"task": "...", "done": [...], "todo": [...], "verifications": [...], "updated_at": "..."}
```

- 每次保存都会追加一个新的 Memory（PowerContext 保留历史版本）；读取时模块取 **updated_at 最新**的一条
  （同秒时按验证条数、revision 兜底），并返回 `artifact_id/revision` 供核对。

## 3. 实际写入与读取序列（一次 `run_all` 的完整闭环）

| 步骤 | 动作 | 结果 |
|---|---|---|
| 1 | `init` | 创建 Scope（示例运行：`scp_2e17hr0h6spsttx1k0dx76c2qj`，见 `logs/state-final.json`） |
| 2 | `10_ingest.sh` | 保存**初始状态**（done 2 条 / todo 3 条 / verifications 0）→ `logs/state-initial.json` |
| 3 | `30_tests_before.sh` | 写入 2 条验证：`target-before`（exit 1, passed=false）、`regression-before`（exit 0, passed=true） |
| 4 | `40_tests_after.sh` | 再写入 2 条：`target-after` / `regression-after`（均 exit 0, passed=true）；并更新 done/todo |
| 5 | `50_state_restart.sh` | **新进程**读取 Scope → 读到 4 条验证结果，并重新生成上下文（状态段落包含它们） |

最终状态（`logs/state-final.json`）：

- done：4 条（规格锁定、上下文交给 MiniMax 修改、测试前后结论、验证结果可复用）
- todo：1 条（训练营评测提交确认）
- verifications：4 条，每条含 `name / command / exit_code / passed / code_sha / recorded_at`

## 4. 重启后复用的证据

`logs/state-restart.log`（由 `50_state_restart.sh` 生成，每次 CLI 调用都是独立新进程）关键内容：

```text
# command: python -m sdd_context --runtime .runtime state-show
scope_id: scp_2e17hr0h6spsttx1k0dx76c2qj
updated_at: 2026-10-29T10:55:34+08:00
verifications: 4
 - target-before exit 1 passed False
 - regression-before exit 0 passed True
 - target-after exit 0 passed True
 - regression-after exit 0 passed True
OK: 重启后的新进程成功读取并复用 PowerContext 状态
```

随后 `context` 重新生成，`logs/context-snapshot-with-state.md` 的「任务状态（PowerContext）」段落包含
上述 done/todo/verifications（并标注 Scope 与 revision）。

## 5. 复现命令

```bash
cd minimax
bash scripts/05_start_powercontext.sh          # 启动并等待 ready

export PYTHONPATH="$PWD/sdd-context" POWERCONTEXT_CLIENT_SERVER_URL=http://127.0.0.1:18080
.venv/bin/python -m sdd_context --runtime .runtime init
.venv/bin/python -m sdd_context --runtime .runtime state-save --file sample-task/state-initial.json
.venv/bin/python -m sdd_context --runtime .runtime state-record-test \
  --name target-before --command "cd sample-app && python -m pytest tests/test_target_feature.py -q" \
  --exit-code 1 --passed 0 --code-sha <before_sha>
.venv/bin/python -m sdd_context --runtime .runtime state-show   # 新进程读取（复用）
```

停止 Server：`bash scripts/99_stop_powercontext.sh`。

## 6. 与题面要求的对应

- 「从空状态开始保存任务记录」：新 Scope + 初始状态保存（verifications 为空）。
- 「重启模块后能够读取」：`state-show` 在全新的 CLI 进程中读取成功。
- 「并用于后续上下文或任务处理」：重新生成的 `context.md` 包含从 PowerContext 读取的状态段落。
- 题面只要求「模块重启后读取并使用保存的状态」，不要求恢复完整 Agent 会话；本作品按此范围实现。
