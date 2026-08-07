import unittest

from tests.skill_contract_helpers import assert_compact_skill


class EvidenceContractTests(unittest.TestCase):
    def test_evidence_freezes_a_semantic_claim_boundary(self):
        body = assert_compact_skill(self, "autoresearch-evidence")
        for token in (
            "validated-research-package", "claim-boundary.md",
            "supporting evidence", "applicable scope", "uncertainty",
            "supported", "qualified", "unsupported", "insufficient-evidence",
        ):
            self.assertIn(token, body)
        self.assertIn("Never change the candidate method", body)
        self.assertNotIn("Claim Authority", body)
