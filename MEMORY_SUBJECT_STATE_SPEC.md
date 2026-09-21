# 长期记忆 Subject 与状态演进规范

> 状态：V1 实施规范；替代“把持续脉络当成对象类型”的旧表达
>
> 原则：Subject 决定跟踪什么，State 表达现在是什么情况，Change Event 记录如何走到现在。

## 1. 三个正交层

```text
Evidence                    真实发生过什么
Periodic Review             一个时间窗口发生了什么
Memory Subject + State      一个对象或主题现在是什么情况
```

“持续脉络”不是一级对象类型，而是每个 Memory Subject 的状态和变化历史。

## 2. Subject 类型

```text
person | pet | project | long_term_topic | health_track | habit | asset | strategy | system | goal
```

`health_track`、`habit` 是长期主题的机器细分类型。目标、承诺、决策、未决问题、下一步通常是 Subject 内部字段，不默认成为一级对象；只有目标本身具有独立生命周期时，才考虑晋升为 `goal` Subject。

## 3. 状态陈述类型

| 类型 | 定义 | 最低证据要求 |
|---|---|---|
| `direct_fact` | 用户或可靠来源明确陈述 | 1 条逐字证据 Claim |
| `derived_state` | 多条事件共同支持的状态抽象 | 至少 2 条 Claim、至少 2 个日期 |
| `hypothesis` | 尚未充分确认的解释或可能状态 | 至少 1 条证据，必须标不确定性 |

状态陈述必须记录 `state_key`、`valid_from/valid_to`、证据 Claim、置信度、审核策略以及被替代关系。

## 4. 状态生命周期

```text
current → superseded
current → resolved
resolved → reopened
```

- 历史 Event 不覆盖、不删除；
- 同一 `state_key` 同时最多存在一个 current 状态；
- `superseded/resolved` 必须填写 `valid_to`；
- 新状态通过 `supersedes[]` 指向旧状态；
- 源证据纠正或删除后，相关状态标记 stale 并重算。

## 5. 自动维护策略

| Subject/状态 | 默认策略 |
|---|---|
| 项目、系统的高置信 direct fact | 可自动维护 |
| 项目、系统的跨日高置信 derived state | 可自动维护并保留审计 |
| hypothesis | 进入未确认项，不覆盖 Current State |
| 健康、人物、资产、策略的派生状态 | `review_required` |
| 与现有 Current State 冲突 | `review_required` |
| 高影响或不可逆决策 | `review_required` |

人工确认是异常和高风险处理机制，不是每次更新的默认工作流。

## 6. Obsidian 人类视图

```text
20-长期记忆/
├── 项目/
├── 长期主题/
├── 人物/
├── 资产与策略/
└── 系统与工具/
```

Project 页面使用：当前阶段、当前状态、当前推进、当前问题、已确定事项、未确认事项、下一步、关键里程碑、状态历史。

长期主题（例如睡眠）使用：当前状态、关注指标、近期模式、最近记录、阶段观察，不套项目任务模板。

证据 ID、置信度和生成信息放入 HTML 注释或独立审计产物，不挤占人类正文。
