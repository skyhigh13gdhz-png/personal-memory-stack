# Claim 候选流水线

> 状态：Gate B 本地原型，不写生产 Hindsight / Obsidian。

## 1. 目标与边界

解决“人工整理 Claim 不可持续”的问题，但不把 LLM 升格为事实裁判者。

```text
Documents
  → LLM 只提候选 Claim
  → 程序校验 Schema / 日期 / Subject 白名单 / 逐字引用
  → 风险政策分流
  → 人工接受或拒绝
  → accepted Claims
  → 时间视图 / 持续脉络
```

LLM 无权：

- 创建 Subject；
- 引用不存在的原文；
- 把记录时间当作事件时间；
- 绕过高影响人工确认；
- 把候选直接投影到正式 Vault。

## 2. 风险政策

| 条件 | 政策 |
|---|---|
| 普通 event / metric，不关联高影响 Subject | `auto_accept_eligible`，仍需显式运行 `--accept-safe` |
| state / preference / decision / commitment | `manual_review` |
| 人物、健康、习惯、资产、策略、目标 | `manual_review` |
| 未知 Subject、日期不一致、非逐字引用 | 整批拒绝 |

`auto_accept_eligible` 不等于已接受，只表示可由明确的本地政策批量接受。

## 3. 额度与重跑控制

- 一个输入 bundle 只调用一次 LLM；
- cache key = `source_sha256 + prompt_version + model`；
- 三者未变时直接跳过 LLM；
- review / export / render 均不调用 LLM；
- `--force` 只用于明确的模型质量重评。
- 每次真实调用在候选包内记录 model、response ID、时延及 prompt/completion/total tokens；输入价格表后可程序计算成本。

这意味着一天正常最多一次 Claim extraction 模型调用，并非日回顾、Subject 页、Obsidian 同步各调一次。

## 4. 本地操作

```bash
# 先从 Gateway Date Range 生成当日完整私有输入
python3 scripts/build_claim_input.py --date 2026-09-20 \
  --subjects config/subjects.example.json \
  --output local-evaluation/2026-09-20-input.json

# 首次提取：默认使用智谱兼容接口，也可用 CLAIM_LLM_* 覆盖
python3 scripts/claim_candidate_pipeline.py extract local-evaluation/input.json \
  --output local-evaluation/candidates.json

# 仅接受政策判定为低风险的候选
python3 scripts/claim_candidate_pipeline.py review local-evaluation/candidates.json \
  --accept-safe --note "local Gate B review"

# 高影响候选必须显式指定 ID
python3 scripts/claim_candidate_pipeline.py review local-evaluation/candidates.json \
  --accept cand-xxxxxxxxxxxxxxxx --note "manually confirmed"

# 只导出 accepted Claims；证据覆盖不完整时拒绝导出
python3 scripts/claim_candidate_pipeline.py export local-evaluation/candidates.json \
  --output local-evaluation/accepted-golden.json
```

可以用 `prepare --response` 注入已保存的模型 JSON，不产生任何网络调用；该入口用于回归测试和 Provider A/B 比较。

## 5. 下一个决策点

在真实数据上只允许 dry-run，比较：

1. Claim 事实召回率；
2. 非逐字引用被拒绝的比例；
3. 高影响候选的人工确认负担；
4. 与手工 golden set 的差集；
5. 单日调用次数、耗时和 token 成本。

达不到关键事实召回率 95% 或人工审核负担过高时，不进入正式 Obsidian。
