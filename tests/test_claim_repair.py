import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "repair_claim_candidates.py"
SPEC = importlib.util.spec_from_file_location("repair_claim_candidates", SCRIPT)
REPAIR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(REPAIR)


class ClaimRepairTests(unittest.TestCase):
    def test_merges_unique_repair_and_preserves_pending(self):
        original = {
            "subjects": [],
            "candidates": [{"candidate_id": "cand-a", "review_status": "pending"}],
            "rejected_candidates": [{"source_index": 0, "raw_claim": {"summary": "bad"}}],
        }
        repaired = {
            "candidates": [
                {"candidate_id": "cand-a", "review_status": "pending"},
                {"candidate_id": "cand-b", "review_status": "pending"},
            ],
            "rejected_candidates": [],
        }
        merged = REPAIR.merge_repair(
            original,
            repaired,
            llm_run={"mode": "live-repair", "calls": 1, "total_tokens": 100},
        )
        self.assertEqual([item["candidate_id"] for item in merged["candidates"]], ["cand-a", "cand-b"])
        self.assertEqual(merged["rejected_candidates"], [])
        self.assertEqual(merged["repair_history"][0]["added_candidate_ids"], ["cand-b"])

    def test_repair_prompt_demands_atomic_verbatim_claims(self):
        package = {
            "subjects": [],
            "rejected_candidates": [{
                "raw_claim": {
                    "summary": "merged",
                    "evidence": [{"document_id": "doc", "quote": "changed"}],
                },
            }],
        }
        documents = [{"document_id": "doc", "date": "2026-01-01", "original_text": "source"}]
        system = REPAIR.repair_messages(package, documents)[0]["content"]
        self.assertIn("原子 Claim", system)
        self.assertIn("禁止删词、改词或改标点", system)


if __name__ == "__main__":
    unittest.main()
