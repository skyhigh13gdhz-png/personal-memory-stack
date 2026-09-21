# WB-01 主线复核结论

> 复核对象：WorkBuddy commit `94d6f28`
>
> 结论：方向正确、原有 134 项测试通过，但存在真实调度阻塞项，暂不合并、不安装 LaunchAgent。请在原分支完成 WB-01R 后重新提交。

## 已确认的优点

- 复用了既有同步、Daily V2 和状态渲染脚本，没有复制业务实现；
- 使用 `fcntl.flock` 处理 macOS 并发锁；
- 有限重试、失败非零退出、同步失败时跳过日报等基本语义正确；
- LaunchAgent plist 不直接写入密钥；
- 测试使用临时目录和 fake command，没有读取个人正文或调用外部 LLM；
- Python 3.9 / 3.13 兼容方向合理。

## WB-01R 必须修复

### R1 环境文件没有配置运行器自身

`--env-file` 只在 `Runner.child_env()` 中注入子进程；`config_from_args()` 在此之前直接读取 `os.environ`。因此 env 文件中的以下配置对运行器本身无效：

- `PERSONAL_MEMORY_VAULT_DIR`
- `PERSONAL_MEMORY_RAW_DIR`
- `PERSONAL_MEMORY_DAILY_DIR`
- `PERSONAL_MEMORY_STATUS_OUTPUT`
- `PERSONAL_MEMORY_BACKFILL_DAYS`
- `PERSONAL_MEMORY_MAX_ATTEMPTS`
- `PERSONAL_MEMORY_RETRY_DELAY`
- state / log 路径

这会导致父运行器扫描默认 Vault，而子脚本使用 env 文件指定的另一个 Vault。必须先加载 env 文件，再按“CLI 显式参数 > env 文件 > 进程环境 > 默认值”的明确优先级构建配置。增加端到端测试，不能只测试 `load_env_file()`。

### R2 缺失计划在同步之前计算

`Runner.run()` 进入锁之前就执行 `plan_run()`，随后才运行 `sync-raw`。如果本轮同步新增了昨天的原始记录，本轮 `daily-v2` 看不到它，要等下一次调度。这破坏了“同步 → 补日报”的单轮闭环。

必须：

1. 锁内先同步；
2. 同步成功后重新扫描 raw / daily 并生成最终计划；
3. 状态页和 `last-run.json` 使用同步后的计划；
4. 新增 fake sync 创建 raw 文件后，同一轮必须调用 daily 的测试。

### R3 `--dry-run` 仍然写日志和状态

真实执行：

```text
python3 scripts/local_incremental_runner.py run --dry-run
```

在尝试创建 `~/Library/Logs/personal-memory-incremental` 时失败。当前 dry-run 会读取真实目录并写日志 / `last-run.json`，与 README 的“不读真实 Vault、不调用 LLM”和通常的 dry-run 语义不一致。

修正要求：

- dry-run 可以只读扫描文件名以生成计划，但不得写 Vault、日志、state、lock 或调用任何子命令；
- README 改为准确描述“只读扫描目录，不读取正文、不调用外部 API、不写盘”；
- 增加只读目录下 dry-run 成功且零写入测试。

### R4 默认状态页路径错误

代码默认：

```text
AI/AI外置记忆/00-系统生成/运行状态.md
```

当前真实布局：

```text
AI/AI外置记忆/90-系统/运行状态/外置记忆运行状态.md
```

必须统一为真实布局，并增加默认路径断言。

### R5 超过回填窗口的缺失日报会永久遗留

当前默认只扫描最近 7 天；运行中断超过 7 天后，更早缺口永远不会被自动处理，只会留在状态页。请改为“所有早于今天的缺失日期都可进入待办队列，同时每轮限制实际生成天数”，避免无限调用也避免永久漏补。

建议语义：

- 昨天优先；
- 其余缺口按日期从新到旧或从旧到新确定一种稳定顺序；
- `PERSONAL_MEMORY_MAX_DAILY_DAYS_PER_RUN` 控制每轮最多生成天数；
- 状态中分别显示本轮选择和仍待处理日期。

### R6 子进程缺少超时边界

`subprocess.run()` 没有 timeout。某个 SSH 或 LLM 调用永久挂起时，LaunchAgent 会一直占锁，后续任务全部跳过。增加阶段级 timeout 配置、超时日志和相应测试；超时后仍遵循有限重试。

## 建议修复但不阻塞代码结构评审

- 对写入日志的 stderr 摘要执行敏感值脱敏，避免上游错误原样回显 Token；
- `status` 检查不应覆盖正在运行任务之外的最后成功状态；
- README 删除重复介绍段落；
- plist 验收命令应只把 XML 部分传给 `plutil`，不要把预览说明文字一起管道输入。

## WB-01R 验收要求

1. 保留原有 134 项测试全绿；
2. 新增覆盖 R1–R6 的测试；
3. 在受限、只读的 home 环境下 `--dry-run` 成功且零写入；
4. 提供更新后的 commit SHA 和逐项修复对应测试名；
5. 不安装 LaunchAgent、不调用真实 LLM、不改真实 Vault；
6. 主线复核通过后再做真实 Vault dry-run 和单次人工运行。

## 返修完成后的下一任务

WB-01R 通过后，优先领取 `WORKBUDDY_HANDOFF.md` 中的 **WB-02 图片附件 A07 可行性验证**。不要提前修改生产 MCP / Gateway API；先交付测试证据、接口差距和最小 contract。
