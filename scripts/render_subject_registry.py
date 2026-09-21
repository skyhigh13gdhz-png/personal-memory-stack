#!/usr/bin/env python3
"""Render the config-driven Subject Registry as a human review page."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("memory_layout", SCRIPT_DIR / "memory_layout.py")
LAYOUT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(LAYOUT)


def render(layout: dict[str, Any], registry: dict[str, Any]) -> str:
    desired = LAYOUT.desired_paths(layout, registry)
    _, subjects = LAYOUT.validate(layout, registry)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for subject in subjects.values():
        grouped.setdefault(subject["collection"], []).append(subject)
    type_labels = {
        "project": "项目", "health_track": "健康主题", "long_term_topic": "长期主题",
        "person": "人物", "pet": "宠物", "account": "账户", "asset": "资产",
        "strategy": "策略", "component": "内部组件", "system": "系统", "goal": "目标",
    }
    lines = [
        "# 长期记忆对象登记表", "",
        "> 这是低频使用的系统治理页，不是日常阅读入口。平时请直接查看日报和各长期记忆页面。", "",
        "## 什么时候需要看", "",
        "- 准备把反复出现的内容升级为长期跟踪对象时。",
        "- 发现某个对象分类错误、放错目录或归属错误时。",
        "- 想合并、改名、归档某个长期对象，或检查为什么系统为它建页时。",
        "- 模板通常由分类自动选择，只有特殊对象才需要单独调整。", "",
        "## 当前对象", "",
    ]
    for collection, items in grouped.items():
        collection_path = layout["collections"][collection]
        lines.extend([f"### {Path(collection_path).name}", ""])
        for subject in sorted(items, key=lambda item: item["canonical_name"]):
            parent_id = subject.get("parent_subject_id")
            parent = subjects[parent_id]["canonical_name"] if parent_id else "独立对象"
            lines.extend([
                f"#### {subject['canonical_name']}", "",
                f"- 分类：{type_labels.get(subject['subject_type'], subject['subject_type'])}",
                f"- 归属：{parent}",
                f"- 存放位置：{Path(desired[subject['subject_id']]).parent}",
                f"- 为什么长期跟踪：{subject['promotion_reason']}",
                "<!-- subject-registry " + json.dumps({
                    "subject_id": subject["subject_id"], "subject_type": subject["subject_type"],
                    "template": subject["template"], "path": desired[subject["subject_id"]],
                }, ensure_ascii=False, separators=(",", ":")) + " -->", "",
            ])
    lines.extend([
        "## 尚未自动晋升的内容", "",
        "- Memory Gateway、Hindsight：目前作为“AI 外置记忆”的内部组件；只有形成独立生命周期和足够信息后才单独建页。",
        "- 老婆、猫咪：原始记录中已出现，但人物/宠物对象的边界、命名和隐私展示尚未确认，因此不自动晋升。",
        "- 交易账户、具体资产：与策略属于同一导航集合但不是同一类型；当前没有足够稳定资料，不创建空壳页面。",
        "", "## 调整原则", "",
        "- 新建：必须有明确名称、分类、长期跟踪理由和持续维护价值，不能只因正文提到一次就建页。",
        "- 改名或移动：只改变显示名称或位置，不把它误认为一个新对象。",
        "- 改归属：例如内部组件可归入所属项目，不必全部做成平级页面。",
        "- 归档：停止生成当前页面，但保留原始记录和历史变化。",
        "- 日常使用不需要手动修改本页；提出调整意图即可由系统校验并执行。", "",
        "<!-- subject-registry-projection " + json.dumps({
            "layout_version": layout["layout_version"], "projection": "subject-registry-review-v2",
        }, ensure_ascii=False, separators=(",", ":")) + " -->",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--subjects", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    text = render(LAYOUT.load(args.layout), LAYOUT.load(args.subjects))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(args.output)
    print(f"[✓] wrote Subject Registry review: {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"SUBJECT_REGISTRY_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
