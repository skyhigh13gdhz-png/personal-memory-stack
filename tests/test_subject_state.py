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


VALIDATOR = load("validate_subject_state", "validate_subject_state.py")
RENDERER = load("render_memory_subject", "render_memory_subject.py")


def claims():
    return {
        "c1": {"claim_id": "c1", "valid_date": "2026-01-01", "summary": "完成部署。"},
        "c2": {"claim_id": "c2", "valid_date": "2026-01-02", "summary": "开始接口集成。"},
    }


def state():
    return {
        "schema_version": "subject-state-v1", "as_of": "2026-01-02",
        "subject": {"subject_id": "project:memory", "subject_type": "project", "canonical_name": "外置记忆"},
        "state_items": [{
            "state_id": "s1", "state_key": "project.phase", "facet": "phase",
            "statement": "项目处于集成阶段。", "state_type": "derived_state", "confidence": "high",
            "valid_from": "2026-01-02", "valid_to": None, "lifecycle": "current",
            "evidence_claim_ids": ["c1", "c2"], "review_policy": "auto_eligible", "supersedes": [],
        }],
    }


class SubjectStateTests(unittest.TestCase):
    def test_cross_date_project_state_is_auto_eligible(self):
        metrics = VALIDATOR.validate(state(), claims())
        self.assertEqual(metrics["auto_eligible"], 1)
        self.assertEqual(metrics["referenced_claims"], 2)

    def test_derived_state_requires_two_dates(self):
        value = claims()
        value["c2"]["valid_date"] = "2026-01-01"
        with self.assertRaisesRegex(ValueError, "two claims from two dates"):
            VALIDATOR.validate(state(), value)

    def test_high_impact_derived_state_requires_review(self):
        value = state()
        value["subject"]["subject_type"] = "health_track"
        with self.assertRaisesRegex(ValueError, "high-impact"):
            VALIDATOR.validate(value, claims())

    def test_only_one_current_state_per_key(self):
        value = state()
        value["state_items"].append({**value["state_items"][0], "state_id": "s2"})
        with self.assertRaisesRegex(ValueError, "multiple current states"):
            VALIDATOR.validate(value, claims())

    def test_project_view_exposes_derived_state_without_audit_noise(self):
        text = RENDERER.render(state(), claims())
        self.assertIn("## 当前阶段", text)
        self.assertIn("项目处于集成阶段。（派生状态）", text)
        self.assertIn("## 演进记录", text)
        visible = "\n".join(line for line in text.splitlines() if "<!--" not in line)
        self.assertNotIn("evidence_claim_ids", visible)

    def test_supersede_requires_closed_state_with_same_key(self):
        value = state()
        old = {**value["state_items"][0], "state_id": "old", "lifecycle": "superseded", "valid_to": "2026-01-01"}
        value["state_items"][0]["supersedes"] = ["old"]
        value["state_items"].append(old)
        metrics = VALIDATOR.validate(value, claims())
        self.assertEqual(metrics["current_items"], 1)

        value["state_items"][-1]["state_key"] = "different.key"
        with self.assertRaisesRegex(ValueError, "same state_key"):
            VALIDATOR.validate(value, claims())


if __name__ == "__main__":
    unittest.main()
