#!/usr/bin/env python3
"""Import dated Markdown files through Memory Gateway with a resumable manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DATE_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:--([a-z0-9_-]+))?\.md$")
AI_ANNOTATION = re.compile(r"^#{1,6}\s*(GPT|AI)\s*(注解|观察|分析)", re.MULTILINE | re.IGNORECASE)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def request_json(url: str, token: str, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", errors="replace")
        raise RuntimeError(f"Gateway HTTP {exc.code}: {detail}") from exc


def list_documents(base: str, token: str, speaker: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode({"speaker": speaker, "limit": 1000, "offset": offset})
        page = request_json(f"{base}/v1/documents?{query}", token).get("data") or {}
        items = page.get("items") or []
        result.extend(items)
        if not items or len(result) >= int(page.get("total", len(result))):
            return result
        offset += len(items)


def get_document(base: str, token: str, speaker: str, document_id: str) -> dict[str, Any]:
    quoted = urllib.parse.quote(document_id, safe="")
    query = urllib.parse.urlencode({"speaker": speaker})
    return request_json(f"{base}/v1/documents/{quoted}?{query}", token).get("data") or {}


def local_day(document: dict[str, Any], zone: ZoneInfo) -> str | None:
    value = (document.get("retain_params") or {}).get("event_date")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(zone).date().isoformat()
    except ValueError:
        return None


def read_candidates(input_dir: Path, speaker: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.md")):
        match = DATE_FILE.match(path.name)
        if not match:
            continue
        day = match.group(1)
        slug = match.group(2)
        datetime.strptime(day, "%Y-%m-%d")
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        digest = sha256(content)
        candidates.append({
            "path": str(path),
            "name": path.name,
            "day": day,
            "content": content,
            "sha256": digest,
            "document_id": f"obsidian-daily-{speaker}-{day}" + (f"--{slug}" if slug else ""),
            "contains_ai_annotation": bool(AI_ANNOTATION.search(content)),
        })
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--speaker", default="liangzai", help="稳定讲述者 ID，默认 liangzai")
    parser.add_argument("--gateway-base", default="http://127.0.0.1:8787")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--token-env", default="GATEWAY_API_TOKEN")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-existing-dates", action="store_true")
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()

    if not re.fullmatch(r"[a-z0-9_-]+", args.speaker):
        raise SystemExit("speaker 只允许小写字母、数字、_、-")
    token = os.environ.get(args.token_env, "")
    if not token:
        raise SystemExit(f"缺少环境变量 {args.token_env}")
    if not args.input_dir.is_dir():
        raise SystemExit(f"输入目录不存在：{args.input_dir}")

    zone = ZoneInfo(args.timezone)
    existing = list_documents(args.gateway_base, token, args.speaker)
    existing_days: dict[str, list[str]] = {}
    existing_hashes: dict[str, str] = {}
    existing_ids: set[str] = set()
    for item in existing:
        document_id = str(item.get("id") or item.get("document_id") or "")
        if not document_id:
            continue
        existing_ids.add(document_id)
        document = get_document(args.gateway_base, token, args.speaker, document_id)
        text = document.get("original_text")
        if isinstance(text, str):
            existing_hashes[sha256(text.strip())] = document_id
        day = local_day(document, zone)
        if day:
            existing_days.setdefault(day, []).append(document_id)

    report: dict[str, Any] = {
        "schema_version": 1,
        "mode": "dry-run" if args.dry_run else "import",
        "speaker": args.speaker,
        "input_dir": str(args.input_dir),
        "generated_at": datetime.now().astimezone().isoformat(),
        "existing_document_count": len(existing_ids),
        "items": [],
    }
    candidates = read_candidates(args.input_dir, args.speaker)
    failures = 0
    for candidate in candidates:
        entry = {key: value for key, value in candidate.items() if key != "content"}
        digest = candidate["sha256"]
        day = candidate["day"]
        document_id = candidate["document_id"]
        if digest in existing_hashes:
            entry.update(status="skip_exact_duplicate", existing_document_id=existing_hashes[digest])
        elif args.skip_existing_dates and day in existing_days:
            entry.update(status="skip_existing_date", existing_document_ids=existing_days[day])
        elif document_id in existing_ids:
            entry.update(status="skip_existing_document_id")
        elif args.dry_run:
            entry.update(status="would_import")
        else:
            payload = {
                "content": candidate["content"],
                "speaker": args.speaker,
                "client_id": "obsidian-history-importer",
                "document_id": document_id,
                "timestamp": f"{day}T12:00:00+08:00",
                "metadata": {
                    "source": "obsidian_daily",
                    "import_kind": "historical_daily",
                    "source_filename": candidate["name"],
                    "source_sha256": digest,
                    "journal_time_precision": "date",
                    "contains_ai_annotation": str(candidate["contains_ai_annotation"]).lower(),
                },
            }
            try:
                result = request_json(f"{args.gateway_base}/v1/memories/retain", token, "POST", payload)
                data = result.get("data") or {}
                entry.update(status="imported", gateway_ok=result.get("ok", False), result=data)
                existing_ids.add(document_id)
                existing_hashes[digest] = document_id
                existing_days.setdefault(day, []).append(document_id)
            except Exception as exc:  # keep the manifest usable for resume
                entry.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                failures += 1
            time.sleep(max(0.0, args.delay))
        report["items"].append(entry)
        print(f"[{entry['status']}] {candidate['name']}", flush=True)

    counts: dict[str, int] = {}
    for item in report["items"]:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    report["counts"] = counts
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))
    print(f"manifest={args.manifest}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
