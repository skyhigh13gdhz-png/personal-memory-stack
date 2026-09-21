# 身份与记忆归属规范

> 状态：V1 语义冻结；实现排在生产闭环之后、Claim → State 之前。
>
> 目标：避免把“谁正在聊天、谁记录、记录说的是谁、谁参与了事件、事实是否共享”混成同一概念。

## 1. 必须分离的字段

| 字段 | 含义 | 示例 |
|---|---|---|
| `current_speaker_id` | 当前会话中正在与 AI 对话的人，只属于会话上下文 | `monica` |
| `speaker_id` | 原始记录的讲述者或提交者 | `liangzai` |
| `subject_ids` | 该事实主要描述的人、宠物、项目或主题 | `pet:xiaohei` |
| `participants` | 事件参与者及其角色 | `liangzai: actor`、`monica: co_actor` |
| `scope` | 事实可如何面向相关用户表达 | `individual`、`household`、`shared`、`project` |

`current_speaker_id` 只能由当前 Project 明示、当前会话本人声明、系统默认值依次确定。历史记忆、语言习惯、关系称谓和内容特征都不能改变它。

## 2. 表达规则

1. 只有事实中的个人主体或行为者等于 `current_speaker_id`，才能将其改写为“你”。
2. 主体不是当前对话者时，保留稳定名字或明确关系称谓，不得偷换成“你”。
3. `household/shared` 只表示事实可以共享表达，不表示其中所有个人行为都属于当前对话者。
4. 家庭、宠物共同事实可表达为“你们家”；个人动作仍必须保留 `participants` 中的 actor。
5. 主体或行为者不确定时使用“有一条……记录”等中性表达，并标记 `attribution_pending`，不得猜测。

## 3. 必须通过的回归样例

| Current Speaker | 原事实 | 正确表达 | 禁止表达 |
|---|---|---|---|
| Monica | liangzai 和老婆一起给三只猫刷牙 | liangzai 和你一起给三只猫刷牙 / 你们一起给三只猫刷牙（参与者明确时） | 你和老婆给猫刷牙 |
| Monica | liangzai 做了三组俯卧撑 | liangzai 做了三组俯卧撑 | 你做了三组俯卧撑 |
| Monica | 家里有三只猫 | 你们家有三只猫 | Monica 养了三只猫（未确认所有权时） |
| 未确认 | 今天有人给猫刷牙 | 今天有一条给猫刷牙的记录 | 你今天给猫刷牙 |

## 4. 实施边界

- Gateway 负责返回结构化归属字段和稳定实体 ID；
- Evidence / Claim 层继承并可细化主体与参与者，但不得无证据改写；
- 客户端负责根据 `current_speaker_id` 做称谓渲染；
- Obsidian 人类视图默认隐藏机器 ID，但审计层必须保留归属来源；
- 旧数据没有可靠主体时不得批量猜测，只能保持中性或进入待确认队列。
