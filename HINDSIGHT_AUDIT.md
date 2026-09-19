# Hindsight 能力审计与 V2.1 决策计划

状态：A01–A06 已执行；A07–A08 待执行

目标环境：腾讯云正式机 `106.53.204.254`

首轮结果见 [AUDIT_RESULTS_2026-09-19.md](AUDIT_RESULTS_2026-09-19.md)。

原则：不靠文档推测当前版本行为，每个结论必须有 API 输入、输出和可重复验收证据。

## 1. 成功标准

本轮审计结束时必须能回答：

1. Hindsight Document 能否承担原始记录持久化；
2. 同 `document_id` 更新后是否不留冲突 memory；
3. 时间模型能否满足补录、相对时间和日记生成；
4. 长记录在不同 extraction mode 下的召回完整率和成本；
5. 附件能否从 ChatGPT 稳定到达 Hindsight 并取回原始 bytes；
6. 整套原文、metadata、附件与必要映射能否备份、恢复和迁移。

## 2. 实验顺序

### A01 原文完整性

- 通过现有 Gateway Retain 写入一条无隐私的唯一哨兵文本；
- 通过公开 Document API 定位并读回；
- 对 `original_text` 做逐字节/hash 比较；
- 记录 Document ID、content hash、memory unit 数量和耗时。

验收：开头、中间、结尾哨兵和完整 hash 一致。

### A02 Replace / Correction

- 使用稳定 `document_id` 写入“CRV 亏 42”；
- 确认 Recall 能找到 42；
- 用同 ID replace 为“CRV 亏 52”并 reprocess；
- 验证 Document 只有 52、Recall 找不到旧 42、可找到新 52；
- 重复相同请求，检查幂等性；
- 用错误 `expected_text` 模拟 `PATCH_CONFLICT`。

验收：无新旧冲突 memory，非匹配 Patch 不产生写入。

### A03 Delete / Reprocess

- 删除一条专用测试 Document；
- 确认 Document、chunks、memories 和附件映射的生命周期；
- 重处理未变更原文，检查是否产生重复 memory。

### A04 时间体系

固定当前时区后测试：

1. “今天 19:00 吃饭”；
2. “补录昨天 19:00 吃饭”；
3. “以前挺喜欢游泳”，无明确时间；
4. 一条文本同时描述昨晚、今早和今下午。

检查 retain timestamp、Document created/updated time、Memory `mentioned_at/occurred_*`、temporal Recall 和日记归档可确定性。

### A05 Tags / Metadata / List

- speaker、source、workspace、session 的写入与精确查询；
- any/all/strict 匹配；
- offset/limit 分页过程是否漏项或重项；
- 排序在多次请求中是否稳定；
- metadata 可读、可更新与可导出性。

### A06 长记录 Extraction A/B

- 用同一结构化长记录分别测 concise / verbose / verbatim；
- 固定问题集：睡眠、交易、午休、晚饭、金额、AI 项目；
- 记录每项召回成功率、memory unit 数、Retain/Recall 延迟与额外模型成本。

不仅对比 Recall，还要确认 Document 原文在所有模式下均完整。

### A07 附件 E2E

```text
ChatGPT 上传图片
  → 自定义 MCP 参数
  → Gateway
  → Hindsight Attachment
  → Document API 取回原始 bytes
```

记录文件名、MIME、字节数、SHA-256 和重复上传行为。

### A08 导出 / 备份 / 恢复

- 列出所有必须迁移的对象和映射；
- 生成可离线校验的导出包；
- 在隔离 bank/测试环境恢复；
- 比对 Document 数、原文 hash、附件 hash、metadata 和样本 Recall。

验收：不依赖直接读 Hindsight 内部表才能取回个人原始数据；否则视为 Canonical Source 的重要风险。

## 3. 证据记录格式

每项实验都要记录：

```text
experiment_id
hindsight_version
gateway_commit
mcp_commit
started_at / finished_at
request fixture
response artifact
database observation（仅用于交叉验证）
expected
actual
PASS / FAIL / BLOCKED
conclusion
```

不将 token、OAuth 凭据、真实个人记忆或附件提交到 Git。

## 4. 决策输出

审计完成后产出一张最终 Gap Analysis：

| 需求 | Hindsight 是否满足 | 证据 | 缺口严重度 | 决策 |
| --- | --- | --- | --- | --- |
| 原文 |  |  |  |  |
| 纠错 |  |  |  |  |
| 时间 |  |  |  |  |
| 查询 |  |  |  |  |
| 附件 |  |  |  |  |
| 审计 |  |  |  |  |
| 导出/恢复 |  |  |  |  |

最终只能选择一个明确方向：

1. Hindsight Documents 直接承担 Record Layer；
2. Hindsight + Gateway 薄索引/轻量 Correction Log；
3. 独立 Record Store，Hindsight 只作为 Semantic Projection。
