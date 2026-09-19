#!/usr/bin/env python3
"""Audit Document listing semantics and extraction modes in isolated banks."""

from __future__ import annotations

import argparse
import json
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
    expected: tuple[int, ...] = (200,),
) -> tuple[int, Any, float]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    try:
        parsed: Any = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = raw.decode("utf-8", errors="replace")
    if status not in expected:
        raise RuntimeError(f"{method} {url} returned HTTP {status}: {parsed}")
    return status, parsed, elapsed_ms


def save(root: Path, name: str, value: Any) -> None:
    (root / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def retain(base: str, bank: str, item: dict[str, Any]) -> tuple[dict[str, Any], float]:
    _, result, elapsed = request_json(
        "POST", f"{base}/v1/default/banks/{bank}/memories", {"items": [item], "async": False}
    )
    return result, elapsed


def list_documents(base: str, bank: str, **params: Any) -> dict[str, Any]:
    query = urllib.parse.urlencode(params, doseq=True)
    _, result, _ = request_json("GET", f"{base}/v1/default/banks/{bank}/documents?{query}")
    return result


def get_document(base: str, bank: str, document_id: str) -> dict[str, Any]:
    _, result, _ = request_json(
        "GET", f"{base}/v1/default/banks/{bank}/documents/{urllib.parse.quote(document_id, safe='')}"
    )
    return result


def list_memories(base: str, bank: str, document_id: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"document_id": document_id, "limit": 100})
    _, result, _ = request_json("GET", f"{base}/v1/default/banks/{bank}/memories/list?{query}")
    return result


def recall(base: str, bank: str, query: str, tag: str) -> tuple[dict[str, Any], float]:
    _, result, elapsed = request_json(
        "POST",
        f"{base}/v1/default/banks/{bank}/memories/recall",
        {
            "query": query,
            "budget": "low",
            "max_tokens": 1200,
            "tags": [tag],
            "tags_match": "all_strict",
        },
    )
    return result, elapsed


def all_strings(value: Any) -> str:
    strings: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, dict):
            for child in item.values():
                walk(child)

    walk(value)
    return "\n".join(strings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hindsight", default="http://127.0.0.1:8888")
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    args = parser.parse_args()

    base = args.hindsight.rstrip("/")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "run_id": args.run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tests": {},
    }

    # A05: exact tag filtering, pagination and ordering.
    list_bank = f"audit-v21-list-{args.run_id.lower()}"
    fixtures = [
        ("d1", ["speaker:audit", "source:chatgpt"]),
        ("d2", ["speaker:audit", "source:claude"]),
        ("d3", ["speaker:other", "source:chatgpt"]),
        ("d4", ["speaker:audit", "source:chatgpt", "session:s1"]),
        ("d5", ["speaker:audit", "source:chatgpt", "session:s1"]),
    ]
    for index, (suffix, tags) in enumerate(fixtures, start=1):
        retain(
            base,
            list_bank,
            {
                "content": f"{args.run_id}-A05-{suffix}：分页和标签查询测试记录 {index}。",
                "document_id": f"audit-list-{args.run_id.lower()}-{suffix}",
                "tags": tags,
                "metadata": {"audit_id": "A05", "sequence": str(index)},
                "timestamp": f"2026-09-19T{10 + index:02d}:00:00+08:00",
            },
        )
    all_strict = list_documents(
        base,
        list_bank,
        tags=["speaker:audit", "source:chatgpt"],
        tags_match="all_strict",
        limit=100,
    )
    pages = [list_documents(base, list_bank, limit=2, offset=offset) for offset in (0, 2, 4)]
    repeated = list_documents(base, list_bank, limit=100, offset=0)
    full = list_documents(base, list_bank, limit=100, offset=0)
    save(output, "a05-all-strict.json", all_strict)
    save(output, "a05-pages.json", pages)
    save(output, "a05-full.json", full)
    save(output, "a05-repeated.json", repeated)
    strict_ids = [item["id"] for item in all_strict.get("items", [])]
    page_ids = [item["id"] for page in pages for item in page.get("items", [])]
    full_ids = [item["id"] for item in full.get("items", [])]
    repeat_ids = [item["id"] for item in repeated.get("items", [])]
    a05_pass = (
        len(strict_ids) == 3
        and len(page_ids) == 5
        and len(set(page_ids)) == 5
        and set(page_ids) == set(full_ids)
        and full_ids == repeat_ids
    )
    summary["tests"]["A05"] = {
        "status": "PASS" if a05_pass else "FAIL",
        "bank_id": list_bank,
        "all_strict_count": len(strict_ids),
        "pagination_ids": page_ids,
        "stable_order": full_ids == repeat_ids,
        "total": full.get("total"),
    }

    # A06: compare extraction modes with identical source text and questions.
    source_text = "\n".join(
        [
            f"LONG-RECORD-{args.run_id}",
            "昨晚 02:00 才睡着，今天 10:00 起床，总共睡了约 8 小时。",
            "起床后看到山寨币在涨，买了 ETH、CRV 和 PEPE。",
            "CRV 之后止损，准确亏损为 52 美元。",
            "13:20 开始午休，14:00 醒来，午休 40 分钟。",
            "下午继续做 AI 外置记忆项目，重点研究 Hindsight Documents。",
            "19:00 吃了炒粉、炸茄子和白粥，花费 69 元，感觉偏贵。",
            "晚上整理了项目架构文档，决定先审计 Hindsight 能力，不立即新建 Record PostgreSQL。",
        ]
    )
    questions = [
        ("sleep", "昨晚几点睡，今天几点起？", ["02:00", "10:00"]),
        ("trading", "买了哪些币？", ["ETH", "CRV", "PEPE"]),
        ("loss", "CRV 亏了多少？", ["52"]),
        ("nap", "午休了多久？", ["40"]),
        ("dinner", "晚饭吃了什么，花了多少？", ["炒粉", "69"]),
        ("project", "AI 外置记忆项目做了什么决策？", ["Hindsight", "Record"]),
    ]
    mode_results: dict[str, Any] = {}
    for mode in ("concise", "verbose", "verbatim"):
        bank = f"audit-v21-{mode}-{args.run_id.lower()}"
        tag = f"audit-mode:{mode}"
        _, config_response, _ = request_json(
            "PATCH",
            f"{base}/v1/default/banks/{bank}/config",
            {"updates": {"retain_extraction_mode": mode, "enable_auto_consolidation": False}},
        )
        document_id = f"audit-long-{mode}-{args.run_id.lower()}"
        retain_response, retain_ms = retain(
            base,
            bank,
            {
                "content": source_text,
                "document_id": document_id,
                "timestamp": "2026-09-19T21:00:00+08:00",
                "tags": [tag, "speaker:audit"],
                "metadata": {"audit_id": "A06", "mode": mode, "run_id": args.run_id},
            },
        )
        document = get_document(base, bank, document_id)
        memories = list_memories(base, bank, document_id)
        recall_results: list[dict[str, Any]] = []
        for name, query, expected_tokens in questions:
            response, recall_ms = recall(base, bank, query, tag)
            response_text = all_strings(response)
            found = {token: token.lower() in response_text.lower() for token in expected_tokens}
            recall_results.append(
                {
                    "case": name,
                    "query": query,
                    "expected_tokens": expected_tokens,
                    "found": found,
                    "pass": all(found.values()),
                    "recall_ms": recall_ms,
                }
            )
            save(output, f"a06-{mode}-recall-{name}.json", response)
        mode_results[mode] = {
            "bank_id": bank,
            "config_overrides": config_response.get("overrides"),
            "document_id": document_id,
            "original_text_exact": document.get("original_text") == source_text,
            "memory_unit_count": document.get("memory_unit_count"),
            "retain_ms": retain_ms,
            "usage": retain_response.get("usage"),
            "recall_pass_count": sum(1 for item in recall_results if item["pass"]),
            "recall_total": len(recall_results),
            "recalls": recall_results,
        }
        save(output, f"a06-{mode}-document.json", document)
        save(output, f"a06-{mode}-memories.json", memories)
        save(output, f"a06-{mode}-retain.json", retain_response)
    a06_pass = all(result["original_text_exact"] for result in mode_results.values())
    summary["tests"]["A06"] = {
        "status": "PASS_WITH_FINDINGS" if a06_pass else "FAIL",
        "modes": mode_results,
        "note": "PASS_WITH_FINDINGS confirms source preservation; extraction quality is a comparative result, not a binary gate.",
    }

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    summary["overall"] = "PASS_WITH_FINDINGS" if a05_pass and a06_pass else "REVIEW"
    save(output, "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if a05_pass and a06_pass else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"AUDIT_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
