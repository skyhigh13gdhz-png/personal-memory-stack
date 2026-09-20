# Gate A 信息模型评审

> 日期：2026-09-20
>
> 状态：工程验证通过，等待真实使用评审
>
> 数据边界：真实 golden set 仅保存在 Git 忽略的 `local-evaluation/`，不提交个人记录。

## 1. 样本与方法

人工核对 2026-09-16、09-17、09-18 的：

1. 手写 Obsidian 记录；
2. Gateway Documents 生成的原始记录；
3. 现有 `daily-v1` 输出；
4. 每条 Claim 的逐字证据引用和禁止推断项。

真实样本当前包含 3 份 Documents、12 条人工确认 Claims、4 条禁止推断、3 个 Subject 候选。

## 2. 现有 daily-v1 评估

| 维度 | 分数 | 结论 |
|---|---:|---|
| 事实覆盖 | 8/10 | 单日明确事实基本保留 |
| 可追溯性 | 4/10 | 只列 Document ID，结论与原文没有逐条映射 |
| 阅读价值 | 5/10 | “事实概览”与后续分类大量重复 |
| 信息密度 | 5/10 | 空栏目统一输出“无明确记录”，形成视觉噪声 |
| 时间语义 | 7/10 | 已按 event date 归档，但还未表达时间精度与不确定性 |
| 推断边界 | 8/10 | Prompt 有明确禁止推断，但没有事后可验证的 forbidden set |

**总评：6.2/10。** 它是合格的技术原型，不是可长期使用的日回顾成品。

## 3. Gate A 决策

### 3.1 时间视图合同

- 日回顾必须读入当日全量 Documents，禁止 Recall Top-K 代替。
- 页面首部只放 3–5 条“当日脉络”，不再复制所有分类事实。
- 无数据栏目直接隐藏，不输出“无明确记录”。
- 每条非统计结论必须有 Claim ID 和 evidence ref。
- 推断与原文事实分区，缺少支持证据的趋势结论不得输出。

### 3.2 Subject 首批候选

| Subject | 类型 | 决策 | 原因 |
|---|---|---|---|
| AI 外置记忆 | project | 进入 Gate B | 跨日推进、有交付与明确问题 |
| 睡眠与精力 | health_track | 进入 Gate B，仅陈述性 | 连续三日有记录，但禁止自动医疗归因 |
| 加密交易节奏 | strategy | 进入 Gate B，高影响 | 有仓位、损益、情绪和决策；状态更新需人工确认 |

食物、餐厅、西瓜、FOMC、ETH/CRV/PEPE 等仍只是 Claim 内容或标签，不自动晋升为 Subject。

## 4. Gate B 最小交付

1. `daily-v2-preview`：隐藏空栏目、消除重复概览、逐条证据引用。
2. 确定性 evaluator：检查 Document 覆盖、引用原文、重复、禁止推断和无变化重建。
3. 只为上述 3 个 Subject 生成本地预览，不写入 Hindsight Knowledge Base。
4. 用真实 golden set 做回归，不通过不同步 Obsidian。

## 5. Gate B 已启动的本地预览

`scripts/render_daily_v2_preview.py` 已实现零 LLM 的确定性阅读预览：

- 输入必须先通过 golden-v1 校验；
- 空栏目不渲染；
- 不再设置重复的“今日事实概览”；
- 每条 Claim 通过 Markdown 脚注对应逐字原文和 Document ID；
- 只写入 Git 忽略的本地评审目录，暂不同步 Vault。

## 6. 当前结论

Gate A 的信息模型和机器验证方法已经可执行；但“用户是否真的愿意读”仍必须通过 Gate B 本地预览和 Gate C 连续使用验证，不能由开发者自我宣布。
