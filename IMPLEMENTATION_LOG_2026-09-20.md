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
