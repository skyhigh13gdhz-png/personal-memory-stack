#!/usr/bin/env bash
set -Eeuo pipefail

LABEL="com.skyhighmonica.personal-memory-journal"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC_SCRIPT="$SCRIPT_DIR/sync_obsidian_vault.sh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/personal-memory-journal"
INTERVAL="${PERSONAL_MEMORY_SYNC_INTERVAL:-3600}"

[[ "$INTERVAL" =~ ^[0-9]+$ ]] && (( INTERVAL >= 300 )) || {
  echo '[✗] PERSONAL_MEMORY_SYNC_INTERVAL 必须是 >=300 的整数秒' >&2
  exit 2
}
[[ -x "$SYNC_SCRIPT" ]] || { echo "[✗] 同步脚本不可执行: $SYNC_SCRIPT" >&2; exit 2; }

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
python3 - "$PLIST" "$LABEL" "$SYNC_SCRIPT" "$LOG_DIR" "$INTERVAL" <<'PY'
import plistlib, sys
from pathlib import Path

path, label, script, logs, interval = sys.argv[1:]
payload = {
    "Label": label,
    "ProgramArguments": ["/bin/bash", script],
    "RunAtLoad": True,
    "StartInterval": int(interval),
    "StandardOutPath": str(Path(logs) / "stdout.log"),
    "StandardErrorPath": str(Path(logs) / "stderr.log"),
    "ProcessType": "Background",
}
Path(path).write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True))
PY
plutil -lint "$PLIST" >/dev/null

DOMAIN="gui/$(id -u)"
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"
launchctl kickstart -k "$DOMAIN/$LABEL"

echo "[✓] 已安装每 ${INTERVAL} 秒同步一次的 LaunchAgent: $LABEL"
echo "[✓] 配置: $PLIST"
echo "[✓] 日志: $LOG_DIR"
