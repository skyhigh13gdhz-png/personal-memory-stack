import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "score_daily_v2.py"
SPEC = importlib.util.spec_from_file_location("score_daily_v2", SCRIPT)
SCORER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SCORER)


def classified_fixture():
    return {
        "units": [{
            "unit_id": "u1", "date": "2026-01-01", "visibility": "daily", "category": "food",
            "text": "早餐跟老婆吃面包。", "document_id": "d1", "start": 0, "end": 9,
        }]
    }


def editorial_fixture():
    return {
        "schema_version": "daily-view-v2", "date": "2026-01-01",
        "sections": [{"section_id": "food", "groups": [{"group_kind": "facts", "items": [{
            "label": "早餐", "text": "早餐跟老婆吃了面包。", "evidence_unit_ids": ["u1"],
        }]}]}],
    }


class DailyV2ScoreTests(unittest.TestCase):
    def test_golden_style_passes(self):
        report = SCORER.score(editorial_fixture(), classified_fixture(), {
            "preserve_terms": ["老婆"], "avoid_terms": ["妻子"],
        })
        self.assertTrue(report["passed"])
        self.assertEqual(report["score"], 100)

    def test_forbidden_tone_is_hard_failure(self):
        editorial = editorial_fixture()
        editorial["sections"][0]["groups"][0]["items"][0]["text"] = "早餐与妻子共进面包。"
        report = SCORER.score(editorial, classified_fixture(), {
            "preserve_terms": ["老婆"], "avoid_terms": ["妻子", "共进"],
        })
        self.assertFalse(report["passed"])
        self.assertIn("妻子", report["diagnostics"]["forbidden_terms"])
        self.assertIn("老婆", report["diagnostics"]["missing_preserved_terms"])

    def test_invalid_hierarchy_cannot_pass_by_score(self):
        editorial = editorial_fixture()
        editorial["sections"][0]["section_id"] = "饮食"
        report = SCORER.score(editorial, classified_fixture(), {})
        self.assertFalse(report["passed"])
        self.assertTrue(report["diagnostics"]["structural_errors"])

    def test_missing_required_personal_term_is_hard_failure(self):
        editorial = editorial_fixture()
        editorial["sections"][0]["groups"][0]["items"][0]["text"] = "早餐吃了面包。"
        report = SCORER.score(editorial, classified_fixture(), {"preserve_terms": ["老婆"]})
        self.assertFalse(report["passed"])
        self.assertIn("老婆", report["diagnostics"]["missing_preserved_terms"])


if __name__ == "__main__":
    unittest.main()
