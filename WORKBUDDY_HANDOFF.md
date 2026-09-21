# WorkBuddy 任务交接单

> 用途：把边界清楚、可独立验收的工程任务交给另一名 Coding Agent。产品语义、个人数据判断和最终上线仍由主线统一评审。

## 协作规则

1. 每次只领取一个任务，使用独立 worktree 或独立分支，禁止直接改稳定工作目录。
2. 开工前记录仓库、基线 commit 和 `git status --short`；若基线不一致，先停止并报告。
3. 不把任何 Token、OAuth 凭据、个人原始记录、Vault 内容、服务器 `.env` 或生产日志提交到 Git。
4. 产品文件、脚本、服务名和用户界面中不得加入 `workbuddy`、`codex` 等工具品牌。
5. 默认只提交代码、测试和文档，不部署生产、不修改真实 Vault、不调用外部 LLM、不上传个人数据。
6. 交付必须包含：改动目的、文件列表、测试结果、已知风险、commit SHA；不能只说“已完成”。
7. 不顺手重构任务范围外的代码；发现架构问题记录为建议，不自行扩大范围。

## WB-01 本机日常增量任务（优先外包）

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

## WorkBuddy 完工回传格式

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
