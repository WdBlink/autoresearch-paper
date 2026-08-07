import re
import unittest
from pathlib import Path

import yaml

from tests.skill_contract_helpers import assert_compact_skill


SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "autoresearch-workflow"


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_is_a_router_not_an_executor(self):
        body = assert_compact_skill(self, "autoresearch-workflow")
        for token in (
            "next_skill", "input_artifact", "resume_artifact",
            "at most one compact handoff", "stop after routing",
            "karpathy-autoresearch-adapter", "autoresearch-evaluator-engineering",
        ):
            self.assertIn(token, body)
        self.assertNotIn("run the experiment", body.lower())
        self.assertNotIn("draft the paper", body.lower())

    def test_status_return_routes_precede_forward_progress(self):
        body = assert_compact_skill(self, "autoresearch-workflow")
        self.assertIn(
            "Evaluate status return routes before every forward-progress route.",
            body,
        )
        self.assertIn(
            "Evidence says `insufficient-evidence`",
            body,
        )
        self.assertIn(
            "Paper says `research-frame-invalid`",
            body,
        )

    def test_reference_defines_the_exact_two_scientific_return_loops(self):
        reference = (SKILL_DIR / "references" / "artifact-handoffs.md").read_text()
        loops = reference.split("## Scientific return loops", 1)[1]
        self.assertIn(
            "Evidence `insufficient-evidence` routes to `autoresearch-experiment`.",
            loops,
        )
        self.assertIn(
            "Paper `research-frame-invalid` waits for human confirmation, then routes to Evidence or Experiment.",
            loops,
        )
        self.assertNotIn("Evaluator `partial` or `missing` routes", loops)
        self.assertIn("conditional capability detour", reference.lower())

    def test_reason_carries_status_without_a_fifth_field(self):
        body = assert_compact_skill(self, "autoresearch-workflow")
        reference = (SKILL_DIR / "references" / "artifact-handoffs.md").read_text()
        self.assertIn("reason: status=", body)
        self.assertIn("reason: status=", reference)
        self.assertNotRegex(body, r"(?m)^status:")
        self.assertNotRegex(reference, r"(?m)^status:")

        yaml_block = re.search(r"```yaml\n(.*?)\n```", body, re.DOTALL)
        self.assertIsNotNone(yaml_block)
        handoff = yaml.safe_load(yaml_block.group(1))
        self.assertEqual(
            set(handoff),
            {"next_skill", "reason", "input_artifact", "resume_artifact"},
        )
