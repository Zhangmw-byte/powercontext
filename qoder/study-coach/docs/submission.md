# 提交材料清单

Qoder × OceanBase 2026 比赛项目 · 复习记忆助手
分支 `feat/qoder-study-coach` · 远程 `origin = https://github.com/Zhangmw-byte/powercontext`

## 1. 项目展示网站(已发布)

- 线上地址:**<https://review-memory-coach-jp71o4oh6tu.qoder.zone>**
- 发布状态:`published: true`(发布 Operation 状态 `succeeded`、`committed: true`)
- 访问范围:`public`(任何人可访问,无需登录)
- 未登录访问验证:已完成。
  - 本侧实测:直接 `curl` 首页返回 `HTTP 200`,页面含最终技术说明原文;截图资源 `assets/09-review-plan.png` 返回 `HTTP 200`、`image/png`、170376 字节,与本地文件字节数一致。
  - 用户侧实测:浏览器未登录状态下可正常访问。
- 站点定位:**本地运行版的展示网站**。页面上没有"在线体验"按钮,`http://127.0.0.1:8765` 仅作为运行说明中的文字地址出现;不含任何用户数、反馈或提效数据。
- 源码位置:`qoder/study-coach/web/`(`index.html` + `style.css` + `assets/` 7 张真实截图),静态站点,无构建步骤。
- 站点描述符 `qoder/study-coach/.复习记忆助手.qoder.site` 由 Sites 工具生成与维护,**不手工编辑、不纳入版本控制**(已在 `.gitignore` 中忽略)。
- 技术说明原文(`web/index.html`):
  > 本项目将掌握程度、复习时间等业务字段编码为 JSON,存入 PowerContext 记忆条目的 text;条目标识、版本和引用由 SDK 管理。

## 2. 运行方式

```bash
cd qoder/study-coach

bash scripts/prepare.sh   # uv 锁定依赖安装到 .venv(依赖安装需要联网)
bash scripts/test.sh      # 独立临时数据库运行 pytest;失败返回非零退出码
bash scripts/start.sh     # 默认启动 http://127.0.0.1:8765
```

- 三个脚本均以自身位置定位项目根,可从任意工作目录调用。
- 环境变量:`STUDY_COACH_DB`(默认 `.data/study_coach.db`)、`STUDY_COACH_HOST`(默认 `127.0.0.1`)、`STUDY_COACH_PORT`(默认 `8765`)。
- 停止:前台 `Ctrl-C`;后台按记录的 PID `kill`。停止与重启**都不清空数据库**;重启后学习者、偏好、记录、进度全部恢复。
- 当前实际使用的数据库路径可由 `GET /healthz` 响应中的 `db` 字段核对。
- 应用主要功能完全离线,不依赖大模型或外部 API Key。

## 3. 材料清单

| 材料 | 路径 | 内容 |
| --- | --- | --- |
| 项目说明 | `README.md` | 特性、实测版本表、快速开始、停止/重启、数据库位置、环境变量、目录结构、PowerContext 分工、设计文档链接、真实限制 |
| 需求与架构设计 | `docs/requirements.md` | 定位、技术栈、**实测确认的 SDK 公开 API**、架构、数据流、REST 设计、验收方法、范围与约束 |
| 开发说明 | `docs/development.md` | SDK 实际使用要点与踩坑(1–8)、领域字段编码约定、调度算法、路由表、证据指向、已知限制 |
| 验证报告 | `docs/verification.md` | A 真实执行样本 S1–S9 / B 自动测试(18 passed)/ C HTTP 冒烟 / D 人工浏览器验证 D1–D8,四类证据分开记录 |
| 截图证据清单 | `docs/evidence/README.md` | 每张图片对应的验证环节、图片能够证明的事实、图片尚不能证实的待验证项 |
| 真实截图 | `docs/evidence/*.png` | 04–10 共 7 张本地运行的真实浏览器操作截图 |
| 应用源码 | `app/app.py` | FastAPI 入口、lifespan、全部路由、静态挂载 |
| PowerContext 交互层 | `app/memory_repo.py` | 与 SDK 真实 API 的**唯一**交互点:scope、读写、修订历史、逐修订回查 |
| 复习清单算法 | `app/review.py` | 纯规则 SM-2 风格间隔重复与预算裁剪,无大模型 |
| 校验与编解码 | `app/models.py` | 字段类型/取值校验,业务字段 → 带版本标识 JSON 文本 |
| 中文前端 | `static/index.html`、`static/app.js`、`static/style.css` | 学习概览 / 档案 / 学习记录 / 复习清单 / 记忆记录,全部按钮接真实后端 |
| 测试 | `tests/test_app.py` | 18 个集成与单元测试,使用独立临时数据库 |
| 脚本 | `scripts/prepare.sh`、`scripts/test.sh`、`scripts/start.sh` | 依赖锁定、测试(失败非零退出)、启动 |
| 依赖锁定 | `pyproject.toml`、`uv.lock` | Python 3.12、`powercontext[builtin]==1.2.0`、FastAPI、uvicorn 等 |
| 展示网站源码 | `web/index.html`、`web/style.css`、`web/assets/*.png` | 已发布展示站及其静态资源 |
| 本清单 | `docs/submission.md` | 发布网址、运行方式、材料清单 |

## 4. 证据边界(如实标注,未自行补写结论)

自动测试已覆盖、但不要求逐条补浏览器截图的用例:非法字段拒绝、重复提交去重、学习者隔离的接口层行为。

截至本次提交,**尚无真实截图**的环节,在 `docs/verification.md` D8 与 `docs/evidence/README.md` 中保持"待验证":

- 修订历史视图的实际浏览器画面(文件名 `10-review-history.png` 的截图内容是学习记录页,不是修订历史视图)。
- 学习偏好"保存成功"的即时反馈画面(`08-preferences.png` 只证明表单已填入真实值,未展示保存成功提示)。
- Qoder 需求设计、编码调试、`test.sh` 输出 18 passed 的过程截图。

## 5. Git 记录

- `5bf507bcbe72b4904eb2c9263060e7cdbc73e588` — 应用实现、测试、脚本、文档与真实截图。
- `1d6b4d326800e4cb475bcb312b11cb2b04256266` — 展示网站源码(含最终技术说明表述)。
- 未提交内容:`.venv/`、`.data/*`(含 `*.db`/`-wal`/`-shm`)、`__pycache__/`、`.pytest_cache/`、`*.log`、站点描述符文件,均在 `.gitignore` 中。
