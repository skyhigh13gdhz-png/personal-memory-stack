#!/usr/bin/env python3
"""Prepare, validate, cache, or run a daily-view-v2 editorial generation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
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
PROMPT_VERSION = "daily-editorial-v2.4"
CATEGORY_SECTION = EDITORIAL.CATEGORY_SECTION
CATEGORY_LABEL = {
    "sleep_body": "补充记录", "food": "饮食记录", "exercise": "运动记录",
    "work_project": "项目记录", "trading_finance": "交易记录",
    "relationships_home": "家庭记录", "pet": "宠物记录", "leisure": "休闲记录", "other": "其他记录",
    "reflection_growth": "觉察记录",
}
COMPLETED_TASK_CHROME = re.compile(r"^\s*[-*+]\s+\[[xX]\]\s*")


def human_evidence_text(unit: dict[str, Any]) -> str:
    text = str(unit.get("text", ""))
    if unit.get("task_status") == "completed":
        return COMPLETED_TASK_CHROME.sub("", text).strip()
    return text


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
        "text": human_evidence_text(unit),
        "current_category": unit["category"],
        "current_summary": unit["summary"],
        "subject_ids": unit["subject_ids"],
        "source_block_id": unit.get("source_block_id"),
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
                "relationships_home/pet/leisure/reflection_growth/other；显示标题由程序决定。所有项目必须归入 project_work，"
                "并以具体项目名建立 facts group，不能把某个项目提升为一级栏目。"
                "交易操作、盘面、盈亏和账户内容只归入 trading_finance，不得在 project_work 下再建‘交易’分组。"
                "同一事实不得在不同栏目重复改写；真正混合了两个维度的单元才能 facet_split，"
                "且两个条目必须各自仅表达所属栏目的不同事实。"
                "情绪事件、自我觉察、行为模式和改进方向必须放 reflection_growth，不得塞入 other。"
                "reflection_growth 中的事实不得在 trading_finance 或其他栏目重复。"
                "每个 group 必须有 group_id，只能使用程序给定的受控分组："
                + json.dumps(EDITORIAL.GROUP_DEFINITIONS, ensure_ascii=False, separators=(",", ":")) + "。"
                "同一小主题的多条事实必须聚合在同一 group，不要平铺成多个 group。分组显示顺序由程序固定，"
                "如睡眠始终是夜间睡眠→午间休息→身体状态。project_work 使用 group_id=project，title 写具体项目名。"
                "主题归类与发生时间是两个维度。每个 item 必须有 period，且只能为 overnight/morning/noon/"
                "afternoon/evening/span/unknown；同一 group 内程序按 period 排序。一个 item 只表达一个时间连续的事件，"
                "同一事件明确从一个时段延续到另一时段时用 span；不得因为人物或主题相同就把早晨、午间、下午、"
                "晚上的独立事件合并，不同事件必须拆成不同 item。"
                "晨间/早上既喝水又吃东西属于 breakfast，不得归入 snacks_hydration。"
                "source_block_id 相同表示内容来自同一编号记录块；其中的说明、链接、工单号等资料必须聚合为同一"
                "事件/资料条目，不得把一个资料块强行平铺成多个主题。"
                "一个单元跨两个事实条目使用时，这些条目都必须 facet_split=true。保留用户稳定用词和领域术语，"
                "不要改成公文腔。不得增加原文没有的结果、动机或因果。程序可直接计算的内容标"
                "analysis_status=calculated；跨单元归纳标 observation；推断标 inference 且 uncertainty=true。"
                "原始事实必须放在 group_kind=facts 且不得设置 analysis_status；只有同时基于至少两个单元的"
                "直接计算可以留在 facts group 并标 calculated；观察/推断必须放在 group_kind=analysis，"
                "正文必须明确不确定性。没有内容的栏目或字段不要生成。项目归组不等于创建长期 Subject。"
                "只返回 daily-view-v2 JSON：{schema_version,date,sections:[{section_id,groups:["
                "{group_id,group_kind,title?,items:[{label,text,period,evidence_unit_ids,facet_split?,analysis_status?,uncertainty?}]}]}]}。"
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
    for section in sections:
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        ordered: list[dict[str, Any]] = []
        for group in section["groups"]:
            key = (str(group.get("group_id", "")), str(group.get("title", "")) if section.get("section_id") == "project_work" else "")
            if key in merged:
                if merged[key].get("group_kind") != group.get("group_kind"):
                    merged[key]["group_kind"] = "mixed"
                merged[key]["items"].extend(group["items"])
            else:
                merged[key] = group
                ordered.append(group)
        section["groups"] = ordered
    unit_map: dict[str, dict[str, Any]] = {}
    for section in sections:
        for group in section["groups"]:
            for item in group["items"]:
                if item.get("period") not in EDITORIAL.PERIOD_ORDER:
                    item["period"] = EDITORIAL.infer_period(item, unit_map)
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


def enforce_primary_section_membership(
    editorial: dict[str, Any], classified: dict[str, Any]
) -> dict[str, Any]:
    """Drop mixed/misplaced items instead of duplicating them across sections.

    We remove the item rather than silently deleting references from it: its
    wording may combine those facts. Coverage recovery can then add grounded
    source summaries back to their primary sections.
    """
    expected = {
        unit["unit_id"]: CATEGORY_SECTION.get(unit.get("category", "other"), "other")
        for unit in classified.get("units", [])
    }
    cleaned = json.loads(json.dumps(editorial, ensure_ascii=False))
    for section in cleaned.get("sections", []):
        section_id = section.get("section_id")
        kept_groups = []
        for group in section.get("groups", []):
            group["items"] = [
                item for item in group.get("items", [])
                if all(expected.get(unit_id, section_id) == section_id
                       for unit_id in item.get("evidence_unit_ids", []))
            ]
            if group["items"]:
                kept_groups.append(group)
        section["groups"] = kept_groups
    cleaned["sections"] = [section for section in cleaned.get("sections", []) if section.get("groups")]
    return cleaned


# Compatibility for callers/tests created before primary membership became general.
enforce_exclusive_primary_sections = enforce_primary_section_membership


def split_cross_period_items(
    editorial: dict[str, Any], classified: dict[str, Any]
) -> dict[str, Any]:
    """Replace model-merged multi-period items with grounded atomic summaries."""
    result = json.loads(json.dumps(editorial, ensure_ascii=False))
    unit_map = {unit["unit_id"]: unit for unit in classified.get("units", [])}
    for section in result.get("sections", []):
        for group in section.get("groups", []):
            replacement = []
            for item in group.get("items", []):
                if len(EDITORIAL.detect_periods(f"{item.get('label', '')} {item.get('text', '')}")) <= 1:
                    replacement.append(item)
                    continue
                refs = item.get("evidence_unit_ids", [])
                unit_periods = [(unit_map.get(unit_id), infer_unit_period(unit_map.get(unit_id, {}))) for unit_id in refs]
                known = {period for _, period in unit_periods if period != "unknown"}
                if len(refs) < 2 or len(known) < 2:
                    item["period"] = "span"
                    replacement.append(item)
                    continue
                for unit, period in unit_periods:
                    if not unit:
                        continue
                    replacement.append({
                        "label": item.get("label", "补充记录"),
                        "text": unit.get("summary") or unit.get("text", ""),
                        "period": period,
                        "evidence_unit_ids": [unit["unit_id"]],
                    })
            group["items"] = replacement
    return result


def complete_small_omissions(
    editorial: dict[str, Any], classified: dict[str, Any], *, max_missing: int = 6
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
    additions = missing
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
                group = {"group_id": "project", "group_kind": "facts", "title": title, "items": []}
                section["groups"].append(group)
        else:
            group_id = fallback_group_id(section_id, unit)
            group = next((item for item in facts if item.get("group_id") == group_id), None)
            if group is None:
                occupied = {item.get("group_id") for item in section["groups"]}
                if group_id in occupied and facts:
                    group = facts[0]
                elif group_id in occupied:
                    group_id = next(
                        (candidate for candidate, _ in EDITORIAL.GROUP_DEFINITIONS[section_id]
                         if candidate not in occupied),
                        group_id,
                    )
            if group is None:
                title = dict(EDITORIAL.GROUP_DEFINITIONS[section_id])[group_id]
                group = {"group_id": group_id, "group_kind": "facts", "title": title, "items": []}
                section["groups"].insert(0, group)
        new_item = {
            "label": CATEGORY_LABEL.get(category, "补充记录"),
            "text": unit.get("summary") or unit["text"],
            "period": infer_unit_period(unit),
            "evidence_unit_ids": [unit["unit_id"]],
        }
        group["items"].append(new_item)
    return completed


def infer_unit_period(unit: dict[str, Any]) -> str:
    periods = EDITORIAL.detect_periods(f"{unit.get('summary', '')} {unit.get('text', '')}")
    return next((period for period in EDITORIAL.PERIOD_ORDER if period in periods), "unknown")


def contextual_unit_periods(classified: dict[str, Any]) -> dict[str, str]:
    """Resolve anaphoric timeline phrases from adjacent source units."""
    by_document: dict[str, list[dict[str, Any]]] = {}
    for unit in classified.get("units", []):
        by_document.setdefault(str(unit.get("document_id", "")), []).append(unit)
    resolved: dict[str, str] = {}
    for units in by_document.values():
        current = "unknown"
        for unit in sorted(units, key=lambda item: int(item.get("start", 0))):
            explicit = infer_unit_period(unit)
            text = str(unit.get("text", "")).strip()
            if explicit != "unknown":
                current = explicit
            elif current != "unknown" and re.match(r"^(期间|之后|随后|然后|当时|后来)", text):
                explicit = current
            resolved[unit["unit_id"]] = explicit
    return resolved


def ground_unknown_periods(editorial: dict[str, Any], classified: dict[str, Any]) -> dict[str, Any]:
    grounded = json.loads(json.dumps(editorial, ensure_ascii=False))
    periods = contextual_unit_periods(classified)
    for section in grounded.get("sections", []):
        for group in section.get("groups", []):
            for item in group.get("items", []):
                if item.get("period") != "unknown":
                    continue
                candidates = [periods.get(unit_id, "unknown") for unit_id in item.get("evidence_unit_ids", [])]
                known = [period for period in candidates if period != "unknown"]
                if known and len(set(known)) == 1:
                    item["period"] = known[0]
    return grounded


def fallback_group_id(section_id: str, unit: dict[str, Any]) -> str:
    """Choose a deterministic human group when the model omitted a unit."""
    text = f"{unit.get('summary', '')} {unit.get('text', '')}"
    if section_id == "food":
        if re.search(r"早餐|早上|早晨|晨间|起床后", text) and re.search(r"吃|食用|面包|饭|粥|蛋", text):
            return "breakfast"
        if re.search(r"午餐|午饭|中午", text):
            return "lunch"
        if re.search(r"晚餐|晚饭|晚上", text):
            return "dinner"
        if re.search(r"买|消费|花费|价格|¥|￥", text):
            return "consumption"
        return "snacks_hydration"
    if section_id == "sleep":
        if re.search(r"午休|午睡", text):
            return "nap"
        if re.search(r"入睡|睡觉|夜里|夜间|凌晨|起床", text):
            return "night_sleep"
        return "body_state"
    if section_id == "relationships_home":
        return "partner" if re.search(r"老婆|妻子|伴侣", text) else "home"
    return EDITORIAL.GROUP_DEFINITIONS[section_id][-1][0]


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
                    value = COMPLETED_TASK_CHROME.sub("", value).strip()
                    item[field] = value
    return replaced


def merge_source_block_items(
    editorial: dict[str, Any], classified: dict[str, Any]
) -> dict[str, Any]:
    """Reassemble adjacent Markdown record blocks after evidence classification."""
    result = json.loads(json.dumps(editorial, ensure_ascii=False))
    block_by_unit = {unit["unit_id"]: unit.get("source_block_id") for unit in classified.get("units", [])}
    for section in result.get("sections", []):
        for group in section.get("groups", []):
            merged: list[dict[str, Any]] = []
            positions: dict[str, int] = {}
            for item in group.get("items", []):
                blocks = {block_by_unit.get(unit_id) for unit_id in item.get("evidence_unit_ids", [])}
                blocks.discard(None)
                block_id = next(iter(blocks)) if len(blocks) == 1 else None
                if not block_id or block_id not in positions:
                    if block_id:
                        positions[block_id] = len(merged)
                    merged.append(item)
                    continue
                target = merged[positions[block_id]]
                if item.get("text") not in target.get("text", ""):
                    target["text"] = target["text"].rstrip("。；; ") + "；" + item["text"]
                target["evidence_unit_ids"] = list(dict.fromkeys(
                    target.get("evidence_unit_ids", []) + item.get("evidence_unit_ids", [])
                ))
                target["facet_split"] = True
            group["items"] = merged
    return result


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
        editorial = apply_style_replacements(merge_source_block_items(complete_small_omissions(
            enforce_primary_section_membership(
                split_cross_period_items(ground_unknown_periods(editorial, classified), classified), classified
            ), classified
        ), classified), style)
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
        editorial = apply_style_replacements(merge_source_block_items(complete_small_omissions(
            enforce_primary_section_membership(
                split_cross_period_items(
                    ground_unknown_periods(normalize_editorial_structure(expand_aliases(response, aliases)), classified), classified
                ), classified
            ), classified
        ), classified), style)
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
            repaired = apply_style_replacements(merge_source_block_items(complete_small_omissions(
                enforce_primary_section_membership(
                    split_cross_period_items(
                        ground_unknown_periods(normalize_editorial_structure(expand_aliases(repair_response, aliases)), classified), classified
                    ), classified
                ), classified
            ), classified), style)
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
