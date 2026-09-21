import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "memory_layout.py"
SPEC = importlib.util.spec_from_file_location("memory_layout", SCRIPT)
LAYOUT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(LAYOUT)


def layout():
    return {
        "schema_version": "memory-layout-v1", "layout_version": 2,
        "collections": {"projects": "20-长期记忆/项目", "finance": "20-长期记忆/资产与策略"},
        "routing": {"project": "projects", "component": "projects", "account": "finance", "strategy": "finance"},
        "templates": {
            "project-v1": {"subject_types": ["project"], "profile_sections": [{"key": "summary", "title": "这是什么", "kind": "paragraph", "required": True}], "state_sections": [{"facet": "phase", "title": "当前阶段"}]},
            "component-v1": {"subject_types": ["component"], "profile_sections": [{"key": "summary", "title": "这是什么", "kind": "paragraph", "required": True}], "state_sections": [{"facet": "capability", "title": "当前能力"}]},
            "account-v1": {"subject_types": ["account"], "profile_sections": [{"key": "summary", "title": "这是什么", "kind": "paragraph", "required": True}], "state_sections": [{"facet": "capability", "title": "当前状态"}]},
            "strategy-v1": {"subject_types": ["strategy"], "profile_sections": [{"key": "summary", "title": "这是什么", "kind": "paragraph", "required": True}], "state_sections": [{"facet": "phase", "title": "当前阶段"}]},
        },
        "nest_under_parent_types": ["component"],
    }


def registry():
    return {
        "schema_version": "subject-registry-v2",
        "subjects": [{
            "subject_id": "project:memory", "subject_type": "project", "canonical_name": "AI 外置记忆",
            "template": "project-v1", "collection": "projects", "parent_subject_id": None,
        }, {
            "subject_id": "component:gateway", "subject_type": "component", "canonical_name": "Memory Gateway",
            "template": "component-v1", "collection": "projects", "parent_subject_id": "project:memory",
        }, {
            "subject_id": "account:trading", "subject_type": "account", "canonical_name": "交易账户",
            "template": "account-v1", "collection": "finance", "parent_subject_id": None,
        }, {
            "subject_id": "strategy:crypto", "subject_type": "strategy", "canonical_name": "加密交易策略",
            "template": "strategy-v1", "collection": "finance", "parent_subject_id": None,
        }],
    }


class MemoryLayoutTests(unittest.TestCase):
    def test_separates_template_type_collection_and_parent(self):
        paths = LAYOUT.desired_paths(layout(), registry())
        self.assertEqual(paths["account:trading"], "20-长期记忆/资产与策略/交易账户.md")
        self.assertEqual(paths["strategy:crypto"], "20-长期记忆/资产与策略/加密交易策略.md")
        self.assertEqual(paths["component:gateway"], "20-长期记忆/项目/AI 外置记忆/Memory Gateway.md")

    def test_plan_apply_and_rollback_managed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            old = vault / "旧目录" / "AI 外置记忆.md"
            old.parent.mkdir()
            old.write_text("# AI 外置记忆\n", encoding="utf-8")
            digest = hashlib.sha256(old.read_bytes()).hexdigest()
            manifest = {
                "schema_version": "memory-layout-manifest-v1",
                "entries": [{"subject_id": "project:memory", "path": "旧目录/AI 外置记忆.md", "sha256": digest, "managed": True}],
            }
            plan = LAYOUT.build_plan(layout(), registry(), manifest, vault)
            self.assertFalse(plan["errors"])
            self.assertEqual(len(plan["moves"]), 1)
            journal = LAYOUT.apply_plan(plan, vault)
            moved = vault / "20-长期记忆" / "项目" / "AI 外置记忆.md"
            self.assertTrue(moved.exists())
            self.assertFalse(old.exists())
            LAYOUT.rollback(journal, vault)
            self.assertTrue(old.exists())
            self.assertFalse(moved.exists())

    def test_refuses_modified_managed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            source = vault / "old.md"
            source.write_text("changed", encoding="utf-8")
            manifest = {
                "schema_version": "memory-layout-manifest-v1",
                "entries": [{"subject_id": "project:memory", "path": "old.md", "sha256": "wrong", "managed": True}],
            }
            plan = LAYOUT.build_plan(layout(), registry(), manifest, vault)
            self.assertIn("changed outside projector", plan["errors"][0])

    def test_apply_preflight_prevents_partial_move(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            first = vault / "first.md"
            second = vault / "second.md"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            plan = {
                "schema_version": "memory-layout-plan-v1", "vault_root": str(vault.resolve()), "errors": [],
                "moves": [
                    {"subject_id": "a", "source": "first.md", "destination": "new/first.md", "sha256": hashlib.sha256(b"first").hexdigest()},
                    {"subject_id": "b", "source": "second.md", "destination": "blocked.md", "sha256": hashlib.sha256(b"second").hexdigest()},
                ],
            }
            (vault / "blocked.md").write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "destination already exists"):
                LAYOUT.apply_plan(plan, vault)
            self.assertTrue(first.exists())
            self.assertFalse((vault / "new" / "first.md").exists())

    def test_rejects_path_traversal_and_parent_cycle(self):
        bad_layout = layout()
        bad_layout["collections"]["projects"] = "../outside"
        with self.assertRaisesRegex(ValueError, "inside the Vault"):
            LAYOUT.desired_paths(bad_layout, registry())

        bad_registry = registry()
        bad_registry["subjects"][0]["parent_subject_id"] = "component:gateway"
        with self.assertRaisesRegex(ValueError, "parent cycle"):
            LAYOUT.desired_paths(layout(), bad_registry)

    def test_rejects_unknown_or_incompatible_template(self):
        bad_registry = registry()
        bad_registry["subjects"][0]["template"] = "missing-v1"
        with self.assertRaisesRegex(ValueError, "unknown template"):
            LAYOUT.desired_paths(layout(), bad_registry)

        bad_registry = registry()
        bad_registry["subjects"][0]["template"] = "strategy-v1"
        with self.assertRaisesRegex(ValueError, "does not support"):
            LAYOUT.desired_paths(layout(), bad_registry)

    def test_rejects_invalid_profile_section_contract(self):
        bad_layout = layout()
        bad_layout["templates"]["project-v1"]["profile_sections"][0]["kind"] = "table"
        with self.assertRaisesRegex(ValueError, "kind is invalid"):
            LAYOUT.desired_paths(bad_layout, registry())

    def test_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            vault = Path(directory)
            (vault / "escape").symlink_to(Path(outside), target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "resolves outside"):
                LAYOUT.vault_path(vault, "escape/file.md", "test.path")

    def test_register_projection_adds_and_refreshes_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            projected = vault / "20-长期记忆" / "项目" / "AI 外置记忆.md"
            projected.parent.mkdir(parents=True)
            projected.write_text("# v1\n", encoding="utf-8")
            manifest = {"schema_version": "memory-layout-manifest-v1", "layout_version": 1, "entries": []}
            first = LAYOUT.register_projection(
                manifest, vault, "project:memory", "20-长期记忆/项目/AI 外置记忆.md"
            )
            self.assertEqual(len(first["entries"]), 1)
            self.assertEqual(first["entries"][0]["sha256"], hashlib.sha256(b"# v1\n").hexdigest())

            projected.write_text("# v2\n", encoding="utf-8")
            second = LAYOUT.register_projection(
                first, vault, "project:memory", "20-长期记忆/项目/AI 外置记忆.md"
            )
            self.assertEqual(len(second["entries"]), 1)
            self.assertEqual(second["entries"][0]["sha256"], hashlib.sha256(b"# v2\n").hexdigest())

    def test_register_projection_refuses_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = {"schema_version": "memory-layout-manifest-v1", "entries": []}
            with self.assertRaisesRegex(ValueError, "projected file missing"):
                LAYOUT.register_projection(manifest, Path(directory), "project:memory", "missing.md")


if __name__ == "__main__":
    unittest.main()
