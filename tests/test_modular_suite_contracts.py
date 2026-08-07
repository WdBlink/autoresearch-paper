from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.skill_contract_helpers import (
    SKILLS_ROOT,
    load_skill,
    local_markdown_links,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "test.sh"
SETUP = ROOT / "skills" / "autoresearch-paper" / "scripts" / "setup.sh"

EXPECTED = {
    "autoresearch-workflow",
    "autoresearch-discovery",
    "karpathy-autoresearch-adapter",
    "autoresearch-evaluator-engineering",
    "autoresearch-experiment",
    "autoresearch-evidence",
    "autoresearch-paper",
}

FORBIDDEN_ACTIVE_REFERENCES = (
    "mvp/",
    "mvp0/",
    "dashboard/",
    "harness-runtime.py",
    "compat/skill.v0.20.md",
)


class ModularSuiteContractTests(unittest.TestCase):
    def test_exactly_seven_top_level_skills_are_discoverable(self):
        discovered = {
            path.parent.name for path in SKILLS_ROOT.glob("*/SKILL.md")
        }
        self.assertEqual(discovered, EXPECTED)

        declared = {load_skill(name)[0].get("name") for name in discovered}
        self.assertEqual(declared, EXPECTED)

    def test_active_skill_links_are_local_existing_and_not_skill_imports(self):
        for name in sorted(EXPECTED):
            skill_dir = SKILLS_ROOT / name
            _, body = load_skill(name)
            with self.subTest(skill=name):
                for target in local_markdown_links(skill_dir, body):
                    self.assertTrue(
                        target.is_relative_to(skill_dir.resolve()),
                        f"{name} link escapes its skill directory: {target}",
                    )
                    self.assertTrue(target.exists(), f"missing local link: {target}")
                    self.assertNotEqual(
                        target.name,
                        "SKILL.md",
                        f"{name} links to another active skill implementation",
                    )

    def test_active_skills_do_not_reference_legacy_runtime(self):
        for name in sorted(EXPECTED):
            text = (SKILLS_ROOT / name / "SKILL.md").read_text().casefold()
            with self.subTest(skill=name):
                for forbidden in FORBIDDEN_ACTIVE_REFERENCES:
                    self.assertNotIn(forbidden, text)

    def test_root_runner_exposes_fail_fast_modular_legacy_and_all_modes(self):
        self.assertTrue(RUNNER.exists(), f"missing root test runner: {RUNNER}")
        self.assertTrue(RUNNER.stat().st_mode & 0o111, "root test runner is not executable")

        text = RUNNER.read_text()
        self.assertIn("set -euo pipefail", text)
        for mode, command in (
            ("modular", "run_modular"),
            ("legacy", "run_legacy"),
            ("all", "run_modular; run_legacy"),
        ):
            with self.subTest(mode=mode):
                self.assertRegex(
                    text,
                    rf"(?m)^\s*{re.escape(mode)}\)\s+{re.escape(command)}\s*;;\s*$",
                )

    def test_legacy_setup_repair_hint_selects_the_compatibility_skill(self):
        text = SETUP.read_text()
        hint = text.split("For GitHub installation:", 1)[1].split("EOF", 1)[0]
        self.assertIn("--skill autoresearch-paper", hint)


if __name__ == "__main__":
    unittest.main()
