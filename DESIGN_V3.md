# Personal Memory V3 调研与可行设计

> 状态：架构评审稿，未授权自动化扩建  
> 日期：2026-09-20  
> 目标：建立可追溯、可重建、可渐进治理的个人记忆与知识系统，不批量生产低质量 Markdown。

## 1. 核心结论

V3 不以文件夹作为数据模型，不把“日/周/月报”和“长期对象”放进同一分类树。系统严格分成：

1. **证据**：原始记录与可引用的事实/事件；
2. **派生视图**：按时间或持续脉络组织的可重建读模型；
3. **人工知识**：用户确认、编辑和长期维护的笔记。

两个正交读取维度：

```text
时间视图（Temporal Views）
└─ 日回顾 / 周回顾 / 月回顾 / 年度回顾

持续脉络（Continuity Views）
└─ 人物 / 项目 / 健康与习惯 / 资产与策略 / 目标与承诺 / 系统与工具
```

两者平级，都从证据生成，不互相作为事实源。

## 2. 调研结论

### 2.1 事件与视图分离

Event Sourcing / CQRS 对本项目有用的不是分布式复杂度，而是：

- 保留表达“发生了什么”的证据；
- 日回顾、长期档案和索引都是可删除重建的物化视图。

Obsidian 内的系统生成文档不是权威数据库，更不允许自动反向 Retain。

### 2.2 双时间是必要的

个人记录会事后补录或纠错，每条事实至少区分：

```text
valid_time      事情在现实世界何时成立/发生
recorded_time   系统何时得知这件事
```

这对应现有 `timestamp/event_date` 和 `created_at/ingested_at`。补录 9 月 17 日的记录，不能把补录时间当成事件时间。

### 2.3 派生结果必须保留来源链

参考 W3C PROV，每个派生结论必须保存：

- source document / fact；
- builder、template version 和 model route；
- 生成时间；
- 输入/输出哈希；
- 结论类型：直接事实、聚合统计或模型推断。

### 2.4 记忆、反思与长期文档不同

研究中的 memory stream 保留经验，reflection 形成高层理解；后者不能冒充原始事实。Hindsight 中：

- Documents：原始证据；
- world / experience facts：提取事实；
- Observations：有支持证据的归并观察；
- Mental Models / Knowledge Pages：适合慢变、可审阅的主题摘要。

## 3. 当前部署实测

2026-09-20 只读检查当前服务器 OpenAPI 与数据：

| 能力 | 结果 | 设计含义 |
|---|---:|---|
| Documents | 已使用 | 继续作为原始证据边界 |
| Entities | 188 个 | 全部缺少可靠类型，禁止直接生成 Obsidian 档案 |
| Observation scopes | 3 个 | 可复用，但需审计质量 |
| Mental Models | 0 个 | API 存在，尚未验证个人场景 |
| Knowledge Base | 0 页 | 可导出 Markdown，不应立即批量建页 |
| MM delta/history/dry-run | API 存在 | 适合做少量可审阅试点 |

当前使用 `latest` 镜像。正式依赖 Knowledge Base 前必须锁定版本，避免 API 漂移。

## 4. 领域模型

### 4.1 Evidence：证据

```text
EvidenceDocument
  document_id, speaker_id, original_text
  valid_time, recorded_time
  source_type, source_hash, revision
```

原文可纠错，但必须经 CAS Patch 并保留修改痕迹。

### 4.2 Claim / Event：可引用事实与事件

```text
Claim
  claim_id
  kind                 event | state | preference | decision | commitment | metric
  subject_id?
  predicate, value, unit?
  valid_from, valid_to?, recorded_at
  epistemic_status     asserted | extracted | inferred | confirmed | disputed | retracted
  confidence
  evidence_refs[]      document_id + quote/span/hash
```

LLM 可提议 Claim，但不能无证据地改变高影响状态。

### 4.3 Subject：经治理的持续脉络主体

Subject 不等于任意 Hindsight Entity。

```text
Subject
  subject_id
  subject_type         person | pet | project | health_track | habit | asset | strategy | goal | system
  canonical_name, aliases[]
  lifecycle_status     candidate | active | archived | merged
  promotion_reason, created_at, confirmed_at?
```

候选主体只在以下情况晋升：用户明确要求；具有目标/承诺/状态/生命周期；或跨至少 3 个日期反复出现并有实际查询价值。“西瓜”、单次餐厅或随口概念不晋升。

### 4.4 Projection：派生视图

```text
ProjectionRun
  projection_id, projection_type
  schema_version, input_watermark, input_hash
  source_refs[], builder_version
  model_provider/model, generated_at, output_hash
  quality_status       draft | reviewed | accepted | rejected
```

视图可删除重建，不反向写入证据。

## 5. 两类派生视图

### 5.1 时间视图

架构名称用“时间视图”，Obsidian 界面可用“周期回顾”。

| 视图 | 问题 | 输入 | 禁止 |
|---|---|---|---|
| 日回顾 | 今天发生了什么 | 当日全量 Evidence/Claims | 把单日现象写成趋势 |
| 周回顾 | 本周频率、模式、推进与阻塞 | 本周全量 Evidence/Claims | 只拼接 7 篇日回顾 |
| 月回顾 | 趋势、转折与阶段目标 | 本月全量 Evidence/Claims | 只拼接周回顾 |

上层回顾可使用下层回顾导航，但最终结论必须回到证据核对。

### 5.2 持续脉络视图

每个 Subject 只有一份人类可读档案：

```markdown
# Subject
## 当前状态
## 已确认的关键事实
## 未决问题与下一步
## 里程碑
## 演进时间线
## 争议与不确定项
## 证据与来源
## 人工备注
```

“当前状态”是 Claim 快照，“演进时间线”是相关 Claim/Event 的投影。不再建立平级的“对象变更记录”目录。

## 6. Hindsight 复用边界

### 立即复用

- Documents：原始证据边界；
- Recall：日常语义查找；
- Observations：候选趋势/观察，保留 supporting facts；
- Reflect：探索性综合，不直写权威档案。

### 小规模试点后决定

- Mental Model delta refresh；
- Knowledge Page Markdown export；
- structured response schema；
- entity labels 与 subject scope tags。

### 明确不做

- 投影当前 188 个自由 entities；
- 把 Mental Model 当事实源；
- 让 Knowledge Page 反向 Retain；
- 在未锁定镜像版本前依赖新 API 做生产流程。

## 7. Obsidian 信息架构

```text
AI/AI外置记忆/
├── 00-证据/原始记录/
├── 10-时间视图/日/周/月/
├── 20-持续脉络/
│   ├── 人物/
│   ├── 项目/
│   ├── 健康与习惯/
│   ├── 资产与策略/
│   ├── 目标与承诺/
│   └── 系统与工具/
├── 30-人工知识/
└── 90-系统/模板/索引/生成清单/
```

`00/10/20/90` 的系统区块可重建、默认只读；`30-人工知识` 由用户所有，系统不覆盖。需要在持续脉络内人工编辑时，使用独立 human-owned block/file。

## 8. 生成约束

### 时间视图

- 输入为当期全量 Documents/Claims，不是 Recall Top-K；
- 统计由程序计算，LLM 只归类和整理文字；
- 非统计结论必须有 evidence refs；
- “没有记录”不等于“没有发生”；
- 空栏目隐藏，概览与分类不重复；
- 只有 material change 才链接持续脉络。

### 持续脉络

- 输入为与 Subject 明确关联的 Claims/Evidence；
- 单次现象不改写慢变特征；
- 偏好、人格和健康趋势必须标记 inferred 并要求多份证据；
- 冲突事实并存，禁止最新一条静默覆盖；
- 删除/纠错证据后必须标记相关视图 stale。

## 9. 质量门槛

| 指标 | 目标 |
|---|---:|
| 期间原文覆盖 | 100% Documents 进入输入清单 |
| 证据可追溯 | 100% 非统计结论可定位原文 |
| 无依据陈述 | < 1% |
| 关键事实召回 | golden set 上 ≥ 95% |
| 无变化重建 | 0 次 LLM 调用，输出字节不变 |
| 重复信息 | 不出现概览和分类整段重复 |
| 阅读价值 | 连续 14 天实用后评审 |

建立 7–14 天 golden set，人工标注关键事实、禁止推断项、隐私项和真正有价值的持续脉络。

## 10. 分阶段决策门

### Gate A：信息模型评审

> 工程状态：已完成 09-16–09-18 真实样本建模、隐私隔离和黄金集校验工具；详见 [GATE_A_REVIEW.md](GATE_A_REVIEW.md)。产品体验仍需 Gate B/C 验证。

- 用 09-16、09-17、09-18 原文制作手工参考样本；
- 评审时间视图与持续脉络的阅读价值；
- 确认 Subject 类型和晋升规则；
- 通过前不批量生成文件。

### Gate B：小样本投影器

- `daily-v1` 降级为技术原型；
- 实现逐条 evidence refs、隐藏空栏目和去重的 temporal-view v1；
- 只创建 2–3 个人工确认 Subject；
- 与 Mental Model dry-run 做 A/B，不写生产 Knowledge Base。

### Gate C：连续使用

- 连续 14 天手动触发；
- 记录阅读、纠错、忽略和重新查询成本；
- 用户确认“真的会看”且质量达标后才定时。

### Gate D：扩展

- 先周回顾，后月回顾；
- 先手动晋升 Subject，后候选推荐；
- 先锁定 Hindsight 版本并验收备份恢复，后试点 Knowledge Pages。

## 11. 待决策

1. “周期回顾”是否是最终界面名称；
2. 首批 2–3 个 Subject 选什么；
3. 健康类 Claim 是否必须人工确认后更新当前状态；
4. 系统生成的回顾保留多久，是否允许人工编辑。

## 12. 当前停工线

Gate A 通过前：

- 不实现周/月回顾自动化；
- 不投影 188 个 entities；
- 不批量创建 Mental Models / Knowledge Pages；
- 不安装日回顾定时任务；
- 不把 `daily-v1` 当最终产品模板。

## 13. 主要调研来源

- [Martin Fowler: Event Sourcing](https://martinfowler.com/eaaDev/EventSourcing.html)
- [Martin Fowler: Bitemporal History](https://martinfowler.com/articles/bitemporal-history.html)
- [Microsoft Azure Architecture Center: CQRS Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs)
- [W3C PROV Model Primer](https://www.w3.org/TR/prov-primer/)
- [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442)
- [Hindsight Best Practices](https://github.com/vectorize-io/hindsight/blob/main/skills/hindsight-docs/references/best-practices.md)
- [Hindsight Mental Models API](https://github.com/vectorize-io/hindsight/blob/main/skills/hindsight-docs/references/developer/api/mental-models.md)
- [Hindsight Memory Banks and Entity Labels](https://github.com/vectorize-io/hindsight/blob/main/skills/hindsight-docs/references/developer/api/memory-banks.md)
- [Obsidian Properties](https://obsidian.md/help/properties)
- [Obsidian Backlinks](https://obsidian.md/help/plugins/backlinks)
