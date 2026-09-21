#!/usr/bin/env python3
"""Render the config-driven Subject Registry as a human review page."""

from __future__ import annotations

import argparse
import importlib.util
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
    lines = [
        "---", "type: subject-registry-review", f"layout_version: {layout['layout_version']}",
        "projection: subject-registry-review-v1", "---", "", "# 长期记忆对象登记表", "",
        "> 这是配置生成的审阅视图。Subject 类型、导航目录和父子关系是三个独立维度。", "",
        "## 当前对象", "",
    ]
    for collection, items in grouped.items():
        collection_path = layout["collections"][collection]
        lines.extend([f"### {Path(collection_path).name}", ""])
        for subject in sorted(items, key=lambda item: item["canonical_name"]):
            parent = subject.get("parent_subject_id") or "无"
            lines.extend([
                f"#### {subject['canonical_name']}", "",
                f"- 类型：`{subject['subject_type']}`",
                f"- 模板：`{subject['template']}`",
                f"- 父对象：`{parent}`",
                f"- 目标页面：`{desired[subject['subject_id']]}`",
                f"- 晋升依据：{subject['promotion_reason']}", "",
            ])
    lines.extend([
        "## 尚未自动晋升的内容", "",
        "- Memory Gateway、Hindsight：目前作为“AI 外置记忆”的内部组件；只有形成独立生命周期和足够信息后才单独建页。",
        "- 老婆、猫咪：原始记录中已出现，但人物/宠物对象的边界、命名和隐私展示尚未确认，因此不自动晋升。",
        "- 交易账户、具体资产：与策略属于同一导航集合但不是同一类型；当前没有足够稳定资料，不创建空壳页面。",
        "", "## 变更规则", "",
        "- 改目录：调整 Layout 的 `collections` 或 Registry 的 `collection`。",
        "- 改模板：修改 Registry 的 `template`，必须通过类型兼容校验。",
        "- 改从属：修改 `parent_subject_id`；永久 `subject_id` 不变。",
        "- 新建对象：必须有明确名称、类型、晋升依据和持续维护价值，禁止仅因正文提到一次就建页。",
        "- 删除对象：先归档或解除投影，不删除证据和历史状态。", "",
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
