# Personal Memory 架构设计记录

状态：V1 已部署并通过真实验收；V2.1 的 Document/timestamp/Patch 薄封装与 Markdown 原始记录投影已部署，附件链路待继续验证。
更新日期：2026-09-20

## 1. 项目目标

把不同 AI 客户端中的对话、事实、分析和附件沉淀为可迁移的个人数字记忆基础设施，同时满足两类需求：

1. AI 能跨会话语义召回和综合分析；
2. 人能查看、纠正、整理和长期保存原始记录及 Markdown 文档。

核心原则是客户端、业务事实、语义记忆和人类文档相互解耦，不让任何一个模型、客户端或存储引擎成为不可替换的唯一依赖。

## 2. 当前 V1：已经部署的语义记忆主干

```text
ChatGPT / Claude / Qwen / 其他 MCP Client
                     │
                     ▼
               Memory MCP
           127.0.0.1:8000/mcp
                     │ HTTP
                     ▼
              Memory Gateway
             127.0.0.1:8787
                     │
                     ▼
                 Hindsight
             127.0.0.1:8888
                     │
                     ▼
          Hindsight 内部持久化存储

公网入口：
memory.skyhighmonica.fyi
          │
          ▼
Cloudflare Tunnel → 127.0.0.1:8000
```

### V1 组件职责

#### `ubuntu-vps-proxy-kit`

- 为中国大陆服务器提供 Xray 选择性出站；
- SOCKS：`127.0.0.1:10808`；
- HTTP：`127.0.0.1:10809`；
- 国内和私网流量直连，海外资源按规则走 Xray；
- 不属于记忆业务，只是服务器网络基础设施。

#### `memory-server-infra`

- 初始化服务器、Swap、Docker；
- 部署 Hindsight；
- 准备 OpenAI/Codex OAuth 或其他模型 Provider；
- 配置 Docker 出站代理和 Hindsight 专属透明代理；
- 限制 Hindsight API/UI 不直接暴露公网；
- 提供健康检查、备份和恢复入口。

### LLM 分工与额度边界

当前线上保留全局 `openai-codex / gpt-5.6-luna` 作为未覆盖操作的默认值，已对高频操作启用按操作的智谱路由：

```text
Retain（抽取、整理记忆）       → 智谱 `glm-4.5-air`
Reflect（跨记录综合与推理）    → 智谱 `glm-4.5-air`
Recall（检索）                 → 不调用 LLM
Embedding（向量化）            → 本地模型
Consolidation（合并、去重）     → 智谱 `glm-4.5-air`
Mental Model Refresh           → 暂时继承全局 Codex
```

Retain、Consolidation 和 Reflect 均已迁移到智谱。智谱操作关闭跨 Provider fallback，避免失败后静默回退 Codex，使成本、时延和质量数据失真。Mental Model Refresh 仍是唯一继承全局 Codex 的 Hindsight LLM 操作，后续需单独迁移和验收。批量导入会触发 Consolidation；当后台任务占满 LLM 并发槽时，Reflect 可因排队显著变慢，这与 Provider 路由是否生效是两个问题。

Recall 的 `max_results` 是本次检索返回的 Top-K 条数，不是存储上限，也不会删除记忆。`max_results=5` 只返回排名最高的 5 条，跨日期或主题较宽时可能漏掉目标日期。普通事实检索可使用 10–20，宽泛检索可使用 50–100；需要完整日期覆盖的日报、周报、月报必须使用 Document Date Range，不能仅依赖 Recall Top-K。

智谱国内开放平台使用 `https://open.bigmodel.cn/api/paas/v4`；Hindsight 文档中的 `zai` 默认地址是国际站，不能在未确认 Key 所属平台时混用。API Key 只写入服务器 root-only 环境文件，不进入 Git、日志或命令历史。

#### `memory-gateway`

- 所有 AI 客户端访问记忆系统的统一业务边界；
- 提供 Retain、Recall、Reflect 以及 Document List/Date Range/Get/Patch API；
- 管理 Gateway Token、client、bank、speaker 等隔离字段；
- 通过 adapter 访问 Hindsight，不读取 Hindsight 内部数据库；
- 已实现 Document 查询、speaker 隔离、同 Document 串行化和 CAS Patch；投影能力仍应从这里作薄封装。
- 在 Retain 边界规范化上游契约：没有 `document_id` 的新记录忽略 `update_mode`；metadata 的非字符串值确定性转换为字符串，避免将 Hindsight 422 误表现为不透明的 502。

#### `memory-mcp`

- 把 Gateway HTTP API 转换为通用 MCP tools；
- 不直接访问 Hindsight，不保存记忆；
- 当前正式工具：`memory_retain`、`memory_recall`、`memory_reflect`、`memory_document_list`、`memory_document_range`、`memory_document_get`、`memory_document_patch`；
- 使用稳定 `speaker` ID 隔离共享 ChatGPT 账号下的不同讲述者；
- 默认只监听本机，由 Cloudflare Tunnel 发布公网。

#### Cloudflare Tunnel

- 只负责安全公网接入和稳定 HTTPS hostname；
- Public Hostname：`memory.skyhighmonica.fyi`；
- Origin Service：`http://127.0.0.1:8000`；
- Cloudflare 侧 Path 留空；客户端 MCP URL 才包含 `/mcp`；
- 采用 remotely-managed Tunnel，服务器使用 root-only token 运行 connector。

### V1 已验收能力

```text
Retain                    PASS
Recall                    PASS
Reflect                   PASS
MCP 本机完整链路          PASS
Cloudflare 公网完整链路   PASS
speaker 隔离基础能力      PASS
Document List/Get/Patch   PASS
Document Date Range 原文  PASS
Patch 冲突与 speaker 隔离   PASS
服务开机自动恢复          PASS
```

V1 当前解决的是“让 AI 能记住和想起”，不是完整的个人记录系统。

## 3. V2.1 候选架构：先复用 Hindsight Documents

新的设计原则是：先完整理解 Hindsight 的公开数据模型，再决定 Gateway 需要补什么。独立 Record Store、Session Store、Asset Store、复杂 Revision Store 和 Event Router 全部暂停开发，不代表永久取消。

```text
ChatGPT / Claude / Qwen / 其他入口
                     │
                     ▼
          保守 Normalizer（客户端）
                     │
                     ▼
                Memory MCP
                     │
                     ▼
            Memory Gateway
          权限 / 隔离 / 确定性操作
                     │
                     ▼
          Hindsight Documents
          ├── document_id
          ├── original_text
          ├── metadata / tags
          ├── attachments
          └── memory units / temporal model
                     │
                     ▼
           Markdown Projector
                     │
                     ▼
                  Obsidian
```

上图是待验证候选架构，不是已交付能力。Hindsight Documents 只有在通过原文、更新、时间、附件、导出和恢复测试后，才能升级为 Canonical Record Source。

## 4. 已发现的原生能力映射

| 业务需求 | Hindsight 候选能力 | 当前状态 |
| --- | --- | --- |
| 完整记录内容 | `Document.original_text` | A01 已验证逐字节一致 |
| 稳定记录 ID | `document_id` | A02 已验证 replace 语义；幂等回归待补强 |
| AI 语义记忆 | memory units / Recall / Reflect | V1 已验收 |
| 事件时间 | retain `timestamp` / `occurred_*` | A04 基础语义已验证，多事件抽取粒度可变 |
| 写入时间 | Document `created_at` / `updated_at` | A02/A04 已验证 |
| speaker / source / session | bank、tags、metadata | A05 小数据量查询/分页已验证 |
| 图片和附件 | Document attachments | Hindsight 侧有能力，ChatGPT→MCP 链路未验证 |
| 纠错 | 同 `document_id` replace / reprocess | A02 确认旧 memory 消失；审计历史仍需薄补丁 |
| 人类可读文档 | Documents → Markdown | 已实现按日只读投影，并自动同步到本机 Obsidian Vault |

`Semantic Memory ≠ Raw Record` 仍然是有效判断；变化的是 Raw Record 不再默认必须由另一套 PostgreSQL 承担。

## 5. 原始内容与 Normalizer 边界

客户端常驻规则应保持极短：

```text
调用 memory_retain 前，对记录做保守的基础纠错：
仅修正高度确定的错别字、ASR 错词、重复词、标点及格式错误。
不得总结、润色、删减、补充、推断或改变原意和确定程度。
不确定时保持原文。
```

“原始记录”必须进一步明确是用户/ASR 原始输入，还是保守纠错后的文本。能力审计期间保留两个逻辑概念：

```text
source_text       用户或 ASR 真正产生的内容
normalized_text   送入 Hindsight 的保守纠错内容
```

是否同时持久化两者，需要根据审计价值、隐私与存储成本决定。

## 6. 纠错契约：局部 Patch，不整篇重写

LLM 负责理解用户想修改哪里，Gateway 只执行确定、可验证、可审计的 compare-and-swap：

```text
memory_patch(
  document_id,
  expected_text,
  replacement_text
)
```

Gateway 必须确认当前内容仍精确包含 `expected_text`；否则返回 `PATCH_CONFLICT` 并不修改。修改成功后使用同一 `document_id` replace/reprocess，并验证旧 memory 已消失。

Hindsight replace 即使能更新当前内容，也未必提供完整纠错审计历史。如实验确认缺失，优先补一个轻量 append-only Correction Log，不立即建设完整 Revision Store。

## 7. 时间模型

必须区分：

```text
ingested_at    系统什么时候得知
timestamp      retain 时的事件时间/解释锚点
occurred_*     Memory 中提取的事件时间
journal_date   可选，Markdown 确定性归档日期
```

不先为每条记录强制添加 `date:YYYY-MM-DD` tag。先实测 Hindsight 时间语义、Document List 查询限制以及多事件长文本。如日记投影仍无法稳定实现，再增加最薄的应用层索引。

## 8. Document Engine 与 Vault

Document Engine 采用“固定模板 + LLM 填充”，而不是让模型自由决定文档结构。

计划支持：

```text
daily
weekly
monthly
trading_live
trading_review
project_log
knowledge_note
```

建议 Vault：

```text
Personal Vault/
├── 00 原始记录/
├── 01 日报/
├── 02 周报/
├── 03 月报/
├── 投资相关/
│   ├── 合约/复盘/
│   └── 合约/实盘回放训练/
├── 项目/
├── 知识/
└── assets/
```

Obsidian 只是 Human UI，不是后端，也不要求一直在线。

## 9. 同步与多 Writer 原则

服务器 AI 和用户本人都可能修改内容，因此不能让双方随意重写同一个 Markdown 文件。

建议 ownership：

```text
journal/raw/        Server-owned
daily/generated/    Server-generated
daily/notes/        Human-owned
knowledge/          Human-owned，AI 通过明确操作修改
trading/review/     Human + AI 协作，必须保留 revision
```

Git、Syncthing 或其他同步方式需要根据 Mac、iPhone、国内网络和冲突体验单独实测，当前不预先锁死。

## 10. 自动化方向

```text
每天 23:50
Hindsight Documents → Daily Builder → 日报

每周
日报 + 关键 Records + Hindsight Reflect → 周报

每月
日报 + 周报 + Hindsight Reflect → 月报

Session Close
交易 Session → Trading Document Builder → 实盘记录/复盘
```

定时器本身不是主要风险，Record 数据模型、附件入口和多 Writer 冲突才是主要风险。

## 11. 分阶段实施顺序

### Phase 1：V1 语义记忆主干

状态：已完成。

- Xray、Hindsight、Gateway、MCP、Cloudflare；
- Retain / Recall / Reflect；
- speaker 隔离；
- 本机与公网 smoke test。

### Phase 2：Hindsight 能力审计

- Document 原文完整性；
- 同 `document_id` replace / delete / reprocess；
- timestamp 与 temporal recall；
- tags / metadata / 分页 / 排序；
- attachments 和原始 bytes；
- 全量导出、备份、恢复和迁移；
- concise / verbose / verbatim 长记录 A/B。

详细步骤和决策门见 [HINDSIGHT_AUDIT.md](HINDSIGHT_AUDIT.md)。

### Phase 3：Gateway/MCP 最小改造

状态：已完成并在服务器本机及 Cloudflare 公网链路验收。

- 保留 `memory_retain` / `memory_recall` / `memory_reflect`；
- 只补审计证明缺失的原文查询、Patch 纠错和时间参数；
- 不在 Gateway 内复制 Hindsight 已有的数据模型。

### Phase 4：Markdown Journal

状态：最小只读投影器已实现；隔离审计 bank 和本机真实 Obsidian Vault 均已验收。macOS LaunchAgent 每小时投影 `speaker=liangzai`，无变化时跳过，变化时替换并保留上一版。

- 先生成按日排列的原始记录；
- 验证 Obsidian 可读；
- 暂不追求复杂日报。

原始记录同步直接调用 Gateway Documents API（List/Get）生成确定性 Markdown，不调用 Recall、Reflect 或 LLM。本机手动入口为 `bash scripts/sync_obsidian_vault.sh`；`bash scripts/install_macos_obsidian_sync.sh` 安装每小时运行的 LaunchAgent。

### Phase 5：附件与 Session 缺口

- 串联连续交易或项目讨论；
- 先复用 Hindsight Attachment，只在不足时增加 Asset 层；
- 实测 ChatGPT 上传附件能否通过 MCP 稳定传到后端。

验收：一次包含 20 轮交流和 3 张图的交易 Session 能完整形成实盘记录。

### Phase 6：Document Engine

- 固定模板；
- 交易实盘、交易复盘、项目文档和知识笔记。

### Phase 7：日报、周报、月报与同步

- 状态：尚未实现，不把当前原始 Markdown 投影误称为日报。
- 先实现版本化 `daily-v1` 固定结构，再向周报、月报扩展；
- 数据源使用 Document Date Range 取得当日全量原文，不使用 Recall Top-K 代替完整性；
- 固定栏目为：事实概览、睡眠/身体、饮食、运动、情绪/关系、工作/项目、交易/财务、决策/待办、不确定/缺失和来源引用；
- 先生成固定 JSON Schema，再确定性渲染 Markdown；保存 source document IDs、source hash、template version 和 model route；
- 同一 source hash + template version 重跑必须幂等，无变化时跳过；
- 日报存入独立目录，默认不自动 Retain 回记忆库，避免生成内容形成反馈循环；
- 自动化生成；
- Vault 同步方案实测；
- 明确多 Writer ownership 和冲突处理。

## 12. 决策门

```text
Hindsight 原生能力
        ↓
个人记忆真实需求
        ↓
还缺什么？
        │
        ├─ 不缺     → 直接复用
        ├─ 小缺口   → Gateway 薄封装/轻量索引
        └─ 核心缺口 → 新增独立组件
```

只有任一条被实验证明，才启动独立 Record Store：

- 无法通过公开 API 完整读取原文；
- replace/delete 会留下冲突 memory 或不能稳定更新；
- 无法做可验证的全量导出和恢复；
- 附件原件不可导出或生命周期不可控；
- Hindsight 升级导致作为事实源的 API 无法保持兼容；
- 需求必须依赖强事务、完整审计或高级查询，而薄封装无法安全实现。

## 13. 工程治理原则

```text
GitHub       = 唯一可写 Source of Truth
Gitee        = 中国大陆只读部署镜像
正式服务器   = 部署目标，不在服务器手工养代码
```

- 四个组件仓保持各自职责；
- `personal-memory-stack` 只负责编排、秘密注入和全链路验收；
- 新功能先进入对应仓库，再由安装器部署；
- 所有安装脚本必须可重复执行、有硬超时、失败可诊断；
- OAuth、API Key、Gateway Token、Tunnel token、真实记忆和附件不得进入 Git；
- V1 与 V2 分阶段验收，不把未实现设计写成已交付能力。

## 14. 当前阶段结论

A01–A06 的正式机结果已证明：当前没有启动独立 Record PostgreSQL 的证据。Gateway/MCP 的 Document/timestamp/CAS Patch 最薄封装已于 2026-09-20 部署，本机和 Cloudflare 公网端到端验收均通过。

A08 已通过无附件的公开 API 导出/隔离恢复。在 A07 附件链路及附件备份回归通过前，Hindsight 仍不升级为已定案的唯一 Canonical Source。详细证据见 [AUDIT_RESULTS_2026-09-19.md](AUDIT_RESULTS_2026-09-19.md)。

## 15. 当前已知风险

1. 当前服务器只有约 2GB RAM，依赖 4GB Swap，Hindsight 应保持低并发并持续观察；
2. 本机 Codex OAuth 凭据已按用户明确授权复制到服务器，服务器安全边界等同于账户凭据安全边界；
3. Cloudflare Tunnel token 可运行对应 connector，泄漏后必须立即轮换；
4. ChatGPT 上传图片原件能否稳定传入自定义 MCP 尚未实测；
5. Markdown 多端同步和双向修改规则尚未最终选型；
6. Hindsight Documents 是否足以作为长期 Canonical Source 尚未验证；
7. replace 可能不保留业务所需的纠错审计历史；
8. `original_text` 是否指未处理的 `source_text` 还是 `normalized_text` 尚未定义；
9. 一条长 Document 可能包含多个事件时间，单一 timestamp 不能直接等价于日记归档日期。
10. 运行中的异步 reprocess 可在 delete 之后重建同一 Document，Gateway 必须序列化同 Document 的变更操作。
