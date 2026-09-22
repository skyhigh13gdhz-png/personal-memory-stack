# WorkBuddy 连续执行队列

> 目标：让 WorkBuddy 承担可独立实现、可自动验证、可回退的工程工作；Codex 主要负责架构门禁、反例复核、合并与上线决策。
>
> 总原则：每项独立 commit、独立报告、全量测试；不重写历史，不直接合并 `main`。除标记为 **主线门控** 的节点外，
> WorkBuddy 不必等待 Codex 回复，可以沿当前分支连续执行。

## A 队列：立即连续执行

### WB-08R～WB-11R：首轮返修

严格按 `WORKBUDDY_REVIEW_WB08_11.md` 修复。返修完成后不要停，继续 WB-12。

### WB-12：真实事件标注工作台

实现本机隔离的事件标注格式与 CLI：输入一天的原始 Markdown，输出候选 Event Boundary、Evidence 引用、
边界状态和争议项。标注者只能看原文，不能看 baseline/Event-first 候选，防止答案污染。

要求：

- 支持同日多文档、跨文档补记、一个事件多主题、同主题多事件；
- WorkBuddy 对 2026-09-04、09-05、09-12 生成第一版人工首标，正文只保存在 `local-evaluation/`；
- Git 只提交 schema、工具、合成 fixture 和哈希/计数，不提交真实正文或真实标注内容；
- 输出争议边界清单，供 Codex 独立复核，只有分歧项以后交用户裁决。

### WB-13：历史低级错误回归集

把用户已指出的问题沉淀为可复现的合成回归集：

1. 一件事被过度拆分；
2. 两件事被错误合并；
3. 栏目顺序制造伪因果；
4. 未完成待办被写成已完成；
5. 已完成待办标题与正文重复；
6. 两个 URL 被拼坏或失去资源名；
7. “网络问题”等不明所以内容进入正文；
8. 夜间睡眠与午间休息顺序错误；
9. 同一记录重复写入多次；
10. ASR 纠错后派生日报未失效；
11. 同日多文档只处理部分来源；
12. 摘要产生原文不存在的结果、动机或因果。

每类至少一个负例、一个合法近邻正例，避免修复时误杀正常内容。

### WB-14：盲评结果录入与 G3 判定器

实现机器可读的盲评结果 schema、CLI 和汇总器。它只能汇总人工填写的事件完整性、事实忠实度、无伪因果、
信息密度、独立可理解性、自然度和阅读成本，不能自行生成“质量分”。硬失败优先于维度比较。

要求：支持缺失评分、双评审分歧、原文不劣约束、Event-first 至少两个维度胜出、≥80% 不差、逐日否决原因，
并能输出 `continue_event_first | choose_direct_baseline | insufficient_evidence`。

### WB-15：隐私、日志与隔离边界审计

扫描 WB-08R～WB-14：真实正文是否可能进入 stdout/stderr、异常、manifest、fixture、Git、临时文件或错误路径。
增加秘密值脱敏、真实内容不出报告、输出根 symlink escape、权限模式和清理策略测试。只修评估链，不碰生产发布。

## B 队列：A 完成后继续，仍不接生产

### WB-16：智谱评估 Provider Adapter

为 direct baseline 和 Event-first 实验实现统一 provider contract。支持从环境变量读取 Base URL、model、key、timeout、
重试和 token 用量；测试只用本地 fake HTTP，不调用真实 API。必须区分 `provider_unavailable`、超时、限流、响应损坏，
失败候选不得进入盲评。

真实智谱调用属于 **主线门控**：代码可以先完成，实际发送个人数据由 Codex 根据既有授权与日期范围执行或明确放行。

### WB-17：Event-first 候选生成器

输入 `DaySourceBundle + style profile`，输出 Event Block document；LLM 只提出候选，程序负责完整验证。
禁止关键词分类决定版式，禁止自动把 `uncertain` 改为 `confirmed`，禁止无 Evidence 摘要。使用 fake/replay provider 完成测试。

### WB-18：隔离端到端评估编排器

串起：原始记录 → 日级聚合 → direct baseline → Event-first 候选 → Event 校验 → 匿名对照包 → 盲评结果汇总。
所有输出只写 `local-evaluation/`；没有通过 WB-14 判定时不得产生可发布 Markdown。

### WB-19：可复现性、成本与性能清单

记录 prompt/schema/model/style/source hash、输入输出 token、延迟、重试、调用次数与估算成本。相同 replay 输入应产生相同包；
不得把原文、API key 或完整模型响应写入普通日志。为未来 LLM 路由选择提供事实数据，不做自动选模。

## C 队列：与日报架构相对独立，可在 B 后继续

### WB-20：纠错传播链审计与测试工具

覆盖 `GPT → memory MCP → Hindsight → 原始记录投影 → 日报/长期对象派生失效`。重点验证“鸡蛋→新单”一类 ASR 修正：
原事实是否被替换/更正、旧派生物是否标 stale、是否保留更正审计、刷新后是否只出现正确版本。

默认只做只读审计和 fake 服务测试；任何真实 Hindsight 写操作属于主线门控。

### WB-21：图片附件 A07

承接原 WB-02：梳理聊天图片、MCP、Hindsight、Obsidian attachment 的标识、存储、去重、引用和迁移 contract；
用合成图片做端到端本机验证，确保交易截图能在 Obsidian 中显示且正文可追溯。不得上传真实图片或改生产服务。

### WB-22：Retain 幂等与异步 operation

承接原 WB-03：建立幂等键、超时后查证、重试不重复写入、operation 状态轮询和重复记录检测的 contract/测试工具。
先对 fake server 和只读日志验证，不写真实记忆库。

### WB-23：角色与 Speaker 身份审计

检查 GPT/MCP/Gateway/Hindsight/Obsidian 各层 `speaker=liangzai`、assistant、system 的映射，找出角色错置入口；
提交身份 contract、迁移影响图和合成回归测试，不批量改真实历史数据。

### WB-24：LLM 路由与额度可见性

生成一个不泄露凭据的配置审计 CLI/状态页：列出当前配置了哪些 provider/model、分别负责 retain/classify/daily/claim/refine，
配置来源、fallback 顺序、最近成功/失败和 token/请求量。先实现只读盘点，不自动切换生产模型。

### WB-25：原始同步与 Obsidian 刷新诊断

复现并定位“同步后必须重启 Obsidian 才看到内容”：区分文件是否落盘、mtime/原子 rename、Vault 路径、Obsidian 文件监听、
缓存和插件行为。交付诊断脚本与最小修复建议；不得为了刷新直接重启用户应用。

## D 队列：必须等待 Codex 明确放行

以下任务依赖真实盲评和架构结论，WorkBuddy 到达这里必须停在 checkpoint：

### WB-26：G3 三日真实盲评执行

使用 09-04、09-05、09-12 的独立标注、真实 direct baseline 和 Event-first 候选产生正式读数。

### WB-27：五日扩展与失败分类

三日全过后随机选择五个历史日期，验证记录风格变化、内容类型变化和不同长度。

### WB-28：新状态语义与 Obsidian 可见性

重新设计缺失、stale、生成失败、隔离、等待人工、已发布状态；旧 WB-06 不直接复活。

### WB-29：缓存、幂等与增量调度

在新 schema 稳定后重做缓存键、失效规则与无人值守增量运行；旧 WB-05/WB-01 不直接复活。

### WB-30：历史迁移与全量重建 dry-run

只生成迁移计划、差异预览和回滚包；用户/Codex 验收前不覆盖任何正式日报。

### WB-31：生产集成、部署与验收

包含解冻、调度器安装、服务器部署、真实 Vault 发布和全量重建。必须由 Codex 复核并明确放行。

## 连续执行与停工规则

1. WorkBuddy 当前可连续执行 `WB-08R～WB-25`；每项独立 commit，不等 Codex 中途回复。
2. 到达 WB-26 必须停下，提交总交接；WB-26～WB-31 是主线门控。
3. 任何真实 API 调用、真实 Hindsight 写入、Obsidian 正式文档写入、部署、解冻和历史数据迁移都不得自行执行。
4. 测试失败、个人数据可能泄漏、需要用户决定产品语义时，在当前任务安全 checkpoint 停止；普通工程问题自行解决。
5. 每五项生成一次 checkpoint 报告，包含提交拓扑、逐项 diff、测试计数、未决风险和下一批入口，避免因对话额度中断丢失进度。

