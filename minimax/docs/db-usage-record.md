# 技术使用记录：seekdb（工程资料存储与检索）

## 1. 使用方式与版本

| 项 | 值 |
|---|---|
| 组件 | **seekdb**（通过 Python SDK **pyseekdb** 使用） |
| SDK 版本 | `pyseekdb==1.4.0.post1`（配套原生库 `pylibseekdb==1.4.0.post2`） |
| 模式 | **embedded**（进程内运行，无需单独启动 server） |
| 数据目录 | `minimax/.runtime/seekdb/`（脚本自动创建，不提交） |
| 数据库 | `sdd` |
| 访问方式 | pyseekdb 底层 MySQL 兼容 SQL（建表/写入/检索）；版本已固定，见 `requirements.txt` |

> 说明：pyseekdb 的公开 `Client` 代理只暴露 collection 操作；本作品需要关系表与 FULLTEXT 索引，
> 因此通过其底层连接执行 SQL。该用法已在本机（Python 3.14.4 + pyseekdb 1.4.0.post1）实测；
> 若更换 pyseekdb 版本需回归 `doctor` 与 `context` 两个命令。

## 2. 表结构

```sql
CREATE TABLE IF NOT EXISTS sdd_documents (
  doc_id VARCHAR(191) NOT NULL PRIMARY KEY,
  kind VARCHAR(16) NOT NULL,            -- spec / code / test
  path VARCHAR(512) NOT NULL,
  title VARCHAR(255) NOT NULL DEFAULT '',
  symbols VARCHAR(512) NOT NULL DEFAULT '',
  content MEDIUMTEXT NOT NULL,          -- 含 PATH/KIND/TITLE/SYMBOLS 头 + 原文
  content_sha VARCHAR(64) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  FULLTEXT INDEX ft_sdd_documents_content (content) WITH PARSER ik
) DEFAULT CHARSET = utf8mb4;

CREATE TABLE IF NOT EXISTS sdd_queries (
  query_id VARCHAR(80) NOT NULL PRIMARY KEY,
  task MEDIUMTEXT NOT NULL,
  created_at VARCHAR(40) NOT NULL,
  hits_json MEDIUMTEXT NOT NULL
) DEFAULT CHARSET = utf8mb4;
```

## 3. 入库的工程资料（实际数据）

`ingest` 从 `sample-task/specs/`、`sample-app/order_service/`、`sample-app/tests/` 读取文件并 upsert（按 doc_id
覆盖旧版本、删除已不存在的文档）。一次运行的入库结果：

```json
{"documents": 9, "upserted": 9, "by_kind": {"spec": 5, "code": 2, "test": 2}}
```

| kind | 数量 | 示例路径 | 内容 sha256（前 12） |
|---|---|---|---|
| spec | 5 | `sample-task/specs/SPEC-003-filter.md` | 见 `logs/doctor.json` |
| code | 2 | `sample-app/order_service/orders.py` | 见 `logs/doctor.json` |
| test | 2 | `sample-app/tests/test_target_feature.py` | 见 `logs/doctor.json` |

完整清单（含每条 sha256）见 `logs/doctor.json` 的 `documents[]`。

## 4. 检索如何参与上下文构造

1. `select.py` 从任务描述提取检索词（中文 2/3-gram + 英文标识符，如 `list_orders`、`page_size`）；
2. 对 spec/code/test 三类分别执行（日志见 `logs/db-query.log`）：

```sql
SELECT doc_id, path, title, symbols, content,
       MATCH(content) AGAINST('list_orders 筛选 分页 …' IN NATURAL LANGUAGE MODE) AS score
FROM sdd_documents
WHERE kind = 'spec'
  AND MATCH(content) AGAINST('list_orders 筛选 分页 …' IN NATURAL LANGUAGE MODE)
ORDER BY score DESC LIMIT 6;
```

3. 无命中时用 `content LIKE '%关键词%'` 兜底；
4. 任务中显式引用的 `SPEC-xxx` 与符号 `list_orders` 必须进入上下文（不足时从 seekdb 补齐）；
5. 检索结果（`title/path/symbols/excerpt/score`）写入 `context.json` 的 `specs[]` / `code[]` / `tests{}`；
   每次检索还会写入 `sdd_queries`（query_id、任务、命中文档）。
6. 覆盖校验：`context`/`verify` 命令输出 `coverage`，要求 `missing_spec_ids=[]` 且代码/目标/回归测试都非空。

## 5. 查询审计（可核对）

一次完整 `run_all` 的数据库查询记录：`logs/db-query.log`

- 共 **88 条** SQL 记录：**56 条 SELECT / 32 条 REPLACE**（每条含时间、耗时 ms、行数、SQL）；
- 覆盖：建表（首次）、文档 upsert、FULLTEXT 检索、LIKE 兜底、查询审计写入、统计查询；
- 查询审计表 `sdd_queries` 保存最近若干次任务检索（可用 `python -m sdd_context doctor` 查看 `recent_queries`）。

示例（`logs/db-query.log` 中截取）：

```json
{"ts":"2026-10-29T10:55:20+08:00","elapsed_ms":1.1,"rows":3,
 "sql":"SELECT kind, COUNT(*) FROM sdd_documents GROUP BY kind"}
```

## 6. 规格更新后重新导入（非固定答案）

`scripts/60_spec_update_demo.sh`：

1. 备份 `SPEC-003-filter.md`；
2. 用 `sample-task/spec-updates/SPEC-003-filter-v2.md` 覆盖并 `ingest`；
3. `context` 输出的 SPEC-003 摘录中出现 v2 新增的 `v2 更新` 内容（`logs/spec-update-demo.log`）；
4. 恢复原规格并再次 `ingest`，上下文不再包含 v2 内容。

## 7. 复现命令

```bash
cd minimax
export PYTHONPATH="$PWD/sdd-context" POWERCONTEXT_CLIENT_SERVER_URL=http://127.0.0.1:18080
.venv/bin/python -m sdd_context --runtime .runtime init
.venv/bin/python -m sdd_context --runtime .runtime ingest
.venv/bin/python -m sdd_context --runtime .runtime doctor     # 查看文档、scope、最近查询
.venv/bin/python -m sdd_context --runtime .runtime context    # 生成上下文
```

## 8. 设计取舍

- **不引入向量 embedding**：题面只要求「存储工程资料或索引，查询、检索结果用于构造任务上下文」；
  全文索引（IK 分词）能覆盖本样例的规格/代码/测试检索，且不依赖模型下载或 GPU，评测环境更易复现。
- **索引随文档更新**：`ingest` 以 doc_id 为单位 REPLACE，规格更新后旧内容被替换，保证上下文使用最新规格。
