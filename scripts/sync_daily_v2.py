#!/usr/bin/env python3
"""Incrementally build quality-gated Daily V2 notes from projected raw journals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
RECORD = re.compile(
    r"^## (?P<label>[^\n]+)\n\n(?P<text>.*?)\n\n"
    r"<!-- personal-memory-record (?P<meta>\{.*?\}) -->\n\n---(?:\n|$)",
    re.MULTILINE | re.DOTALL,
)


def parse_projected_day(path: Path, day: str) -> list[dict[str, str]]:
    documents = []
    for match in RECORD.finditer(path.read_text(encoding="utf-8")):
        metadata = json.loads(match.group("meta"))
        text = match.group("text").strip()
        if text:
            documents.append({
                "document_id": str(metadata["document_id"]),
                "date": day,
                "original_text": text,
            })
    if not documents:
        raise ValueError(f"no projected Documents found in {path}")
    return documents


def run(*arguments: str) -> None:
    subprocess.run([sys.executable, *arguments], check=True)


def atomic_publish(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(source.read_bytes())
    temporary.replace(target)
    target.chmod(0o600)


def stamp_source_hash(rendered: Path, raw: Path) -> str:
    """Bind a derived Daily V2 note to the exact projected source bytes."""
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    with rendered.open("a", encoding="utf-8") as handle:
        handle.write(f"\n<!-- daily-v2-source-sha256:{digest} -->\n")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    parser.add_argument("--subjects", type=Path, default=SCRIPT_DIR.parent / "config/subjects.json")
    parser.add_argument("--style", type=Path, default=SCRIPT_DIR.parent / "config/daily-style.example.json")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = date.fromisoformat(args.date_from)
    end = date.fromisoformat(args.date_to)
    if end < start:
        raise ValueError("--date-to must not be earlier than --date-from")
    subjects_value = json.loads(args.subjects.read_text(encoding="utf-8"))
    subjects = subjects_value.get("subjects")
    if not isinstance(subjects, list):
        raise ValueError("subjects config must contain a subjects array")

    candidates = sorted(
        path for path in args.raw_dir.glob("????-??-??.md")
        if start <= date.fromisoformat(path.stem) <= end
    )
    if not candidates:
        raise ValueError("no projected daily source files found in requested range")

    owned_temp = None
    if args.work_dir is None:
        owned_temp = tempfile.TemporaryDirectory(prefix="daily-v2-")
        work_root = Path(owned_temp.name)
    else:
        work_root = args.work_dir
        work_root.mkdir(parents=True, exist_ok=True)

    generated = skipped = failed = 0
    failures: list[str] = []
    try:
        for raw_path in candidates:
            day = raw_path.stem
            target = args.output_dir / f"{day}.md"
            if target.exists() and not args.replace_existing:
                print(f"[=] existing daily preserved: {target}")
                skipped += 1
                continue
            if args.dry_run:
                print(f"[dry-run] would build {day} from {raw_path}")
                continue
            day_work = work_root / day
            day_work.mkdir(parents=True, exist_ok=True)
            bundle = day_work / "input.json"
            evidence = day_work / "evidence.json"
            classified = day_work / "classified.json"
            editorial = day_work / "editorial.json"
            rendered = day_work / f"{day}.md"
            bundle.write_text(json.dumps({
                "speaker": "liangzai",
                "date": day,
                "subjects": subjects,
                "documents": parse_projected_day(raw_path, day),
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            try:
                if not evidence.exists():
                    run(str(SCRIPT_DIR / "build_evidence_units.py"), str(bundle), "--output", str(evidence))
                else:
                    print(f"[=] reused evidence cache: {evidence}")
                if not classified.exists():
                    run(str(SCRIPT_DIR / "classify_evidence_units.py"), "extract", str(evidence), "--output", str(classified))
                else:
                    print(f"[=] reused classification cache: {classified}")
                run(
                    str(SCRIPT_DIR / "daily_v2_pipeline.py"), "extract", str(classified),
                    "--date", day, "--style", str(args.style), "--output", str(editorial),
                )
                run(
                    str(SCRIPT_DIR / "render_daily_v2_editorial.py"), str(editorial),
                    "--classified", str(classified), "--output", str(rendered),
                )
                stamp_source_hash(rendered, raw_path)
                atomic_publish(rendered, target)
                print(f"[✓] published Daily V2: {target}")
                generated += 1
            except (subprocess.CalledProcessError, ValueError) as exc:
                failed += 1
                failures.append(f"{day}: {exc}")
                print(f"[!] {day} rejected; kept work files at {day_work}: {exc}", file=sys.stderr)
    finally:
        if owned_temp is not None and failed == 0:
            owned_temp.cleanup()

    print(f"[summary] generated={generated} skipped={skipped} failed={failed}")
    if failures:
        print("[failures] " + " | ".join(failures), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"SYNC_DAILY_V2_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
