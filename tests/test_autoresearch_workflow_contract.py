import re
import unittest
from pathlib import Path

import yaml

from tests.skill_contract_helpers import assert_compact_skill


SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "autoresearch-workflow"
REFERENCE = SKILL_DIR / "references" / "artifact-handoffs.md"


def route_rows() -> list[tuple[str, str, str, str, str]]:
    text = REFERENCE.read_text()
    if "## Route matrix" not in text:
        raise AssertionError("artifact handoff reference must define a Route matrix")
    section = text.split("## Route matrix", 1)[1].split("## Direct entry", 1)[0]
    rows = []
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        rows.append(tuple(cells))
    return rows


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_emits_only_the_exact_four_field_handoff(self):
        body = assert_compact_skill(self, "autoresearch-workflow")
        yaml_block = re.search(r"```yaml\n(.*?)\n```", body, re.DOTALL)
        self.assertIsNotNone(yaml_block)
        handoff = yaml.safe_load(yaml_block.group(1))
        self.assertEqual(
            list(handoff),
            ["next_skill", "reason", "input_artifact", "resume_artifact"],
        )
        self.assertIn("next_skill: none", body)
        self.assertNotRegex(body, r"(?m)^status:")

    def test_route_matrix_is_ordered_and_complete(self):
        expected = [
            ("required-input-missing", "Referenced required input is absent", "none", "none", "none"),
            ("no-testable-opportunity", "Discovery found no testable opportunity", "none", "research-brief.md", "none"),
            ("evaluator-not-validatable", "Evaluator cannot be validated from the Adapter plan", "none", "autoresearch/evaluator_plan.md", "none"),
            ("no-improvement", "Experiment ended without an accepted candidate", "none", "autoresearch/candidate-package/manifest.json", "none"),
            ("budget-exhausted", "Experiment exhausted its budget without an accepted candidate", "none", "autoresearch/candidate-package/manifest.json", "none"),
            ("contract-reauthorization-needed", "Frozen contract requires changed authority", "none", "autoresearch/experiment-contract.md", "none"),
            ("no-accepted-candidate", "Candidate Package contains no accepted candidate", "none", "autoresearch/candidate-package/manifest.json", "none"),
            ("missing-frozen-evidence", "Paper cannot resolve a manifest-linked frozen asset", "none", "validated-research-package/manifest.json", "none"),
            ("invalid-validated-package", "Validated package contains insufficient-evidence", "none", "validated-research-package/manifest.json", "none"),
            ("research-frame-invalid-confirmation-pending", "Paper frame invalid and confirmation absent", "none", "validated-research-package/manifest.json", "none"),
            ("research-frame-invalid-confirmed-evidence", "Human confirmed Evidence as correction target", "autoresearch-evidence", "autoresearch/candidate-package/manifest.json", "validated-research-package/manifest.json"),
            ("research-frame-invalid-confirmed-experiment", "Human confirmed Experiment as correction target", "autoresearch-experiment", "autoresearch/experiment-contract.md", "autoresearch/candidate-package/manifest.json"),
            ("insufficient-evidence", "Evidence issued a claim-blocking request", "autoresearch-experiment", "autoresearch/evidence-request.md", "autoresearch/candidate-package/manifest.json"),
            ("experiment-evaluator-invalid", "Experiment found evaluator integrity or readiness invalid", "karpathy-autoresearch-adapter", "autoresearch/experiment-contract.md", "autoresearch/experiment-contract.md"),
            ("evaluator-package-ready-for-adapter", "Evaluator Engineering produced a package", "karpathy-autoresearch-adapter", "autoresearch/evaluator-package/manifest.json", "autoresearch/experiment-contract.md"),
            ("evaluator-partial", "Adapter classified evaluator partial", "autoresearch-evaluator-engineering", "autoresearch/evaluator_plan.md", "autoresearch/evaluator-package/manifest.json"),
            ("evaluator-missing", "Adapter classified evaluator missing", "autoresearch-evaluator-engineering", "autoresearch/evaluator_plan.md", "autoresearch/evaluator-package/manifest.json"),
            ("manuscript-package-complete", "Paper completed the manuscript package", "none", "manuscript-package/", "none"),
            ("no-research-brief", "Project has no Research Brief", "autoresearch-discovery", "none", "research-brief.md"),
            ("research-brief-no-experiment-contract", "Research Brief exists and no Experiment Contract exists", "karpathy-autoresearch-adapter", "research-brief.md", "autoresearch/experiment-contract.md"),
            ("experiment-contract-frozen", "Adapter-issued frozen ready contract exists and no Candidate Package exists", "autoresearch-experiment", "autoresearch/experiment-contract.md", "autoresearch/candidate-package/manifest.json"),
            ("accepted-candidate-package", "Candidate Package has an accepted candidate and no Validated Research Package exists", "autoresearch-evidence", "autoresearch/candidate-package/manifest.json", "validated-research-package/manifest.json"),
            ("validated-research-package-claim-bounded", "Valid frozen package has an exact three-status Claim Boundary", "autoresearch-paper", "validated-research-package/manifest.json", "manuscript-package/"),
        ]
        self.assertEqual(route_rows(), expected)

    def test_negative_and_confirmation_states_precede_artifact_fallthrough(self):
        statuses = [row[0] for row in route_rows()]
        first_forward = statuses.index("no-research-brief")
        for status in (
            "no-testable-opportunity",
            "evaluator-not-validatable",
            "no-improvement",
            "budget-exhausted",
            "contract-reauthorization-needed",
            "no-accepted-candidate",
            "missing-frozen-evidence",
            "invalid-validated-package",
            "research-frame-invalid-confirmation-pending",
            "insufficient-evidence",
            "experiment-evaluator-invalid",
            "evaluator-package-ready-for-adapter",
        ):
            self.assertLess(statuses.index(status), first_forward, status)

    def test_reference_defines_exactly_two_scientific_loops(self):
        reference = REFERENCE.read_text()
        loops = reference.split("## Scientific return loops", 1)[1]
        rows = re.findall(r"(?m)^- (.+)$", loops)
        self.assertEqual(
            rows,
            [
                "Evidence `insufficient-evidence` routes to `autoresearch-experiment`.",
                "Human-confirmed Paper `research-frame-invalid` routes to `autoresearch-evidence` or `autoresearch-experiment`.",
            ],
        )
        self.assertNotIn("discovery", loops.casefold())
        self.assertIn("conditional operational detour", reference.casefold())


if __name__ == "__main__":
    unittest.main()
