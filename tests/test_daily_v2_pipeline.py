import importlib.util
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
    def test_uses_short_ids_and_only_daily_units(self):
        units, aliases = PIPELINE.alias_units(classified_fixture(), "2026-01-01")
        self.assertEqual(aliases, {"u01": "unit-long-hash-a"})
        self.assertEqual(units[0]["id"], "u01")
        content = PIPELINE.messages(classified_fixture(), "2026-01-01", {"tone": "自然"})[1]["content"]
        self.assertIn('"id":"u01"', content)
        self.assertNotIn("unit-long-hash-a", content)
        self.assertNotIn("长期资料", content)

    def test_expands_short_ids_before_validation(self):
        response = {
            "schema_version": "daily-view-v2", "date": "2026-01-01",
            "sections": [{"title": "饮食", "groups": [{"items": [{
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


if __name__ == "__main__":
    unittest.main()
