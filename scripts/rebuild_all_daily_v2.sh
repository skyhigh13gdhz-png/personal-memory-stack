#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MODE="${1:-preview}"
[[ $# -gt 0 ]] && shift

CONFIRM=0
DATE_FROM=""
DATE_TO=""
ENV_FILE="${PERSONAL_MEMORY_RUNNER_ENV_FILE:-$HOME/.config/personal-memory/incremental.env}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --confirm) CONFIRM=1 ;;
    --date-from=*) DATE_FROM="${1#*=}" ;;
    --date-to=*) DATE_TO="${1#*=}" ;;
    --env-file=*) ENV_FILE="${1#*=}" ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
  shift
done

if [[ "$MODE" != "preview" && "$MODE" != "run" ]]; then
  echo "用法: bash scripts/rebuild_all_daily_v2.sh [preview|run] [--confirm] [--date-from=YYYY-MM-DD] [--date-to=YYYY-MM-DD]" >&2
  exit 2
fi
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

VAULT_DIR="${PERSONAL_MEMORY_VAULT_DIR:-/Users/weizhenliang/obsidian空间}"
RAW_DIR="${PERSONAL_MEMORY_RAW_DIR:-$VAULT_DIR/AI/AI外置记忆/00-系统生成/原始记录/liangzai}"
DAILY_DIR="${PERSONAL_MEMORY_DAILY_DIR:-$VAULT_DIR/AI/AI外置记忆/01-日报}"

mapfile_cmd=(find "$RAW_DIR" -maxdepth 1 -type f -name '????-??-??.md' -print)
FIRST_FILE="$("${mapfile_cmd[@]}" | LC_ALL=C sort | head -1)"
LAST_FILE="$("${mapfile_cmd[@]}" | LC_ALL=C sort | tail -1)"
if [[ -z "$FIRST_FILE" || -z "$LAST_FILE" ]]; then
  echo "没有找到原始记录: $RAW_DIR" >&2
  exit 2
fi
DATE_FROM="${DATE_FROM:-$(basename "$FIRST_FILE" .md)}"
DATE_TO="${DATE_TO:-$(basename "$LAST_FILE" .md)}"

COMMAND=(python3 "$SCRIPT_DIR/sync_daily_v2.py"
  --raw-dir "$RAW_DIR"
  --output-dir "$DAILY_DIR"
  --date-from "$DATE_FROM"
  --date-to "$DATE_TO"
  --subjects "$REPO_DIR/config/subjects.json"
  --style "$REPO_DIR/config/daily-style.example.json"
  --replace-existing)

echo "[→] 日报重建范围: $DATE_FROM 至 $DATE_TO"
echo "[→] 原始记录: $RAW_DIR"
echo "[→] 正式日报: $DAILY_DIR"
if [[ "$MODE" == "preview" ]]; then
  "${COMMAND[@]}" --dry-run
  echo "[=] 仅预览。正式执行: bash scripts/rebuild_all_daily_v2.sh run --confirm"
  exit 0
fi
if [[ "$CONFIRM" != "1" ]]; then
  echo "全量重建会逐日调用已配置的 LLM，并仅用通过门禁的结果替换正式日报；请加 --confirm。" >&2
  exit 2
fi

WORK_ROOT="${PERSONAL_MEMORY_REBUILD_WORK_DIR:-$HOME/Library/Application Support/personal-memory-daily-rebuild}"
mkdir -p "$WORK_ROOT"
"${COMMAND[@]}" --work-dir "$WORK_ROOT"
