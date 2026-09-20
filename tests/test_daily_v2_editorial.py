import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "render_daily_v2_editorial.py"
SPEC = importlib.util.spec_from_file_location("render_daily_v2_editorial", SCRIPT)
EDITORIAL = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(EDITORIAL)


def classified_fixture():
    return {
        "units": [
            {"unit_id": "u1", "date": "2026-01-01", "visibility": "daily", "text": "早餐吃面包。",
             "document_id": "d1", "start": 0, "end": 6},
            {"unit_id": "u2", "date": "2026-01-01", "visibility": "daily", "text": "上午处理项目并看盘。",
             "document_id": "d1", "start": 7, "end": 17},
        ]
    }


def editorial_fixture():
    return {
        "schema_version": "daily-view-v2",
        "date": "2026-01-01",
        "sections": [
            {"title": "饮食与消费", "groups": [{"items": [{
                "label": "早餐", "text": "吃了面包。", "evidence_unit_ids": ["u1"]
            }]}]},
            {"title": "项目与工作", "number_groups": True, "groups": [{"title": "示例项目", "items": [{
                "label": "项目推进", "text": "上午处理项目。", "evidence_unit_ids": ["u2"], "facet_split": True
            }]}]},
            {"title": "交易", "groups": [{"items": [{
                "label": "盘中操作", "text": "上午同时看盘。", "evidence_unit_ids": ["u2"], "facet_split": True
            }]}]},
        ],
    }


class DailyV2EditorialTests(unittest.TestCase):
    def test_human_view_is_grouped_and_hides_audit_details(self):
        text = EDITORIAL.render(editorial_fixture(), classified_fixture())
        self.assertIn("### 1. 示例项目", text)
        self.assertIn("- 早餐：吃了面包。", text)
        self.assertIn("<!-- evidence u2 -->", text)
        self.assertNotIn("## 证据索引", text)

    def test_audit_view_shows_full_coverage_and_sources(self):
        text = EDITORIAL.render(editorial_fixture(), classified_fixture(), audit_details=True)
        self.assertIn("日报单元覆盖：2/2", text)
        self.assertIn("条目证据引用：3", text)
        self.assertIn("「早餐吃面包。」", text)

    def test_rejects_missing_daily_unit(self):
        editorial = editorial_fixture()
        editorial["sections"] = editorial["sections"][:1]
        with self.assertRaisesRegex(ValueError, "without editorial destination"):
            EDITORIAL.validate(editorial, classified_fixture())

    def test_rejects_unmarked_repeated_unit(self):
        editorial = editorial_fixture()
        editorial["sections"][1]["groups"][0]["items"][0].pop("facet_split")
        with self.assertRaisesRegex(ValueError, "requires facet_split"):
            EDITORIAL.validate(editorial, classified_fixture())

    def test_inference_requires_uncertainty(self):
        editorial = editorial_fixture()
        item = editorial["sections"][0]["groups"][0]["items"][0]
        item["analysis_status"] = "inference"
        with self.assertRaisesRegex(ValueError, "uncertainty is required"):
            EDITORIAL.validate(editorial, classified_fixture())


if __name__ == "__main__":
    unittest.main()
