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


def workflow_routes() -> list[tuple[str, str, str, str, str]]:
    reference = (
        SKILLS_ROOT
        / "autoresearch-workflow"
        / "references"
        / "artifact-handoffs.md"
    ).read_text()
    self_contained = reference.split("## Route matrix", 1)[1].split(
        "## Direct entry", 1
    )[0]
    return [
        tuple(cell.strip().strip("`") for cell in line.strip("|").split("|"))
        for line in self_contained.splitlines()
        if line.startswith("| `")
    ]


def sole_handoff_artifacts(skill_name: str) -> set[str]:
    skill_body = body(skill_name)
    if "## Sole handoff modes" not in skill_body:
        return set()
    section = skill_body.split("## Sole handoff modes", 1)[1].split("\n## ", 1)[0]
    return {
        match
        for match in re.findall(r"(?m)^\| [^|]+ \| `([^`]+)` \|$", section)
    }


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

    def test_every_nonterminal_route_matches_destination_handoff_contract(self):
        for status, _, destination, input_artifact, _ in workflow_routes():
            if destination == "none":
                continue
            with self.subTest(status=status, destination=destination):
                if destination == "autoresearch-discovery":
                    self.assertEqual(input_artifact, "none")
                    continue
                self.assertIn(
                    input_artifact,
                    sole_handoff_artifacts(destination),
                    f"{status} sends {input_artifact} to {destination}, which does not accept it",
                )

    def test_evaluator_detour_and_integrity_return_only_through_adapter(self):
        adapter = " ".join(body("karpathy-autoresearch-adapter").split())
        evaluator = " ".join(body("autoresearch-evaluator-engineering").split())
        experiment = " ".join(body("autoresearch-experiment").split())

        self.assertIn("For `partial` or `missing`", adapter)
        self.assertIn("`autoresearch-evaluator-engineering`", adapter)
        self.assertIn("return to Adapter", evaluator)
        self.assertIn("return only to Adapter", experiment)
        self.assertNotIn("Evaluator Engineering", experiment)

        routes_by_status = {row[0]: row for row in workflow_routes()}
        self.assertIn("experiment-evaluator-invalid", routes_by_status)
        invalid_route = routes_by_status["experiment-evaluator-invalid"]
        self.assertEqual(invalid_route[3], "autoresearch/evaluator-invalid-return.md")

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
