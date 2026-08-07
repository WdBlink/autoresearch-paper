import unittest

from tests.skill_contract_helpers import assert_compact_skill


class AdapterContractTests(unittest.TestCase):
    def test_adapter_maps_brief_to_repository_execution_contract(self):
        body = assert_compact_skill(self, "karpathy-autoresearch-adapter")
        for token in (
            "research-brief.md", "adaptation-plan.md", "experiment-contract.md",
            "ready", "partial", "missing", "explicit apply authorization",
            "return to Adapter", "fresh-agent",
        ):
            self.assertIn(token, body)
        for forbidden in ("redefine the gap", "run the research loop", "write the paper"):
            self.assertIn(forbidden, body)
