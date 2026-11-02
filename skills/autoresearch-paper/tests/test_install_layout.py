#!/usr/bin/env python3
"""Ensure the copied Claude Code skill validates without repository parents."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class InstalledLayoutContracts(unittest.TestCase):
    def run_mvp0_installer(self, install_root: Path) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["AUTORESEARCH_SKILLS_HOME"] = str(install_root)
        return subprocess.run(
            ["bash", str(ROOT / "scripts" / "install-mvp0.sh")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    @staticmethod
    def mvp0_targets(install_root: Path) -> tuple[Path, Path, Path]:
        name = "autoresearch-paper-mvp0"
        shared = install_root / ".agents" / "skills" / name
        codex = install_root / ".codex" / "skills" / name
        claude = install_root / ".claude" / "skills" / name
        return shared, codex, claude

    def run_validator(self, installed: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(installed / "tests" / "validate_contracts.py")],
            cwd=installed,
            text=True,
            capture_output=True,
            check=False,
        )

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

    def test_explicit_mvp0_installer_materializes_only_the_installed_manifest(self) -> None:
        self.assertFalse((ROOT / "mvp0" / "SKILL.md").exists())
        compatibility_source = ROOT / "mvp0" / "SKILL.compat.md"
        self.assertTrue(compatibility_source.is_file())

        with tempfile.TemporaryDirectory() as td:
            install_root = Path(td) / "skill-home"
            completed = self.run_mvp0_installer(install_root)

            self.assertEqual(
                completed.returncode,
                0,
                f"stdout={completed.stdout}\nstderr={completed.stderr}",
            )
            installed, codex, claude = self.mvp0_targets(install_root)
            self.assertEqual(
                (installed / "SKILL.md").read_text(),
                compatibility_source.read_text(),
            )
            manifest_text = (installed / "SKILL.md").read_text()
            frontmatter = manifest_text.split("---", 2)[1]
            metadata = yaml.safe_load(frontmatter)
            self.assertEqual(metadata["name"], "autoresearch-paper-mvp0")
            self.assertIn("P1–P6 loop: compile", metadata["description"])
            self.assertEqual(
                (installed / ".autoresearch-paper-mvp0-installer").read_text(),
                "autoresearch-paper-mvp0 installer-owned v1\n",
            )
            self.assertTrue(
                (
                    installed
                    / "examples/mvp0/fixed-wing-visual-guidance/source-brief.md"
                ).is_file()
            )
            self.assertFalse(
                (installed / "examples/fixed-wing-visual-guidance").exists()
            )
            for relative in (
                "mvp/README.md",
                "mvp/worker_adapter.py",
                "mvp/experiment_ledger.py",
                "mvp/evidence_gate.py",
                "mvp/recompile_loop.py",
                "mvp/supervisory_controller.py",
                "mvp/runtime_assurance.py",
                "mvp/prompts/codex-research-compiler.md",
                "mvp/prompts/codex-recompile-analyst.md",
                "mvp/prompts/codex-supervisor-heartbeat.md",
                "mvp/schemas/research-ir.schema.json",
                "examples/mvp0/fixed-wing-visual-guidance/source-brief.md",
            ):
                with self.subTest(installed_reference=relative):
                    self.assertTrue((installed / relative).is_file(), relative)
            self.assertEqual(codex.resolve(), installed.resolve())
            self.assertEqual(claude.resolve(), installed.resolve())

    def test_mvp0_installer_rejects_unowned_shared_directory_without_mutation(self) -> None:
        for marker_value in (None, "owner-managed directory\n"):
            with self.subTest(marker=marker_value):
                with tempfile.TemporaryDirectory() as td:
                    install_root = Path(td) / "skill-home"
                    shared, codex, claude = self.mvp0_targets(install_root)
                    shared.mkdir(parents=True)
                    manifest = shared / "SKILL.md"
                    sentinel = shared / "mvp" / "keep.txt"
                    sentinel.parent.mkdir()
                    manifest.write_text("owner manifest\n")
                    sentinel.write_text("owner content\n")
                    if marker_value is not None:
                        (shared / ".autoresearch-paper-mvp0-installer").write_text(
                            marker_value
                        )
                    before = {
                        path.relative_to(shared).as_posix(): path.read_bytes()
                        for path in shared.rglob("*")
                        if path.is_file()
                    }

                    completed = self.run_mvp0_installer(install_root)

                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("refusing", completed.stderr)
                    after = {
                        path.relative_to(shared).as_posix(): path.read_bytes()
                        for path in shared.rglob("*")
                        if path.is_file()
                    }
                    self.assertEqual(after, before)
                    self.assertFalse(codex.exists() or codex.is_symlink())
                    self.assertFalse(claude.exists() or claude.is_symlink())

    def test_mvp0_installer_rejects_existing_frontend_directories_without_mutation(self) -> None:
        for frontend_index in (1, 2):
            with self.subTest(frontend=("codex", "claude")[frontend_index - 1]):
                with tempfile.TemporaryDirectory() as td:
                    install_root = Path(td) / "skill-home"
                    shared, codex, claude = self.mvp0_targets(install_root)
                    targets = (shared, codex, claude)
                    shared.mkdir(parents=True)
                    previous_manifest = shared / "SKILL.md"
                    previous_manifest.write_text("previous install\n")
                    conflict = targets[frontend_index]
                    conflict.mkdir(parents=True)
                    marker = conflict / "keep.txt"
                    marker.write_text("owner content\n")

                    completed = self.run_mvp0_installer(install_root)

                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("refusing", completed.stderr)
                    self.assertEqual(marker.read_text(), "owner content\n")
                    self.assertEqual(
                        sorted(path.name for path in conflict.iterdir()),
                        ["keep.txt"],
                    )
                    self.assertEqual(previous_manifest.read_text(), "previous install\n")
                    other = claude if conflict == codex else codex
                    self.assertFalse(other.exists() or other.is_symlink())

    def test_mvp0_installer_rejects_unexpected_frontend_symlinks_without_mutation(self) -> None:
        for frontend_index in (1, 2):
            with self.subTest(frontend=("codex", "claude")[frontend_index - 1]):
                with tempfile.TemporaryDirectory() as td:
                    install_root = Path(td) / "skill-home"
                    shared, codex, claude = self.mvp0_targets(install_root)
                    targets = (shared, codex, claude)
                    shared.mkdir(parents=True)
                    previous_manifest = shared / "SKILL.md"
                    previous_manifest.write_text("previous install\n")
                    conflict = targets[frontend_index]
                    unexpected = install_root / "owner-managed-skill"
                    unexpected.mkdir(parents=True)
                    (unexpected / "keep.txt").write_text("owner content\n")
                    conflict.parent.mkdir(parents=True)
                    conflict.symlink_to(unexpected, target_is_directory=True)
                    original_link = os.readlink(conflict)

                    completed = self.run_mvp0_installer(install_root)

                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("refusing", completed.stderr)
                    self.assertTrue(conflict.is_symlink())
                    self.assertEqual(os.readlink(conflict), original_link)
                    self.assertEqual((unexpected / "keep.txt").read_text(), "owner content\n")
                    self.assertEqual(previous_manifest.read_text(), "previous install\n")
                    other = claude if conflict == codex else codex
                    self.assertFalse(other.exists() or other.is_symlink())

    def test_mvp0_installer_is_idempotent_for_its_own_layout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            install_root = Path(td) / "skill-home"
            shared, codex, claude = self.mvp0_targets(install_root)

            first = self.run_mvp0_installer(install_root)
            first_files = {
                path.relative_to(shared).as_posix(): path.read_bytes()
                for path in shared.rglob("*")
                if path.is_file()
            }
            first_links = (os.readlink(codex), os.readlink(claude))
            second = self.run_mvp0_installer(install_root)
            second_files = {
                path.relative_to(shared).as_posix(): path.read_bytes()
                for path in shared.rglob("*")
                if path.is_file()
            }

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(first_files, second_files)
            self.assertEqual((os.readlink(codex), os.readlink(claude)), first_links)
            self.assertEqual(first_links, (str(shared), str(shared)))
            self.assertFalse((codex / shared.name).exists())
            self.assertFalse((claude / shared.name).exists())

    def test_mvp0_installer_rejects_nested_symlinks_without_external_mutation(self) -> None:
        for relative, directory_target in (
            (Path("agents"), True),
            (Path("agents/openai.yaml"), False),
            (Path("mvp"), True),
            (Path("examples"), True),
        ):
            with self.subTest(relative=relative.as_posix()):
                with tempfile.TemporaryDirectory() as td:
                    install_root = Path(td) / "skill-home"
                    shared, _codex, _claude = self.mvp0_targets(install_root)
                    first = self.run_mvp0_installer(install_root)
                    self.assertEqual(first.returncode, 0, first.stderr)

                    external = Path(td) / "owner-managed-external"
                    if directory_target:
                        external.mkdir()
                        sentinel = external / "keep.txt"
                        sentinel.write_text("owner content\n")
                    else:
                        external.write_text("owner content\n")
                        sentinel = external
                    nested = shared / relative
                    if nested.is_dir():
                        shutil.rmtree(nested)
                    else:
                        nested.unlink()
                    nested.parent.mkdir(parents=True, exist_ok=True)
                    nested.symlink_to(external, target_is_directory=directory_target)
                    external_before = (
                        {
                            path.relative_to(external).as_posix(): path.read_bytes()
                            for path in external.rglob("*")
                            if path.is_file()
                        }
                        if directory_target
                        else external.read_bytes()
                    )

                    completed = self.run_mvp0_installer(install_root)

                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("refusing", completed.stderr)
                    self.assertIn("symlink", completed.stderr)
                    self.assertTrue(nested.is_symlink())
                    external_after = (
                        {
                            path.relative_to(external).as_posix(): path.read_bytes()
                            for path in external.rglob("*")
                            if path.is_file()
                        }
                        if directory_target
                        else external.read_bytes()
                    )
                    self.assertEqual(external_after, external_before)
                    self.assertEqual(sentinel.read_text(), "owner content\n")

    def test_mvp0_installer_rejects_nested_hardlinks_without_external_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            install_root = Path(td) / "skill-home"
            shared, _codex, _claude = self.mvp0_targets(install_root)
            first = self.run_mvp0_installer(install_root)
            self.assertEqual(first.returncode, 0, first.stderr)

            external = Path(td) / "owner-managed-file"
            external.write_text("owner content\n")
            nested = shared / "agents/openai.yaml"
            nested.unlink()
            os.link(external, nested)
            external_before = external.read_bytes()

            completed = self.run_mvp0_installer(install_root)

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("refusing", completed.stderr)
            self.assertIn("multi-link", completed.stderr)
            self.assertEqual(external.read_bytes(), external_before)
            self.assertEqual(nested.read_bytes(), external_before)

    def test_unrelated_agent_container_readme_is_not_repository_readme(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            agent_root = Path(td) / ".agents"
            installed = agent_root / "skills" / "autoresearch-paper"
            shutil.copytree(ROOT, installed, ignore=shutil.ignore_patterns("node_modules"))
            (agent_root / "README.md").write_text("Agent container documentation\n")

            completed = self.run_validator(installed)

            self.assertEqual(
                completed.returncode,
                0,
                f"stdout={completed.stdout}\nstderr={completed.stderr}",
            )
            self.assertIn("contracts ok", completed.stdout)

    def test_source_layout_without_repository_readme_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repository = Path(td) / "repository"
            installed = repository / "skills" / "autoresearch-paper"
            shutil.copytree(ROOT, installed, ignore=shutil.ignore_patterns("node_modules"))
            (repository / "CHANGELOG.md").write_text("# Changelog\n")

            completed = self.run_validator(installed)

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("missing repository README.md", completed.stdout)

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
