import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RENDERER = load_module("render_memory_subject_pipeline", "render_memory_subject.py")
LAYOUT = load_module("memory_layout_pipeline", "memory_layout.py")


class MemorySubjectPipelineTests(unittest.TestCase):
    def test_profile_state_timeline_register_move_and_rollback(self):
        layout = json.loads((ROOT / "config" / "memory-layout.json").read_text(encoding="utf-8"))
        registry = json.loads((ROOT / "config" / "subjects.json").read_text(encoding="utf-8"))
        subject = next(item for item in registry["subjects"] if item["subject_id"] == "project:personal-memory")
        profile = {
            "schema_version": "subject-profile-v1", "subject_id": subject["subject_id"],
            "content": {
                "summary": "一套个人外置记忆系统。",
                "purpose": "保存、检索并组织个人记录。",
                "origin": "为减少跨会话信息丢失而建立。",
                "boundaries": ["原始记录不可由摘要反向覆盖。"],
            },
        }
        claims = {
            "c1": {"claim_id": "c1", "valid_date": "2026-01-01", "summary": "完成首轮部署。"},
        }
        state = {
            "schema_version": "subject-state-v1", "as_of": "2026-01-01",
            "subject": {"subject_id": subject["subject_id"], "subject_type": "project", "canonical_name": "AI 外置记忆"},
            "state_items": [{
                "state_id": "s1", "state_key": "project.phase", "facet": "phase",
                "statement": "项目完成首轮部署。", "state_type": "direct_fact", "confidence": "high",
                "valid_from": "2026-01-01", "valid_to": None, "lifecycle": "current",
                "evidence_claim_ids": ["c1"], "review_policy": "auto_eligible", "supersedes": [],
            }],
        }
        text = RENDERER.render(profile, state, claims, layout["templates"][subject["template"]])
        self.assertLess(text.index("## 这是什么"), text.index("## 当前阶段"))
        self.assertLess(text.index("## 当前阶段"), text.index("## 演进记录"))

        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            old_rel = LAYOUT.desired_paths(layout, registry)[subject["subject_id"]]
            old = vault / old_rel
            old.parent.mkdir(parents=True)
            old.write_text(text, encoding="utf-8")
            manifest = LAYOUT.register_projection(
                {"schema_version": "memory-layout-manifest-v1", "layout_version": 1, "entries": []},
                vault, subject["subject_id"], old_rel,
            )
            self.assertEqual(manifest["entries"][0]["sha256"], hashlib.sha256(text.encode()).hexdigest())

            moved_layout = json.loads(json.dumps(layout))
            moved_layout["layout_version"] = 2
            moved_layout["collections"]["projects"] = "20-长期记忆/进行中的项目"
            plan = LAYOUT.build_plan(moved_layout, registry, manifest, vault)
            self.assertFalse(plan["errors"])
            self.assertEqual(len(plan["moves"]), 1)
            journal = LAYOUT.apply_plan(plan, vault)
            new = vault / plan["moves"][0]["destination"]
            self.assertTrue(new.is_file())
            LAYOUT.rollback(journal, vault)
            self.assertTrue(old.is_file())
            self.assertEqual(old.read_text(encoding="utf-8"), text)


if __name__ == "__main__":
    unittest.main()
