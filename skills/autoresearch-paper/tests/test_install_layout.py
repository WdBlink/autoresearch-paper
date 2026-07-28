#!/usr/bin/env python3
"""Ensure the copied Claude Code skill validates without repository parents."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstalledLayoutContracts(unittest.TestCase):
    def test_contract_validator_supports_standalone_skill_copy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            installed = Path(td) / ".agents" / "skills" / "autoresearch-paper"
            shutil.copytree(ROOT, installed, ignore=shutil.ignore_patterns("node_modules"))
            repository_readme = installed.parents[2] / "README.md"
            self.assertFalse(repository_readme.exists())
            proc = subprocess.run(
                [sys.executable, str(installed / "tests" / "validate_contracts.py")],
                cwd=installed,
                text=True,
                capture_output=True,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"stdout={proc.stdout}\nstderr={proc.stderr}",
            )
            self.assertIn("contracts ok", proc.stdout)

    def test_compiled_dashboard_runs_from_standalone_copy_without_node(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            installed = Path(td) / ".agents" / "skills" / "autoresearch-paper"
            shutil.copytree(ROOT, installed, ignore=shutil.ignore_patterns("node_modules"))
            env = dict(os.environ)
            env["PATH"] = "/usr/bin:/bin"
            proc = subprocess.run(
                [sys.executable, str(installed / "tests" / "test_dashboard_server.py")],
                cwd=installed,
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"stdout={proc.stdout}\nstderr={proc.stderr}",
            )


if __name__ == "__main__":
    unittest.main()
