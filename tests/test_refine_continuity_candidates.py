import importlib.util
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("refine", ROOT / "scripts" / "refine_continuity_candidates.py")
REFINE = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(REFINE)


def bundle():
    return {
        "schema_version": "continuity-candidates-v1", "source_sha256": "x",
        "subjects": [{"subject": {
            "subject_id": "project:memory", "subject_type": "project", "canonical_name": "外置记忆",
        }, "candidates": [{
            "candidate_id": "c1", "evidence_unit_id": "u1", "valid_date": "2026-01-01",
            "original_text": "完成接口测试，同时吃了午饭。",
            "evidence": {"document_id": "d1", "start": 0, "end": 15},
        }]}], "metrics": {"candidate_links": 1},
    }


class RefinementTests(unittest.TestCase):
    def test_prompt_requires_one_decision_and_minimal_verbatim_facets(self):
        system = REFINE.messages(bundle()["subjects"][0])[0]["content"]
        self.assertIn("必须且只能给一个 decision", system)
        self.assertIn("最小连续片段", system)

    def test_validation_rejects_omitted_candidates(self):
        response = {"schema_version": "continuity-review-v1", "subject_id": "project:memory", "decisions": []}
        with self.assertRaisesRegex(ValueError, "omitted 1 candidates"):
            REFINE.validate_response(bundle(), "project:memory", response)

    def test_validation_accepts_rejection(self):
        response = {"schema_version": "continuity-review-v1", "subject_id": "project:memory", "decisions": [{
            "candidate_id": "c1", "action": "reject", "reason": "与该项目无关",
        }]}
        reviewed = REFINE.validate_response(bundle(), "project:memory", response)
        self.assertEqual(len(reviewed["rejected"]), 1)

    def test_normalizes_only_known_provider_format_drift(self):
        response = {"decisions": [{
            "candidate_id": "c1", "decision": "reject", "claims": [],
        }]}
        normalized = REFINE.normalize_response(response)
        self.assertEqual(normalized["decisions"][0]["action"], "reject")
        self.assertNotIn("decision", normalized["decisions"][0])
        self.assertNotIn("claims", normalized["decisions"][0])
        self.assertIn("reason", normalized["decisions"][0])

    def test_repairs_quote_only_when_difference_is_markdown_decoration(self):
        entry = bundle()["subjects"][0]
        entry["candidates"][0]["original_text"] = "- **入睡时间**：00:30~08:00"
        response = {"decisions": [{
            "candidate_id": "c1", "decision": "promote", "claims": [{
                "role": "state", "kind": "state", "summary": "睡眠时间",
                "evidence_quote": "入睡时间：00:30~08:00",
            }],
        }]}
        normalized = REFINE.normalize_response(response, entry)
        self.assertEqual(normalized["decisions"][0]["claims"][0]["evidence_quote"], entry["candidates"][0]["original_text"])

    def test_does_not_repair_changed_wording(self):
        entry = bundle()["subjects"][0]
        response = {"decisions": [{
            "candidate_id": "c1", "decision": "promote", "claims": [{
                "role": "progress", "kind": "event", "summary": "接口已稳定",
                "evidence_quote": "接口已稳定",
            }],
        }]}
        normalized = REFINE.normalize_response(response, entry)
        self.assertEqual(normalized["decisions"][0]["claims"][0]["evidence_quote"], "接口已稳定")

    def test_normalizes_market_role_to_context(self):
        entry = bundle()["subjects"][0]
        response = {"decisions": [{
            "candidate_id": "c1", "decision": "promote", "claims": [{
                "role": "market", "kind": "state", "summary": "市场需求待验证",
                "evidence_quote": "完成接口测试",
            }],
        }]}
        normalized = REFINE.normalize_response(response, entry)
        self.assertEqual(normalized["decisions"][0]["claims"][0]["role"], "context")

    def test_normalizes_role_like_kinds_to_stable_claim_primitives(self):
        entry = bundle()["subjects"][0]
        response = {"decisions": [{
            "candidate_id": "c1", "decision": "promote", "claims": [{
                "role": "goal", "kind": "goal", "summary": "建立稳定的外置记忆",
                "evidence_quote": "完成接口测试",
            }],
        }]}
        normalized = REFINE.normalize_response(response, entry)
        claim = normalized["decisions"][0]["claims"][0]
        self.assertEqual(claim["role"], "goal")
        self.assertEqual(claim["kind"], "commitment")

    def test_uniquely_aligns_equivalent_quote_punctuation(self):
        entry = bundle()["subjects"][0]
        entry["candidates"][0]["original_text"] = "系统要解决“未来找得回来”的问题。"
        response = {"decisions": [{
            "candidate_id": "c1", "decision": "promote", "claims": [{
                "role": "problem", "kind": "state", "summary": "未来需要可检索",
                "evidence_quote": '系统要解决"未来找得回来"的问题。',
            }],
        }]}
        normalized = REFINE.normalize_response(response, entry)
        self.assertEqual(
            normalized["decisions"][0]["claims"][0]["evidence_quote"],
            entry["candidates"][0]["original_text"],
        )

    @patch.object(REFINE.CLAIMS, "request_llm")
    def test_large_subject_is_batched_then_reassembled(self, request_llm):
        entry = bundle()["subjects"][0]
        entry["candidates"] = [
            {**entry["candidates"][0], "candidate_id": f"c{index}", "evidence_unit_id": f"u{index}"}
            for index in range(3)
        ]
        request_llm.side_effect = [
            ({"schema_version": "continuity-review-v1", "subject_id": "project:memory", "decisions": [
                {"candidate_id": item["candidate_id"], "decision": "reject", "claims": []}
                for item in partial
            ]}, {"total_tokens": 10})
            for partial in (entry["candidates"][:2], entry["candidates"][2:])
        ]
        response, metrics = REFINE.request_entry(
            entry, base_url="x", api_key="x", model="x", batch_size=2,
        )
        self.assertEqual(len(response["decisions"]), 3)
        self.assertEqual(metrics["batch_count"], 2)
        self.assertEqual(metrics["total_tokens"], 20)


if __name__ == "__main__":
    unittest.main()
