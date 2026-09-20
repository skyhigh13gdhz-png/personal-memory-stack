# 2026-09-20 历史日记导入记录

## 范围

- 来源：`/Users/weizhenliang/obsidian空间/每日记录/2026/9月`
- 身份：`speaker=liangzai`
- 文件：15 篇，日期覆盖 2026-09-04 至 2026-09-19（无 09-10）
- 正式入口：Memory Gateway Retain API；未直接写 Hindsight 数据库

## 去重与导入结果

- 2026-09-16、17、18 已有正式记录，按事件日期识别并跳过；保留库内已纠错版本。
- 其余 12 篇完成导入。
- 2026-09-11 单篇调用时智谱返回 HTTP 500；按原 Markdown 标题自然拆为 `morning`、`memory-system`、`daily-activities` 三个同日 Document。三部分按顺序拼接后的 SHA-256 与源文件一致，未改写或遗漏正文。
- 新增 14 个 Documents，对应 12 篇源文件；稳定 ID 使用 `obsidian-daily-liangzai-YYYY-MM-DD[--slug]`。
- 最终幂等 dry-run：11 篇 exact duplicate，4 个日期已有记录，无待导入项。

## 配置调整

- Retain 与 Consolidation 使用智谱 `glm-4.5-air`。
- 保留 `HINDSIGHT_API_LLM_MAX_CONCURRENT=2`，避免后台 Consolidation 阻塞前台 Reflect。
- Retain/Consolidation timeout 调整为 180 秒。
- 修复容器 cgroup 透明代理规则：只能在最终容器启动后绑定，绑定后不再重启容器。

## 验收

- Gateway Documents 总数：23。
- 只读投影：17 个正式 Documents，6 个已知测试噪声排除，生成 15 个日期 Markdown。
- 2026-09-04、09-11、09-19 的稳定 Document ID 均可查询。
- Recall 扩大到 100 条后，以下目标事实均存在：家庭资金与找工作约定；小黑挠门、晨间烦躁与金刚功；《兰香如故》、小红书工作和合约收益。
- 初始 `max_results=5` 的 Recall 排序曾优先返回 09-16/09-18 高相关记忆；事实已入库，但小结果集排序仍需单独优化，不能与导入完整性混为一谈。

## Obsidian

- 已刷新 `AI/AI外置记忆/00-系统生成/原始记录/liangzai`。
- 旧投影已备份到相邻 `.history` 目录。
- 源目录 `每日记录/2026/9月` 未修改。
