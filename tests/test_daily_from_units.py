import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "render_daily_from_units.py"
SPEC = importlib.util.spec_from_file_location("render_daily_from_units", SCRIPT)
DAILY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(DAILY)


class DailyFromUnitsTests(unittest.TestCase):
    def test_render_includes_classified_and_fallback_without_empty_sections(self):
        value = {
            "schema_version": "classified-evidence-v1",
            "coverage": {
                "units_total": 2,
                "units_classified": 1,
                "units_fallback": 1,
                "units_preserved": 2,
            },
            "units": [
                {
                    "unit_id": "unit-1",
                    "document_id": "doc-1",
                    "date": "2026-01-01",
                    "start": 0,
                    "end": 6,
                    "text": "午饭吃面条。",
                    "summary": "午饭吃面条。",
                    "category": "food",
                    "visibility": "daily",
                    "classification_status": "classified",
                },
                {
                    "unit_id": "unit-2",
                    "document_id": "doc-1",
                    "date": "2026-01-01",
                    "start": 7,
                    "end": 13,
                    "text": "一段未分类原文。",
                    "summary": "一段未分类原文。",
                    "category": "other",
                    "visibility": "daily",
                    "classification_status": "unclassified",
                },
            ],
        }
        text = DAILY.render(value, "2026-01-01")
        self.assertIn("## 饮食与消费", text)
        self.assertIn("## 未分类原文", text)
        self.assertIn("- 一段未分类原文。", text)
        self.assertIn("<!-- evidence unit_id=unit-2", text)
        self.assertNotIn("Evidence Unit", text)
        self.assertNotIn("## 证据索引", text)
        self.assertNotIn("## 睡眠与身体", text)

        audit = DAILY.render(value, "2026-01-01", audit_details=True)
        self.assertIn("Evidence Unit 审计视图", audit)
        self.assertIn("一段未分类原文。 `unclassified` [^unit-2]", audit)
        self.assertIn("「午饭吃面条。」 — `doc-1` chars 0:6", audit)
        self.assertIn("「一段未分类原文。」 — `doc-1` chars 7:13", audit)

    def test_rejects_day_without_visible_units(self):
        value = {
            "schema_version": "classified-evidence-v1",
            "coverage": {"units_total": 0, "units_classified": 0, "units_fallback": 0},
            "units": [],
        }
        with self.assertRaises(ValueError):
            DAILY.render(value, "2026-01-01")


if __name__ == "__main__":
    unittest.main()
