#!/usr/bin/env python3
"""Render a local, deterministic daily-v2 preview from a validated golden set."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("validate_golden_set", SCRIPT_DIR / "validate_golden_set.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VALIDATOR)

PREVIEW_VERSION = "daily-v2-preview.1"
SECTION_ORDER = ("health", "projects", "trading", "life", "other")
SECTION_TITLES = {
    "health": "睡眠、身体与运动",
    "projects": "项目推进",
    "trading": "交易与策略",
    "life": "生活记录",
    "other": "其他",
}
SUBJECT_SECTION = {
    "health_track": "health",
    "habit": "health",
    "project": "projects",
    "system": "projects",
    "asset": "trading",
    "strategy": "trading",
}


def _section_for(claim: dict[str, Any], subjects: dict[str, dict[str, Any]]) -> str:
    for subject_id in claim.get("subject_ids", []):
        subject_type = subjects[subject_id]["subject_type"]
        if subject_type in SUBJECT_SECTION:
            return SUBJECT_SECTION[subject_type]
    if claim.get("kind") in {"event", "preference"}:
        return "life"
    return "other"


def render(golden: dict[str, Any], day: str) -> str:
    subjects = {item["subject_id"]: item for item in golden["subjects"]}
    documents = {item["document_id"]: item for item in golden["documents"]}
    claims = [item for item in golden["claims"] if item["valid_date"] == day]
    if not claims:
        raise ValueError(f"no claims for {day}")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    linked_subject_ids: list[str] = []
    for claim in claims:
        grouped[_section_for(claim, subjects)].append(claim)
        for subject_id in claim.get("subject_ids", []):
            if subject_id not in linked_subject_ids:
                linked_subject_ids.append(subject_id)

    canonical = json.dumps(claims, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    metadata = {
        "preview_version": PREVIEW_VERSION,
        "date": day,
        "claim_count": len(claims),
        "input_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }
    lines = [
        f"# {day} 日回顾",
        "",
        "> [!info] 本地评审预览",
        "> 基于人工确认的 Claim 生成，不作为原始记录，不反向写入记忆库。",
        "",
        f"<!-- personal-memory-preview {json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))} -->",
        "",
    ]
    if linked_subject_ids:
        links = " · ".join(f"[[{subjects[item]['canonical_name']}]]" for item in linked_subject_ids)
        lines.extend([f"**关联持续脉络：** {links}", ""])

    footnotes: list[str] = []
    for section in SECTION_ORDER:
        section_claims = grouped.get(section, [])
        if not section_claims:
            continue
        lines.extend([f"## {SECTION_TITLES[section]}", ""])
        for claim in section_claims:
            footnote_id = claim["claim_id"]
            status = claim["epistemic_status"]
            status_suffix = "" if status in {"asserted", "confirmed"} else f" `[{status}]`"
            lines.append(f"- {claim['summary']}{status_suffix}[^{footnote_id}]")
            refs = []
            for evidence in claim["evidence"]:
                document = documents[evidence["document_id"]]
                refs.append(
                    f"「{evidence['quote']}」"
                    f" — `{evidence['document_id']}` / {document['date']}"
                )
            footnotes.append(f"[^{footnote_id}]: " + "；".join(refs))
        lines.append("")

    lines.extend(["## 证据索引", "", *footnotes, ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("golden", type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    golden = VALIDATOR.load_json(args.golden)
    errors = VALIDATOR.validate(golden, base_dir=args.golden.parent)
    if errors:
        raise SystemExit("invalid golden set:\n" + "\n".join(f"- {item}" for item in errors))
    content = render(golden, args.date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print(f"[✓] wrote {PREVIEW_VERSION}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
