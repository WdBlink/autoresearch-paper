import unittest

from tests.skill_contract_helpers import assert_compact_skill


class PaperContractTests(unittest.TestCase):
    def test_paper_enters_only_through_compact_validated_manifest(self):
        body = assert_compact_skill(self, "autoresearch-paper")
        inputs = body.split("## Inputs", 1)[1].split("## Asset gate", 1)[0]
        normalized = " ".join(inputs.split())
        self.assertIn("sole prior-stage handoff", normalized)
        self.assertIn("`validated-research-package/manifest.json`", normalized)
        self.assertIn("open only linked", normalized)

    def test_paper_refuses_any_package_with_insufficient_evidence(self):
        body = assert_compact_skill(self, "autoresearch-paper")
        gate = body.split("## Asset gate", 1)[1].split("## Autonomous production loop", 1)[0]
        normalized = " ".join(gate.split())
        self.assertIn("exactly `supported|qualified|unsupported`", normalized)
        self.assertIn("Refuse", gate)
        self.assertIn("`invalid-validated-package`", gate)
        self.assertIn("do not begin manuscript production", normalized)

    def test_paper_remains_autonomous_for_a_valid_frozen_package(self):
        body = assert_compact_skill(self, "autoresearch-paper")
        self.assertIn("Work fully autonomous", body)
        self.assertIn("Proceed without routine outline", body)
        for forbidden in ("new seed", "new ablation", "new experiment"):
            self.assertIn(f"Refuse a {forbidden}" if forbidden == "new seed" else forbidden, body)


if __name__ == "__main__":
    unittest.main()
