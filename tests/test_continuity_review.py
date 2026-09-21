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


REVIEW = load("review_continuity_candidates", "review_continuity_candidates.py")
VIEW = load("render_continuity_view_v1", "render_continuity_view_v1.py")


def bundle():
    return {
        "schema_version": "continuity-candidates-v1",
        "subjects": [{
            "subject": {"subject_id": "project:memory", "subject_type": "project", "canonical_name": "外置记忆"},
            "candidates": [{
                "candidate_id": "c1", "evidence_unit_id": "u1", "valid_date": "2026-01-01",
                "original_text": "完成接口测试，同时吃了午饭。",
                "evidence": {"document_id": "d1", "start": 0, "end": 15},
            }],
        }],
    }


def decisions(quote="完成接口测试"):
    return {
        "schema_version": "continuity-review-v1", "subject_id": "project:memory",
        "decisions": [{
            "candidate_id": "c1", "action": "promote", "role": "progress", "kind": "event",
            "summary": "完成接口测试。", "evidence_quote": quote,
        }],
    }


class ContinuityReviewTests(unittest.TestCase):
    def test_promotes_verbatim_facet_without_state_update(self):
        result = REVIEW.review(bundle(), decisions())
        self.assertTrue(result["quality"]["ready_for_projection"])
        self.assertEqual(result["quality"]["state_updates"], 0)
        self.assertEqual(result["claims"][0]["evidence"][0]["quote"], "完成接口测试")

    def test_rejects_non_verbatim_facet(self):
        with self.assertRaisesRegex(ValueError, "must be verbatim"):
            REVIEW.review(bundle(), decisions("接口已稳定"))

    def test_view_keeps_current_state_unconfirmed(self):
        reviewed = REVIEW.review(bundle(), decisions())
        text = VIEW.render(reviewed)
        self.assertIn("## 当前状态", text)
        self.assertIn("待人工确认", text)
        self.assertIn("## 演进时间线", text)
        self.assertIn("完成接口测试。", text)
        self.assertEqual(text.count("完成接口测试。"), 1)


if __name__ == "__main__":
    unittest.main()
