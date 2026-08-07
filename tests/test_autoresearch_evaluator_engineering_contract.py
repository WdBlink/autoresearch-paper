import unittest

from tests.skill_contract_helpers import assert_compact_skill


class EvaluatorEngineeringContractTests(unittest.TestCase):
    def test_evaluator_is_conditional_isolated_and_returns_to_adapter(self):
        body = assert_compact_skill(self, "autoresearch-evaluator-engineering")
        for token in (
            "partial", "missing", "evaluator-package", "discriminative",
            "repeatable", "isolated", "known limitations",
            "evaluator-not-validatable", "return to Adapter",
        ):
            self.assertIn(token, body)
        self.assertIn("Never optimize the candidate", body)
