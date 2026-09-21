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

FACET_HEADINGS = {
    "phase": "当前阶段",
    "capability": "当前状态",
    "focus": "当前推进",
    "problem": "当前问题",
    "decision": "已确定事项",
    "goal": "长期目标",
    "open_question": "未确认事项",
    "next_action": "下一步",
    "milestone": "关键里程碑",
}
PROJECT_ORDER = ("phase", "capability", "goal", "decision", "focus", "problem", "open_question", "next_action", "milestone")


def render(state: dict[str, Any], claims: dict[str, dict[str, Any]]) -> str:
    metrics = VALIDATOR.validate(state, claims)
    subject = state["subject"]
    if subject["subject_type"] not in {"project", "system"}:
        raise ValueError("V1 renderer currently supports project/system only")
    current = [item for item in state["state_items"] if item["lifecycle"] in {"current", "reopened"}]
    lines = [
        "---",
        f"type: {subject['subject_type']}",
        f"subject_id: {subject['subject_id']}",
        f"as_of: {state['as_of']}",
        "projection: memory-subject-v1",
        "---",
        "",
        f"# {subject['canonical_name']}",
        "",
    ]
    for facet in PROJECT_ORDER:
        items = [item for item in current if item["facet"] == facet]
        if not items:
            continue
        lines.extend([f"## {FACET_HEADINGS[facet]}", ""])
        for item in items:
            marker = ""
            if item["state_type"] == "derived_state":
                marker = "（派生状态）"
            elif item["state_type"] == "hypothesis":
                marker = "（未确认）"
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
    parser.add_argument("--reviewed", required=True, type=Path)
    parser.add_argument("--historical", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    reviewed = json.loads(args.reviewed.read_text(encoding="utf-8"))
    historical = json.loads(args.historical.read_text(encoding="utf-8")) if args.historical else None
    text = render(state, VALIDATOR.claim_map(historical, reviewed))
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
