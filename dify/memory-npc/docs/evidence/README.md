# 证据目录（docs/evidence/）

本目录存放可核查的运行证据。约定：**每份证据必须注明生成方式与日期**；
未执行的验证在 `docs/verification.md` 中明确标记，不得写成通过。

| 文件 | 内容 | 生成方式 |
|---|---|---|
| `backend-tests.txt` | 真实 PowerContext 后端测试结果（15 项） | `scripts/test.sh` 原样输出 |
| `dify-dsl-validation.txt` | DSL 对照 1.13.3 官方模型的结构校验 | 在 `langgenius/dify-api:1.13.3` 镜像内运行 `scripts/validate_dsl.py`（当前对正式导出版 DSL 执行） |
| `container-connectivity.txt` | 容器连通实测（api→squid→npc-memory）、重启与 down/up 数据保留 | `docker exec` + `curl` 原样输出 |
| `runtime-recall.txt` | Dify 真实运行后的记忆回查（demo-player-a/b） | `GET /v1/players/{id}/memory` 原样输出；发生在 down/up 全栈重启之后 |
| `memory-npc-export.yml`（未复制入内） | 实际运行版 DSL 原件位于 `/mnt/d/DifyEvidence/memory-npc-export.yml`，已设为 `workflows/memory-npc.yml` 正式版本 | 用户从 Dify 1.13.3 界面导出 |

## 界面截图（未提供）

2026-10-29 检查 `/mnt/d/DifyEvidence`：目录内仅有两份 YAML
（`memory-npc.yml` 手写入稿、`memory-npc-export.yml` Dify 导出运行版），
**没有任何图片文件**。工作流运行界面截图、节点执行详情截图等
尚未提供，因此本目录不含截图证据；后续获得后按上表格式补入
（建议命名 `01-dsl-import.png`、`02-run-node-execution.png`、
`03-memory-recall.png`、`04-player-isolation.png` 等）。
