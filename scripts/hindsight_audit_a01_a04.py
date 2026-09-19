#!/usr/bin/env python3
"""Run the first V2.1 Hindsight audit batch against an isolated bank.

The script never prints credentials and never touches a non-audit bank. Raw JSON
responses are written below the selected output directory for later review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def request_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    expected: tuple[int, ...] = (200,),
) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    merged_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        merged_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=merged_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=240) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    parsed: Any
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = raw.decode("utf-8", errors="replace")
    if status not in expected:
        raise RuntimeError(f"{method} {url} returned HTTP {status}: {parsed}")
    return status, parsed


def save_json(root: Path, name: str, value: Any) -> None:
    (root / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def list_documents(base: str, bank: str, **params: Any) -> dict[str, Any]:
    query = urllib.parse.urlencode(params, doseq=True)
    _, result = request_json("GET", f"{base}/v1/default/banks/{bank}/documents?{query}")
    return result


def get_document(base: str, bank: str, document_id: str) -> dict[str, Any]:
    safe_id = urllib.parse.quote(document_id, safe="")
    _, result = request_json("GET", f"{base}/v1/default/banks/{bank}/documents/{safe_id}")
    return result


def list_memories(base: str, bank: str, document_id: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"document_id": document_id, "limit": 100})
    _, result = request_json("GET", f"{base}/v1/default/banks/{bank}/memories/list?{query}")
    return result


def retain(base: str, bank: str, item: dict[str, Any]) -> dict[str, Any]:
    _, result = request_json(
        "POST",
        f"{base}/v1/default/banks/{bank}/memories",
        {"items": [item], "async": False},
    )
    return result


def memory_texts(payload: Any) -> str:
    strings: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key in {"text", "content", "original_text"}:
                    walk(item)
                elif isinstance(item, (dict, list)):
                    walk(item)

    walk(payload)
    return "\n".join(strings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hindsight", default="http://127.0.0.1:8888")
    parser.add_argument("--gateway", default="http://127.0.0.1:8787")
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    args = parser.parse_args()

    token = os.environ.get("GATEWAY_API_TOKEN", "")
    if not token:
        raise SystemExit("GATEWAY_API_TOKEN is required in the environment")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    bank = f"audit-v21-{args.run_id.lower()}"
    speaker = f"audit-{args.run_id.lower()}"
    base = args.hindsight.rstrip("/")
    gateway = args.gateway.rstrip("/")
    results: dict[str, Any] = {
        "run_id": args.run_id,
        "bank_id": bank,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tests": {},
    }

    # A01: write through Gateway, read exact original text through Document API.
    a01_text = (
        f"DOC-RAW-TEST-{args.run_id}\n"
        "START-739251\n"
        "今天测试 Hindsight Document 是否完整保存原始文本。\n"
        "中间值 ABC-987654。\n"
        "END-739251"
    )
    gateway_body = {
        "content": a01_text,
        "bank_id": bank,
        "client_id": "v21-audit",
        "speaker": speaker,
        "metadata": {"audit_id": "A01", "run_id": args.run_id},
    }
    _, gateway_response = request_json(
        "POST",
        f"{gateway}/v1/memories/retain",
        gateway_body,
        {"Authorization": f"Bearer {token}"},
    )
    save_json(output, "a01-gateway-retain.json", gateway_response)
    documents = list_documents(base, bank, tags=[f"speaker:{speaker}"], tags_match="all_strict", limit=100)
    save_json(output, "a01-documents.json", documents)
    matched_document: dict[str, Any] | None = None
    for item in documents.get("items", []):
        document = get_document(base, bank, item["id"])
        if args.run_id in (document.get("original_text") or ""):
            matched_document = document
            break
    if matched_document is None:
        raise RuntimeError("A01 could not locate the Gateway-retained document")
    save_json(output, "a01-document.json", matched_document)
    a01_pass = matched_document.get("original_text") == a01_text
    results["tests"]["A01"] = {
        "status": "PASS" if a01_pass else "FAIL",
        "document_id": matched_document.get("id"),
        "expected_sha256": sha256_text(a01_text),
        "actual_sha256": sha256_text(matched_document.get("original_text") or ""),
        "memory_unit_count": matched_document.get("memory_unit_count"),
    }

    # A02: stable document ID replacement and memory cleanup.
    correction_id = f"audit-correction-{args.run_id.lower()}"
    correction_tag = f"audit-run:{args.run_id}"
    old_text = f"审计标记 {args.run_id}-CORRECTION：CRV 止损亏损 42 美元。"
    new_text = f"审计标记 {args.run_id}-CORRECTION：CRV 止损亏损 52 美元。"
    common_item = {
        "document_id": correction_id,
        "tags": [correction_tag, "speaker:audit"],
        "metadata": {"audit_id": "A02", "run_id": args.run_id},
        "timestamp": "2026-09-19T17:00:00+08:00",
    }
    retain(base, bank, {**common_item, "content": old_text, "update_mode": "replace"})
    before_doc = get_document(base, bank, correction_id)
    before_memories = list_memories(base, bank, correction_id)
    save_json(output, "a02-before-document.json", before_doc)
    save_json(output, "a02-before-memories.json", before_memories)
    retain(base, bank, {**common_item, "content": new_text, "update_mode": "replace"})
    after_doc = get_document(base, bank, correction_id)
    after_memories = list_memories(base, bank, correction_id)
    save_json(output, "a02-after-document.json", after_doc)
    save_json(output, "a02-after-memories.json", after_memories)
    before_texts = memory_texts(before_memories)
    after_texts = memory_texts(after_memories)
    a02_pass = (
        before_doc.get("original_text") == old_text
        and after_doc.get("original_text") == new_text
        and "42" in before_texts
        and "42" not in after_texts
        and "52" in after_texts
    )
    results["tests"]["A02"] = {
        "status": "PASS" if a02_pass else "FAIL",
        "document_id": correction_id,
        "before_memory_unit_count": before_doc.get("memory_unit_count"),
        "after_memory_unit_count": after_doc.get("memory_unit_count"),
        "old_value_present_before": "42" in before_texts,
        "old_value_present_after": "42" in after_texts,
        "new_value_present_after": "52" in after_texts,
    }

    # A03: reprocess then delete a dedicated document.
    lifecycle_id = f"audit-lifecycle-{args.run_id.lower()}"
    lifecycle_text = f"审计标记 {args.run_id}-LIFECYCLE：这条记录仅用于 reprocess/delete 测试。"
    retain(
        base,
        bank,
        {
            "content": lifecycle_text,
            "document_id": lifecycle_id,
            "tags": [correction_tag, "speaker:audit"],
            "metadata": {"audit_id": "A03", "run_id": args.run_id},
        },
    )
    lifecycle_safe = urllib.parse.quote(lifecycle_id, safe="")
    _, reprocess_response = request_json(
        "POST",
        f"{base}/v1/default/banks/{bank}/documents/{lifecycle_safe}/reprocess",
    )
    save_json(output, "a03-reprocess.json", reprocess_response)
    _, delete_response = request_json(
        "DELETE",
        f"{base}/v1/default/banks/{bank}/documents/{lifecycle_safe}",
    )
    save_json(output, "a03-delete.json", delete_response)
    get_status, get_after_delete = request_json(
        "GET",
        f"{base}/v1/default/banks/{bank}/documents/{lifecycle_safe}",
        expected=(404,),
    )
    memories_after_delete = list_memories(base, bank, lifecycle_id)
    save_json(output, "a03-get-after-delete.json", get_after_delete)
    save_json(output, "a03-memories-after-delete.json", memories_after_delete)
    remaining_memories = memories_after_delete.get("total")
    if remaining_memories is None:
        remaining_memories = len(memories_after_delete.get("items", []))
    a03_pass = (
        bool(reprocess_response.get("success"))
        and bool(delete_response.get("success"))
        and get_status == 404
        and remaining_memories == 0
    )
    results["tests"]["A03"] = {
        "status": "PASS" if a03_pass else "FAIL",
        "document_id": lifecycle_id,
        "reprocess_operation_id": reprocess_response.get("operation_id"),
        "memory_units_deleted": delete_response.get("memory_units_deleted"),
        "remaining_memories": remaining_memories,
    }

    # A04: explicit, backfilled, timeless, and multi-event timestamps.
    time_cases = [
        ("today", "今天 19:00 吃了砂锅粥。", "2026-09-19T19:00:00+08:00"),
        ("yesterday", "补录昨天：19:00 吃了砂锅粥。", "2026-09-18T19:00:00+08:00"),
        ("timeless", "我以前挺喜欢游泳的。", "unset"),
        (
            "multi-event",
            "昨晚 23:00 睡觉，今早 08:00 起床，今天 15:00 处理了记忆项目。",
            "2026-09-19T20:00:00+08:00",
        ),
    ]
    a04_items: list[dict[str, Any]] = []
    for name, content, timestamp in time_cases:
        document_id = f"audit-time-{name}-{args.run_id.lower()}"
        retain(
            base,
            bank,
            {
                "content": f"{args.run_id}-{name}: {content}",
                "document_id": document_id,
                "timestamp": timestamp,
                "tags": [correction_tag, "speaker:audit", f"time-case:{name}"],
                "metadata": {"audit_id": "A04", "case": name, "run_id": args.run_id},
            },
        )
        document = get_document(base, bank, document_id)
        memories = list_memories(base, bank, document_id)
        save_json(output, f"a04-{name}-document.json", document)
        save_json(output, f"a04-{name}-memories.json", memories)
        a04_items.append(
            {
                "case": name,
                "document_id": document_id,
                "input_timestamp": timestamp,
                "created_at": document.get("created_at"),
                "updated_at": document.get("updated_at"),
                "retain_params": document.get("retain_params"),
                "memory_unit_count": document.get("memory_unit_count"),
                "memory_time_fields": [
                    {
                        "mentioned_at": item.get("mentioned_at"),
                        "occurred_start": item.get("occurred_start"),
                        "occurred_end": item.get("occurred_end"),
                    }
                    for item in memories.get("items", [])
                ],
            }
        )
    a04_pass = all(item["retain_params"] is not None for item in a04_items)
    results["tests"]["A04"] = {
        "status": "PASS" if a04_pass else "PARTIAL",
        "cases": a04_items,
        "note": "Temporal semantics require manual evidence review; this status only confirms retained parameters are inspectable.",
    }

    results["finished_at"] = datetime.now(timezone.utc).isoformat()
    results["overall"] = (
        "PASS"
        if all(test["status"] == "PASS" for test in results["tests"].values())
        else "REVIEW"
    )
    save_json(output, "summary.json", results)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(results["tests"][key]["status"] == "PASS" for key in ("A01", "A02", "A03")) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - audit runner must print a concise terminal failure.
        print(f"AUDIT_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
