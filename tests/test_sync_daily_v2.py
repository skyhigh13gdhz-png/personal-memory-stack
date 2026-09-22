import importlib.util
import hashlib
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "sync_daily_v2.py"
SPEC = importlib.util.spec_from_file_location("sync_daily_v2", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SyncDailyV2Tests(unittest.TestCase):
    def test_stamp_source_hash_tracks_exact_raw_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw.md"
            rendered = root / "daily.md"
            raw.write_text("修正后原文", encoding="utf-8")
            rendered.write_text("# 日报\n", encoding="utf-8")
            digest = MODULE.stamp_source_hash(rendered, raw)
            self.assertEqual(digest, hashlib.sha256(raw.read_bytes()).hexdigest())
            self.assertIn(f"daily-v2-source-sha256:{digest}", rendered.read_text(encoding="utf-8"))

    def test_parse_projected_day_preserves_multiple_documents(self):
        content = """# 2026年9月20日

## 当日记录

第一条。

<!-- personal-memory-record {\"document_id\":\"doc-1\",\"sha256\":\"a\",\"time_source\":\"event_date\"} -->

---

## 20:30

第二条。

<!-- personal-memory-record {\"document_id\":\"doc-2\",\"sha256\":\"b\",\"time_source\":\"event_date\"} -->

---
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "2026-09-20.md"
            path.write_text(content, encoding="utf-8")
            documents = MODULE.parse_projected_day(path, "2026-09-20")
        self.assertEqual([item["document_id"] for item in documents], ["doc-1", "doc-2"])
        self.assertEqual([item["original_text"] for item in documents], ["第一条。", "第二条。"])


if __name__ == "__main__":
    unittest.main()
