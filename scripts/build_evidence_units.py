#!/usr/bin/env python3
"""Split Claim input Documents into stable, lossless evidence units without an LLM."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("claim_candidate_pipeline", SCRIPT_DIR / "claim_candidate_pipeline.py")
PIPELINE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PIPELINE)

UNIT_VERSION = "evidence-units-v1"
SENTENCE_PATTERN = re.compile(r"[^\n]+?(?:[。！？!?](?=\s|$)|(?=\n|$))")


def content_fingerprint(text: str) -> str:
    return hashlib.sha256("".join(text.split()).encode()).hexdigest()


def split_document(document: dict[str, str]) -> list[dict[str, Any]]:
    text = document["original_text"]
    units = []
    for match in SENTENCE_PATTERN.finditer(text):
        raw = match.group(0)
        stripped = raw.strip()
        if not stripped:
            continue
        leading = len(raw) - len(raw.lstrip())
        start = match.start() + leading
        end = start + len(stripped)
        identity = f"{document['document_id']}:{start}:{end}:{stripped}"
        units.append({
            "unit_id": "unit-" + hashlib.sha256(identity.encode()).hexdigest()[:20],
            "document_id": document["document_id"],
            "date": document["date"],
            "start": start,
            "end": end,
            "text": stripped,
            "text_sha256": hashlib.sha256(stripped.encode()).hexdigest(),
            "classification_status": "unclassified",
        })
    reconstructed = "".join(item["text"] for item in units)
    if content_fingerprint(reconstructed) != content_fingerprint(text):
        raise ValueError(f"lossless coverage failed for document {document['document_id']}")
    return units


def build_units(bundle: dict[str, Any], documents: list[dict[str, str]]) -> dict[str, Any]:
    units = [unit for document in documents for unit in split_document(document)]
    return {
        "schema_version": UNIT_VERSION,
        "speaker": bundle.get("speaker"),
        "date": bundle.get("date"),
        "source_sha256": PIPELINE.source_hash(documents),
        "document_count": len(documents),
        "unit_count": len(units),
        "coverage": {
            "documents_total": len(documents),
            "documents_lossless": len(documents),
            "non_whitespace_content": "100%",
        },
        "subjects": bundle["subjects"],
        "units": units,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    bundle = PIPELINE.load_bundle(args.bundle)
    documents = PIPELINE.resolve_documents(bundle, args.bundle.parent)
    result = build_units(bundle, documents)
    PIPELINE.write_json_atomic(args.output, result)
    print(
        f"[✓] wrote {result['unit_count']} lossless evidence units from "
        f"{result['document_count']} Documents: {args.output}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"EVIDENCE_UNITS_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
