# WB-07 Event-first 架构独立红队评审

> 评审身份：独立 Bar Raiser。不是提案方的实现助手；本项**不写生产代码**。
>
> 唯一产品目标：**日报必须比原始记录更清晰，否则不发布。**
>
> 评审日期：2026-09-22
> 基线：`main` @ `be1c3db`（本评审在独立分支 `review/event-first-red-team`、独立 worktree 上进行）

---

## 0. 评审方法与边界

**做了**：

- 通读 `DAILY_PRODUCT_RESET.md`、`DAILY_VIEW_V2_SPEC.md`、`DESIGN_V3.md`、`GATE_A_REVIEW.md`、`GATE_B_RESULTS_2026-09-20.md`；
- 逐行审读 `build_evidence_units.py`（119 行）、`classify_evidence_units.py`（515 行）、`daily_v2_pipeline.py`（640 行）、`render_daily_v2_editorial.py`（314 行）、`score_daily_v2.py`（137 行）；
- 用**纯合成、脱敏**夹具实际运行 `score_daily_v2.score()` 与 `render_daily_v2_editorial.render()`，把"评分器能否识别事件化重写"从断言变成**可复现实验**（§1.2、§11）。

**没做**（硬边界）：未读真实 Vault、未读个人记录、未调用任何 LLM / 外部 API、未修改 `config/daily-v2.freeze`、未解冻任何发布入口、**未修改任何决策文档**（§10 的 diff 均为内嵌提案，未 apply）。

**为什么"不写生产代码"很关键**：WB-07 的产物是**判断**，不是实现。如果评审同时提交实现，就失去了独立立场——下面每一条否决理由都指向"现有门禁会主动改造新架构"，而不是"新架构写得不够好"。

---

## 1. 结论摘要（先给可否决结论）

**方向支持，验收不支持。** `DAILY_PRODUCT_RESET.md` 对失败机制的判断基本正确，但**当前证据不足以支持 Event-first 进入 WB-08 的原型验收**，理由是可复现的三条：

### 1.1 对照基线不存在，方案既不可证伪也不可证明

`DAILY_VIEW_V2_SPEC.md:156`（§6.18）与 `:160`（§7.1）明确要求"管道版必须与**当天原始材料直接交给 LLM** 的基线版定期同日盲评；若不能稳定胜出，不得以'自动化'为由上线"。

但全仓库**没有任何"直接原文→LLM"基线的实现**。`classify_evidence_units.py:409-412` 的 `baseline` 子命令是"全部保留为未分类原文"（README:238 自述为"零 LLM 完整性基线"），语义与 §6.18 要求的基线**完全不同**。

> **结论**：产品规范里的关键门禁**从未被执行过**（因为执行不了）。在基线补上之前，任何"Event-first 更好"的结论都缺少对照物。

### 1.2 现有机器门禁在结构上无法区分"逐句罗列"与"事件化重写"

合成复现实测（4 个句子级单元，纯合成内容，§11 附命令）：

| 变体 | score | passed | 触发 |
|---|---:|---|---|
| **零编辑、逐句原样罗列**（每句一条） | **100** | ✅ | — |
| 同段合并（2 句合 1 条，全部单元仍被引用） | 100 | ✅ | — |
| 跨段合并（同项目"下午 + 晚上"合成 1 条） | 100 | ❌ | 硬失败 `mixes distinct event periods` |
| 跨段合并 + 手工改标 `period="span"` | 100 | ✅ | — |
| 删 1 句低信息句（不再引用该单元） | 91 | ❌ | 硬失败 `daily units without editorial destination` |
| 删 2 句 | 83 | ❌ | 硬失败 + 跌破 85 |

注意 `GATE_B_RESULTS_2026-09-20.md:126` 记载**人工黄金样例 = 100/100**。上表第一行说明：**一份零编辑的句子罗列同样得 100/100**。也就是说——

> **评分器的 100 分不含任何"事件连贯性 / 阅读价值"信息。** 它给罗列稿和给它自己认定的黄金样例打同一个分。

原因在权重：`score_daily_v2.py:80-97`，`evidence_integrity = round(35 × 引用单元数 / 可见单元数)` 是**最大单一维度（35%）**，只数"引用了多少句"；`readability` 满分 10 分且只惩罚 6 个泛化标签词。**五个维度里没有任何一项检查事件完整性、事实忠实度、伪因果或信息价值。** 这与 RCA 第 4 条"垃圾稿也能得 100 分"完全吻合，且现在是**已复现事实**，不再是假设。

### 1.3 现有门禁会主动阻止事件化与编辑判断

- **阻止合并**：`render_daily_v2_editorial.py:178-180`，一个条目若命中 ≥2 个时间词（`detect_periods` 正则）而 `period` 不是 `span`，直接硬失败"split into separate items"。实测"下午联调接口，晚上补完文档"——一个自然的单一项目推进事件——**被系统判为违规**。是否允许合并，由**时间词正则**裁定，而不是由事件语义裁定。
- **阻止省略**：`render_daily_v2_editorial.py:204-206`，任何 `visibility ∈ {daily, both}` 的单元没有"编辑落座"就是硬失败。实测删掉 1 句"早上喝了一杯温水"→ 硬失败。这与 `DAILY_PRODUCT_RESET.md` §1"不得为覆盖率展示废话"、§6"孤立的无对象短语不进入正文"、§5"'不总结'是合法且必要的产品结果"**直接冲突**。
- **把合并拆回去**：`daily_v2_pipeline.py:245-275` `split_cross_period_items()` 会把模型已合并的跨时段条目**重新拆成逐单元条目**，`text` 取 `unit.summary`。即：LLM 若做出正确的"事件化""合并"，程序会把它拆回句子。

> **如果只换中间表示而不换门禁，Event-first 的产出会被现有 `validate()` + `split_cross_period_items()` 改造成"段落级逐句罗列"**——换汤不换药，且更难发现。

### 1.4 立场

**有条件支持 Event-first**，条件见 §8（六道可否决硬门禁）。**G0 未满足前，不得宣布 WB-08 原型"通过"**：可以定义 schema、可以做隔离区原型（WB-08 自身目标是"定义与验证中间层"，不生成正式日报），但**不得**以现有评分器或现有 `validate()` 作为"通过"依据。

---

## 2. Q1 — RCA 哪些有证据，哪些仍是未验证假设

逐条对 `DAILY_PRODUCT_RESET.md` §2 的 5 条 RCA：

| # | RCA 主张 | 证据 | 判定 |
|---|---|---|---|
| 1 | 句级 Evidence Unit 被同时当成审计/分类/阅读单位 | `build_evidence_units.py:23` `BUILDER_VERSION="sentence-split-v3"`；`:26` 在**每个** `。！？` 处切分；`:24-25` 注释自陈"要求空格会合并同一段落里不相关的事实"；`classify_evidence_units.py:144-146` 提示词**禁止模型合并 ID**（"必须为输入中的每个 unit_id 返回且只返回一项…不得遗漏、增加或合并 ID"）；`render_daily_v2_editorial.py:30-41` `CATEGORY_SECTION` 把 category 1:1 映射到 section | **已证实**（代码级） |
| 2 | 固定栏目顺序被读成因果 | `render_daily_v2_editorial.py:50-51` `trading_finance = [(execution,交易执行),(result_risk,结果与风险),(reflection,复盘与纪律)]`；`:241` 组按 `GROUP_DEFINITIONS` 固定顺序输出；`:248-251` 组内条目按 `PERIOD_ORDER` 排序；**Daily V2 正文表示中无任何关系字段**（`relation`/`causal`/`cause` 在 `scripts/` 零命中，仅有栏目名 `relationships_home`；`sequence` 仅出现在无关的审计元数据 `hindsight_audit_a05_a06.py:140`） | **已证实**（版面确实承载了原文没有的顺序断言）。但"读者**实际**读成因果"是**未验证假设**——需要盲评证人 |
| 3 | "每个单元必须落座"把标题/待办/过渡句变成废话 | `render_daily_v2_editorial.py:204-206` 硬失败；实测删 1 句即失败（§1.2）。反证：`classify_evidence_units.py:86-102` `is_structural_heading` 与 `:301-313` 待办已被排除出 daily 可见集，所以"标题/待办"这条**部分已被缓解**，"过渡句/低信息句"仍然成立 | **部分证实** |
| 4 | 评分器奖励覆盖与形式完整，垃圾稿也能得 100 | §1.2 实测：零编辑罗列 = 100/100 通过；`score_daily_v2.py:81` 主维度只数引用数 | **已证实**（已复现） |
| 5 | 修复始终作用于输出表层，没有更换中间表示 | `daily_v2_pipeline.py:554-558` / `:589-595`：LLM 草稿后串行 **8 道程序后处理**（`normalize` → `ground_unknown_periods` → `split_cross_period_items` → `enforce_primary_section_membership` → `complete_small_omissions` → `merge_source_block_items` → `apply_style_replacements`，外加 `expand_aliases`）；其中 `enforce_primary_section_membership` **丢弃**条目、`complete_small_omissions` 再用泛化标签补回 | **已证实** |

### 2.1 RCA 未覆盖、但同等重要的成因（我方补充）

1. **句级切分是一次"过度修正"**：`GATE_B_RESULTS_2026-09-20.md:54` 记载初版把句子合并成 14 个粗单元，被真实日报打回后升级为 `sentence-split-v2` → **33 个原子单元**。所以"句子=单位"不是从产品目标推导出来的，是**上一次失败的反弹**。RCA 把它描述成"设计选择"，实际是"历史事故的过度补偿"——这直接影响 Q2 的判断（见 §3）。
2. **"直接 LLM 基线"从未落地**（§1.1）。RCA 第 4 条归因于评分器，但更上游的问题是**产品规范 §6.18 的对照门禁被跳过**：`GATE_B_RESULTS` §8 记录"旧版结构门禁能够确认'16 条证据都被引用'，但产品阅读验收未通过"——**自动门禁绿灯、产品验收红灯**当时已经出现过一次，却仍然继续自动编排，直到本次冻结。
3. **多主题一句的历史结论是 facets，不是事件**：`GATE_B_RESULTS:82` 明确写下"仍存在一条同时描述记忆项目和交易的复合句，只能选择一个主栏目，后续需要以'主栏目 + 结构化 facets'解决，不能继续盲目细切逗号"。**当年就否决了事件化，选择了 facets。** 本次重置要翻这个案，必须解释当年为什么不是事件方案。

---

## 3. Q2 — Event Block 真的解决连贯性，还是把"句子过度切"换成"段落过度切"？

**当前提案不足以证明它解决了连贯性。** 三个缺口：

### 3.1 缺可证伪的事件边界判据

`DAILY_PRODUCT_RESET.md` §4 给的是**优先级**（用户显式结构 → 指代/时间/语义连续性 → LLM 建议），不是判据。优先级无法回答"这两句算一个事件还是两个"。没有判据，Event Block 就退化为"把 `sentence-split-v3` 换成 `paragraph-split-v1`"——**换粒度参数，不换模型**。

证据支持这个担忧：切分粒度在本项目已经**摆动过一次**（14 → 33，`GATE_B_RESULTS:54`）。摆动说明团队没有稳定的粒度判据，只有"上次被骂了就调细/调粗"。

### 3.2 缺"事件"的操作定义与度量

要证明"解决连贯性"，至少需要以下**可测量**指标（当前全缺）：

| 指标 | 定义 | 为何必须 |
|---|---|---|
| 事件计数一致性 | 系统事件数 vs 人工标注事件数的偏差 | 直接暴露过度切/过度并 |
| 边界稳定性 | 句序打乱 / 同义改写后，事件集合不变 | 若一改句子顺序事件就变，说明边界来自窗口而非语义 |
| 槽位填充率 | 背景/触发/行动/结果/感受/未解问题 的实际填充率与准确率 | reset §4 定义了槽位，却无验收 |
| 合并收益 | 同一事件内合并 vs 逐句罗列，人工判"更清晰"的比例 | 这正是 §1.2 里评分器测不到的东西 |

### 3.3 反例：合并**可能更差**

Event Block 不是单调改进。合成反例（脱敏）：

```text
原文（同一编号块）
  下午把接口联调通过了。
  晚上补完了说明文档。

方案 A（逐句）        两行，各自独立，读者一眼看到两件事、两个时间
方案 B（合并为事件）  "推进示例项目：下午联调接口，晚上补完文档。"
```

- 若原文的"下午/晚上"是**并列的两件事**，B 的"推进示例项目：…"会**制造**一个原文没有的统一叙事（reset §6 明确禁止）。
- 若原文是**一件事的两个阶段**（先联调、联调通过后才能补文档），B 才对。
- **系统目前无法区分这两种情况**，而现有 `validate()` 用时间词正则做裁决（§1.3）——这是"用版面/词表代替理解"。

> **判定**：Event Block 是**必要的**（现有表示确实错误），但**当前提案不充分**。必须补 §3.1 的判据 + §3.2 的度量，否则它只是把钟摆拨回去，且新钟摆更难被现有门禁发现（因为评分器对合并无感，§1.2）。

---

## 4. Q3 — 四类边界情况

### 4.1 一个事件涉及多个主题

**规则**：事件是渲染单位，主题是检索标签。事件**不因多主题而拆分**；主栏位由事件的**主导轴**决定，其余轴进入 `facets[]`。

**表示**：

```jsonc
{ "event_id": "e-01",
  "primary_axis": "work_project",
  "facets": ["trading_finance"],          // 仅用于检索/周报，不生成第二个正文条目
  "diverges_from": "e-00"                  // 与哪句共享原文（审计用）
}
```

**反例/失败模式**：`GATE_B_RESULTS:82` 的复合句（项目 + 交易）。若按旧机制，`CATEGORY_SECTION` 只允许一个 `primary_section`，模型必然二选一，另一轴**静默丢失**到 `other`。Event 层必须显式保留 `facets` 并在审计视图中可查。

**禁止**：为覆盖 facets 而在两个栏目各渲染一次（那是 reset §1"把一件事拆成一堆标签"）。

### 4.2 一个主题包含多个事件

**规则**：这是**常态**，不是边界情况。主题 → `group`，组内 = **N 个事件块**。事件块之间**不得合并**；顺序按 §5 的关系/原文偏移，不再按 `PERIOD_ORDER`。

**表示**：组只提供归属与检索，不提供叙事；`group.title` 仅是标签。

**失败模式**：现有实现把"组内排序"交给 `PERIOD_ORDER`（`render_daily_v2_editorial.py:248-251`），于是早上/中午/下午/晚上四个独立事件被强制成时间桶顺序，**丢掉原文叙事顺序**（与 `DAILY_VIEW_V2_SPEC.md:52`"日报顺序优先尊重用户原始记录的叙事顺序"冲突）。

### 4.3 长文无明确标题

**规则**：边界按以下顺序取，且**必须在表示里记录边界来源与置信度**：

1. 显式结构（标题 / 编号块 / 段落）→ 已可实现：`build_evidence_units.py:51-58` 已经在算 `source_block_id`（编号块），**这是现成的、被低估的资产**；
2. 指代/时间/语义连续性 → 仅在同段内、且有显式指代或时间标记时成立；
3. LLM 建议 → **只作提案**，附 `confidence` 与所引用原文片段。

**硬规则**：模糊处**默认拆开**（fail-open = 多事件），绝不静默合并。理由：漏合并的可发现性高（读者会觉得散），错合并的可发现性低（读者会以为原文如此），后者正是本次冻结的成因。

**失败模式**：`daily_v2_pipeline.py:427-487` `merge_source_block_items()` 用 `"；"` 把同块条目拼接成一句（`:468`）。这会**在文本层制造连续叙事**，且没有任何 relation 标记。这是伪因果的直接文本来源。

### 4.4 跨文档补记

**规则**：必须沿用双时间（`DESIGN_V3.md:38-47` 已定 `valid_time` / `recorded_time`）。

- 补记按 `valid_time` 归入**目标日**；
- 事件块记录 `recorded_time` 与 `backfilled=true`；
- 补记**不得**静默并入原事件正文；应作为 `amendment` 挂在该事件下（附自身证据），或在正文中以显式标记（如"（后来补记）"）呈现。

**失败模式**：`build_evidence_units.py` 以 `document_id + date` 为单位；跨文档合并若在 Event 层按 `document_id` 分组，会把补记当成"另一件事"或按到达顺序排错。**Event 层必须以 `valid_time` 为键，不能继承文档分组。**

---

## 5. Q4 — 事件内部关系表示，以及如何禁止版面伪因果

### 5.1 现状（证据）

| 现状 | 位置 | 后果 |
|---|---|---|
| 无任何关系字段 | Daily V2 正文表示中 `relation`/`causal`/`cause` 零命中 | 关系只能靠**版面**推断 |
| 分组顺序固定 | `render_daily_v2_editorial.py:43-58, 241` | "交易执行 → 结果与风险"永远这个顺序 |
| 组内按粗时间桶排序 | `:248-251`、`PERIOD_ORDER:60` | 原文顺序被覆盖 |
| 文本层拼接 | `daily_v2_pipeline.py:468` | 用"；"制造连续叙事 |

三者叠加 = **版面在替原文断言顺序与因果**。

### 5.2 提案：显式关系 + 原文序渲染

**表示**（事件块内）：

```jsonc
"relations": [
  { "from": "s-01", "to": "s-02",
    "kind": "parallel",            // parallel | sequence | contrast | cause
    "basis": "explicit",           // explicit | proposed
    "cue": "然后"                   // basis=explicit 时必填：原文里的显式标记
  }
]
```

- **默认 `parallel`，不携带任何时间断言**（对齐 reset §4"未明示时默认为并列"）；
- `kind="cause"` **仅当** `basis="explicit"` 且 `cue` 在原文中逐字存在（因为/所以/导致/使得/于是/因此…）才成立；
- 事件块内部条目按**原文 `start` 偏移**渲染；跨条目顺序不得由分组或时间桶决定。

**渲染硬规则（可否决）**：

1. 正文出现因果连接词 → 必须能映射到某条 `relations` 且 `basis="explicit"` 且有 `cue`；否则硬失败。
2. **禁止用版面表达进程**：不得存在"因为 A 组在 B 组之前所以读者应理解成先后"的结构。落地做法：**组只做标签，不做容器**；跨组条目必须按原文偏移序输出。
3. `span` 不再是"时间词正则的逃生口"，而是由 `relations` 中显式 `sequence` 推导（覆盖 §1.3 的"正则裁定粒度"问题）。

> 这三条会**删除** `GROUP_DEFINITIONS` 的固定顺序语义（见 §9），这是有意的：它是伪因果的结构性来源。

---

## 6. Q5 — 哪些环节交给 LLM，哪些必须由程序确定

判据：**可被逐字核对的事 → 程序；需要理解与措辞的事 → LLM；决定"事实是否消失/通过与否"→ 程序且必须可审计。**

| 环节 | 归属 | 理由 |
|---|---|---|
| 显式结构切分（标题/编号块/段落）、字符区间、哈希 | **程序** | 可逐字核对；`source_block_id` 已实现 |
| 显式时间戳解析 | **程序** | 事实性 |
| 证据完整性与去重（按精确 span） | **程序** | 必须 100% 可追 |
| 覆盖率**核算**（不是覆盖率**门禁**，见 §8） | **程序** | 审计需要 |
| 关系默认值（`parallel`） | **程序** | 防止"未明示即因果" |
| 渲染顺序 | **程序** | 防止版面伪因果 |
| 通过/否决与隔离 | **程序** | 不能由被评者自评 |
| 事件主题命名、槽位填充、措辞压缩 | **LLM** | 需要理解与表达 |
| 模糊边界处的合并/拆分**提案** | **LLM（仅提案）** | 必须附 `confidence` + 所引原文；未采纳也保留记录 |
| 关系**提案** | **LLM（仅提案）** | 同上，且因果必须给 `cue` |
| 决定某条事实是否从系统消失 | **禁止 LLM** | reset §3；`GATE_B_RESULTS` §4 同结论 |
| 选择一级栏目 / 决定排序 / 决定是否通过 | **禁止 LLM** | 既有教训：`GATE_B_RESULTS:118` "模型自行创建了一级栏目" |

### 6.1 现状违规：程序在替代编辑判断

`DAILY_VIEW_V2_SPEC.md:162`（§7.3）明令"程序不得用大量专属文案规则代替编辑判断"。但现状：

- `daily_v2_pipeline.py:383-404` `fallback_group_id()`：用关键词正则（`re.search(r"早餐|早上|…")`）决定一条事实进"早餐/午餐/晚餐/加餐"哪个组；
- `render_daily_v2_editorial.py:67-84` `detect_periods` / `infer_period`：用正则决定时间桶，并**据此裁定合并是否合法**（§1.3）；
- `classify_evidence_units.py:53-83` `_task_anchors` + `suppress_redundant_completed_tasks`：用 3–4 字 n-gram **子串匹配**决定"这条已勾选待办是否被更丰富的事实覆盖"，命中即隐藏。

第三项风险最高：中文 3-gram 子串命中的误配率不可控（任意两句话共享一个 3 字片段即命中）→ 可能**误隐藏一条真实事实**。这是"程序替编辑做判断"的典型，且**静默**。

> **建议**：以上三处降级为"只产生候选标记、不自动隐藏/不自动定组"，或直接删除（§9）。

---

## 7. Q6 — 相对"直接原文→LLM"基线，Event-first 必须额外证明什么

**前提**：基线必须**先实现**。当前不存在（§1.1）。这是 WB-08 之前的**前置任务**，不是"以后再说"。

基线定义（严格版）：同一份当日原文，**不经 Evidence Unit 切分、不经分类**，一次 LLM 调用直接产出"给人读的当日回顾"，同样跑硬门禁（伪因果、可追溯——可追溯对基线是弱点，正是要暴露的差异）。

Event-first 必须**额外**证明（相对基线）：

| 维度 | 若不能证明的后果 |
|---|---|
| **1. 事实忠实度更高**（无支持陈述率更低） | 基线更便宜即可胜出 |
| **2. 事件完整性更好**（相对人工标注事件集，漏事件更少） | Event-first 的核心卖点消失 |
| **3. 每条正文事实可定位到原文 span** | 基线通常做不到；这是 Event-first **最可能赢**的一项，应重点取证 |
| **4. 多主题一句 / 一主题多事 的处理更稳**（基线常在这两类出错） | 若基线也不出错，则中间层是纯开销 |
| **5. 成本可接受**（token / 时延 / 稳定性） | 见下 |

**举证责任在 Event-first 一侧。** 基线更简单、更少组件、更少维护面；Event-first 增加了切分器 + 事件层 + 关系 + 渲染约束。按"最简可比方案"原则，**Event-first 必须至少在两项上可测量胜出**，否则应选基线（并**把程序能力用在事后校验**：伪因果检查、span 回溯、事件完整性检查——这些对基线同样有效）。

**特别提醒**：`GATE_B_RESULTS:82` 的历史结论是"用 facets 解决多主题"而非"用事件"。若基线 + facets + 事后校验已能达标，Event-first 的中间层就应被放弃——这正是 §8 中 G3 的停工条件。

---

## 8. Q7 — 可否决方案的硬门禁（不是"建议优化"）

每条门禁给出：**判据 / 阈值 / 否决后果**。未达标即**否决**，不允许用其他维度的高分抵消。

### G0（前置，现在就必须满足）— 对照基线存在

- **判据**：仓库内存在可运行的"直接原文→LLM 基线"入口，能与 Event-first 稿同日产出匿名版本。
- **阈值**：基线入口存在，且三者（原文 / 基线稿 / Event-first 稿）具备匿名化与同日配对产出能力。
- **否决后果**：**G0 未满足前，WB-08 不得宣布"Event-first 通过"**（可定义 schema、可出隔离区原型）。理由：没有对照物，"通过"无意义。

### G1 — 三日反例集硬门禁

- **判据**：`DAILY_PRODUCT_RESET.md` §7 指定的 2026-09-04 / 09-05 / 09-12。
- **阈值**：三日的硬失败项**零容忍**——错置事件、伪因果、未完成当完成、关键结果遗漏，出现任一即**当日不合格**。
- **否决后果**：任一反例日不合格 → **方案否决**（不是"再调 prompt"）。

### G2 — 伪因果双门禁

- **判据**：机器检查 + 人工盲评。机器：正文中的因果连接词必须能映射到带 `cue` 的显式关系（§5.2）；人工：盲评者只看到稿件，标记"哪些先后/因果是原文没有的"。
- **阈值**：机器硬失败 0；人工标记的伪因果 ≤ 基线稿的伪因果数。
- **否决后果**：机器能构造出"版面即因果"的稳定反例 → **否决渲染方案**；人工伪因果多于基线 → **否决 Event Block 的合并收益主张**。

### G3 — 增量价值门禁（最重要）

- **判据**：§7 的五项，至少两项可测量胜出；且 §6.18 的"≥80% 盲评不差于基线"。
- **阈值**：≥2 项胜出 **且** 不差率 ≥80% **且** 无一日"比原文更难理解"。
- **否决后果**：不满足 → **取消 Event-first 中间层**，改为"直接原文→LLM + 程序事后校验（伪因果 / span 回溯 / 事件完整性）"。注意：**这是否决，不是降级为"以后优化"**。

### G4 — 可追溯门禁

- **判据**：正文每条事实可定位到原文 `document_id + 字符区间`；事件摘要不得引入原文没有的结果/动机。
- **阈值**：100% 可定位；抽样人工核对"新增动机/结果" = 0。
- **否决后果**：不可追溯的事实 > 0 → 拒绝发布（与现有 `DESIGN_V3.md:241` 一致，此处只是把它变成硬门禁）。

### G5 — fail-safe：证明不了就出原文

- **判据**：系统必须能判定"生成稿是否比原文更清晰"；判不了时默认输出原文或轻度编辑版。
- **阈值**：存在可执行的降级路径，且 `DAILY_PRODUCT_RESET.md` §5"允许保留原文"被实现在入口而非文档里。
- **否决后果**：若系统**无法**表达"本日不发布"，则**不得恢复自动发布**——否则违反唯一产品目标。

### G6 — 不回退既有已达成项

- **判据**：保留用户稳定措辞 / 不书面化 / 事实-计算-推断分层 / 默认隐藏证据索引（`DAILY_VIEW_V2_SPEC` §4、§5、§6.7）。
- **阈值**：全部保持；`avoid_terms` / `preserve_terms` 检查仍硬失败。
- **否决后果**：任一回退 → 不得合并。

### 8.1 一条必须先修的"反向门禁"

现有 `validate()` 的"100% 落座"（`render_daily_v2_editorial.py:204-206`）与 G5 直接冲突：**它使"不总结/省略低信息句"在机器上不可能**。因此 Event-first 的第一步不是加功能，而是**把"落座门禁"改成"可追溯门禁"**：

- 旧：每条可见单元**必须**出现在正文（硬失败）。
- 新：每条正文事实**必须**可追溯到原文（硬失败）；单元**允许**不被正文引用，但必须可被审计视图列出。

这是 §9 删除清单的第 1 项，也是 §10 的第一条建议 diff。

---

## 9. Q8 — 应**删除**而非重写的旧组件

判据：**前提错误的组件，重写是沉没成本**（它的存在本身就表达了一个错误的架构假设）。以下按"该删"排序：

| 组件 | 位置 | 为何"删"而非"重写" |
|---|---|---|
| **百分制评分器** | `score_daily_v2.py:20-21, 80-97`（`PASS_SCORE=85`、五维度） | 前提错误：它假设"引用覆盖 = 质量"。实测对合并完全无感、对省略敌意（§1.2）。**不要重写维度**——维度化打分本身就是"用代理指标替代阅读"的错误。替换为"硬门禁 + 盲评"，不做分数。 |
| **"100% 落座"硬错误** | `render_daily_v2_editorial.py:204-206` | 前提错误：把"证据不丢失"错误实现为"正文必须展示每句"。是 reset §1"展示废话"的机器化来源。改为"可追溯"，见 §8.1。 |
| **`CATEGORY_SECTION` 1:1 映射 + `enforce_primary_section_membership`** | `render_daily_v2_editorial.py:30-41`；`daily_v2_pipeline.py:211-238` | 前提错误：让"句子分类"决定"页面结构"。与事件层根本冲突（事件跨主题、主题含多事件都违反 1:1）。删。 |
| **`split_cross_period_items`** | `daily_v2_pipeline.py:245-275` | 前提错误：它假定"跨时段 = 应拆"。会把正确的事件合并**拆回句子**，与 Event Block 目标相反。删。 |
| **`GROUP_DEFINITIONS` 的固定顺序语义**（尤其 `trading_finance` 的 execution→result_risk） | `render_daily_v2_editorial.py:43-58, 241` | 前提错误：用版面表达进程。保留"受控 group_id 集合"作检索标签可以，但**必须删掉"顺序即叙事"**。 |
| **`suppress_redundant_completed_tasks`（n-gram 子串匹配）** | `classify_evidence_units.py:53-83` | 前提错误：用子串命中代替语义判重，会**静默误隐藏**真实事实。删，或降级为"标记候选，交人工/LLM 复核"。 |
| **`fallback_group_id` / `detect_periods` 关键词表** | `daily_v2_pipeline.py:383-404`；`render_daily_v2_editorial.py:67-84` | 前提错误：程序用词表替代编辑判断（违反 §7.3）。且 `detect_periods` 目前在**裁定合并合法性**（§1.3）。删关键词表，仅保留显式时间戳解析。 |
| **`classification_messages` 中"不得合并 ID"约束** | `classify_evidence_units.py:144-146` | 前提错误：在 Event-first 下，合并恰恰是需要的。**这一条是"删"而不是"删掉整个分类器"**——分类/打标能力仍有用，只是不再充当阅读单位。 |

**应保留（不删）并复用的资产**：原子发布与哈希（`PIPELINE.write_json_atomic`）、失败隔离（`write_rejection` / quarantine）、`source_block_id` 与字符区间（`build_evidence_units.py:51-58`）、`contextual_unit_periods` 的指代继承（`daily_v2_pipeline.py:349-365`，思路对，但应基于显式指代而非全表回填）、`expand_aliases` 短 ID 机制（`:147-157`）、脱敏与审计视图（`--audit-details`）。

---

## 10. 建议 diff（**提案，未应用**）

> 以下均为**建议**。本评审**未修改任何决策文档、未改 `config/daily-v2.freeze`、未解冻任何入口**。若主线采纳，请自行 apply 并单独提交。

### 10.1 `render_daily_v2_editorial.py` — 把"落座门禁"改成"可追溯门禁"

```diff
-    missing = sorted(set(source_units) - set(referenced))
-    if missing:
-        errors.append(f"daily units without editorial destination: {missing}")
+    # 证据不必逐条落座正文；它必须先进入证据索引，再由审计视图列出。
+    # 正文只需要保证：凡是写出来的事实，都能追溯回原文。
+    # 未被正文引用的可见单元进入 audit-only 集合，由 --audit-details 呈现。
+    audit_only = sorted(set(source_units) - set(referenced))
     for unit_id, unit in source_units.items():
         expected = CATEGORY_SECTION.get(unit.get("category"), "other")
-        if unit_id in reference_sections and expected not in reference_sections[unit_id]:
-            errors.append(f"unit {unit_id} must appear in primary section {expected}")
         if expected == "reflection_growth" and reference_sections.get(unit_id, set()) - {expected}:
             errors.append(f"reflection unit {unit_id} must not be duplicated outside reflection_growth")
```

并把返回值改为包含 `audit_only_units`，供审计视图与状态页使用。

### 10.2 `render_daily_v2_editorial.py` — 删除"跨时段即拆"的正则裁定

```diff
-                detected = detect_periods(f"{item.get('label', '')} {item.get('text', '')}")
-                if (len(detected) > 1 and period != "span"
-                        and not (section_id == "sleep" and group_id == "night_sleep")):
-                    errors.append(f"{path} mixes distinct event periods {sorted(detected)}; split into separate items")
+                # 是否允许一个条目覆盖多时段，由事件层的关系表示决定（relations[].kind == "sequence"），
+                # 不再由时间词正则裁定。此处只校验 period 取值合法。
```

### 10.3 `score_daily_v2.py` — 用硬门禁替代百分制

```diff
-SCORE_VERSION = "daily-v2-score.1"
-PASS_SCORE = 85
+SCORE_VERSION = "daily-v2-gates.1"
+# 不再使用百分制：代理指标无法度量事件完整性、伪因果与信息价值（见 reviews/WB07_EVENT_FIRST_RED_TEAM.md §1.2）。
+PASS_SCORE = None
@@
-    dimensions = {
-        "evidence_integrity": round(35 * len(known_refs) / source_count),
-        ...
-    }
-    total = sum(dimensions.values())
-    hard_failures = list(structural_errors)
+    hard_failures = list(structural_errors)
+    # 硬门禁（任一命中即拒绝，不允许用其他维度抵消）
+    hard_failures += causal_connective_gate(editorial, classified)   # 伪因果
+    hard_failures += traceability_gate(editorial, classified)         # 正文事实必须可定位 span
+    total = 0
```

### 10.4 `DAILY_VIEW_V2_SPEC.md` — 把"对照基线"从要求变成前置条件

```diff
-18. 管道版必须与“当天原始材料直接交给 LLM”的基线版定期同日盲评；若在事实正确性、组织、语言和可读性上不能稳定胜出，不得以“自动化”为由上线。
+18. 管道版必须与“当天原始材料直接交给 LLM”的基线版定期同日盲评；若在事实正确性、组织、语言和可读性上不能稳定胜出，不得以“自动化”为由上线。
+18a. 该基线必须有可实现、可运行的入口（当前不存在）。基线落地前，任何“管道胜出”的结论与任何“新架构通过”的验收均不成立。
+18b. 评分必须包含“事件完整性”与“伪因果”两项，且二者为硬门禁；不得以引用覆盖率作为质量代理。
```

---

## 11. 复现命令与未验证假设

### 11.1 复现 §1.2 的评分实验（纯合成、零 LLM、零 Vault）

```bash
cd <repo>
python3 - <<'PY'
# 见本评审正文 §1.2 的 6 个变体；核心：构造 4 个可见单元 + editorial，
# 调用 score_daily_v2.score()，观察 "零编辑罗列" 得 100/100 且 passed=True，
# 而 "删 1 句" 触发 daily units without editorial destination 硬失败。
PY
```

实测结果（Python 3.13.12）：

```text
零编辑逐句罗列(4 单元各一条)      score=100 passed=True
同段合并(4 单元全引用)            score=100 passed=True
跨段合并(未标 span)               score=100 passed=False  hard=["mixes distinct event periods ['afternoon','evening']"]
跨段合并(已标 span)               score=100 passed=True
删 1 句低信息                     score= 91 passed=False  hard=["daily units without editorial destination: ['u1']"]
删 2 句低信息                     score= 83 passed=False  hard=[... + 跌破 85]
```

### 11.2 本次评审**未验证**的假设（明确标注，避免被当成结论）

1. **"读者会把固定栏目顺序读成因果"** —— 代码证明版面确实携带了原文没有的顺序断言，但"读者实际读成因果"需要盲评证人，本评审无人类被试。
2. **"Event Block 能提升可读性"** —— 无对照基线（G0），不可证。
3. **"n-gram 子串匹配会误隐藏真实事实"** —— 机制上必然可能（任意两句共享 3 字片段即命中），但**发生频率未测**（需真实语料，本次不允许）。
4. **"直接 LLM 基线在可追溯性上必然更弱"** —— 属合理预期，未实测。
5. 全部结论基于 `be1c3db`；`DAILY_PRODUCT_RESET.md` 与 `config/daily-v2.freeze` 取自主仓工作树中**尚未提交**的版本（`main` 上尚不存在），若其正式提交版本有出入，§2 的条目对应关系需重新核对。

### 11.3 给抽取方的三个问题（评审无法自行回答）

1. `GATE_B_RESULTS:82` 当年明确选择"主栏目 + facets"而非事件化，**这次翻案的依据是什么**？是否只是"facets 实现得不够好"？
2. 反例集 2026-09-04/05/12 的**人工标注**由谁做、什么标准？没有人工事件标注，§3.2 的事件完整性无法度量。
3. 是否接受 G3 的结论——**若 Event-first 不能在 ≥2 项上可测量胜出，就取消中间层改走基线 + 事后校验**？
