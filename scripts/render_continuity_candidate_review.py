#!/usr/bin/env python3
"""Render a human review sheet for continuity candidates without changing Subject state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def render(bundle: dict[str, Any]) -> str:
    if bundle.get("schema_version") != "continuity-candidates-v1":
        raise ValueError("input must be continuity-candidates-v1")
    lines = [
        "# 持续脉络候选评审",
        "",
        "> [!warning] 候选证据，不是长期结论",
        "> 本页不会自动更新 Subject 当前状态；勾选只代表进入下一步 Claim 评审。",
        "",
    ]
    for entry in bundle.get("subjects", []):
        subject = entry["subject"]
        candidates = entry["candidates"]
        lines.extend([
            f"## {subject['canonical_name']}",
            "",
            f"- 类型：`{subject['subject_type']}`",
            f"- 晋升原因：{subject['promotion_reason']}",
            f"- 待评审证据：{len(candidates)} 条",
            "",
        ])
        if not candidates:
            lines.extend(["_当前没有关联证据。_", ""])
            continue
        current_date = None
        for candidate in candidates:
            if candidate["valid_date"] != current_date:
                current_date = candidate["valid_date"]
                lines.extend([f"### {current_date}", ""])
            lines.append(f"- [ ] {candidate['original_text']}")
            lines.append(f"  <!-- evidence {candidate['evidence_unit_id']} -->")
        lines.append("")
    metrics = bundle["metrics"]
    lines.extend([
        "## 生成边界",
        "",
        f"- 已确认 Subject：{metrics['confirmed_subjects']}",
        f"- 候选关联：{metrics['candidate_links']}",
        f"- 唯一 Evidence Units：{metrics['unique_evidence_units']}",
        "- LLM 调用：0",
        "- 当前状态更新：0",
    ])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    value = json.loads(args.bundle.read_text(encoding="utf-8"))
    text = render(value)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(args.output)
    args.output.chmod(0o600)
    print(f"[✓] wrote continuity candidate review: {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"CONTINUITY_REVIEW_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
