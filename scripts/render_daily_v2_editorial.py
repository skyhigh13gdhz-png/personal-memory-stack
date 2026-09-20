#!/usr/bin/env python3
"""Validate and render a human-first daily-v2 editorial document."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "daily-view-v2"
ANALYSIS_STATUSES = {"calculated", "observation", "inference"}
SECTION_TITLES = {
    "sleep": "睡眠",
    "food": "饮食与消费",
    "exercise": "运动",
    "project_work": "项目与工作",
    "trading_finance": "交易与财务",
    "relationships_home": "关系与家庭",
    "pet": "宠物",
    "leisure": "休闲",
    "other": "其他",
}
SECTION_ORDER = tuple(SECTION_TITLES)
CATEGORY_SECTION = {
    "sleep_body": "sleep",
    "food": "food",
    "exercise": "exercise",
    "work_project": "project_work",
    "trading_finance": "trading_finance",
    "relationships_home": "relationships_home",
    "pet": "pet",
    "leisure": "leisure",
    "other": "other",
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def validate(editorial: dict[str, Any], classified: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if editorial.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    day = editorial.get("date")
    if not isinstance(day, str) or not day:
        errors.append("date is required")
    source_units = {
        unit["unit_id"]: unit for unit in classified.get("units", [])
        if unit.get("date") == day and unit.get("visibility") in {"daily", "both"}
    }
    referenced: list[str] = []
    reference_items: dict[str, list[dict[str, Any]]] = {}
    reference_sections: dict[str, set[str]] = {}
    sections = editorial.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append("sections must be a non-empty array")
        sections = []
    seen_sections = set()
    for section_index, section in enumerate(sections):
        if not isinstance(section, dict) or section.get("section_id") not in SECTION_TITLES:
            errors.append(f"sections[{section_index}] requires valid section_id")
            continue
        section_id = section["section_id"]
        if section_id in seen_sections:
            errors.append(f"duplicate section_id {section_id}")
        seen_sections.add(section_id)
        groups = section.get("groups")
        if not isinstance(groups, list) or not groups:
            errors.append(f"sections[{section_index}].groups must be non-empty")
            continue
        for group_index, group in enumerate(groups):
            items = group.get("items") if isinstance(group, dict) else None
            group_kind = group.get("group_kind") if isinstance(group, dict) else None
            if group_kind not in {"facts", "analysis"}:
                errors.append(f"sections[{section_index}].groups[{group_index}].group_kind is invalid")
            if section_id == "project_work" and group_kind == "facts" and not group.get("title"):
                errors.append(f"sections[{section_index}].groups[{group_index}] project facts require title")
            if not isinstance(items, list) or not items:
                errors.append(f"sections[{section_index}].groups[{group_index}].items must be non-empty")
                continue
            for item_index, item in enumerate(items):
                path = f"sections[{section_index}].groups[{group_index}].items[{item_index}]"
                if not isinstance(item, dict):
                    errors.append(f"{path} must be an object")
                    continue
                if not isinstance(item.get("label"), str) or not item["label"].strip():
                    errors.append(f"{path}.label is required")
                if not isinstance(item.get("text"), str) or not item["text"].strip():
                    errors.append(f"{path}.text is required")
                refs = item.get("evidence_unit_ids")
                if not isinstance(refs, list) or not refs:
                    errors.append(f"{path}.evidence_unit_ids must be non-empty")
                    continue
                status = item.get("analysis_status")
                if status is not None and status not in ANALYSIS_STATUSES:
                    errors.append(f"{path}.analysis_status is invalid")
                if group_kind == "facts" and status in {"observation", "inference"}:
                    errors.append(f"{path} observation/inference must be in analysis group")
                if group_kind == "analysis" and status not in ANALYSIS_STATUSES:
                    errors.append(f"{path} analysis item requires analysis_status")
                if status == "calculated" and len(refs) < 2:
                    errors.append(f"{path} calculated item requires at least two evidence units")
                if status == "inference" and not item.get("uncertainty"):
                    errors.append(f"{path}.uncertainty is required for inference")
                for unit_id in refs:
                    if unit_id not in source_units:
                        errors.append(f"{path} references unknown or invisible unit {unit_id}")
                    referenced.append(unit_id)
                    reference_items.setdefault(unit_id, []).append(item)
                    reference_sections.setdefault(unit_id, set()).add(section_id)
    missing = sorted(set(source_units) - set(referenced))
    if missing:
        errors.append(f"daily units without editorial destination: {missing}")
    for unit_id, unit in source_units.items():
        expected = CATEGORY_SECTION.get(unit.get("category"), "other")
        if unit_id in reference_sections and expected not in reference_sections[unit_id]:
            errors.append(f"unit {unit_id} must appear in primary section {expected}")
    for unit_id, count in Counter(referenced).items():
        fact_items = [item for item in reference_items[unit_id] if item.get("analysis_status") is None]
        if len(fact_items) > 1 and not all(item.get("facet_split") is True for item in fact_items):
            errors.append(f"repeated unit {unit_id} requires facet_split=true on every use")
    if errors:
        raise ValueError("; ".join(errors))
    return {"daily_units": len(source_units), "referenced_units": len(set(referenced)), "references": len(referenced)}


def render(editorial: dict[str, Any], classified: dict[str, Any], *, audit_details: bool = False) -> str:
    metrics = validate(editorial, classified)
    unit_map = {unit["unit_id"]: unit for unit in classified["units"]}
    lines = [f"# {editorial['date']} 日回顾", ""]
    sections = sorted(editorial["sections"], key=lambda item: SECTION_ORDER.index(item["section_id"]))
    for section in sections:
        lines.extend([f"## {SECTION_TITLES[section['section_id']]}", ""])
        numbered_groups = section["section_id"] == "project_work"
        for group_index, group in enumerate(section["groups"], start=1):
            if group.get("title"):
                prefix = f"{group_index}. " if numbered_groups else ""
                lines.extend([f"### {prefix}{group['title']}", ""])
            for item in group["items"]:
                suffix = ""
                if item.get("analysis_status") == "calculated":
                    suffix = " `计算`" if audit_details else ""
                elif item.get("analysis_status") == "observation":
                    suffix = " `观察`" if audit_details else ""
                elif item.get("analysis_status") == "inference":
                    suffix = " `推测`" if audit_details else ""
                lines.append(f"- {item['label']}：{item['text']}{suffix}")
                refs = item["evidence_unit_ids"]
                if audit_details:
                    lines.append("  - 证据：" + "、".join(f"[^{unit_id}]" for unit_id in refs))
                else:
                    lines.append("  <!-- evidence " + ",".join(refs) + " -->")
            lines.append("")
    if audit_details:
        lines.extend([
            "## 生成审计",
            "",
            f"- 日报单元覆盖：{metrics['referenced_units']}/{metrics['daily_units']}",
            f"- 条目证据引用：{metrics['references']}",
            "",
            "## 证据索引",
            "",
        ])
        used = {unit_id for section in editorial["sections"] for group in section["groups"]
                for item in group["items"] for unit_id in item["evidence_unit_ids"]}
        for unit_id in sorted(used):
            unit = unit_map[unit_id]
            lines.append(
                f"[^{unit_id}]: 「{unit['text']}」 — `{unit['document_id']}` "
                f"chars {unit['start']}:{unit['end']}"
            )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("editorial", type=Path)
    parser.add_argument("--classified", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit-details", action="store_true")
    args = parser.parse_args()
    editorial = load_json(args.editorial)
    classified = load_json(args.classified)
    output = render(editorial, classified, audit_details=args.audit_details)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(output, encoding="utf-8")
    temporary.replace(args.output)
    args.output.chmod(0o600)
    print(f"[✓] wrote daily-v2 editorial view: {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"DAILY_V2_EDITORIAL_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
