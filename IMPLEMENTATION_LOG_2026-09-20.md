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

### 时间精度修正

恢复时使用的 `12:00` 只是日期锚点，不是真实事件时刻。投影契约增加 `journal_time_precision=date`：仅知道日期的记录按日归档但显示“当日记录”；只有来源明确提供具体时刻时才显示 `HH:MM`。`created_at` 只用于回退归日，不再冒充事件发生时间。

后续发现客户端还会把日期编码为 `00:00`。因此未显式声明精度的午夜值默认按“仅日期”处理；真实午夜事件必须声明 `journal_time_precision=minute`。Obsidian 同步也由整体替换目标目录改为目录内 `rsync --delete`，保留目录 inode 和文件监听，解决同步后需重启 Obsidian 才能看到新文件的问题。

## 9. 时间范围分析漏召回修正

### 现象与证据

2026-09-17 原始 Document 完整存在并含饮食记录，Hindsight 也生成了 3 个 memory units；但 ChatGPT 做 9 月 14–20 日饮食分析时，Reflect 在 120 秒处失败，随后多轮语义 Recall 只命中 16 日和 18 日。语义召回按相关度返回事实，本来就不保证覆盖日期范围内每一天；用日期字符串搜索正文同样无法匹配只存在于 `retain_params.event_date` 的日期。

### 修复契约

- Gateway Document List 增加包含边界的 `date_from` / `date_to` 过滤与 `include_text=true` 原文返回；
- MCP 增加 `memory_document_range`，一次确定性返回日期范围内全部 Documents 和完整原文；
- MCP 总指令明确规定：日报、周报、月报及饮食/睡眠/交易等范围统计必须先调用 Date Range，不能用 Recall/Reflect 判断某天没有记录；
- 日期过滤仍强制 speaker 隔离，反向日期范围返回 422。

### 部署与真实验收

| 仓库 | 提交 | 内容 |
| --- | --- | --- |
| `memory-gateway` | `c3c1cbc` | Document 日期范围过滤、完整原文返回与测试 |
| `memory-mcp` | `7d5fbdd` | `memory_document_range` 与范围分析工具约束 |
| `memory-gateway` | `47bf379` | 国内服务器部署优先使用本机 Xray |
| `memory-mcp` | `3128554` | 国内服务器部署优先使用本机 Xray |

服务器本机 MCP 与 Cloudflare 公网 MCP 的 Date Range 验收均 PASS。对 `speaker=liangzai` 执行 2026-09-14 至 2026-09-20 真实查询，确定性返回 16、17、18 日共 3 份完整 Documents；17 日原文确认包含炒面、西瓜、花卷和烤鸭。

## 10. Daily V2 质量闭环与持续脉络候选层

- Daily V2 增加 100 分确定性评分：证据完整性 35、信息架构 25、分析边界 15、语言风格 15、可读性 10；
- 交付阈值为 85 分，结构错误、禁用措辞或用户稳定用词丢失均为硬失败；
- 2026-09-20 人工 V2 黄金样例得分 100，首次智谱自动结果得分 70 并拒绝交付；
- Prompt 版本升级为 `daily-editorial-v2.1`，避免规则变化后错误复用旧缓存；
- Provider 已返回但未过门禁的响应写入独立 `daily-v2-rejected-v1` 隔离文件，不覆盖合格产物、不自动重试；
- 持续脉络新增零 LLM 候选构建器，只收集与三个已确认 Subject 明确关联的 Evidence Units；
- 2026-09-20 生成 7 个候选关联：AI 外置记忆 2、睡眠与精力 3、加密交易节奏 2；全部为 `pending`，当前状态更新为 0；
- 持续脉络增加 Claim 编辑门禁：每个 promoted Claim 必须从原始复合单元截取逐字 facet，不能把同句中的交易内容错误带入项目脉络；
- “AI 外置记忆”首份编辑预览已合并 09-16、09-18 的历史确认 Claim 与 09-20 的两个草稿 Claim；当前状态保持待确认；
- 初版预览因“近期进展/状态记录”和时间线重复而被自检退回，现收敛为单一演进时间线，同一事实只展示一次；
- 周报/月报未继续扩建，符合“日报 → 持续脉络 → 周/月报”的当前优先级。

## 11. 长期记忆状态层纠偏

- 明确“持续脉络”不是对象类型或 Obsidian 一级目录，而是每个 Memory Subject 的状态演进属性；
- 产品命名调整为 `10-周期回顾` 与 `20-长期记忆`，目标、承诺、决策和未决问题默认作为 Subject 内部字段；
- 新增 `subject-state-v1`，区分 `direct_fact`、`derived_state` 与 `hypothesis`；
- Derived State 至少需要 2 条 Claim 且跨 2 个日期；Hypothesis 不能使用 high confidence，必须进入 `review_required`；
- 新增状态生命周期和替换校验：同一 `state_key` 只能有一个 current，新状态只能 supersede 同 key 且已关闭的旧状态；
- 项目/系统的高置信状态可标 `auto_eligible`；人物、健康、资产和策略的派生状态默认人工评审；
- 基于 09-16、09-18、09-20 四条项目 Claim 生成第一份 Living Memory Object 私有预览：5 个状态项、4 条证据 Claim，其中 3 项可自动维护、2 项需评审；
- 该预览 `as_of=2026-09-20`，不冒充当前实时状态，尚未进入正式长期记忆目录。

## 12. 配置驱动的 Subject 与 Vault 布局

- 将 `subject_type`、`collection`、`parent_subject_id` 分离，分别控制模板、导航目录和对象从属；
- 交易账户与交易策略可同属“资产与策略”集合，但分别使用 account/strategy 模板；
- component 可嵌套在父项目下，Memory Gateway/Hindsight 不再因类型自动与项目平级；
- `subject-registry-v2` 为现有三个 Subject 增加 template、collection 和 parent 字段；
- `memory-layout-v1` 把目录名与代码解耦，常规目录调整只改配置；
- `memory_layout.py` 已实现 validate、plan、apply、rollback；
- 迁移仅处理 manifest 管理且哈希未变化的文件，支持全量预检、目标冲突拒绝、路径逃逸保护和回滚日志；
- 当前只在临时 Vault 自动化测试，没有迁移用户正式 Obsidian 文件。

## 13. Subject Registry 治理闭环

- 建立第一版正式 `config/subjects.json` 和 `config/memory-layout.json`：先纳入 AI 外置记忆、小红书店铺、睡眠与精力、加密交易节奏四个已具持续维护价值的对象；
- 增加模板目录及类型兼容校验，防止把项目模板误套到健康、人物或策略对象；
- `memory_layout.py register` 可在投影完成后刷新受管文件路径与哈希，补齐“生成 → 登记 → 安全迁移”的闭环；
- 增加人类可读 Subject Registry 审阅页；人物、宠物、账户和内部组件证据不足时不自动创建空壳对象；
- 正式 manifest 当前为空，意味着现有 Vault 文件均未被擅自接管，首次只读计划只会报告待投影对象。

## 14. 人类视图与机器元数据分层

- 修正“`subject_id` 属于人类有用属性”的错误表达：它是永久机器身份，用户日常无需查看或维护；
- 新增 `HUMAN_VIEW_CONTRACT.md`，规定新的人类页面默认不使用 YAML 属性展示机器治理字段；
- Subject Registry 明确为低频系统治理页，只在对象晋升、纠正分类/归属、改名、合并和归档时使用；模板通常由分类自动选择；
- Registry 可见正文改为中文分类、自然语言归属、存放位置和长期跟踪理由，模板 ID、对象 ID 和投影版本移入隐藏注释；
- Living Memory Object 移除 YAML 中的 type/subject_id/projection，只保留正文可理解的“更新至”日期；派生状态不显示工程术语，假设改写为“待确认”；
- Daily V2 默认已隐藏证据详情；旧 Daily V1 的重复概览和来源 UUID 被标记为历史展示问题，不再作为新输出规范。

## 15. Profile / State / Timeline 框架闭环

- 修正把具体项目预览误称为框架成果的问题，新增 `ROADMAP.md` 固定 P0–P4 的推进顺序；
- 长期对象正式拆分为 Profile（基本档案）、State（当前状态）、Timeline（演进记录）三层；
- Profile 强制回答对象“是什么、用来做什么、为什么存在、范围边界”等稳定信息，缺少必填字段时拒绝投影；
- 项目、健康主题、人物、宠物、账户/资产、策略、系统组件和独立目标均有独立 Profile 契约；
- State 栏目也从项目渲染器中解耦，由对象模板决定，健康、宠物和策略不再套项目栏目；
- 高影响范围补充 pet、account、habit_track，相关派生状态必须进入人工评审；
- 完成端到端自动化验收：三层组合投影 → Manifest 登记 → 哈希校验 → 布局迁移 → 回滚恢复；
- 测试增至 92 项。P0 基础框架完成，下一阶段仅以“AI 外置记忆”做首个正式对象验收。

## 16. 首个正式对象试运行

- 用户明确要求先按当前模板继续推进、后续持续优化，因此新增 `trial` Profile 状态，区别于未获准使用的 `draft` 和稳定确认的 `confirmed`；
- “AI 外置记忆”三层页面已进入正式 `20-长期记忆/项目` 目录，并登记为第一个 managed projection；
- 新增受保护 `publish`：更新前核对旧 Manifest 哈希，拒绝覆盖人工修改，拒绝接管未登记的同名文件；
- 相同内容重复发布返回 `unchanged`，不会重复写入；正式 Vault 已完成真实幂等验收；
- 自动化测试增至 95 项。P1 试运行闭环完成，下一主线进入 P2 持续更新机制。
