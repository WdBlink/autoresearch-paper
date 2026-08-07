from __future__ import annotations

import re
import unittest

from tests.skill_contract_helpers import SKILLS_ROOT, load_skill


PRODUCTS = {
    "autoresearch-discovery": "research-brief.md",
    "karpathy-autoresearch-adapter": "autoresearch/experiment-contract.md",
    "autoresearch-evaluator-engineering": "autoresearch/evaluator-package/",
    "autoresearch-experiment": "autoresearch/candidate-package/",
    "autoresearch-evidence": "validated-research-package/",
    "autoresearch-paper": "manuscript-package/",
}

REFERENCE_PRODUCTS = {
    "Research Brief": "research-brief.md",
    "Experiment Contract": "autoresearch/experiment-contract.md",
    "Evaluator Package": "autoresearch/evaluator-package/",
    "Candidate Package": "autoresearch/candidate-package/",
    "Validated Research Package": "validated-research-package/",
    "Manuscript Package": "manuscript-package/",
}

ALLOWED_OUTBOUND_SKILL_REFERENCES = {
    "autoresearch-workflow": {
        "autoresearch-discovery",
        "karpathy-autoresearch-adapter",
        "autoresearch-evaluator-engineering",
        "autoresearch-experiment",
        "autoresearch-evidence",
        "autoresearch-paper",
    },
    "autoresearch-discovery": set(),
    "karpathy-autoresearch-adapter": {
        "autoresearch-evaluator-engineering",
        "autoresearch-experiment",
    },
    "autoresearch-evaluator-engineering": {"karpathy-autoresearch-adapter"},
    "autoresearch-experiment": {
        "karpathy-autoresearch-adapter",
        "autoresearch-evidence",
    },
    "autoresearch-evidence": {
        "autoresearch-experiment",
        "autoresearch-paper",
    },
    "autoresearch-paper": {
        "autoresearch-evidence",
        "autoresearch-experiment",
    },
}


def body(name: str) -> str:
    return load_skill(name)[1]


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

    def test_each_owner_uses_its_exact_canonical_product_path(self):
        for skill, product in PRODUCTS.items():
            with self.subTest(skill=skill, product=product):
                self.assertIn(f"`{product}`", body(skill))

    def test_active_contracts_do_not_use_short_product_aliases(self):
        active = "\n".join(
            (SKILLS_ROOT / name / "SKILL.md").read_text()
            for name in sorted(ALLOWED_OUTBOUND_SKILL_REFERENCES)
        )
        for alias in (
            "`experiment-contract.md`",
            "`evaluator-package/`",
            "`candidate-package/`",
        ):
            self.assertNotIn(alias, active)

    def test_all_explicit_outbound_skill_edges_are_enumerated(self):
        all_skill_names = set(ALLOWED_OUTBOUND_SKILL_REFERENCES)
        for owner, expected in ALLOWED_OUTBOUND_SKILL_REFERENCES.items():
            mentioned = {
                target
                for target in all_skill_names - {owner}
                if target in body(owner)
            }
            with self.subTest(owner=owner):
                self.assertEqual(mentioned, expected)

    def test_evaluator_detour_and_integrity_return_only_through_adapter(self):
        adapter = " ".join(body("karpathy-autoresearch-adapter").split())
        evaluator = " ".join(body("autoresearch-evaluator-engineering").split())
        experiment = " ".join(body("autoresearch-experiment").split())

        self.assertIn("For `partial` or `missing`", adapter)
        self.assertIn("`autoresearch-evaluator-engineering`", adapter)
        self.assertIn("return to Adapter", evaluator)
        self.assertIn("return only to Adapter", experiment)
        self.assertNotIn("Evaluator Engineering", experiment)

    def test_evidence_has_one_claim_blocking_route_and_paper_requires_confirmation(self):
        evidence = " ".join(body("autoresearch-evidence").split())
        paper = " ".join(body("autoresearch-paper").split())

        self.assertIn("only `autoresearch-experiment`", evidence)
        self.assertNotIn("autoresearch-discovery", evidence)
        confirmation = paper.index("human confirmation")
        upstream_route = paper.index("routing upstream to `autoresearch-evidence` or `autoresearch-experiment`")
        self.assertLess(confirmation, upstream_route)


if __name__ == "__main__":
    unittest.main()
