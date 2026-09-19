#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${PERSONAL_MEMORY_STACK_CONFIG:-/etc/personal-memory-stack.env}"
LOCK_FILE=/run/lock/personal-memory-stack.lock
XRAY_HTTP_PROXY="${XRAY_HTTP_PROXY:-http://127.0.0.1:10809}"
DRY_RUN="${PERSONAL_MEMORY_STACK_DRY_RUN:-0}"
ALLOW_NO_CLOUDFLARE="${PERSONAL_MEMORY_ALLOW_NO_CLOUDFLARE:-0}"

log(){ printf '\n========== %s ==========\n' "$*"; }
ok(){ printf '[✓] %s\n' "$*"; }
warn(){ printf '[!] %s\n' "$*"; }
die(){ printf '[✗] %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die '请使用 sudo/root 运行。'
command -v flock >/dev/null 2>&1 || die '缺少 flock（util-linux）。'
exec 9>"$LOCK_FILE"
flock -n 9 || die '已有一套 Personal Memory 部署正在运行。'

if [[ -f "$CONFIG_FILE" ]]; then
  [[ "$(stat -c '%a' "$CONFIG_FILE")" == 600 ]] || die "配置文件权限必须是 600：$CONFIG_FILE"
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
  set +a
  ok "已读取 root-only 配置：$CONFIG_FILE"
else
  warn "未找到可选配置：$CONFIG_FILE；需要密钥的阶段可能进入人工确认或保持待配置。"
fi

run(){
  if [[ "$DRY_RUN" == 1 ]]; then printf '[DRY-RUN]'; printf ' %q' "$@"; printf '\n'; else "$@"; fi
}

fetch_script(){
  local name="$1" github_url="$2" gitee_url="$3" target="$4"
  if curl -fsSL --connect-timeout 8 --max-time 30 "$github_url" -o "$target"; then
    ok "$name：从 GitHub 主仓获取入口"
  elif curl -fsSL --connect-timeout 8 --max-time 30 --proxy "$XRAY_HTTP_PROXY" "$github_url" -o "$target"; then
    ok "$name：通过 Xray 从 GitHub 主仓获取入口"
  elif curl -fsSL --connect-timeout 8 --max-time 30 "$gitee_url" -o "$target"; then
    warn "$name：GitHub 不可达，使用 Gitee 只读镜像入口"
  else
    die "$name：GitHub/Gitee 部署入口均无法获取。"
  fi
  chmod 0700 "$target"
}

install_optional_codex_auth(){
  local source="${CODEX_AUTH_SOURCE_FILE:-}"
  [[ -n "$source" ]] || return 0
  [[ -s "$source" ]] || die "CODEX_AUTH_SOURCE_FILE 不存在或为空：$source"
  if ! command -v jq >/dev/null 2>&1; then
    apt-get update -qq
    NEEDRESTART_MODE=a DEBIAN_FRONTEND=noninteractive apt-get install -y -qq jq >/dev/null
  fi
  jq -e '.tokens != null and .auth_mode != null' "$source" >/dev/null || die 'Codex auth.json 结构校验失败。'
  install -d -m 0700 /var/lib/hindsight/codex
  install -m 0600 "$source" /var/lib/hindsight/codex/auth.json
  ok '已安装 Hindsight 专用 Codex 凭据；未输出凭据内容。'
}

run_component(){
  local name="$1" github_url="$2" gitee_url="$3" tmp
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN
  fetch_script "$name" "$github_url" "$gitee_url" "$tmp"
  run bash "$tmp"
  rm -f "$tmp"
  trap - RETURN
}

main(){
  log 'Personal Memory 同机一条龙部署'
  install_optional_codex_auth

  log '1/5 Hindsight 基础设施'
  run_component memory-server-infra \
    'https://raw.githubusercontent.com/skyhigh13gdhz-png/memory-server-infra/main/bootstrap.sh' \
    'https://gitee.com/skyhigh13/memory-server-infra/raw/main/bootstrap.sh'

  log '2/5 Memory Gateway'
  run_component memory-gateway \
    'https://raw.githubusercontent.com/skyhigh13gdhz-png/memory-gateway/main/bootstrap.sh' \
    'https://gitee.com/skyhigh13/memory-gateway/raw/main/bootstrap.sh'

  log '3/5 Memory MCP'
  run_component memory-mcp \
    'https://raw.githubusercontent.com/skyhigh13gdhz-png/memory-mcp/main/bootstrap.sh' \
    'https://gitee.com/skyhigh13/memory-mcp/raw/main/bootstrap.sh'

  log '4/5 Cloudflare Tunnel'
  if run bash "$ROOT_DIR/scripts/40-cloudflared.sh"; then
    ok 'Cloudflare Tunnel 阶段完成'
  elif [[ "$ALLOW_NO_CLOUDFLARE" == 1 ]]; then
    warn '已显式允许无 Cloudflare 模式；仅保留本机链路。'
  else
    die 'Cloudflare Tunnel 未完成；配置 token 后重复运行本入口即可续跑。若只需本机链路，显式设置 PERSONAL_MEMORY_ALLOW_NO_CLOUDFLARE=1。'
  fi

  log '5/5 全链路健康检查'
  run bash "$ROOT_DIR/scripts/90-health-check.sh"
}

main "$@"
