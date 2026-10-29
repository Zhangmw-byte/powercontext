# 开发说明

面向贡献者的实现细节与运行/调试指引。需求与架构见 `requirements.md`,验证结果见 `verification.md`。

## 开发过程记录

本次按"设计 → SDK 核对 → 编码 → 调试 → 验证 → 交付整理"推进,如实记录:

1. **基线核对**:确认工作区 `/home/hp/powercontext-qoder`、分支 `feat/qoder-study-coach`,其 HEAD 提交 `d647275c` 与 `ecosystem-official/2026-competition-ecosystem` 完全一致,工作树干净。项目资产全部置于 `qoder/study-coach/`。
2. **需求设计**:先产出 `docs/requirements.md`,定义分层架构、scope=学习者隔离、记忆条目 `kind`+`text` 编码取舍与验收方法,展示设计经确认后再编码。
3. **SDK 核对**:用 Python 3.12 venv 实装 `powercontext[builtin]==1.2.0`,直接 introspect 公开 API 并跑最小探测,确证:入口 `open_builtin_contexts(BuiltinConfig(SQLiteConfig(...)))`、`contexts.get(scope)`、`ctx.artifacts.memory`(`MemoryService`);离线可用(inference 默认 None,仅 FTS5);内容级幂等去重;`forget` 后条目仍在 `head_entries` 需按 manifest `state` 过滤;`remember` 必须基于最新 revision 否则 `RevisionConflictError`;历史经 `revisions/entries/changes` 回查。此阶段未修改任何 SDK 源码。
4. **编码**:以 `uv` 重建独立环境(`pyproject.toml` + `uv.lock`)。分 `models.py`(校验与编解码)、`memory_repo.py`(SDK 唯一交互点)、`review.py`(规则算法)、`app.py`(路由与 lifespan)、`static/`(中文单页)、`scripts/`、`tests/`。
5. **调试**:记忆层首次冒烟发现"复习结果重复提交仍推进 SM-2"(因基于新状态重算),加入 `_last_result` 结果指纹修复;`list_records` 剥离内部 `_v`/`_last_result`。清理了探测用的临时库。
6. **验证**:自动测试 18 项全过;真实 HTTP 冒烟与重启持久化通过;两学习者完整样例真实运行(见 `verification.md` A 段)。
7. **交付整理**:补全 README、verification、development,建 `docs/evidence/`,核对 `.gitignore` 覆盖 `.venv/.data/*.db/缓存/日志` 且保留 `uv.lock`。

## 验证状态:自动 vs 人工(务必区分)

- **自动验证(已执行、通过)**:pytest 18 项;uvicorn+curl 冒烟(创建/去重/清单/回写/422/隔离/重启);两学习者样例;前端资源 200;`app.js` 引用的 26 个 DOM id 与 `index.html` 静态比对一致。
- **人工浏览器验证(尚未执行,未确认)**:本环境无可用无头浏览器(未安装 chromium/playwright),因此**未在浏览器中逐项点击验证**交互效果。`verification.md` D 段列出待人工确认清单,当前一律视为"未通过",不得记为已通过。

## 环境

- Python 3.12(实测 3.12.16)
- `uv`(实测 0.13.6)管理独立虚拟环境 `.venv`
- 依赖以 `pyproject.toml` + `uv.lock` 锁定:`powercontext[builtin]==1.2.0`、`fastapi`、`uvicorn[standard]`、`httpx`;开发组 `pytest`、`pytest-asyncio`

```bash
bash scripts/prepare.sh          # = uv sync --frozen
.venv/bin/python -m pytest -q    # 直接跑测试
bash scripts/start.sh            # 启动服务
```

三个脚本都以 `dirname BASH_SOURCE` 定位自身、再取 `..` 为项目根,因此从任意工作目录调用都能正确运行。

## PowerContext 使用要点(实测)

SDK 公开 API 较薄,以下是本项目踩过的关键点:

1. **入口**:`open_builtin_contexts(BuiltinConfig(database=SQLiteConfig(url="sqlite+aiosqlite:///...")))` 是 async context manager,产出 `RelationalContexts`。`inference` 配置默认全 `None` → 只建 FTS5 索引,离线可跑。必须使用 `sqlite+aiosqlite` 方言(SQLAlchemy async + aiosqlite)。
2. **scope 隔离**:`await contexts.get(scope_id)` 按 scope 缓存 `PowerContext`。`scope_id` 为经校验的非空字符串。本项目:
   - 学习者注册表 → 固定 scope `study-coach-registry`
   - 每位学习者 → `learner-<learner_id>`
3. **记忆服务**:`ctx.artifacts.memory`(`MemoryService`),`ctx.artifacts.memory_artifact_id` 默认 `"memory"`。全部方法 async。
4. **写入**:`remember(memory=<head或None>, mode="append", entries=[MemoryEntryInput(kind, text)])`。
   - `memory` 必须是**最新** revision,否则抛 `RevisionConflictError`。故每次写前用 `head_entries()` 取回最新头。
   - `mode="extract"` 需要 LLM candidate_pipeline,离线禁用。
5. **幂等去重(内建)**:对同一 head 追加内容完全相同的条目不会新增(`entry_content_hash` 去重)。因此条目文本必须**不含服务端易变时间戳**,才能靠"相同请求 → 相同文本"实现去重。复习结果另用 `_last_result` 指纹在应用层拦截重放。
6. **读取**:`head_entries("memory")` 返回 `(Memory, [MemoryEntryVersion])`。**注意**:`forget` 置 `state="inactive"` 后,`head_entries`/`entries` 仍列出该条目;必须按 `mem.content.manifest.entries[*].state` 在应用层过滤活动条目。
7. **历史**:`revisions(mem)` 列出各 revision;`revision(ref)` + `entries(rev)` 可逐修订回查正文;`changes(mem)` 给每个 revision 的 add/revise/deactivate 变更明细。
8. **检索**:`search(query, memories=[head], mode="fts")`;离线强制 `vector/hybrid` 抛 `CapabilityNotSupportedError`。清单主链路用 `head_entries` 枚举 + 规则算法,保证确定性;`search` 非必需。

## 领域字段编码

SDK 条目只有 `kind` + `text`。业务字段编码为带 `_v` 版本号的规范 JSON(`json.dumps(..., ensure_ascii=False, sort_keys=True)`):

- `kind="learner"`:`{learner_id, name}`
- `kind="preference"`:`{daily_minutes, goal, preferences}`
- `kind="record"`:`{course, topic, note, mastery(0–5), studied_on, last_review, review_count, interval, ease, lapses}`

`list_records` 读取时剥离内部字段(`_v`、`_last_result`)。

## 复习算法(`app/review.py`)

- `apply_quality`:SM-2 风格更新 `interval/ease/reps/lapses`,`mastery` 取回忆质量。
- `generate_plan`:到期判定(`last_review + interval <= today`,未复习视为到期)→ 优先级 = `(5-mastery)*2 + min(逾期,30) + 遗忘次数` → 按 `daily_minutes` 预算裁剪,每条附规则化理由。

## 路由一览

| 方法 | 路径 |
|---|---|
| GET | `/api/learners` |
| POST | `/api/learners` |
| GET | `/api/learners/{id}/overview` |
| GET/PUT | `/api/learners/{id}/preference` |
| GET/POST | `/api/learners/{id}/records` |
| GET | `/api/learners/{id}/review-plan?date=YYYY-MM-DD` |
| POST | `/api/learners/{id}/review-result` |
| GET | `/api/learners/{id}/memory`(验证视图) |
| GET | `/api/learners/{id}/memory/history`(SDK 逐修订回查) |
| GET | `/healthz` |
| GET | `/`(前端)、`/static/*` |

## 证据材料

真实浏览器人工操作截图存于 [`docs/evidence/`](./evidence/README.md)(04–10),含逐项"图片能证明的事实"清单;自动测试与人工浏览器验证在 [`docs/verification.md`](./verification.md) 中分开记录。开发过程类截图(需求设计、编码调试、`test.sh` 通过终端)目前**尚未收到**,在证据清单中列为待补。

## 已知限制

- 学习记录的"创建时间"不入库(为保持幂等,文本不含服务端时间戳),排序按课程+知识点。
- `studied_on` 缺省时不做到期日推断,新记录一律视为到期。
- 单一 SQLite 文件、单进程;无鉴权、无并发多写调优。
- 人工浏览器截图已覆盖:学习记录显示与保存提示、记忆验证视图、学习者隔离、重启恢复、偏好表单展示、复习清单条目/排序/理由/预算。**尚未有浏览器截图**:修订历史视图、偏好"保存成功"即时反馈(均由自动化测试覆盖,详见 `verification.md` D8)。
