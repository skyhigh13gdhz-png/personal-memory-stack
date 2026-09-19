# Hindsight V2.1 审计结果（2026-09-19）

## 1. 环境与边界

| 项目 | 值 |
| --- | --- |
| Server | 106.53.204.254 |
| Hindsight | 0.10.0 |
| Image | ghcr.io/vectorize-io/hindsight:latest |
| Image digest | sha256:3edcb6165cefdeaa6721dd0fce43cfd13b7a9c346ce0d2c5f4b4bf7bc3c8ac0b |
| Upstream revision | 5d46f9c8c8eb4fb96f549aa63abe1191b82a7840 |
| Audit banks | audit-v21-* |
| Production data touched | no |

所有写入均使用无隐私测试数据和独立 bank。A03 只删除它自己创建的生命周期测试 Document。

## 2. 结果摘要

| ID | 结果 | 结论 |
| --- | --- | --- |
| A01 | PASS | Gateway Retain 后可通过 Document API 逐字节取回 original_text |
| A02 | PASS | 同 document_id replace 会更新原文/hash，删除旧 Memory 并生成新 Memory |
| A03 | PASS | reprocess 可提交；delete 同时删除 Document 和关联 Memory |
| A04 | PASS WITH FINDING | timestamp/timeless/多事件时间可用；多事件抽取粒度存在非确定性 |
| A05 | PASS | tags all_strict、offset/limit 分页和重复查询排序通过 |
| A06 | PASS WITH FINDING | 三种模式原文均完整，当前样本 6/6 召回均通过 |
| A07 | TODO | ChatGPT 图片 → MCP → Gateway → Attachment |
| A08 | TODO | 导出、备份、恢复和迁移 |

## 3. A01 原文完整性

- run_id：20260919T220000Z
- bank_id：audit-v21-20260919t220000z
- document_id：9f3174de-5010-405e-8d5b-de81806394b3
- expected sha256：ef12f0ac536e28986b3a269290717ed292b3e2447efaa1152daae16bd6dea5eb
- actual sha256：ef12f0ac536e28986b3a269290717ed292b3e2447efaa1152daae16bd6dea5eb

路径是 Gateway Retain → Hindsight → Document GET，不是直接写数据库。中文、换行、START/END 哨兵和中间唯一值全部保留。

结论：Document.original_text 在当前版本可作为原文持久化候选字段。

## 4. A02 Replace / Correction

原文从“CRV 止损亏损 42 美元”更新为“CRV 止损亏损 52 美元”。Document created_at 保持，updated_at 和 content_hash 变更；旧 Memory ID 被删除，新 Memory ID 生成；Memory List 中旧 42 消失，只保留新 52。第二个全新 bank 重跑结果一致。

结论：Hindsight replace 可作为 Correction 的底层更新机制。Gateway 仍应实现 expected_text compare-and-swap，防止 LLM 基于过期内容修改。

replace 本身不提供业务纠错历史，后续仍需要轻量 append-only Correction Log。

## 5. A03 Delete / Reprocess

- reprocess success：true
- delete success：true
- memory_units_deleted：1
- Document after delete：HTTP 404
- Memories after delete：0

结论：Document 和关联 Memory 的删除生命周期在当前版本一致。reprocess 是异步操作；本轮确认成功提交和 operation ID，完成状态轮询及重复 Memory 检查留待幂等回归。

## 6. A04 时间模型

- 显式 2026-09-19T19:00:00+08:00 被保存为 retain event_date，Memory 转换为等价 UTC；
- 补录昨天正确锚定到 9 月 18 日；
- timestamp=unset 时不伪造时间，mentioned_at/occurred_* 全为 null；
- 多事件文本能识别“昨晚 23:00 → 今早 08:00”和“今天 15:00”。

两次相同语义测试分别产生 3 条和 2 条 Memory；第二次将入睡/起床合并为一个时间区间，没有丢失事件，但证明抽取粒度并非完全确定。

结论：时间模型足以进入 Gateway timestamp 薄封装设计，但日报生成必须以 Document 原文保证完整性，不能只依赖 Memory Unit 数量。

## 7. A05 Tags / Pagination / Ordering

- Document 总数：5
- speaker:audit + source:chatgpt 严格匹配：3
- 分页 limit：2
- 分页唯一 ID：5/5
- 重复查询排序：稳定

结论：tags 可以支持 V2.1 的 speaker/source/session 轻量索引。本次只验证小数据量，大规模性能和并发分页一致性仍需长期回归。

## 8. A06 Extraction Mode A/B

| Mode | Memory Units | Retain | Tokens | Recall | 原文 |
| --- | ---: | ---: | ---: | ---: | --- |
| concise | 6 | 35.3 s | 2673 | 6/6 | 逐字一致 |
| verbose | 7 | 66.1 s | 3150 | 6/6 | 逐字一致 |
| verbatim | 1 | 11.6 s | 1370 | 6/6 | 逐字一致 |

固定问题集覆盖睡眠、交易币种、CRV 亏损、午休、晚饭/金额和项目决策。

当前样本上 verbatim 最快、token 最少且未漏召回，但不能据此立即设为生产默认：

- 它把整段作为一个 Memory Unit，局部时间、图检索、Reflect 和更长文本上限尚未充分测试；
- 当前是单样本、单轮，不代表稳定召回率；
- verbose 成本明显更高，但可能在更长或更复杂记录中有价值。

阶段决策：生产默认暂不改。下一轮使用更长、多时间、包含否定和更正的样本做多轮回归，再在 concise 与 verbatim 之间决策。

## 9. 当前架构决策

1. V2.1 不启动独立 Record PostgreSQL；
2. Hindsight Documents 继续作为候选 Record Layer；
3. Gateway 下一步可开始设计薄封装：document_id、timestamp、Document GET/List 和 compare-and-swap Patch；
4. A08 通过之前，不将 Hindsight 正式宣布为唯一 Canonical Source；
5. A07 失败时只补真实缺口，不预先建设 Asset Store。

## 10. 可重复入口

- scripts/hindsight_audit_a01_a04.py
- scripts/hindsight_audit_a05_a06.py

脚本不包含凭据，不访问非 audit-* bank。原始 JSON 保留在服务器 /var/tmp/hindsight-audit-* 目录。
