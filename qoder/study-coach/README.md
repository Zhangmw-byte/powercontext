# 复习记忆助手

Qoder × OceanBase 2026 比赛项目 · 分支 `feat/qoder-study-coach`

项目展示网站(公开访问,本地运行版介绍,无在线体验入口):**<https://review-memory-coach-jp71o4oh6tu.qoder.zone>**

把不同学习者的**学习偏好**、**薄弱知识点**和**复习进度**写入 [PowerContext] 的真实 SQLite 持久化后端;服务重启后继续读取这些记忆,并依据掌握程度与每日学习时间生成复习清单。全部功能离线运行,不依赖任何大模型或外部 API Key。

## 特性

- 多学习者创建与切换;**学习者注册表本身也持久化**,重启后仍在。
- 保存学习偏好(每日学习时间、学习目标、偏好说明),生成清单时实际读取。
- 添加学习记录(课程、知识点、笔记、掌握程度 0–5),字段类型与取值严格校验,非法数据被拒绝。
- 复习清单:**规则算法**(SM-2 风格间隔重复)按真实掌握度、复习时间与每日时间预算生成,薄弱优先,每条附推荐理由。明确不调用大模型。
- 复习结果回写:更新最新进度,历史记录经 SDK 逐修订回查仍可查看。
- 记忆验证视图:展示真实 `scope`、`revision`、`entry_id`/`entry_version_id` 及 SDK 回查正文。
- 中文界面:学习概览 / 档案 / 学习记录 / 复习清单 / 记忆记录,所有按钮连接真实后端;不用 localStorage 替代持久化。
- 相同内容重复提交不产生重复记录(复用 SDK 内容级幂等 + 应用层结果指纹)。

## 技术栈与版本

实测锁定版本(见 `uv.lock`):

| 组件 | 版本 |
|---|---|
| Python | 3.12.16(要求 `>=3.12,<3.13`) |
| powercontext[builtin] | 1.2.0 |
| fastapi | 0.162.0 |
| uvicorn[standard] | 0.54.0 |
| sqlalchemy | 2.1.6 |
| aiosqlite | 0.22.1 |
| pydantic | 2.14.1 |
| uv | 0.13.6 |
| pytest / pytest-asyncio | 9.x / 1.x(开发依赖) |

## 快速开始

```bash
cd qoder/study-coach

# 1. 准备锁定依赖(安装到 .venv)
bash scripts/prepare.sh

# 2. 运行测试(独立临时数据库,不触碰用户数据)
bash scripts/test.sh

# 3. 启动服务(默认 http://127.0.0.1:8765)
bash scripts/start.sh
```

浏览器打开 <http://127.0.0.1:8765>,先添加学习者,再设置偏好、录入学习记录、查看复习清单、回写复习结果,并在"记忆记录"页查看真实持久化内容。

脚本可从任意工作目录调用,内部以脚本自身位置定位项目根。

## 停止与重启

- **停止**:前台运行时按 `Ctrl-C`;后台运行可 `pkill -f "uvicorn app.app:app"` 或按记录的 PID `kill <pid>`。停止只关闭进程,**不会删除数据库**。
- **重启**:再次执行 `bash scripts/start.sh`,仍指向同一 `STUDY_COACH_DB` 文件即恢复全部记忆。启动/重启均不清空数据(不存在建表即清库、也没有 drop 操作)。
- **换端口/地址**:`STUDY_COACH_PORT=9000 STUDY_COACH_HOST=0.0.0.0 bash scripts/start.sh`。
- **换数据库**:`STUDY_COACH_DB=/绝对路径/other.db bash scripts/start.sh`。

## 数据库位置

- 默认:`qoder/study-coach/.data/study_coach.db`(WAL 模式,附属 `-wal`/`-shm` 文件)。目录不存在时由 `start.sh`/应用自动创建。
- 该文件与所有 `*.db`、`.data/*` 已被 `.gitignore` 忽略,不入库;`.data/.gitkeep` 保留以固定目录。
- 备份/迁移:直接复制该 `.db` 文件即可;新机器放相同路径并设 `STUDY_COACH_DB` 指向它。
- 检查当前实际使用的库:访问 `GET /healthz`,响应中的 `db` 字段即真实路径。


## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `STUDY_COACH_DB` | `.data/study_coach.db` | SQLite 持久化文件路径。启动/重启不清空。测试用独立临时库。 |
| `STUDY_COACH_HOST` | `127.0.0.1` | 监听地址 |
| `STUDY_COACH_PORT` | `8765` | 监听端口 |

## 目录结构

```
qoder/study-coach/
├── app/
│   ├── app.py          # FastAPI 入口、lifespan、路由、静态挂载
│   ├── memory_repo.py  # 与 powercontext[builtin] 真实 API 的唯一交互点
│   ├── review.py       # SM-2 风格调度 + 复习清单生成(纯规则)
│   └── models.py       # 请求/响应模型、字段校验、记忆条目 JSON 编解码
├── static/             # 中文单页前端(index.html / app.js / style.css)
├── tests/test_app.py   # 集成与单元测试(临时数据库)
├── scripts/            # prepare.sh / test.sh / start.sh
├── docs/               # requirements / development / verification / submission / evidence(截图)
├── web/                # 已发布的 Qoder Sites 展示网站静态源码(index.html / style.css / assets)
├── pyproject.toml      # 依赖配置
└── uv.lock             # 锁定依赖
```

持久化数据、`.venv`、缓存与日志均在 `.gitignore` 中忽略;`uv.lock` 保留以供复现。

## PowerContext 的实际分工

| 职责 | 承担者 |
|---|---|
| 记忆的**持久化与一致性** | `powercontext[builtin]`:SQLite(WAL)后端、FTS5 索引、条目内容哈希去重、`revision` 版本与逐修订历史 |
| **写入/读取记忆的 API** | `MemoryService`(`remember` / `head_entries` / `entries` / `revisions` / `changes` / `search` / `forget`),全部经 `app/memory_repo.py` 调用 |
| **scope(学习者隔离)** | PowerContext 的 scope 机制;学习者注册表用 `study-coach-registry`,每位学习者 `learner-<id>` |
| 领域语义(掌握度、间隔、预算) | 应用层:业务字段编码为带 `_v` 的规范 JSON 存入条目 `text`,由 `app/models.py` 校验与解析 |
| 复习清单算法 | 应用层 `app/review.py`(纯规则 SM-2 风格,**非** PowerContext、**非**大模型) |
| HTTP 接口与前端 | `app/app.py`(FastAPI)+ `static/` |

> 说明:SDK 记忆条目本体只有 `kind` + `text` 两字段(无数值列);数值与日期字段是应用层约定编码进 `text` 的,不属于 SDK 原生结构。

## 设计文档

- 需求与架构:`docs/requirements.md`
- 开发说明:`docs/development.md`
- 验证报告:`docs/verification.md`
- 证据材料:`docs/evidence/`
- 提交材料与发布网址:`docs/submission.md`

## 限制(真实)

- **本地单进程**:单一 uvicorn 进程 + 单一 SQLite 文件,面向比赛演示与本地运行。未做并发写锁调优或多进程/多实例部署,不建议公网多用户并发。
- **无鉴权 / 无权限隔离**:学习者靠 `scope_id` 逻辑隔离,但接口层不做身份认证或授权;任何人知道 `learner_id` 即可读写该学习者数据。切勿暴露到不受信网络。
- **完全离线**:只使用 SQLite FTS5,不接大模型、不做向量检索;清单与推荐理由均由规则算法产生。
- **领域字段编码**:掌握度、日期、时长等编码进记忆条目 `text`(带 `_v` 版本标识的规范 JSON),SDK 条目本体仅 `kind`/`text`。
- **记录创建时间不入库**:为保证"相同请求 → 相同内容 → 幂等去重",写入文本不含服务端易变时间戳;列表按课程 + 知识点排序。


[PowerContext]: https://github.com/oceanbase/powercontext
