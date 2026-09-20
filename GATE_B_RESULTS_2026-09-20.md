# Gate B 真实数据 Dry-run 结果

> 日期：2026-09-20
>
> 结论：证据门禁有效，但“让 LLM 自由决定提取哪些事实”不达到产品要求，转向 Evidence Unit 优先。

## 1. 执行边界

- 输入：3 份 2026-09-20 Gateway Documents；
- Provider：已配置智谱 `glm-4.5-air`；
- 所有文件保存在服务器 `/opt/personal-memory-evaluation`，目录 `700`、文件 `600`；
- 没有 Claim 被接受，没有写入 Hindsight 或正式 Obsidian Vault。

## 2. 实测结果

| 实验 | 结果 | 关键问题 |
|---|---:|---|
| Prompt v1 | 结构拒绝 | 候选 evidence 为空 |
| Prompt v2 | 9 条通过，召回 57.9% | 遗漏三餐和宠物长期档案 |
| Prompt v3 原始响应 | 12 条 | 1 条合并了多个无关事件；3 条证据校验失败 |
| v3 逐条隔离 | 9 条通过，召回 73.7% | 不应因一条失败丢弃整批 |
| v3 唯一标点对齐 | 11 条通过，召回 84.2% | 2 条中英引号差异安全对齐；1 条少词仍拒绝 |
| 定向修复 | 180s 读超时 | 无产物，不重试 |

Prompt v2 可记录的一次调用指标：68.013s，1,071 prompt tokens，4,817 completion tokens，总计 5,888 tokens。Prompt v3 的 metrics 因早期隔离格式未保存，不伪造数据。

## 3. 关键判断

Prompt v3 能把原始覆盖提高到接近完整，但仍有：

- 模型自主遗漏；
- 不同主题被合并；
- Subject 错绑风险；
- 非逐字引用；
- 修复调用时延和额度不稳定。

因此不继续用 Prompt 堆叠掩盖数据完整性问题。

## 4. 新的实施方向

```text
Documents
  → 程序确定性切分 Evidence Units（100% 非空白内容覆盖）
  → LLM 对每个 unit 做分类/压缩/Subject 候选
  → 漏标或失败的 unit 保留为 unclassified
  → 风险分流与人工确认
  → 时间视图 / 持续脉络
```

完整性由程序保证，LLM 只决定阅读形态，不再决定某条事实是否从系统中消失。

## 5. Evidence Unit 基础实现

- 初版把连续中文句子错误合并成 14 个粗粒度单元；真实日报检查发现后，切分器升级为 `sentence-split-v2`，不再要求中文句末标点后存在空格；
- 非空白原文覆盖率 100%；
- `classify_evidence_units.py` 要求每个 `unit_id` 恰好返回一个标签；
- 缺失、非法、重复或引用未知 Subject 的标签进入隔离记录，对应单元自动回退为原文；
- `render_daily_from_units.py` 只渲染非空栏目，同时保留每个单元的 Document ID、原文和字符区间脚注；
- baseline、离线响应处理和 Markdown 渲染均为零 LLM 调用。

此实现先解决“信息不能消失”，尚未证明分类、摘要和持续脉络关联质量。真实 LLM 分类必须单独授权并经过人工评审，不能直接进入正式 Obsidian。
