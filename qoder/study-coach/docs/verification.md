# 验证报告

复习记忆助手的验证分两部分:**自动验证**(已在本环境实际执行并附真实输出)与**人工浏览器验证**(部分已执行并附真实截图,见 D 段;未覆盖项单独标注待验证,不混为通过)。

环境:Python 3.12.16 · powercontext 1.2.0 · fastapi 0.162.0 · sqlalchemy 2.1.6 · aiosqlite 0.22.1 · uv 0.13.6。
所有验证使用独立临时 SQLite 数据库,不触碰用户运行实例(`.data/study_coach.db`)。

---

## A. 两学习者完整验证样例(真实执行输出)

以固定"今天 = 2026-11-02"驱动清单生成。下列每步为「输入 / 操作 / 预期结果 / 实际结果」。操作可经 HTTP 接口或 `app/memory_repo.py` 直接调用完成;此处记录一次真实运行的输出。

### S1 创建两个学习者
- **输入**:`{"learner_id":"xiaoming","name":"小明"}`;`{"learner_id":"xiaohua","name":"小花"}`
- **操作**:`POST /api/learners`(两次)
- **预期**:各自返回学习者对象;列表包含两人;写入注册 scope `study-coach-registry`。
- **实际**:`{"kind":"learner","learner_id":"xiaoming","name":"小明"}`、`{"...":"xiaohua","name":"小花"}`;列表 `[{"id":"xiaohua","name":"小花"},{"id":"xiaoming","name":"小明"}]`

### S2 保存学习偏好
- **输入**:小明 `{daily_minutes:15, goal:"期中考试", preferences:"喜欢例题"}`;小花 `{daily_minutes:30}`
- **操作**:`PUT /api/learners/xiaoming/preference`
- **预期**:偏好写入该学习者 scope,读回一致。
- **实际**:`{"daily_minutes":15,"goal":"期中考试","kind":"preference","preferences":"喜欢例题"}`;小花 `daily_minutes:30`

### S3 添加学习记录 + 重复提交去重
- **输入**:记录①`{course:数学,topic:分数运算,note:通分易错,mastery:1,studied_on:2026-10-01}`;记录②`{course:数学,topic:二次方程,mastery:4,studied_on:2026-10-10}`;再把记录①**重复提交一次**。
- **操作**:`POST /api/learners/xiaoming/records`(3 次)
- **预期**:两条不同记录入库;内容完全相同的重复提交**不新增**(SDK 内容级去重)。
- **实际**:`去重后 records: [["二次方程",4],["分数运算",1]]`(提交 3 次仅 2 条)。

### S4 生成复习清单
- **输入**:读取小明真实记录与偏好,今天=2026-11-02
- **操作**:`GET /api/learners/xiaoming/review-plan?date=2026-11-02`
- **预期**:预算取偏好的 15 分钟;**薄弱(掌握度1)分数运算排在前**,每条含推荐理由;总时长≤预算;明示规则生成。
- **实际**:`budget:15`,items=`[{topic:"分数运算",mastery:1,est:7,reason:"薄弱(掌握度1/5);尚未复习"},{topic:"二次方程",mastery:4,est:4,reason:"掌握度4/5,尚可;尚未复习"}]`(合计 11≤15)。

### S5 回写复习结果
- **输入**:`{topic:"分数运算", quality:4, review_date:"2026-10-25"}`;随后**重复提交同一结果**。
- **操作**:`POST /api/learners/xiaoming/review-result`(2 次)
- **预期**:首次更新成功,mastery 提升、间隔推进、写回 revision;重放因结果指纹**不再推进**。
- **实际**:首次 `{"changed":true,"interval":1,"lapses":0,"mastery":4,"review_count":1}`;重放 `replay changed: False`。

### S6 数据隔离
- **输入**:读取小花记录
- **操作**:`GET /api/learners/xiaohua/records`
- **预期**:仅含小花自己的数据,绝不含小明记录。
- **实际**:`[["词汇",2]]`(小花仅一条英语记录,与小明数学记录互不可见)。

### S7 查看历史(SDK 逐修订回查)
- **输入**:读取小明记忆历史
- **操作**:`GET /api/learners/xiaoming/memory/history`
- **预期**:各 revision 可回查;更新前的 mastery=1 与更新后的 mastery=4 同时存在于历史,旧值不被覆盖。
- **实际**:
  ```
  revision 1: entries=[preference]
  revision 2: entries=[record, preference]
  revision 3: entries=[record, record, preference]
  revision 4: changes=[revise:mem_ent_56…] entries=[record, record, preference]
  分数运算历史 mastery 版本: [1, 1, 4]   # 更新前(1)保留,更新后(4)并存
  ```

### S8 记忆验证视图
- **操作**:`GET /api/learners/xiaoming/memory`
- **预期**:展示真实 scope、memory_artifact_id、当前 revision、活动条目数与 SDK 回查正文。
- **实际**:`{"scope":"learner-xiaoming","artifact":"memory","revision":4,"entry_count":3}`

### S9 停止后重启恢复
- **操作**:关闭 store(退出 context),对**同一 DB 文件**重新 `open_store`
- **预期**:学习者、记录(含更新后的进度)、偏好、revision 全部保留,不回退。
- **实际**:
  ```
  learners: ["小花","小明"]
  xiaoming recs: [["二次方程",4,null,0],["分数运算",4,"2026-10-25",1]]   # 更新后的 mastery/last_review/interval 保留
  xiaoming pref: daily_minutes=15, goal=期中考试
  revision: 4
  ```

---

## B. 自动化测试(已执行)

命令:`bash scripts/test.sh`(任意工作目录;内部定位项目、用 `tmp_path` 独立库)。

结果:**18 passed in 4.65s**

| 测试 | 验收点 | 结果 |
|---|---|---|
| test_healthz | 后端可读 | PASS |
| test_learner_and_record_persist | 偏好/记录真实写入,重开同库仍在 | PASS |
| test_learner_registry_persist_across_restart | 注册表重启恢复 | PASS |
| test_learner_isolation | 两学习者隔离 | PASS |
| test_preference_changes_plan | 偏好(预算)实际影响清单 | PASS |
| test_weak_first_ordering | 薄弱优先 | PASS |
| test_review_result_updates_and_history | 更新最新进度 + 历史可读 | PASS |
| test_duplicate_submit_no_duplicate | 重复提交不重复、结果重放不推进 | PASS |
| test_illegal_fields_rejected ×5 | 空课程/掌握度6/-1/非法日期/非整数 → 422 | PASS |
| test_preference_illegal_rejected | 预算 0/9999 越界 → 422 | PASS |
| test_chinese_roundtrip | 中文保存/显示/SDK 回查一致 | PASS |
| test_unknown_learner_404 / test_review_result_unknown_topic_404 | 缺失资源 404 | PASS |
| test_review_units_sm2 | SM-2:interval 1→6 | PASS |

退出码:全通过=0;`-k <不存在>`=5(非零)。

---

## C. HTTP 冒烟(已执行,独立 live_smoke.db)

真实 uvicorn + curl:创建两人 → 偏好 → 记录 → 重复提交(仍 2 条) → 清单(薄弱优先,used 11≤budget) → 结果回写(changed:true) → 非法 mastery=6→422 → 隔离(xiaohua 记录为空) → 记忆视图(rev 4/entries 3)。停进程、重开同库:learners=2、分数运算 mastery 4/last_review 保留、revision 不回退。冒烟库已清理。

---

## D. 人工浏览器验证(真实截图)

截图为在真实浏览器(`localhost:8765`)中人工操作所得,存于 [`docs/evidence/`](./evidence/README.md)。逐项事实以画面可见内容为准,画面不能证明的结论不写入本段。本段与上面的自动验证**分开记录**。

### D1 学习记录显示 — 已证实
- 截图:[`04-records-and-plan.png`](./evidence/04-records-and-plan.png)
- 画面可见:"已保存记录"表格两行中文记录(矩阵对角化 掌握度 2/5、英语阅读 4/5),列为 课程/知识点/笔记/掌握度/学习日期/上次复习/复习次数/操作,每行含"记住了/模糊/忘了"按钮,两条显示"未复习"、复习次数 0。
- 可证明:学习记录在浏览器中保存并正确显示(含中文)。
- 注:该文件名含 "plan",但画面**未见复习清单条目**,清单页排序/理由不能由此图证明。

### D2 记忆验证视图 — 已证实
- 截图:[`05-memory-details.png`](./evidence/05-memory-details.png)
- 画面可见:scope=`learner-A`、memory_artifact_id=`memory`、当前 revision=`2`、活动条目数=`2`;表格含 kind=`record`、真实 `entry_id`(`mem_ent_…`)/`entry_version_id`(`mem_ver_…`)、version=1、state=`active`、正文为含中文的 JSON(矩阵对角化 mastery 2、英语阅读 mastery 4)。
- 可证明:通过真实 SDK 回查持久化正文与标识,非伪造响应。

### D3 学习者隔离 — 已证实
- 截图:[`06-learner-isolation.png`](./evidence/06-learner-isolation.png)
- 画面可见:当前学习者切到 `B (B)`,学习概览记录总数/掌握良好/薄弱/今日到期全为 0、学习偏好"未设置"、每日时间预算 30 分钟。
- 可证明:学习者 B 看不到 A 的记录数据。

### D4 停止后重启恢复 — 已证实
- 截图:[`07-after-restart.png`](./evidence/07-after-restart.png)
- 画面可见:地址栏 `localhost:8765`、当前学习者 `A (A)`;概览 记录总数=2、掌握良好(≥4)=1、薄弱(≤2)=1、今日到期=2、每日时间预算 30 分钟、学习偏好"未设置"。
- 可证明:服务停止并重启后,学习者 A 的记录仍在。

### D5 学习偏好表单 — 部分证实
- 截图:[`08-preferences.png`](./evidence/08-preferences.png)
- 画面可见:"档案"页"学习偏好"表单填入 每日学习时间(分钟)=20、学习目标=期中考试、偏好说明=视觉化,含"保存偏好"按钮。
- 可证明:偏好表单在浏览器中展示中文输入项。
- **未证实**:画面未拍到"保存成功"提示,故偏好写入的即时反馈与"偏好→清单"闭环不由此图单独证明(该闭环由自动测试 `test_preference_changes_plan` 覆盖)。

### D6 复习清单(条目/排序/理由) — 已证实
- 截图:[`09-review-plan.png`](./evidence/09-review-plan.png)
- 画面可见:生成日期 2026-10-29、预算 20 分钟、已用 10 分钟、2 条;说明"共2条到期记录,按薄弱与逾期优先…(本清单由规则算法生成,未调用任何大模型。)";优先级 1=矩阵对角化(掌握度2/5,理由"薄弱(掌握度2/5);尚未复习",预计6),优先级 2=英语阅读(掌握度4/5,理由"掌握度4/5,尚可;尚未复习",预计4)。
- 可证明:清单实际条目、**薄弱优先排序**、推荐理由、预算占用在浏览器呈现,且明示规则生成;预算 20 与 D5 偏好的 20 分钟一致。

### D7 学习记录保存提示 — 已证实
- 截图:[`10-review-history.png`](./evidence/10-review-history.png)
- 画面可见:绿色提示"记录已保存到 PowerContext(相同内容重复提交不会产生重复记录)。";已保存记录三行(矩阵对角化 2/5、矩阵对角化 4/5、英语阅读 4/5)。
- **注意**:文件名含 "history",但画面实为"学习记录"页,**并非"修订历史"视图**。可证明:记录保存成功提示与中文记录列表;不能证明修订历史视图。

### D8 尚未由浏览器截图覆盖(待验证)

以下保持未确认,不以自动验证或推断替代:

- [ ] **修订历史视图**(记忆记录页"查看修订历史",同一知识点 mastery 新旧版本并存)。10 画面为学习记录页,未出现该视图。→ 待补图(能力由自动测试 `test_review_result_updates_and_history` 覆盖)。
- [ ] **偏好"保存成功"的即时反馈**(08 仅显示表单填值)。→ 待补图(闭环由自动测试覆盖)。

> 非法字段拒绝、重复提交去重:按已有真实自动化测试结果登记(B 段),不要求补成浏览器截图。
> 说明:本环境无可用无头浏览器(chromium/playwright 缺失),D 段截图由用户在真实浏览器人工操作提供。此前"页面 200 + DOM id 接线静态校验(app.js 引用的 26 个 id 均存在于 index.html)"仍成立,作为补充。
