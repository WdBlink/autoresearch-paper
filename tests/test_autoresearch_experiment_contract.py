import re
import unittest

from tests.skill_contract_helpers import assert_compact_skill


class ExperimentContractTests(unittest.TestCase):
    def test_experiment_has_exactly_two_single_handoff_modes(self):
        body = assert_compact_skill(self, "autoresearch-experiment")
        self.assertIn("## Sole handoff modes", body)
        modes = body.split("## Sole handoff modes", 1)[1].split("## Entry gate", 1)[0]
        rows = re.findall(r"(?m)^\| ([^|]+) \| `([^`]+)` \|$", modes)
        self.assertEqual(
            rows,
            [
                ("New run", "autoresearch/experiment-contract.md"),
                ("Evidence resume", "autoresearch/evidence-request.md"),
            ],
        )

    def test_new_run_requires_adapter_issued_ready_contract(self):
        body = assert_compact_skill(self, "autoresearch-experiment")
        gate = body.split("## Entry gate", 1)[1].split("## Frozen contract", 1)[0]
        normalized = " ".join(gate.split())
        self.assertIn("Adapter-issued", normalized)
        self.assertIn("frozen `autoresearch/experiment-contract.md`", normalized)
        self.assertIn("binds a `ready` evaluator", normalized)
        self.assertNotIn("evaluator package whose", normalized)

    def test_evidence_resume_is_bound_and_cannot_expand_contract_authority(self):
        body = assert_compact_skill(self, "autoresearch-experiment")
        self.assertIn("## Evidence resume", body)
        resume = body.split("## Evidence resume", 1)[1].split("## Frozen contract", 1)[0]
        normalized = " ".join(resume.split())
        for item in (
            "Experiment Contract identity and hash",
            "Candidate Package manifest",
            "evaluator identity",
            "requested missing evidence",
            "permitted scope",
            "provenance",
        ):
            self.assertIn(item, normalized)
        self.assertIn("open the linked frozen contract", normalized)
        self.assertIn("`contract-reauthorization-needed`", normalized)
        self.assertIn("no iteration", normalized)

    def test_all_evaluator_integrity_problems_return_to_adapter(self):
        body = assert_compact_skill(self, "autoresearch-experiment")
        gate = body.split("## Entry gate", 1)[1].split("## Frozen contract", 1)[0]
        stop = body.split("## Stop", 1)[1].split("## Boundaries", 1)[0]
        self.assertIn("return only to Adapter", gate)
        self.assertIn("return to Adapter", stop)
        self.assertNotIn("Evaluator Engineering", body)

    def test_evaluator_invalid_return_preserves_operational_state(self):
        body = assert_compact_skill(self, "autoresearch-experiment")
        self.assertIn("## Evaluator-invalid return", body)
        invalid = body.split("## Evaluator-invalid return", 1)[1].split(
            "## Frozen contract", 1
        )[0]
        normalized = " ".join(invalid.split())
        for item in (
            "`autoresearch/evaluator-invalid-return.md`",
            "Experiment Contract identity and hash",
            "evaluator identity",
            "failure evidence",
            "candidate and ledger state",
            "provenance",
        ):
            self.assertIn(item, normalized)

    def test_candidate_manifest_is_the_compact_evidence_handoff(self):
        body = assert_compact_skill(self, "autoresearch-experiment")
        package = body.split("## Candidate Package", 1)[1].split("## Stop", 1)[0]
        package = " ".join(package.split())
        for item in (
            "`autoresearch/candidate-package/manifest.json`",
            "Experiment Contract",
            "evaluator",
            "accepted candidate",
            "outcome summary",
            "experiment ledger",
            "evidence/log index",
            "sole compact handoff to Evidence",
        ):
            self.assertIn(item, package)


if __name__ == "__main__":
    unittest.main()
