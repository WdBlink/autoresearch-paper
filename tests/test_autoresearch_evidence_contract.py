import re
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

    def test_resolved_negative_and_unresolved_conflict_have_distinct_statuses(self):
        body = assert_compact_skill(self, "autoresearch-evidence")
        unsupported = re.search(
            r"- `unsupported` — (.*?)(?=\n- `insufficient-evidence`)",
            body,
            re.DOTALL,
        )
        self.assertIsNotNone(unsupported)
        unsupported_definition = " ".join(unsupported.group(1).split())
        self.assertIn(
            "clear negative or regression evidence that answers the claim",
            unsupported_definition,
        )
        self.assertNotIn("contradict", unsupported_definition)

        stop = body.split("## Stop", 1)[1].split("## Boundaries", 1)[0]
        normalized_stop = " ".join(stop.split())
        self.assertIn(
            "unresolved or internally inconsistent/contradictory required evidence",
            normalized_stop,
        )
        self.assertIn("use `insufficient-evidence`", normalized_stop)
        self.assertIn("return to Experiment", normalized_stop)
