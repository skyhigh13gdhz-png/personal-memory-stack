#!/usr/bin/env python3
"""Render a human-first Subject continuity view from reviewed and historical Claims."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def collect(reviewed: dict[str, Any], historical: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if reviewed.get("schema_version") != "continuity-claims-v1":
        raise ValueError("reviewed input must be continuity-claims-v1")
    subject = reviewed["subject"]
    claims = list(reviewed.get("claims", []))
    if historical is not None:
        if historical.get("schema_version") != "golden-v1":
            raise ValueError("historical input must be golden-v1")
        historical_subject = next(
            (item for item in historical["subjects"] if item["subject_id"] == subject["subject_id"]), None
        )
        if historical_subject:
            for claim in historical["claims"]:
                if subject["subject_id"] not in claim.get("subject_ids", []):
                    continue
                role = "state" if claim["kind"] == "state" else "progress"
                claims.append({**claim, "role": role, "review_status": "historical_confirmed"})
    claims.sort(key=lambda item: (item["valid_date"], item["claim_id"]))
    return subject, claims


def render(reviewed: dict[str, Any], historical: dict[str, Any] | None = None) -> str:
    subject, claims = collect(reviewed, historical)
    lines = [
        f"# {subject['canonical_name']}",
        "",
        "> [!info] 持续脉络评审预览",
        "> 当前状态不会由单条事件自动改写；本页只展示有逐字证据的演进记录。",
        "",
        "## 当前状态",
        "",
        "- 待人工确认。现有事件只进入时间线，不自动升格为长期状态。",
        "",
    ]
    groups = (
        ("背景与边界", {"context"}),
        ("目标与需求", {"goal", "requirement"}),
        ("里程碑", {"milestone"}),
        ("决策与承诺", {"decision", "commitment"}),
        ("关键指标", {"metric"}),
    )
    for heading, roles in groups:
        role_claims = [claim for claim in claims if claim.get("role") in roles]
        if not role_claims:
            continue
        lines.extend([f"## {heading}", ""])
        for claim in role_claims:
            lines.append(f"- **{claim['valid_date']}：** {claim['summary']}")
            refs = ",".join(ref["document_id"] for ref in claim["evidence"])
            lines.append(f"  <!-- evidence {refs} -->")
        lines.append("")
    timeline_claims = [claim for claim in claims if claim.get("role") in {"progress", "state"}]
    lines.extend(["## 演进时间线", ""])
    for claim in timeline_claims:
        role_label = {
            "progress": "进展", "state": "状态", "milestone": "里程碑",
            "decision": "决策", "commitment": "承诺", "metric": "指标",
        }.get(claim.get("role"), "记录")
        lines.append(f"- **{claim['valid_date']} · {role_label}：** {claim['summary']}")
        refs = ",".join(ref["document_id"] for ref in claim["evidence"])
        lines.append(f"  <!-- evidence {refs} -->")
    lines.extend(["", "## 未决问题", ""])
    problems = [claim for claim in claims if claim.get("role") == "problem"]
    for claim in problems:
        lines.append(f"- **{claim['valid_date']}：** {claim['summary']}")
        refs = ",".join(ref["document_id"] for ref in claim["evidence"])
        lines.append(f"  <!-- evidence {refs} -->")
    if not problems:
        lines.append("- 哪些进展足以改变“当前状态”，仍需人工确认。")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reviewed", type=Path)
    parser.add_argument("--historical", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    reviewed = json.loads(args.reviewed.read_text(encoding="utf-8"))
    historical = json.loads(args.historical.read_text(encoding="utf-8")) if args.historical else None
    text = render(reviewed, historical)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(args.output)
    args.output.chmod(0o600)
    print(f"[✓] wrote continuity view: {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"CONTINUITY_VIEW_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
