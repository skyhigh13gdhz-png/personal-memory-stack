#!/usr/bin/env bash
set -Eeuo pipefail

PUBLIC_HOST="${MEMORY_MCP_PUBLIC_HOST:-memory.skyhighmonica.fyi}"
failures=0

ok(){ printf '[✓] %s\n' "$*"; }
bad(){ printf '[✗] %s\n' "$*" >&2; failures=$((failures+1)); }
check_service(){ if systemctl is-active --quiet "$1"; then ok "$1：active"; else bad "$1：未运行"; fi; }
check_url(){ if curl -fsS --max-time "$2" "$1" >/dev/null; then ok "$3：$1"; else bad "$3：不可访问 ($1)"; fi; }
check_public_mcp(){
  local url="$1" code
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$url" || true)"
  case "$code" in
    2??|3??|400|401|403|405|406|415|422) ok "公网 MCP 已到达源站：$url (HTTP $code)" ;;
    *) bad "公网 MCP 未打通：$url (HTTP ${code:-000})" ;;
  esac
}

check_service xray
check_service docker
check_service memory-gateway
check_service memory-mcp
check_url http://127.0.0.1:8888/docs 10 Hindsight
check_url http://127.0.0.1:8787/health 10 Gateway
if command -v memory-mcp >/dev/null 2>&1 && memory-mcp health >/dev/null; then
  ok 'MCP：本机健康检查通过'
else
  bad 'MCP：本机健康检查失败'
fi

if systemctl is-active --quiet cloudflared.service; then
  ok 'cloudflared.service：active'
  check_public_mcp "https://${PUBLIC_HOST}/mcp"
else
  bad 'Cloudflare Tunnel：未运行'
fi

(( failures == 0 )) || exit 1
printf '\n[✓] Personal Memory 已部署到当前可配置范围。\n'
