import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_daily_v1.py"
SPEC = importlib.util.spec_from_file_location("build_daily_v1", SCRIPT)
DAILY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(DAILY)


class DailyV1Tests(unittest.TestCase):
    def test_source_hash_is_order_independent(self):
        documents = [
            {"id": "b", "original_text": "晚饭"},
            {"id": "a", "original_text": "午饭"},
        ]
        first, first_hash = DAILY.source_payload(documents)
        second, second_hash = DAILY.source_payload(list(reversed(documents)))
        self.assertEqual(first, second)
        self.assertEqual(first_hash, second_hash)

    def test_validation_rejects_free_form_schema(self):
        with self.assertRaises(RuntimeError):
            DAILY.validate_report({"summary": ["自由格式"]})

    def test_render_has_fixed_sections_and_trace_metadata(self):
        report = DAILY.validate_report({"food": ["中午吃了炒面。"]})
        text = DAILY.render_markdown(
            "2026-09-17",
            report,
            speaker="liangzai",
            source_hash="a" * 64,
            source_ids=["doc-1"],
            model="glm-test",
        )
        self.assertIn("## 饮食\n\n- 中午吃了炒面。", text)
        self.assertIn("## 睡眠与身体\n\n- 无明确记录", text)
        self.assertIn('"template_version":"daily-v1"', text)
        self.assertIn("`doc-1`", text)

    def test_existing_hash_requires_matching_template(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.md"
            metadata = {
                "template_version": "daily-v1",
                "source_sha256": "b" * 64,
            }
            path.write_text(
                f"# report\n<!-- personal-memory-daily {json.dumps(metadata)} -->\n",
                encoding="utf-8",
            )
            self.assertEqual(DAILY.existing_source_hash(path), "b" * 64)


if __name__ == "__main__":
    unittest.main()
