#!/usr/bin/env python3
"""Render a complete daily review from classified evidence units."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


SECTION_ORDER = (
    "sleep_body", "food", "exercise", "work_project", "trading_finance",
    "relationships_home", "pet", "leisure", "other",
)
SECTION_TITLES = {
    "sleep_body": "睡眠与身体",
    "food": "饮食与消费",
    "exercise": "运动",
    "work_project": "项目与工作",
    "trading_finance": "交易与财务",
    "relationships_home": "关系与家庭",
    "pet": "宠物",
    "leisure": "休闲",
    "other": "未分类原文",
}


def load_classified(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != "classified-evidence-v1":
        raise ValueError("input must be classified-evidence-v1")
    return value


def render(value: dict[str, Any], day: str) -> str:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    visible_units = [
        unit for unit in value["units"]
        if unit["date"] == day and unit["visibility"] in {"daily", "both"}
    ]
    for unit in visible_units:
        grouped[unit["category"]].append(unit)
    if not any(grouped.values()):
        raise ValueError(f"no daily units for {day}")
    classified_count = sum(unit["classification_status"] == "classified" for unit in visible_units)
    fallback_count = len(visible_units) - classified_count
    lines = [
        f"# {day} 日回顾",
        "",
        "> [!info] Evidence Unit 预览",
        f"> 当日显示 {len(visible_units)} 个单元；已分类 {classified_count}，"
        f"原文回退 {fallback_count}。未分类不等于丢失。",
        "",
    ]
    for section in SECTION_ORDER:
        units = grouped.get(section, [])
        if not units:
            continue
        lines.extend([f"## {SECTION_TITLES[section]}", ""])
        for unit in units:
            status = "" if unit["classification_status"] == "classified" else " `unclassified`"
            lines.append(f"- {unit['summary']}{status} [^{unit['unit_id']}]")
        lines.append("")
    lines.extend(["## 证据索引", ""])
    for unit in visible_units:
        lines.append(
            f"[^{unit['unit_id']}]: 「{unit['text']}」 — `{unit['document_id']}` "
            f"chars {unit['start']}:{unit['end']}"
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("classified", type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = render(load_classified(args.classified), args.date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(output, encoding="utf-8")
    temporary.replace(args.output)
    args.output.chmod(0o600)
    print(f"[✓] wrote Evidence Unit daily preview: {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"UNIT_DAILY_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
