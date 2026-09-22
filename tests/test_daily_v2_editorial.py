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
            {"unit_id": "u1", "date": "2026-01-01", "visibility": "daily", "category": "food", "text": "早餐吃面包。",
             "document_id": "d1", "start": 0, "end": 6},
            {"unit_id": "u2", "date": "2026-01-01", "visibility": "daily", "category": "work_project", "text": "上午处理项目并看盘。",
             "document_id": "d1", "start": 7, "end": 17},
        ]
    }


def editorial_fixture():
    return {
        "schema_version": "daily-view-v2",
        "date": "2026-01-01",
        "sections": [
            {"section_id": "food", "groups": [{"group_id": "breakfast", "group_kind": "facts", "items": [{
                "label": "早餐", "text": "吃了面包。", "period": "morning", "evidence_unit_ids": ["u1"]
            }]}]},
            {"section_id": "project_work", "groups": [{"group_id": "project", "group_kind": "facts", "title": "示例项目", "items": [{
                "label": "项目推进", "text": "上午处理项目。", "period": "morning", "evidence_unit_ids": ["u2"], "facet_split": True
            }]}]},
            {"section_id": "trading_finance", "groups": [{"group_id": "execution", "group_kind": "facts", "items": [{
                "label": "盘中操作", "text": "上午同时看盘。", "period": "morning", "evidence_unit_ids": ["u2"], "facet_split": True
            }]}]},
        ],
    }


class DailyV2EditorialTests(unittest.TestCase):
    def test_sleep_groups_render_in_fixed_human_priority(self):
        classified = {"units": [
            {"unit_id": "night", "date": "2026-01-01", "visibility": "daily", "category": "sleep_body",
             "text": "凌晨0点入睡。", "document_id": "d1", "start": 0, "end": 6},
            {"unit_id": "nap", "date": "2026-01-01", "visibility": "daily", "category": "sleep_body",
             "text": "下午午休。", "document_id": "d1", "start": 7, "end": 13},
        ]}
        editorial = {"schema_version": "daily-view-v2", "date": "2026-01-01", "sections": [{
            "section_id": "sleep", "groups": [
                {"group_id": "nap", "group_kind": "facts", "items": [
                    {"label": "时间", "text": "下午午休。", "period": "afternoon", "evidence_unit_ids": ["nap"]}]},
                {"group_id": "night_sleep", "group_kind": "facts", "items": [
                    {"label": "入睡", "text": "凌晨0点入睡。", "period": "overnight", "evidence_unit_ids": ["night"]}]},
            ],
        }]}
        text = EDITORIAL.render(editorial, classified)
        self.assertLess(text.index("### 夜间睡眠"), text.index("### 午间休息"))

    def test_rejects_duplicate_semantic_group_in_one_section(self):
        editorial = editorial_fixture()
        duplicate = dict(editorial["sections"][0]["groups"][0])
        editorial["sections"][0]["groups"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "cluster related items together"):
            EDITORIAL.validate(editorial, classified_fixture())

    def test_reflection_evidence_cannot_be_duplicated_into_trading(self):
        classified = classified_fixture()
        classified["units"].append({
            "unit_id": "u3", "date": "2026-01-01", "visibility": "daily",
            "category": "reflection_growth", "text": "亏损后起情绪。",
            "document_id": "d1", "start": 18, "end": 25,
        })
        editorial = editorial_fixture()
        editorial["sections"].append({
            "section_id": "reflection_growth", "groups": [{
                "group_id": "event", "group_kind": "facts", "items": [{
                    "label": "情绪事件", "text": "亏损后起情绪。",
                    "period": "unknown", "evidence_unit_ids": ["u3"], "facet_split": True,
                }],
            }],
        })
        editorial["sections"][2]["groups"][0]["items"].append({
            "label": "情绪交易", "text": "亏损后起了情绪。",
            "period": "unknown", "evidence_unit_ids": ["u3"], "facet_split": True,
        })
        with self.assertRaisesRegex(ValueError, "must not be duplicated outside"):
            EDITORIAL.validate(editorial, classified)

    def test_human_view_is_grouped_and_hides_audit_details(self):
        text = EDITORIAL.render(editorial_fixture(), classified_fixture())
        self.assertIn("## 项目与工作", text)
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

    def test_rejects_cross_section_duplicate_meaning_even_when_facet_split(self):
        editorial = editorial_fixture()
        editorial["sections"][2]["groups"][0]["items"][0]["text"] = "上午处理项目。"
        with self.assertRaisesRegex(ValueError, "cross-section duplicate facts"):
            EDITORIAL.validate(editorial, classified_fixture())

    def test_items_render_in_event_time_order_within_same_topic(self):
        editorial = editorial_fixture()
        group = editorial["sections"][0]["groups"][0]
        group["items"] = [
            {"label": "晚间", "text": "晚上吃水果。", "period": "evening", "evidence_unit_ids": ["u1"], "facet_split": True},
            {"label": "早餐", "text": "早上吃面包。", "period": "morning", "evidence_unit_ids": ["u1"], "facet_split": True},
        ]
        text = EDITORIAL.render(editorial, classified_fixture())
        self.assertLess(text.index("早上吃面包"), text.index("晚上吃水果"))

    def test_rejects_one_item_mixing_morning_and_night_events(self):
        editorial = editorial_fixture()
        item = editorial["sections"][0]["groups"][0]["items"][0]
        item.update({"text": "早上喝水，晚上吃饭。", "period": "morning"})
        with self.assertRaisesRegex(ValueError, "mixes distinct event periods"):
            EDITORIAL.validate(editorial, classified_fixture())

    def test_inference_requires_uncertainty(self):
        editorial = editorial_fixture()
        group = editorial["sections"][0]["groups"][0]
        group["group_kind"] = "analysis"
        item = group["items"][0]
        item["analysis_status"] = "inference"
        with self.assertRaisesRegex(ValueError, "uncertainty is required"):
            EDITORIAL.validate(editorial, classified_fixture())

    def test_rejects_project_promoted_to_free_form_section(self):
        editorial = editorial_fixture()
        editorial["sections"][1]["section_id"] = "personal_memory_project"
        with self.assertRaisesRegex(ValueError, "requires valid section_id"):
            EDITORIAL.validate(editorial, classified_fixture())

    def test_rejects_observation_on_fact_item(self):
        editorial = editorial_fixture()
        editorial["sections"][0]["groups"][0]["items"][0]["analysis_status"] = "observation"
        with self.assertRaisesRegex(ValueError, "must be in analysis group"):
            EDITORIAL.validate(editorial, classified_fixture())

    def test_calculated_item_requires_multiple_evidence_units(self):
        editorial = editorial_fixture()
        editorial["sections"][0]["groups"][0]["items"][0]["analysis_status"] = "calculated"
        with self.assertRaisesRegex(ValueError, "requires at least two"):
            EDITORIAL.validate(editorial, classified_fixture())


if __name__ == "__main__":
    unittest.main()
