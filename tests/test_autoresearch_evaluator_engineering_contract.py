import unittest

from tests.skill_contract_helpers import assert_compact_skill


class EvaluatorEngineeringContractTests(unittest.TestCase):
    def test_only_adapter_plan_and_project_files_cross_the_entry_boundary(self):
        body = assert_compact_skill(self, "autoresearch-evaluator-engineering")
        inputs = body.split("## Inputs", 1)[1].split("## Build and validate", 1)[0]
        normalized = " ".join(inputs.split())
        self.assertIn("`autoresearch/evaluator_plan.md`", normalized)
        self.assertIn("sole prior-stage handoff", normalized)
        self.assertIn("necessary project files", normalized)
        self.assertIn(
            "Do not request or load a Research Brief or any Experiment Contract",
            normalized,
        )
        self.assertIn("frozen evaluation requirements", normalized)
        self.assertIn("permitted design latitude", normalized)
        self.assertIn("Research Brief identity/hash/reference", normalized)

    def test_evaluator_package_exposes_a_compact_manifest_and_returns_adapter(self):
        body = assert_compact_skill(self, "autoresearch-evaluator-engineering")
        package = body.split("## Evaluator Package", 1)[1].split("## Stop", 1)[0]
        package = " ".join(package.split())
        for item in (
            "`autoresearch/evaluator-package/manifest.json`",
            "fixed data/split",
            "known-outcome",
            "discrimination",
            "repeatability",
            "candidate-edit isolation",
            "known limitations",
            "return to Adapter",
        ):
            self.assertIn(item, package)


if __name__ == "__main__":
    unittest.main()
