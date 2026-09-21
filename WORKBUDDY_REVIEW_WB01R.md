# WB-01R Codex 第二轮复核

结论：`a1ff246` 已正确修复第一轮 R1–R6，独立执行 `python3 -m unittest discover -s tests -v` 得到 `Ran 157 tests / OK`；但真实无人值守运行仍有 4 个阻塞项，暂不合并、暂不安装 LaunchAgent。

## 已确认通过

- env 文件能配置运行器自身，优先级符合交接说明；
- 原始投影同步后重新规划，同轮可生成新出现的缺失日报；
- dry-run 不创建日志、状态和锁文件；
- 默认 Vault 的 raw、daily、status 路径与当前真实目录一致；
- 历史缺口进入有界队列，昨天优先，旧缺口不会永久丢失；
- 单阶段超时进入有界重试；
- 真实 Vault 目录只做了路径核对，没有读取正文、调用 LLM 或写入。

## 必须返修

### R7：CLI 路径没有传给同步子脚本（阻塞）

`config_from_args()` 会让运行器按 `--vault-dir` / `--raw-dir` 扫描，但 `Runner.child_env()` 没有把解析后的 Vault 和目标路径注入子进程。`sync_obsidian_vault.sh` 只读取 `PERSONAL_MEMORY_VAULT_DIR` / `PERSONAL_MEMORY_TARGET_REL`，因此 CLI 示例可能出现“同步写默认 Vault，运行器扫描另一个 Vault”。

最小复现：清空相关进程环境后传 `--vault-dir /tmp/explicit-vault`，运行器的 `raw_dir` 指向 `/tmp/explicit-vault/...`，但 child env 中 `PERSONAL_MEMORY_VAULT_DIR=None`。

验收要求：

- 建立单一解析后的 Vault/路径配置，并明确注入同步子进程；
- CLI > env 文件 > 进程环境 > 默认值的结果必须同时被父进程和三个子阶段使用；
- 增加 CLI `--vault-dir`、`--raw-dir` 覆盖时的端到端测试，不能只测 env 文件。

### R8：锁竞争实例不应覆盖共享状态（阻塞）

`Runner.run()` 捕获 `LockUnavailable` 后调用 `finish()`，会在主实例仍运行时写同一个 `last-run.json`。这会暂时把真实运行状态覆盖成 `skipped`，还可能与主实例的非原子 `write_text()` 并发，造成状态文件损坏。

验收要求：

- 锁竞争实例只追加结构化日志并退出，不写共享 `last-run.json`；
- `last-run.json` 使用同目录临时文件 + `os.replace()` 原子发布；
- 测试先写入一个既有状态，再持锁启动第二实例，断言状态文件字节完全不变。

### R9：阶段超时必须终止整个进程组（阻塞）

当前 `subprocess.run(..., timeout=...)` 只保证直接子进程被杀。实际 `sync-raw` 是 Bash，再启动 `ssh` / `scp`；只杀 Bash 可能留下网络子进程。后续重试可能与遗留进程并行，违背“超时释放锁并安全重试”的目标。

验收要求：

- POSIX 下为阶段创建独立 session/process group；
- 超时时先终止整个进程组，短暂等待后强杀，完整回收输出；
- 测试使用“父进程再派生长睡眠子进程”的命令，超时后断言父子均不存在。

### R10：成功输出也必须脱敏（阻塞）

失败尾行经过 `redact()`，但成功分支逐行 `emit(completed.stdout)` 没有脱敏。LaunchAgent 会把这些内容写入 `stdout.log`；只要子脚本意外打印凭据，就会落盘。

验收要求：

- 成功 stdout、失败 stdout/stderr、异常 detail、持久化 JSON 和 console 统一经过同一脱敏器；
- 同时收集 env 文件与实际传给子进程的敏感环境变量值；
- 增加“成功子进程打印 token”测试，断言 console、JSONL、`last-run.json` 均不含明文。

## 建议项（不阻塞本轮）

- 为 `max_attempts >= 1`、`max_daily_days_per_run >= 1`、`retry_delay >= 0`、`stage_timeout > 0` 增加配置校验，避免异常值进入模糊失败路径。
- 超时留下的 Daily V2 工作目录可以继续复用缓存，但状态页应明确显示该阶段超时，而非只显示最终 `failed`。

## 下一次交付要求

- 保留 `94d6f28` 和 `a1ff246`，在其后追加返修 commit，不重写历史；
- 提供 R7–R10 对应测试、最小复现和风险说明；
- 全量测试必须继续通过；
- 不安装 LaunchAgent、不调用真实 LLM、不修改真实 Vault。
