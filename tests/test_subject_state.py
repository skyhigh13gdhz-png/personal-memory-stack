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


def profile():
    return {
        "schema_version": "subject-profile-v1", "review_status": "confirmed", "subject_id": "project:memory",
        "content": {
            "summary": "一套个人外置记忆系统。",
            "purpose": "帮助保存、检索和整理个人记录。",
            "origin": "为减少跨会话信息丢失而建立。",
            "boundaries": ["原始记录不可由摘要反向覆盖。"],
            "objectives": ["形成稳定的记忆工作流。"],
        },
    }


def template():
    return {
        "subject_types": ["project"],
        "profile_sections": [
            {"key": "summary", "title": "这是什么", "kind": "paragraph", "required": True},
            {"key": "purpose", "title": "用来做什么", "kind": "paragraph", "required": True},
            {"key": "origin", "title": "为什么建立", "kind": "paragraph", "required": True},
            {"key": "boundaries", "title": "范围与边界", "kind": "list", "required": True},
            {"key": "objectives", "title": "目标", "kind": "list", "required": False},
        ],
        "state_sections": [
            {"facet": "phase", "title": "当前阶段"},
            {"facet": "capability", "title": "当前状态"},
            {"facet": "focus", "title": "当前推进"},
            {"facet": "problem", "title": "当前问题"},
            {"facet": "open_question", "title": "待确认事项"},
        ],
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
        text = RENDERER.render(profile(), state(), claims(), template())
        self.assertIn("## 这是什么", text)
        self.assertIn("一套个人外置记忆系统。", text)
        self.assertIn("## 为什么建立", text)
        self.assertLess(text.index("## 这是什么"), text.index("## 当前阶段"))
        self.assertIn("## 当前阶段", text)
        self.assertIn("项目处于集成阶段。", text)
        self.assertNotIn("（派生状态）", text)
        self.assertFalse(text.startswith("---"))
        self.assertIn("> 更新至 2026-01-02", text)
        self.assertIn("## 演进记录", text)
        visible = "\n".join(line for line in text.splitlines() if "<!--" not in line)
        self.assertNotIn("evidence_claim_ids", visible)
        self.assertNotIn("subject_id", visible)

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

    def test_renderer_uses_type_specific_state_sections(self):
        root = Path(__file__).parents[1]
        import json
        layout = json.loads((root / "config" / "memory-layout.json").read_text(encoding="utf-8"))
        cases = {
            "health-track-v1": ("health_track", "当前情况"),
            "pet-v1": ("pet", "当前情况"),
            "strategy-v1": ("strategy", "当前阶段"),
        }
        for template_id, (subject_type, expected_heading) in cases.items():
            contract = layout["templates"][template_id]
            first = contract["state_sections"][0]
            value = state()
            value["subject"]["subject_type"] = subject_type
            value["state_items"] = [{
                **value["state_items"][0], "state_type": "direct_fact", "facet": first["facet"],
                "evidence_claim_ids": ["c1"], "review_policy": "auto_eligible",
            }]
            content = {}
            for section in contract["profile_sections"]:
                if section["required"]:
                    content[section["key"]] = "示例说明。" if section["kind"] == "paragraph" else ["示例条目。"]
            profile_value = {"schema_version": "subject-profile-v1", "review_status": "confirmed", "subject_id": "project:memory", "content": content}
            text = RENDERER.render(profile_value, value, claims(), contract)
            self.assertIn(f"## {expected_heading}", text)


if __name__ == "__main__":
    unittest.main()
