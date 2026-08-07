import re
import unittest

from tests.skill_contract_helpers import assert_compact_skill


class AdapterContractTests(unittest.TestCase):
    def test_adapter_is_the_only_readiness_classifier_and_never_emits_partial_contract(self):
        body = assert_compact_skill(self, "karpathy-autoresearch-adapter")
        self.assertIn("sole evaluator-readiness classifier", body)
        partial = body.split("For `partial` or `missing`", 1)[1].split("## Stop", 1)[0]
        self.assertIn("Do not create an Experiment Contract", partial)
        self.assertIn("`autoresearch/evaluator_plan.md`", partial)

    def test_ready_requires_all_readiness_evidence(self):
        body = assert_compact_skill(self, "karpathy-autoresearch-adapter")
        classification = body.split("## Evaluator classification", 1)[1].split(
            "## Apply only after authorization", 1
        )[0]
        ready = re.search(r"- `ready`: (.*?)(?=\n- `partial`:)", classification, re.DOTALL)
        self.assertIsNotNone(ready)
        normalized = " ".join(ready.group(1).split())
        for evidence in (
            "fixed inputs and splits",
            "candidate-edit isolation",
            "known-outcome",
            "discrimination",
            "repeatability",
        ):
            self.assertIn(evidence, normalized)
        self.assertIn("A deterministic command alone is insufficient", classification)
        self.assertIn("not external scientific validity", classification)

    def test_ready_contract_links_frozen_brief_and_evaluator(self):
        body = assert_compact_skill(self, "karpathy-autoresearch-adapter")
        ready = body.split("For `ready`", 1)[1].split("For `partial` or `missing`", 1)[0]
        normalized = " ".join(ready.split())
        self.assertIn("`research-brief.md`", normalized)
        self.assertIn("frozen evaluator evidence", normalized)
        self.assertIn("sole compact prior-stage handoff to Experiment", normalized)

    def test_adapter_reclassifies_from_compact_evaluator_manifest(self):
        body = assert_compact_skill(self, "karpathy-autoresearch-adapter")
        self.assertIn("`autoresearch/evaluator-package/manifest.json`", body)
        self.assertIn("open only linked evidence needed", body)


if __name__ == "__main__":
    unittest.main()
