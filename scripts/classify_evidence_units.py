#!/usr/bin/env python3
"""Classify every evidence unit while preserving deterministic fallback coverage."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("claim_candidate_pipeline", SCRIPT_DIR / "claim_candidate_pipeline.py")
PIPELINE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PIPELINE)

CLASSIFIER_VERSION = "evidence-classifier-v1"
CATEGORIES = {
    "sleep_body",
    "food",
    "exercise",
    "work_project",
    "trading_finance",
    "relationships_home",
    "pet",
    "leisure",
    "other",
}
VISIBILITIES = {"daily", "continuity", "both", "archive"}
IMPORTANCES = {"low", "normal", "high"}


def is_structural_heading(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped in {"```", "---", ">", "**", "`**"}:
        return True
    if stripped.startswith(("# ", "## ", "### ", "#### ", "> [!")):
        return True
    if stripped.startswith(("记录状态：", "记录状态:")):
        return True
    if re.fullmatch(r"</?[A-Za-z][^>]*>", stripped):
        return True
    if re.fullmatch(r"(?:abstract|note|info|tip|warning|danger|quote)\].*", stripped, re.IGNORECASE):
        return True
    if re.fullmatch(r">?\s*\*\*[^*]+\*\*", stripped):
        return True
    return len(stripped) <= 32 and stripped.endswith(("：", ":"))


def load_units(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != "evidence-units-v1":
        raise ValueError("input must be evidence-units-v1")
    if not isinstance(value.get("units"), list) or not value["units"]:
        raise ValueError("evidence units must be a non-empty array")
    return value


def classification_messages(evidence: dict[str, Any]) -> list[dict[str, str]]:
    subjects = [
        {
            "subject_id": item["subject_id"],
            "subject_type": item["subject_type"],
            "canonical_name": item["canonical_name"],
        }
        for item in evidence["subjects"]
    ]
    units = []
    previous_by_document: dict[str, str] = {}
    for item in evidence["units"]:
        if is_structural_heading(item["text"]):
            previous_by_document[item["document_id"]] = item["text"]
            continue
        units.append({
            "unit_id": item["unit_id"],
            "text": item["text"],
            "context_before": previous_by_document.get(item["document_id"], ""),
        })
        previous_by_document[item["document_id"]] = item["text"]
    return [
        {
            "role": "system",
            "content": (
                "你是 Evidence Unit 分类器，不负责决定是否保留事实。必须为输入中的每个 unit_id 返回且只返回一项，"
                "不得遗漏、增加或合并 ID。summary 只能保守压缩当前 unit，不得加入外部信息或因果推断。"
                "context_before 只用于消解当前 unit 的代词、主体或上下文，不得把前文事实重复写入 summary。"
                "category 只能是 sleep_body/food/exercise/work_project/trading_finance/"
                "relationships_home/pet/leisure/other。visibility 只能是 daily/continuity/both/archive。"
                "importance 只能是 low/normal/high。subject_ids 只能使用允许列表；没有直接关联时返回空数组。"
                "涉及健康、资产策略、人物或宠物档案的稳定状态只做候选关联，后续仍需人工确认。"
                "返回 {labels:[{unit_id,category,summary,visibility,importance,subject_ids}]}，不输出解释。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"allowed_subjects": subjects, "units": units},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]


def _within_one_edit(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) <= 1
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    short_index = 0
    skipped = 0
    for character in longer:
        if short_index < len(shorter) and shorter[short_index] == character:
            short_index += 1
        else:
            skipped += 1
            if skipped > 1:
                return False
    return True


def _align_unit_id(unit_id: str, known_ids: set[str]) -> tuple[str, str | None]:
    if unit_id in known_ids:
        return unit_id, None
    matches = [known for known in known_ids if _within_one_edit(unit_id, known)]
    if len(matches) == 1:
        return matches[0], "unique_edit_distance_1"
    return unit_id, None


def merge_repair_logs(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = []
    seen = set()
    for item in previous + current:
        identity = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if identity not in seen:
            seen.add(identity)
            merged.append(item)
    return merged


def classify_response(evidence: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict) or set(response) != {"labels"}:
        raise ValueError("classifier response must contain only labels")
    labels = response["labels"]
    if not isinstance(labels, list):
        raise ValueError("labels must be an array")
    unit_map = {item["unit_id"]: item for item in evidence["units"]}
    structural_ids = {
        item["unit_id"] for item in evidence["units"] if is_structural_heading(item["text"])
    }
    subject_ids = {item["subject_id"] for item in evidence["subjects"]}
    accepted: dict[str, dict[str, Any]] = {}
    rejected = []
    label_repairs = []
    allowed_keys = {"unit_id", "category", "summary", "visibility", "importance", "subject_ids"}
    for index, label in enumerate(labels):
        error = None
        if not isinstance(label, dict) or set(label) != allowed_keys:
            error = "invalid keys"
        else:
            label = dict(label)
            original_unit_id = label.get("unit_id")
            if isinstance(original_unit_id, str):
                aligned_unit_id, repair_method = _align_unit_id(original_unit_id, set(unit_map))
                label["unit_id"] = aligned_unit_id
                if repair_method:
                    label_repairs.append({
                        "source_index": index,
                        "field": "unit_id",
                        "from": original_unit_id,
                        "to": aligned_unit_id,
                        "method": repair_method,
                    })
        if error:
            rejected.append({"source_index": index, "error": error, "raw_label": label})
            continue
        if label.get("unit_id") in structural_ids:
            continue
        if label.get("unit_id") not in unit_map:
            error = "unknown unit_id"
        elif label["unit_id"] in accepted:
            error = "duplicate unit_id"
        elif label.get("category") not in CATEGORIES:
            error = "invalid category"
        elif label.get("visibility") not in VISIBILITIES:
            error = "invalid visibility"
        elif label.get("importance") not in IMPORTANCES:
            error = "invalid importance"
        elif not isinstance(label.get("summary"), str) or not label["summary"].strip():
            error = "summary is required"
        elif not isinstance(label.get("subject_ids"), list):
            error = "subject_ids must be an array"
        elif any(item not in subject_ids for item in label["subject_ids"]):
            error = "unknown subject_id"
        if error:
            rejected.append({"source_index": index, "error": error, "raw_label": label})
            continue
        accepted[label["unit_id"]] = {
            **label,
            "summary": label["summary"].strip(),
            "subject_ids": sorted(set(label["subject_ids"])),
            "classification_status": "classified",
        }

    classified_units = []
    for unit in evidence["units"]:
        if unit["unit_id"] in structural_ids:
            classified_units.append({
                **unit,
                "category": "other",
                "summary": unit["text"],
                "visibility": "archive",
                "importance": "low",
                "subject_ids": [],
                "classification_status": "structural",
            })
            continue
        label = accepted.get(unit["unit_id"])
        if label is None:
            classified_units.append({
                **unit,
                "category": "other",
                "summary": unit["text"],
                "visibility": "daily",
                "importance": "normal",
                "subject_ids": [],
                "classification_status": "unclassified",
            })
        else:
            classified_units.append({**unit, **label})
    return {
        "schema_version": "classified-evidence-v1",
        "classifier_version": CLASSIFIER_VERSION,
        "source_sha256": evidence["source_sha256"],
        "subjects": evidence["subjects"],
        "units": classified_units,
        "rejected_labels": rejected,
        "label_repairs": label_repairs,
        "coverage": {
            "units_total": len(classified_units),
            "units_classified": sum(item["classification_status"] == "classified" for item in classified_units),
            "units_fallback": sum(item["classification_status"] == "unclassified" for item in classified_units),
            "units_structural": sum(item["classification_status"] == "structural" for item in classified_units),
            "units_preserved": len(classified_units),
        },
    }


def input_hash(evidence: dict[str, Any], model: str) -> str:
    canonical = json.dumps(
        {
            "classifier_version": CLASSIFIER_VERSION,
            "model": model,
            "source_sha256": evidence["source_sha256"],
            "unit_ids": [item["unit_id"] for item in evidence["units"]],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    baseline = subparsers.add_parser("baseline")
    baseline.add_argument("evidence", type=Path)
    baseline.add_argument("--output", required=True, type=Path)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("evidence", type=Path)
    prepare.add_argument("--response", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("classified", type=Path)
    reconcile.add_argument("--output", required=True, type=Path)
    extract = subparsers.add_parser("extract")
    extract.add_argument("evidence", type=Path)
    extract.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "reconcile":
        previous = json.loads(args.classified.read_text(encoding="utf-8"))
        if previous.get("schema_version") != "classified-evidence-v1":
            raise ValueError("reconcile input must be classified-evidence-v1")
        labels = [
            {key: unit[key] for key in (
                "unit_id", "category", "summary", "visibility", "importance", "subject_ids"
            )}
            for unit in previous["units"]
            if unit["classification_status"] == "classified"
        ]
        labels.extend(item["raw_label"] for item in previous.get("rejected_labels", []))
        result = classify_response(previous, {"labels": labels})
        result["label_repairs"] = merge_repair_logs(
            previous.get("label_repairs", []), result.get("label_repairs", [])
        )
        result["llm_run"] = {**previous.get("llm_run", {}), "reconciled_without_llm": True}
        PIPELINE.write_json_atomic(args.output, result)
        coverage = result["coverage"]
        print(
            f"[✓] reconciled without LLM: classified {coverage['units_classified']}, "
            f"fallback {coverage['units_fallback']}, structural {coverage['units_structural']}: {args.output}"
        )
        return 0

    evidence = load_units(args.evidence)

    if args.command == "baseline":
        response = {"labels": []}
        result = classify_response(evidence, response)
        result["llm_run"] = {"mode": "baseline", "calls": 0}
    elif args.command == "prepare":
        response = json.loads(args.response.read_text(encoding="utf-8"))
        result = classify_response(evidence, response)
        result["llm_run"] = {"mode": "offline-response", "calls": 0}
    else:
        api_key = os.environ.get("UNIT_LLM_API_KEY") or os.environ.get("HINDSIGHT_API_RETAIN_LLM_API_KEY", "")
        base_url = os.environ.get("UNIT_LLM_BASE_URL") or os.environ.get(
            "HINDSIGHT_API_RETAIN_LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
        )
        model = os.environ.get("UNIT_LLM_MODEL") or os.environ.get(
            "HINDSIGHT_API_RETAIN_LLM_MODEL", "glm-4.5-air"
        )
        if not api_key:
            raise SystemExit("missing UNIT_LLM_API_KEY/HINDSIGHT_API_RETAIN_LLM_API_KEY")
        request_options = {
            "max_tokens": int(os.environ.get("UNIT_LLM_MAX_TOKENS", "8192")),
            "thinking": os.environ.get("UNIT_LLM_THINKING", "disabled"),
            "timeout": int(os.environ.get("UNIT_LLM_TIMEOUT", "300")),
        }
        non_structural = [unit for unit in evidence["units"] if not is_structural_heading(unit["text"])]
        batch_size = int(os.environ.get("UNIT_LLM_BATCH_SIZE", "12"))
        batches = [non_structural[index:index + batch_size] for index in range(0, len(non_structural), batch_size)]
        all_labels: list[dict[str, Any]] = []
        call_metrics: list[dict[str, Any]] = []
        calls = 0
        for batch_index, batch in enumerate(batches, start=1):
            batch_evidence = {**evidence, "units": batch}
            expected_ids = {unit["unit_id"] for unit in batch}
            first_error = None
            for attempt in range(2):
                try:
                    batch_response, metrics = PIPELINE.request_llm(
                        base_url, api_key, model, classification_messages(batch_evidence), **request_options
                    )
                    calls += 1
                    labels = batch_response.get("labels") if isinstance(batch_response, dict) else None
                    returned_ids = {
                        item.get("unit_id") for item in labels if isinstance(item, dict)
                    } if isinstance(labels, list) else set()
                    allowed_keys = {"unit_id", "category", "summary", "visibility", "importance", "subject_ids"}
                    well_formed = isinstance(labels, list) and all(
                        isinstance(item, dict)
                        and set(item) == allowed_keys
                        and item.get("category") in CATEGORIES
                        and item.get("visibility") in VISIBILITIES
                        and item.get("importance") in IMPORTANCES
                        and isinstance(item.get("summary"), str) and bool(item["summary"].strip())
                        and isinstance(item.get("subject_ids"), list)
                        for item in labels
                    )
                    if not well_formed or returned_ids != expected_ids:
                        raise ValueError(
                            f"batch schema/coverage mismatch: expected={len(expected_ids)} returned={len(returned_ids)}"
                        )
                    break
                except (RuntimeError, ValueError) as exc:
                    first_error = exc
                    if attempt == 1:
                        raise
            if first_error is not None:
                metrics["retry_reason"] = str(first_error)
            all_labels.extend(labels)
            call_metrics.append({"batch": batch_index, **metrics})
        response = {"labels": all_labels}
        metrics = {
            "batches": len(batches),
            "batch_metrics": call_metrics,
            "prompt_tokens": sum(item.get("prompt_tokens") or 0 for item in call_metrics),
            "completion_tokens": sum(item.get("completion_tokens") or 0 for item in call_metrics),
            "total_tokens": sum(item.get("total_tokens") or 0 for item in call_metrics),
        }
        result = classify_response(evidence, response)
        result["llm_run"] = {
            "mode": "live",
            "calls": calls,
            "model": model,
            "input_hash": input_hash(evidence, model),
            **metrics,
        }
    PIPELINE.write_json_atomic(args.output, result)
    coverage = result["coverage"]
    print(
        f"[✓] preserved {coverage['units_preserved']}/{coverage['units_total']} units; "
        f"classified {coverage['units_classified']}, fallback {coverage['units_fallback']}, "
        f"structural {coverage['units_structural']}: {args.output}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"UNIT_CLASSIFIER_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
