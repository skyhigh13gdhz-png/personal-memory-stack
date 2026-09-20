#!/usr/bin/env python3
"""Fetch complete daily Gateway Documents into a private Claim input bundle."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any


def request_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode(errors="replace")
        raise RuntimeError(f"Gateway HTTP {exc.code}: {detail}") from exc


def fetch_day(base: str, token: str, speaker: str, day: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({
        "speaker": speaker,
        "date_from": day,
        "date_to": day,
        "include_text": "true",
        "limit": 1000,
        "offset": 0,
    })
    result = request_json(f"{base.rstrip('/')}/v1/documents?{params}", token)
    data = result.get("data") or {}
    items = data.get("items") or []
    if int(data.get("total", len(items))) != len(items):
        raise RuntimeError("Gateway result was truncated; refusing incomplete Claim input")
    return items


def load_subjects(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    subjects = value.get("subjects") if isinstance(value, dict) else value
    if not isinstance(subjects, list):
        raise ValueError("subjects file must be an array or contain a subjects array")
    required = {"subject_id", "subject_type", "canonical_name", "promotion_reason"}
    for index, subject in enumerate(subjects):
        if not isinstance(subject, dict) or not required.issubset(subject):
            raise ValueError(f"subjects[{index}] misses required fields")
    return subjects


def build_bundle(
    documents: list[dict[str, Any]],
    subjects: list[dict[str, Any]],
    *,
    day: str,
    speaker: str,
) -> dict[str, Any]:
    normalized = []
    for index, document in enumerate(documents):
        document_id = document.get("id") or document.get("document_id")
        original_text = document.get("original_text")
        if not isinstance(document_id, str) or not document_id:
            raise ValueError(f"documents[{index}] has no id")
        if not isinstance(original_text, str) or not original_text.strip():
            raise ValueError(f"documents[{index}] has no original_text")
        normalized.append({
            "document_id": document_id,
            "date": day,
            "original_text": original_text,
        })
    normalized.sort(key=lambda item: item["document_id"])
    return {
        "schema_version": "claim-input-v1",
        "speaker": speaker,
        "date": day,
        "subjects": subjects,
        "documents": normalized,
        "forbidden_inferences": [],
    }


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--speaker", default="liangzai")
    parser.add_argument("--gateway", default="http://127.0.0.1:8787")
    parser.add_argument("--subjects", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    date.fromisoformat(args.date)
    token = os.environ.get("GATEWAY_API_TOKEN", "")
    if not token:
        raise SystemExit("missing GATEWAY_API_TOKEN")
    documents = fetch_day(args.gateway, token, args.speaker, args.date)
    if not documents:
        raise SystemExit(f"no Documents found for {args.speaker} on {args.date}")
    bundle = build_bundle(
        documents,
        load_subjects(args.subjects),
        day=args.date,
        speaker=args.speaker,
    )
    write_json_atomic(args.output, bundle)
    print(f"[✓] wrote complete Claim input: {args.output} ({len(documents)} Documents)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"CLAIM_INPUT_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
