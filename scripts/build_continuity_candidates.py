#!/usr/bin/env python3
"""Build a lossless, zero-LLM continuity candidate bundle from classified evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "continuity-candidates-v1"


def build(classified: dict[str, Any]) -> dict[str, Any]:
    if classified.get("schema_version") != "classified-evidence-v1":
        raise ValueError("input must be classified-evidence-v1")
    subjects = classified.get("subjects", [])
    subject_map = {item["subject_id"]: item for item in subjects}
    if len(subject_map) != len(subjects):
        raise ValueError("duplicate subject_id")
    candidates: dict[str, list[dict[str, Any]]] = {subject_id: [] for subject_id in subject_map}
    seen_units: set[str] = set()
    for source_order, unit in enumerate(classified.get("units", [])):
        unit_subjects = unit.get("subject_ids", [])
        if len(unit_subjects) != len(set(unit_subjects)):
            raise ValueError(f"duplicate subject link on {unit.get('unit_id')}")
        for subject_id in unit_subjects:
            if subject_id not in subject_map:
                raise ValueError(f"unknown subject {subject_id} on {unit.get('unit_id')}")
            required = ("unit_id", "date", "text", "document_id", "start", "end")
            if any(key not in unit for key in required):
                raise ValueError(f"incomplete evidence unit {unit.get('unit_id')}")
            candidates[subject_id].append({
                "candidate_id": f"candidate:{subject_id}:{unit['unit_id']}",
                "source_order": source_order,
                "evidence_unit_id": unit["unit_id"],
                "valid_date": unit["date"],
                "summary": unit.get("summary") or unit["text"],
                "original_text": unit["text"],
                "category": unit.get("category", "other"),
                "visibility": unit.get("visibility", "archive"),
                "evidence": {
                    "document_id": unit["document_id"],
                    "start": unit["start"],
                    "end": unit["end"],
                },
                "review_status": "pending",
                "state_update_allowed": False,
            })
            seen_units.add(unit["unit_id"])
    entries = []
    for subject_id, subject in subject_map.items():
        rows = sorted(candidates[subject_id], key=lambda item: (item["valid_date"], item["source_order"]))
        entries.append({"subject": subject, "candidates": rows})
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": SCHEMA_VERSION,
        "source_schema_version": classified["schema_version"],
        "source_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "subjects": entries,
        "metrics": {
            "confirmed_subjects": len(subject_map),
            "subjects_with_candidates": sum(bool(item["candidates"]) for item in entries),
            "candidate_links": sum(len(item["candidates"]) for item in entries),
            "unique_evidence_units": len(seen_units),
            "llm_calls": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("classified", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    value = json.loads(args.classified.read_text(encoding="utf-8"))
    result = build(value)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    args.output.chmod(0o600)
    print(
        f"[✓] wrote {SCHEMA_VERSION}: {args.output} "
        f"({result['metrics']['candidate_links']} links, 0 LLM calls)"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"CONTINUITY_CANDIDATES_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
