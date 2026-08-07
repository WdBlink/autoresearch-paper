import re
import unittest

from tests.skill_contract_helpers import assert_compact_skill


class EvidenceContractTests(unittest.TestCase):
    def test_claim_boundary_has_exactly_three_row_statuses(self):
        body = assert_compact_skill(self, "autoresearch-evidence")
        self.assertIn("Use exactly these Claim Boundary row statuses:", body)
        section = body.split("Use exactly these Claim Boundary row statuses:", 1)[1]
        section = section.split("A resolved negative result", 1)[0]
        statuses = re.findall(r"(?m)^- `([^`]+)` —", section)
        self.assertEqual(statuses, ["supported", "qualified", "unsupported"])
        self.assertNotIn("insufficient-evidence", section)

    def test_insufficient_evidence_is_an_upstream_outcome_not_a_validated_package(self):
        body = assert_compact_skill(self, "autoresearch-evidence")
        stop = body.split("## Stop", 1)[1].split("## Boundaries", 1)[0]
        normalized = " ".join(stop.split())
        self.assertIn("do not create or freeze `validated-research-package/`", normalized)
        self.assertIn("`autoresearch/evidence-request.md`", normalized)
        self.assertIn("only `autoresearch-experiment`", normalized)
        self.assertNotIn("appropriate earlier stage", body)

    def test_evidence_request_is_a_bound_resume_manifest(self):
        body = assert_compact_skill(self, "autoresearch-evidence")
        stop = body.split("## Stop", 1)[1].split("## Boundaries", 1)[0]
        normalized = " ".join(stop.split())
        for item in (
            "Experiment Contract identity and hash",
            "Candidate Package manifest",
            "evaluator identity",
            "requested missing evidence",
            "permitted scope",
            "provenance",
        ):
            self.assertIn(item, normalized)
        self.assertIn("compact resume manifest", normalized)

    def test_evidence_enters_through_candidate_manifest_and_opens_claim_needed_files(self):
        body = assert_compact_skill(self, "autoresearch-evidence")
        inputs = body.split("## Inputs", 1)[1].split("## Freeze", 1)[0]
        normalized = " ".join(inputs.split())
        self.assertIn("sole prior-stage handoff", normalized)
        self.assertIn("`autoresearch/candidate-package/manifest.json`", normalized)
        self.assertIn("open only", normalized.casefold())
        self.assertIn("needed", normalized.casefold())

    def test_validated_manifest_is_compact_and_points_to_claim_boundary(self):
        body = assert_compact_skill(self, "autoresearch-evidence")
        self.assertIn("## Validated Research Package", body)
        package = body.split("## Validated Research Package", 1)[1].split("## Stop", 1)[0]
        for item in (
            "claim-boundary.md",
            "frozen candidate",
            "Experiment Contract",
            "evaluator",
            "evidence index",
            "validation summary",
        ):
            self.assertIn(item, package)


if __name__ == "__main__":
    unittest.main()
