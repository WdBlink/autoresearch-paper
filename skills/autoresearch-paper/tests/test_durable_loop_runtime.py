#!/usr/bin/env python3
"""Focused T006 tests for the durable trigger, state loop, and Guardian boundary."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_runtime_contracts as runtime_contracts


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "references" / "scripts" / "harness-runtime.py"


class DurableLoopRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = runtime_contracts.RuntimeContracts(methodName="runTest")

    def call(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [sys.executable, str(RUNTIME), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if check and proc.returncode != 0:
            self.fail(f"command failed: {args}\nstdout={proc.stdout}\nstderr={proc.stderr}")
        return proc

    def ready_plan(self, root: Path) -> Path:
        plan = self.base.make_plan(root / "plan")
        self.base.write_manifest(plan)
        self.base.init_model_policy(plan)
        self.base.approve_cp01(plan, root)
        return plan

    @staticmethod
    def artifact(path: Path) -> dict[str, str]:
        return {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    def graph(self, plan: Path) -> Path:
        objective = plan / "objective.md"
        constraints = plan / "constraints.json"
        evaluator = plan / "evaluator.json"
        task_input = plan / "input.json"
        first_contract = plan / "task-first.json"
        second_contract = plan / "task-second.json"
        objective.write_text("bounded objective\n")
        constraints.write_text('{"budget":"bounded"}\n')
        evaluator.write_text('{"kind":"hard-metric"}\n')
        task_input.write_text('{"seed":1}\n')
        first_contract.write_text('{"schema_version":1,"task_id":"first"}\n')
        second_contract.write_text('{"schema_version":1,"task_id":"second"}\n')
        graph = plan / "durable-plan.json"
        graph.write_text(json.dumps({
            "schema_version": 1,
            "plan_id": "plan_abc",
            "target_tier": "arxiv",
            "execution_mode": "unattended",
            "objective": self.artifact(objective),
            "constraints": self.artifact(constraints),
            "evaluator": self.artifact(evaluator),
            "tasks": [
                {
                    "task_id": "first",
                    "phase": "research",
                    "depends_on": [],
                    "task_contract": self.artifact(first_contract),
                    "inputs": [self.artifact(task_input)],
                },
                {
                    "task_id": "second",
                    "phase": "evaluate",
                    "depends_on": ["first"],
                    "task_contract": self.artifact(second_contract),
                    "inputs": [self.artifact(task_input)],
                },
            ],
        }, indent=2))
        return graph

    def fake_launchctl(self, root: Path) -> tuple[Path, Path]:
        executable = root / "fake-launchctl"
        state = root / "launchctl.state"
        log = root / "launchctl.log"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib,sys\n"
            f"state=pathlib.Path({str(state)!r});log=pathlib.Path({str(log)!r})\n"
            "args=sys.argv[1:];log.open('a').write(' '.join(args)+'\\n')\n"
            "if args[0]=='print':sys.exit(0 if state.exists() else 3)\n"
            "if args[0]=='bootstrap':state.write_text(args[-1]);sys.exit(0)\n"
            "if args[0]=='bootout':state.unlink(missing_ok=True);sys.exit(0)\n"
            "sys.exit(2)\n"
        )
        executable.chmod(0o755)
        return executable, log

    def register(self, plan: Path, launchctl: Path) -> dict[str, object]:
        return json.loads(self.call(
            "register-durable-trigger",
            "--plan-dir", str(plan),
            "--schedule-id", "research_loop",
            "--interval-seconds", "60",
            "--jitter-seconds", "0",
            "--session-budget-seconds", "600",
            "--human-escalation-after-seconds", "300",
            "--lease-seconds", "30",
            "--first-due-at", "2026-07-23T00:00:00Z",
            "--launchctl-bin", str(launchctl),
        ).stdout)

    def test_state_capsule_rebuild_and_integrity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.ready_plan(root)
            graph = self.graph(plan)
            initialized = json.loads(self.call(
                "init-durable-plan", "--plan-dir", str(plan), "--graph", str(graph),
            ).stdout)
            self.assertEqual(initialized["state_revision"], 0)
            self.assertEqual(initialized["projection"]["next_action"]["task_id"], "first")

            advanced = json.loads(self.call(
                "advance-durable-plan", "--plan-dir", str(plan),
            ).stdout)
            capsule = Path(advanced["capsule_path"])
            self.assertTrue(capsule.is_file())
            self.assertEqual(advanced["capsule"]["state_revision"], 1)
            projection_path = plan / "state" / "durable_loop" / "projection.json"
            expected_projection = json.loads(projection_path.read_text())
            projection_path.unlink()
            rebuilt = json.loads(self.call(
                "rebuild-durable-projection", "--plan-dir", str(plan),
            ).stdout)["projection"]
            self.assertEqual(rebuilt, expected_projection)

            evidence = plan / "first-evidence.json"
            evidence.write_text('{"score":1}\n')
            result = plan / "first-result.json"
            result.write_text(json.dumps({
                "schema_version": 1,
                "capsule_id": advanced["capsule"]["capsule_id"],
                "task_id": "first",
                "evidence": [self.artifact(evidence)],
            }))
            evaluator = plan / "evaluator.json"
            original = evaluator.read_text()
            evaluator.write_text('{"kind":"drifted"}\n')
            drift = self.call(
                "apply-work-unit-result",
                "--plan-dir", str(plan),
                "--capsule", str(capsule),
                "--result", str(result),
                check=False,
            )
            self.assertEqual(drift.returncode, 2)
            self.assertIn("hash mismatch", drift.stderr)
            evaluator.write_text(original)

            applied = json.loads(self.call(
                "apply-work-unit-result",
                "--plan-dir", str(plan),
                "--capsule", str(capsule),
                "--result", str(result),
            ).stdout)
            self.assertEqual(applied["projection"]["state_revision"], 2)
            self.assertEqual(applied["projection"]["next_action"]["task_id"], "second")
            second = json.loads(self.call(
                "advance-durable-plan", "--plan-dir", str(plan),
            ).stdout)
            self.assertEqual(second["capsule"]["task_id"], "second")
            self.assertNotEqual(
                second["capsule"]["capsule_id"],
                advanced["capsule"]["capsule_id"],
            )

    def test_external_registration_concurrent_claim_and_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.ready_plan(root)
            launchctl, log = self.fake_launchctl(root)
            graph = self.graph(plan)
            self.call("init-durable-plan", "--plan-dir", str(plan), "--graph", str(graph))
            first = self.register(plan, launchctl)
            second = self.register(plan, launchctl)
            self.assertTrue(second["idempotent"])
            self.assertEqual(
                sum("bootstrap " in line for line in log.read_text().splitlines()),
                1,
            )
            tick_id = "tick_" + "a" * 64
            argv = [
                sys.executable, str(RUNTIME), "claim-durable-tick",
                "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--tick-id", tick_id,
                "--observed-at", "2026-07-23T00:00:00Z",
                "--lease-seconds", "30",
            ]
            one = subprocess.Popen(argv, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            two = subprocess.Popen(argv, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out_one, err_one = one.communicate()
            out_two, err_two = two.communicate()
            self.assertEqual(one.returncode, 0, err_one)
            self.assertEqual(two.returncode, 0, err_two)
            claims = [json.loads(out_one), json.loads(out_two)]
            self.assertEqual(sum("claim_receipt" in item for item in claims), 1)
            self.assertEqual(sum(item.get("already_claimed", False) for item in claims), 1)

            pending = json.loads(self.call(
                "reconcile-durable-tick",
                "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--tick-id", tick_id,
                "--observed-at", "2026-07-23T00:00:10Z",
            ).stdout)
            self.assertEqual(pending["outcome"], "pending")
            advanced = json.loads(self.call(
                "reconcile-durable-tick",
                "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--tick-id", tick_id,
                "--observed-at", "2026-07-23T00:00:31Z",
            ).stdout)
            self.assertEqual(advanced["outcome"], "advanced")
            self.assertEqual(advanced["resulting_generation"], 2)
            no_duplicate = json.loads(self.call(
                "reconcile-durable-tick",
                "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--tick-id", tick_id,
                "--observed-at", "2026-07-23T00:00:31Z",
            ).stdout)
            self.assertEqual(no_duplicate["outcome"], "pending")
            self.assertEqual(no_duplicate["resulting_generation"], 2)
            self.assertEqual(first["scheduler_backend"], "launchd")

            tick = json.loads(self.call(
                "run-durable-tick",
                "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--observed-at", "2026-07-23T00:00:00Z",
            ).stdout)
            self.assertTrue(tick["due"])
            self.assertEqual(tick["advance"]["capsule"]["task_id"], "first")
            duplicate_delivery = json.loads(self.call(
                "run-durable-tick",
                "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--observed-at", "2026-07-23T00:00:00Z",
            ).stdout)
            self.assertFalse(duplicate_delivery["due"])

            key = self.base.human_key(root)
            stop = self.base.create_action(plan, key, "stop", record_id="har_stop_trigger")
            applied = json.loads(self.call(
                "apply-human-action",
                "--plan-dir", str(plan),
                "--record", str(stop),
                "--key-file", str(key),
                "--expected-action", "stop",
            ).stdout)
            removed = json.loads(self.call(
                "unregister-durable-trigger",
                "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--authorization", applied["receipt"]["receipt_path"],
                "--launchctl-bin", str(launchctl),
            ).stdout)
            self.assertEqual(removed["registration_id"], first["registration_id"])
            self.assertIn("bootout ", log.read_text())

    def test_guardian_rejects_content_and_requires_applied_lifecycle_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.ready_plan(root)
            run_id = "cwr_" + "a" * 32
            run_dir = plan / "state" / "worker_runs" / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "status.json").write_text(json.dumps({
                "schema_version": 1,
                "run_id": run_id,
                "status": "RUNNING",
                "started_at": "2026-07-23T00:00:00Z",
                "updated_at": "2026-07-23T00:00:00Z",
            }))
            observation = plan / "guardian-observation.json"
            payload = {
                "schema_version": 1,
                "plan_id": "plan_abc",
                "observed_at": "2026-07-23T01:00:00Z",
                "schedule": {
                    "schedule_id": "research_loop",
                    "last_tick_at": None,
                    "next_due_at": "2026-07-23T00:00:00Z",
                },
                "workers": [{
                    "run_id": run_id,
                    "status": "RUNNING",
                    "updated_at": "2026-07-23T00:00:00Z",
                }],
                "controller": {"status": "RUNNING", "state_revision": 0},
            }
            observation.write_text(json.dumps(payload))
            proposal = json.loads(self.call(
                "guardian-observe",
                "--plan-dir", str(plan),
                "--observation", str(observation),
                "--stale-seconds", "300",
            ).stdout)
            self.assertFalse(proposal["research_content_access"])
            self.assertFalse(proposal["lifecycle_authority"])
            self.assertEqual(
                {item["action"] for item in proposal["proposals"]},
                {"reconcile_tick", "record_runtime_stall"},
            )
            stall_index = next(
                index for index, item in enumerate(proposal["proposals"])
                if item["action"] == "record_runtime_stall"
            )
            stall = json.loads(self.call(
                "apply-guardian-proposal",
                "--plan-dir", str(plan),
                "--proposal", proposal["proposal_path"],
                "--action-index", str(stall_index),
            ).stdout)
            self.assertEqual(stall["controller_policy"], "guardian-recovery-v1")
            failure = json.loads((plan / "state" / "failure_state.json").read_text())
            self.assertEqual(failure["runtime_stall_count"], 1)

            payload["research_summary"] = "forbidden content"
            observation.write_text(json.dumps(payload))
            rejected = self.call(
                "guardian-observe",
                "--plan-dir", str(plan),
                "--observation", str(observation),
                "--stale-seconds", "300",
                check=False,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("unexpected properties", rejected.stderr)

            unsigned = plan / "unsigned-stop.json"
            unsigned.write_text('{"action":"stop"}')
            denied = self.call(
                "guardian-validate-lifecycle",
                "--plan-dir", str(plan),
                "--action", "stop",
                "--authorization", str(unsigned),
                check=False,
            )
            self.assertEqual(denied.returncode, 2)

            key = self.base.human_key(root)
            stop = self.base.create_action(plan, key, "stop", record_id="har_guardian_stop")
            applied = json.loads(self.call(
                "apply-human-action",
                "--plan-dir", str(plan),
                "--record", str(stop),
                "--key-file", str(key),
                "--expected-action", "stop",
            ).stdout)
            allowed = json.loads(self.call(
                "guardian-validate-lifecycle",
                "--plan-dir", str(plan),
                "--action", "stop",
                "--authorization", applied["receipt"]["receipt_path"],
            ).stdout)
            self.assertEqual(allowed["applied_by"], "controller")
            self.assertEqual(
                allowed["event"]["guardian_authority"],
                "validated_pre_authorized_only",
            )

    def test_registration_and_applied_tick_crash_recover_without_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.ready_plan(root)
            launchctl, log = self.fake_launchctl(root)
            graph = self.graph(plan)
            self.call("init-durable-plan", "--plan-dir", str(plan), "--graph", str(graph))
            register_args = (
                "register-durable-trigger",
                "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--interval-seconds", "60",
                "--jitter-seconds", "0",
                "--session-budget-seconds", "600",
                "--human-escalation-after-seconds", "300",
                "--lease-seconds", "30",
                "--first-due-at", "2026-07-23T00:00:00Z",
                "--launchctl-bin", str(launchctl),
            )
            interrupted = self.call(
                *register_args,
                "--simulate-crash-after-bootstrap",
                check=False,
            )
            self.assertEqual(interrupted.returncode, 2)
            recovered = json.loads(self.call(*register_args).stdout)
            self.assertEqual(recovered["registration_generation"], 1)
            self.assertEqual(
                sum("bootstrap " in line for line in log.read_text().splitlines()),
                1,
            )

            tick_args = (
                "run-durable-tick",
                "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--observed-at", "2026-07-23T00:00:00Z",
            )
            tick_interrupted = self.call(
                *tick_args,
                "--simulate-crash-after-tick-apply",
                check=False,
            )
            self.assertEqual(tick_interrupted.returncode, 2)
            tick_recovered = json.loads(self.call(*tick_args).stdout)
            self.assertTrue(tick_recovered["reconciled_applied_tick"])
            head = json.loads(
                (plan / "state" / "durable_loop" / "canonical" / "head.json").read_text()
            )
            self.assertEqual(head["state_revision"], 1)
            events = (
                plan / "state" / "durable_loop" / "schedules"
                / "research_loop" / "tick-events.jsonl"
            ).read_text().splitlines()
            self.assertEqual(sum('"event": "tick_applied"' in line for line in events), 1)


if __name__ == "__main__":
    unittest.main()
