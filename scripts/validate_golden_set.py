#!/usr/bin/env python3
"""Validate a provenance-first golden set without calling an LLM."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any


KINDS = {"event", "state", "preference", "decision", "commitment", "metric"}
STATUSES = {"asserted", "extracted", "inferred", "confirmed", "disputed", "retracted"}
SUBJECT_TYPES = {"person", "pet", "project", "health_track", "habit", "asset", "strategy", "goal", "system"}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("root must be a JSON object")
    return value


def _require_text(value: Any, field: str, errors: list[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be a non-empty string")
        return ""
    return value


def validate(golden: dict[str, Any], *, base_dir: Path) -> list[str]:
    errors: list[str] = []
    if golden.get("schema_version") != "golden-v1":
        errors.append("schema_version must be golden-v1")

    subjects = golden.get("subjects")
    documents = golden.get("documents")
    claims = golden.get("claims")
    forbidden = golden.get("forbidden_inferences")
    if not isinstance(subjects, list):
        errors.append("subjects must be an array")
        subjects = []
    if not isinstance(documents, list) or not documents:
        errors.append("documents must be a non-empty array")
        documents = []
    if not isinstance(claims, list) or not claims:
        errors.append("claims must be a non-empty array")
        claims = []
    if not isinstance(forbidden, list):
        errors.append("forbidden_inferences must be an array")
        forbidden = []

    subject_ids: set[str] = set()
    for index, subject in enumerate(subjects):
        prefix = f"subjects[{index}]"
        if not isinstance(subject, dict):
            errors.append(f"{prefix} must be an object")
            continue
        subject_id = _require_text(subject.get("subject_id"), f"{prefix}.subject_id", errors)
        if subject_id in subject_ids:
            errors.append(f"duplicate subject_id: {subject_id}")
        subject_ids.add(subject_id)
        if subject.get("subject_type") not in SUBJECT_TYPES:
            errors.append(f"{prefix}.subject_type is invalid")
        _require_text(subject.get("promotion_reason"), f"{prefix}.promotion_reason", errors)

    document_text: dict[str, str] = {}
    document_dates: dict[str, str] = {}
    for index, document in enumerate(documents):
        prefix = f"documents[{index}]"
        if not isinstance(document, dict):
            errors.append(f"{prefix} must be an object")
            continue
        document_id = _require_text(document.get("document_id"), f"{prefix}.document_id", errors)
        if document_id in document_text:
            errors.append(f"duplicate document_id: {document_id}")
        day = _require_text(document.get("date"), f"{prefix}.date", errors)
        try:
            date.fromisoformat(day)
        except ValueError:
            errors.append(f"{prefix}.date is not ISO-8601")
        text = document.get("original_text")
        source_path = document.get("source_path")
        if isinstance(text, str) and text:
            resolved_text = text
        elif isinstance(source_path, str) and source_path:
            path = Path(source_path).expanduser()
            if not path.is_absolute():
                path = base_dir / path
            if not path.is_file():
                errors.append(f"{prefix}.source_path does not exist: {path}")
                resolved_text = ""
            else:
                resolved_text = path.read_text(encoding="utf-8")
        else:
            errors.append(f"{prefix} needs original_text or source_path")
            resolved_text = ""
        document_text[document_id] = resolved_text
        document_dates[document_id] = day

    claim_ids: set[str] = set()
    referenced_documents: set[str] = set()
    for index, claim in enumerate(claims):
        prefix = f"claims[{index}]"
        if not isinstance(claim, dict):
            errors.append(f"{prefix} must be an object")
            continue
        claim_id = _require_text(claim.get("claim_id"), f"{prefix}.claim_id", errors)
        if claim_id in claim_ids:
            errors.append(f"duplicate claim_id: {claim_id}")
        claim_ids.add(claim_id)
        if claim.get("kind") not in KINDS:
            errors.append(f"{prefix}.kind is invalid")
        if claim.get("epistemic_status") not in STATUSES:
            errors.append(f"{prefix}.epistemic_status is invalid")
        _require_text(claim.get("summary"), f"{prefix}.summary", errors)
        day = _require_text(claim.get("valid_date"), f"{prefix}.valid_date", errors)
        try:
            date.fromisoformat(day)
        except ValueError:
            errors.append(f"{prefix}.valid_date is not ISO-8601")
        for subject_id in claim.get("subject_ids", []):
            if subject_id not in subject_ids:
                errors.append(f"{prefix} references unknown subject: {subject_id}")
        evidence = claim.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{prefix}.evidence must be a non-empty array")
            continue
        for evidence_index, ref in enumerate(evidence):
            ref_prefix = f"{prefix}.evidence[{evidence_index}]"
            if not isinstance(ref, dict):
                errors.append(f"{ref_prefix} must be an object")
                continue
            document_id = _require_text(ref.get("document_id"), f"{ref_prefix}.document_id", errors)
            quote = _require_text(ref.get("quote"), f"{ref_prefix}.quote", errors)
            if document_id not in document_text:
                errors.append(f"{ref_prefix} references unknown document: {document_id}")
                continue
            referenced_documents.add(document_id)
            if quote and quote not in document_text[document_id]:
                errors.append(f"{ref_prefix}.quote not found verbatim in source")
            if day and document_dates.get(document_id) != day:
                errors.append(f"{ref_prefix} date differs from claim valid_date")

    unreferenced = sorted(set(document_text) - referenced_documents)
    if unreferenced:
        errors.append(f"documents without any claim evidence: {unreferenced}")
    for index, item in enumerate(forbidden):
        if not isinstance(item, dict):
            errors.append(f"forbidden_inferences[{index}] must be an object")
            continue
        _require_text(item.get("statement"), f"forbidden_inferences[{index}].statement", errors)
        _require_text(item.get("reason"), f"forbidden_inferences[{index}].reason", errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    errors = validate(load_json(args.path), base_dir=args.path.parent)
    if errors:
        for error in errors:
            print(f"[x] {error}", file=sys.stderr)
        return 1
    print(f"[✓] golden-v1 valid: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
