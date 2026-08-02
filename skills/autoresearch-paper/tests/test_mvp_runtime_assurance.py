#!/usr/bin/env python3
"""Contracts for the MVP-0 P6 L0/L1/L2 runtime-assurance closure."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from mvp import automation_registration as automation  # noqa: E402
from mvp import runtime_assurance as assurance  # noqa: E402


THREAD_ID = "019fc053-ab31-7333-b5da-85b03372ec24"
CONTROLLER_ID = "mvp0-supervisor-0123456789abcdef"


class FakeLaunchd:
    def __init__(self) -> None:
        self.loaded: dict[str, bytes] = {}
        self.events: list[tuple[str, str]] = []

    def is_loaded(self, label: str) -> bool:
        return label in self.loaded

    def load(self, label: str, plist_path: Path) -> None:
        self.loaded[label] = plist_path.read_bytes()
        self.events.append(("load", label))

    def unload(self, label: str) -> None:
        self.loaded.pop(label, None)
        self.events.append(("unload", label))


class FakeProcesses:
    def __init__(self) -> None:
        self.live: dict[int, str] = {}
        self.events: list[tuple[str, int]] = []

    def identity(self, pid: int) -> str | None:
        return self.live.get(pid)

    def terminate(self, pid: int) -> None:
        self.events.append(("TERM", pid))
        self.live.pop(pid, None)

    def kill(self, pid: int) -> None:
        self.events.append(("KILL", pid))
        self.live.pop(pid, None)


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


class RuntimeAssuranceContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = self.root / "run" / "supervisor"
        self.store.mkdir(parents=True)
        self.automation_path = self.root / "automations" / CONTROLLER_ID / "automation.toml"
        self.automation_path.parent.mkdir(parents=True)
        self.automation_bytes = automation.render_thread_automation(
            controller_id=CONTROLLER_ID,
            name="AutoResearch MVP0 · unit",
            prompt="Run one exact P6 tick.",
            target_thread_id=THREAD_ID,
            created_at_ms=1785632400000,
        ).encode()
        self.automation_path.write_bytes(self.automation_bytes)
        self.backend = FakeLaunchd()
        self.processes = FakeProcesses()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def bootstrap(self) -> dict[str, object]:
        return assurance.bootstrap_assurance(
            store_dir=self.store,
            controller_id=CONTROLLER_ID,
            target_thread_id=THREAD_ID,
            l1_automation_path=self.automation_path,
            l0_interval_seconds=300,
            l1_interval_seconds=600,
            l2_interval_seconds=60,
            heartbeat_stale_seconds=900,
            scheduler=self.backend,
            launch_agents_dir=self.root / "LaunchAgents",
            python_executable=Path(sys.executable),
            now="2026-08-02T08:00:00Z",
        )

    def test_bootstrap_binds_loaded_distinct_l0_l1_l2_and_runs_probes(self) -> None:
        result = self.bootstrap()
        receipt = json.loads(Path(result["activation_receipt_path"]).read_text())
        self.assertTrue(self.backend.is_loaded(receipt["l0"]["scheduler_label"]))
        self.assertNotEqual(receipt["l0"]["scheduler_label"], receipt["l1"]["automation_id"])
        self.assertNotEqual(receipt["l0"]["command_sha256"], receipt["l1"]["command_sha256"])
        self.assertEqual(receipt["probes"]["l0"]["model_dispatches"], 0)
        self.assertTrue(receipt["probes"]["l0"]["l1_was_removed"])
        self.assertTrue(receipt["probes"]["l0"]["l1_restored"])
        self.assertEqual(receipt["probes"]["l1"]["model_dispatches"], 0)
        self.assertFalse(receipt["probes"]["l1"]["due"])
        self.assertEqual(receipt["probes"]["l2"]["model_dispatches"], 0)
        self.assertTrue(receipt["probes"]["l2"]["contract_verified"])
        self.assertEqual(self.automation_path.read_bytes(), self.automation_bytes)
        self.assertEqual(Path(result["activation_receipt_path"]).stat().st_mode & 0o777, 0o444)

    def test_bootstrap_rejects_unsafe_health_interval_without_mutation(self) -> None:
        before = tree_digest(self.root)
        with self.assertRaisesRegex(assurance.AssuranceError, "health interval"):
            assurance.bootstrap_assurance(
                store_dir=self.store,
                controller_id=CONTROLLER_ID,
                target_thread_id=THREAD_ID,
                l1_automation_path=self.automation_path,
                l0_interval_seconds=500,
                l1_interval_seconds=600,
                l2_interval_seconds=60,
                heartbeat_stale_seconds=900,
                scheduler=self.backend,
                launch_agents_dir=self.root / "LaunchAgents",
                python_executable=Path(sys.executable),
                now="2026-08-02T08:00:00Z",
            )
        self.assertEqual(tree_digest(self.root), before)
        self.assertEqual(self.backend.events, [])

    def test_l0_restores_missing_exact_l1_and_deduplicates_healthy_observation(self) -> None:
        result = self.bootstrap()
        self.automation_path.unlink()
        recovered = assurance.run_l0_health_tick(
            store_dir=self.store,
            scheduler=self.backend,
            now="2026-08-02T08:05:00Z",
        )
        self.assertEqual(recovered["action"], "RESTORED_L1")
        self.assertEqual(recovered["model_dispatches"], 0)
        self.assertEqual(self.automation_path.read_bytes(), self.automation_bytes)
        first = assurance.run_l0_health_tick(
            store_dir=self.store,
            scheduler=self.backend,
            now="2026-08-02T08:10:00Z",
        )
        second = assurance.run_l0_health_tick(
            store_dir=self.store,
            scheduler=self.backend,
            now="2026-08-02T08:11:00Z",
        )
        self.assertEqual(first["action"], "HEALTHY")
        self.assertTrue(second["deduplicated"])
        receipt = assurance.verify_activation(
            store_dir=self.store,
            scheduler=self.backend,
            now="2026-08-02T08:11:00Z",
        )
        self.assertEqual(receipt["activation_receipt_path"], result["activation_receipt_path"])

    def test_l0_refuses_unknown_l1_drift(self) -> None:
        self.bootstrap()
        self.automation_path.write_text("version = 1\nid = \"foreign\"\n", encoding="utf-8")
        observed = assurance.run_l0_health_tick(
            store_dir=self.store,
            scheduler=self.backend,
            now="2026-08-02T08:05:00Z",
        )
        self.assertEqual(observed["action"], "RECOVERY_PROPOSED")
        self.assertEqual(observed["reason"], "L1_DRIFT")
        self.assertIn(b"foreign", self.automation_path.read_bytes())

    def test_pause_prevents_l0_reactivation_and_resume_revalidates_closure(self) -> None:
        self.bootstrap()
        paused = assurance.pause_runtime(
            store_dir=self.store,
            scheduler=self.backend,
            authority_id="owner/unit-pause",
            now="2026-08-02T08:05:00Z",
        )
        self.assertEqual(paused["status"], "PAUSED")
        self.assertIn(b'status = "PAUSED"', self.automation_path.read_bytes())
        observation = assurance.run_l0_health_tick(
            store_dir=self.store,
            scheduler=self.backend,
            now="2026-08-02T08:06:00Z",
        )
        self.assertEqual(observation["action"], "NOOP")
        resumed = assurance.resume_runtime(
            store_dir=self.store,
            scheduler=self.backend,
            authority_id="owner/unit-resume",
            now="2026-08-02T08:07:00Z",
        )
        self.assertEqual(resumed["status"], "ACTIVE")
        self.assertEqual(self.automation_path.read_bytes(), self.automation_bytes)
        self.assertEqual(
            assurance.verify_activation(
                store_dir=self.store,
                scheduler=self.backend,
                now="2026-08-02T08:07:00Z",
            )["status"],
            "VERIFIED",
        )

    def test_l2_heartbeat_is_identity_bound_sequenced_and_idempotent(self) -> None:
        self.bootstrap()
        binding = assurance.bind_worker(
            store_dir=self.store,
            adapter_id="mvp0-worker-unit",
            turn_id="turn-000001",
            session_id="11111111-1111-4111-8111-111111111111",
            worker_model="MiniMax-M3",
            task_contract_sha256="a" * 64,
            process_id=4242,
            process_identity="pid-4242-start-7",
            now="2026-08-02T08:01:00Z",
        )
        first = assurance.record_worker_heartbeat(
            store_dir=self.store,
            worker_binding_path=Path(binding["worker_binding_path"]),
            sequence=1,
            session_id="11111111-1111-4111-8111-111111111111",
            process_id=4242,
            process_identity="pid-4242-start-7",
            task_contract_sha256="a" * 64,
            observed_at="2026-08-02T08:02:00Z",
        )
        duplicate = assurance.record_worker_heartbeat(
            store_dir=self.store,
            worker_binding_path=Path(binding["worker_binding_path"]),
            sequence=1,
            session_id="11111111-1111-4111-8111-111111111111",
            process_id=4242,
            process_identity="pid-4242-start-7",
            task_contract_sha256="a" * 64,
            observed_at="2026-08-02T08:02:00Z",
        )
        self.assertFalse(first["already_applied"])
        self.assertTrue(duplicate["already_applied"])
        with self.assertRaisesRegex(assurance.AssuranceError, "sequence"):
            assurance.record_worker_heartbeat(
                store_dir=self.store,
                worker_binding_path=Path(binding["worker_binding_path"]),
                sequence=3,
                session_id="11111111-1111-4111-8111-111111111111",
                process_id=4242,
                process_identity="pid-4242-start-7",
                task_contract_sha256="a" * 64,
                observed_at="2026-08-02T08:03:00Z",
            )
        with self.assertRaisesRegex(assurance.AssuranceError, "session"):
            assurance.record_worker_heartbeat(
                store_dir=self.store,
                worker_binding_path=Path(binding["worker_binding_path"]),
                sequence=2,
                session_id="22222222-2222-4222-8222-222222222222",
                process_id=4242,
                process_identity="pid-4242-start-7",
                task_contract_sha256="a" * 64,
                observed_at="2026-08-02T08:03:00Z",
            )

    def test_inspection_is_read_only_and_exposes_stale_l2(self) -> None:
        self.bootstrap()
        binding = assurance.bind_worker(
            store_dir=self.store,
            adapter_id="mvp0-worker-unit",
            turn_id="turn-000001",
            session_id="11111111-1111-4111-8111-111111111111",
            worker_model="MiniMax-M3",
            task_contract_sha256="a" * 64,
            process_id=4242,
            process_identity="pid-4242-start-7",
            now="2026-08-02T08:01:00Z",
        )
        assurance.record_worker_heartbeat(
            store_dir=self.store,
            worker_binding_path=Path(binding["worker_binding_path"]),
            sequence=1,
            session_id="11111111-1111-4111-8111-111111111111",
            process_id=4242,
            process_identity="pid-4242-start-7",
            task_contract_sha256="a" * 64,
            observed_at="2026-08-02T08:02:00Z",
        )
        before = tree_digest(self.store)
        snapshot = assurance.inspect_runtime(
            store_dir=self.store,
            scheduler=self.backend,
            processes=self.processes,
            now="2026-08-02T08:20:00Z",
        )
        after = tree_digest(self.store)
        self.assertEqual(before, after)
        self.assertEqual(snapshot["l2"]["freshness"], "STALE")
        self.assertEqual(snapshot["scientific_state_mutations"], 0)

    def test_stop_is_ordered_exact_once_and_preserves_research_artifacts(self) -> None:
        result = self.bootstrap()
        receipt = json.loads(Path(result["activation_receipt_path"]).read_text())
        self.processes.live[4242] = "pid-4242-start-7"
        assurance.bind_worker(
            store_dir=self.store,
            adapter_id="mvp0-worker-unit",
            turn_id="turn-000001",
            session_id="11111111-1111-4111-8111-111111111111",
            worker_model="MiniMax-M3",
            task_contract_sha256="a" * 64,
            process_id=4242,
            process_identity="pid-4242-start-7",
            now="2026-08-02T08:01:00Z",
        )
        research_artifact = self.root / "run" / "accepted-result.json"
        research_artifact.write_text('{"accepted":true}\n', encoding="utf-8")
        first = assurance.shutdown_runtime(
            store_dir=self.store,
            scheduler=self.backend,
            processes=self.processes,
            authority_id="owner/unit-stop",
            now="2026-08-02T08:30:00Z",
        )
        second = assurance.shutdown_runtime(
            store_dir=self.store,
            scheduler=self.backend,
            processes=self.processes,
            authority_id="owner/unit-stop",
            now="2026-08-02T08:31:00Z",
        )
        self.assertEqual(first["shutdown_receipt_sha256"], second["shutdown_receipt_sha256"])
        l0_event = ("unload", receipt["l0"]["scheduler_label"])
        self.assertIn(l0_event, self.backend.events)
        self.assertLess(self.backend.events.index(l0_event), len(self.backend.events))
        self.assertIn(("TERM", 4242), self.processes.events)
        self.assertTrue(research_artifact.is_file())
        self.assertFalse(first["artifacts_deleted"])

    def test_stop_refuses_reused_process_identity(self) -> None:
        self.bootstrap()
        self.processes.live[4242] = "pid-4242-reused"
        assurance.bind_worker(
            store_dir=self.store,
            adapter_id="mvp0-worker-unit",
            turn_id="turn-000001",
            session_id="11111111-1111-4111-8111-111111111111",
            worker_model="MiniMax-M3",
            task_contract_sha256="a" * 64,
            process_id=4242,
            process_identity="pid-4242-start-7",
            now="2026-08-02T08:01:00Z",
        )
        stopped = assurance.shutdown_runtime(
            store_dir=self.store,
            scheduler=self.backend,
            processes=self.processes,
            authority_id="owner/unit-stop",
            now="2026-08-02T08:30:00Z",
        )
        self.assertEqual(stopped["status"], "SHUTDOWN_WITH_RESIDUALS")
        self.assertEqual(stopped["residuals"][0]["reason"], "PROCESS_IDENTITY_MISMATCH")
        self.assertEqual(self.processes.events, [])

    def test_stop_recovers_after_crash_following_l0_disable(self) -> None:
        result = self.bootstrap()
        receipt = json.loads(Path(result["activation_receipt_path"]).read_text())
        with self.assertRaisesRegex(assurance.AssuranceError, "simulated crash"):
            assurance.shutdown_runtime(
                store_dir=self.store,
                scheduler=self.backend,
                processes=self.processes,
                authority_id="owner/unit-stop",
                now="2026-08-02T08:30:00Z",
                simulate_crash_after="L0_DISABLED",
            )
        self.assertFalse(self.backend.is_loaded(receipt["l0"]["scheduler_label"]))
        stopped = assurance.shutdown_runtime(
            store_dir=self.store,
            scheduler=self.backend,
            processes=self.processes,
            authority_id="owner/unit-stop",
            now="2026-08-02T08:31:00Z",
        )
        self.assertEqual(stopped["status"], "SHUTDOWN")
        self.assertEqual(
            [event for event in self.backend.events if event == ("unload", receipt["l0"]["scheduler_label"])],
            [("unload", receipt["l0"]["scheduler_label"]), ("unload", receipt["l0"]["scheduler_label"])],
        )


if __name__ == "__main__":
    unittest.main()
