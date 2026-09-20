#!/usr/bin/env bash
set -Eeuo pipefail

SERVER="${PERSONAL_MEMORY_SERVER:-ubuntu@106.53.204.254}"
SPEAKER="${PERSONAL_MEMORY_SPEAKER:-liangzai}"
VAULT_DIR="${PERSONAL_MEMORY_VAULT_DIR:-/Users/weizhenliang/obsidian空间}"
TARGET_REL="${PERSONAL_MEMORY_TARGET_REL:-AI/AI外置记忆/00-系统生成/原始记录/liangzai}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECTOR="$SCRIPT_DIR/project_markdown_journal.py"
TARGET="$VAULT_DIR/$TARGET_REL"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15)

[[ "$SPEAKER" =~ ^[a-z0-9_-]+$ ]] || { echo '[✗] speaker 只允许小写字母、数字、_、-' >&2; exit 2; }
[[ -d "$VAULT_DIR/.obsidian" ]] || { echo "[✗] 不是 Obsidian Vault: $VAULT_DIR" >&2; exit 2; }
[[ -f "$PROJECTOR" ]] || { echo "[✗] 缺少投影器: $PROJECTOR" >&2; exit 2; }
case "$TARGET" in
  "$VAULT_DIR"/*) ;;
  *) echo '[✗] 输出必须位于 Vault 内' >&2; exit 2 ;;
esac

LOCAL_STAGE="$(mktemp -d "${TMPDIR:-/tmp}/personal-memory-vault.XXXXXX")"
REMOTE_TMP=""
cleanup() {
  rm -rf -- "$LOCAL_STAGE"
  if [[ -n "$REMOTE_TMP" && "$REMOTE_TMP" == /tmp/personal-memory-journal.* ]]; then
    ssh "${SSH_OPTS[@]}" "$SERVER" "rm -rf -- '$REMOTE_TMP'" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "[→] 在服务器生成 speaker=$SPEAKER 的只读投影"
REMOTE_TMP="$(ssh "${SSH_OPTS[@]}" "$SERVER" 'mktemp -d /tmp/personal-memory-journal.XXXXXX')"
scp "${SSH_OPTS[@]}" "$PROJECTOR" "$SERVER:$REMOTE_TMP/project_markdown_journal.py" >/dev/null
ssh "${SSH_OPTS[@]}" "$SERVER" \
  "sudo -n bash -lc 'set -a; source /opt/src/memory-gateway/.env; python3 \"$REMOTE_TMP/project_markdown_journal.py\" --speaker \"$SPEAKER\" --output \"$REMOTE_TMP/output\"; chown -R ubuntu:ubuntu \"$REMOTE_TMP/output\"'"

echo '[→] 下载到本机隔离 staging 目录'
scp -r "${SSH_OPTS[@]}" "$SERVER:$REMOTE_TMP/output/." "$LOCAL_STAGE/" >/dev/null
python3 - "$LOCAL_STAGE/manifest.json" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
if data.get("schema_version") != 1 or not isinstance(data.get("documents"), list):
    raise SystemExit("invalid projection manifest")
print(f"[✓] manifest: {data['document_count']} documents / timezone={data['timezone']}")
PY

mkdir -p "$(dirname "$TARGET")"
BACKUP=""
if [[ -e "$TARGET" ]]; then
  if diff -qr "$TARGET" "$LOCAL_STAGE" >/dev/null; then
    echo "[✓] Obsidian 投影无变化，无需替换: $TARGET"
    exit 0
  fi
  BACKUP="${TARGET}.backup-$(date -u +%Y%m%dT%H%M%SZ)"
  [[ ! -e "$BACKUP" ]] || BACKUP="${BACKUP}-$$"
  mv "$TARGET" "$BACKUP"
fi
if ! mv "$LOCAL_STAGE" "$TARGET"; then
  [[ -z "$BACKUP" || -e "$TARGET" ]] || mv "$BACKUP" "$TARGET"
  exit 1
fi
LOCAL_STAGE="$(mktemp -d "${TMPDIR:-/tmp}/personal-memory-vault.cleanup.XXXXXX")"

echo "[✓] Obsidian 投影已更新: $TARGET"
[[ -z "$BACKUP" ]] || echo "[✓] 上一版已保留: $BACKUP"
