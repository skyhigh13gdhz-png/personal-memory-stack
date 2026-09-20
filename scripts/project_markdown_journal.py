#!/usr/bin/env python3
"""Project speaker-scoped Gateway Documents into a deterministic Markdown journal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def request_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError(f"Gateway HTTP {exc.code}: {detail}") from exc


def list_document_ids(base: str, token: str, speaker: str, bank_id: str | None) -> list[str]:
    ids: list[str] = []
    offset = 0
    while True:
        params: dict[str, Any] = {"speaker": speaker, "limit": 1000, "offset": offset}
        if bank_id:
            params["bank_id"] = bank_id
        result = request_json(f"{base}/v1/documents?{urllib.parse.urlencode(params)}", token)
        listing = result.get("data") or {}
        items = listing.get("items") or []
        page_ids = [str(item["id"]) for item in items]
        ids.extend(page_ids)
        total = int(listing.get("total", len(ids)))
        if not page_ids or len(ids) >= total:
            return ids
        offset += len(page_ids)


def get_document(base: str, token: str, speaker: str, document_id: str, bank_id: str | None) -> dict[str, Any]:
    params = {"speaker": speaker}
    if bank_id:
        params["bank_id"] = bank_id
    quoted = urllib.parse.quote(document_id, safe="")
    result = request_json(f"{base}/v1/documents/{quoted}?{urllib.parse.urlencode(params)}", token)
    document = result.get("data")
    if not isinstance(document, dict):
        raise RuntimeError(f"Document {document_id} returned an invalid payload")
    return document


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value or value.lower() == "unset":
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def document_time(document: dict[str, Any]) -> tuple[datetime | None, str]:
    event_date = (document.get("retain_params") or {}).get("event_date")
    parsed = parse_time(event_date)
    if parsed is not None:
        return parsed, "event_date"
    parsed = parse_time(document.get("created_at"))
    if parsed is not None:
        return parsed, "created_at"
    return None, "undated"


def render_day(day: str, entries: list[dict[str, Any]], zone: ZoneInfo) -> str:
    if day == "_undated":
        title = "未标注日期的记录"
    else:
        parsed_day = datetime.strptime(day, "%Y-%m-%d")
        title = f"{parsed_day.year}年{parsed_day.month}月{parsed_day.day}日"
    lines = [f"# {title}", ""]
    for entry in entries:
        document = entry["document"]
        text = document.get("original_text")
        if not isinstance(text, str):
            text = ""
        instant = entry["instant"]
        label = instant.astimezone(zone).strftime("%H:%M") if instant else "时间未知"
        document_id = str(document.get("id") or document.get("document_id") or entry["id"])
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        lines.extend([
            f"## {label}",
            "",
            text.strip(),
            "",
            "<!-- personal-memory-record "
            + json.dumps(
                {
                    "document_id": document_id,
                    "sha256": digest,
                    "time_source": entry["time_source"],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + " -->",
            "",
            "---",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def build_projection(
    documents: list[dict[str, Any]],
    timezone_name: str,
    excluded_sha256: set[str] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    zone = ZoneInfo(timezone_name)
    excluded_sha256 = excluded_sha256 or set()
    grouped: dict[str, list[dict[str, Any]]] = {}
    manifest_documents: list[dict[str, Any]] = []
    excluded_documents: list[dict[str, str]] = []
    for document in documents:
        document_id = str(document.get("id") or document.get("document_id") or "")
        if not document_id:
            raise RuntimeError("Document without id cannot be projected")
        original = document.get("original_text") or ""
        digest = hashlib.sha256(original.encode("utf-8")).hexdigest()
        if digest in excluded_sha256:
            excluded_documents.append({"id": document_id, "original_text_sha256": digest})
            continue
        instant, time_source = document_time(document)
        day = instant.astimezone(zone).date().isoformat() if instant else "_undated"
        grouped.setdefault(day, []).append({
            "id": document_id,
            "instant": instant,
            "time_source": time_source,
            "document": document,
        })
        manifest_documents.append({
            "id": document_id,
            "day": day,
            "time_source": time_source,
            "original_text_sha256": digest,
        })

    files: dict[str, str] = {}
    for day, entries in sorted(grouped.items()):
        entries.sort(key=lambda item: (item["instant"] or datetime.min.replace(tzinfo=timezone.utc), item["id"]))
        files[f"{day}.md"] = render_day(day, entries, zone)
    index_lines = ["# 外置记忆", "", "这里是按日期整理的个人记录，由记忆系统自动更新。", ""]
    dated_files = [name for name in sorted(files, reverse=True) if name != "_undated.md"]
    if dated_files:
        index_lines.extend(["## 按日期", ""])
        index_lines.extend(f"- [[{name[:-3]}]]" for name in dated_files)
        if "_undated.md" in files:
            index_lines.append("- [[_undated|日期未知]]")
    elif "_undated.md" in files:
        index_lines.extend(["- [[_undated|日期未知]]"])
    else:
        index_lines.append("当前还没有可展示的个人记录。")
    files["_索引.md"] = "\n".join(index_lines).rstrip() + "\n"
    manifest = {
        "schema_version": 1,
        "timezone": timezone_name,
        "source_document_count": len(documents),
        "document_count": len(manifest_documents),
        "excluded_document_count": len(excluded_documents),
        "excluded_documents": sorted(excluded_documents, key=lambda item: item["id"]),
        "documents": sorted(manifest_documents, key=lambda item: item["id"]),
    }
    return files, manifest


def write_projection(output: Path, files: dict[str, str], manifest: dict[str, Any], replace: bool) -> Path | None:
    backup: Path | None = None
    staging = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex[:8]}"
    staging.mkdir(parents=True)
    try:
        for name, content in files.items():
            (staging / name).write_text(content, encoding="utf-8")
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if output.exists():
            if not replace:
                raise FileExistsError(f"Output already exists: {output}; pass --replace-output")
            suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = output.parent / f"{output.name}.backup-{suffix}"
            if backup.exists():
                backup = output.parent / f"{output.name}.backup-{suffix}-{uuid.uuid4().hex[:6]}"
            output.rename(backup)
        staging.rename(output)
        return backup
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if backup is not None and not output.exists():
            backup.rename(output)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", default="http://127.0.0.1:8787")
    parser.add_argument("--speaker", required=True)
    parser.add_argument("--bank-id")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--token-env", default="GATEWAY_API_TOKEN")
    parser.add_argument("--exclude-text-sha256", action="append", default=[])
    parser.add_argument("--replace-output", action="store_true")
    args = parser.parse_args()

    token = os.environ.get(args.token_env)
    if not token:
        raise SystemExit(f"Missing token environment variable: {args.token_env}")
    base = args.gateway.rstrip("/")
    ids = list_document_ids(base, token, args.speaker, args.bank_id)
    documents = [get_document(base, token, args.speaker, item, args.bank_id) for item in ids]
    excluded = {value.lower() for value in args.exclude_text_sha256}
    if any(len(value) != 64 or any(char not in "0123456789abcdef" for char in value) for value in excluded):
        raise SystemExit("--exclude-text-sha256 must be a 64-character lowercase hex digest")
    files, manifest = build_projection(documents, args.timezone, excluded)
    backup = write_projection(args.output, files, manifest, args.replace_output)
    print(
        f"[✓] Projected {manifest['document_count']} documents into {len(files)} Markdown files "
        f"({manifest['excluded_document_count']} excluded): {args.output}"
    )
    if backup:
        print(f"[✓] Previous projection preserved at: {backup}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"PROJECT_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
