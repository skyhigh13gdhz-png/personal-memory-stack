import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BUILDER = load("build_continuity_candidates", "build_continuity_candidates.py")
RENDERER = load("render_continuity_candidate_review", "render_continuity_candidate_review.py")


def fixture():
    return {
        "schema_version": "classified-evidence-v1",
        "subjects": [{
            "subject_id": "project:memory", "subject_type": "project",
            "canonical_name": "外置记忆", "promotion_reason": "用户确认项目",
        }],
        "units": [{
            "unit_id": "u1", "date": "2026-01-01", "text": "完成接口测试。",
            "summary": "完成接口测试", "document_id": "d1", "start": 0, "end": 7,
            "category": "work_project", "visibility": "daily", "subject_ids": ["project:memory"],
        }, {
            "unit_id": "u2", "date": "2026-01-01", "text": "午餐吃面。",
            "summary": "午餐吃面", "document_id": "d1", "start": 8, "end": 13,
            "category": "food", "visibility": "daily", "subject_ids": [],
        }],
    }


class ContinuityCandidatesTests(unittest.TestCase):
    def test_builds_only_confirmed_subject_links_without_state_updates(self):
        bundle = BUILDER.build(fixture())
        self.assertEqual(bundle["metrics"]["candidate_links"], 1)
        self.assertEqual(bundle["metrics"]["llm_calls"], 0)
        candidate = bundle["subjects"][0]["candidates"][0]
        self.assertFalse(candidate["state_update_allowed"])
        self.assertEqual(candidate["original_text"], "完成接口测试。")

    def test_rejects_unknown_subject_link(self):
        value = fixture()
        value["units"][0]["subject_ids"] = ["project:unknown"]
        with self.assertRaisesRegex(ValueError, "unknown subject"):
            BUILDER.build(value)

    def test_review_is_clearly_candidate_only(self):
        text = RENDERER.render(BUILDER.build(fixture()))
        self.assertIn("候选证据，不是长期结论", text)
        self.assertIn("- [ ] 完成接口测试。", text)
        self.assertIn("当前状态更新：0", text)


if __name__ == "__main__":
    unittest.main()
