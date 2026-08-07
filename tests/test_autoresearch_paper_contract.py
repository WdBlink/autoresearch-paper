import unittest

from tests.skill_contract_helpers import assert_compact_skill


class PaperContractTests(unittest.TestCase):
    def test_paper_is_autonomous_inside_frozen_evidence(self):
        body = assert_compact_skill(self, "autoresearch-paper")
        for token in (
            "validated-research-package", "Claim Boundary", "manuscript-package",
            "fully autonomous", "frozen deterministic", "existing data",
            "new seed", "new ablation", "research-frame-invalid",
            "human confirmation",
        ):
            self.assertIn(token, body)
        for forbidden in ("Watchdog", "Claude Code Worker", "MAVIS", "SOTA search"):
            self.assertNotIn(forbidden, body)


if __name__ == "__main__":
    unittest.main()
