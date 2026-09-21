import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("render_subject_registry", ROOT / "scripts" / "render_subject_registry.py")
RENDERER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RENDERER)


class SubjectRegistryReviewTests(unittest.TestCase):
    def test_real_registry_renders_dimensions_and_conservative_candidates(self):
        layout = json.loads((ROOT / "config" / "memory-layout.json").read_text(encoding="utf-8"))
        subjects = json.loads((ROOT / "config" / "subjects.json").read_text(encoding="utf-8"))
        text = RENDERER.render(layout, subjects)
        self.assertIn("# 长期记忆对象登记表", text)
        self.assertIn("#### AI 外置记忆", text)
        self.assertIn("#### 小红书店铺", text)
        self.assertIn("#### 睡眠与精力", text)
        self.assertIn("#### 加密交易节奏", text)
        self.assertIn("Memory Gateway、Hindsight", text)
        self.assertIn("不创建空壳页面", text)
        self.assertFalse(text.startswith("---"))
        visible = "\n".join(line for line in text.splitlines() if "<!--" not in line)
        self.assertNotIn("subject_id", visible)
        self.assertNotIn("project-v1", visible)
        self.assertNotIn("subject-registry-review-v1", visible)
        self.assertIn("- 分类：项目", visible)
        self.assertIn("低频使用的系统治理页", visible)
        self.assertIn("模板通常由分类自动选择", visible)
        self.assertNotIn("parent_subject_id", visible)


if __name__ == "__main__":
    unittest.main()
