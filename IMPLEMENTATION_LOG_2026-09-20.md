# V2.1 Document API 实施记录（2026-09-20）

## 1. 结论

Gateway/MCP 最薄 Document 封装已部署到 `ubuntu@106.53.204.254`，服务器本机和 Cloudflare 公网 MCP 链路均通过真实端到端验收。当前不需要启动独立 Record Store。

## 2. 仓库与可追溯提交

| 仓库 | 提交 | 内容 |
| --- | --- | --- |
| `personal-memory-stack` | `9aaf3e5` | A08 Document 导出/恢复审计与 reprocess/delete 竞态修正 |
| `memory-gateway` | `dbe8efb` | Retain 可选参数、Document List/Get、串行化 CAS Patch |
| `memory-gateway` | `b77c88f` | Document API 服务器端到端验收脚本 |
| `memory-mcp` | `8c02224` | 六个正式 MCP 工具与 Document API 验收脚本 |
| `memory-mcp` | `99f2015` | 收紧 Patch 验收断言 |
| `memory-mcp` | `5cc0ebe` | bootstrap 拉取新版后自动重入最新部署逻辑 |

## 3. 已交付接口

Gateway：

- `POST /v1/memories/retain`：可选 `document_id`、`timestamp`、`update_mode`；
- `GET /v1/documents`：按 speaker 列表/搜索；
- `GET /v1/documents/{document_id}`：读取原文；
- `POST /v1/documents/{document_id}/patch`：单次精确匹配的 compare-and-swap 替换。

MCP：

- `memory_retain`、`memory_recall`、`memory_reflect`；
- `memory_document_list`、`memory_document_get`、`memory_document_patch`。

MCP 不暴露 Delete/Reprocess。审计已证明，运行中的异步 reprocess 可在 delete 后复活同一 Document，因此在完成更强的操作状态协调前不对 AI 客户端开放。

## 4. 真实验收

### Gateway

- List/Get：PASS；
- Patch `42 → 52`：PASS；
- 重复 Patch：HTTP 409 `PATCH_CONFLICT`；
- 错误 speaker 读取：HTTP 404。

### MCP 本机链路

- Retain → List → Get → Patch → Get：PASS；
- 重复 Patch 冲突保护：PASS；
- Speaker 跨用户隔离：PASS；
- 原有 Retain/Recall/Reflect：PASS。

### Cloudflare 公网链路

对 `https://memory.skyhighmonica.fyi/mcp` 执行同一组 Document API 验收，全部 PASS。

## 5. 风险与下一步

1. A07 附件入口与附件导出/恢复尚未验证；
2. Correction Log 尚未实现，当前 Patch 只保证当前值的确定性，不提供完整业务修订史；
3. Markdown Journal 最小投影已落地为 `scripts/project_markdown_journal.py`；隔离审计 bank 实机验收为 6 份 Documents 生成 2 份按日 Markdown，默认覆盖保护和带备份替换均 PASS；
4. 投影跑通后再决定 Correction Log、Session 和 Asset 层是否真有必要。

## 6. Obsidian 自动接入

- Vault：`/Users/weizhenliang/obsidian空间`；
- 生成目录：`AI/AI外置记忆/00-系统生成/原始记录/liangzai`；
- 首次真实投影：6 份 Documents → 2 份按日 Markdown；
- LaunchAgent：`com.skyhighmonica.personal-memory-journal`，每 3600 秒执行；
- 首次后台执行：exit code 0；
- 无变化重跑：跳过替换，backup 数量保持不变；
- 安全边界：Gateway Token 不离开服务器，Vault 的其他未提交内容和 Git 历史均未修改。

## 7. 人类可读性修正

- 日记正文改为“日期 → 时间 → 原文”，不再显示 UUID、SHA-256 和 `time_source`；
- 技术元数据保留在 Markdown HTML 注释和 `manifest.json`，不影响 Obsidian 阅读视图；
- 精确识别并从人类投影排除 6 条既有部署 smoke 记录，不删除 Hindsight 源数据；
- MCP smoke 已改为 `speaker=audit-mcp-core` + 稳定 `document_id=mcp-core-smoke`，后续部署不再污染个人记录；
- 旧投影历史统一保留在隐藏 `.history` 目录，不与正式日记并列。

## 8. ChatGPT Retain 502 事故与恢复

### 现象

ChatGPT 对 2026-09-18 原始记录连续两次调用 `memory_retain`，均收到 `502 Bad Gateway`。请求已到达 MCP 与 Gateway，故障不在 Cloudflare Tunnel。

### 根因

1. 新记录没有 `document_id`，但客户端传入了 `update_mode=append`；Hindsight 的 append 语义要求明确的目标 Document；
2. Gateway 接受任意类型 metadata，而 Hindsight 要求 metadata 的值全部为字符串；布尔值会触发上游 HTTP 422，此前被 Gateway 统一表现为 502。

### 修复

| 仓库 | 提交 | 修复内容 |
| --- | --- | --- |
| `memory-gateway` | `6488d9a` | 无 `document_id` 时忽略 `update_mode`，并补充非正文诊断日志 |
| `memory-mcp` | `e361900` | MCP 参数层同步约束，新记录不得使用 replace/append |
| `memory-gateway` | `d7daaf4` | metadata 在 Gateway 边界确定性转换为字符串 |

Gateway 单元测试 6/6 通过；重新部署后 Retain/Recall/Reflect 全链路通过。原故障组合“无 `document_id` + append”回归为 HTTP 200。

### 数据恢复

- 稳定 Document ID：`liangzai-journal-2026-09-18`；
- 事件时间：`2026-09-18T12:00:00+08:00`；
- 写入结果：HTTP 200，实际处理约 39.3 秒；
- 原始内容已完整保留，没有把失败重试制造成重复记录；
- Obsidian 投影结果：源 Documents 7 份，可见个人记录 1 份，精确排除部署 smoke 记录 6 份；
- 人类可读文件：`00-系统生成/原始记录/liangzai/2026-09-18.md`。
