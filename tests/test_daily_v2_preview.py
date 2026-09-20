import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "render_daily_v2_preview.py"
SPEC = importlib.util.spec_from_file_location("render_daily_v2_preview", SCRIPT)
PREVIEW = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PREVIEW)
FIXTURE = Path(__file__).parent / "fixtures" / "golden-v1.json"


class DailyV2PreviewTests(unittest.TestCase):
    def test_render_is_deterministic_and_traceable(self):
        golden = PREVIEW.VALIDATOR.load_json(FIXTURE)
        first = PREVIEW.render(golden, "2026-01-01")
        second = PREVIEW.render(golden, "2026-01-01")
        self.assertEqual(first, second)
        self.assertIn("## 项目推进", first)
        self.assertIn("[^claim-1]", first)
        self.assertIn("「上午9:00开始整理项目需求。」", first)
        self.assertNotIn("无明确记录", first)

    def test_does_not_repeat_summary_section(self):
        golden = PREVIEW.VALIDATOR.load_json(FIXTURE)
        text = PREVIEW.render(golden, "2026-01-01")
        self.assertNotIn("今日事实概览", text)
        self.assertEqual(text.count("上午开始整理项目需求。"), 1)

    def test_rejects_date_without_claims(self):
        golden = PREVIEW.VALIDATOR.load_json(FIXTURE)
        with self.assertRaises(ValueError):
            PREVIEW.render(golden, "2026-01-03")


if __name__ == "__main__":
    unittest.main()
