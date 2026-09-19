#!/usr/bin/env bash
set -Eeuo pipefail

XRAY_HTTP_PROXY="${XRAY_HTTP_PROXY:-http://127.0.0.1:10809}"
TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"
TOKEN_FILE="${CLOUDFLARE_TUNNEL_TOKEN_FILE:-}"
REINSTALL="${CLOUDFLARE_REINSTALL_SERVICE:-0}"

ok(){ printf '[✓] %s\n' "$*"; }
warn(){ printf '[!] %s\n' "$*"; }
die(){ printf '[✗] %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die '请使用 sudo/root 运行。'

fetch(){
  local url="$1" target="$2"
  curl -fsSL --connect-timeout 8 --max-time 60 "$url" -o "$target" ||
    curl -fsSL --connect-timeout 8 --max-time 60 --proxy "$XRAY_HTTP_PROXY" "$url" -o "$target"
}

install_cloudflared(){
  command -v cloudflared >/dev/null 2>&1 && { ok "cloudflared 已安装：$(cloudflared --version | head -n1)"; return; }
  local key=/usr/share/keyrings/cloudflare-main.gpg
  install -d -m 0755 /usr/share/keyrings
  fetch 'https://pkg.cloudflare.com/cloudflare-main.gpg' "$key" || die 'Cloudflare APT 签名密钥下载失败。'
  chmod 0644 "$key"
  printf '%s\n' 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' > /etc/apt/sources.list.d/cloudflared.list
  if ! apt-get update -qq; then
    HTTPS_PROXY="$XRAY_HTTP_PROXY" HTTP_PROXY="$XRAY_HTTP_PROXY" apt-get update -qq || die 'Cloudflare APT 源更新失败。'
  fi
  NEEDRESTART_MODE=a DEBIAN_FRONTEND=noninteractive apt-get install -y -qq cloudflared >/dev/null || die 'cloudflared 安装失败。'
  ok "cloudflared 已安装：$(cloudflared --version | head -n1)"
}

install_cloudflared

if [[ -n "$TOKEN_FILE" ]]; then
  [[ -r "$TOKEN_FILE" ]] || die "Tunnel token 文件不可读：$TOKEN_FILE"
  [[ "$(stat -c '%a' "$TOKEN_FILE")" == 600 ]] || die "Tunnel token 文件权限必须是 600：$TOKEN_FILE"
  TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
fi

if systemctl is-active --quiet cloudflared.service && [[ "$REINSTALL" != 1 ]]; then
  ok 'cloudflared.service 已运行；保留现有 connector 配置。'
  exit 0
fi

if [[ -z "$TOKEN" ]]; then
  warn 'cloudflared 已安装，但缺少 remotely-managed Tunnel token。'
  warn '请将 token 写入权限 600 的文件，并在 /etc/personal-memory-stack.env 配置 CLOUDFLARE_TUNNEL_TOKEN_FILE。'
  exit 2
fi

if systemctl list-unit-files cloudflared.service >/dev/null 2>&1; then
  cloudflared service uninstall >/dev/null 2>&1 || true
fi
cloudflared service install "$TOKEN" >/dev/null
systemctl enable --now cloudflared.service >/dev/null
systemctl restart cloudflared.service
sleep 2
systemctl is-active --quiet cloudflared.service || {
  journalctl -u cloudflared.service -n 80 --no-pager || true
  die 'cloudflared 服务启动失败。'
}
ok 'Cloudflare Tunnel connector 已安装、启动并设为开机自动恢复。'
