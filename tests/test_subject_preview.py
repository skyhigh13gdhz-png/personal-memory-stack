import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "render_subject_preview.py"
SPEC = importlib.util.spec_from_file_location("render_subject_preview", SCRIPT)
SUBJECT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SUBJECT)
FIXTURE = Path(__file__).parent / "fixtures" / "golden-v1.json"


class SubjectPreviewTests(unittest.TestCase):
    def test_render_keeps_state_uninferred(self):
        golden = SUBJECT.VALIDATOR.load_json(FIXTURE)
        text = SUBJECT.render(golden, "project:memory-system")
        self.assertIn("# 个人记忆系统", text)
        self.assertIn("未由单条记录自动推断", text)
        self.assertIn("[[2026-01-01 日回顾|2026-01-01]]", text)
        self.assertIn("[[2026-01-02 日回顾|2026-01-02]]", text)

    def test_rejects_unknown_subject(self):
        golden = SUBJECT.VALIDATOR.load_json(FIXTURE)
        with self.assertRaises(ValueError):
            SUBJECT.render(golden, "missing")


if __name__ == "__main__":
    unittest.main()
