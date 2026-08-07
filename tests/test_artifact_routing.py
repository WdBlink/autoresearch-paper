from __future__ import annotations

import re
import unittest

from tests.skill_contract_helpers import SKILLS_ROOT, load_skill


PRODUCTS = {
    "autoresearch-discovery": "research-brief.md",
    "karpathy-autoresearch-adapter": "experiment-contract.md",
    "autoresearch-evaluator-engineering": "evaluator-package",
    "autoresearch-experiment": "candidate-package",
    "autoresearch-evidence": "validated-research-package",
    "autoresearch-paper": "manuscript-package",
}

CHAIN_INPUTS = {
    "karpathy-autoresearch-adapter": "research-brief.md",
    "autoresearch-experiment": "experiment-contract.md",
    "autoresearch-evidence": "candidate-package",
    "autoresearch-paper": "validated-research-package",
}

REFERENCE_PRODUCTS = {
    "Research Brief": "research-brief.md",
    "Experiment Contract": "experiment-contract.md",
    "Evaluator Package": "evaluator-package/",
    "Candidate Package": "candidate-package/",
    "Validated Research Package": "validated-research-package/",
    "Manuscript Package": "manuscript-package/",
}


def normalized_skill(name: str) -> str:
    return " ".join(load_skill(name)[1].split())


class ArtifactRoutingTests(unittest.TestCase):
    def test_workflow_reference_names_exact_canonical_product_chain(self):
        reference = (
            SKILLS_ROOT
            / "autoresearch-workflow"
            / "references"
            / "artifact-handoffs.md"
        ).read_text()
        primary_products = reference.split("## Primary products", 1)[1].split(
            "## Compact handoff", 1
        )[0]
        rows = re.findall(r"(?m)^\d+\. ([^—]+) — `([^`]+)`$", primary_products)

        self.assertEqual(rows, list(REFERENCE_PRODUCTS.items()))

    def test_each_lifecycle_owner_names_its_canonical_product(self):
        for skill, product in PRODUCTS.items():
            with self.subTest(skill=skill, product=product):
                self.assertIn(product, normalized_skill(skill).casefold())

    def test_forward_product_chain_consumes_the_previous_product(self):
        for skill, input_product in CHAIN_INPUTS.items():
            with self.subTest(skill=skill, input_product=input_product):
                self.assertIn(input_product, normalized_skill(skill).casefold())

        evidence = normalized_skill("autoresearch-evidence").casefold()
        self.assertIn("experiment contract", evidence)

    def test_evaluator_detour_returns_to_adapter_for_reclassification(self):
        adapter = normalized_skill("karpathy-autoresearch-adapter")
        evaluator = normalized_skill("autoresearch-evaluator-engineering")
        workflow = normalized_skill("autoresearch-workflow")

        self.assertRegex(adapter, r"partial.*missing.*return to Adapter.*reclassif")
        self.assertRegex(evaluator, r"partial.*missing.*return to Adapter")
        self.assertRegex(
            workflow,
            r"Evaluator `partial` or `missing`.*evaluator-engineering`, then Adapter reclassification",
        )

    def test_exact_two_scientific_return_loops_exclude_discovery(self):
        reference = (
            SKILLS_ROOT
            / "autoresearch-workflow"
            / "references"
            / "artifact-handoffs.md"
        ).read_text()
        loops = reference.split("## Scientific return loops", 1)[1]
        loop_rows = re.findall(r"(?m)^- (.+)$", loops)

        self.assertEqual(
            loop_rows,
            [
                "Evidence `insufficient-evidence` routes to `autoresearch-experiment`.",
                "Paper `research-frame-invalid` waits for human confirmation, then routes to Evidence or Experiment.",
            ],
        )
        self.assertNotIn("discovery", loops.casefold())

        detour = reference.split("## Conditional capability detour", 1)[1].split(
            "## Scientific return loops", 1
        )[0]
        self.assertIn("partial", detour)
        self.assertIn("missing", detour)
        self.assertIn("then Adapter reclassification", detour)

    def test_evidence_returns_only_insufficient_evidence_to_experiment(self):
        evidence = normalized_skill("autoresearch-evidence")
        stop = evidence.split("## Stop", 1)[1].split("## Boundaries", 1)[0]

        self.assertRegex(stop, r"insufficient-evidence.*return to Experiment")
        self.assertIn("Do not automatically route to Discovery", stop)

    def test_paper_never_routes_to_experiment_without_human_confirmation(self):
        paper = normalized_skill("autoresearch-paper")
        stop = paper.split("## Stop", 1)[1].split("## Boundaries", 1)[0]
        workflow = normalized_skill("autoresearch-workflow")

        confirmation = stop.index("human confirmation")
        upstream_route = stop.index("routing upstream to Evidence or Experiment")
        self.assertLess(confirmation, upstream_route)
        self.assertNotRegex(stop, r"automatically route.*Experiment")
        self.assertIn(
            "wait for human confirmation, then Evidence or Experiment",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
