#!/usr/bin/env python3
"""Prepare, validate, cache, or run a daily-view-v2 editorial generation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CLAIMS = load_module("claim_candidate_pipeline", SCRIPT_DIR / "claim_candidate_pipeline.py")
EDITORIAL = load_module("render_daily_v2_editorial", SCRIPT_DIR / "render_daily_v2_editorial.py")
PROMPT_VERSION = "daily-editorial-v2"


def load_classified(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "classified-evidence-v1":
        raise ValueError("input must be classified-evidence-v1")
    return value


def alias_units(classified: dict[str, Any], day: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    visible = [
        unit for unit in classified["units"]
        if unit["date"] == day and unit["visibility"] in {"daily", "both"}
    ]
    aliases = {f"u{index:02d}": unit["unit_id"] for index, unit in enumerate(visible, start=1)}
    reverse = {unit_id: alias for alias, unit_id in aliases.items()}
    payload = [{
        "id": reverse[unit["unit_id"]],
        "text": unit["text"],
        "current_category": unit["category"],
        "current_summary": unit["summary"],
        "subject_ids": unit["subject_ids"],
    } for unit in visible]
    return payload, aliases


def messages(classified: dict[str, Any], day: str, style: dict[str, Any]) -> list[dict[str, str]]:
    units, _ = alias_units(classified, day)
    return [
        {
            "role": "system",
            "content": (
                "你是个人日报编辑，不是事实抽取器。输入单元已通过证据校验，必须让每个 id 至少出现在一个"
                "evidence_unit_ids 中。按栏目→具体项目/子主题→语义标签形成总分结构；同项目内容合并去重。"
                "一个单元跨两个事实条目使用时，这些条目都必须 facet_split=true。保留用户稳定用词和领域术语，"
                "不要改成公文腔。不得增加原文没有的结果、动机或因果。程序可直接计算的内容标"
                "analysis_status=calculated；跨单元归纳标 observation；推断标 inference 且 uncertainty=true，"
                "正文必须明确不确定性。没有内容的栏目或字段不要生成。项目归组不等于创建长期 Subject。"
                "只返回 daily-view-v2 JSON：{schema_version,date,sections:[{title,number_groups?,groups:["
                "{title?,items:[{label,text,evidence_unit_ids,facet_split?,analysis_status?,uncertainty?}]}]}]}。"
                "evidence_unit_ids 只能使用输入短 ID，不输出解释。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps({
                "date": day,
                "style": style,
                "confirmed_subjects": classified.get("subjects", []),
                "units": units,
            }, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def expand_aliases(editorial: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    expanded = json.loads(json.dumps(editorial, ensure_ascii=False))
    for section in expanded.get("sections", []):
        for group in section.get("groups", []):
            for item in group.get("items", []):
                refs = item.get("evidence_unit_ids", [])
                unknown = [unit_id for unit_id in refs if unit_id not in aliases]
                if unknown:
                    raise ValueError(f"unknown short unit ids: {unknown}")
                item["evidence_unit_ids"] = [aliases[unit_id] for unit_id in refs]
    return expanded


def source_hash(classified: dict[str, Any], day: str, style: dict[str, Any], model: str) -> str:
    units, _ = alias_units(classified, day)
    canonical = json.dumps({
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "date": day,
        "style": style,
        "units": units,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def package(editorial: dict[str, Any], classified: dict[str, Any], *, run: dict[str, Any]) -> dict[str, Any]:
    metrics = EDITORIAL.validate(editorial, classified)
    return {
        **editorial,
        "generation": run,
        "validation": metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "extract"):
        child = subparsers.add_parser(command)
        child.add_argument("classified", type=Path)
        child.add_argument("--date", required=True)
        child.add_argument("--style", required=True, type=Path)
        child.add_argument("--output", required=True, type=Path)
        if command == "prepare":
            child.add_argument("--response", required=True, type=Path)
    args = parser.parse_args()
    classified = load_classified(args.classified)
    style = json.loads(args.style.read_text(encoding="utf-8"))
    _, aliases = alias_units(classified, args.date)
    if args.command == "prepare":
        response = json.loads(args.response.read_text(encoding="utf-8"))
        editorial = expand_aliases(response, aliases)
        result = package(editorial, classified, run={
            "mode": "offline-response", "calls": 0, "prompt_version": PROMPT_VERSION
        })
    else:
        api_key = os.environ.get("DAILY_V2_LLM_API_KEY") or os.environ.get(
            "HINDSIGHT_API_RETAIN_LLM_API_KEY", ""
        )
        base_url = os.environ.get("DAILY_V2_LLM_BASE_URL") or os.environ.get(
            "HINDSIGHT_API_RETAIN_LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
        )
        model = os.environ.get("DAILY_V2_LLM_MODEL") or os.environ.get(
            "HINDSIGHT_API_RETAIN_LLM_MODEL", "glm-4.5-air"
        )
        if not api_key:
            raise SystemExit("missing DAILY_V2_LLM_API_KEY/HINDSIGHT_API_RETAIN_LLM_API_KEY")
        digest = source_hash(classified, args.date, style, model)
        if args.output.exists():
            current = json.loads(args.output.read_text(encoding="utf-8"))
            if current.get("generation", {}).get("input_hash") == digest:
                print(f"[=] unchanged daily-v2 input; skipped LLM: {args.output}")
                return 0
        response, metrics = CLAIMS.request_llm(base_url, api_key, model, messages(classified, args.date, style))
        editorial = expand_aliases(response, aliases)
        result = package(editorial, classified, run={
            "mode": "live", "calls": 1, "prompt_version": PROMPT_VERSION,
            "model": model, "input_hash": digest, **metrics,
        })
    CLAIMS.write_json_atomic(args.output, result)
    print(f"[✓] wrote validated daily-v2 editorial package: {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"DAILY_V2_PIPELINE_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
