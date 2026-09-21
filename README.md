# Personal Memory Stack

V3 产品设计、停工线和质量门槛见 [DESIGN_V3.md](DESIGN_V3.md)；真实样本的 Gate A 结论见 [GATE_A_REVIEW.md](GATE_A_REVIEW.md)。
候选 Claim 的提取、逐字验证、风险分流、人工确认和额度控制见 [CLAIM_PIPELINE.md](CLAIM_PIPELINE.md)。
真实样本证明自由 Claim 抽取会遗漏事实；当前主线改为 Evidence Unit 全覆盖，结果见 [GATE_B_RESULTS_2026-09-20.md](GATE_B_RESULTS_2026-09-20.md)。
日报的总分结构、语言风格、事实/分析边界和人类/审计双视图规范见 [DAILY_VIEW_V2_SPEC.md](DAILY_VIEW_V2_SPEC.md)。

Gate A/B 评审工具：

```bash
python3 scripts/validate_golden_set.py tests/fixtures/golden-v1.json
python3 scripts/render_daily_v2_preview.py tests/fixtures/golden-v1.json \
  --date 2026-01-01 --output /tmp/2026-01-01.md
python3 scripts/render_subject_preview.py tests/fixtures/golden-v1.json \
  --subject project:memory-system --output /tmp/memory-system.md
```

`local-evaluation/` 专用于本机真实记录评审，已被 Git 忽略；禁止把个人日记、原文引用或本机绝对路径改放到可提交 fixture。

这是同一台 Ubuntu 服务器的一条龙部署编排器。GitHub 仓库是该编排层的唯一可写源：[skyhigh13gdhz-png/personal-memory-stack](https://github.com/skyhigh13gdhz-png/personal-memory-stack)。

当前架构、V2.1 候选设计和决策门见 [ARCHITECTURE.md](ARCHITECTURE.md)；Hindsight 实机审计步骤见 [HINDSIGHT_AUDIT.md](HINDSIGHT_AUDIT.md)；首轮审计结果见 [AUDIT_RESULTS_2026-09-19.md](AUDIT_RESULTS_2026-09-19.md)；Document API 实施记录见 [IMPLEMENTATION_LOG_2026-09-20.md](IMPLEMENTATION_LOG_2026-09-20.md)；历史日记导入结果见 [IMPORT_LOG_2026-09-20.md](IMPORT_LOG_2026-09-20.md)；服务器已完成验收数据见 [VALIDATION.md](VALIDATION.md)。

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
- 只有明确的事件时刻才显示 `HH:MM`；未声明时间精度的午夜值默认视为日期锚点，真正发生在 00:00 的记录需使用 metadata `journal_time_precision=minute`；写入时间回退也不会冒充事件时间；
- 每条记录保留 Document ID 和原文 SHA-256，原文置于动态 Markdown fence 内；
- 默认拒绝覆盖已有输出；显式传 `--replace-output` 时，旧投影先改名为带 UTC 时间戳的 backup，不直接删除。

macOS 上的自动 Obsidian 接入使用：

```bash
bash scripts/sync_obsidian_vault.sh
bash scripts/install_macos_obsidian_sync.sh
```

默认从 `ubuntu@106.53.204.254` 投影 `speaker=liangzai`，每小时更新当前 Vault 的 `AI/AI外置记忆/00-系统生成/原始记录/liangzai`。Gateway Token 始终留在服务器；本机只通过 SSH 取回生成的 Markdown。可通过 `PERSONAL_MEMORY_SERVER`、`PERSONAL_MEMORY_SPEAKER`、`PERSONAL_MEMORY_VAULT_DIR`、`PERSONAL_MEMORY_TARGET_REL` 和 `PERSONAL_MEMORY_SYNC_INTERVAL` 覆盖默认值。

同步时保留目标目录本身，仅增量更新其内部文件，避免 Obsidian 因目录整体替换而丢失文件监听。旧投影仍会先完整备份到相邻的隐藏 `.history` 目录。

## 历史 Markdown 导入

`scripts/import_markdown_history.py` 将以 `YYYY-MM-DD.md` 命名的历史日记通过 Gateway 正式 Retain 链路导入；过长日记可按已有章节拆成 `YYYY-MM-DD--slug.md`，仍归入同一天。它保留原文，使用稳定 Document ID，写入日期精度和来源 metadata，并生成可续跑 manifest；可按日期跳过已经存在的记录，避免把曾经通过 ChatGPT 写入的同日内容重复导入。

当前由 Codex 协助维护和导入的个人记录统一使用稳定身份 `speaker=liangzai`；导入器也以此为默认值，不根据正文内容猜测身份。

```bash
python3 scripts/import_markdown_history.py \
  --input-dir /path/to/history \
  --speaker liangzai \
  --manifest /tmp/history-import.json \
  --skip-existing-dates \
  --dry-run
```

正式导入时移除 `--dry-run`。生产环境应在服务器加载 `/opt/src/memory-gateway/.env` 后运行，API Token 不应复制到本机命令历史。

中国大陆服务器的代理分两层：`proxy_on` 只影响当前 shell 的 `curl/git/pip`；Docker 镜像由 Docker daemon 自己的代理配置负责。首次 Hindsight 拉取包含大镜像层且解压后占用数 GB，后续重复安装命中本地缓存会明显更快。

## Hindsight 多 LLM 路由

当前 Retain、Reflect 和 Consolidation 均走智谱 `glm-4.5-air`，Embedding 留在本地；Mental Model Refresh 仍继承全局 Codex 路由。实现位于 `memory-server-infra/scripts/09-configure-llm-routing.sh`，总编排仓只记录架构和调用边界，不保存任何模型凭据。智谱路由不启用跨 Provider fallback，便于准确衡量成功率、时延、质量和实际额度消耗。

Recall 的 `max_results` 只限制本次返回的 Top-K 数量，不影响已存数据。完整按日期的分析应使用 Document Date Range，原始 Obsidian Markdown 同步使用 `bash scripts/sync_obsidian_vault.sh`，该过程不调用 LLM。`daily-v1` 单日生成器已实现；周报和月报尚未实现。

## daily-v1 日报

`scripts/build_daily_v1.py` 已实现单日日报的固定流程：

1. 通过 Gateway Document Date Range 读取当日全部原文；
2. 计算排序无关的 source SHA-256；
3. 要求 LLM 只返回 `daily-v1` 固定 JSON Schema；
4. 校验 Schema 后由程序确定性渲染 Markdown；
5. 原文、模板版本未变时跳过重新生成。

在服务器上运行：

```bash
set -a
source /opt/src/memory-gateway/.env
source /opt/memory-server-infra/hindsight/.env
set +a
python3 scripts/build_daily_v1.py \
  --date 2026-09-17 \
  --speaker liangzai \
  --output /path/to/daily/2026-09-17.md
```

默认复用 Hindsight Retain 的智谱 Key、Base URL 和 Model；可以用 `DAILY_LLM_API_KEY`、`DAILY_LLM_BASE_URL`、`DAILY_LLM_MODEL` 单独覆盖。运行时会把当日原始记录发送给所配置的 LLM Provider，必须先确认该数据处理边界。生成日报默认不 Retain 回记忆库。

## Evidence Unit 日回顾主线

`daily-v1` 保留为技术原型。当前主线先由程序把完整 Documents 切成稳定 Evidence Units，再让分类器逐单元标注阅读形态；模型漏标、错标或调用失败时，单元以原文回退，不能从日报输入中消失。

```bash
# 1. 确定性切分，不调用 LLM
python3 scripts/build_evidence_units.py local-evaluation/input.json \
  --output local-evaluation/evidence-units.json

# 2. 零 LLM 完整性基线：全部保留为未分类原文
python3 scripts/classify_evidence_units.py baseline \
  local-evaluation/evidence-units.json \
  --output local-evaluation/classified-baseline.json

# 3. 确定性渲染人类可读日报预览
python3 scripts/render_daily_from_units.py \
  local-evaluation/classified-baseline.json --date 2026-09-20 \
  --output local-evaluation/2026-09-20-unit-preview.md
```

`extract` 子命令会把 Evidence Units 发送给配置的 LLM；处理个人数据前必须取得明确授权。`prepare --response` 可离线验证已保存响应。分类结果只改变栏目、摘要、显示范围和 Subject 候选关联；原文、字符区间、Document ID 与未分类回退始终保留。当前输出仍是私有评审预览，不自动写入 Hindsight 或正式 Obsidian。

若 Provider 只把一个不透明 `unit_id` 抄错一个字符，校验器仅在候选唯一时安全对齐并记录修复；可用 `reconcile` 对已有分类包离线重算，不再次调用模型：

```bash
python3 scripts/classify_evidence_units.py reconcile \
  local-evaluation/classified.json --output local-evaluation/classified-reconciled.json
```

日报 V2 编辑包通过独立 Schema 控制具体项目、子主题、条目标签、个人语气和分析状态；渲染器强制检查当日单元100%有去向、跨 facet 重复显式声明、推断包含不确定性：

```bash
python3 scripts/render_daily_v2_editorial.py local-evaluation/daily-v2-editorial.json \
  --classified local-evaluation/classified.json \
  --output local-evaluation/daily-v2.md
```

`scripts/daily_v2_pipeline.py` 提供离线 `prepare` 和需明确数据授权的 `extract`。Provider 请求使用 `u01` 等短别名，返回后再映射为稳定 Evidence Unit ID；风格文件、模型、Prompt 版本和输入单元共同进入缓存哈希，无变化时不重复调用。示例风格配置见 `config/daily-style.example.json`。

`scripts/score_daily_v2.py` 对证据覆盖、固定信息架构、事实/分析边界、语言风格和可读性做 100 分质量检查；低于 85 分、违反结构门禁或命中禁用书面词的结果不允许由 pipeline 写出。评分是交付门禁，不替代人工阅读验收。

`scripts/sync_daily_v2.py` 是日报增量入口：从已投影的原始日记识别缺失日期，依次执行 Evidence Unit 切分、智谱分类、Daily V2 编排和质量门禁，只有通过的结果才会原子写入 `01-日报`。默认保留已存在日报；失败日期保留中间产物供排查，不污染正式 Vault。该命令会将指定日期的个人记录发送给已配置的 LLM Provider，应由已明确授权的定时任务或人工命令调用。

持续脉络先走零 LLM 候选层：`scripts/build_continuity_candidates.py` 只汇集与已确认 Subject 明确关联的 Evidence Units，`scripts/render_continuity_candidate_review.py` 生成待勾选评审页。候选默认 `pending` 且禁止更新当前状态；完整设计见 [CONTINUITY_VIEW_V1_SPEC.md](CONTINUITY_VIEW_V1_SPEC.md)。

候选进入长期视图前还必须经过 `scripts/review_continuity_candidates.py`：每个 promoted Claim 需要逐字 evidence facet，并明确标为进展、里程碑、决策、承诺、状态或指标。`scripts/render_continuity_view_v1.py` 可把通过校验的新 Claim 与历史 `golden-v1` 合并成阅读预览，但不会自动填写“当前状态”。

长期记忆状态层由 `scripts/validate_subject_state.py` 校验 Direct Fact、Derived State、Hypothesis、证据跨度、状态覆盖和分级审核策略；`scripts/render_memory_subject.py` 先支持 project/system 类型的 Living Memory Object。新状态规范见 [MEMORY_SUBJECT_STATE_SPEC.md](MEMORY_SUBJECT_STATE_SPEC.md)。

Vault 布局不再硬编码在模板里。`config/memory-layout.json` 分别配置模板目录、类型路由、导航集合和父子嵌套，`config/subjects.json` 保存当前确认的最小对象集合；`scripts/memory_layout.py` 支持 `validate → plan → apply → rollback`，并可在投影后登记 manifest。迁移只处理 manifest 标记为 managed 且哈希未变化的系统文件，目标冲突、外部编辑或越界路径都会拒绝执行。

目录配置、迁移命令和“何时改配置/何时改代码”的边界见 [MEMORY_LAYOUT.md](MEMORY_LAYOUT.md)。

`scripts/render_subject_registry.py` 将机器配置生成人可读的对象登记表，用于在正式投影或迁移之前检查分类、模板、从属关系和目标路径。

所有面向 Obsidian 阅读的输出遵循 [HUMAN_VIEW_CONTRACT.md](HUMAN_VIEW_CONTRACT.md)：默认不显示机器 ID、哈希、模板版本和证据索引，审计信息进入隐藏注释或独立产物。

长期对象由 Profile、State、Timeline 三层组成，类型化字段及更新边界见 [SUBJECT_PROFILE_SPEC.md](SUBJECT_PROFILE_SPEC.md)；当前推进顺序与完成状态见 [ROADMAP.md](ROADMAP.md)。

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
