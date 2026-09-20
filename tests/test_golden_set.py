import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_golden_set.py"
SPEC = importlib.util.spec_from_file_location("validate_golden_set", SCRIPT)
GOLDEN = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(GOLDEN)
FIXTURE = Path(__file__).parent / "fixtures" / "golden-v1.json"


class GoldenSetTests(unittest.TestCase):
    def test_valid_fixture(self):
        value = GOLDEN.load_json(FIXTURE)
        self.assertEqual(GOLDEN.validate(value, base_dir=FIXTURE.parent), [])

    def test_rejects_non_verbatim_evidence(self):
        value = GOLDEN.load_json(FIXTURE)
        value["claims"][0]["evidence"][0]["quote"] = "原文中不存在"
        errors = GOLDEN.validate(value, base_dir=FIXTURE.parent)
        self.assertTrue(any("not found verbatim" in error for error in errors))

    def test_rejects_unreferenced_document(self):
        value = GOLDEN.load_json(FIXTURE)
        value["claims"] = value["claims"][:1]
        errors = GOLDEN.validate(value, base_dir=FIXTURE.parent)
        self.assertTrue(any("documents without any claim evidence" in error for error in errors))

    def test_supports_private_source_paths(self):
        value = GOLDEN.load_json(FIXTURE)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.md"
            source.write_text("真实原文。", encoding="utf-8")
            value["documents"] = [{
                "document_id": "private",
                "date": "2026-01-01",
                "source_path": str(source),
            }]
            value["claims"] = [{
                "claim_id": "private-claim",
                "kind": "event",
                "summary": "真实原文。",
                "valid_date": "2026-01-01",
                "epistemic_status": "asserted",
                "subject_ids": [],
                "evidence": [{"document_id": "private", "quote": "真实原文。"}],
            }]
            value["forbidden_inferences"] = []
            self.assertEqual(GOLDEN.validate(value, base_dir=Path(directory)), [])


if __name__ == "__main__":
    unittest.main()
