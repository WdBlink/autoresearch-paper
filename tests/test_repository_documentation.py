from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryDocumentationTests(unittest.TestCase):
    def test_readme_describes_the_exact_modular_architecture(self):
        text = (ROOT / "README.md").read_text()
        self.assertIn("1 thin router + 5 lifecycle skills + 1 conditional capability", text)
        for name in (
            "autoresearch-workflow", "autoresearch-discovery",
            "karpathy-autoresearch-adapter", "autoresearch-evaluator-engineering",
            "autoresearch-experiment", "autoresearch-evidence", "autoresearch-paper",
        ):
            self.assertIn(name, text)
        self.assertIn("--skill autoresearch-paper", text)
        self.assertIn("--list", text)
        self.assertIn("v0.20 compatibility backend", text)
        self.assertNotIn("one all-in-one skill", text.lower())

    def test_design_spec_routes_evaluator_work_through_adapter(self):
        text = (
            ROOT
            / "docs/superpowers/specs/2026-08-07-modular-autoresearch-skills-design.md"
        ).read_text()
        self.assertIn(
            "| Adapter (`ready`) | `autoresearch/experiment-contract.md` | Experiment |",
            text,
        )
        self.assertIn(
            "| Adapter (`partial` or `missing`) | `autoresearch/evaluator_plan.md` | Evaluator Engineering |",
            text,
        )
        self.assertIn(
            "| Evaluator Engineering | `autoresearch/evaluator-package/` | Adapter for readiness reclassification |",
            text,
        )
        self.assertNotIn(
            "| Evaluator Engineering | `autoresearch/evaluator-package/` | Experiment |",
            text,
        )

    def test_readme_direct_paper_entry_uses_the_manifest(self):
        text = (ROOT / "README.md").read_text()
        example = text.split("Enter directly at Paper", 1)[1].split(
            "## Stage boundaries", 1
        )[0]
        self.assertIn(
            "Use autoresearch-paper with validated-research-package/manifest.json.",
            example,
        )
        self.assertNotIn(
            "Use autoresearch-paper with validated-research-package/.",
            example,
        )

    def test_design_and_changelog_name_bound_operational_manifests(self):
        spec = (
            ROOT
            / "docs/superpowers/specs/2026-08-07-modular-autoresearch-skills-design.md"
        ).read_text()
        changelog = (ROOT / "CHANGELOG.md").read_text()
        for artifact in (
            "`autoresearch/evidence-request.md`",
            "`autoresearch/evaluator-invalid-return.md`",
        ):
            self.assertIn(artifact, spec)
            self.assertIn(artifact, changelog)

    def test_adapter_provenance_is_not_assigned_to_ui_metadata(self):
        spec = (
            ROOT
            / "docs/superpowers/specs/2026-08-07-modular-autoresearch-skills-design.md"
        ).read_text()
        changelog = (ROOT / "CHANGELOG.md").read_text()
        wording = "provenance is recorded in root documentation and Git history"
        self.assertIn(wording, spec)
        self.assertIn(wording, changelog)
        self.assertIn(
            "All seven modular skills carry generated `agents/openai.yaml` UI metadata and no per-skill README.",
            spec,
        )
        self.assertNotIn(
            "provenance recorded in its generated `agents/openai.yaml`",
            spec,
        )
