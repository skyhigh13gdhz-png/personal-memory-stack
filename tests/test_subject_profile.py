import importlib.util
import json
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_subject_profile.py"
SPEC = importlib.util.spec_from_file_location("validate_subject_profile", SCRIPT)
PROFILE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PROFILE)


def subject(subject_type="project"):
    return {"subject_id": "x:1", "subject_type": subject_type, "canonical_name": "示例"}


def template(sections):
    return {"subject_types": ["project"], "profile_sections": sections}


class SubjectProfileTests(unittest.TestCase):
    def test_validates_required_paragraph_and_list(self):
        value = {
            "schema_version": "subject-profile-v1", "review_status": "confirmed", "subject_id": "x:1",
            "content": {"summary": "示例项目。", "boundaries": ["不覆盖原始记录。"]},
        }
        result = PROFILE.validate(value, subject(), template([
            {"key": "summary", "title": "这是什么", "kind": "paragraph", "required": True},
            {"key": "boundaries", "title": "范围与边界", "kind": "list", "required": True},
        ]))
        self.assertEqual(result["populated"], 2)

    def test_rejects_missing_required_and_unknown_fields(self):
        value = {
            "schema_version": "subject-profile-v1", "review_status": "draft", "subject_id": "x:1",
            "content": {"extra": "不属于模板"},
        }
        with self.assertRaisesRegex(ValueError, "content.summary is required"):
            PROFILE.validate(value, subject(), template([
                {"key": "summary", "title": "这是什么", "kind": "paragraph", "required": True},
            ]))

    def test_rejects_cross_subject_profile(self):
        value = {"schema_version": "subject-profile-v1", "review_status": "draft", "subject_id": "x:2", "content": {}}
        with self.assertRaisesRegex(ValueError, "must match"):
            PROFILE.validate(value, subject(), template([
                {"key": "summary", "title": "这是什么", "kind": "paragraph", "required": False},
            ]))

    def test_every_configured_type_has_a_satisfiable_profile_contract(self):
        root = Path(__file__).parents[1]
        layout = json.loads((root / "config" / "memory-layout.json").read_text(encoding="utf-8"))
        for template_id, contract in layout["templates"].items():
            subject_type = contract["subject_types"][0]
            content = {}
            for section in contract["profile_sections"]:
                if not section["required"]:
                    continue
                content[section["key"]] = "示例说明。" if section["kind"] == "paragraph" else ["示例条目。"]
            result = PROFILE.validate(
                {"schema_version": "subject-profile-v1", "review_status": "confirmed", "subject_id": "x:1", "content": content},
                subject(subject_type), contract,
            )
            self.assertGreater(result["populated"], 0, template_id)


if __name__ == "__main__":
    unittest.main()
