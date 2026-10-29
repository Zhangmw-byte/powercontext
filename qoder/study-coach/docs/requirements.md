# 复习记忆助手 — 需求与架构设计

Qoder × OceanBase 2026 比赛项目
分支 `feat/qoder-study-coach`(基线 `ecosystem-official/2026-competition-ecosystem` @ `d647275c`)
本阶段仅为设计文档,不发布网站、不推送 Git。

---

## 1. 项目定位

一个面向多学习者的"复习记忆助手"。系统把每位学习者的**学习偏好**、**薄弱知识点**、**复习进度**写入 PowerContext 记忆,服务重启后仍能从真实 SQLite 后端继续读取,并结合掌握程度与每日可用学习时间生成当日**复习清单**。

价值主张:记忆不是存在进程内存里,而是由 `powercontext[builtin]` 的持久化后端托管;复习清单是"记忆读取 + 间隔重复算法"的确定性产物,不依赖任何大模型或联网推理。

## 2. 技术选型

| 层 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.12 | 实测 venv 为 3.12.16 |
| Web 框架 | FastAPI 0.162 + Uvicorn 0.54 | 全异步,匹配 SDK 的 async 生命周期 |
| 前端 | 原生 HTML / CSS / JavaScript | 单页,`fetch` 调用后端 JSON 接口,无构建步骤 |
| 记忆后端 | `powercontext[builtin]==1.2.0` | 真实 SQLite 持久化(SQLAlchemy 2.1.6 + aiosqlite 0.22.1) |
| 存储介质 | SQLite 文件(`journal_mode=WAL`) | 跨重启持久 |

依赖版本(实测):powercontext 1.2.0 / pydantic 2.14.1 / sqlalchemy 2.1.6 / aiosqlite 0.22.1。

## 3. SDK 公开 API 核对结果(实测)

以下为 `powercontext[builtin]==1.2.0` 中本项目实际会用到的公开入口,均已在本地 SQLite 文件后端上跑通。

### 3.1 生命周期与上下文

```python
from powercontext.builtin.runtime import open_builtin_contexts      # async contextmanager
from powercontext.builtin.runtime.config import BuiltinConfig
from powercontext.builtin.persistence.sqlite import SQLiteConfig

config = BuiltinConfig(database=SQLiteConfig(url="sqlite+aiosqlite:///./data/study_coach.db"))
async with open_builtin_contexts(config) as contexts:               # -> RelationalContexts
    ctx = await contexts.get(scope_id)                             # -> PowerContext (按 scope 缓存)
```

- `open_builtin_contexts` 是精简组合根,内部建库、建索引、`bootstrap_default()` 后产出 `RelationalContexts`。全 async。
- `inference` 配置默认全部为 `None`,因此**离线可运行**:不带 embedding 模型时只建 SQLite FTS5 索引。
- `open_builtin_contexts(...)` 需在应用生命周期内保持打开(FastAPI lifespan),每次请求调用 `contexts.get(scope_id)`;上下文按 scope 记忆化。数据库所有权随 context 退出而关闭。

### 3.2 Scope = 学习者隔离

`scope_id` 是一个经校验的非空字符串(`validate_scope_id`),烧进每行 Source/Artifact/Memory。每位学习者用一个稳定 scope id(如 `learner-42`),读写天然隔离。

实测:learner-99 首次访问 `head("memory")` 抛 `ArtifactNotFoundError`,证明与 learner-7 数据隔离。

### 3.3 MemoryService

`ctx.artifacts.memory` 即 `MemoryService`;`ctx.artifacts.memory_artifact_id` 默认为 `"memory"`。

```python
async def remember(*, memory: Memory | None, sources=(), artifacts=(),
                   entries: Sequence[MemoryEntryInput] = (),
                   mode: Literal["append","extract","auto"] = "append") -> Memory | None

async def head(artifact_id: str) -> Memory                          # 取记忆头
async def head_entries(artifact_id: str) -> tuple[Memory, tuple[MemoryEntryVersion, ...]]
async def search(query: str, *, memories: Sequence[Memory], limit=10,
                 mode: Literal["fts","vector","hybrid","auto"] = "auto") -> MemorySearchResult
async def forget(...)  # 停用条目
```

写入输入模型:

```python
class MemoryEntryInput(BaseModel):
    kind: str        # 语义分类,如 preference / weak_point / progress
    text: str        # 结构化载荷文本
    entry: MemoryEntryVersion | None = None   # 设置则为修订已有条目
    reason: str | None = None
    sources / artifacts  # 证据引用(可选)
```

读取条目模型 `MemoryEntryVersion` 字段(实测):`entry_id, entry_version_id, version, previous_version_id, kind, text, entry_content_hash, created_in_revision, sources, artifacts`。

关键行为约束(实测):
- 离线一律用 `mode="append"` 且显式传 `entries`;`mode="extract"` 需要 LLM candidate_pipeline,会抛 `CapabilityNotSupportedError`。
- `search` 至少传一个 memory 头;离线 `mode="auto"` 解析为 `"fts"`,强制 `vector/hybrid` 会抛 `CapabilityNotSupportedError`。
- 对同一 `Memory` 头反复 `remember` 会自增 `revision`(实测 append 3 条 → `head_entries` 返回 3 条,含各自 `kind`/`text`)。
- 重启后重开同一 SQLite 文件,`head("memory")` 取回原 `revision`,`search` 命中旧条目 → 持久化验证通过。

> 说明:SDK 记忆条目本体是 `kind` + `text` 的自由文本,没有数值字段。本项目的"掌握度、复习日期、时长"等领域字段编码进 `text`(建议 JSON 串或 `key=value`),在应用层解析;`kind` 承担分类。这是设计取舍,验收以此为准。

## 4. 系统架构

```
浏览器 (index.html + app.js)
        │  fetch JSON
        ▼
FastAPI 应用 (app.py, lifespan 持有 open_builtin_contexts)
        │
        ├── 领域层  learners.py / review.py
        │      · 解析/编码 MemoryEntryInput.text
        │      · SM-2 风格间隔重复排序与清单生成
        │
        └── 记忆层  memory_repo.py
               · contexts.get(scope_id) → ctx.artifacts.memory
               · remember / head_entries / search / forget
                     │
                     ▼
        powercontext[builtin]  (RelationalContexts → RelationalMemoryBackend)
                     │  SQLAlchemy async + aiosqlite
                     ▼
        SQLite 文件 data/study_coach.db  (WAL,FTS5)   ← 跨重启持久
```

模块划分(`qoder/study-coach/` 下):

- `app.py` — FastAPI 入口、lifespan 生命周期、路由挂载、静态文件。
- `memory_repo.py` — 封装 PowerContext:上下文管理、按 scope 取 MemoryService、条目编解码。
- `review.py` — 复习清单算法(排序、按时长裁剪、状态阈值)。
- `models.py` — 应用侧 pydantic 请求/响应模型与条目载荷 schema。
- `static/index.html`、`static/app.js`、`static/style.css` — 原生前端。
- `data/` — SQLite 文件(gitignore)。
- `requirements.txt`、`run.sh`、`tests/`。

## 5. 数据流程

### 5.1 记忆分类(kind)

| kind | 载荷 | 用途 |
|---|---|---|
| `preference` | 每日学习分钟数、复习时段、难度倾向 | 清单时长预算 |
| `weak_point` | 知识点、掌握度、错误次数 | 排序加权 |
| `progress` | 知识点、`mastery`、`last_review`、`interval`、`ease`、`reps`、`lapses` | 间隔重复状态 |

### 5.2 写入(保存记忆)

1. 前端提交 `{ learner_id, kind, payload }`。
2. `memory_repo` 编码为 `MemoryEntryInput(kind, text=json(payload))`。
3. 取当前头 `head = await ms.head("memory") or await ms.remember(memory=None, mode="append", entries=[])`。
4. `await ms.remember(memory=head, mode="append", entries=[entry])`,revision 自增。
5. 更新型进度:复用已有 `entry`(传 `MemoryEntryVersion`)做修订而非重复追加。

### 5.3 重启恢复

- 应用 lifespan 关闭后再启动:`open_builtin_contexts` 指向同一 SQLite 文件;`contexts.get(learner_id)` → `head_entries("memory")` 返回重启前的全部条目。
- 无需迁移或缓存预热。这是"服务重启后继续读取记忆"的核心验收路径。

### 5.4 复习清单生成(读取 + 算法)

1. 载入该学习者全部条目:`mem, entries = await ms.head_entries("memory")`。
2. 解析 `progress`/`weak_point` → 每个知识点状态 `{mastery, last_review, interval, ease, lapses}`。
3. 到期判定:`due = last_review + interval(current)`;`mastery` 越低、`lapses` 越多、间隔重复越欠账 → 优先级越高。
4. 排序:组合"到期紧迫度 + 薄弱加权",降序。
5. 预算裁剪:读取 `preference.daily_minutes`,按每题预计耗时累加,截断到当日预算。
6. 返回清单 `[{topic, mastery, reason, est_minutes}]` 与剩余预算。
7. 复习回填:学习者报告结果 → 更新 SM-2 风格 `interval/ease/reps/lapses` 与 `mastery`,写回 `progress` 条目(revision++),供下次重启后读取。

### 5.5 检索增强(可选)

对"最近哪个薄弱点和二次方程有关"这类模糊问句,`search(query, memories=[head], mode="fts")` 用 FTS5 召回相关条目作为清单排序的补充信号;主链路仍是枚举 + 算法,保证确定性。

## 6. REST 接口(设计)

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/api/learners/{id}/memory` | 读取该学习者全部记忆条目 |
| `POST` | `/api/learners/{id}/memory` | 写入/更新一条记忆(preference/weak_point/progress) |
| `DELETE` | `/api/learners/{id}/memory/{entry_id}` | 停用某条记忆(`forget`) |
| `GET` | `/api/learners/{id}/review-plan` | 生成当日复习清单 |
| `POST` | `/api/learners/{id}/review-result` | 回写复习结果,更新进度并重算 |
| `GET` | `/api/search?q=...` | 对该学习者记忆做 FTS 检索 |
| `GET` | `/healthz` | 探测后端 DB 可用(重启恢复证据) |

## 7. 验收方法

1. **依赖与环境**:干净 `python3.12 -m venv && pip install -r requirements.txt` 装到 powercontext 1.2.0,无 inference/embedding 配置即可启动。
2. **写入**:向 `learner-A` 保存偏好、若干薄弱点与进度,接口返回 2xx;`GET memory` 能读回,`kind`/载荷一致。
3. **隔离**:`learner-B` 的 `GET memory` 不含 A 的数据(实测 `ArtifactNotFoundError` 语义)。
4. **重启持久化**(核心):停止 uvicorn,重启,指向同一 SQLite 文件;`GET /learner-A/memory` 与 `/healthz` 返回重启前数据;`revision` 不回退。
5. **清单生成**:`GET /learner-A/review-plan` 返回按掌握度+每日时长排序的清单,条数与题目总时长 ≤ `daily_minutes`;低掌握度知识点排在前面。
6. **进度回写闭环**:`POST /review-result` 后,对应 `progress` 条目更新(间隔/掌握度变化),再次 `review-plan` 排序随之改变。
7. **检索**:模糊查询命中相关薄弱点条目(FTS)。
8. **前端**:浏览器实际点选——添加学习者、录入记忆、查看清单、报告复习结果、模拟重启后清单仍在。

## 8. 范围与约束

- 本阶段只交付设计,不写业务代码、不发布网站、不 `git push`。
- 完全离线:不接大模型、不做向量检索;记忆读写走 SQLite FTS5。
- 领域数值字段编码进记忆条目 `text`,由应用层解析(SDK 条目本体仅 `kind`/`text`)。
- 单文件 SQLite,面向比赛演示与本地运行,不含多租户扩展/鉴权。
