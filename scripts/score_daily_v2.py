#!/usr/bin/env python3
"""Score a Daily V2 package and block outputs below the product threshold."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("render_daily_v2_editorial", SCRIPT_DIR / "render_daily_v2_editorial.py")
EDITORIAL = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(EDITORIAL)

SCORE_VERSION = "daily-v2-score.1"
PASS_SCORE = 85
GENERIC_LABELS = {"记录", "情况", "内容", "事项", "相关", "其他"}


def _items(editorial: dict[str, Any]):
    for section in editorial.get("sections", []):
        if not isinstance(section, dict):
            continue
        for group in section.get("groups", []):
            if not isinstance(group, dict):
                continue
            for item in group.get("items", []):
                if isinstance(item, dict):
                    yield section, group, item


def score(editorial: dict[str, Any], classified: dict[str, Any], style: dict[str, Any]) -> dict[str, Any]:
    day = editorial.get("date")
    source_units = {
        unit["unit_id"]: unit for unit in classified.get("units", [])
        if unit.get("date") == day and unit.get("visibility") in {"daily", "both"}
    }
    sections = [section for section in editorial.get("sections", []) if isinstance(section, dict)]
    items = list(_items(editorial))
    refs = [unit_id for _, _, item in items for unit_id in item.get("evidence_unit_ids", [])]
    known_refs = {unit_id for unit_id in refs if unit_id in source_units}
    source_count = max(len(source_units), 1)

    structural_errors: list[str] = []
    try:
        EDITORIAL.validate(editorial, classified)
    except ValueError as exc:
        structural_errors = str(exc).split("; ")

    valid_sections = [section for section in sections if section.get("section_id") in EDITORIAL.SECTION_TITLES]
    unique_sections = {section.get("section_id") for section in valid_sections}
    project_groups = [
        group for section in valid_sections if section.get("section_id") == "project_work"
        for group in section.get("groups", []) if isinstance(group, dict) and group.get("group_kind") == "facts"
    ]
    project_group_ok = all(isinstance(group.get("title"), str) and group["title"].strip() for group in project_groups)

    source_text = "\n".join(unit.get("text", "") for unit in source_units.values())
    output_text = "\n".join(str(item.get("text", "")) for _, _, item in items)
    avoid_terms = [term for term in style.get("avoid_terms", []) if term and term in output_text]
    expected_preserved = [term for term in style.get("preserve_terms", []) if term and term in source_text]
    missing_preserved = [term for term in expected_preserved if term not in output_text]

    invalid_analysis = 0
    for _, group, item in items:
        status = item.get("analysis_status")
        if group.get("group_kind") == "facts" and status in {"observation", "inference"}:
            invalid_analysis += 1
        if status == "calculated" and len(item.get("evidence_unit_ids", [])) < 2:
            invalid_analysis += 1
        if status == "inference" and item.get("uncertainty") is not True:
            invalid_analysis += 1

    generic_labels = [item.get("label") for _, _, item in items if item.get("label") in GENERIC_LABELS]
    dimensions = {
        "evidence_integrity": round(35 * len(known_refs) / source_count),
        "information_architecture": (
            round(15 * len(valid_sections) / max(len(sections), 1))
            + (5 if len(valid_sections) == len(unique_sections) else 0)
            + (5 if project_group_ok else 0)
        ),
        "analysis_integrity": max(0, 15 - invalid_analysis * 5),
        "language_style": max(0, 15 - len(avoid_terms) * 5 - len(missing_preserved) * 3),
        "readability": max(0, 10 - len(generic_labels) * 2),
    }
    total = sum(dimensions.values())
    hard_failures = list(structural_errors)
    if avoid_terms:
        hard_failures.append(f"forbidden style terms: {avoid_terms}")
    if missing_preserved:
        hard_failures.append(f"missing preserved terms: {missing_preserved}")
    passed = not hard_failures and total >= PASS_SCORE
    return {
        "score_version": SCORE_VERSION,
        "score": total,
        "pass_score": PASS_SCORE,
        "passed": passed,
        "dimensions": dimensions,
        "diagnostics": {
            "source_units": len(source_units),
            "referenced_units": len(known_refs),
            "forbidden_terms": avoid_terms,
            "missing_preserved_terms": missing_preserved,
            "generic_labels": generic_labels,
            "structural_errors": structural_errors,
        },
        "hard_failures": hard_failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("editorial", type=Path)
    parser.add_argument("--classified", required=True, type=Path)
    parser.add_argument("--style", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = score(
        json.loads(args.editorial.read_text(encoding="utf-8")),
        json.loads(args.classified.read_text(encoding="utf-8")),
        json.loads(args.style.read_text(encoding="utf-8")),
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
