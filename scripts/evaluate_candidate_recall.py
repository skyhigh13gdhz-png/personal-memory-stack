#!/usr/bin/env python3
"""Measure deterministic evidence recall against a manually curated benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} root must be an object")
    return value


def evaluate(candidates: dict[str, Any], benchmark: dict[str, Any]) -> dict[str, Any]:
    candidate_items = candidates.get("candidates")
    expected_items = benchmark.get("expected_evidence")
    if not isinstance(candidate_items, list):
        raise ValueError("candidate package needs candidates array")
    if not isinstance(expected_items, list) or not expected_items:
        raise ValueError("benchmark needs non-empty expected_evidence array")
    evidence_quotes = [
        ref.get("quote", "")
        for candidate in candidate_items
        for ref in candidate.get("evidence", [])
        if isinstance(ref, dict) and isinstance(ref.get("quote"), str)
    ]
    rows = []
    for index, expected in enumerate(expected_items):
        if not isinstance(expected, dict):
            raise ValueError(f"expected_evidence[{index}] must be an object")
        item_id = expected.get("id")
        quote = expected.get("quote")
        importance = expected.get("importance", "required")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError(f"expected_evidence[{index}].id is required")
        if not isinstance(quote, str) or len(quote.strip()) < 4:
            raise ValueError(f"expected_evidence[{index}].quote is too short")
        if importance not in {"required", "optional"}:
            raise ValueError(f"expected_evidence[{index}].importance is invalid")
        matched = any(quote in candidate_quote or candidate_quote in quote for candidate_quote in evidence_quotes)
        rows.append({"id": item_id, "importance": importance, "matched": matched})
    required = [item for item in rows if item["importance"] == "required"]
    matched_required = sum(item["matched"] for item in required)
    recall = matched_required / len(required) if required else 1.0
    return {
        "required_total": len(required),
        "required_matched": matched_required,
        "required_recall": recall,
        "missing_required": [item["id"] for item in required if not item["matched"]],
        "optional_total": sum(item["importance"] == "optional" for item in rows),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--minimum", type=float, default=0.95)
    args = parser.parse_args()
    result = evaluate(load_object(args.candidates), load_object(args.benchmark))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["required_recall"] < args.minimum:
        print(
            f"[x] recall {result['required_recall']:.1%} is below {args.minimum:.1%}",
            file=sys.stderr,
        )
        return 1
    print(f"[✓] recall {result['required_recall']:.1%} meets {args.minimum:.1%}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"CLAIM_RECALL_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
