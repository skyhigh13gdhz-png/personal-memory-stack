# WorkBuddy WB-08～WB-11 主线复核

> 复核日期：2026-09-22  
> 被审分支：`feature/workbuddy-eventfirst-wb08-11`  
> 被审范围：`12f04cf..8bc842b`  
> 结论：**不整体合并；WB-08/WB-09/WB-10 request changes，WB-11 仅接受为静态清单。**

## 1. 验证事实

- `/usr/bin/python3 -m unittest discover -s tests -v`：374 tests，OK。
- Python 3.13.12 同一命令：374 tests，OK。
- `git diff --check 12f04cf..HEAD`：通过。
- 工作区干净，未发现真实个人正文、凭据或 `local-evaluation` 产物进入 Git。
- 测试全绿只证明现有断言成立；下面两个最小反例证明核心产品约束尚未被断言覆盖。

## 2. 阻断问题

### P0：WB-08 尚未建立真正的整日直投 LLM 基线

`scripts/eval_direct_llm_baseline.py:608-614` 的 CLI 永远实例化 `RefusingProvider`，随后在
`render_baseline():306-339` 将失败降级为原文；这会生成带 baseline 身份但内容等于原文的候选。
盲评包虽然隐藏了 `fallback`，却也把“基线未生成”伪装成一个可评分版本。

此外，`load_source_documents():173-188` 与主循环 `:611-614` 按文件分别生成 raw/baseline。
最小复现中，同一天两个文档得到 4 个候选 `A/B/C/D`，而产品目标是把当天全部原始材料一次交给
同一 provider，形成一份 raw、一份 direct baseline、一份 Event-first 候选。规范
`EVAL_BASELINE_SPEC.md:11-14` 宣称 G0 已补齐，与实际行为不一致。

要求：

1. 新增 `DaySourceBundle`（或等价聚合），保留每个文档的 ID、哈希与明确分隔，一日只调用一次 provider；
2. CLI 必须支持显式 provider adapter 或显式 replay 输入；默认拒绝可以保留，但 fallback **不得进入盲评包**；
3. provider 失败时整日标为 `baseline_unavailable` 并非零退出，不能把原文冒充 baseline；
4. 测试覆盖同日多文档、失败不可评分、恰好三种候选以及真实基线只调用一次。

### P0：WB-10 允许无证据摘要和悬空资源通过

`scripts/event_block_schema.py:133-188` 只要求摘要非空，却没有要求摘要引用 Evidence；资源只要求
`evidence_unit_ids` 非空，不验证 ID 是否存在。最小复现中，源 Evidence 仅为“今天吃了饭”，Event Block
摘要写成“今天交易盈利一百万元”，资源引用 `missing`，`validate_document()` 仍返回 `valid=True`。

要求：

1. summary/title 的事实性文本必须有事件级 Evidence 引用，或明确由已验证 details 派生；
2. resource、relation、source span 的所有引用必须存在且属于该事件；
3. `source_spans` 不能只验“列表非空”，需校验 document ID、非负范围、`start < end` 和不越界；
4. 投影前必须强制执行 document validation，禁止调用方绕过验证直接 `project_body()`；
5. 增加无依据摘要、未知资源引用、未知关系引用、非法 span 与直接投影无效事件的回归测试。

### P1：WB-09 的真实回放结论超出其可测能力

`scripts/event_boundary_gates.py:721-738` 只有在候选文本近似逐字包含原句时才能建立引用；因此大幅改写时
`merged_item_count` 不能判断是否真的合并事件。可是函数文档 `:684-688` 和
`EVENT_BOUNDARY_SCORECARD.md:108` 声称该结构比值在改写后仍可靠，前后矛盾。

`MIN_ADJUDICABLE_RATIO=0.5`（`:62-65`）也没有经验依据。六天真实回放全部 not_adjudicable，说明它目前
只能报告“自动对齐失败”，不能评价旧日报质量，也不能作为 G3 的胜负数据。

要求：

1. 将 gold-free replay 明确降级为诊断工具，删除“改写后仍可靠”的表述；
2. `merged_item_count` 只在逐字对齐覆盖达到条件时展示，否则返回 `null`；
3. 0.5 改成显式参数/报告元数据，不能作为产品质量门禁；
4. G3 只接受人工事件标注后的 pair confusion 与真实盲评读数。

## 3. 逐项结论

- **WB-08 `45f3f87`：request changes。** 安全骨架和匿名包可复用，但 G0 未闭合。
- **WB-09 `bbba869`：request changes。** 合成 pair-confusion 方向正确；真实回放的能力声明和阈值需修正。
- **WB-10 `c8b1ac1`：request changes。** 边界、顺序、显式因果方向正确，但事实追踪存在 P0 漏洞。
- **WB-11 `8bc842b`：accept as inventory only。** 可作为静态依赖清单；在替代能力通过 G3 前，不接受为删除作业依据。

## 4. 对交接单六个问题的回答

1. 逐项结论见上；不得整体合并。
2. **暂不能进入正式三方盲评。** 先完成 WB-08R/WB-09R/WB-10R，再用真实 provider 生成真正的整日 baseline。
3. 人工标注采用“独立草标 + 争议裁决”：WorkBuddy 只看原文制作首标，Codex 独立复核；仅把分歧边界交用户裁决。候选稿对标注者保持隐藏。
4. 0.5 不确认。当前只作可配置的诊断阈值；有人工标注样本后再校准，且不得转成日报质量分数。
5. WB-11 的四波次仅接受为候选顺序；等替代链通过 G3 和回滚演练后，才可成为删除执行依据。
6. 不合并现有四提交。保留原 SHA，追加独立 `WB-08R → WB-09R → WB-10R → WB-11R` 修复提交，不重写历史。

## 5. 修改准则

- **目的**：确保评估工具真正比较整日日报，Event Block 中所有可见事实均可追溯。
- **改动点**：日级聚合、baseline unavailable 状态、Evidence 完整校验、gold-free replay 能力降级。
- **预期影响**：测试数量可能继续增加，但核心是产生可信读数，避免“工具全绿、产品仍错误”。
- **潜在风险**：严格校验会使更多候选进入隔离区；这是设计目标，不允许用 fallback 或放宽门禁掩盖。

