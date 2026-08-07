import unittest

from tests.skill_contract_helpers import assert_compact_skill


class ExperimentContractTests(unittest.TestCase):
    def test_experiment_accepts_only_adapter_issued_ready_contract(self):
        body = assert_compact_skill(self, "autoresearch-experiment")
        gate = body.split("## Entry gate", 1)[1].split("## Frozen contract", 1)[0]
        normalized = " ".join(gate.split())
        self.assertIn("sole compact prior-stage handoff", normalized)
        self.assertIn("Adapter-issued", normalized)
        self.assertIn("frozen `autoresearch/experiment-contract.md`", normalized)
        self.assertIn("binds a `ready` evaluator", normalized)
        self.assertNotIn("evaluator package whose", normalized)

    def test_all_evaluator_integrity_problems_return_to_adapter(self):
        body = assert_compact_skill(self, "autoresearch-experiment")
        gate = body.split("## Entry gate", 1)[1].split("## Frozen contract", 1)[0]
        stop = body.split("## Stop", 1)[1].split("## Boundaries", 1)[0]
        self.assertIn("return only to Adapter", gate)
        self.assertIn("return to Adapter", stop)
        self.assertNotIn("Evaluator Engineering", body)

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
