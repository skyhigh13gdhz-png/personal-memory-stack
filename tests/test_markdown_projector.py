import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "project_markdown_journal.py"
SPEC = importlib.util.spec_from_file_location("project_markdown_journal", SCRIPT)
PROJECTOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PROJECTOR)


class ProjectorTests(unittest.TestCase):
    def test_event_date_wins_and_text_is_preserved(self):
        documents = [{
            "id": "doc-1",
            "original_text": "第一行\n## 不应变成日记标题\n```",
            "created_at": "2026-09-18T01:00:00Z",
            "retain_params": {"event_date": "2026-09-19T23:30:00+08:00"},
        }]
        files, manifest = PROJECTOR.build_projection(documents, "Asia/Shanghai")
        self.assertEqual(set(files), {"2026-09-19.md", "_索引.md"})
        rendered = files["2026-09-19.md"]
        self.assertIn(documents[0]["original_text"], rendered)
        self.assertNotIn("time_source:", rendered)
        self.assertNotIn("sha256:", rendered)
        self.assertNotIn("## 23:30 ·", rendered)
        self.assertIn("## 23:30", rendered)
        self.assertIn("<!-- personal-memory-record", rendered)
        self.assertEqual(manifest["documents"][0]["time_source"], "event_date")

    def test_date_precision_does_not_render_placeholder_time(self):
        documents = [{
            "id": "doc-date-only",
            "original_text": "跨越全天的记录",
            "retain_params": {
                "event_date": "2026-09-18T12:00:00+08:00",
                "metadata": {"journal_time_precision": "date"},
            },
        }]
        files, manifest = PROJECTOR.build_projection(documents, "Asia/Shanghai")
        rendered = files["2026-09-18.md"]
        self.assertIn("## 当日记录", rendered)
        self.assertNotIn("## 12:00", rendered)
        self.assertEqual(manifest["documents"][0]["time_precision"], "date")

    def test_midnight_defaults_to_date_only_but_can_be_explicit(self):
        base = {
            "original_text": "午夜锚点",
            "retain_params": {"event_date": "2026-09-17T00:00:00+08:00"},
        }
        files, manifest = PROJECTOR.build_projection([{"id": "implicit", **base}], "Asia/Shanghai")
        self.assertIn("## 当日记录", files["2026-09-17.md"])
        self.assertNotIn("## 00:00", files["2026-09-17.md"])
        self.assertEqual(manifest["documents"][0]["time_precision"], "date")

        explicit = {
            "id": "explicit",
            **base,
            "retain_params": {
                **base["retain_params"],
                "metadata": {"journal_time_precision": "minute"},
            },
        }
        files, manifest = PROJECTOR.build_projection([explicit], "Asia/Shanghai")
        self.assertIn("## 00:00", files["2026-09-17.md"])
        self.assertEqual(manifest["documents"][0]["time_precision"], "minute")

    def test_created_at_fallback_is_not_presented_as_event_time(self):
        documents = [{
            "id": "doc-created",
            "original_text": "只有写入时间",
            "created_at": "2026-09-19T18:00:00Z",
        }]
        files, manifest = PROJECTOR.build_projection(documents, "Asia/Shanghai")
        rendered = files["2026-09-20.md"]
        self.assertIn("## 当日记录", rendered)
        self.assertNotIn("## 02:00", rendered)
        self.assertEqual(manifest["documents"][0]["time_precision"], "date")

    def test_created_at_fallback_and_undated(self):
        documents = [
            {"id": "doc-created", "original_text": "a", "created_at": "2026-09-19T18:00:00Z"},
            {"id": "doc-undated", "original_text": "b", "retain_params": {"event_date": "unset"}},
        ]
        files, manifest = PROJECTOR.build_projection(documents, "Asia/Shanghai")
        self.assertEqual(set(files), {"2026-09-20.md", "_undated.md", "_索引.md"})
        self.assertEqual(manifest["document_count"], 2)

    def test_excluded_hash_is_not_rendered(self):
        text = "deployment smoke"
        import hashlib
        digest = hashlib.sha256(text.encode()).hexdigest()
        files, manifest = PROJECTOR.build_projection(
            [{"id": "smoke", "original_text": text, "created_at": "2026-09-20T00:00:00Z"}],
            "Asia/Shanghai",
            {digest},
        )
        self.assertEqual(set(files), {"_索引.md"})
        self.assertIn("还没有可展示的个人记录", files["_索引.md"])
        self.assertEqual(manifest["document_count"], 0)
        self.assertEqual(manifest["excluded_document_count"], 1)


if __name__ == "__main__":
    unittest.main()
