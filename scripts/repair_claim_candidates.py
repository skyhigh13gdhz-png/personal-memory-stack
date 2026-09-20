#!/usr/bin/env python3
"""Repair quarantined Claim candidates with one bounded LLM call."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("claim_candidate_pipeline", SCRIPT_DIR / "claim_candidate_pipeline.py")
PIPELINE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PIPELINE)

REPAIR_PROMPT_VERSION = "claim-repair-v1"


def repair_messages(
    package: dict[str, Any],
    documents: list[dict[str, str]],
) -> list[dict[str, str]]:
    rejected = [item["raw_claim"] for item in package.get("rejected_candidates", [])]
    referenced_ids = {
        evidence.get("document_id")
        for claim in rejected
        for evidence in claim.get("evidence", [])
        if isinstance(evidence, dict)
    }
    relevant_documents = [item for item in documents if item["document_id"] in referenced_ids]
    allowed_subjects = [
        {
            "subject_id": item["subject_id"],
            "subject_type": item["subject_type"],
            "canonical_name": item["canonical_name"],
        }
        for item in package["subjects"]
    ]
    return [
        {
            "role": "system",
            "content": (
                "你只修复被证据校验拒绝的 Claim。把合并了不同主题或不同事件的 Claim 拆成原子 Claim。"
                "每条 summary 只表达一个连贯事实，subject_ids 只保留与该事实直接相关的允许 Subject。"
                "evidence.quote 必须逐字复制 source_documents 中的连续原文，禁止删词、改词或改标点。"
                "无法逐字引用的事实直接放弃。返回对象 {claims:[...]}，每项只含 "
                "kind,summary,valid_date,subject_ids,evidence，不输出解释。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "allowed_subjects": allowed_subjects,
                    "rejected_claims": rejected,
                    "source_documents": relevant_documents,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]


def merge_repair(
    package: dict[str, Any],
    repair_package: dict[str, Any],
    *,
    llm_run: dict[str, Any],
) -> dict[str, Any]:
    merged = json.loads(json.dumps(package))
    known = {item["candidate_id"] for item in merged["candidates"]}
    added = []
    for candidate in repair_package["candidates"]:
        if candidate["candidate_id"] not in known:
            merged["candidates"].append(candidate)
            known.add(candidate["candidate_id"])
            added.append(candidate["candidate_id"])
    previous_rejected = merged.get("rejected_candidates", [])
    merged["rejected_candidates"] = repair_package.get("rejected_candidates", [])
    merged.setdefault("repair_history", []).append({
        "prompt_version": REPAIR_PROMPT_VERSION,
        "input_rejected_count": len(previous_rejected),
        "added_candidate_ids": added,
        "remaining_rejected_count": len(merged["rejected_candidates"]),
        "llm_run": llm_run,
    })
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("package", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    bundle = PIPELINE.load_bundle(args.bundle)
    documents = PIPELINE.resolve_documents(bundle, args.bundle.parent)
    package = json.loads(args.package.read_text(encoding="utf-8"))
    if not package.get("rejected_candidates"):
        print("[=] no rejected candidates; repair call skipped")
        PIPELINE.write_json_atomic(args.output, package)
        return 0

    api_key = os.environ.get("CLAIM_LLM_API_KEY") or os.environ.get("HINDSIGHT_API_RETAIN_LLM_API_KEY", "")
    base_url = os.environ.get("CLAIM_LLM_BASE_URL") or os.environ.get(
        "HINDSIGHT_API_RETAIN_LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
    )
    model = os.environ.get("CLAIM_LLM_MODEL") or os.environ.get(
        "HINDSIGHT_API_RETAIN_LLM_MODEL", "glm-4.5-air"
    )
    if not api_key:
        raise SystemExit("missing CLAIM_LLM_API_KEY/HINDSIGHT_API_RETAIN_LLM_API_KEY")
    response, metrics = PIPELINE.request_llm(
        base_url,
        api_key,
        model,
        repair_messages(package, documents),
    )
    run = {"mode": "live-repair", "calls": 1, "model": model, **metrics}
    repair_package = PIPELINE.build_package(
        bundle,
        documents,
        response,
        model=model,
        llm_run=run,
    )
    merged = merge_repair(package, repair_package, llm_run=run)
    PIPELINE.write_json_atomic(args.output, merged)
    print(
        f"[✓] repair added {len(merged['repair_history'][-1]['added_candidate_ids'])} candidates; "
        f"remaining rejected {len(merged['rejected_candidates'])}: {args.output}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"CLAIM_REPAIR_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
