# 一页技术说明：模块结构、上下文选择方式与技术分工

## 1. 模块结构

```text
任务描述 (sample-task/task.md)
        │
        ▼
┌──────────────────────────── sdd-context（Python 包 / CLI）────────────────────────────┐
│  ingest.py ── 读取规格(md)/代码(py)/测试(py)，生成 Document(kind,path,symbols,sha256)    │
│        │                                                                              │
│        ▼                                                                              │
│  seekdb_store.py ── embedded seekdb（pyseekdb 1.4.0.post1）                            │
│     表 sdd_documents(kind,path,title,symbols,content,sha256, FULLTEXT(IK))             │
│     表 sdd_queries(查询审计：任务、查询 ID、命中文档)                                    │
│        │  按任务检索：MATCH(content) AGAINST(检索词) + LIKE 兜底                        │
│        ▼                                                                              │
│  select.py ── 组装上下文包：适用规格 + 相关代码 + 目标/回归测试 + PowerContext 状态       │
│        │                                                                              │
│        ▼                                                                              │
│  context.md / context.json（交给开发助手）                                             │
│                                                                                       │
│  state.py ── PowerContext 1.4.1 显式 Memory：保存 done/todo/verifications，新进程读取    │
└───────────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
MiniMax-M3.1-Flash（经 DeepSeek Harness headless 会话）读取上下文包 → 修改业务代码 → 跑测试
```

## 2. 上下文选择方式（非固定答案）

1. **分词**：从任务描述提取英文标识符（`list_orders`、`page_size` 等）与中文 2/3-gram（`筛选`、`分页` 等），
   不依赖任何分词模型（`tokenize.py`）。
2. **分类检索**：对 `spec`（规格）、`code`（代码）、`test`（测试）三类分别执行
   `SELECT ... MATCH(content) AGAINST(:query IN NATURAL LANGUAGE MODE) ... ORDER BY score DESC LIMIT n`；
   无命中时用 `LIKE` 关键词兜底。
3. **必要来源补齐**：任务里显式引用的 `SPEC-xxx`（正则提取）必须出现在结果中；任务点名的符号
   （本项目为 `list_orders`）必须对应到代码文件。补齐内容来自 seekdb 当前数据，而非硬编码。
4. **状态合并**：从 PowerContext 读取该任务状态（done/todo/verifications），作为上下文的一节。
5. **输出与审计**：生成 `context.md` / `context.json`，并把本次检索写入 `sdd_queries` 与
   `.runtime/db-query.log`（查询 ID、SQL、行数、耗时）。

**验证「不是固定答案」**：`scripts/60_spec_update_demo.sh` 将 SPEC-003 替换为 v2 规格 → 重新 ingest →
上下文命中 v2 新增内容；恢复原规格 → 重新 ingest → 上下文回到原内容（`logs/spec-update-demo.log`）。

## 3. 三种技术的分工

| 技术 | 角色 | 关键实现 |
|---|---|---|
| MiniMax-M3.1-Flash | 开发期编码助手 | 通过 DeepSeek Harness 0.2.1-rc.2 的自定义 provider（`minimax-cn`，Anthropic Messages 协议，pi-ai adapter）以 headless 会话读取上下文包、修改 `sample-app/order_service/orders.py`，会话原始日志可核验（见 `minimax-dev-record.md`） |
| seekdb | 工程资料存储与检索 | pyseekdb embedded 模式（无需独立服务），MySQL 兼容 SQL；`sdd_documents` 上建 `FULLTEXT ... WITH PARSER ik`；检索结果直接用于上下文 |
| PowerContext | 任务状态保存/复用 | 本地 1.4.1 Server（SQLite、显式 Memory）；`kind=state` 的 Memory 保存 `SDD_STATE_V1:{json}`；模块重启后的新进程读取最新 revision |

## 4. 调用入口与输入输出

- 入口：`python -m sdd_context <command> [--runtime DIR] [--powercontext-url URL]`
- 命令：`init` / `ingest` / `context` / `state-show` / `state-save` / `state-record-test` / `state-finalize` /
  `doctor` / `verify`
- 输入：任务描述文件 + seekdb 中的工程资料 + PowerContext 中的任务状态
- 输出：`context.md`（人类可读上下文包）、`context.json`（结构化，含来源路径、得分、覆盖校验）

## 5. 设计取舍

- **不用向量 embedding**：避免在评测环境下载模型/依赖 GPU；全文索引 + 关键词覆盖对本题工程资料足够且可复现。
- **状态只存“可核对的事实”**：done/todo/verifications 均为结构化 JSON；每条验证结果记录命令、退出码、代码 sha256。
- **所有证据落盘**：测试日志记录命令、退出码、代码版本；数据库查询、PowerContext 读写在 `logs/` 可查。
