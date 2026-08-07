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
