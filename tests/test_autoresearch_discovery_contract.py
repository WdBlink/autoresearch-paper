import unittest

from tests.skill_contract_helpers import assert_compact_skill


class DiscoveryContractTests(unittest.TestCase):
    def test_discovery_owns_the_research_question_only(self):
        body = assert_compact_skill(self, "autoresearch-discovery")
        for token in (
            "research-brief.md", "Problem", "Prior art", "Gap",
            "Hypothesis", "Falsifier", "Plausible baselines",
            "Evaluation requirements", "no-testable-opportunity",
        ):
            self.assertIn(token, body)
        for forbidden in ("experiment-contract.md", "KEEP/DISCARD", "manuscript-package"):
            self.assertNotIn(forbidden, body)
