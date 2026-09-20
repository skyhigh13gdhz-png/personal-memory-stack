import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "claim_candidate_pipeline.py"
SPEC = importlib.util.spec_from_file_location("claim_candidate_pipeline", SCRIPT)
PIPELINE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PIPELINE)
FIXTURE = Path(__file__).parent / "fixtures" / "golden-v1.json"


def response_for_fixture():
    return {
        "claims": [
            {
                "kind": "event",
                "summary": "开始整理项目需求。",
                "valid_date": "2026-01-01",
                "subject_ids": ["project:memory-system"],
                "evidence": [{
                    "document_id": "synthetic-2026-01-01",
                    "quote": "上午9:00开始整理项目需求。",
                }],
            },
            {
                "kind": "event",
                "summary": "完成导出流程人工验收。",
                "valid_date": "2026-01-02",
                "subject_ids": ["project:memory-system"],
                "evidence": [{
                    "document_id": "synthetic-2026-01-02",
                    "quote": "中午完成导出流程的人工验收。",
                }],
            },
        ]
    }


class ClaimCandidatePipelineTests(unittest.TestCase):
    def setUp(self):
        self.bundle = PIPELINE.load_bundle(FIXTURE)
        self.documents = PIPELINE.resolve_documents(self.bundle, FIXTURE.parent)

    def test_rejects_non_verbatim_quote(self):
        response = response_for_fixture()
        response["claims"][0]["evidence"][0]["quote"] = "并不存在的原文"
        with self.assertRaisesRegex(ValueError, "not a verbatim quote"):
            PIPELINE.validate_model_claims(
                response,
                documents=self.documents,
                subjects=self.bundle["subjects"],
            )

    def test_rejects_unknown_subject(self):
        response = response_for_fixture()
        response["claims"][0]["subject_ids"] = ["project:invented"]
        with self.assertRaisesRegex(ValueError, "unknown subject"):
            PIPELINE.validate_model_claims(
                response,
                documents=self.documents,
                subjects=self.bundle["subjects"],
            )

    def test_high_impact_subject_requires_manual_review(self):
        bundle = json.loads(json.dumps(self.bundle))
        bundle["subjects"][0]["subject_type"] = "health_track"
        candidates = PIPELINE.validate_model_claims(
            response_for_fixture(),
            documents=self.documents,
            subjects=bundle["subjects"],
        )
        self.assertTrue(all(item["policy"] == "manual_review" for item in candidates))

    def test_accept_safe_and_export(self):
        package = PIPELINE.build_package(
            self.bundle,
            self.documents,
            response_for_fixture(),
            model="offline-test",
        )
        self.assertEqual(package["llm_run"]["calls"], 0)
        self.assertTrue(all(item["review_status"] == "pending" for item in package["candidates"]))
        changed = PIPELINE.apply_review(
            package,
            accept=set(),
            reject=set(),
            accept_safe=True,
            note="test",
        )
        self.assertEqual(changed, 2)
        golden = PIPELINE.export_golden(package)
        self.assertEqual(len(golden["claims"]), 2)
        self.assertTrue(all(item["epistemic_status"] == "extracted" for item in golden["claims"]))
        self.assertEqual(PIPELINE.VALIDATOR.validate(golden, base_dir=FIXTURE.parent), [])

    def test_current_cache_requires_source_prompt_and_model_match(self):
        package = PIPELINE.build_package(
            self.bundle,
            self.documents,
            response_for_fixture(),
            model="offline-test",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidates.json"
            PIPELINE.write_json_atomic(path, package)
            self.assertTrue(PIPELINE.existing_is_current(
                path,
                digest=PIPELINE.source_hash(self.documents),
                model="offline-test",
            ))
            self.assertFalse(PIPELINE.existing_is_current(
                path,
                digest=PIPELINE.source_hash(self.documents),
                model="changed-model",
            ))


if __name__ == "__main__":
    unittest.main()
