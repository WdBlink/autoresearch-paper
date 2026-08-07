import re
import unittest
from pathlib import Path

from tests.skill_contract_helpers import assert_compact_skill


PAPER_DIR = Path(__file__).resolve().parents[1] / "skills" / "autoresearch-paper"


class PaperContractTests(unittest.TestCase):
    def test_paper_accepts_only_the_validated_manifest_handoff(self):
        body = assert_compact_skill(self, "autoresearch-paper")
        self.assertIn("## Sole handoff modes", body)
        section = body.split("## Sole handoff modes", 1)[1].split("## Inputs", 1)[0]
        rows = re.findall(r"(?m)^\| ([^|]+) \| `([^`]+)` \|$", section)
        self.assertEqual(
            rows,
            [("Validated package", "validated-research-package/manifest.json")],
        )

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

    def test_disclosed_limitation_does_not_become_missing_evidence(self):
        body = assert_compact_skill(self, "autoresearch-paper")
        gate = " ".join(
            body.split("## Asset gate", 1)[1].split(
                "## Autonomous production loop", 1
            )[0].split()
        )
        self.assertIn("already frozen", gate)
        self.assertIn("all referenced assets are present", gate)
        self.assertIn("disclosed limitation", gate)
        self.assertIn("does not emit `missing-frozen-evidence`", gate)

    def test_required_asset_recovery_precedes_terminal_missing_outcome(self):
        body = assert_compact_skill(self, "autoresearch-paper")
        self.assertIn("## Required-asset recovery", body)
        recovery = body.split("## Required-asset recovery", 1)[1].split(
            "## Autonomous production loop", 1
        )[0]
        normalized = " ".join(recovery.split())
        for token in (
            "already-frozen deterministic recovery task",
            "exactly as recorded",
            "If recovery succeeds",
            "continue the asset gate",
            "no authorized recovery exists",
            "recovery fails",
            "remains absent or invalid",
            "`missing-frozen-evidence`",
            "create no Manuscript Package",
        ):
            self.assertIn(token, normalized)
        self.assertLess(
            normalized.index("already-frozen deterministic recovery task"),
            normalized.index("`missing-frozen-evidence`"),
        )

    def test_required_asset_recovery_cannot_change_research_authority(self):
        body = assert_compact_skill(self, "autoresearch-paper")
        self.assertIn("## Required-asset recovery", body)
        recovery = " ".join(
            body.split("## Required-asset recovery", 1)[1].split(
                "## Autonomous production loop", 1
            )[0].split()
        )
        for forbidden in (
            "new seed",
            "new ablation",
            "new experiment",
            "change the Claim Boundary",
        ):
            self.assertIn(forbidden, recovery)

        for reference in (
            "asset-intake.md",
            "review-and-packaging.md",
        ):
            text = (PAPER_DIR / "references" / "paper" / reference).read_text()
            normalized = " ".join(text.split())
            self.assertIn("frozen deterministic recovery", normalized)
            self.assertIn("emit `missing-frozen-evidence`", normalized)
            self.assertLess(
                normalized.index("frozen deterministic recovery"),
                normalized.index("emit `missing-frozen-evidence`"),
                reference,
            )

    def test_missing_evidence_and_completion_are_mutually_exclusive(self):
        body = assert_compact_skill(self, "autoresearch-paper")
        self.assertIn("## Outcome exclusivity", body)
        section = body.split("## Outcome exclusivity", 1)[1].split("## Boundaries", 1)[0]
        rows = re.findall(
            r"(?m)^\| ([^|]+) \| `([^`]+)` \| `([^`]+)` \|$",
            section,
        )
        self.assertEqual(
            rows,
            [
                (
                    "Required frozen asset remains absent or invalid after recovery gate",
                    "missing-frozen-evidence",
                    "forbidden",
                ),
                ("Invalid validated package", "invalid-validated-package", "forbidden"),
                ("Research frame invalid, confirmation pending", "research-frame-invalid-confirmation-pending", "forbidden"),
                ("All release gates clean", "manuscript-package-complete", "required"),
            ],
        )
        packaging = (PAPER_DIR / "references" / "paper" / "review-and-packaging.md").read_text()
        self.assertNotIn("unresolved\n  `missing-frozen-evidence` limitation", packaging)
        self.assertIn("never coexist", packaging)


if __name__ == "__main__":
    unittest.main()
