import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "classify_evidence_units.py"
SPEC = importlib.util.spec_from_file_location("classify_evidence_units", SCRIPT)
CLASSIFIER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CLASSIFIER)


def evidence_fixture():
    return {
        "schema_version": "evidence-units-v1",
        "source_sha256": "source-hash",
        "subjects": [{
            "subject_id": "project-memory",
            "subject_type": "project",
            "canonical_name": "外置记忆",
        }],
        "units": [
            {
                "unit_id": "unit-1",
                "document_id": "doc-1",
                "date": "2026-01-01",
                "start": 0,
                "end": 6,
                "text": "整理记忆项目。",
                "text_sha256": "one",
                "classification_status": "unclassified",
            },
            {
                "unit_id": "unit-2",
                "document_id": "doc-1",
                "date": "2026-01-01",
                "start": 7,
                "end": 13,
                "text": "晚上吃面条。",
                "text_sha256": "two",
                "classification_status": "unclassified",
            },
        ],
    }


class UnitClassifierTests(unittest.TestCase):
    def test_partial_response_preserves_every_unit_with_fallback(self):
        response = {"labels": [{
            "unit_id": "unit-1",
            "category": "work_project",
            "summary": "整理外置记忆项目。",
            "visibility": "both",
            "importance": "high",
            "subject_ids": ["project-memory"],
        }]}
        result = CLASSIFIER.classify_response(evidence_fixture(), response)
        self.assertEqual([item["unit_id"] for item in result["units"]], ["unit-1", "unit-2"])
        self.assertEqual(result["coverage"], {
            "units_total": 2,
            "units_classified": 1,
            "units_fallback": 1,
            "units_preserved": 2,
        })
        self.assertEqual(result["units"][1]["summary"], "晚上吃面条。")
        self.assertEqual(result["units"][1]["classification_status"], "unclassified")

    def test_invalid_subject_is_quarantined_without_losing_unit(self):
        response = {"labels": [{
            "unit_id": "unit-1",
            "category": "work_project",
            "summary": "整理项目。",
            "visibility": "daily",
            "importance": "normal",
            "subject_ids": ["invented-subject"],
        }]}
        result = CLASSIFIER.classify_response(evidence_fixture(), response)
        self.assertEqual(result["coverage"]["units_fallback"], 2)
        self.assertEqual(result["rejected_labels"][0]["error"], "unknown subject_id")

    def test_prompt_requires_exactly_one_label_for_every_unit(self):
        messages = CLASSIFIER.classification_messages(evidence_fixture())
        self.assertIn("每个 unit_id", messages[0]["content"])
        self.assertIn("不得遗漏、增加或合并 ID", messages[0]["content"])
        self.assertIn("context_before 只用于消解", messages[0]["content"])
        self.assertIn('"unit_id":"unit-2"', messages[1]["content"])
        self.assertIn('"context_before":"整理记忆项目。"', messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
