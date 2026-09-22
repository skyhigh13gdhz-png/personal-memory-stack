import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "daily_v2_pipeline.py"
SPEC = importlib.util.spec_from_file_location("daily_v2_pipeline", SCRIPT)
PIPELINE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PIPELINE)


def classified_fixture():
    return {
        "schema_version": "classified-evidence-v1",
        "subjects": [],
        "units": [
            {"unit_id": "unit-long-hash-a", "date": "2026-01-01", "visibility": "daily",
             "text": "早餐吃面包。", "category": "food", "summary": "早餐吃面包", "subject_ids": [],
             "document_id": "d1", "start": 0, "end": 6},
            {"unit_id": "unit-long-hash-b", "date": "2026-01-01", "visibility": "continuity",
             "text": "长期资料。", "category": "other", "summary": "长期资料", "subject_ids": [],
             "document_id": "d1", "start": 7, "end": 12},
        ],
    }


class DailyV2PipelineTests(unittest.TestCase):
    def test_normalize_removes_empty_groups_and_marks_repeated_fact_facets(self):
        editorial = {
            "sections": [
                {"section_id": "food", "groups": [
                    {"group_kind": "facts", "items": []},
                    {"group_kind": "facts", "items": [
                        {"label": "午餐", "text": "A", "evidence_unit_ids": ["u1"]},
                        {"label": "消费", "text": "B", "evidence_unit_ids": ["u1", "u2"]},
                    ]},
                ]},
                {"section_id": "other", "groups": [{"group_kind": "facts", "items": []}]},
            ]
        }
        result = PIPELINE.normalize_editorial_structure(editorial)
        self.assertEqual(len(result["sections"]), 1)
        items = result["sections"][0]["groups"][0]["items"]
        self.assertTrue(items[0]["facet_split"])
        self.assertTrue(items[1]["facet_split"])

    def test_normalize_merges_duplicate_controlled_groups(self):
        editorial = {"sections": [{"section_id": "food", "groups": [
            {"group_id": "breakfast", "group_kind": "facts", "items": [{"label": "A", "text": "A", "evidence_unit_ids": ["u1"]}]},
            {"group_id": "breakfast", "group_kind": "facts", "items": [{"label": "B", "text": "B", "evidence_unit_ids": ["u2"]}]},
        ]}]}
        result = PIPELINE.normalize_editorial_structure(editorial)
        self.assertEqual(len(result["sections"][0]["groups"]), 1)
        self.assertEqual(len(result["sections"][0]["groups"][0]["items"]), 2)

    def test_uses_short_ids_and_only_daily_units(self):
        units, aliases = PIPELINE.alias_units(classified_fixture(), "2026-01-01")
        self.assertEqual(aliases, {"u01": "unit-long-hash-a"})
        self.assertEqual(units[0]["id"], "u01")
        content = PIPELINE.messages(classified_fixture(), "2026-01-01", {"tone": "自然"})[1]["content"]
        self.assertIn('"id":"u01"', content)
        self.assertNotIn("unit-long-hash-a", content)
        self.assertNotIn("长期资料", content)

    def test_repair_prompt_contains_validation_error_and_draft(self):
        draft = {"schema_version": "daily-view-v2", "date": "2026-01-01", "sections": []}
        result = PIPELINE.repair_messages(
            classified_fixture(), "2026-01-01", {"tone": "自然"}, draft,
            ValueError("missing unit-long-hash-a"), {"u01": "unit-long-hash-a"}
        )
        self.assertEqual(result[-2]["role"], "assistant")
        self.assertIn("missing u01", result[-1]["content"])
        self.assertNotIn("unit-long-hash-a", result[-1]["content"])

    def test_completes_small_omission_in_primary_section(self):
        editorial = {
            "schema_version": "daily-view-v2", "date": "2026-01-01",
            "sections": [{"section_id": "food", "groups": [{"group_kind": "facts", "items": []}]}],
        }
        result = PIPELINE.complete_small_omissions(editorial, classified_fixture())
        item = result["sections"][0]["groups"][0]["items"][0]
        self.assertEqual(item["evidence_unit_ids"], ["unit-long-hash-a"])
        self.assertEqual(item["label"], "饮食记录")
        self.assertEqual(result["sections"][0]["groups"][0]["group_id"], "breakfast")
        self.assertEqual(item["period"], "morning")

    def test_morning_water_and_food_falls_back_to_breakfast(self):
        classified = classified_fixture()
        classified["units"][0].update({
            "text": "晨间喝了一杯热水，吃了点东西。",
            "summary": "晨间喝热水并吃了点东西",
        })
        editorial = {"schema_version": "daily-view-v2", "date": "2026-01-01", "sections": []}
        result = PIPELINE.complete_small_omissions(editorial, classified)
        group = result["sections"][0]["groups"][0]
        self.assertEqual(group["group_id"], "breakfast")
        self.assertEqual(group["items"][0]["period"], "morning")

    def test_applies_configured_style_replacements(self):
        editorial = {"sections": [{"groups": [{"items": [{"label": "关系", "text": "跟妻子共进晚餐"}]}]}]}
        result = PIPELINE.apply_style_replacements(
            editorial, {"replacements": {"妻子": "老婆", "共进": "一起吃"}}
        )
        self.assertEqual(result["sections"][0]["groups"][0]["items"][0]["text"], "跟老婆一起吃晚餐")

    def test_drops_fact_item_reusing_reflection_evidence_outside_primary_section(self):
        classified = classified_fixture()
        classified["units"][0]["category"] = "reflection_growth"
        editorial = {"sections": [
            {"section_id": "trading_finance", "groups": [{
                "group_id": "reflection", "group_kind": "facts", "items": [{
                    "label": "交易情绪", "text": "起了情绪", "evidence_unit_ids": ["unit-long-hash-a"]
                }],
            }]},
            {"section_id": "reflection_growth", "groups": [{
                "group_id": "event", "group_kind": "facts", "items": [{
                    "label": "情绪事件", "text": "起了情绪", "evidence_unit_ids": ["unit-long-hash-a"]
                }],
            }]},
        ]}
        result = PIPELINE.enforce_exclusive_primary_sections(editorial, classified)
        self.assertEqual([item["section_id"] for item in result["sections"]], ["reflection_growth"])

    def test_drops_any_item_with_evidence_in_wrong_primary_section(self):
        editorial = {"sections": [{"section_id": "sleep", "groups": [{
            "group_id": "body_state", "group_kind": "facts", "items": [{
                "label": "身体状态", "text": "早餐吃面包", "period": "morning",
                "evidence_unit_ids": ["unit-long-hash-a"],
            }],
        }]}]}
        result = PIPELINE.enforce_primary_section_membership(editorial, classified_fixture())
        self.assertEqual(result["sections"], [])

    def test_splits_model_merged_events_from_distinct_periods(self):
        classified = classified_fixture()
        classified["units"].append({
            "unit_id": "unit-night", "date": "2026-01-01", "visibility": "daily",
            "text": "半夜开仓。", "summary": "半夜开仓", "category": "food", "subject_ids": [],
            "document_id": "d1", "start": 13, "end": 18,
        })
        editorial = {"sections": [{"section_id": "food", "groups": [{
            "group_id": "breakfast", "group_kind": "facts", "items": [{
                "label": "记录", "text": "半夜开仓，早上吃面包。", "period": "morning",
                "evidence_unit_ids": ["unit-night", "unit-long-hash-a"],
            }],
        }]}]}
        result = PIPELINE.split_cross_period_items(editorial, classified)
        items = result["sections"][0]["groups"][0]["items"]
        self.assertEqual([item["period"] for item in items], ["overnight", "morning"])
        self.assertEqual([item["evidence_unit_ids"] for item in items], [["unit-night"], ["unit-long-hash-a"]])

    def test_anaphoric_event_inherits_previous_source_period(self):
        classified = classified_fixture()
        classified["units"] = [
            {**classified["units"][0], "unit_id": "night", "text": "凌晨回床睡觉。", "summary": "凌晨回床睡觉", "start": 0},
            {**classified["units"][0], "unit_id": "during", "text": "期间老婆热醒，拿了风扇。", "summary": "期间老婆热醒，拿了风扇", "start": 10},
        ]
        editorial = {"sections": [{"section_id": "relationships_home", "groups": [{
            "group_id": "partner", "group_kind": "facts", "items": [{
                "label": "家庭记录", "text": "期间老婆热醒，拿了风扇。", "period": "unknown",
                "evidence_unit_ids": ["during"],
            }],
        }]}]}
        result = PIPELINE.ground_unknown_periods(editorial, classified)
        self.assertEqual(result["sections"][0]["groups"][0]["items"][0]["period"], "overnight")

    def test_expands_short_ids_before_validation(self):
        response = {
            "schema_version": "daily-view-v2", "date": "2026-01-01",
            "sections": [{"section_id": "food", "groups": [{"group_kind": "facts", "items": [{
                "label": "早餐", "text": "吃了面包。", "evidence_unit_ids": ["u01"]
            }]}]}],
        }
        expanded = PIPELINE.expand_aliases(response, {"u01": "unit-long-hash-a"})
        self.assertEqual(
            expanded["sections"][0]["groups"][0]["items"][0]["evidence_unit_ids"],
            ["unit-long-hash-a"],
        )

    def test_rejects_unknown_short_id(self):
        response = {
            "sections": [{"groups": [{"items": [{"evidence_unit_ids": ["u99"]}]}]}]
        }
        with self.assertRaisesRegex(ValueError, "unknown short unit ids"):
            PIPELINE.expand_aliases(response, {"u01": "unit-long-hash-a"})

    def test_hash_changes_with_style(self):
        first = PIPELINE.source_hash(classified_fixture(), "2026-01-01", {"tone": "自然"}, "model")
        second = PIPELINE.source_hash(classified_fixture(), "2026-01-01", {"tone": "书面"}, "model")
        self.assertNotEqual(first, second)

    def test_prompt_keeps_trading_out_of_project_groups(self):
        prompt = PIPELINE.messages(classified_fixture(), "2026-01-01", {})[0]["content"]
        self.assertIn("交易操作、盘面、盈亏", prompt)
        self.assertIn("不得在 project_work 下再建‘交易’分组", prompt)

    def test_rejected_response_is_quarantined_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "daily.json"
            rejected = PIPELINE.write_rejection(
                output, {"bad": True}, {"calls": 1}, ValueError("quality failed")
            )
            self.assertFalse(output.exists())
            self.assertTrue(rejected.exists())
            self.assertIn("quality failed", rejected.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
