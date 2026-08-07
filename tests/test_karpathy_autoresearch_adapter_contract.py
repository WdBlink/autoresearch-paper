import re
import unittest

from tests.skill_contract_helpers import assert_compact_skill


class AdapterContractTests(unittest.TestCase):
    def test_adapter_has_normal_and_operational_return_handoff_modes(self):
        body = assert_compact_skill(self, "karpathy-autoresearch-adapter")
        self.assertIn("## Sole handoff modes", body)
        section = body.split("## Sole handoff modes", 1)[1].split("## Core contract", 1)[0]
        rows = re.findall(r"(?m)^\| ([^|]+) \| `([^`]+)` \|$", section)
        self.assertEqual(
            rows,
            [
                ("Research brief", "research-brief.md"),
                ("Evaluator package return", "autoresearch/evaluator-package/manifest.json"),
                ("Evaluator-invalid return", "autoresearch/evaluator-invalid-return.md"),
            ],
        )

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

    def test_evaluator_invalid_return_makes_stale_contract_ineligible_before_reclassification(self):
        body = assert_compact_skill(self, "karpathy-autoresearch-adapter")
        self.assertIn("## Evaluator-invalid operational return", body)
        section = body.split("## Evaluator-invalid operational return", 1)[1].split(
            "## Apply only after authorization", 1
        )[0]
        normalized = " ".join(section.split())
        for token in (
            "ineligible for reuse",
            "reclassify",
            "return the replacement plan in chat",
            "explicit apply authorization",
        ):
            self.assertIn(token, normalized)
        stale = normalized.index("ineligible for reuse")
        reclassify = normalized.index("reclassify")
        plan = normalized.index("return the replacement plan in chat")
        authorization = normalized.index("explicit apply authorization")
        self.assertLess(stale, reclassify)
        self.assertLess(reclassify, plan)
        self.assertLess(plan, authorization)
        self.assertIn("partial` or `missing", normalized)
        self.assertIn("`autoresearch/evaluator_plan.md`", normalized)

    def test_evaluator_plan_preserves_brief_requirements_without_loading_brief(self):
        body = assert_compact_skill(self, "karpathy-autoresearch-adapter")
        partial = body.split("For `partial` or `missing`", 1)[1].split(
            "## Stop", 1
        )[0]
        normalized = " ".join(partial.split())
        for item in (
            "Research Brief identity/hash/reference",
            "frozen evaluation requirements",
            "permitted design latitude",
            "necessary project files",
        ):
            self.assertIn(item, normalized)

    def test_adapter_terminal_outcomes_are_operational_not_scientific(self):
        body = assert_compact_skill(self, "karpathy-autoresearch-adapter")
        stop = body.split("## Stop", 1)[1]
        normalized = " ".join(stop.split())
        self.assertIn("`repository-not-runnable`", normalized)
        self.assertIn("setup or required invocation", normalized)
        self.assertIn("`baseline-failed`", normalized)
        self.assertIn("cannot be reproduced reliably enough to freeze", normalized)
        self.assertIn("do not redefine", normalized)


if __name__ == "__main__":
    unittest.main()
