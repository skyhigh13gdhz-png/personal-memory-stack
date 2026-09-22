# Event Block V1 数据契约

> 状态：架构候选，只允许在隔离评估区使用。Daily V2 仍冻结。

## 1. 为什么需要 Event Block

Evidence Unit 回答“原文哪里支持这句话”，Event Block 回答“这是什么完整的事”。
两者不得共用粒度。句子可以是证据，却不应因此在日报中自动变成一个条目。

Event Block 也不等于 Markdown 段落。一个事件可跨越多个段落或标题，一个段落也可明确记录多个无关事件。
原始结构只是事件边界的高权重信号，不是最终答案。

## 2. 四层强制分离

### 2.1 Source Layer

保留 Document 原文、Markdown 结构、字符位置和日期。任何派生产物都不是反向写入源。

### 2.2 Evidence Layer

句子级或短语级证据，可用于精确引用。Evidence 可被事件摘要整体覆盖，
不要求每个 Evidence 在人类视图中单独出现。

### 2.3 Event Layer

完整叙事单位，保留背景、行动、结果、感受和未解问题之间的关系。
同一事件在日报中只出现一次。

### 2.4 Index Layer

类别、Subject、人物、项目、交易标的、餐次等都是多值索引。它们用于 Recall、周期统计和长期对象候选，
默认不生成日报栏目，更不能把一个事件复制到多个类别下。

## 3. Event Block schema

```json
{
  "event_id": "event-<stable hash>",
  "date": "YYYY-MM-DD",
  "title": "可独立理解的事件名",
  "summary": "保留原意的连贯摘要",
  "details": [
    {
      "role": "context|trigger|action|result|feeling|reflection|open_question",
      "text": "事件内部要点",
      "evidence_unit_ids": ["unit-..."]
    }
  ],
  "resources": [{"label": "工单", "url": "https://...", "evidence_unit_ids": ["unit-..."]}],
  "source_spans": [{"document_id": "...", "start": 0, "end": 100}],
  "source_order": 3,
  "boundary": {"status": "confirmed|proposed|uncertain", "confidence": 0.0, "reason": "..."},
  "time": {"start": null, "end": null, "precision": "unknown"},
  "relations": [
    {
      "type": "temporal|parallel|contrast|elaboration|explicit_cause|reflection_on",
      "target_event_id": "event-...",
      "evidence_unit_ids": ["unit-..."]
    }
  ],
  "tags": ["trading", "relationship"],
  "subject_candidates": [],
  "publication": {"decision": "include|omit|needs_context", "reason": "..."}
}
```

`summary` 必须在不看其他条目时仍能理解。`details` 是事件内部的逻辑槽位，不是外部分类。
简单事件可以没有 details，直接展示 summary。

## 4. 事件边界决策

应合并的信号：同一编号块；同一明确标题下的连续叙事；后文使用“这件事/后来/但/因此”回指前文；
同一对象、地点和短时间内的连续行动；背景、处理、结果与感受共同构成闭环。

应拆分的信号：时间或地点明显跳转；主体变化且无指代连续；两件事分别有完整的行动/结果；
只因为属于同一类别而被放在一起。

边界不确定时，不自动选择“合并”或“拆分”。标为 `uncertain` 并保留完整源跨度，候选稿可展示原文或轻编辑版本，
但不得把猜测的事件边界发布成正式日报。错误合并会制造伪关系，错误拆分会破坏语义，两者都不是安全默认值。

## 5. 关系和因果约束

`parallel` 是事件间默认关系。`explicit_cause` 必须引用原文中明示因果表达的 Evidence；
没有证据时不允许由顺序、栏目、语义相似或模型常识推导因果。

人类视图不展示会暗示因果的通用容器名，例如“执行→结果”。如需展示多个并列方面，
在同一 Event Card 内使用“市场背景”“个人操作”“账户状态”等无因果角色名。

## 6. 发布决策

- `include`：事件能独立理解，且包含有价值的发生事实、感受、思考或结果。
- `omit`：结构标记、重复标题、未完成待办或只有名称的已勾选待办。
- `needs_context`：似乎有事件，但缺少对象、处理或结果，例如孤立的“TikTok 网络问题”。

`needs_context` 进入待补充/审计视图，不进入正式日报。系统不得用常识自动补齐。

## 7. LLM 与程序边界

LLM 负责：模糊事件边界、指代关系、连贯摘要、事件内部角色和低信息判断。

程序负责：原始字节与位置、Markdown 结构候选、待办状态、URL 完整性、Evidence 引用有效性、
事件必填字段、未知 ID、重复事件、显式因果证据、隔离和原子发布。

程序不写自然语言摘要，不依靠用户专属关键词决定事件结构；LLM 不能改写原始证据、伪造关系或决定是否绕过硬门禁。

## 8. 人类视图约束

1. 默认按原始叙事顺序或明确事件时间排列 Event Card；
2. 同一事件只显示一次，多标签不复制正文；
3. 简单事件一段话表达，复杂事件最多使用少量有语义的内部子项；
4. 没有信息的栏目不生成，不为对称或完整而填充废话；
5. 事件分类是可选导航，不是叙事层级；
6. 如果原始记录已经达到更高的连贯度，可原样引用或只做轻编辑。

## 9. 硬门禁

本 schema 通过门禁，不等于 Event-first 路线胜出。必须先有真实的“原文直接交给 LLM”基线，
再做匿名盲评；若额外中间层没有可测净收益，应删除而不是继续加规则。

以下任一情况使整日稿不合格：

- 一个源事件的关键背景、行动或结果被拆散到无关 Event Card；
- 页面栏目或条目顺序暗示原文不存在的因果；
- `explicit_cause` 没有明示原文证据；
- 未完成待办被写成已发生，或孤立已勾选待办被写成有结果的事件；
- 任一正文条目离开原文后不明所以；
- 多个裸 URL 被拼接在正文或链接失去资源名；
- 为了形式覆盖显示结构词、过渡句或无信息量短语；
- 生成稿在人工阅读上比原始记录更难理解。
