#!/usr/bin/env python3
"""Behavioral tests for autoresearch-paper runtime contracts."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    proc = subprocess.run(cmd, cwd=cwd, env=merged, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise AssertionError(f"command failed {cmd}\nstdout={proc.stdout}\nstderr={proc.stderr}")
    return proc


class RuntimeContracts(unittest.TestCase):
    def make_plan(self, tmp: Path, name: str = "plan-artifacts") -> Path:
        plan = tmp / name
        (plan / "state").mkdir(parents=True)
        (plan / "control").mkdir()
        return plan

    def write_manifest(self, plan: Path, **overrides: object) -> None:
        data = {
            "schema_version": 1,
            "plan_id": "plan_abc",
            "plan_dir": str(plan),
            "status": "running",
            "agents": [],
            "sessions": [],
            "crons": [],
            "hooks": [],
            "launchd": [],
            "local_processes": [],
            "remote_processes": [],
            "locks": [],
        }
        data.update(overrides)
        (plan / "resource_manifest.json").write_text(json.dumps(data, indent=2) + "\n")

    def fake_mavis_env(self, tmp: Path) -> dict[str, str]:
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        log = tmp / "mavis.log"
        (bin_dir / "mavis").write_text(
            "#!/usr/bin/env bash\n"
            "echo \"$*\" >> \"$MAVIS_FAKE_LOG\"\n"
            "case \"$1 $2\" in\n"
            "  'cron list') echo keep-cron; echo delete-cron ;;\n"
            "  'hook list') echo keep-hook.json; echo delete-hook.json ;;\n"
            "  'team plan') echo '{\"state\":{\"status\":\"paused\"}}' ;;\n"
            "esac\n"
        )
        (bin_dir / "mavis").chmod(0o755)
        return {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}", "MAVIS_FAKE_LOG": str(log)}

    def test_cleanup_preserves_non_ephemeral_resources(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp)
            self.write_manifest(
                plan,
                crons=[
                    {"agent": "a", "name": "keep-cron", "ephemeral": False},
                    {"agent": "a", "name": "delete-cron", "ephemeral": True},
                ],
                hooks=[
                    {"name": "keep-hook.json", "ephemeral": False},
                    {"name": "delete-hook.json", "ephemeral": True},
                ],
                agents=[
                    {"name": "stable-agent", "ephemeral": False},
                    {"name": "tmp-agent", "ephemeral": True},
                ],
                local_processes=[
                    {"label": "shared-proc", "pid": 999999, "ephemeral": False},
                    {"label": "owned-proc", "pid": 999999, "ephemeral": True},
                ],
            )
            run([
                "bash",
                "references/scripts/cleanup-plan-resources.sh",
                str(plan),
                "--dry-run",
            ], env=self.fake_mavis_env(tmp))
            report = (plan / "cleanup_report.md").read_text()
            self.assertIn("non-ephemeral; left in place", report)
            self.assertIn("DRY-RUN cron:a/delete-cron", report)
            self.assertIn("DRY-RUN hook:delete-hook.json", report)
            self.assertIn("DRY-RUN agent-archive:tmp-agent", report)
            self.assertNotIn("DRY-RUN cron:a/keep-cron", report)
            self.assertNotIn("DRY-RUN hook:keep-hook.json", report)
            self.assertNotIn("DRY-RUN agent-archive:stable-agent", report)

    def test_cleanup_complete_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = self.make_plan(Path(td))
            self.write_manifest(plan, plan_id=None)
            run(["bash", "references/scripts/cleanup-plan-resources.sh", str(plan), "--mode", "complete"])
            manifest = json.loads((plan / "resource_manifest.json").read_text())
            self.assertEqual(manifest["status"], "completed_cleaned")
            self.assertEqual(manifest["cleanup_mode"], "complete")

    def test_bootstrap_rescue_creates_launchagents_parent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            (plan / "watchdog-system-prompt.md").write_text("watchdog prompt\n")
            env = {**self.fake_mavis_env(tmp), "HOME": str(tmp)}
            run([
                "bash",
                "references/bootstrap-watchdog.sh",
                "smoke",
                "conference",
                str(plan),
                "--rescue",
            ], env=env)
            self.assertTrue((tmp / "Library" / "LaunchAgents").is_dir())
            self.assertTrue((plan / "WATCHDOG.md").read_text().find("--rescue") >= 0)
            manifest = json.loads((plan / "resource_manifest.json").read_text())
            self.assertEqual(manifest["topic_slug"], "smoke")
            self.assertEqual(manifest["launchd"][0]["run_scoped"], False)

    def test_research_writing_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = self.make_plan(Path(td))
            gate = plan / "state" / "research_acceptance.md"
            gate.write_text("FAIL\n")
            proc = run([
                "python3",
                "references/scripts/research-state-guard.py",
                "check-writing-gate",
                "--plan-dir",
                str(plan),
                "--tier",
                "conference",
            ], check=False)
            self.assertEqual(proc.returncode, 20)
            self.assertFalse(json.loads(proc.stdout)["ok"])

            gate.write_text("PASS\n")
            proc = run([
                "python3",
                "references/scripts/research-state-guard.py",
                "check-writing-gate",
                "--plan-dir",
                str(plan),
                "--tier",
                "conference",
            ])
            self.assertTrue(json.loads(proc.stdout)["ok"])

            gate.write_text("WAIVED_NEGATIVE_RESULT\n")
            proc = run([
                "python3",
                "references/scripts/research-state-guard.py",
                "check-writing-gate",
                "--plan-dir",
                str(plan),
                "--tier",
                "conference",
            ], check=False)
            self.assertEqual(proc.returncode, 20)

            proc = run([
                "python3",
                "references/scripts/research-state-guard.py",
                "check-writing-gate",
                "--plan-dir",
                str(plan),
                "--tier",
                "arxiv",
            ])
            self.assertTrue(json.loads(proc.stdout)["ok"])

    def test_structural_pivot_guard(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = self.make_plan(Path(td))
            (plan / "state" / "progress.json").write_text(json.dumps({"stale_count": 2}) + "\n")
            weak = plan / "weak-pivot.json"
            weak.write_text(json.dumps({"changed_fields": ["learning_rate"]}))
            proc = run([
                "python3",
                "references/scripts/research-state-guard.py",
                "validate-pivot",
                "--plan-dir",
                str(plan),
                "--proposal",
                str(weak),
            ], check=False)
            self.assertEqual(proc.returncode, 21)

            strong = plan / "strong-pivot.json"
            strong.write_text(json.dumps({"changed_fields": ["algorithm_family"]}))
            proc = run([
                "python3",
                "references/scripts/research-state-guard.py",
                "validate-pivot",
                "--plan-dir",
                str(plan),
                "--proposal",
                str(strong),
            ])
            self.assertTrue(json.loads(proc.stdout)["ok"])

    def test_l0_dry_run_does_not_mutate_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = self.make_plan(Path(td))
            self.write_manifest(plan)
            (plan / "state.json").write_text(json.dumps({"state": {"status": "running", "cycle_started_at": 0}}))
            before = sorted(str(p.relative_to(plan)) for p in plan.rglob("*") if p.is_file())
            proc = run([
                "python3",
                "references/scripts/plan-l0-guard.py",
                "--plan-dir",
                str(plan),
                "--once",
                "--stale-sec",
                "1",
                "--dry-run",
            ])
            self.assertIn("stale_observed", proc.stdout)
            after = sorted(str(p.relative_to(plan)) for p in plan.rglob("*") if p.is_file())
            self.assertEqual(before, after)

    def test_l0_stale_count_and_escalation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = self.make_plan(Path(td))
            self.write_manifest(plan)
            (plan / "state.json").write_text(json.dumps({"state": {"status": "running", "cycle_started_at": 0}}))
            (plan / "last_seen.jsonl").write_text('{"ts":"2020-01-01T00:00:00Z"}\n')
            run(["python3", "references/scripts/plan-l0-guard.py", "--plan-dir", str(plan), "--once", "--stale-sec", "1"])
            run(["python3", "references/scripts/plan-l0-guard.py", "--plan-dir", str(plan), "--once", "--stale-sec", "1"])
            progress = json.loads((plan / "state" / "progress.json").read_text())
            self.assertEqual(progress["stale_count"], 1)
            (plan / "last_seen.jsonl").write_text('{"ts":"2021-01-01T00:00:00Z"}\n')
            run(["python3", "references/scripts/plan-l0-guard.py", "--plan-dir", str(plan), "--once", "--stale-sec", "1"])
            progress = json.loads((plan / "state" / "progress.json").read_text())
            self.assertEqual(progress["research_status"], "pivot_required")
            self.assertTrue((plan / "control" / "pivot_requested.json").exists())

            progress["stale_count"] = 3
            (plan / "state" / "progress.json").write_text(json.dumps(progress))
            (plan / "last_seen.jsonl").write_text('{"ts":"2022-01-01T00:00:00Z"}\n')
            run(["python3", "references/scripts/plan-l0-guard.py", "--plan-dir", str(plan), "--once", "--stale-sec", "1"])
            progress = json.loads((plan / "state" / "progress.json").read_text())
            self.assertEqual(progress["research_status"], "escalate_to_human")
            self.assertTrue((plan / "control" / "override_requested.json").exists())

    def test_resolve_plan_dir_and_stop_json_escaping(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            root = tmp / "scratchpads"
            plan = self.make_plan(root / "autoresearch" / "topic")
            self.write_manifest(plan, plan_id="plan_quote")
            env = {**self.fake_mavis_env(tmp), "AUTORESEARCH_PLAN_ROOTS": str(root)}
            resolved = run(["python3", "references/scripts/resolve-plan-dir.py", "plan_quote"], env=env).stdout.strip()
            self.assertEqual(Path(resolved), plan.resolve())

            reason = 'bad " quote and slash \\ ok'
            run(["bash", "references/scripts/stop-plan.sh", "plan_quote", "--reason", reason], env=env)
            manifest = json.loads((plan / "resource_manifest.json").read_text())
            self.assertEqual(manifest["status"], "stopped_cleaned")
            history = [json.loads(line) for line in (plan / "state" / "stop_history.jsonl").read_text().splitlines()]
            self.assertEqual(history[-1]["reason"], reason)
            handled = list((plan / "control" / "handled").glob("*stop_requested.json"))
            self.assertTrue(handled)
            json.loads(handled[-1].read_text())
            cleanup_requested = json.loads((plan / "control" / "cleanup_requested.json").read_text())
            self.assertEqual(cleanup_requested["reason"], reason)

    def test_rescue_dry_run_does_not_call_mavis_or_write_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan_stop")
            self.write_manifest(plan)
            (plan / "state.json").write_text(json.dumps({"state": {"status": "running"}}))
            (plan / "control" / "stop_requested.json").write_text("{}")
            env = self.fake_mavis_env(tmp)
            run([
                "python3",
                "references/scripts/plan-rescue-daemon.py",
                "--dry-run",
                "--once",
            ], env={**env, "HOME": str(tmp), "AUTORESEARCH_PLAN_ROOTS": str(tmp)})
            log = Path(env["MAVIS_FAKE_LOG"])
            self.assertFalse(log.exists(), "dry-run should not call mavis")
            self.assertFalse((plan / "state" / "rescue_history.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
