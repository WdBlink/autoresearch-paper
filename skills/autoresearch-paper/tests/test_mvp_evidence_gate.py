#!/usr/bin/env python3
"""Contracts for the isolated MVP-0 P4 deterministic Evidence Gate."""

from __future__ import annotations

import ast
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_ROOT))
sys.path.insert(0, str(TEST_ROOT))

from mvp import evidence_gate as gate  # noqa: E402
from mvp import experiment_ledger as ledger  # noqa: E402
import test_mvp_worker_adapter as p2_tests  # noqa: E402


class EvidenceGateContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.p2 = p2_tests.WorkerAdapterContracts(
            "test_init_binds_detached_worktree_and_immutable_session_manifest"
        )
        self.p2.setUp()
        self.ledger_dir = self.p2.root / "experiment-ledger"
        ledger.initialize_ledger(adapter_dir=self.p2.adapter_dir, ledger_dir=self.ledger_dir)
        delivered = self.p2.dispatch(
            "task-one",
            env={"MVP0_FAKE_REPORT_COMMAND": "1"},
        )
        self.recorded = ledger.record_turn(
            ledger_dir=self.ledger_dir,
            turn_receipt=Path(str(delivered["receipt_path"])),
        )
        self.receipt_digest = str(self.recorded["receipt_sha256"])
        self.receipt = json.loads(Path(str(self.recorded["receipt_path"])).read_text())
        self.store_dir = self.p2.root / "evidence-gate"
        gate.initialize_store(ledger_dir=self.ledger_dir, store_dir=self.store_dir)

    def tearDown(self) -> None:
        self.p2.tearDown()

    def report(
        self,
        name: str,
        *,
        quality: tuple[float, float, float] = (0.82, 0.78, 0.86),
        baseline_quality: tuple[float, float, float] = (0.70, 0.66, 0.74),
        latency: tuple[float, float, float] = (70.0, 65.0, 75.0),
        stop_rule: str | None = None,
    ) -> Path:
        artifact = self.receipt["artifacts"][0]
        rules = []
        for frozen in self.p2.ir["stop_rules"]:
            triggered = frozen["id"] == stop_rule
            evidence = []
            if triggered:
                evidence = [
                    {
                        "requirement": requirement,
                        "artifact_sha256": artifact["sha256"],
                    }
                    for requirement in frozen["evidence_required"]
                ]
            rules.append({
                "rule_id": frozen["id"],
                "triggered": triggered,
                "evidence": evidence,
            })
        value = {
            "schema_version": "evaluator-report/v1",
            "research_ir_sha256": self.p2.ir_digest,
            "experiment_receipt_sha256": self.receipt_digest,
            "candidate_id": self.receipt["task"]["id"],
            "baseline_id": "unit-baseline",
            "evaluator_implementation_sha256": self.p2.ir["evaluator_spec"][
                "implementation_sha256"
            ],
            "evaluated_at": self.receipt["execution"]["completed_at"],
            "execution": {
                "working_directory": self.p2.ir["evaluator_spec"]["working_directory"],
                "command_argv": self.p2.ir["evaluator_spec"]["command_argv"],
                "exit_code": 0,
            },
            "seeds": self.receipt["task"]["seeds"],
            "metrics": [
                {
                    "metric_id": "quality",
                    "unit": "ratio",
                    "confidence_level": 0.95,
                    "candidate": {
                        "estimate": quality[0],
                        "ci_lower": quality[1],
                        "ci_upper": quality[2],
                    },
                    "baseline": {
                        "estimate": baseline_quality[0],
                        "ci_lower": baseline_quality[1],
                        "ci_upper": baseline_quality[2],
                    },
                },
                {
                    "metric_id": "latency",
                    "unit": "ms",
                    "confidence_level": 0.95,
                    "candidate": {
                        "estimate": latency[0],
                        "ci_lower": latency[1],
                        "ci_upper": latency[2],
                    },
                    "baseline": {
                        "estimate": 80.0,
                        "ci_lower": 75.0,
                        "ci_upper": 85.0,
                    },
                },
            ],
            "stop_rules": rules,
            "source_artifacts": [
                {
                    "path": artifact["path"],
                    "sha256": artifact["sha256"],
                    "blob_path": artifact["blob_path"],
                    "purpose": "Raw evaluator input bound by the P3 receipt",
                }
            ],
        }
        return p2_tests.write_json(self.p2.root / name, value)

    def decide(self, report: Path | None) -> dict[str, object]:
        return gate.decide(
            store_dir=self.store_dir,
            experiment_receipt_sha256=self.receipt_digest,
            evaluator_report=report,
        )

    def test_keep_requires_thresholds_guardrails_and_baseline_noninferiority(self) -> None:
        result = self.decide(self.report("keep.json"))
        self.assertEqual(result["decision"], "KEEP")
        self.assertTrue(result["candidate_accepted"])
        decision = json.loads(Path(str(result["decision_path"])).read_text())
        self.assertEqual(decision["reason_codes"], ["CANDIDATE_MEETS_GATE"])
        self.assertEqual(len(decision["metric_assessments"]), 2)
        self.assertTrue(all(item["passed"] for item in decision["metric_assessments"]))
        self.assertTrue(gate.verify_store(store_dir=self.store_dir)["verified"])

    def test_primary_threshold_miss_pivots(self) -> None:
        result = self.decide(
            self.report("primary-miss.json", quality=(0.68, 0.65, 0.72))
        )
        self.assertEqual(result["decision"], "PIVOT")
        self.assertIn("PRIMARY_THRESHOLD_MISSED", result["reason_codes"])

    def test_baseline_comparison_miss_pivots_even_above_absolute_threshold(self) -> None:
        result = self.decide(
            self.report(
                "baseline-miss.json",
                quality=(0.82, 0.78, 0.86),
                baseline_quality=(0.90, 0.88, 0.92),
            )
        )
        self.assertEqual(result["decision"], "PIVOT")
        self.assertIn("BASELINE_COMPARISON_MISSED", result["reason_codes"])

    def test_guardrail_miss_pivots(self) -> None:
        result = self.decide(
            self.report("guardrail-miss.json", latency=(105.0, 101.0, 110.0))
        )
        self.assertEqual(result["decision"], "PIVOT")
        self.assertIn("GUARDRAIL_MISSED", result["reason_codes"])

    def test_sufficient_falsification_stops(self) -> None:
        result = self.decide(
            self.report("falsified.json", quality=(0.25, 0.20, 0.30))
        )
        self.assertEqual(result["decision"], "STOP")
        self.assertIn("CLAIM_FALSIFIED", result["reason_codes"])

    def test_frozen_stop_and_recompile_rules_have_distinct_decisions(self) -> None:
        stop = self.decide(
            self.report("stop-rule.json", stop_rule="catastrophic-safety")
        )
        self.assertEqual(stop["decision"], "STOP")
        self.assertIn("STOP_RULE_TRIGGERED", stop["reason_codes"])

        other_p2 = p2_tests.WorkerAdapterContracts(
            "test_init_binds_detached_worktree_and_immutable_session_manifest"
        )
        other_p2.setUp()
        original = (self.p2, self.ledger_dir, self.store_dir, self.receipt, self.receipt_digest)
        try:
            other_ledger = other_p2.root / "ledger"
            ledger.initialize_ledger(adapter_dir=other_p2.adapter_dir, ledger_dir=other_ledger)
            delivered = other_p2.dispatch(
                "task-one", env={"MVP0_FAKE_REPORT_COMMAND": "1"}
            )
            recorded = ledger.record_turn(
                ledger_dir=other_ledger,
                turn_receipt=Path(str(delivered["receipt_path"])),
            )
            other_store = other_p2.root / "gate"
            gate.initialize_store(ledger_dir=other_ledger, store_dir=other_store)
            self.p2 = other_p2
            self.ledger_dir = other_ledger
            self.store_dir = other_store
            self.receipt = json.loads(Path(str(recorded["receipt_path"])).read_text())
            self.receipt_digest = str(recorded["receipt_sha256"])
            recompile = self.decide(
                self.report("recompile-rule.json", stop_rule="contract-drift")
            )
            self.assertEqual(recompile["decision"], "RECOMPILE")
            self.assertIn("RECOMPILE_RULE_TRIGGERED", recompile["reason_codes"])
        finally:
            self.p2, self.ledger_dir, self.store_dir, self.receipt, self.receipt_digest = original
            other_p2.tearDown()

    def test_planned_evaluator_requires_recompile_without_report(self) -> None:
        manifest, _ledger_manifest, ir = gate._store_manifest(self.store_dir)  # noqa: SLF001
        planned = copy.deepcopy(ir)
        planned["evaluator_spec"]["status"] = "PLANNED"
        planned["evaluator_spec"]["implementation_sha256"] = None
        receipt, receipt_path, prefix = gate._receipt(  # noqa: SLF001
            store_manifest=manifest,
            digest=self.receipt_digest,
        )
        decision = gate._build_decision(  # noqa: SLF001
            store_manifest=manifest,
            ir=planned,
            receipt=receipt,
            receipt_path=receipt_path,
            receipt_digest=self.receipt_digest,
            prefix=prefix,
            report=None,
            report_path=None,
            report_digest=None,
        )
        self.assertEqual(decision["decision"], "RECOMPILE")
        self.assertEqual(decision["reason_codes"], ["EVALUATOR_REQUIRES_FREEZE"])

    def test_budget_exhaustion_stops_but_preserves_candidate_assessment(self) -> None:
        manifest, _ledger_manifest, ir = gate._store_manifest(self.store_dir)  # noqa: SLF001
        bounded = copy.deepcopy(ir)
        bounded["budget"]["max_experiments"] = 1
        receipt, receipt_path, prefix = gate._receipt(  # noqa: SLF001
            store_manifest=manifest,
            digest=self.receipt_digest,
        )
        report_path = self.report("budget.json")
        report, report_digest = gate._prepare_report(  # noqa: SLF001
            path=report_path,
            ledger_dir=self.ledger_dir,
            ir=bounded,
            ir_digest=manifest["research_ir_sha256"],
            receipt=receipt,
            receipt_digest=self.receipt_digest,
        )
        decision = gate._build_decision(  # noqa: SLF001
            store_manifest=manifest,
            ir=bounded,
            receipt=receipt,
            receipt_path=receipt_path,
            receipt_digest=self.receipt_digest,
            prefix=prefix,
            report=report,
            report_path=report_path,
            report_digest=report_digest,
        )
        self.assertEqual(decision["decision"], "STOP")
        self.assertTrue(decision["candidate_accepted"])
        self.assertIn("EXPERIMENT_BUDGET_EXHAUSTED", decision["reason_codes"])

    def test_insufficient_seeds_cannot_trigger_falsification_or_keep(self) -> None:
        ir = copy.deepcopy(self.p2.ir)
        ir["metric_contract"]["primary_metric"]["acceptance"]["minimum_seeds"] = 2
        report = json.loads(self.report("underpowered.json", quality=(0.25, 0.20, 0.30)).read_text())
        metrics, falsification = gate._assess_metrics(ir, report)  # noqa: SLF001
        self.assertFalse(next(item for item in metrics if item["role"] == "PRIMARY")["passed"])
        self.assertFalse(falsification[0]["evidence_sufficient"])
        self.assertFalse(falsification[0]["triggered"])

    def test_report_lineage_or_unbound_source_is_rejected(self) -> None:
        wrong = json.loads(self.report("wrong.json").read_text())
        wrong["experiment_receipt_sha256"] = "0" * 64
        path = p2_tests.write_json(self.p2.root / "wrong-receipt.json", wrong)
        with self.assertRaisesRegex(gate.GateError, "identity or frozen execution"):
            self.decide(path)

        wrong = json.loads(self.report("wrong-source-base.json").read_text())
        wrong["source_artifacts"][0]["path"] = "unbound.json"
        path = p2_tests.write_json(self.p2.root / "wrong-source.json", wrong)
        with self.assertRaisesRegex(gate.GateError, "not bound by the Experiment Receipt"):
            self.decide(path)

    def test_one_query_rule_rejects_report_switching(self) -> None:
        report = self.report("first.json")
        first = self.decide(report)
        repeated = self.decide(report)
        self.assertTrue(repeated["already_decided"])
        self.assertEqual(repeated["decision_sha256"], first["decision_sha256"])
        with self.assertRaisesRegex(gate.GateError, "one-query Gate record"):
            self.decide(self.report("second.json", quality=(0.68, 0.65, 0.72)))

    def test_gate_decisions_cannot_skip_p3_receipts(self) -> None:
        delivered = self.p2.dispatch(
            "task-two",
            env={"MVP0_FAKE_REPORT_COMMAND": "1"},
        )
        second = ledger.record_turn(
            ledger_dir=self.ledger_dir,
            turn_receipt=Path(str(delivered["receipt_path"])),
        )
        with self.assertRaisesRegex(gate.GateError, "expected 1, received 2"):
            gate.decide(
                store_dir=self.store_dir,
                experiment_receipt_sha256=str(second["receipt_sha256"]),
                evaluator_report=None,
            )

    def test_decision_or_evaluator_blob_tampering_breaks_replay(self) -> None:
        result = self.decide(self.report("keep.json"))
        decision_path = Path(str(result["decision_path"]))
        decision_path.chmod(0o644)
        decision_path.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(gate.GateError, "decision object is missing, mutable"):
            gate.verify_store(store_dir=self.store_dir)

    def test_evaluator_implementation_blob_tampering_breaks_replay(self) -> None:
        self.decide(self.report("keep.json"))
        digest = self.p2.ir["evaluator_spec"]["implementation_sha256"]
        blob = self.store_dir / "blobs" / "sha256" / digest
        blob.chmod(0o644)
        blob.write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(gate.GateError, "archived evaluator implementation"):
            gate.verify_store(store_dir=self.store_dir)

    def test_interrupted_record_publication_recovers_exact_objects(self) -> None:
        report = self.report("keep.json")
        original = gate._publish_json  # noqa: SLF001

        def interrupt_record(path: Path, value: object) -> None:
            if "by-experiment-receipt" in path.parts:
                raise gate.GateError("simulated record interruption")
            original(path, value)

        with mock.patch.object(gate, "_publish_json", side_effect=interrupt_record):
            with self.assertRaisesRegex(gate.GateError, "record interruption"):
                self.decide(report)
        self.assertEqual(len(list((self.store_dir / "reports" / "sha256").iterdir())), 1)
        self.assertEqual(len(list((self.store_dir / "decisions" / "sha256").iterdir())), 1)
        recovered = self.decide(report)
        self.assertFalse(recovered["already_decided"])
        self.assertTrue(gate.verify_store(store_dir=self.store_dir)["verified"])

    def test_blocked_receipt_pivots_until_failure_budget_is_exhausted(self) -> None:
        manifest, _ledger_manifest, ir = gate._store_manifest(self.store_dir)  # noqa: SLF001
        receipt, receipt_path, prefix = gate._receipt(  # noqa: SLF001
            store_manifest=manifest,
            digest=self.receipt_digest,
        )
        blocked = copy.deepcopy(receipt)
        blocked["execution"]["status"] = "BLOCKED"
        blocked_prefix = copy.deepcopy(prefix)
        blocked_prefix[-1]["receipt"]["execution"]["status"] = "BLOCKED"
        decision = gate._build_decision(  # noqa: SLF001
            store_manifest=manifest,
            ir=ir,
            receipt=blocked,
            receipt_path=receipt_path,
            receipt_digest=self.receipt_digest,
            prefix=blocked_prefix,
            report=None,
            report_path=None,
            report_digest=None,
        )
        self.assertEqual(decision["decision"], "PIVOT")
        self.assertEqual(decision["reason_codes"], ["RECEIPT_BLOCKED"])

        exhausted = copy.deepcopy(ir)
        exhausted["budget"]["max_failed_experiments"] = 1
        decision = gate._build_decision(  # noqa: SLF001
            store_manifest=manifest,
            ir=exhausted,
            receipt=blocked,
            receipt_path=receipt_path,
            receipt_digest=self.receipt_digest,
            prefix=blocked_prefix,
            report=None,
            report_path=None,
            report_digest=None,
        )
        self.assertEqual(decision["decision"], "STOP")
        self.assertIn("FAILURE_BUDGET_EXHAUSTED", decision["reason_codes"])

    def test_p4_module_does_not_import_legacy_harness(self) -> None:
        source = (SKILL_ROOT / "mvp" / "evidence_gate.py").read_text()
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        self.assertFalse(any("harness" in name or "references" in name for name in imports))


if __name__ == "__main__":
    unittest.main()
