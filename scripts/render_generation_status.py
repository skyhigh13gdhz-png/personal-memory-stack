#!/usr/bin/env python3
"""Render a human-facing coverage and exception dashboard for the Obsidian projection."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


DATE_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def dated_files(directory: Path) -> dict[str, Path]:
    if not directory.exists():
        return {}
    return {path.stem: path for path in directory.glob("*.md") if DATE_FILE.match(path.name)}


def daily_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if '"template_version":"daily-v1"' in text:
        return "V1（待升级）"
    if text.startswith(f"# {path.stem} 日回顾"):
        return "V2"
    return "未识别"


def rejected_days(work_dir: Path | None) -> dict[str, str]:
    if work_dir is None or not work_dir.exists():
        return {}
    output = {}
    for path in work_dir.glob("????-??-??/editorial-rejected.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            output[path.parent.name] = str(payload.get("validation_error") or "未知错误")
        except (OSError, json.JSONDecodeError):
            output[path.parent.name] = "隔离件无法读取"
    return output


def render(raw_dir: Path, daily_dir: Path, work_dir: Path | None = None) -> str:
    raw = dated_files(raw_dir)
    daily = dated_files(daily_dir)
    versions = {day: daily_version(path) for day, path in daily.items()}
    missing = sorted(set(raw) - set(daily))
    orphaned = sorted(set(daily) - set(raw))
    old = sorted(day for day, version in versions.items() if version != "V2")
    rejected = rejected_days(work_dir)
    unresolved_rejected = {day: error for day, error in rejected.items() if day not in daily}
    healthy = not missing and not old and not unresolved_rejected
    lines = [
        "# 外置记忆运行状态",
        "",
        f"> 更新时间：{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "",
        "## 总览",
        "",
        f"- 当前状态：{'正常' if healthy else '需要处理'}",
        f"- 有原始记录的日期：{len(raw)}",
        f"- 已生成日报：{len(daily)}",
        f"- 缺失日报：{len(missing)}",
        f"- 非 Daily V2：{len(old)}",
        f"- 未解决隔离件：{len(unresolved_rejected)}",
        "",
        "## 需要关注",
        "",
    ]
    if healthy:
        lines.append("- 当前没有发现静默缺失、旧版日报或未解决隔离件。")
    else:
        lines.extend(f"- 缺失日报：[[../../01-日报/{day}|{day}]]" for day in missing)
        lines.extend(f"- 日报版本异常：{day}（{versions[day]}）" for day in old)
        lines.extend(f"- 生成隔离：{day} — {error}" for day, error in sorted(unresolved_rejected.items()))
    lines.extend(["", "## 日期覆盖", "", "| 日期 | 原始记录 | 日报 | 版本 |", "|---|---:|---:|---|"])
    for day in sorted(set(raw) | set(daily), reverse=True):
        raw_mark = "✓" if day in raw else "—"
        daily_mark = "✓" if day in daily else "缺失"
        lines.append(f"| {day} | {raw_mark} | {daily_mark} | {versions.get(day, '—')} |")
    if orphaned:
        lines.extend(["", "## 仅有日报、无原始投影", ""])
        lines.extend(f"- {day}" for day in orphaned)
    lines.extend([
        "",
        "---",
        "",
        "这是系统运行视图，不是个人记忆内容。生成失败不代表当天没有记录。",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--daily-dir", required=True, type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    content = render(args.raw_dir, args.daily_dir, args.work_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(args.output)
    print(f"[✓] wrote generation status: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
