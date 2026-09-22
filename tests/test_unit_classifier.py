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
    def test_markdown_chrome_is_structural(self):
        structural = [
            "## 睡眠复盘", "```", "---", ">", "**", "`**", "> [!note]", "note] 记录说明",
            "> **健康基石**", "</font>", "- **改善计划**：",
        ]
        for text in structural:
            with self.subTest(text=text):
                self.assertTrue(CLASSIFIER.is_structural_heading(text))
        self.assertFalse(CLASSIFIER.is_structural_heading("- **早餐**：10:00，1个玉米1个鸡蛋"))

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
            "units_structural": 0,
            "units_pending_tasks": 0,
            "units_suppressed_tasks": 0,
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

    def test_uniquely_repairs_one_character_unit_id_error(self):
        response = {"labels": [{
            "unit_id": "unit1",
            "category": "work_project",
            "summary": "整理项目。",
            "visibility": "daily",
            "importance": "normal",
            "subject_ids": [],
        }]}
        result = CLASSIFIER.classify_response(evidence_fixture(), response)
        self.assertEqual(result["units"][0]["classification_status"], "classified")
        self.assertEqual(result["label_repairs"], [{
            "source_index": 0,
            "field": "unit_id",
            "from": "unit1",
            "to": "unit-1",
            "method": "unique_edit_distance_1",
        }])

    def test_structural_heading_is_preserved_but_not_sent_for_classification(self):
        evidence = evidence_fixture()
        evidence["units"][0]["text"] = "今天的一些记录："
        messages = CLASSIFIER.classification_messages(evidence)
        self.assertNotIn('"unit_id":"unit-1"', messages[1]["content"])
        result = CLASSIFIER.classify_response(evidence, {"labels": []})
        self.assertEqual(result["units"][0]["classification_status"], "structural")
        self.assertEqual(result["units"][0]["visibility"], "archive")
        self.assertEqual(result["coverage"]["units_structural"], 1)

    def test_pending_markdown_task_is_preserved_but_excluded_from_daily(self):
        evidence = evidence_fixture()
        evidence["units"][0]["text"] = "- [ ] 金刚功或下楼走一圈"
        messages = CLASSIFIER.classification_messages(evidence)
        self.assertNotIn('"unit_id":"unit-1"', messages[1]["content"])
        result = CLASSIFIER.classify_response(evidence, {"labels": []})
        unit = result["units"][0]
        self.assertEqual(unit["classification_status"], "pending_task")
        self.assertEqual(unit["task_status"], "pending")
        self.assertEqual(unit["visibility"], "archive")
        self.assertEqual(unit["summary"], "金刚功或下楼走一圈")
        self.assertEqual(result["coverage"]["units_pending_tasks"], 1)

    def test_completed_markdown_task_is_classified_without_checkbox_chrome(self):
        evidence = evidence_fixture()
        evidence["units"][0]["text"] = "- [x] 跟老婆打网球"
        messages = CLASSIFIER.classification_messages(evidence)
        self.assertIn('"text":"跟老婆打网球"', messages[1]["content"])
        self.assertIn('"task_status":"completed"', messages[1]["content"])

    def test_completed_task_is_suppressed_when_richer_fact_exists(self):
        evidence = evidence_fixture()
        evidence["units"][0]["text"] = "- [x] 网球"
        evidence["units"][1]["text"] = "今天17点跟老婆打网球。"
        labels = []
        for unit, summary in zip(evidence["units"], ("网球", "17点跟老婆打网球")):
            labels.append({
                "unit_id": unit["unit_id"], "category": "exercise", "summary": summary,
                "visibility": "daily", "importance": "normal", "subject_ids": [],
            })
        result = CLASSIFIER.classify_response(evidence, {"labels": labels})
        self.assertEqual(result["units"][0]["classification_status"], "suppressed_task")
        self.assertEqual(result["units"][0]["visibility"], "archive")
        self.assertEqual(result["coverage"]["units_suppressed_tasks"], 1)

    def test_repair_logs_are_preserved_and_deduplicated(self):
        repair = {"field": "unit_id", "from": "bad", "to": "good"}
        other = {"field": "unit_id", "from": "old", "to": "new"}
        self.assertEqual(
            CLASSIFIER.merge_repair_logs([repair], [repair, other]),
            [repair, other],
        )

    def test_prompt_requires_exactly_one_label_for_every_unit(self):
        messages = CLASSIFIER.classification_messages(evidence_fixture())
        self.assertIn("每个 unit_id", messages[0]["content"])
        self.assertIn("不得遗漏、增加或合并 ID", messages[0]["content"])
        self.assertIn("context_before 只用于消解", messages[0]["content"])
        self.assertIn('"unit_id":"unit-2"', messages[1]["content"])
        self.assertIn('"context_before":"整理记忆项目。"', messages[1]["content"])

    def test_repair_prompt_pins_exact_unit_ids(self):
        messages = CLASSIFIER.classification_repair_messages(
            evidence_fixture(), {"labels": [{"unit_id": "changed"}]}, ValueError("coverage mismatch")
        )
        self.assertIn('"unit-1","unit-2"', messages[-1]["content"])
        self.assertIn("逐字复制", messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
