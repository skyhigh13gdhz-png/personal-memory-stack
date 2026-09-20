import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_claim_input.py"
SPEC = importlib.util.spec_from_file_location("build_claim_input", SCRIPT)
INPUT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(INPUT)


class ClaimInputTests(unittest.TestCase):
    def test_builds_sorted_private_bundle(self):
        documents = [
            {"id": "b", "original_text": "第二条"},
            {"id": "a", "original_text": "第一条"},
        ]
        subjects = [{
            "subject_id": "project:test",
            "subject_type": "project",
            "canonical_name": "测试",
            "promotion_reason": "测试用",
        }]
        bundle = INPUT.build_bundle(documents, subjects, day="2026-01-01", speaker="liangzai")
        self.assertEqual(bundle["schema_version"], "claim-input-v1")
        self.assertEqual([item["document_id"] for item in bundle["documents"]], ["a", "b"])
        self.assertEqual(bundle["documents"][0]["date"], "2026-01-01")

    def test_rejects_document_without_text(self):
        with self.assertRaisesRegex(ValueError, "original_text"):
            INPUT.build_bundle(
                [{"id": "a", "original_text": ""}],
                [],
                day="2026-01-01",
                speaker="liangzai",
            )


if __name__ == "__main__":
    unittest.main()
