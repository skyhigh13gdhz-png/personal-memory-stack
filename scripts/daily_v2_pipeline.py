#!/usr/bin/env python3
"""Prepare, validate, cache, or run a daily-view-v2 editorial generation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from collections import Counter
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
SCORER = load_module("score_daily_v2", SCRIPT_DIR / "score_daily_v2.py")
PROMPT_VERSION = "daily-editorial-v2.1"
CATEGORY_SECTION = EDITORIAL.CATEGORY_SECTION
CATEGORY_LABEL = {
    "sleep_body": "补充记录", "food": "饮食记录", "exercise": "运动记录",
    "work_project": "项目记录", "trading_finance": "交易记录",
    "relationships_home": "家庭记录", "pet": "宠物记录", "leisure": "休闲记录", "other": "其他记录",
}


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
                "一级栏目只能使用固定 section_id：sleep/food/exercise/project_work/trading_finance/"
                "relationships_home/pet/leisure/other；显示标题由程序决定。所有项目必须归入 project_work，"
                "并以具体项目名建立 facts group，不能把某个项目提升为一级栏目。"
                "一个单元跨两个事实条目使用时，这些条目都必须 facet_split=true。保留用户稳定用词和领域术语，"
                "不要改成公文腔。不得增加原文没有的结果、动机或因果。程序可直接计算的内容标"
                "analysis_status=calculated；跨单元归纳标 observation；推断标 inference 且 uncertainty=true。"
                "原始事实必须放在 group_kind=facts 且不得设置 analysis_status；只有同时基于至少两个单元的"
                "直接计算可以留在 facts group 并标 calculated；观察/推断必须放在 group_kind=analysis，"
                "正文必须明确不确定性。没有内容的栏目或字段不要生成。项目归组不等于创建长期 Subject。"
                "只返回 daily-view-v2 JSON：{schema_version,date,sections:[{section_id,groups:["
                "{group_kind,title?,items:[{label,text,evidence_unit_ids,facet_split?,analysis_status?,uncertainty?}]}]}]}。"
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


def repair_messages(
    classified: dict[str, Any], day: str, style: dict[str, Any], draft: dict[str, Any], error: Exception,
    aliases: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    base = messages(classified, day, style)
    error_text = str(error)
    if aliases:
        for short_id, full_id in sorted(aliases.items(), key=lambda item: len(item[1]), reverse=True):
            error_text = error_text.replace(full_id, short_id)
    base.extend([
        {"role": "assistant", "content": json.dumps(draft, ensure_ascii=False, separators=(",", ":"))},
        {
            "role": "user",
            "content": (
                "上一版未通过程序校验。只修正下列问题，仍返回完整 daily-view-v2 JSON，"
                "不得删除已有合法事实，不得虚构：" + error_text
            ),
        },
    ])
    return base


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


def normalize_editorial_structure(editorial: dict[str, Any]) -> dict[str, Any]:
    """Repair schema-preserving presentation defects without changing facts."""
    normalized = json.loads(json.dumps(editorial, ensure_ascii=False))
    sections = []
    fact_references: list[str] = []
    for section in normalized.get("sections", []):
        groups = []
        for group in section.get("groups", []):
            items = group.get("items")
            if not isinstance(items, list) or not items:
                continue
            groups.append(group)
            if group.get("group_kind") == "facts":
                for item in items:
                    if item.get("analysis_status") is None:
                        fact_references.extend(item.get("evidence_unit_ids", []))
        if groups:
            section["groups"] = groups
            sections.append(section)
    normalized["sections"] = sections
    repeated = {unit_id for unit_id, count in Counter(fact_references).items() if count > 1}
    if repeated:
        for section in sections:
            for group in section["groups"]:
                if group.get("group_kind") != "facts":
                    continue
                for item in group["items"]:
                    if item.get("analysis_status") is None and repeated.intersection(item.get("evidence_unit_ids", [])):
                        item["facet_split"] = True
    return normalized


def complete_small_omissions(
    editorial: dict[str, Any], classified: dict[str, Any], *, max_missing: int = 3
) -> dict[str, Any]:
    """Deterministically retain a few model-omitted facts in their classified section."""
    completed = json.loads(json.dumps(editorial, ensure_ascii=False))
    referenced: set[str] = set()
    reference_sections: dict[str, set[str]] = {}
    for section in completed.get("sections", []):
        for group in section.get("groups", []):
            for item in group.get("items", []):
                for unit_id in item.get("evidence_unit_ids", []):
                    referenced.add(unit_id)
                    reference_sections.setdefault(unit_id, set()).add(section["section_id"])
    day = completed.get("date")
    visible = [
        unit for unit in classified.get("units", [])
        if unit.get("date") == day and unit.get("visibility") in {"daily", "both"}
    ]
    missing = [unit for unit in visible if unit["unit_id"] not in referenced]
    misplaced = [
        unit for unit in visible if unit["unit_id"] in referenced
        and CATEGORY_SECTION.get(unit.get("category", "other"), "other")
        not in reference_sections.get(unit["unit_id"], set())
    ]
    additions = missing + misplaced
    if not additions or len(additions) > max_missing:
        return completed
    section_map = {section["section_id"]: section for section in completed.get("sections", [])}
    subject_names = {item["subject_id"]: item["canonical_name"] for item in classified.get("subjects", [])}
    for unit in additions:
        category = unit.get("category", "other")
        section_id = CATEGORY_SECTION.get(category, "other")
        section = section_map.get(section_id)
        if section is None:
            section = {"section_id": section_id, "groups": []}
            completed.setdefault("sections", []).append(section)
            section_map[section_id] = section
        facts = [group for group in section["groups"] if group.get("group_kind") == "facts"]
        if section_id == "project_work":
            title = next((subject_names[item] for item in unit.get("subject_ids", []) if item in subject_names), "其他项目")
            group = next((item for item in facts if item.get("title") == title), None)
            if group is None:
                group = {"group_kind": "facts", "title": title, "items": []}
                section["groups"].append(group)
        else:
            group = facts[0] if facts else None
            if group is None:
                group = {"group_kind": "facts", "items": []}
                section["groups"].insert(0, group)
        new_item = {
            "label": CATEGORY_LABEL.get(category, "补充记录"),
            "text": unit.get("summary") or unit["text"],
            "evidence_unit_ids": [unit["unit_id"]],
        }
        if unit in misplaced:
            new_item["facet_split"] = True
            for existing_section in completed.get("sections", []):
                for existing_group in existing_section.get("groups", []):
                    if existing_group.get("group_kind") != "facts":
                        continue
                    for existing_item in existing_group.get("items", []):
                        if unit["unit_id"] in existing_item.get("evidence_unit_ids", []):
                            existing_item["facet_split"] = True
        group["items"].append(new_item)
    return completed


def apply_style_replacements(editorial: dict[str, Any], style: dict[str, Any]) -> dict[str, Any]:
    replaced = json.loads(json.dumps(editorial, ensure_ascii=False))
    replacements = style.get("replacements", {})
    if not isinstance(replacements, dict):
        return replaced
    for section in replaced.get("sections", []):
        for group in section.get("groups", []):
            for item in group.get("items", []):
                for field in ("label", "text"):
                    value = item.get(field)
                    if not isinstance(value, str):
                        continue
                    for source, target in replacements.items():
                        if isinstance(source, str) and isinstance(target, str):
                            value = value.replace(source, target)
                    item[field] = value
    return replaced


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


def package(editorial: dict[str, Any], classified: dict[str, Any], style: dict[str, Any], *, run: dict[str, Any]) -> dict[str, Any]:
    metrics = EDITORIAL.validate(editorial, classified)
    quality = SCORER.score(editorial, classified, style)
    if not quality["passed"]:
        raise ValueError(f"daily v2 quality gate failed: score={quality['score']} failures={quality['hard_failures']}")
    return {
        **editorial,
        "generation": run,
        "validation": metrics,
        "quality": quality,
    }


def quarantine_path(output: Path) -> Path:
    return output.with_name(f"{output.stem}-rejected.json")


def write_rejection(output: Path, editorial: dict[str, Any], run: dict[str, Any], error: Exception) -> Path:
    path = quarantine_path(output)
    CLAIMS.write_json_atomic(path, {
        "schema_version": "daily-v2-rejected-v1",
        "generation": run,
        "validation_error": f"{type(error).__name__}: {error}",
        "response": editorial,
    })
    path.chmod(0o600)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "extract", "recover"):
        child = subparsers.add_parser(command)
        child.add_argument("classified", type=Path)
        child.add_argument("--date", required=True)
        child.add_argument("--style", required=True, type=Path)
        child.add_argument("--output", required=True, type=Path)
        if command in {"prepare", "recover"}:
            child.add_argument("--response", required=True, type=Path)
    args = parser.parse_args()
    classified = load_classified(args.classified)
    style = json.loads(args.style.read_text(encoding="utf-8"))
    _, aliases = alias_units(classified, args.date)
    if args.command in {"prepare", "recover"}:
        response = json.loads(args.response.read_text(encoding="utf-8"))
        if args.command == "recover":
            if response.get("schema_version") != "daily-v2-rejected-v1":
                raise ValueError("recover response must be daily-v2-rejected-v1")
            editorial = normalize_editorial_structure(response["response"])
        else:
            editorial = normalize_editorial_structure(expand_aliases(response, aliases))
        editorial = apply_style_replacements(complete_small_omissions(editorial, classified), style)
        result = package(editorial, classified, style, run={
            "mode": "deterministic-recovery" if args.command == "recover" else "offline-response",
            "calls": 0, "prompt_version": PROMPT_VERSION
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
        request_options = {
            "max_tokens": int(os.environ.get("DAILY_V2_LLM_MAX_TOKENS", "8192")),
            "thinking": os.environ.get("DAILY_V2_LLM_THINKING", "disabled"),
            "timeout": int(os.environ.get("DAILY_V2_LLM_TIMEOUT", "300")),
        }
        response, metrics = CLAIMS.request_llm(
            base_url, api_key, model, messages(classified, args.date, style), **request_options
        )
        editorial = apply_style_replacements(complete_small_omissions(
            normalize_editorial_structure(expand_aliases(response, aliases)), classified
        ), style)
        run = {
            "mode": "live", "calls": 1, "prompt_version": PROMPT_VERSION,
            "model": model, "input_hash": digest, **metrics,
        }
        try:
            result = package(editorial, classified, style, run=run)
        except Exception as first_error:
            repair_response, repair_metrics = CLAIMS.request_llm(
                base_url, api_key, model,
                repair_messages(classified, args.date, style, response, first_error, aliases),
                **request_options,
            )
            repaired = apply_style_replacements(complete_small_omissions(
                normalize_editorial_structure(expand_aliases(repair_response, aliases)), classified
            ), style)
            repaired_run = {
                **run,
                "calls": 2,
                "repair_reason": str(first_error),
                "repair_response_id": repair_metrics.get("response_id"),
                "repair_latency_ms": repair_metrics.get("latency_ms"),
                "repair_prompt_tokens": repair_metrics.get("prompt_tokens"),
                "repair_completion_tokens": repair_metrics.get("completion_tokens"),
                "repair_total_tokens": repair_metrics.get("total_tokens"),
            }
            try:
                result = package(repaired, classified, style, run=repaired_run)
            except Exception as exc:
                rejected = write_rejection(args.output, repaired, repaired_run, exc)
                raise ValueError(f"daily v2 rejected after one repair and quarantined at {rejected}: {exc}") from exc
    CLAIMS.write_json_atomic(args.output, result)
    print(f"[✓] wrote validated daily-v2 editorial package: {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"DAILY_V2_PIPELINE_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
