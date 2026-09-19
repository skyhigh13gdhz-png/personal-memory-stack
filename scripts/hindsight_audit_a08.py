#!/usr/bin/env python3
"""Export an audit bank, import it into a fresh bank, and compare public API state."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def request(
    method: str,
    url: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    expected: tuple[int, ...] = (200,),
    timeout: int = 300,
) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    if status not in expected:
        raise RuntimeError(f"{method} {url} returned HTTP {status}: {raw[:1000]!r}")
    return status, raw


def request_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    expected: tuple[int, ...] = (200,),
) -> tuple[int, Any]:
    encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if encoded is not None:
        headers["Content-Type"] = "application/json"
    status, raw = request(method, url, encoded, headers, expected)
    return status, json.loads(raw.decode("utf-8")) if raw else None


def save(root: Path, name: str, value: Any) -> None:
    (root / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_documents(base: str, bank: str) -> dict[str, Any]:
    _, result = request_json("GET", f"{base}/v1/default/banks/{bank}/documents?limit=1000&offset=0")
    return result


def get_document(base: str, bank: str, document_id: str) -> dict[str, Any]:
    quoted = urllib.parse.quote(document_id, safe="")
    _, result = request_json("GET", f"{base}/v1/default/banks/{bank}/documents/{quoted}")
    return result


def list_memories(base: str, bank: str, document_id: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"document_id": document_id, "limit": 1000})
    _, result = request_json("GET", f"{base}/v1/default/banks/{bank}/memories/list?{query}")
    return result


def snapshot(base: str, bank: str) -> dict[str, Any]:
    listing = list_documents(base, bank)
    documents: dict[str, Any] = {}
    for item in listing.get("items", []):
        document_id = item["id"]
        document = get_document(base, bank, document_id)
        memories = list_memories(base, bank, document_id)
        original = document.get("original_text")
        documents[document_id] = {
            "original_text_sha256": (
                hashlib.sha256(original.encode("utf-8")).hexdigest() if isinstance(original, str) else None
            ),
            "content_hash": document.get("content_hash"),
            "tags": sorted(document.get("tags") or []),
            "document_metadata": document.get("document_metadata"),
            "retain_params": document.get("retain_params"),
            "memory_unit_count": document.get("memory_unit_count"),
            "memory_list_total": memories.get("total", len(memories.get("items", []))),
        }
    return {"bank_id": bank, "total": listing.get("total"), "documents": documents}


def wait_operation(base: str, bank: str, operation_id: str, timeout_seconds: int = 300) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        _, result = request_json(
            "GET", f"{base}/v1/default/banks/{bank}/operations/{urllib.parse.quote(operation_id, safe='')}"
        )
        if result.get("status") == "completed":
            return result
        if result.get("status") in {"failed", "cancelled", "not_found"}:
            raise RuntimeError(f"operation {operation_id} ended as {result.get('status')}: {result}")
        time.sleep(1)
    raise TimeoutError(f"operation {operation_id} did not finish within {timeout_seconds}s")


def multipart_file(field: str, path: Path) -> tuple[bytes, str]:
    boundary = f"----personal-memory-{uuid.uuid4().hex}"
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8")
    suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return prefix + path.read_bytes() + suffix, boundary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hindsight", default="http://127.0.0.1:8888")
    parser.add_argument("--source-bank", required=True)
    parser.add_argument("--restore-bank", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if not args.source_bank.startswith("audit-") or not args.restore_bank.startswith("audit-"):
        raise SystemExit("source and restore bank names must start with audit-")
    if args.source_bank == args.restore_bank:
        raise SystemExit("restore bank must differ from source bank")

    base = args.hindsight.rstrip("/")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    source = snapshot(base, args.source_bank)
    if not source["documents"]:
        raise RuntimeError("source bank contains no documents")
    save(output, "source-snapshot.json", source)

    _, submit = request_json(
        "POST",
        f"{base}/v1/default/banks/{args.source_bank}/document-transfer/export"
        "?include_observations=false&include_knowledge_base=false",
        expected=(202,),
    )
    export_status = wait_operation(base, args.source_bank, submit["operation_id"])
    save(output, "export-operation.json", export_status)
    metadata = export_status.get("result_metadata") or {}
    download_url = metadata.get("download_url")
    if not download_url:
        key = metadata.get("storage_key")
        if not key:
            raise RuntimeError(f"export completed without download_url/storage_key: {export_status}")
        download_url = f"/v1/default/files/download/{urllib.parse.quote(key, safe='/')}"
    if download_url.startswith("/"):
        download_url = base + download_url
    _, archive = request("GET", download_url)
    archive_path = output / (metadata.get("filename") or "document-export.zip")
    archive_path.write_bytes(archive)
    archive_sha256 = hashlib.sha256(archive).hexdigest()
    with zipfile.ZipFile(archive_path) as zipped:
        zip_entries = sorted(zipped.namelist())

    multipart, boundary = multipart_file("file", archive_path)
    _, import_submit_raw = request(
        "POST",
        f"{base}/v1/default/banks/{args.restore_bank}/document-transfer?on_conflict=replace",
        multipart,
        {
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        expected=(202,),
    )
    import_submit = json.loads(import_submit_raw.decode("utf-8"))
    import_status = wait_operation(base, args.restore_bank, import_submit["operation_id"])
    save(output, "import-operation.json", import_status)

    restored = snapshot(base, args.restore_bank)
    save(output, "restore-snapshot.json", restored)
    source_docs = source["documents"]
    restored_docs = restored["documents"]
    comparisons: dict[str, Any] = {}
    for document_id in sorted(set(source_docs) | set(restored_docs)):
        before = source_docs.get(document_id)
        after = restored_docs.get(document_id)
        comparisons[document_id] = {
            "present_in_source": before is not None,
            "present_in_restore": after is not None,
            "original_text_sha256_equal": bool(before and after) and before["original_text_sha256"] == after["original_text_sha256"],
            "content_hash_equal": bool(before and after) and before["content_hash"] == after["content_hash"],
            "tags_equal": bool(before and after) and before["tags"] == after["tags"],
            "metadata_equal": bool(before and after) and before["document_metadata"] == after["document_metadata"],
            "retain_params_equal": bool(before and after) and before["retain_params"] == after["retain_params"],
            "memory_unit_count_equal": bool(before and after) and before["memory_unit_count"] == after["memory_unit_count"],
            "memory_list_total_equal": bool(before and after) and before["memory_list_total"] == after["memory_list_total"],
        }
    passed = (
        source["total"] == restored["total"]
        and set(source_docs) == set(restored_docs)
        and all(all(value for key, value in item.items() if key != "present_in_source") for item in comparisons.values())
    )
    summary = {
        "status": "PASS" if passed else "FAIL",
        "source_bank": args.source_bank,
        "restore_bank": args.restore_bank,
        "document_count_source": source["total"],
        "document_count_restore": restored["total"],
        "archive_bytes": len(archive),
        "archive_sha256": archive_sha256,
        "zip_entries": zip_entries,
        "export_operation_id": submit["operation_id"],
        "import_operation_id": import_submit["operation_id"],
        "comparisons": comparisons,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    save(output, "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"AUDIT_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
