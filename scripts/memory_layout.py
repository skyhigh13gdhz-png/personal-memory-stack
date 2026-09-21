#!/usr/bin/env python3
"""Validate, plan, apply, or roll back config-driven managed Vault layout changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Union


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def safe_relative(value: str, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"{field} must stay inside the Vault")
    return path


def safe_filename(value: str) -> str:
    cleaned = value.strip().replace("/", "-").replace(":", "-")
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("subject filename is invalid")
    return cleaned if cleaned.endswith(".md") else cleaned + ".md"


def validate(layout: dict[str, Any], registry: dict[str, Any]) -> tuple[dict[str, PurePosixPath], dict[str, dict[str, Any]]]:
    if layout.get("schema_version") != "memory-layout-v1":
        raise ValueError("layout schema_version must be memory-layout-v1")
    if registry.get("schema_version") != "subject-registry-v2":
        raise ValueError("registry schema_version must be subject-registry-v2")
    collections = layout.get("collections")
    routing = layout.get("routing")
    templates = layout.get("templates")
    if not isinstance(collections, dict) or not collections:
        raise ValueError("collections must be a non-empty object")
    if not isinstance(routing, dict):
        raise ValueError("routing must be an object")
    if not isinstance(templates, dict) or not templates:
        raise ValueError("templates must be a non-empty object")
    for template_id, template in templates.items():
        allowed = template.get("subject_types") if isinstance(template, dict) else None
        if not isinstance(allowed, list) or not allowed or not all(isinstance(item, str) and item for item in allowed):
            raise ValueError(f"templates.{template_id}.subject_types must be a non-empty string array")
    collection_paths = {key: safe_relative(value, f"collections.{key}") for key, value in collections.items()}
    if len(set(collection_paths.values())) != len(collection_paths):
        raise ValueError("collection paths must be unique")
    for subject_type, collection in routing.items():
        if collection not in collection_paths:
            raise ValueError(f"routing.{subject_type} references unknown collection {collection}")
    subjects = registry.get("subjects")
    if not isinstance(subjects, list):
        raise ValueError("subjects must be an array")
    subject_map: dict[str, dict[str, Any]] = {}
    for index, subject in enumerate(subjects):
        if not isinstance(subject, dict):
            raise ValueError(f"subjects[{index}] must be an object")
        subject_id = subject.get("subject_id")
        if not isinstance(subject_id, str) or not subject_id:
            raise ValueError(f"subjects[{index}].subject_id is required")
        if subject_id in subject_map:
            raise ValueError(f"duplicate subject_id: {subject_id}")
        subject_type = subject.get("subject_type")
        collection = subject.get("collection") or routing.get(subject_type)
        if collection not in collection_paths:
            raise ValueError(f"subject {subject_id} has no valid collection")
        if not subject.get("canonical_name") or not subject.get("template"):
            raise ValueError(f"subject {subject_id} requires canonical_name and template")
        template_id = subject["template"]
        if template_id not in templates:
            raise ValueError(f"subject {subject_id} references unknown template {template_id}")
        if subject_type not in templates[template_id]["subject_types"]:
            raise ValueError(f"template {template_id} does not support subject type {subject_type}")
        subject_map[subject_id] = {**subject, "collection": collection}
    for subject_id, subject in subject_map.items():
        parent = subject.get("parent_subject_id")
        if parent is not None and parent not in subject_map:
            raise ValueError(f"subject {subject_id} references unknown parent {parent}")
        visited = {subject_id}
        while parent is not None:
            if parent in visited:
                raise ValueError(f"subject parent cycle involving {subject_id}")
            visited.add(parent)
            parent = subject_map[parent].get("parent_subject_id")
    return collection_paths, subject_map


def desired_paths(layout: dict[str, Any], registry: dict[str, Any]) -> dict[str, str]:
    collections, subjects = validate(layout, registry)
    nested_types = set(layout.get("nest_under_parent_types", []))
    result = {}
    for subject_id, subject in subjects.items():
        base = collections[subject["collection"]]
        parent_id = subject.get("parent_subject_id")
        if parent_id and subject["subject_type"] in nested_types:
            parent = subjects[parent_id]
            if parent["collection"] != subject["collection"]:
                raise ValueError(f"nested subject {subject_id} must share its parent's collection")
            base /= safe_filename(parent.get("filename") or parent["canonical_name"])[:-3]
        filename = safe_filename(subject.get("filename") or subject["canonical_name"])
        result[subject_id] = str(base / filename)
    return result


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def vault_path(vault: Path, relative: Union[str, PurePosixPath], field: str) -> Path:
    root = vault.resolve()
    candidate = (root / safe_relative(str(relative), field)).resolve(strict=False)
    if os.path.commonpath([str(root), str(candidate)]) != str(root):
        raise ValueError(f"{field} resolves outside the Vault")
    return candidate


def build_plan(layout: dict[str, Any], registry: dict[str, Any], manifest: dict[str, Any], vault: Path) -> dict[str, Any]:
    if manifest.get("schema_version") != "memory-layout-manifest-v1":
        raise ValueError("manifest schema_version must be memory-layout-manifest-v1")
    desired = desired_paths(layout, registry)
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("manifest entries must be an array")
    moves, unchanged, untracked, orphans, errors = [], [], [], [], []
    seen: set[str] = set()
    for entry in entries:
        subject_id = entry.get("subject_id")
        if subject_id in seen:
            errors.append(f"duplicate manifest subject: {subject_id}")
            continue
        seen.add(subject_id)
        if entry.get("managed") is not True:
            continue
        if subject_id not in desired:
            orphans.append(subject_id)
            continue
        source_rel = str(safe_relative(entry.get("path"), f"manifest.{subject_id}.path"))
        destination_rel = desired[subject_id]
        source = vault_path(vault, source_rel, f"manifest.{subject_id}.path")
        if not source.is_file():
            errors.append(f"managed source missing: {source_rel}")
            continue
        actual_hash = file_sha256(source)
        if entry.get("sha256") != actual_hash:
            errors.append(f"managed source changed outside projector: {source_rel}")
            continue
        if source_rel == destination_rel:
            unchanged.append(subject_id)
        else:
            moves.append({
                "subject_id": subject_id, "source": source_rel, "destination": destination_rel,
                "sha256": actual_hash,
            })
    untracked = sorted(set(desired) - seen)
    return {
        "schema_version": "memory-layout-plan-v1",
        "layout_version": layout["layout_version"],
        "vault_root": str(vault.resolve()),
        "moves": moves,
        "unchanged_subject_ids": sorted(unchanged),
        "untracked_subject_ids": untracked,
        "orphan_subject_ids": sorted(orphans),
        "errors": errors,
        "warnings": ["Explicit path-based Markdown links may require a separate link rewrite."],
    }


def apply_plan(plan: dict[str, Any], vault: Path) -> dict[str, Any]:
    if plan.get("schema_version") != "memory-layout-plan-v1" or plan.get("errors"):
        raise ValueError("refusing invalid layout plan")
    if str(vault.resolve()) != plan.get("vault_root"):
        raise ValueError("plan Vault root does not match")
    prepared = []
    destinations: set[Path] = set()
    for move in plan.get("moves", []):
        source = vault_path(vault, move["source"], "move.source")
        destination = vault_path(vault, move["destination"], "move.destination")
        if not source.is_file() or file_sha256(source) != move["sha256"]:
            raise ValueError(f"source changed since plan: {move['source']}")
        if destination.exists():
            raise ValueError(f"destination already exists: {move['destination']}")
        if destination in destinations:
            raise ValueError(f"duplicate destination in plan: {move['destination']}")
        destinations.add(destination)
        prepared.append((move, source, destination))
    completed = []
    for move, source, destination in prepared:
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        completed.append(move)
    return {
        "schema_version": "memory-layout-journal-v1",
        "vault_root": str(vault.resolve()),
        "moves": completed,
    }


def rollback(journal: dict[str, Any], vault: Path) -> None:
    if journal.get("schema_version") != "memory-layout-journal-v1":
        raise ValueError("journal must be memory-layout-journal-v1")
    if str(vault.resolve()) != journal.get("vault_root"):
        raise ValueError("journal Vault root does not match")
    prepared = []
    destinations: set[Path] = set()
    for move in reversed(journal.get("moves", [])):
        source = vault_path(vault, move["destination"], "rollback.source")
        destination = vault_path(vault, move["source"], "rollback.destination")
        if not source.is_file() or file_sha256(source) != move["sha256"]:
            raise ValueError(f"moved file changed; refusing rollback: {move['destination']}")
        if destination.exists():
            raise ValueError(f"rollback destination exists: {move['source']}")
        if destination in destinations:
            raise ValueError(f"duplicate rollback destination: {move['source']}")
        destinations.add(destination)
        prepared.append((source, destination))
    for source, destination in prepared:
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def register_projection(
    manifest: dict[str, Any], vault: Path, subject_id: str, relative_path: str, *, managed: bool = True
) -> dict[str, Any]:
    """Return a manifest with one projector-owned file recorded at its current hash."""
    if manifest.get("schema_version") != "memory-layout-manifest-v1":
        raise ValueError("manifest schema_version must be memory-layout-manifest-v1")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("manifest entries must be an array")
    path = str(safe_relative(relative_path, "projection.path"))
    projected = vault_path(vault, path, "projection.path")
    if not projected.is_file():
        raise ValueError(f"projected file missing: {path}")
    if not isinstance(subject_id, str) or not subject_id.strip():
        raise ValueError("subject_id is required")
    replacement = {
        "subject_id": subject_id,
        "path": path,
        "sha256": file_sha256(projected),
        "managed": managed,
    }
    result = []
    found = False
    for entry in entries:
        if entry.get("subject_id") == subject_id:
            if found:
                raise ValueError(f"duplicate manifest subject: {subject_id}")
            result.append(replacement)
            found = True
        else:
            result.append(entry)
    if not found:
        result.append(replacement)
    result.sort(key=lambda item: item.get("subject_id", ""))
    return {**manifest, "entries": result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate_cmd = sub.add_parser("validate")
    plan_cmd = sub.add_parser("plan")
    apply_cmd = sub.add_parser("apply")
    rollback_cmd = sub.add_parser("rollback")
    register_cmd = sub.add_parser("register")
    for child in (validate_cmd, plan_cmd):
        child.add_argument("--layout", required=True, type=Path)
        child.add_argument("--subjects", required=True, type=Path)
    plan_cmd.add_argument("--manifest", required=True, type=Path)
    plan_cmd.add_argument("--vault", required=True, type=Path)
    plan_cmd.add_argument("--output", required=True, type=Path)
    apply_cmd.add_argument("--plan", required=True, type=Path)
    apply_cmd.add_argument("--vault", required=True, type=Path)
    apply_cmd.add_argument("--journal", required=True, type=Path)
    rollback_cmd.add_argument("--journal", required=True, type=Path)
    rollback_cmd.add_argument("--vault", required=True, type=Path)
    register_cmd.add_argument("--manifest", required=True, type=Path)
    register_cmd.add_argument("--vault", required=True, type=Path)
    register_cmd.add_argument("--subject-id", required=True)
    register_cmd.add_argument("--path", required=True)
    args = parser.parse_args()
    if args.command == "validate":
        paths = desired_paths(load(args.layout), load(args.subjects))
        print(json.dumps(paths, ensure_ascii=False, indent=2))
    elif args.command == "plan":
        result = build_plan(load(args.layout), load(args.subjects), load(args.manifest), args.vault)
        write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result["errors"] else 0
    elif args.command == "apply":
        result = apply_plan(load(args.plan), args.vault)
        write_json(args.journal, result)
        print(f"[✓] moved {len(result['moves'])} managed files; journal: {args.journal}")
    elif args.command == "rollback":
        rollback(load(args.journal), args.vault)
        print("[✓] rolled back managed layout moves")
    else:
        result = register_projection(load(args.manifest), args.vault, args.subject_id, args.path)
        write_json(args.manifest, result)
        print(f"[✓] registered managed projection: {args.subject_id} -> {args.path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"MEMORY_LAYOUT_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
