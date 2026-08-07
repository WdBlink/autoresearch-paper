import unittest

from tests.skill_contract_helpers import assert_compact_skill


class ExperimentContractTests(unittest.TestCase):
    def test_experiment_owns_the_complete_bounded_search_loop(self):
        body = assert_compact_skill(self, "autoresearch-experiment")
        for token in (
            "Research", "Development", "Review", "Record",
            "candidate-package", "experiment-ledger.jsonl",
            "no-improvement", "budget-exhausted",
            "contract-reauthorization-needed",
        ):
            self.assertIn(token, body)
        self.assertIn("Never modify the frozen evaluator", body)
        self.assertIn("screening", body.lower())
        self.assertIn("cannot authorize adoption", body.lower())
