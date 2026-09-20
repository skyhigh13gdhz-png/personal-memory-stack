#!/usr/bin/env python3
"""Render a deterministic continuity-view preview from validated Claims."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("validate_golden_set", SCRIPT_DIR / "validate_golden_set.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VALIDATOR)

PREVIEW_VERSION = "subject-v1-preview.1"
KIND_LABELS = {
    "event": "事件",
    "state": "状态",
    "preference": "偏好",
    "decision": "决策",
    "commitment": "承诺",
    "metric": "指标",
}


def render(golden: dict[str, Any], subject_id: str) -> str:
    subjects = {item["subject_id"]: item for item in golden["subjects"]}
    if subject_id not in subjects:
        raise ValueError(f"unknown subject: {subject_id}")
    subject = subjects[subject_id]
    claims = sorted(
        (item for item in golden["claims"] if subject_id in item.get("subject_ids", [])),
        key=lambda item: (item["valid_date"], item["claim_id"]),
    )
    if not claims:
        raise ValueError(f"subject has no claims: {subject_id}")

    metadata = {
        "preview_version": PREVIEW_VERSION,
        "subject_id": subject_id,
        "subject_type": subject["subject_type"],
        "claim_count": len(claims),
    }
    lines = [
        f"# {subject['canonical_name']}",
        "",
        "> [!info] 本地评审预览",
        "> 只展示已确认 Claim 的连续脉络，不把最新事件自动升格为长期特征。",
        "",
        f"<!-- personal-memory-subject {json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))} -->",
        "",
        "## 跟踪边界",
        "",
        f"- **类型：** `{subject['subject_type']}`",
        f"- **晋升原因：** {subject['promotion_reason']}",
        "- **当前状态：** 未由单条记录自动推断，待人工评审。",
        "",
        "## 演进时间线",
        "",
    ]
    for claim in claims:
        kind = KIND_LABELS[claim["kind"]]
        lines.append(
            f"- **[[{claim['valid_date']} 日回顾|{claim['valid_date']}]]** "
            f"`{kind}` {claim['summary']} `[{claim['claim_id']}]`"
        )
    lines.extend([
        "",
        "## 未决问题",
        "",
        "- 哪些变化足以更新“当前状态”，必须在 Gate B 人工评审。",
        "",
        "## 来源",
        "",
    ])
    seen: set[tuple[str, str]] = set()
    for claim in claims:
        for evidence in claim["evidence"]:
            key = (evidence["document_id"], evidence["quote"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- 「{evidence['quote']}」 — `{evidence['document_id']}`")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("golden", type=Path)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    golden = VALIDATOR.load_json(args.golden)
    errors = VALIDATOR.validate(golden, base_dir=args.golden.parent)
    if errors:
        raise SystemExit("invalid golden set:\n" + "\n".join(f"- {item}" for item in errors))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(golden, args.subject), encoding="utf-8")
    print(f"[✓] wrote {PREVIEW_VERSION}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
