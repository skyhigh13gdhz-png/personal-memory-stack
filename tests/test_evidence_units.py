import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_evidence_units.py"
SPEC = importlib.util.spec_from_file_location("build_evidence_units", SCRIPT)
UNITS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(UNITS)


class EvidenceUnitTests(unittest.TestCase):
    def test_sentence_units_are_lossless_and_stable(self):
        document = {
            "document_id": "doc-1",
            "date": "2026-01-01",
            "original_text": "早上起床。\n\n猫体重 3.35kg，喜欢逗猫棒！",
        }
        first = UNITS.split_document(document)
        second = UNITS.split_document(document)
        self.assertEqual(first, second)
        self.assertEqual([item["text"] for item in first], ["早上起床。", "猫体重 3.35kg，喜欢逗猫棒！"])
        self.assertEqual(
            UNITS.content_fingerprint("".join(item["text"] for item in first)),
            UNITS.content_fingerprint(document["original_text"]),
        )

    def test_build_records_full_document_coverage(self):
        bundle = {"speaker": "liangzai", "date": "2026-01-01", "subjects": []}
        documents = [
            {"document_id": "a", "date": "2026-01-01", "original_text": "第一条。"},
            {"document_id": "b", "date": "2026-01-01", "original_text": "第二条。"},
        ]
        result = UNITS.build_units(bundle, documents)
        self.assertEqual(result["document_count"], 2)
        self.assertEqual(result["unit_count"], 2)
        self.assertEqual(result["coverage"]["non_whitespace_content"], "100%")
        self.assertTrue(all(item["classification_status"] == "unclassified" for item in result["units"]))

    def test_splits_adjacent_chinese_sentences_without_spaces(self):
        document = {
            "document_id": "doc-1",
            "date": "2026-01-01",
            "original_text": "凌晨睡觉。早上起床。早餐吃面包。",
        }
        units = UNITS.split_document(document)
        self.assertEqual(
            [item["text"] for item in units],
            ["凌晨睡觉。", "早上起床。", "早餐吃面包。"],
        )
        self.assertEqual(UNITS.content_fingerprint("".join(item["text"] for item in units)),
                         UNITS.content_fingerprint(document["original_text"]))


if __name__ == "__main__":
    unittest.main()
