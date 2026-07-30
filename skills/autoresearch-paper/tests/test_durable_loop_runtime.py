#!/usr/bin/env python3
"""Focused T006 tests for the durable trigger, state loop, and Guardian boundary."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import time
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
                    "inputs": [{**self.artifact(task_input), "purpose": "task_input"}],
                },
                {
                    "task_id": "second",
                    "phase": "evaluate",
                    "depends_on": ["first"],
                    "task_contract": self.artifact(second_contract),
                    "inputs": [{**self.artifact(task_input), "purpose": "task_input"}],
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

    def multi_service_launchctl(self, root: Path) -> tuple[Path, Path]:
        executable = root / "multi-launchctl"
        services = root / "launchd-services"
        log = root / "multi-launchctl.log"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib,plistlib,sys\n"
            f"services=pathlib.Path({str(services)!r});log=pathlib.Path({str(log)!r})\n"
            "services.mkdir(exist_ok=True);args=sys.argv[1:]\n"
            "log.open('a').write(' '.join(args)+'\\n')\n"
            "if args[0]=='print':\n"
            " label=args[-1].rsplit('/',1)[-1];raise SystemExit(0 if (services/label).exists() else 3)\n"
            "if args[0]=='bootstrap':\n"
            " label=plistlib.loads(pathlib.Path(args[-1]).read_bytes())['Label'];(services/label).write_text(args[-1]);raise SystemExit(0)\n"
            "if args[0]=='bootout':\n"
            " label=args[-1].rsplit('/',1)[-1];(services/label).unlink(missing_ok=True);raise SystemExit(0)\n"
            "raise SystemExit(2)\n"
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

    def bootstrap_host(
        self, plan: Path, graph: Path, launchctl: Path,
        *extra: str, check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self.call(
            "bootstrap-host-runtime",
            "--plan-dir", str(plan),
            "--graph", str(graph),
            "--interval-seconds", "300",
            "--jitter-seconds", "0",
            "--session-budget-seconds", "600",
            "--human-escalation-after-seconds", "300",
            "--lease-seconds", "30",
            "--health-interval-seconds", "300",
            "--worker-stale-seconds", "1200",
            "--frontier-stale-seconds", "1200",
            "--heartbeat-stale-seconds", "600",
            "--dashboard-port", "8765",
            "--launchctl-bin", str(launchctl),
            *extra,
            check=check,
        )

    @staticmethod
    def process_identity(pid: int) -> dict[str, object]:
        started = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            text=True, capture_output=True, check=True,
        ).stdout.strip()
        command = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True, capture_output=True, check=True,
        ).stdout.strip()
        body: dict[str, object] = {
            "pid": pid,
            "process_group_id": os.getpgid(pid),
            "os_started_at": started,
            "os_command_sha256": hashlib.sha256(command.encode()).hexdigest(),
        }
        encoded = json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode()
        return {**body, "identity_sha256": hashlib.sha256(encoded).hexdigest()}

    def applied_stop(self, plan: Path, root: Path, record_id: str) -> Path:
        key = self.base.human_key(root)
        stop = self.base.create_action(plan, key, "stop", record_id=record_id)
        applied = json.loads(self.call(
            "apply-human-action", "--plan-dir", str(plan),
            "--record", str(stop), "--key-file", str(key),
            "--expected-action", "stop",
        ).stdout)
        return Path(applied["receipt"]["receipt_path"])

    def test_runtime_assurance_activates_independent_l0_l1_l2(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.ready_plan(root)
            launchctl, log = self.multi_service_launchctl(root)
            self.call(
                "init-durable-plan", "--plan-dir", str(plan),
                "--graph", str(self.graph(plan)),
            )
            l1 = self.register(plan, launchctl)
            missing = self.call(
                "record-worker-heartbeat", "--plan-dir", str(plan),
                "--worker-run-id", "cwr_" + "a" * 32,
                check=False,
            )
            self.assertIn("requires runtime-assurance activation", missing.stderr)
            activated = json.loads(self.call(
                "activate-runtime-assurance", "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--health-interval-seconds", "300",
                "--worker-stale-seconds", "1200",
                "--frontier-stale-seconds", "1200",
                "--heartbeat-stale-seconds", "600",
                "--launchctl-bin", str(launchctl),
            ).stdout)
            self.assertNotEqual(
                activated["l0_scheduler_label"], l1["scheduler_label"],
            )
            l1_plist = plistlib.loads(Path(l1["scheduler_plist_path"]).read_bytes())
            self.assertEqual(l1_plist["StandardOutPath"], l1["scheduler_stdout_path"])
            self.assertEqual(l1_plist["StandardErrorPath"], l1["scheduler_stderr_path"])
            l0_plist = plistlib.loads(
                Path(activated["l0_scheduler_plist_path"]).read_bytes()
            )
            self.assertEqual(
                l0_plist["StandardOutPath"], activated["l0_scheduler_stdout_path"],
            )
            self.assertEqual(
                l0_plist["StandardErrorPath"], activated["l0_scheduler_stderr_path"],
            )
            self.assertEqual(
                json.loads(Path(activated["test_health_tick_path"]).read_text())[
                    "model_dispatches"
                ],
                0,
            )
            self.assertEqual(
                json.loads(Path(activated["test_heartbeat_path"]).read_text())[
                    "model_dispatches"
                ],
                0,
            )
            tick = json.loads(self.call(
                "run-runtime-assurance-tick", "--plan-dir", str(plan),
            ).stdout)
            self.assertEqual(tick["kind"], "health_only")
            self.assertEqual(tick["model_dispatches"], 0)
            (root / "launchd-services" / l1["scheduler_label"]).unlink()
            recovered = json.loads(self.call(
                "run-runtime-assurance-tick", "--plan-dir", str(plan),
            ).stdout)
            self.assertTrue(recovered["recovered_l1"])
            current_path = (
                plan / "state" / "runtime_assurance" / "v1" / "current.json"
            )
            current = json.loads(current_path.read_text())
            live_health = current["last_health_at"]
            current["last_health_at"] = "2026-01-01T00:00:00Z"
            current_path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
            stale = self.call(
                "record-worker-heartbeat", "--plan-dir", str(plan),
                "--worker-run-id", "cwr_" + "a" * 32,
                check=False,
            )
            self.assertIn("health receipt is stale", stale.stderr)
            current["last_health_at"] = live_health
            current_path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
            bootstrap_lines = [
                line for line in log.read_text().splitlines()
                if line.startswith("bootstrap ")
            ]
            self.assertEqual(len(bootstrap_lines), 3)
            invalid = self.call(
                "activate-runtime-assurance", "--plan-dir", str(plan),
                "--health-interval-seconds", "601",
                "--worker-stale-seconds", "1200",
                "--frontier-stale-seconds", "1200",
                "--heartbeat-stale-seconds", "1200",
                "--launchctl-bin", str(launchctl),
                check=False,
            )
            self.assertIn("no more than half", invalid.stderr)

    def test_codex_host_bootstrap_exercises_watchdog_layers_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.ready_plan(root)
            graph = self.graph(plan)
            launchctl, log = self.multi_service_launchctl(root)
            result = json.loads(
                self.bootstrap_host(plan, graph, launchctl).stdout
            )
            self.assertEqual(result["status"], "READY")
            l0_probe = json.loads(Path(result["l0_recovery_probe_path"]).read_text())
            l1_probe = json.loads(Path(result["l1_functional_probe_path"]).read_text())
            l2_probe = json.loads(Path(result["l2_conformance_probe_path"]).read_text())
            self.assertTrue(l0_probe["l1_was_removed"])
            self.assertTrue(l0_probe["l1_restored"])
            self.assertEqual(l0_probe["model_dispatches"], 0)
            self.assertFalse(l1_probe["due"])
            self.assertEqual(l1_probe["model_dispatches"], 0)
            self.assertFalse(l2_probe["live_worker_evidence"])
            self.assertEqual(l2_probe["live_worker_gate"], "T032")
            services = root / "launchd-services"
            self.assertTrue((services / result["l0_scheduler_label"]).is_file())
            self.assertTrue((services / result["l1_scheduler_label"]).is_file())
            mutations_before = [
                line for line in log.read_text().splitlines()
                if line.startswith(("bootstrap ", "bootout "))
            ]
            duplicate = json.loads(
                self.bootstrap_host(plan, graph, launchctl).stdout
            )
            self.assertTrue(duplicate["idempotent"])
            mutations_after = [
                line for line in log.read_text().splitlines()
                if line.startswith(("bootstrap ", "bootout "))
            ]
            self.assertEqual(mutations_before, mutations_after)
            manifest = json.loads((plan / "resource_manifest.json").read_text())
            resources = [
                item for item in manifest["resources"]
                if item.get("resource_id") == "codex_host_runtime_assurance_v1"
            ]
            self.assertEqual(len(resources), 1)
            inspection = json.loads(self.call(
                "inspect-plan-runtime", "--plan-dir", str(plan),
                "--launchctl-bin", str(launchctl),
            ).stdout)
            self.assertEqual(inspection["host_bootstrap"]["status"], "READY")
            self.assertEqual(
                inspection["host_bootstrap"]["last_health_action"],
                "l1_restored",
            )
            self.assertIsNone(
                inspection["host_bootstrap"]["live_l2_worker_evidence"],
            )
            (services / result["l1_scheduler_label"]).unlink()
            degraded = json.loads(self.call(
                "inspect-plan-runtime", "--plan-dir", str(plan),
                "--launchctl-bin", str(launchctl),
            ).stdout)
            self.assertIn(
                "L1 durable trigger is not loaded",
                degraded["host_bootstrap"]["validation_error"],
            )
            recovered_tick = json.loads(self.call(
                "run-runtime-assurance-tick", "--plan-dir", str(plan),
            ).stdout)
            self.assertTrue(recovered_tick["recovered_l1"])
            healed = json.loads(self.call(
                "inspect-plan-runtime", "--plan-dir", str(plan),
                "--launchctl-bin", str(launchctl),
            ).stdout)
            self.assertIsNone(healed["host_bootstrap"]["validation_error"])

    def test_codex_host_bootstrap_recovers_crash_after_l1_loss(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.ready_plan(root)
            graph = self.graph(plan)
            launchctl, _ = self.multi_service_launchctl(root)
            crashed = self.bootstrap_host(
                plan, graph, launchctl,
                "--simulate-crash-after", "l1_bootout",
                check=False,
            )
            self.assertEqual(crashed.returncode, 2)
            current = plan / "state" / "host_bootstrap" / "v1" / "current.json"
            self.assertFalse(current.exists())
            journal = json.loads(
                (plan / "state" / "host_bootstrap" / "v1" / "journal.json").read_text()
            )
            self.assertEqual(
                journal["last_failure"]["failure_class"],
                "bootstrap_interrupted",
            )
            self.assertTrue(journal["last_failure"]["recoverable"])
            recovered = json.loads(
                self.bootstrap_host(plan, graph, launchctl).stdout
            )
            self.assertEqual(recovered["status"], "READY")
            services = root / "launchd-services"
            self.assertTrue((services / recovered["l0_scheduler_label"]).is_file())
            self.assertTrue((services / recovered["l1_scheduler_label"]).is_file())

    def test_codex_host_bootstrap_binding_drift_is_visible_and_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.ready_plan(root)
            graph = self.graph(plan)
            launchctl, _ = self.multi_service_launchctl(root)
            result = json.loads(
                self.bootstrap_host(plan, graph, launchctl).stdout
            )
            probe = Path(result["l1_functional_probe_path"])
            probe.chmod(0o644)
            payload = json.loads(probe.read_text())
            payload["due"] = True
            probe.write_text(json.dumps(payload))
            inspection = json.loads(self.call(
                "inspect-plan-runtime", "--plan-dir", str(plan),
                "--launchctl-bin", str(launchctl),
            ).stdout)
            self.assertIsNotNone(
                inspection["host_bootstrap"]["validation_error"],
            )
            duplicate = self.bootstrap_host(
                plan, graph, launchctl, check=False,
            )
            self.assertEqual(duplicate.returncode, 2)
            self.assertIn("binding changed", duplicate.stderr)

    def test_codex_host_bootstrap_rejects_missing_authority_before_runtime_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.base.make_plan(root / "plan")
            self.base.write_manifest(plan)
            self.base.init_model_policy(plan)
            graph = self.graph(plan)
            launchctl, log = self.multi_service_launchctl(root)
            rejected = self.bootstrap_host(
                plan, graph, launchctl, check=False,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("transition receipt", rejected.stderr)
            self.assertFalse(log.exists())
            self.assertFalse((plan / "state" / "host_bootstrap").exists())
            self.assertFalse((plan / "state" / "durable_loop").exists())

    def test_read_only_inspection_and_exact_once_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.ready_plan(root)
            launchctl, _ = self.multi_service_launchctl(root)
            self.call(
                "init-durable-plan", "--plan-dir", str(plan),
                "--graph", str(self.graph(plan)),
            )
            l1 = self.register(plan, launchctl)
            l0 = json.loads(self.call(
                "activate-runtime-assurance", "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--health-interval-seconds", "300",
                "--worker-stale-seconds", "1200",
                "--frontier-stale-seconds", "1200",
                "--heartbeat-stale-seconds", "600",
                "--launchctl-bin", str(launchctl),
            ).stdout)

            retry_root = plan / "state" / "frontier" / "retry-trigger"
            retry_generation = retry_root / "generations" / "1"
            retry_generation.mkdir(parents=True)
            retry_label = "com.autoresearch-paper.frontier-retry.test"
            retry_plist = retry_generation / f"{retry_label}.plist"
            retry_plist.write_bytes(plistlib.dumps({
                "Label": retry_label,
                "ProgramArguments": ["/usr/bin/true"],
            }))
            subprocess.run(
                [str(launchctl), "bootstrap", f"gui/{os.getuid()}", str(retry_plist)],
                check=True,
            )
            retry_receipt = retry_generation / "registration-receipt.json"
            retry_receipt.write_text(json.dumps({
                "schema_version": 1,
                "plan_id": "plan_abc",
                "generation": 1,
                "launchctl_bin": str(launchctl),
                "scheduler_label": retry_label,
                "scheduler_plist_path": str(retry_plist),
            }))
            (retry_root / "current.json").write_text(json.dumps({
                "schema_version": 1,
                "plan_id": "plan_abc",
                "generation": 1,
                "active": True,
                "registration_receipt_path": str(retry_receipt),
            }))

            sleeper = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                start_new_session=True,
            )
            try:
                time.sleep(0.05)
                run_id = "cwr_" + "b" * 32
                run_dir = plan / "state" / "worker_runs" / run_id
                run_dir.mkdir(parents=True)
                stdout_path = run_dir / "transport.stdout"
                stderr_path = run_dir / "transport.stderr"
                stdout_path.write_text("")
                stderr_path.write_text("")
                identity = self.process_identity(sleeper.pid)
                (run_dir / "status.json").write_text(json.dumps({
                    "schema_version": 1,
                    "run_id": run_id,
                    "status": "RUNNING",
                    "started_at": "2026-07-28T00:00:00Z",
                    "updated_at": "2026-07-28T00:00:00Z",
                    "pid": sleeper.pid,
                    "process_group_id": os.getpgid(sleeper.pid),
                    "process_identity": identity,
                    "worker_command_sha256": "a" * 64,
                    "transport_stdout_path": str(stdout_path),
                    "transport_stderr_path": str(stderr_path),
                }))
                before = {
                    str(path.relative_to(plan)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in plan.rglob("*") if path.is_file()
                }
                inspection = json.loads(self.call(
                    "inspect-plan-runtime", "--plan-dir", str(plan),
                    "--launchctl-bin", str(launchctl),
                ).stdout)
                after = {
                    str(path.relative_to(plan)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in plan.rglob("*") if path.is_file()
                }
                self.assertEqual(before, after)
                self.assertTrue(inspection["observation_only"])
                self.assertEqual(
                    {item["kind"] for item in inspection["schedulers"] if item["loaded"]},
                    {"l0_runtime_assurance", "l1_durable_trigger", "frontier_retry_trigger"},
                )
                self.assertTrue(inspection["workers"][0]["process"]["identity_match"])

                stop_receipt = self.applied_stop(plan, root, "har_shutdown")
                crashed = self.call(
                    "shutdown-plan", "--plan-dir", str(plan),
                    "--authorization", str(stop_receipt),
                    "--launchctl-bin", str(launchctl),
                    "--term-grace-seconds", "0.2",
                    "--simulate-crash-after", "l0",
                    check=False,
                )
                self.assertEqual(crashed.returncode, 2)
                self.assertFalse(
                    (root / "launchd-services" / l0["l0_scheduler_label"]).exists()
                )
                self.assertTrue(
                    (root / "launchd-services" / l1["scheduler_label"]).exists()
                )
                shutdown = json.loads(self.call(
                    "shutdown-plan", "--plan-dir", str(plan),
                    "--authorization", str(stop_receipt),
                    "--launchctl-bin", str(launchctl),
                    "--term-grace-seconds", "0.2",
                ).stdout)
                self.assertEqual(shutdown["status"], "SHUTDOWN")
                self.assertFalse(shutdown["artifacts_deleted"])
                self.assertFalse(shutdown["cleanup_resource_authority"])
                self.assertFalse((root / "launchd-services" / l1["scheduler_label"]).exists())
                self.assertFalse((root / "launchd-services" / retry_label).exists())
                sleeper.wait(timeout=3)
                worker_status = json.loads((run_dir / "status.json").read_text())
                self.assertEqual(worker_status["status"], "CANCELLED")
                duplicate = json.loads(self.call(
                    "shutdown-plan", "--plan-dir", str(plan),
                    "--authorization", str(stop_receipt),
                    "--launchctl-bin", str(launchctl),
                ).stdout)
                self.assertTrue(duplicate["idempotent"])
                blocked = self.call(
                    "advance-durable-plan", "--plan-dir", str(plan), check=False,
                )
                self.assertIn("plan is stopped", blocked.stderr)
            finally:
                if sleeper.poll() is None:
                    os.killpg(os.getpgid(sleeper.pid), 9)
                    sleeper.wait(timeout=3)

    def test_shutdown_refuses_reused_or_drifted_worker_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.ready_plan(root)
            launchctl, _ = self.multi_service_launchctl(root)
            sleeper = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                start_new_session=True,
            )
            try:
                time.sleep(0.05)
                run_id = "cwr_" + "c" * 32
                run_dir = plan / "state" / "worker_runs" / run_id
                run_dir.mkdir(parents=True)
                identity = self.process_identity(sleeper.pid)
                identity["os_command_sha256"] = "0" * 64
                body = {key: value for key, value in identity.items() if key != "identity_sha256"}
                identity["identity_sha256"] = hashlib.sha256(json.dumps(
                    body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                ).encode()).hexdigest()
                (run_dir / "status.json").write_text(json.dumps({
                    "schema_version": 1,
                    "run_id": run_id,
                    "status": "RUNNING",
                    "started_at": "2026-07-28T00:00:00Z",
                    "pid": sleeper.pid,
                    "process_group_id": os.getpgid(sleeper.pid),
                    "process_identity": identity,
                }))
                stop_receipt = self.applied_stop(plan, root, "har_shutdown_drift")
                shutdown = json.loads(self.call(
                    "shutdown-plan", "--plan-dir", str(plan),
                    "--authorization", str(stop_receipt),
                    "--launchctl-bin", str(launchctl),
                    "--term-grace-seconds", "0.1",
                ).stdout)
                self.assertEqual(shutdown["status"], "SHUTDOWN_WITH_RESIDUALS")
                self.assertEqual(
                    shutdown["steps"]["workers"][run_id]["outcome"],
                    "identity_mismatch",
                )
                self.assertIsNone(sleeper.poll())
                self.assertEqual(
                    json.loads((run_dir / "status.json").read_text())["status"],
                    "CANCELLED",
                )
            finally:
                if sleeper.poll() is None:
                    os.killpg(os.getpgid(sleeper.pid), 9)
                    sleeper.wait(timeout=3)

    def test_authenticated_worker_cancel_terminates_bound_process(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.ready_plan(root)
            sleeper = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                start_new_session=True,
            )
            try:
                time.sleep(0.05)
                run_id = "cwr_" + "d" * 32
                run_dir = plan / "state" / "worker_runs" / run_id
                run_dir.mkdir(parents=True)
                identity = self.process_identity(sleeper.pid)
                (run_dir / "status.json").write_text(json.dumps({
                    "schema_version": 1,
                    "run_id": run_id,
                    "status": "RUNNING",
                    "started_at": "2026-07-28T00:00:00Z",
                    "pid": sleeper.pid,
                    "process_group_id": os.getpgid(sleeper.pid),
                    "process_identity": identity,
                }))
                key = self.base.human_key(root)
                cancel = self.base.create_action(
                    plan, key, "cancel_worker", record_id="har_cancel_bound",
                    extra=("--worker-run-id", run_id),
                )
                applied = json.loads(self.call(
                    "cancel-worker", "--plan-dir", str(plan),
                    "--record", str(cancel), "--key-file", str(key),
                    "--worker-run-id", run_id,
                ).stdout)
                sleeper.wait(timeout=3)
                self.assertEqual(
                    applied["receipt"]["process_termination"]["outcome"],
                    "terminated",
                )
                self.assertEqual(
                    json.loads((run_dir / "status.json").read_text())["status"],
                    "CANCELLED",
                )
            finally:
                if sleeper.poll() is None:
                    os.killpg(os.getpgid(sleeper.pid), 9)
                    sleeper.wait(timeout=3)

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
