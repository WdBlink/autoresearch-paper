#!/usr/bin/env python3
"""T008 production fault, multi-session soak, and claim-gate acceptance."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import test_durable_loop_runtime as durable_tests


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "references" / "scripts" / "harness-runtime.py"
SCENARIOS = (
    "process_death",
    "missed_tick",
    "duplicate_trigger",
    "state_corruption",
    "budget_exhaustion",
    "evaluator_drift",
    "multi_session_restart",
)


class FaultSoakAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.helper = durable_tests.DurableLoopRuntimeTests(methodName="runTest")
        self.helper.setUp()

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

    @staticmethod
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def utc() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def profile(self, plan: Path) -> Path:
        profile = plan / "t008-profile.json"
        profile.write_text(json.dumps({
            "schema_version": 1,
            "profile_id": "t008-short-bounded",
            "planned_duration_seconds": 1,
            "required_session_restarts": 2,
            "fault_scenarios": list(SCENARIOS),
            "allowed_claims": ["bounded_fault_acceptance"],
        }, indent=2))
        return profile

    def write_fault(
        self, plan: Path, scenario: str, details: dict[str, object],
    ) -> Path:
        log = plan / "state" / "acceptance" / "observed" / f"{scenario}.json"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps(details, indent=2, sort_keys=True))
        record = plan / f"fault-{scenario}.json"
        record.write_text(json.dumps({
            "schema_version": 1,
            "profile_id": "t008-short-bounded",
            "scenario": scenario,
            "status": "PASS",
            "checks": {
                "authority": True,
                "idempotency": True,
                "recovery": True,
                "evidence": True,
            },
            "evidence": [{
                "path": str(log),
                "sha256": self.sha(log),
                "purpose": f"{scenario} observed result",
            }],
        }, indent=2))
        return record

    def write_session(
        self,
        plan: Path,
        index: int,
        transitions: list[str],
        accepted: list[str],
    ) -> Path:
        started = self.utc()
        rebuilt = json.loads(self.call(
            "rebuild-durable-projection", "--plan-dir", str(plan),
        ).stdout)
        completed = self.utc()
        path = plan / f"soak-session-{index}.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "profile_id": "t008-short-bounded",
            "session_id": f"session-{index}",
            "started_at": started,
            "completed_at": completed,
            "new_transition_ids": transitions,
            "accepted_evidence_ids": accepted,
            "max_controller_overlap": 1,
            "unauthorized_recovery_actions": 0,
        }, indent=2))
        self.assertEqual(rebuilt["projection"]["state_revision"], 1)
        return path

    def test_malformed_profile_types_are_contract_rejections(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = self.helper.ready_plan(Path(td))
            profile = self.profile(plan)
            malformed = json.loads(profile.read_text())
            malformed["profile_id"] = 7
            malformed["fault_scenarios"] = [{"not": "hashable"}]
            profile.write_text(json.dumps(malformed))
            rejected = self.call(
                "start-acceptance-profile",
                "--plan-dir", str(plan),
                "--profile", str(profile),
                check=False,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertNotIn("Traceback", rejected.stderr)
            self.assertIn("acceptance profile values", rejected.stderr)

    def test_seven_faults_multisession_soak_and_bounded_claim(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.helper.ready_plan(root)
            profile = self.profile(plan)
            self.call(
                "start-acceptance-profile",
                "--plan-dir", str(plan),
                "--profile", str(profile),
            )
            graph = self.helper.graph(plan)
            self.call(
                "init-durable-plan", "--plan-dir", str(plan), "--graph", str(graph),
            )
            launchctl, launch_log = self.helper.fake_launchctl(root)

            registration_args = (
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
            crashed = self.call(
                *registration_args,
                "--simulate-crash-after-bootstrap",
                check=False,
            )
            self.assertEqual(crashed.returncode, 2)
            recovered = json.loads(self.call(*registration_args).stdout)
            self.assertEqual(recovered["registration_generation"], 1)
            process_fault = self.write_fault(plan, "process_death", {
                "simulated_crash_returncode": crashed.returncode,
                "registration_id": recovered["registration_id"],
                "bootstrap_calls": sum(
                    "bootstrap " in line for line in launch_log.read_text().splitlines()
                ),
            })

            duplicate_tick = "tick_" + "d" * 64
            claim_argv = [
                sys.executable, str(RUNTIME), "claim-durable-tick",
                "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--tick-id", duplicate_tick,
                "--observed-at", "2026-07-23T00:00:00Z",
                "--lease-seconds", "30",
            ]
            processes = [
                subprocess.Popen(
                    claim_argv, cwd=ROOT, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                for _ in range(2)
            ]
            claims = []
            for process in processes:
                stdout, stderr = process.communicate()
                self.assertEqual(process.returncode, 0, stderr)
                claims.append(json.loads(stdout))
            self.assertEqual(sum("claim_receipt" in item for item in claims), 1)
            self.assertEqual(sum(item.get("already_claimed", False) for item in claims), 1)
            duplicate_fault = self.write_fault(plan, "duplicate_trigger", {
                "claims": claims,
                "winning_claims": 1,
            })

            missed_tick = "tick_" + "e" * 64
            self.call(
                "claim-durable-tick",
                "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--tick-id", missed_tick,
                "--observed-at", "2026-07-23T00:01:00Z",
                "--lease-seconds", "1",
            )
            missed = json.loads(self.call(
                "reconcile-durable-tick",
                "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--tick-id", missed_tick,
                "--observed-at", "2026-07-23T00:01:02Z",
            ).stdout)
            self.assertEqual(missed["outcome"], "advanced")
            repeated_missed = json.loads(self.call(
                "reconcile-durable-tick",
                "--plan-dir", str(plan),
                "--schedule-id", "research_loop",
                "--tick-id", missed_tick,
                "--observed-at", "2026-07-23T00:01:02Z",
            ).stdout)
            self.assertNotEqual(repeated_missed.get("outcome"), "advanced")
            missed_fault = self.write_fault(plan, "missed_tick", {
                "first": missed,
                "repeat": repeated_missed,
            })

            advanced = json.loads(self.call(
                "advance-durable-plan", "--plan-dir", str(plan),
            ).stdout)
            projection_path = plan / "state" / "durable_loop" / "projection.json"
            expected_projection = json.loads(projection_path.read_text())
            projection_path.unlink()
            rebuilt = json.loads(self.call(
                "rebuild-durable-projection", "--plan-dir", str(plan),
            ).stdout)["projection"]
            self.assertEqual(rebuilt, expected_projection)
            state_fault = self.write_fault(plan, "state_corruption", {
                "deleted": "derived projection",
                "rebuilt_state_revision": rebuilt["state_revision"],
                "canonical_event_id": rebuilt["rebuilt_through_event_id"],
            })

            second_request = "far_t008_budget_second"
            self.call(*self.helper.base.cp01_create_args(
                plan, "plan_abc", second_request,
            ))
            self.call(
                "send-frontier-request",
                "--plan-dir", str(plan),
                "--request-id", second_request,
                "--codex-bin", str(self.helper.base.fake_codex(root)),
            )
            third_request = "far_t008_budget_third"
            third_args = self.helper.base.cp01_create_args(
                plan, "plan_abc", third_request,
            )
            self.call(*third_args)
            exhausted = self.call(
                "send-frontier-request",
                "--plan-dir", str(plan),
                "--request-id", third_request,
                "--codex-bin", str(self.helper.base.fake_codex(root)),
                check=False,
            )
            self.assertEqual(exhausted.returncode, 2)
            self.assertIn("budget exhausted", exhausted.stderr)
            budget_fault = self.write_fault(plan, "budget_exhaustion", {
                "returncode": exhausted.returncode,
                "error": json.loads(exhausted.stderr)["error"],
            })

            events = [
                json.loads(line)
                for line in (
                    plan / "state" / "durable_loop" / "events.jsonl"
                ).read_text().splitlines()
                if line.strip()
            ]
            event_ids = [item["event_id"] for item in events]
            approval_id = "frontier:far_worker_approval"
            session_paths = [
                self.write_session(plan, 1, event_ids[:1], [approval_id]),
                self.write_session(plan, 2, event_ids[1:2], [approval_id]),
                self.write_session(plan, 3, event_ids[2:], [approval_id]),
            ]
            session_fault = self.write_fault(plan, "multi_session_restart", {
                "session_count": len(session_paths),
                "state_revision": advanced["projection"]["state_revision"],
                "event_ids": event_ids,
            })

            evaluator = plan / "evaluator.json"
            evaluator.write_text('{"kind":"drifted-after-capsule"}\n')
            evidence = plan / "t008-result-evidence.json"
            evidence.write_text('{"score":1}\n')
            result = plan / "t008-result.json"
            result.write_text(json.dumps({
                "schema_version": 1,
                "capsule_id": advanced["capsule"]["capsule_id"],
                "task_id": advanced["capsule"]["task_id"],
                "evidence": [{
                    "path": str(evidence),
                    "sha256": self.sha(evidence),
                }],
            }))
            drift = self.call(
                "apply-work-unit-result",
                "--plan-dir", str(plan),
                "--capsule", advanced["capsule_path"],
                "--result", str(result),
                check=False,
            )
            self.assertEqual(drift.returncode, 2)
            failure_state = json.loads(
                (plan / "state" / "failure_state.json").read_text()
            )
            self.assertEqual(failure_state["evaluator_integrity_count"], 1)
            drift_fault = self.write_fault(plan, "evaluator_drift", {
                "returncode": drift.returncode,
                "evaluator_integrity_count": 1,
                "runtime_stall_count": failure_state["runtime_stall_count"],
            })

            fault_paths = [
                process_fault, missed_fault, duplicate_fault, state_fault,
                budget_fault, drift_fault, session_fault,
            ]
            duplicate_session = json.loads(session_paths[1].read_text())
            original_transitions = duplicate_session["new_transition_ids"]
            duplicate_session["new_transition_ids"] = event_ids[:1]
            session_paths[1].write_text(json.dumps(duplicate_session, indent=2))
            invalid_args = [
                "complete-acceptance-profile",
                "--plan-dir", str(plan),
                "--profile-id", "t008-short-bounded",
            ]
            for path in fault_paths:
                invalid_args += ["--fault-evidence", str(path)]
            for path in session_paths:
                invalid_args += ["--session-observation", str(path)]
            duplicate_rejected = self.call(*invalid_args, check=False)
            self.assertEqual(duplicate_rejected.returncode, 2)
            self.assertIn("duplicate applied transition", duplicate_rejected.stderr)
            duplicate_session["new_transition_ids"] = original_transitions
            session_paths[1].write_text(json.dumps(duplicate_session, indent=2))

            completed = json.loads(self.call(*invalid_args).stdout)
            self.assertEqual(completed["status"], "PASS")
            self.assertGreaterEqual(completed["measured_duration_seconds"], 1)
            self.assertEqual(completed["observed_session_restarts"], 2)
            self.assertEqual(completed["measured_max_controller_overlap"], 1)
            bounded = json.loads(self.call(
                "validate-acceptance-claim",
                "--plan-dir", str(plan),
                "--profile-id", "t008-short-bounded",
                "--claim-kind", "bounded_fault_acceptance",
                "--claimed-duration-seconds",
                str(completed["measured_duration_seconds"]),
            ).stdout)
            self.assertTrue(bounded["bounded_by_measured_evidence"])
            for claim_kind in (
                "long_stability", "seven_by_twenty_four", "full_cutover",
            ):
                rejected = self.call(
                    "validate-acceptance-claim",
                    "--plan-dir", str(plan),
                    "--profile-id", "t008-short-bounded",
                    "--claim-kind", claim_kind,
                    "--claimed-duration-seconds",
                    str(completed["measured_duration_seconds"]),
                    check=False,
                )
                self.assertEqual(rejected.returncode, 2)
            overclaim = self.call(
                "validate-acceptance-claim",
                "--plan-dir", str(plan),
                "--profile-id", "t008-short-bounded",
                "--claim-kind", "bounded_fault_acceptance",
                "--claimed-duration-seconds",
                str(completed["measured_duration_seconds"] + 1),
                check=False,
            )
            self.assertEqual(overclaim.returncode, 2)
            self.assertIn("exceeds", overclaim.stderr)
            (
                plan / "state" / "acceptance" / "observed"
                / "process_death.json"
            ).write_text('{"tampered":true}\n')
            evidence_drift = self.call(
                "validate-acceptance-claim",
                "--plan-dir", str(plan),
                "--profile-id", "t008-short-bounded",
                "--claim-kind", "bounded_fault_acceptance",
                "--claimed-duration-seconds",
                str(completed["measured_duration_seconds"]),
                check=False,
            )
            self.assertEqual(evidence_drift.returncode, 2)
            self.assertIn("evidence changed", evidence_drift.stderr)


if __name__ == "__main__":
    unittest.main()
