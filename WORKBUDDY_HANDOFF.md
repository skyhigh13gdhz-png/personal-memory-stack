# WorkBuddy 任务交接单

> 用途：把边界清楚、可独立验收的工程任务交给另一名 Coding Agent。产品语义、个人数据判断和最终上线仍由主线统一评审。

## 当前领取顺序

> **2026-09-22 紧急架构冻结，优先级高于本文后续旧任务**：Daily V2 的“句子分类后重组”路线已判定为架构缺陷并冻结。WB-07 已完成并由主线接受；WB-04/WB-05/WB-06 继续冻结，不合并 main、不安装调度器。先阅读 `DAILY_PRODUCT_RESET.md`、`EVENT_BLOCK_SPEC.md`、`reviews/WB07_EVENT_FIRST_RED_TEAM.md` 和 `config/daily-v2.freeze`，然后从 WB-08 开始。

> **WB-08～WB-11 首轮复核状态**：详见 `WORKBUDDY_REVIEW_WB08_11.md`。现有四提交不得合并；保留原 SHA，
> 按 `WB-08R → WB-09R → WB-10R → WB-11R` 追加修复提交，不重写历史。修复期间仍不得解冻或写正式日报。

1. `WB-07` Event-first 日报架构独立红队评审；
2. `WB-08` 原文直投 LLM 基线与匿名对照包；
3. `WB-09` 事件边界反例集与盲评量表；
4. `WB-10` Event Block schema 与隔离验证器；
5. `WB-11` 旧 Daily V2 删除/迁移影响图（只分析，不改生产）；
6. `WB-04` 日报分类体系配置化（冻结，不再继续）；
7. `WB-05` 派生缓存有效性与可恢复重建（暂停，待新 schema）；
8. `WB-06` 运行状态、失败日期与隔离件可见性（暂停，待新状态语义）；
9. `WB-02` 图片附件 A07 可行性验证。

支持两种执行模式：

- **单项模式**：每项经主线复核合并后再开始下一项；
- **批量串行模式**：本轮可连续完成 `WB-08 → WB-09 → WB-10 → WB-11`，不等待中途复核。每项必须形成独立 commit、独立交付报告和测试记录；后一项以上一项 commit 为基线，形成一条可逐层审查、逐层回退的提交链。禁止把多项 squash 成一个提交。

批量串行模式仍禁止直接修改或推送 `main`、部署和调用外部 API。用户已授权 WorkBuddy 只读使用真实个人数据做本机评估；
任一阶段出现测试失败、需求冲突、需要改变产品语义时，停止在当前阶段并报告；不得带病进入下一项。

## 协作规则

1. 单项模式每次只领取一个任务；批量模式按已授权顺序连续执行。始终使用独立 worktree 或独立分支，禁止直接改稳定工作目录。
2. 开工前记录仓库、基线 commit 和 `git status --short`；若基线不一致，先停止并报告。
3. 不把任何 Token、OAuth 凭据、个人原始记录、Vault 内容、服务器 `.env` 或生产日志提交到 Git；真实数据不得复制进 fixture、快照、交接报告或命令输出。
4. 产品文件、脚本、服务名和用户界面中不得加入 `workbuddy`、`codex` 等工具品牌。
5. 默认只提交代码、测试和文档，不部署生产、不修改真实 Vault、不调用外部 LLM、不上传个人数据。允许只读分析真实 Vault，并把所有真实数据产物写入 Git 忽略的本机评估目录。
6. 交付必须包含：改动目的、文件列表、测试结果、已知风险、commit SHA；不能只说“已完成”。
7. 不顺手重构任务范围外的代码；发现架构问题记录为建议，不自行扩大范围。

## WB-01 本机日常增量任务（优先外包）

> 首次实现 `94d6f28` 已完成主线复核，返修要求见 `WORKBUDDY_REVIEW_WB01.md`。WB-01R 通过前不得安装或进入 WB-02。

### 仓库和基线

- 仓库：`personal-memory-stack`
- 基线：`bc5691f`
- 建议分支：`feature/local-incremental-runner`
- 允许修改：`scripts/`、`tests/`、`README.md`、调度配置模板
- 禁止修改：Daily V2 Prompt、评分阈值、长期对象模板、身份归属规范

### 目标

实现 macOS 本机无人值守增量运行器，因为 Obsidian Vault 位于本机，调度器不应安装在远端 Ubuntu：

1. 周期性执行原始记录投影；
2. 次日生成前一自然日缺失的 Daily V2，不反复重写当天日报；
3. 每轮刷新运行状态页；
4. 使用运行锁防止重叠；
5. 失败采用有限次数重试，保留结构化日志并返回非零状态；
6. 没有变化时不调用 LLM；
7. 提供 install / status / uninstall，但安装脚本默认仅生成或预览配置，真实安装必须显式确认。

### 设计边界

- 复用现有 `sync_obsidian_vault.sh`、`sync_daily_v2.py`、`render_generation_status.py`，不得复制实现；
- 配置通过独立环境文件或环境变量注入，LaunchAgent plist 不保存密钥；
- 时区固定为 `Asia/Shanghai`；
- 当前日只同步原始记录；正式日报默认处理“昨天”以及更早的缺失日期；
- 同一 Speaker、Provider、既定用途沿用现有持续授权策略；
- 日报失败不得覆盖已有正式文件。

### 验收条件

- 至少覆盖：无变化、缺失日报、已有日报、并发锁、单日失败、重试上限、路径含中文和空格；
- 所有测试使用临时目录和 fake commands，不读取真实 Vault 或真实 Token；
- `python3 -m unittest discover -s tests -v` 全部通过；
- 提供一次 `--dry-run` 示例输出；
- README 写明实际安装和回滚方法。

## WB-02 图片附件 A07 可行性验证（WB-01 完成后）

### 仓库和基线

- 主仓库：`personal-memory-stack`，基线以领取任务时 `main` 最新 commit 为准
- 只允许新增审计脚本、fixture、测试和报告；未经确认不得修改生产 API
- 建议分支：`research/attachment-a07`

### 目标

验证一张测试 PNG 能否完成：客户端参数 → MCP → Gateway → Hindsight Attachment → 原始字节取回，并记录文件名、MIME、字节数、SHA-256、重复上传和删除行为。

### 验收条件

- 先使用无个人信息的合成小图；
- 报告必须明确区分“官方接口存在”“本机实测通过”和“仍属推测”；
- 若 Hindsight 附件接口不可用，给出独立对象存储方案，但不直接引入新基础设施；
- 产出最小 API contract 和 Obsidian `![[...]]` 投影建议；
- 不把 base64 图片直接塞进 Markdown 或 Git fixture。

## WB-03 Retain 幂等与异步 operation 调研（WB-02 之后或独立领取）

### 仓库和基线

- `memory-gateway`：`b58f86a`
- `memory-mcp`：`928c61d`
- 建议分支：`feature/retain-operation-safety`

### 第一阶段只做调研和测试设计

1. 确认 Hindsight 异步 operation 的查询接口、终态、失败信息和保留周期；
2. 设计客户端 `idempotency_key` 到稳定 Document / operation 的持久化映射；
3. 明确进程重启、并发相同请求、相同文本不同事件、失败重试的语义；
4. 给出存储选择、迁移和回滚方案；
5. 未经主线确认，不直接引入 Redis、PostgreSQL 或新的常驻服务。

### 必须覆盖的测试矩阵

- 同一幂等键并发两次，只产生一次上游 Retain；
- 同一幂等键、不同 payload 返回冲突；
- 同一文本但不同时间或显式不同键允许成为两条记录；
- Gateway 重启后幂等记录仍有效；
- operation 成功、失败、超时、未知和过期状态可区分；
- 不把 `accepted` 呈现为 `completed`。

## 暂不外包给 WorkBuddy

- Claim → State 的产品语义和晋升政策；
- Monica / liangzai 的身份归属规则及称谓决策；
- 睡眠、交易、宠物等对象模板的内容质量判断；
- 日报、周报的风格与人类可读性评审；
- 任何需要读取真实个人日记或向外部 LLM 发送个人数据的工作。

这些任务需要连续理解用户偏好、风险边界和既有设计，拆给另一个 Agent 的复核成本通常高于节省的额度。

## WB-04 日报分类体系配置化（当前推荐领取）

### 仓库和基线

- 仓库：`personal-memory-stack`，基线以领取时 `main` 最新提交为准；开始前确认工作区干净。
- 建议分支：`feature/configurable-daily-taxonomy`
- 允许修改：新增 taxonomy 配置、配置加载/校验模块、测试、README 和规范文档。
- 禁止修改：真实 Vault、生产服务、LLM 凭据、用户原始记录、Daily V2 文案质量判断、当前 Subject 数据。

### 目标

把 `render_daily_v2_editorial.py` 中面向具体用户的栏目、分组标题、显示顺序和回退规则迁移到可校验配置；程序只保留证据、时间、去重、事实/分析边界等通用不变量。

1. 提供内置通用默认 taxonomy 与个人覆盖配置，未配置时行为必须与当前主线一致；
2. 配置至少覆盖 section ID/标题/顺序、group ID/标题/顺序和确定性 fallback 关键词；
3. 未知内容进入稳定的 `other/uncategorized`，不得由 LLM 临时创造目录；
4. 新用户可以复制示例配置启动，不需要改 Python；
5. 配置错误（重复 ID、未知 section、空标题、非法 fallback）启动即失败；
6. renderer、pipeline、score 共用同一份加载结果，禁止各自复制常量；
7. 保持现有 JSON 与 Markdown 兼容，禁止顺手改日报文风或真实分类结果。

### 验收条件

- 默认配置下现有全量测试无回归；
- 新增至少两套 fixture：当前个人配置、完全不同的示例用户配置（例如育儿/科研），证明无需改代码即可改变分组；
- 覆盖配置合并、未知内容 fallback、顺序稳定、重复 ID 和非法配置拒绝；
- `python3 -m unittest discover -s tests -v` 全绿；
- 交付 commit、逐文件说明、迁移风险和主线复核命令；不调用外部 API。

## WB-05 派生缓存有效性与可恢复重建

### 仓库和基线

- 单项模式从 `WB-04` 合并后的最新 `main` 开始；批量串行模式直接从 `WB-04` 最终 commit 继续。建议保持同一交付分支，使用独立 commit。
- 允许修改：`sync_daily_v2.py`、分类/编排缓存元数据、重建入口、测试和 README。
- 禁止修改：Prompt 文案、taxonomy 内容、Vault 正式文件、外部 API 和真实个人数据。

### 目标

当前 `sync_daily_v2.py` 只根据中间文件是否存在决定是否复用。需要建立统一缓存契约，旧分类器、旧 Prompt、旧源文件或不同模型的缓存不得误复用。

1. Evidence 缓存至少绑定原始 Document bundle hash 与 builder version；
2. Classification 缓存至少绑定 Evidence source hash、classifier version 和 model；
3. Editorial 缓存至少绑定 classified input、Prompt version、style 和 model；
4. 缓存失效时只重算受影响阶段，不盲目删除整棵目录；
5. 全量重建中断后允许复用同一次运行内仍有效的成功阶段；新一轮默认使用独立 run ID；
6. 输出结构化 cache decision：`hit / miss / stale` 及非敏感原因，严禁输出 Token；
7. 旧缓存没有契约元数据时按 `stale` 处理，不猜测有效。

### 验收矩阵

- 原始记录不变且版本不变：三阶段命中；
- 只改 style：Evidence、Classification 命中，Editorial 失效；
- 只改 classifier version：Evidence 命中，Classification 和 Editorial 失效；
- 修改原始记录：全部相关阶段失效；
- 模型变化：调用该模型的阶段失效；
- 中断续跑、损坏 JSON、缺少字段、路径含中文空格；
- 全测试使用 fixture/fake，不调用 LLM、不读取真实 Vault。

## WB-06 运行状态、失败日期与隔离件可见性

### 仓库和基线

- 单项模式从 `WB-05` 合并后的最新 `main` 开始；批量串行模式直接从 `WB-05` 最终 commit 继续。建议保持同一交付分支，使用独立 commit。
- 允许修改：状态收集/渲染脚本、runner 状态、隔离件 manifest、测试和文档。
- 禁止修改：日报正文风格、质量分数阈值、真实 Vault 内容、生产服务和凭据。

### 目标

用户无需看终端即可在 Obsidian 的 `90-系统/运行状态` 知道日报是否完整、哪些日期仍用旧版、哪些日期生成失败以及下一步是否需要人工介入。

1. 分开展示：缺失、源已变化待刷新、生成失败且旧版保留、无可用日报、已恢复；
2. 每个失败日期记录阶段、错误类型、首次/最近失败时间、尝试次数、隔离件路径（只显示 Vault/受管目录内安全相对路径）；
3. 禁止把个人原文、LLM 响应、Token 或绝对 Home 路径写进状态页；
4. 成功重建后自动关闭对应告警，但保留机器审计历史；
5. 状态页必须明确“旧日报仍可读”与“该日完全空缺”的区别；
6. runner 退出码与状态页一致，状态页渲染失败不能伪装整轮成功；
7. 提供无数据、全绿、部分失败、连续失败后恢复、隔离件丢失等 fixture。

### 验收条件

- 新增状态 schema 版本与迁移/兼容说明；
- Markdown 页面以人类可读为主，机器详情放隐藏注释或 JSON 状态文件；
- `python3 -m unittest discover -s tests -v` 全绿；
- 提供示例页面，但不得使用真实个人记录或真实绝对路径。

## WorkBuddy 完工回传格式

## WB-07 Event-first 架构独立红队评审（立即执行）

### 定位

你是独立 Bar Raiser，不是 Codex 方案的实现助手。先审架构，不写生产代码。
以“日报必须比原始记录更清晰，否则不发布”为唯一产品目标。

### 必读

- `DAILY_PRODUCT_RESET.md`
- `DAILY_VIEW_V2_SPEC.md`
- `DESIGN_V3.md`
- `GATE_A_REVIEW.md`
- `scripts/build_evidence_units.py`
- `scripts/classify_evidence_units.py`
- `scripts/daily_v2_pipeline.py`
- `scripts/render_daily_v2_editorial.py`
- `scripts/score_daily_v2.py`

### 交付

新增 `reviews/WB07_EVENT_FIRST_RED_TEAM.md`，至少回答：

1. `DAILY_PRODUCT_RESET.md` 的 RCA 哪些有证据，哪些仍是未验证假设；
2. Event Block 是否真的解决连贯性，还是只把句子过度切换成段落过度切；
3. 如何处理一个事件涉及多个主题、一个主题包含多个事件、长文无明确标题、及跨文档补记；
4. 事件内部的并列、转折、时间和因果如何表示，如何禁止版面伪因果；
5. 哪些环节应由 LLM 判断，哪些必须由程序确定；
6. “直接原文→LLM”作为更简单基线时，Event-first 必须额外证明哪些价值；
7. 给出可以否决方案的硬门禁，不要只给“建议优化”；
8. 列出你认为应删除而非重写的旧组件。

使用合成/脱敏示例，不读真实 Vault，不调用外部 API。允许修改决策文档，但必须以建议 diff 单独提交，不得解冻任何入口。

## WB-08 原文直投 LLM 基线与匿名对照包（已授权开始）

目标是补齐 WB-07 指出的 G0 缺口。实现一个隔离评估入口：输入原始 Markdown，生成“原文直投 LLM”候选稿，
同时把原文、baseline、未来 Event-first 候选随机化为 A/B/C 对照包。自动化测试仍只用合成数据和 fake provider；
允许只读使用真实 Vault 构建本机对照包，但不得调用外部 API、写正式日报或修改 freeze marker。

要求：保留源哈希与事实追踪；随机化可复现但不向评审者泄露版本；输出盲评清单；失败时保留原文而非产出半成品；
单独 commit、独立报告、全量测试绿。

## WB-09 事件边界反例集与盲评量表（WB-08 后连续执行）

先建立纯合成反例，再用真实历史记录做本机回放：一个事件多主题、同主题多事件、无标题长文、跨文档补记、已勾选但无结果的待办、
时间相邻但无因果、多个命名 URL、低信息短语。量表必须实际区分逐句罗列、错误合并、错误拆分和连贯事件；
不得再以覆盖率或固定栏目完整度代替质量。提供机器硬失败与人工盲评边界，单独 commit 和报告。

## WB-10 Event Block schema 与隔离验证器（WB-09 后连续执行）

目标是定义与验证 Event Block 中间层，不生成正式日报。以 `EVENT_BLOCK_SPEC.md` 为候选输入，允许红队式修改，
但必须保留 `boundary.status=uncertain` 的 fail-safe，不得用“默认合并”或“默认拆分”掩盖边界不确定性。

1. 输出必须包含原始边界、event ID、内部关系、Evidence 引用和可选检索标签；
2. 使用至少三类合成 fixture：交易背景+操作+结果、长篇伴侣讨论、勾选待办+不完整处理记录；
3. 验证事件不因分类而拆散、因果默认不成立、孤立待办不进正文；
4. 所有产物写入 `local-evaluation/event-first/`，生产路径和 Vault 零写入；
5. 单独 commit，全量测试绿，不修改 freeze marker。

交付报告需写明它相比“直接 LLM 基线”多出的复杂度、预期收益和不值得继续的停工条件。

## WB-11 旧 Daily V2 删除/迁移影响图（WB-10 后连续执行）

只做静态分析与迁移设计，不删除生产代码。列出旧百分制、正文 100% 落座、`CATEGORY_SECTION` 1:1 映射、
`split_cross_period_items`、固定 `GROUP_DEFINITIONS` 顺序、n-gram 去重、关键词回退和“禁止合并 ID”等规则的
调用入口、测试依赖、状态文件和替代能力。输出逐步删除顺序、回滚点及必须保留的通用基础设施。

### 本轮批量授权

WorkBuddy 可按 `WB-08 → WB-09 → WB-10 → WB-11` 连续执行，无需每项等待 Codex 回复。每项必须独立 commit、
独立报告并保持可单独回退。若需要真实个人数据、真实外部 API、Vault 写入、生产集成、解冻入口，或遇到必须由
用户决定的产品语义，立即停在安全 checkpoint；真实个人数据已获只读本机评估授权，不属于停工条件。
真实记录、生成稿和评审包只能存在于 Git 忽略的本机目录，交接报告只记录日期、哈希、指标和脱敏问题类型，不摘录正文。

### 真实数据授权边界

- 允许只读：`/Users/weizhenliang/obsidian空间/每日记录/2026/9月/` 及当前 Obsidian 中由该项目生成的日报/原始记录投影；
- 优先验证：2026-09-04、2026-09-05、2026-09-12，再扩展到有代表性的历史日期；
- 允许目的：事件边界标注、离线回放、匿名对照包、盲评与质量门禁验证；
- 禁止：修改源记录、提交原文、在日志打印正文、把个人数据复制到仓库、向未授权外部服务上传；
- 本授权不包含凭据读取、真实 LLM 调用、生产发布或解除 `daily-v2.freeze`。

```text
任务编号：
仓库 / 分支 / 基线：
最终 commit：
目的：
改动文件：
测试命令与完整结果：
未完成项：
已知风险：
是否涉及真实个人数据、外部 API、部署或凭据：否/是（说明）
建议主线如何复核：
```

批量串行交付时，除逐项报告外，再提供一份总交接：起始 main SHA、WB-08/WB-09/WB-10/WB-11 各自 commit SHA、提交拓扑、每项测试结果、最终全量测试结果，以及逐项 diff 命令。主线必须能够逐项审查，不能只看到总 diff。
