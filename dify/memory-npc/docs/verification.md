# 验证清单（如实区分，未执行项不得写成通过）

日期：2026-10-29　环境：WSL2 Ubuntu（D 盘）+ Docker Desktop
正式 DSL：`workflows/memory-npc.yml`（自实际运行 Dify 1.13.3 界面导出）
模型：`deepseek-v4-flash`（插件 `langgenius/deepseek:0.0.26@bdf47cb4…`，凭据由使用者界面配置）

## A. 后端测试 —— 已执行，全部通过

命令：`scripts/test.sh`（真实 `powercontext` SDK + 真实 PowerContext Server 子进程 +
临时 SQLite，15 项）→ **15 passed**。输出：`docs/evidence/backend-tests.txt`

| 覆盖点 | 用例 |
|---|---|
| 真实 SDK 写入/读取（memory entry + citation） | `test_commit_persists_chinese_quotes_and_multiline` |
| 中文、引号、多行、emoji 正确保存 | 同上（往返逐字节比对） |
| 读取不创建记录 | `test_prepare_on_fresh_player_does_not_write` |
| 重启后恢复（杀 Server 进程再拉起同目录） | `test_restart_recovery` |
| 玩家隔离 | `test_players_are_isolated` |
| 同回合重复请求返回原结果、不重复写入 | `test_duplicate_turn_same_action_returns_saved_result` |
| 同回合不同行动 409 拒绝 | `test_same_turn_number_different_action_rejected` |
| 回合乱序拒绝 | `test_out_of_order_turn_rejected` |
| expected_revision 过期 409 | `test_stale_expected_revision_rejected` |
| 并发同回合仅写一次 / 并发冲突拒绝 | 2 个 `test_concurrent_*` |
| 历史窗口限制、完整存档保留 | `test_history_window_limits_context_but_keeps_archive` |
| 非法输入拒绝、后端宕机 healthz 如实 503 | `test_invalid_inputs_rejected` 等 |

## B. 容器连通测试 —— 已执行，全部通过

`docs/evidence/container-connectivity.txt`（原样输出）：

- api → squid（Dify HTTP 节点真实路径）→ npc-memory：prepare 200 /
  commit 200 / 重复提交 `already_committed` / 同回合改行动 409。
- `restart-memory.sh` 后与 `down.sh`→`up.sh` 后，测试玩家存档完整恢复
  （未使用 `down -v`）。
- SSRF：仅注入 `dstdomain npc-memory` 单目标放行规则；未全局关闭防护。
  （说明：Dify 1.13.3 官方 squid 镜像自带 `conf.d/debian.conf` 的
  `http_access allow localnet`，为官方默认行为，本作品未改动、未扩大。）
- 端口：记忆服务仅 `127.0.0.1:8877`；Dify 页面 8080 正常。

## C. Dify DSL 结构校验 —— 已执行，全部通过

在官方 `langgenius/dify-api:1.13.3` 镜像内以真实 `dify_graph` pydantic
节点模型校验（`scripts/validate_dsl.py`）：**11 节点 / 10 边全部 PASS**。
当前校验对象为正式导出版 DSL。
输出：`docs/evidence/dify-dsl-validation.txt`

## D. Dify 实际导入与真实模型运行 —— 已由使用者执行（文本证据在档）

- **实际导入并运行**：成立。证据：运行版 DSL 自 Dify 界面导出
  （`/mnt/d/DifyEvidence/memory-npc-export.yml`，含 deepseek 插件依赖与
  实际模型绑定），且记忆服务中存在与其对应的真实回合。
- **真实节点执行 → 记忆写入**：`demo-player-a` 连续 3 回合
  （2026-10-29 23:00–23:02 本地时间），回合内容为 Dify 工作流运行产物：
  第 1 回合寄存蓝色徽章并约定暗号「月光奶茶」；第 2、3 回合的 NPC 回答
  **正确引用了已保存历史**（徽章、暗号、旧借阅册细节一致）。
  原样输出：`docs/evidence/runtime-recall.txt`。
- **无历史不编造（隔离/编造检查）**：全新玩家 `demo-player-b` 询问
  「我以前来过这里吗？你有我的寄存记录吗？」，NPC 明确回答**没有任何
  寄存记录**、拒绝编造，随后写入其第一条存档。玩家间隔离同时成立
  （b 看不到 a 的徽章/暗号）。见 `runtime-recall.txt`。
- **重启恢复（含真实运行数据）**：上述回查发生在本机 `down.sh`→`up.sh`
  全栈重启之后，`demo-player-a`（3 回合）与 `demo-player-b`（1 回合）
  存档、scope id、中文内容完整恢复。
- **无重复写入（间接）**：a 玩家 `revision=3`、`turn_count=3`、各回合
  `entry_version=1`，与 3 次运行一一对应，未见重复条目。

## E. 未执行 / 未提供 —— 不作通过结论

1. **Dify 界面内的重复回合与冲突回合运行**：未提供对应运行记录
   （该两项已在后端层 A/容器层 B 实测通过）。界面复现剧本见
   `docs/dify-setup.md` 第 4 节步骤 3、4。
2. **界面截图**：`/mnt/d/DifyEvidence` 实际检查仅含两份 YAML，
   **没有任何图片**；本仓库不虚构截图证据。
3. **模型凭据轮换/多供应商**：仅按使用者实际绑定的 deepseek 记录，
   未测试其他供应商。

## 已知限制

- 送入模型的历史窗口默认最近 12 回合（`NPC_MEMORY_HISTORY_WINDOW` 可调）；
  完整存档始终保留在 PowerContext，`GET /v1/players/{id}/memory` 回查全部。
- 主存储为 PowerContext（SQLite 持久化）；Dify 用官方默认 Postgres。
- 并发回合保护按单实例设计（服务内按玩家加锁 + SDK revision 乐观锁）；
  多实例部署需外部互斥。
- 正式 DSL 中 `http_prepare`/`http_commit` 启用节点重试
  （max_retries=3, interval=100ms）；业务 409 不产生假成功记录。
