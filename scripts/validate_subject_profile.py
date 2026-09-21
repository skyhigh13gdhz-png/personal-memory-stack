#!/usr/bin/env python3
"""Validate the stable human profile of a Memory Subject against its type template."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def validate(profile: dict[str, Any], subject: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if profile.get("schema_version") != "subject-profile-v1":
        errors.append("schema_version must be subject-profile-v1")
    if profile.get("review_status") not in {"draft", "confirmed"}:
        errors.append("review_status must be draft or confirmed")
    if profile.get("subject_id") != subject.get("subject_id"):
        errors.append("profile subject_id must match registry subject_id")
    sections = template.get("profile_sections")
    if not isinstance(sections, list) or not sections:
        errors.append("template profile_sections must be a non-empty array")
        sections = []
    seen = set()
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            errors.append(f"profile_sections[{index}] must be an object")
            continue
        key = section.get("key")
        title = section.get("title")
        kind = section.get("kind")
        if not isinstance(key, str) or not key or key in seen:
            errors.append(f"profile_sections[{index}].key is missing or duplicated")
            continue
        seen.add(key)
        if not isinstance(title, str) or not title:
            errors.append(f"profile_sections[{index}].title is required")
        if kind not in {"paragraph", "list"}:
            errors.append(f"profile_sections[{index}].kind is invalid")
        value = profile.get("content", {}).get(key)
        if section.get("required") and (value is None or value == "" or value == []):
            errors.append(f"profile content.{key} is required")
        if value is not None:
            if kind == "paragraph" and (not isinstance(value, str) or not value.strip()):
                errors.append(f"profile content.{key} must be non-empty text")
            if kind == "list" and (
                not isinstance(value, list) or not value or
                not all(isinstance(item, str) and item.strip() for item in value)
            ):
                errors.append(f"profile content.{key} must be a non-empty string array")
    unknown = sorted(set(profile.get("content", {})) - seen)
    if unknown:
        errors.append(f"profile contains fields not declared by template: {unknown}")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "sections": len(sections), "populated": sum(key in profile["content"] for key in seen),
        "review_status": profile["review_status"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("--subject", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    subject = json.loads(args.subject.read_text(encoding="utf-8"))
    template = json.loads(args.template.read_text(encoding="utf-8"))
    print(json.dumps(validate(profile, subject, template), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"SUBJECT_PROFILE_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
