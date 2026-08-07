import unittest

from tests.skill_contract_helpers import assert_compact_skill


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_is_a_router_not_an_executor(self):
        body = assert_compact_skill(self, "autoresearch-workflow")
        for token in (
            "next_skill", "input_artifact", "resume_artifact",
            "at most one compact handoff", "stop after routing",
            "karpathy-autoresearch-adapter", "autoresearch-evaluator-engineering",
        ):
            self.assertIn(token, body)
        self.assertNotIn("run the experiment", body.lower())
        self.assertNotIn("draft the paper", body.lower())
