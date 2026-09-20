import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "evaluate_candidate_recall.py"
SPEC = importlib.util.spec_from_file_location("evaluate_candidate_recall", SCRIPT)
RECALL = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RECALL)


class CandidateRecallTests(unittest.TestCase):
    def test_reports_missing_required_evidence(self):
        candidates = {"candidates": [{"evidence": [{"quote": "上午完成了项目测试。"}]}]}
        benchmark = {"expected_evidence": [
            {"id": "project", "quote": "完成了项目测试", "importance": "required"},
            {"id": "food", "quote": "中午吃了炒面", "importance": "required"},
            {"id": "weather", "quote": "今天下雨", "importance": "optional"},
        ]}
        result = RECALL.evaluate(candidates, benchmark)
        self.assertEqual(result["required_recall"], 0.5)
        self.assertEqual(result["missing_required"], ["food"])

    def test_rejects_too_short_benchmark_quote(self):
        with self.assertRaisesRegex(ValueError, "too short"):
            RECALL.evaluate(
                {"candidates": []},
                {"expected_evidence": [{"id": "x", "quote": "abc"}]},
            )


if __name__ == "__main__":
    unittest.main()
