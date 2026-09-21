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
    def test_merges_multiple_days_losslessly_and_in_date_order(self):
        first = fixture()
        second = fixture()
        second["units"][0] = {
            **second["units"][0], "unit_id": "u3", "date": "2026-01-02",
            "document_id": "d2", "text": "完成第二轮测试。", "summary": "完成第二轮测试",
        }
        second["units"] = [second["units"][0], first["units"][0]]
        merged = BUILDER.merge_classified([second, first])
        self.assertEqual(merged["coverage"]["source_packages"], 2)
        self.assertEqual(merged["coverage"]["units_preserved"], 3)
        self.assertEqual([item["unit_id"] for item in merged["units"]], ["u1", "u2", "u3"])
        bundle = BUILDER.build(merged)
        self.assertEqual(bundle["metrics"]["candidate_links"], 2)

    def test_rejects_conflicting_duplicate_unit(self):
        first = fixture()
        second = fixture()
        second["units"][0]["text"] = "同一个 ID 却是不同内容"
        with self.assertRaisesRegex(ValueError, "conflicting duplicate evidence unit"):
            BUILDER.merge_classified([first, second])

    def test_rejects_conflicting_subject_definition(self):
        first = fixture()
        second = fixture()
        second["subjects"][0]["canonical_name"] = "不同名称"
        with self.assertRaisesRegex(ValueError, "conflicting subject identity"):
            BUILDER.merge_classified([first, second])

    def test_allows_subject_description_to_evolve(self):
        first = fixture()
        second = fixture()
        second["subjects"][0]["promotion_reason"] = "更清晰的后续说明"
        merged = BUILDER.merge_classified([first, second])
        self.assertEqual(merged["subjects"][0]["promotion_reason"], "更清晰的后续说明")

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
