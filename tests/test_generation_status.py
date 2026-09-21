import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "render_generation_status.py"
SPEC = importlib.util.spec_from_file_location("render_generation_status", SCRIPT)
STATUS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(STATUS)


class GenerationStatusTests(unittest.TestCase):
    def test_reports_missing_and_v1_without_silent_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw, daily = root / "raw", root / "daily"
            raw.mkdir(); daily.mkdir()
            (raw / "2026-01-01.md").write_text("raw", encoding="utf-8")
            (raw / "2026-01-02.md").write_text("raw", encoding="utf-8")
            (daily / "2026-01-01.md").write_text(
                '# 2026-01-01\n<!-- personal-memory-daily {"template_version":"daily-v1"} -->',
                encoding="utf-8",
            )
            output = STATUS.render(raw, daily)
        self.assertIn("当前状态：需要处理", output)
        self.assertIn("缺失日报：1", output)
        self.assertIn("非 Daily V2：1", output)


if __name__ == "__main__":
    unittest.main()
