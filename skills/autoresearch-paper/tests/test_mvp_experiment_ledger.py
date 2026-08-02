#!/usr/bin/env python3
"""Contracts for the isolated MVP-0 P3 Experiment Receipt ledger."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_ROOT))
sys.path.insert(0, str(TEST_ROOT))

from mvp import experiment_ledger as ledger  # noqa: E402
import test_mvp_worker_adapter as p2_tests  # noqa: E402


class ExperimentLedgerContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.p2 = p2_tests.WorkerAdapterContracts(
            "test_init_binds_detached_worktree_and_immutable_session_manifest"
        )
        self.p2.setUp()
        self.ledger_dir = self.p2.root / "experiment-ledger"
        ledger.initialize_ledger(
            adapter_dir=self.p2.adapter_dir,
            ledger_dir=self.ledger_dir,
        )

    def tearDown(self) -> None:
        self.p2.tearDown()

    def dispatch(self, task_id: str, **environment: str) -> dict[str, object]:
        return self.p2.dispatch(
            task_id,
            env={"MVP0_FAKE_REPORT_COMMAND": "1", **environment},
        )

    def record(self, delivered: dict[str, object]) -> dict[str, object]:
        return ledger.record_turn(
            ledger_dir=self.ledger_dir,
            turn_receipt=Path(str(delivered["receipt_path"])),
        )

    def test_completed_turn_becomes_content_addressed_experiment_receipt(self) -> None:
        delivered = self.dispatch("task-one")
        recorded = self.record(delivered)
        self.assertFalse(recorded["already_recorded"])
        self.assertEqual(recorded["sequence"], 1)
        self.assertEqual(recorded["outcome"], "COMPLETED")

        receipt_path = Path(str(recorded["receipt_path"]))
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt_path.stat().st_mode & 0o777, 0o444)
        self.assertEqual(
            hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            recorded["receipt_sha256"],
        )
        self.assertEqual(receipt["experiment"]["id"], "exp-one")
        self.assertEqual(receipt["experiment"]["stage"], "BASELINE")
        self.assertEqual(receipt["task"]["config"]["optimizer"], "test-only")
        self.assertEqual(receipt["task"]["seeds"], [7])
        self.assertTrue(receipt["execution"]["planned_command_reported"])
        self.assertEqual(receipt["usage"]["input_tokens"], 40)
        self.assertTrue(receipt["usage"]["complete"])
        self.assertEqual(len(receipt["artifacts"]), 1)
        self.assertEqual(len(receipt["provenance"]["data_artifacts"]), 1)
        self.assertEqual(len(receipt["provenance"]["environment"]["artifacts"]), 1)
        for item in (
            *receipt["artifacts"],
            *receipt["provenance"]["input_artifacts"],
        ):
            blob = Path(item["blob_path"])
            self.assertEqual(blob.stat().st_mode & 0o777, 0o444)
            self.assertEqual(hashlib.sha256(blob.read_bytes()).hexdigest(), item["sha256"])

        verified = ledger.verify_ledger(ledger_dir=self.ledger_dir)
        self.assertTrue(verified["verified"])
        self.assertEqual(verified["record_count"], 1)
        self.assertEqual(verified["head_receipt_sha256"], recorded["receipt_sha256"])

    def test_append_log_is_ordered_hash_chain(self) -> None:
        first = self.record(self.dispatch("task-one"))
        second = self.record(self.dispatch("task-two", MVP0_FAKE_INPUT="0"))
        lines = [
            json.loads(line)
            for line in (self.ledger_dir / "experiment-receipts.jsonl").read_text().splitlines()
        ]
        self.assertEqual([line["sequence"] for line in lines], [1, 2])
        self.assertEqual(lines[0]["receipt_sha256"], first["receipt_sha256"])
        self.assertEqual(lines[1]["receipt_sha256"], second["receipt_sha256"])
        second_receipt = json.loads(Path(str(second["receipt_path"])).read_text())
        self.assertEqual(second_receipt["previous_receipt_sha256"], first["receipt_sha256"])
        self.assertEqual(ledger.verify_ledger(ledger_dir=self.ledger_dir)["record_count"], 2)

    def test_record_is_idempotent_for_exact_turn_receipt(self) -> None:
        delivered = self.dispatch("task-one")
        first = self.record(delivered)
        second = self.record(delivered)
        self.assertTrue(second["already_recorded"])
        self.assertEqual(second["receipt_sha256"], first["receipt_sha256"])
        self.assertEqual(
            len((self.ledger_dir / "experiment-receipts.jsonl").read_text().splitlines()),
            1,
        )

    def test_interrupted_index_append_reuses_exact_immutable_object(self) -> None:
        delivered = self.dispatch("task-one")
        with mock.patch.object(
            ledger,
            "_append_index",
            side_effect=ledger.LedgerError("simulated interrupted append"),
        ):
            with self.assertRaisesRegex(ledger.LedgerError, "interrupted append"):
                self.record(delivered)
        objects = list((self.ledger_dir / "objects" / "sha256").glob("*.json"))
        self.assertEqual(len(objects), 1)
        self.assertEqual((self.ledger_dir / "experiment-receipts.jsonl").read_text(), "")

        recovered = self.record(delivered)
        self.assertFalse(recovered["already_recorded"])
        self.assertEqual(Path(str(recovered["receipt_path"])).resolve(), objects[0].resolve())
        self.assertTrue(ledger.verify_ledger(ledger_dir=self.ledger_dir)["verified"])

    def test_verify_rejects_truncated_jsonl_suffix(self) -> None:
        self.record(self.dispatch("task-one"))
        self.record(self.dispatch("task-two", MVP0_FAKE_INPUT="0"))
        log = self.ledger_dir / "experiment-receipts.jsonl"
        log.write_text(log.read_text().splitlines()[0] + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ledger.LedgerError, "does not cover all terminal P2 turns"):
            ledger.verify_ledger(ledger_dir=self.ledger_dir)

    def test_verify_rejects_unindexed_receipt_object(self) -> None:
        payload = b'{}\n'
        digest = hashlib.sha256(payload).hexdigest()
        orphan = self.ledger_dir / "objects" / "sha256" / f"{digest}.json"
        orphan.write_bytes(payload)
        orphan.chmod(0o444)
        with self.assertRaisesRegex(ledger.LedgerError, "object inventory differs"):
            ledger.verify_ledger(ledger_dir=self.ledger_dir)

    def test_idempotent_record_does_not_hide_unindexed_object(self) -> None:
        delivered = self.dispatch("task-one")
        self.record(delivered)
        payload = b'{}\n'
        digest = hashlib.sha256(payload).hexdigest()
        orphan = self.ledger_dir / "objects" / "sha256" / f"{digest}.json"
        orphan.write_bytes(payload)
        orphan.chmod(0o444)
        with self.assertRaisesRegex(ledger.LedgerError, "unrelated unindexed object"):
            self.record(delivered)

    def test_turns_cannot_be_skipped_or_reordered(self) -> None:
        self.dispatch("task-one")
        second = self.dispatch("task-two")
        with self.assertRaisesRegex(ledger.LedgerError, "expected 1, received 2"):
            self.record(second)
        self.assertEqual((self.ledger_dir / "experiment-receipts.jsonl").read_text(), "")

    def test_completed_turn_without_frozen_command_evidence_is_rejected(self) -> None:
        delivered = self.p2.dispatch("task-one")
        with self.assertRaisesRegex(ledger.LedgerError, "successful frozen command"):
            self.record(delivered)
        self.assertEqual((self.ledger_dir / "experiment-receipts.jsonl").read_text(), "")

    def test_output_drift_before_recording_is_rejected(self) -> None:
        delivered = self.dispatch("task-one")
        (self.p2.worktree / "src" / "one.txt").write_text("drifted\n", encoding="utf-8")
        with self.assertRaisesRegex(ledger.LedgerError, "hash differs from bound provenance"):
            self.record(delivered)
        self.assertEqual((self.ledger_dir / "experiment-receipts.jsonl").read_text(), "")

    def test_failed_p2_turn_is_recorded_without_claiming_model_identity(self) -> None:
        delivered = self.p2.dispatch(
            "task-one",
            env={"MVP0_FAKE_MODEL": "claude-opus-4"},
        )
        self.assertEqual(delivered["outcome"], "FAILED")
        recorded = self.record(delivered)
        receipt = json.loads(Path(str(recorded["receipt_path"])).read_text())
        self.assertEqual(receipt["execution"]["status"], "FAILED")
        self.assertFalse(receipt["provenance"]["worker_model_verified"])
        self.assertIsNone(receipt["provenance"]["worker_result_path"])
        self.assertEqual(receipt["artifacts"], [])
        self.assertTrue(ledger.verify_ledger(ledger_dir=self.ledger_dir)["verified"])

    def test_archived_blob_tampering_breaks_full_replay(self) -> None:
        recorded = self.record(self.dispatch("task-one"))
        receipt = json.loads(Path(str(recorded["receipt_path"])).read_text())
        blob = Path(receipt["artifacts"][0]["blob_path"])
        blob.chmod(0o644)
        blob.write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(ledger.LedgerError, "blob is missing, mutable"):
            ledger.verify_ledger(ledger_dir=self.ledger_dir)

    def test_p2_result_tampering_breaks_provenance_replay(self) -> None:
        recorded = self.record(self.dispatch("task-one"))
        receipt = json.loads(Path(str(recorded["receipt_path"])).read_text())
        result_path = Path(receipt["provenance"]["worker_result_path"])
        result_path.chmod(0o644)
        result_path.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ledger.LedgerError, "Worker result is missing, mutable"):
            ledger.verify_ledger(ledger_dir=self.ledger_dir)

    def test_p2_input_archive_tampering_is_rejected_before_append(self) -> None:
        delivered = self.dispatch("task-one")
        turn = json.loads(Path(str(delivered["receipt_path"])).read_text())
        archive = json.loads(Path(turn["input_archive_path"]).read_text())
        blob = Path(archive["artifacts"][0]["blob_path"])
        blob.chmod(0o644)
        with self.assertRaisesRegex(ledger.LedgerError, "input archive blob is mutable"):
            self.record(delivered)

    def test_ledger_cannot_overlap_adapter_or_research_worktree(self) -> None:
        for target in (
            self.p2.adapter_dir / "ledger",
            self.p2.worktree / "ledger",
        ):
            with self.assertRaisesRegex(ledger.LedgerError, "must not overlap"):
                ledger.initialize_ledger(adapter_dir=self.p2.adapter_dir, ledger_dir=target)


if __name__ == "__main__":
    unittest.main()
