#!/usr/bin/env python3
"""Validate editorial decisions that promote continuity evidence into draft Claims."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROLES = {"progress", "milestone", "decision", "commitment", "state", "metric", "noise"}
KINDS = {"event", "state", "decision", "commitment", "metric"}


def review(bundle: dict[str, Any], decisions: dict[str, Any]) -> dict[str, Any]:
    if bundle.get("schema_version") != "continuity-candidates-v1":
        raise ValueError("bundle must be continuity-candidates-v1")
    if decisions.get("schema_version") != "continuity-review-v1":
        raise ValueError("decisions must be continuity-review-v1")
    subject_id = decisions.get("subject_id")
    entries = [entry for entry in bundle["subjects"] if entry["subject"]["subject_id"] == subject_id]
    if len(entries) != 1:
        raise ValueError(f"unknown subject: {subject_id}")
    entry = entries[0]
    candidate_map = {item["candidate_id"]: item for item in entry["candidates"]}
    rows = decisions.get("decisions")
    if not isinstance(rows, list):
        raise ValueError("decisions must be an array")
    seen: set[str] = set()
    claims = []
    held = []
    rejected = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"decisions[{index}] must be an object")
        candidate_id = row.get("candidate_id")
        if candidate_id not in candidate_map:
            raise ValueError(f"decisions[{index}] references unknown candidate")
        if candidate_id in seen:
            raise ValueError(f"duplicate decision for {candidate_id}")
        seen.add(candidate_id)
        action = row.get("action")
        if action == "hold":
            held.append(candidate_id)
            continue
        if action == "reject":
            rejected.append({"candidate_id": candidate_id, "reason": row.get("reason", "")})
            continue
        if action != "promote":
            raise ValueError(f"decisions[{index}].action is invalid")
        role = row.get("role")
        kind = row.get("kind")
        summary = row.get("summary")
        quote = row.get("evidence_quote")
        if role not in ROLES - {"noise"}:
            raise ValueError(f"decisions[{index}].role is invalid")
        if kind not in KINDS:
            raise ValueError(f"decisions[{index}].kind is invalid")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(f"decisions[{index}].summary is required")
        candidate = candidate_map[candidate_id]
        if not isinstance(quote, str) or not quote.strip() or quote not in candidate["original_text"]:
            raise ValueError(f"decisions[{index}].evidence_quote must be verbatim")
        canonical = json.dumps({
            "subject_id": subject_id, "candidate_id": candidate_id, "role": role,
            "kind": kind, "summary": summary.strip(), "quote": quote,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        claims.append({
            "claim_id": "continuity-" + hashlib.sha256(canonical.encode()).hexdigest()[:16],
            "candidate_id": candidate_id,
            "role": role,
            "kind": kind,
            "summary": summary.strip(),
            "valid_date": candidate["valid_date"],
            "epistemic_status": "asserted",
            "evidence": [{
                "evidence_unit_id": candidate["evidence_unit_id"],
                "document_id": candidate["evidence"]["document_id"],
                "quote": quote,
                "start": candidate["evidence"]["start"],
                "end": candidate["evidence"]["end"],
            }],
            "review_status": "draft",
            "state_update_allowed": False,
        })
    unreviewed = sorted(set(candidate_map) - seen)
    return {
        "schema_version": "continuity-claims-v1",
        "subject": entry["subject"],
        "claims": sorted(claims, key=lambda item: (item["valid_date"], item["claim_id"])),
        "held_candidate_ids": held,
        "rejected": rejected,
        "unreviewed_candidate_ids": unreviewed,
        "quality": {
            "all_quotes_verbatim": True,
            "state_updates": 0,
            "llm_calls": 0,
            "ready_for_projection": not unreviewed and bool(claims),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--decisions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = review(
        json.loads(args.bundle.read_text(encoding="utf-8")),
        json.loads(args.decisions.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    args.output.chmod(0o600)
    print(f"[✓] wrote continuity claims: {args.output} ({len(result['claims'])} draft claims)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"CONTINUITY_REVIEW_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
