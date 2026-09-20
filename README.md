# Personal Memory Stack

这是同一台 Ubuntu 服务器的一条龙部署编排器。GitHub 仓库是该编排层的唯一可写源：[skyhigh13gdhz-png/personal-memory-stack](https://github.com/skyhigh13gdhz-png/personal-memory-stack)。

当前架构、V2.1 候选设计和决策门见 [ARCHITECTURE.md](ARCHITECTURE.md)；Hindsight 实机审计步骤见 [HINDSIGHT_AUDIT.md](HINDSIGHT_AUDIT.md)；首轮审计结果见 [AUDIT_RESULTS_2026-09-19.md](AUDIT_RESULTS_2026-09-19.md)；Document API 实施记录见 [IMPLEMENTATION_LOG_2026-09-20.md](IMPLEMENTATION_LOG_2026-09-20.md)；服务器已完成验收数据见 [VALIDATION.md](VALIDATION.md)。

它不复制四个组件仓的实现，只按依赖顺序调用各仓正式 `bootstrap.sh`：

```text
memory-server-infra  → Hindsight / Docker / Xray
memory-gateway       → 127.0.0.1:8787
memory-mcp           → 127.0.0.1:8000/mcp
Cloudflare Tunnel    → 公网 hostname → 127.0.0.1:8000
```

## 为什么 Cloudflare 放在总编排器

Cloudflare Tunnel 是 MCP 的公网发布层，不属于 Hindsight、Gateway 或 MCP 的业务实现。放进任一组件仓都会破坏边界；放在总编排器可以统一管理“安装顺序、敏感 token、服务状态和公网验收”。

这里采用 Cloudflare 官方推荐的 remotely-managed Tunnel：Dashboard/API 保存 ingress 配置，服务器仅用 Tunnel token 安装 connector。官方安装方式是 `cloudflared service install <TOKEN>`。

## 配置

```bash
sudo install -m 0600 config.env.example /etc/personal-memory-stack.env
sudo mkdir -p -m 0700 /root/.secrets
sudo install -m 0600 /path/to/tunnel-token /root/.secrets/personal-memory-tunnel.token
```

Cloudflare Dashboard 的 Public Hostname 必须配置：

```text
Hostname: memory.skyhighmonica.fyi
Service:  http://127.0.0.1:8000
Path:     留空
```

给 ChatGPT/MCP Client 的地址才是：

```text
https://memory.skyhighmonica.fyi/mcp
```

## 一键运行

```bash
git clone https://github.com/skyhigh13gdhz-png/personal-memory-stack.git
cd personal-memory-stack
sudo bash bootstrap.sh
```

重复运行会复用已完成步骤。用 `flock` 防止两套部署同时执行；各组件仍由各自仓库负责安装、升级和 smoke test。

Cloudflare 默认是完整部署的必需阶段：缺 token 或公网验收失败时，总脚本返回失败，不会把“只有本机链路”误报为完成。仅调试本机链路时可显式设置 `PERSONAL_MEMORY_ALLOW_NO_CLOUDFLARE=1`。

## Markdown Journal 最小投影

`scripts/project_markdown_journal.py` 通过 Gateway Document API 按 speaker 读取原文，生成只读、可重建的按日 Markdown：

```bash
GATEWAY_API_TOKEN='...' python3 scripts/project_markdown_journal.py \
  --speaker monica \
  --output /path/to/Personal-Vault/00-原始记录
```

- 优先以 `retain_params.event_date` 归日，缺失时回退到 `created_at`，仍缺失则进入 `_undated.md`；
- 只有明确的事件时刻才显示 `HH:MM`；仅知道日期时使用 metadata `journal_time_precision=date`，写入时间回退也不会冒充事件时间；
- 每条记录保留 Document ID 和原文 SHA-256，原文置于动态 Markdown fence 内；
- 默认拒绝覆盖已有输出；显式传 `--replace-output` 时，旧投影先改名为带 UTC 时间戳的 backup，不直接删除。

macOS 上的自动 Obsidian 接入使用：

```bash
bash scripts/sync_obsidian_vault.sh
bash scripts/install_macos_obsidian_sync.sh
```

默认从 `ubuntu@106.53.204.254` 投影 `speaker=liangzai`，每小时更新当前 Vault 的 `AI/AI外置记忆/00-系统生成/原始记录/liangzai`。Gateway Token 始终留在服务器；本机只通过 SSH 取回生成的 Markdown。可通过 `PERSONAL_MEMORY_SERVER`、`PERSONAL_MEMORY_SPEAKER`、`PERSONAL_MEMORY_VAULT_DIR`、`PERSONAL_MEMORY_TARGET_REL` 和 `PERSONAL_MEMORY_SYNC_INTERVAL` 覆盖默认值。

中国大陆服务器的代理分两层：`proxy_on` 只影响当前 shell 的 `curl/git/pip`；Docker 镜像由 Docker daemon 自己的代理配置负责。首次 Hindsight 拉取包含大镜像层且解压后占用数 GB，后续重复安装命中本地缓存会明显更快。

## 本地无副作用检查

```bash
sudo PERSONAL_MEMORY_STACK_DRY_RUN=1 bash bootstrap.sh
bash -n bootstrap.sh scripts/*.sh
```

## 安全边界

- Codex OAuth、Gateway Token、Cloudflare Tunnel token 不进入本目录或 Git。
- `/etc/personal-memory-stack.env` 和 token 文件必须是 `0600`。
- Hindsight、Gateway、MCP 只在服务器本地端口工作；公网只暴露 Cloudflare Tunnel。
- Tunnel token 持有者可以运行该 Tunnel connector；泄漏后应立即在 Cloudflare 侧轮换。
