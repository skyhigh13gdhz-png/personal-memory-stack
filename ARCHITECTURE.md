# Personal Memory 架构设计记录

状态：V1 已部署并通过真实验收；V2 为已讨论的目标设计，尚未实现。  
更新日期：2026-09-19

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

#### `memory-gateway`

- 所有 AI 客户端访问记忆系统的统一业务边界；
- 提供 Retain、Recall、Reflect API；
- 管理 Gateway Token、client、bank、speaker 等隔离字段；
- 通过 adapter 访问 Hindsight，不读取 Hindsight 内部数据库；
- 未来的 Record/Event Router 也应从这里扩展。

#### `memory-mcp`

- 把 Gateway HTTP API 转换为通用 MCP tools；
- 不直接访问 Hindsight，不保存记忆；
- 当前正式工具：`memory_retain`、`memory_recall`、`memory_reflect`；
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
服务开机自动恢复          PASS
```

V1 当前解决的是“让 AI 能记住和想起”，不是完整的个人记录系统。

## 3. V2 目标：个人数字记忆基础设施

V2 不推翻 V1，而是在 Gateway 后增加人类可读、可纠错、可再生成的数据主干。

```text
ChatGPT / Claude / Qwen / 其他入口
                     │
                     ▼
                Memory MCP
                     │
                     ▼
                Memory Gateway
                     │
                     ▼
                 Event Router
          ┌──────────┼───────────┐
          │          │           │
          ▼          ▼           ▼
    Record Store  Hindsight  Document Pipeline
          │       AI语义记忆       │
          │                        ▼
          ├── Session Store   Markdown Vault
          ├── Asset Store          │
          └── Revision Store       ▼
                                Obsidian
```

### 三类真相与投影

```text
Record / Session / Asset = Canonical Source，业务事实源
Hindsight                = AI Projection，语义记忆投影
Markdown Vault           = Human Projection，人类可读投影
```

因此：

- Markdown 删除后可以从事实源重新生成；
- Hindsight 损坏后可以从事实源重新 Retain；
- 更换 Obsidian 或 Hindsight 不会丢失核心业务数据；
- 不直接把 Hindsight 内部数据库当个人记录业务库。

## 4. V2 核心数据对象

### Record

表示“一条当时实际产生的记录”。建议字段：

```text
record_id
speaker
created_at
event_at
source
workspace
topic
content_type
original_content
corrected_content
session_id
asset_ids[]
revision
metadata
```

Record 负责回答：当时到底记录了什么，以及后来如何纠正。

### Session

表示“一段连续活动”，例如一次 ENA 实盘交流、项目讨论或旅行规划。建议字段：

```text
session_id
speaker
workspace
topic
started_at
ended_at
record_ids[]
asset_ids[]
metadata
```

Session 让 Document Engine 知道哪些消息、图片和分析属于同一件事。

### Asset

表示图片和附件原件。建议字段：

```text
asset_id
record_id
session_id
filename
mime_type
sha256
storage_path
created_at
metadata
```

职责边界：Asset Store 保存原件；Hindsight 理解图片；Markdown Vault 展示图片。

### Revision

纠错不能生成两条互相冲突的事实。正确流程是：

```text
record_correct(record_id)
          │
          ▼
revision N → N+1
          │
          ├── 更新事实源
          ├── 用稳定 document_id 更新/重处理 Hindsight
          └── 重新生成相关 Markdown 投影
```

## 5. V2 Gateway API 方向

在现有 Memory API 之外增加 Record/Session/Asset API：

```text
record_create
record_get
record_list
record_correct
record_delete

session_create
session_get
session_close
session_attach_record

asset_create
asset_get
asset_link
```

未来 `memory_retain` 的内部行为应升级为：

```text
① 创建 Record
② 保存原始内容并生成稳定 record_id
③ 投递给 Hindsight，document_id 关联 record_id
④ 保存处理状态
⑤ 更新 Markdown Journal 投影
```

第一版 Record Store 建议独立使用 PostgreSQL；Hindsight 自己的 PostgreSQL 继续由 Hindsight 管理。

## 6. Document Engine 与 Vault

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

## 7. 同步与多 Writer 原则

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

## 8. 自动化方向

```text
每天 23:50
Records + Sessions → Daily Builder → 日报

每周
日报 + 关键 Records + Hindsight Reflect → 周报

每月
日报 + 周报 + Hindsight Reflect → 月报

Session Close
交易 Session → Trading Document Builder → 实盘记录/复盘
```

定时器本身不是主要风险，Record 数据模型、附件入口和多 Writer 冲突才是主要风险。

## 9. 分阶段实施顺序

### Phase 1：V1 语义记忆主干

状态：已完成。

- Xray、Hindsight、Gateway、MCP、Cloudflare；
- Retain / Recall / Reflect；
- speaker 隔离；
- 本机与公网 smoke test。

### Phase 2：Record Store + Revision

- 建立独立 PostgreSQL 业务库；
- 实现 Record API；
- `memory_retain` 双写 Record Store 与 Hindsight；
- 用稳定 ID 处理纠错和重处理。

验收：当天记录 10 条、纠正 1 条，数据库、Markdown 与 Recall 结果一致。

### Phase 3：Markdown Journal

- 先生成按日排列的原始记录；
- 验证 Obsidian 可读；
- 暂不追求复杂日报。

### Phase 4：Session + Asset

- 串联连续交易或项目讨论；
- 保存图片/附件原件及 hash；
- 实测 ChatGPT 上传附件能否通过 MCP 稳定传到后端。

验收：一次包含 20 轮交流和 3 张图的交易 Session 能完整形成实盘记录。

### Phase 5：Document Engine

- 固定模板；
- 交易实盘、交易复盘、项目文档和知识笔记。

### Phase 6：日报、周报、月报与同步

- 自动化生成；
- Vault 同步方案实测；
- 明确多 Writer ownership 和冲突处理。

## 10. 工程治理原则

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

## 11. 当前已知风险

1. 当前服务器只有约 2GB RAM，依赖 4GB Swap，Hindsight 应保持低并发并持续观察；
2. 本机 Codex OAuth 凭据已按用户明确授权复制到服务器，服务器安全边界等同于账户凭据安全边界；
3. Cloudflare Tunnel token 可运行对应 connector，泄漏后必须立即轮换；
4. ChatGPT 上传图片原件能否稳定传入自定义 MCP 尚未实测；
5. Markdown 多端同步和双向修改规则尚未最终选型；
6. V2 数据模型一旦投入真实长期数据，迁移成本会上升，实施前需要先固定 schema 与 API contract。
