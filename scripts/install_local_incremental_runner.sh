#!/usr/bin/env bash
# Install, preview, inspect and remove the local incremental runner LaunchAgent.
#
#   bash scripts/install_local_incremental_runner.sh preview   # default: print only
#   bash scripts/install_local_incremental_runner.sh install --confirm
#   bash scripts/install_local_incremental_runner.sh status
#   bash scripts/install_local_incremental_runner.sh uninstall
#
# The generated plist stores paths only. Secrets stay in the separate env file
# and are injected into child processes by the runner itself.

set -Eeuo pipefail

LABEL="com.skyhighmonica.personal-memory-incremental"
RUNNER_LABEL="personal-memory-incremental"
ACTION="${1:-preview}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$SCRIPT_DIR/local_incremental_runner.py"
FREEZE_MARKER="$REPO_DIR/config/daily-v2.freeze"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/$RUNNER_LABEL"
STATE_DIR="$HOME/Library/Application Support/$RUNNER_LABEL"
DOMAIN="gui/$(id -u)"

INTERVAL="${PERSONAL_MEMORY_RUNNER_INTERVAL:-3600}"
ENV_FILE="${PERSONAL_MEMORY_RUNNER_ENV_FILE:-$HOME/.config/personal-memory/incremental.env}"
CONFIRM=0
# LaunchAgent runs with a minimal PATH, so pin an absolute interpreter and let
# callers override it when they need a newer Python.
PYTHON_BIN="${PERSONAL_MEMORY_PYTHON:-/usr/bin/python3}"

shift || true
for argument in "$@"; do
  case "$argument" in
    --confirm) CONFIRM=1 ;;
    --interval=*) INTERVAL="${argument#*=}" ;;
    --env-file=*) ENV_FILE="${argument#*=}" ;;
    *) echo "[✗] 未知参数: $argument" >&2; exit 2 ;;
  esac
done

[[ -f "$RUNNER" ]] || { echo "[✗] 缺少运行器: $RUNNER" >&2; exit 2; }
[[ "$INTERVAL" =~ ^[0-9]+$ ]] && (( INTERVAL >= 300 )) || {
  echo '[✗] PERSONAL_MEMORY_RUNNER_INTERVAL 必须是 >=300 的整数秒' >&2
  exit 2
}

emit_plist() {
  python3 - "$LABEL" "$PYTHON_BIN" "$RUNNER" "$ENV_FILE" "$LOG_DIR" "$STATE_DIR" "$INTERVAL" <<'PY'
import plistlib, sys
from pathlib import Path

label, python, runner, env_file, logs, state, interval = sys.argv[1:]
payload = {
    "Label": label,
    "ProgramArguments": [
        python, runner, "run",
        "--env-file", env_file,
        "--state-dir", state,
        "--log-file", str(Path(logs) / "runner.jsonl"),
    ],
    "RunAtLoad": True,
    "StartInterval": int(interval),
    "StandardOutPath": str(Path(logs) / "stdout.log"),
    "StandardErrorPath": str(Path(logs) / "stderr.log"),
    "ProcessType": "Background",
}
print(plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True).decode("utf-8"), end="")
PY
}

case "$ACTION" in
  preview)
    echo "[=] 仅预览，不写入 LaunchAgents，也不启动任何任务"
    echo "[=] plist 目标路径: $PLIST"
    echo "[=] 配置来源: $ENV_FILE"
    echo
    emit_plist
    echo
    echo "[→] 确认无误后执行: bash $0 install --confirm"
    ;;
  install)
    if [[ -f "$FREEZE_MARKER" ]]; then
      echo "Daily V2 已冻结，禁止重新安装旧增量日报调度器。请阅读 DAILY_PRODUCT_RESET.md。" >&2
      exit 3
    fi
    if (( CONFIRM == 0 )); then
      echo '[✗] 真实安装会注册本机定时任务，必须显式加 --confirm' >&2
      echo "[→] 先运行: bash $0 preview" >&2
      exit 2
    fi
    [[ -f "$ENV_FILE" ]] || { echo "[✗] 配置环境文件不存在: $ENV_FILE" >&2; exit 2; }
    mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR" "$STATE_DIR"
    emit_plist > "$PLIST"
    plutil -lint "$PLIST" >/dev/null
    launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    launchctl enable "$DOMAIN/$LABEL"
    launchctl kickstart -k "$DOMAIN/$LABEL"
    echo "[✓] 已安装每 ${INTERVAL} 秒运行一次的 LaunchAgent: $LABEL"
    echo "[✓] 配置: $PLIST"
    echo "[✓] 日志: $LOG_DIR"
    ;;
  status)
    echo "[=] LaunchAgent: $LABEL"
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      echo "[✓] 已注册"
      launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "state|last exit|runs" || true
    else
      echo "[-] 未注册"
    fi
    echo
    "$PYTHON_BIN" "$RUNNER" status --state-dir "$STATE_DIR" || true
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    [[ -f "$PLIST" ]] && rm -f "$PLIST"
    echo "[✓] 已卸载 LaunchAgent: $LABEL"
    echo "[=] 日志和状态保留在: $LOG_DIR / $STATE_DIR"
    ;;
  *)
    echo "[✗] 未知子命令: $ACTION" >&2
    echo "用法: bash $0 {preview|install|status|uninstall} [--confirm] [--interval=N] [--env-file=PATH]" >&2
    exit 2
    ;;
esac
