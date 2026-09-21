#!/usr/bin/env python3
"""Validate evidence-backed Current State and state-transition proposals for one Subject."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


STATE_TYPES = {"direct_fact", "derived_state", "hypothesis"}
CONFIDENCE = {"low", "medium", "high"}
FACETS = {
    "phase", "capability", "focus", "problem", "decision", "goal",
    "open_question", "next_action", "milestone",
}
LIFECYCLE = {"current", "superseded", "resolved", "reopened"}
HIGH_IMPACT_SUBJECTS = {"person", "health_track", "asset", "strategy"}


def claim_map(historical: dict[str, Any] | None, reviewed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    claims: dict[str, dict[str, Any]] = {}
    if historical:
        for claim in historical.get("claims", []):
            claims[claim["claim_id"]] = claim
    for claim in reviewed.get("claims", []):
        if claim["claim_id"] in claims:
            raise ValueError(f"duplicate claim_id: {claim['claim_id']}")
        claims[claim["claim_id"]] = claim
    return claims


def validate(state: dict[str, Any], claims: dict[str, dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    if state.get("schema_version") != "subject-state-v1":
        errors.append("schema_version must be subject-state-v1")
    subject = state.get("subject")
    if not isinstance(subject, dict) or not subject.get("subject_id") or not subject.get("subject_type"):
        errors.append("subject is incomplete")
        subject = {}
    try:
        date.fromisoformat(state.get("as_of", ""))
    except ValueError:
        errors.append("as_of must be ISO-8601 date")
    items = state.get("state_items")
    if not isinstance(items, list) or not items:
        errors.append("state_items must be non-empty")
        items = []
    ids: set[str] = set()
    item_map: dict[str, dict[str, Any]] = {}
    current_keys: list[str] = []
    referenced_claims: set[str] = set()
    for index, item in enumerate(items):
        path = f"state_items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        state_id = item.get("state_id")
        if not isinstance(state_id, str) or not state_id:
            errors.append(f"{path}.state_id is required")
        elif state_id in ids:
            errors.append(f"duplicate state_id: {state_id}")
        ids.add(state_id)
        if isinstance(state_id, str) and state_id:
            item_map[state_id] = item
        if not isinstance(item.get("state_key"), str) or not item["state_key"]:
            errors.append(f"{path}.state_key is required")
        if not isinstance(item.get("statement"), str) or not item["statement"].strip():
            errors.append(f"{path}.statement is required")
        state_type = item.get("state_type")
        if state_type not in STATE_TYPES:
            errors.append(f"{path}.state_type is invalid")
        if item.get("confidence") not in CONFIDENCE:
            errors.append(f"{path}.confidence is invalid")
        if item.get("facet") not in FACETS:
            errors.append(f"{path}.facet is invalid")
        lifecycle = item.get("lifecycle")
        if lifecycle not in LIFECYCLE:
            errors.append(f"{path}.lifecycle is invalid")
        if lifecycle in {"current", "reopened"}:
            current_keys.append(item.get("state_key", ""))
            if item.get("valid_to") is not None:
                errors.append(f"{path}.valid_to must be null while current")
        elif not item.get("valid_to"):
            errors.append(f"{path}.valid_to is required when closed")
        for field in ("valid_from", "valid_to"):
            value = item.get(field)
            if value is None and field == "valid_to":
                continue
            try:
                date.fromisoformat(value)
            except (TypeError, ValueError):
                errors.append(f"{path}.{field} must be ISO-8601 date or null")
        refs = item.get("evidence_claim_ids")
        if not isinstance(refs, list) or not refs:
            errors.append(f"{path}.evidence_claim_ids must be non-empty")
            refs = []
        unknown = [claim_id for claim_id in refs if claim_id not in claims]
        if unknown:
            errors.append(f"{path} references unknown claims: {unknown}")
        referenced_claims.update(refs)
        evidence_dates = {claims[claim_id]["valid_date"] for claim_id in refs if claim_id in claims}
        if state_type == "derived_state" and (len(refs) < 2 or len(evidence_dates) < 2):
            errors.append(f"{path} derived_state requires at least two claims from two dates")
        if state_type == "hypothesis":
            if item.get("confidence") == "high":
                errors.append(f"{path} hypothesis cannot have high confidence")
            if item.get("review_policy") != "review_required":
                errors.append(f"{path} hypothesis requires review")
        if subject.get("subject_type") in HIGH_IMPACT_SUBJECTS and state_type != "direct_fact":
            if item.get("review_policy") != "review_required":
                errors.append(f"{path} high-impact derived state requires review")
        if item.get("review_policy") not in {"auto_eligible", "review_required"}:
            errors.append(f"{path}.review_policy is invalid")
        if item.get("supersedes") is not None and not isinstance(item.get("supersedes"), list):
            errors.append(f"{path}.supersedes must be an array")
    duplicate_current = [key for key, count in Counter(current_keys).items() if key and count > 1]
    if duplicate_current:
        errors.append(f"multiple current states for keys: {duplicate_current}")
    for index, item in enumerate(items):
        for old_id in item.get("supersedes", []):
            if old_id not in ids:
                errors.append(f"state_items[{index}] supersedes unknown state: {old_id}")
            elif old_id == item.get("state_id"):
                errors.append(f"state_items[{index}] cannot supersede itself")
            else:
                old = item_map[old_id]
                if old.get("state_key") != item.get("state_key"):
                    errors.append(f"state_items[{index}] can only supersede the same state_key")
                if old.get("lifecycle") not in {"superseded", "resolved"}:
                    errors.append(f"state_items[{index}] superseded state must be closed")
                if old.get("valid_to") and item.get("valid_from") and old["valid_to"] > item["valid_from"]:
                    errors.append(f"state_items[{index}] starts before superseded state ended")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "state_items": len(items),
        "current_items": sum(item["lifecycle"] in {"current", "reopened"} for item in items),
        "referenced_claims": len(referenced_claims),
        "auto_eligible": sum(item["review_policy"] == "auto_eligible" for item in items),
        "review_required": sum(item["review_policy"] == "review_required" for item in items),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--reviewed", required=True, type=Path)
    parser.add_argument("--historical", type=Path)
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    reviewed = json.loads(args.reviewed.read_text(encoding="utf-8"))
    historical = json.loads(args.historical.read_text(encoding="utf-8")) if args.historical else None
    metrics = validate(state, claim_map(historical, reviewed))
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"SUBJECT_STATE_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
