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
