import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "references" / "scripts" / "stage_report_validator.py"
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("stage_report_validator", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class StageReportValidatorTests(unittest.TestCase):
    def test_conformance_suite_passes_all_cases(self) -> None:
        receipt = MODULE.run_conformance_suite()
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["case_count"], 12)
        self.assertTrue(all(case["passed"] for case in receipt["cases"]))

    def test_inactive_profile_style_report_accepts_empty_context_lists(self) -> None:
        report = {
            "schema_version": 1,
            "stage_report_id": "report_stage_1",
            "stage_cycle_id": "stage_1",
            "worker_identity": {
                "model": "MiniMax-M3", "agent": "worker", "provider": "MiniMax",
            },
            "candidate_sha256": "a" * 64,
            "evidence_refs": [],
            "development_validator_receipts": [{
                "kind": "observation_validation",
                "path": "/plan/stage/observation-validation.json",
                "sha256": "b" * 64,
            }],
            "scientific_summary": "A bounded observation was completed.",
            "findings": [{
                "claim": "The candidate contains the validated observation.",
                "evidence_sha256": "a" * 64,
            }],
            "uncertainties": [],
            "proposed_next_questions": [],
        }
        MODULE.validate_stage_report(
            report,
            stage_cycle_id="stage_1",
            expected_worker_identity={
                "model": "MiniMax-M3",
                "agent": "worker",
                "provider": "MiniMax",
            },
            candidate_sha256="a" * 64,
            authorized_evidence_refs=[],
            expected_validator_receipts=[{
                "kind": "observation_validation",
                "path": "/plan/stage/observation-validation.json",
                "sha256": "b" * 64,
            }],
        )

    def test_runtime_accepts_explicit_inactive_observation_profile(self) -> None:
        runtime_path = MODULE_PATH.parent / "harness-runtime.py"
        runtime_spec = importlib.util.spec_from_file_location(
            "harness_runtime_under_test", runtime_path,
        )
        runtime = importlib.util.module_from_spec(runtime_spec)
        assert runtime_spec.loader is not None
        runtime_spec.loader.exec_module(runtime)
        runtime.staged_validate_evaluation_profile({
            "schema_version": 1,
            "profile_id": "observation_profile_v1",
            "applicable": False,
            "reason": "observation_only_no_logical_gate",
            "private_split_policy_sha256": "1" * 64,
            "holdout_refresh_policy_sha256": "2" * 64,
            "transfer_audit_schedule_sha256": "3" * 64,
            "external_suite_identity_sha256": "4" * 64,
        })


if __name__ == "__main__":
    unittest.main()
