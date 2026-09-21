#!/usr/bin/env python3
"""Render a human review page for LLM-refined continuity Claim drafts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROLE_LABELS = {
    "context": "背景与边界", "goal": "目标", "requirement": "需求",
    "problem": "问题", "progress": "进展", "milestone": "里程碑",
    "decision": "决策", "commitment": "承诺", "state": "状态", "metric": "指标",
}


def render(refinement: dict[str, Any], source: dict[str, Any]) -> str:
    if refinement.get("schema_version") != "continuity-refinement-v1":
        raise ValueError("input must be continuity-refinement-v1")
    candidate_map = {
        item["candidate_id"]: item
        for entry in source.get("subjects", []) for item in entry.get("candidates", [])
    }
    metrics = refinement["metrics"]
    lines = [
        "# 持续脉络 Claim 草稿评审", "",
        "> [!warning] 这是精炼后的草稿，不是已确认长期结论",
        "> 所有 Claim 均有逐字证据，但尚未更新正式 Subject 当前状态。", "",
        "## 全局结果", "",
        f"- 输入候选关联：{metrics['input_candidate_links']}",
        f"- 草稿 Claim：{metrics['draft_claims']}",
        f"- 拒绝：{metrics['rejected']}",
        f"- 暂缓：{metrics['held']}",
        f"- 漏处理：{metrics['unreviewed']}", "",
    ]
    for reviewed in refinement["reviewed_subjects"]:
        subject = reviewed["subject"]
        lines.extend([f"## {subject['canonical_name']}", ""])
        grouped: dict[str, list[dict[str, Any]]] = {}
        for claim in reviewed["claims"]:
            grouped.setdefault(claim["role"], []).append(claim)
        for role, claims in grouped.items():
            lines.extend([f"### {ROLE_LABELS.get(role, role)}", ""])
            for claim in claims:
                quote = claim["evidence"][0]["quote"]
                lines.extend([
                    f"- **{claim['valid_date']}** {claim['summary']}",
                    f"  - 原文：「{quote}」",
                    f"  <!-- claim {claim['claim_id']} -->",
                ])
            lines.append("")
        if reviewed["rejected"]:
            lines.extend(["### 已拒绝的误关联", ""])
            for rejected in reviewed["rejected"]:
                candidate = candidate_map.get(rejected["candidate_id"], {})
                lines.append(f"- {candidate.get('original_text', rejected['candidate_id'])}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("refinement", type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    text = render(
        json.loads(args.refinement.read_text(encoding="utf-8")),
        json.loads(args.source.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"[✓] wrote refinement review: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
