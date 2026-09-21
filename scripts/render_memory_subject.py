#!/usr/bin/env python3
"""Render a type-aware living Memory Subject page from validated state and Claims."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("validate_subject_state", SCRIPT_DIR / "validate_subject_state.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VALIDATOR)
PROFILE_SPEC = importlib.util.spec_from_file_location("validate_subject_profile", SCRIPT_DIR / "validate_subject_profile.py")
PROFILE_VALIDATOR = importlib.util.module_from_spec(PROFILE_SPEC)
assert PROFILE_SPEC.loader is not None
PROFILE_SPEC.loader.exec_module(PROFILE_VALIDATOR)

def render(
    profile: dict[str, Any], state: dict[str, Any], claims: dict[str, dict[str, Any]], template: dict[str, Any]
) -> str:
    metrics = VALIDATOR.validate(state, claims)
    subject = state["subject"]
    PROFILE_VALIDATOR.validate(profile, subject, template)
    current = [item for item in state["state_items"] if item["lifecycle"] in {"current", "reopened"}]
    metadata = {
        "subject_id": subject["subject_id"], "subject_type": subject["subject_type"],
        "as_of": state["as_of"], "projection": "memory-subject-v2",
    }
    lines = [
        f"# {subject['canonical_name']}", "", f"> 更新至 {state['as_of']}", "",
        "<!-- memory-subject " + json.dumps(metadata, ensure_ascii=False, separators=(",", ":")) + " -->", "",
    ]
    if profile["review_status"] == "draft":
        lines.extend(["> [!warning] 基本档案待确认", "> 以下基本档案是评审草案，确认前不会进入正式长期记忆。", ""])
    for section in template["profile_sections"]:
        value = profile["content"].get(section["key"])
        if not value:
            continue
        lines.extend([f"## {section['title']}", ""])
        if section["kind"] == "paragraph":
            lines.extend([value, ""])
        else:
            lines.extend([*(f"- {item}" for item in value), ""])
    for state_section in template["state_sections"]:
        facet = state_section["facet"]
        items = [item for item in current if item["facet"] == facet]
        if not items:
            continue
        lines.extend([f"## {state_section['title']}", ""])
        for item in items:
            marker = ""
            if item["state_type"] == "hypothesis":
                marker = "（待确认）"
            lines.append(f"- {item['statement']}{marker}")
            audit = {
                "state_id": item["state_id"], "state_type": item["state_type"],
                "confidence": item["confidence"], "evidence_claim_ids": item["evidence_claim_ids"],
                "review_policy": item["review_policy"],
            }
            lines.append("  <!-- memory-state " + json.dumps(audit, ensure_ascii=False, separators=(",", ":")) + " -->")
        lines.append("")
    lines.extend(["## 演进记录", ""])
    used_claims = sorted(
        (claims[claim_id] for claim_id in {claim_id for item in state["state_items"] for claim_id in item["evidence_claim_ids"]}),
        key=lambda item: (item["valid_date"], item["claim_id"]), reverse=True,
    )
    for claim in used_claims:
        lines.append(f"### {claim['valid_date']}")
        lines.append("")
        lines.append(claim["summary"])
        lines.append("")
    projection = {
        "state_items": metrics["state_items"], "referenced_claims": metrics["referenced_claims"],
        "auto_eligible": metrics["auto_eligible"], "review_required": metrics["review_required"],
    }
    lines.append("<!-- memory-subject-projection " + json.dumps(projection, ensure_ascii=False, separators=(",", ":")) + " -->")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--reviewed", required=True, type=Path)
    parser.add_argument("--historical", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    layout = json.loads(args.layout.read_text(encoding="utf-8"))
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    subject_id = state["subject"]["subject_id"]
    registry_subject = next((item for item in registry["subjects"] if item["subject_id"] == subject_id), None)
    if registry_subject is None:
        raise ValueError(f"subject missing from registry: {subject_id}")
    template = layout["templates"].get(registry_subject["template"])
    if template is None:
        raise ValueError(f"template missing from layout: {registry_subject['template']}")
    reviewed = json.loads(args.reviewed.read_text(encoding="utf-8"))
    historical = json.loads(args.historical.read_text(encoding="utf-8")) if args.historical else None
    text = render(profile, state, VALIDATOR.claim_map(historical, reviewed), template)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(args.output)
    args.output.chmod(0o600)
    print(f"[✓] wrote living Memory Subject preview: {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"MEMORY_SUBJECT_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
