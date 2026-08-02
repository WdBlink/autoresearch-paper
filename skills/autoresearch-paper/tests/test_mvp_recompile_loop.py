#!/usr/bin/env python3
"""Contracts for the isolated MVP-0 P5 Recompile Loop."""

from __future__ import annotations

import ast
import copy
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_ROOT))
sys.path.insert(0, str(TEST_ROOT))

from mvp import recompile_loop as p5  # noqa: E402
from mvp import research_compiler as compiler  # noqa: E402
from mvp import delegated_review  # noqa: E402
from mvp import experiment_ledger as ledger  # noqa: E402
import test_mvp_evidence_gate as p4_tests  # noqa: E402
import test_mvp_worker_adapter as p2_tests  # noqa: E402


def plus_seconds(value: str, seconds: int) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed + timedelta(seconds=seconds)).astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


class RecompileLoopContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.p4 = p4_tests.EvidenceGateContracts(
            "test_primary_threshold_miss_pivots"
        )
        self.p4.setUp()
        self.decision_result = self.p4.decide(
            self.p4.report("p5-pivot.json", quality=(0.68, 0.65, 0.72))
        )
        self.decision = json.loads(
            Path(str(self.decision_result["decision_path"])).read_text()
        )
        self.store_dir = self.p4.p2.root / "recompile-loop"
        p5.initialize_store(gate_store=self.p4.store_dir, store_dir=self.store_dir)

    def tearDown(self) -> None:
        self.p4.tearDown()

    def analysis_value(self) -> dict[str, object]:
        artifact = self.p4.receipt["artifacts"][0]
        return {
            "schema_version": "failure-analysis/v1",
            "analyzed_at": self.decision["decided_at"],
            "analyst": "codex/recompile-analyst",
            "research_ir_sha256": self.p4.p2.ir_digest,
            "evidence_gate_decision_sha256": self.decision_result["decision_sha256"],
            "experiment_receipt_sha256": self.p4.receipt_digest,
            "gate_decision": self.decision["decision"],
            "gate_reason_codes": self.decision["reason_codes"],
            "problem": "The primary confidence bound remains below the frozen acceptance threshold.",
            "attempted_directions": [
                {
                    "experiment_receipt_sha256": self.p4.receipt_digest,
                    "experiment_id": self.p4.receipt["experiment"]["id"],
                    "outcome": self.p4.receipt["execution"]["status"],
                    "interpretation": "The bounded intervention completed but did not clear the primary threshold.",
                    "evidence_sha256s": [artifact["sha256"]],
                }
            ],
            "evidence": [
                {
                    "path": artifact["path"],
                    "sha256": artifact["sha256"],
                    "blob_path": artifact["blob_path"],
                    "supports": "The exact completed experiment artifact used by the frozen evaluator.",
                }
            ],
            "causal_hypotheses": [
                {
                    "hypothesis": "The first intervention is too weak to improve the lower confidence bound.",
                    "confidence": "MEDIUM",
                    "disconfirming_test": "Run the frozen second experiment and observe a passing lower bound.",
                }
            ],
            "new_questions": [
                "Does the second frozen intervention resolve the observed primary-metric deficit?"
            ],
            "uncertainties": [
                "One completed experiment cannot distinguish optimization weakness from variance."
            ],
        }

    def publish_analysis(self, value: dict[str, object] | None = None) -> dict[str, object]:
        path = p2_tests.write_json(
            self.p4.p2.root / "failure-analysis.json",
            self.analysis_value() if value is None else value,
        )
        return p5.publish_analysis(store_dir=self.store_dir, analysis_path=path)

    def request_value(
        self,
        analysis_result: dict[str, object],
        *,
        disposition: str = "RECOMPILE_IR",
    ) -> dict[str, object]:
        analysis = self.analysis_value()
        recompile = disposition == "RECOMPILE_IR"
        return {
            "schema_version": "recompile-request/v1",
            "requested_at": analysis["analyzed_at"],
            "requested_by": "codex/recompile-compiler",
            "failure_analysis_sha256": analysis_result["analysis_sha256"],
            "evidence_gate_decision_sha256": self.decision_result["decision_sha256"],
            "parent_freeze_receipt_sha256": self.p4.p2.freeze_digest,
            "current_ir": {
                "ir_id": self.p4.p2.ir["ir_id"],
                "version": self.p4.p2.ir["version"],
                "sha256": self.p4.p2.ir_digest,
            },
            "disposition": disposition,
            "problem": analysis["problem"],
            "attempted_receipt_sha256s": [self.p4.receipt_digest],
            "evidence_sha256s": [analysis["evidence"][0]["sha256"]],
            "new_questions": analysis["new_questions"],
            "recommendation": (
                "Compile a versioned experiment plan that tests the remaining causal uncertainty."
                if recompile
                else "Continue with the already-frozen second experiment without changing the IR."
            ),
            "requested_changes": (
                [
                    {
                        "path": "/experiment_plan",
                        "rationale": "The next experiment hypothesis must incorporate the observed failure mode.",
                        "expected_effect": "The revised experiment isolates optimization weakness from variance.",
                    }
                ]
                if recompile
                else []
            ),
            "retained_constraints": [
                "/central_claim",
                "/metric_contract",
                "/evaluator_spec",
            ],
            "continuation_experiment_id": None if recompile else "exp-two",
        }

    def publish_request(
        self,
        analysis_result: dict[str, object],
        *,
        disposition: str = "RECOMPILE_IR",
        value: dict[str, object] | None = None,
    ) -> dict[str, object]:
        request = self.request_value(analysis_result, disposition=disposition)
        path = p2_tests.write_json(
            self.p4.p2.root / "recompile-request.json",
            request if value is None else value,
        )
        return p5.publish_request(store_dir=self.store_dir, request_path=path)

    def candidate(self) -> dict[str, object]:
        candidate = copy.deepcopy(self.p4.p2.ir)
        candidate["version"] = 2
        candidate["parent_ir_sha256"] = self.p4.p2.ir_digest
        candidate["experiment_plan"][1]["hypothesis"] = (
            "The second versioned intervention distinguishes optimization weakness from variance under frozen controls."
        )
        return candidate

    def test_recompile_request_and_candidate_enter_p1_human_review(self) -> None:
        analysis = self.publish_analysis()
        request = self.publish_request(analysis)
        candidate_path = p2_tests.write_json(
            self.p4.p2.root / "candidate-ir-v2.json", self.candidate()
        )
        compiled = p5.compile_candidate(
            store_dir=self.store_dir,
            request_sha256=str(request["request_sha256"]),
            candidate_ir=candidate_path,
            author="codex/recompile-compiler",
        )
        self.assertEqual(compiled["stage"], "AWAITING_HUMAN_CRITIQUE")
        self.assertEqual(json.loads(Path(compiled["research_ir_path"]).read_text())["version"], 2)
        self.assertTrue(p5.verify_store(store_dir=self.store_dir)["verified"])

    def test_continue_current_ir_selects_only_ready_unattempted_experiment(self) -> None:
        analysis = self.publish_analysis()
        request = self.publish_request(analysis, disposition="CONTINUE_CURRENT_IR")
        self.assertEqual(request["stage"], "CONTINUE_CURRENT_IR")
        self.assertEqual(request["continuation_experiment_id"], "exp-two")
        with self.assertRaisesRegex(p5.RecompileError, "does not compile"):
            p5.compile_candidate(
                store_dir=self.store_dir,
                request_sha256=str(request["request_sha256"]),
                candidate_ir=p2_tests.write_json(
                    self.p4.p2.root / "unused-candidate.json", self.candidate()
                ),
                author="codex/recompile-compiler",
            )

    def test_unbound_or_incomplete_analysis_evidence_is_rejected(self) -> None:
        value = self.analysis_value()
        value["evidence"][0]["sha256"] = "a" * 64
        value["attempted_directions"][0]["evidence_sha256s"] = ["a" * 64]
        with self.assertRaisesRegex(p5.RecompileError, "outside the P3 prefix"):
            self.publish_analysis(value)

    def test_one_analysis_and_request_per_gate_decision(self) -> None:
        analysis = self.publish_analysis()
        changed = self.analysis_value()
        changed["problem"] = "A different post-hoc interpretation attempts to replace the frozen analysis."
        with self.assertRaisesRegex(p5.RecompileError, "different analysis"):
            self.publish_analysis(changed)
        self.publish_request(analysis)
        alternate = self.request_value(analysis)
        alternate["recommendation"] = "A different recommendation attempts to replace the first immutable request."
        with self.assertRaisesRegex(p5.RecompileError, "different request"):
            self.publish_request(analysis, value=alternate)

    def test_recompile_request_cannot_omit_analysis_lineage(self) -> None:
        analysis = self.publish_analysis()
        request = self.request_value(analysis)
        request["new_questions"] = ["A substituted question that is absent from the analysis."]
        with self.assertRaisesRegex(p5.RecompileError, "omits or changes"):
            self.publish_request(analysis, value=request)

    def test_candidate_version_parent_and_changed_roots_are_closed(self) -> None:
        analysis = self.publish_analysis()
        request = self.publish_request(analysis)
        wrong_parent = self.candidate()
        wrong_parent["parent_ir_sha256"] = "b" * 64
        with self.assertRaisesRegex(p5.RecompileError, "version or project identity"):
            p5.compile_candidate(
                store_dir=self.store_dir,
                request_sha256=str(request["request_sha256"]),
                candidate_ir=p2_tests.write_json(self.p4.p2.root / "wrong-parent.json", wrong_parent),
                author="codex/recompile-compiler",
            )
        expanded = self.candidate()
        expanded["central_claim"]["statement"] += " This undeclared expansion is forbidden."
        with self.assertRaisesRegex(p5.RecompileError, "changed roots differ"):
            p5.compile_candidate(
                store_dir=self.store_dir,
                request_sha256=str(request["request_sha256"]),
                candidate_ir=p2_tests.write_json(self.p4.p2.root / "expanded.json", expanded),
                author="codex/recompile-compiler",
            )

    def test_human_reviewed_ir_v2_freeze_binds_full_p5_lineage(self) -> None:
        analysis = self.publish_analysis()
        request = self.publish_request(analysis)
        compiled = p5.compile_candidate(
            store_dir=self.store_dir,
            request_sha256=str(request["request_sha256"]),
            candidate_ir=p2_tests.write_json(
                self.p4.p2.root / "candidate.json", self.candidate()
            ),
            author="codex/recompile-compiler",
        )
        base_time = json.loads(Path(compiled["compiler_proposal_path"]).read_text())[
            "recorded_at"
        ]
        critique_input = p2_tests.write_json(
            self.p4.p2.root / "v2-critique.json",
            {
                "summary": "Require the revised experiment to name the decisive observation.",
                "verdict": "REVISE",
                "findings": [
                    {
                        "finding_id": "decisive-observation",
                        "severity": "major",
                        "path": "$.experiment_plan[1].expected_observation",
                        "message": "The expected observation is not sufficiently decisive.",
                        "required_change": "Name the outcome that separates the causal hypotheses.",
                    }
                ],
            },
        )
        critique = compiler.critique(
            proposal_path=Path(compiled["compiler_proposal_path"]),
            critique_path=critique_input,
            store=self.p4.p2.store,
            reviewer="owner/v2-critic",
            recorded_at=plus_seconds(base_time, 1),
        )
        revision_input = p2_tests.write_json(
            self.p4.p2.root / "v2-revision.json",
            {
                "summary": "Make the second experiment's decisive observation explicit.",
                "addressed_finding_ids": ["decisive-observation"],
                "changes": [
                    {
                        "op": "replace",
                        "path": "/experiment_plan/1/expected_observation",
                        "value": "A passing paired lower bound rules out optimization weakness under frozen variance controls.",
                    }
                ],
            },
        )
        revision = compiler.revise(
            proposal_path=Path(compiled["compiler_proposal_path"]),
            critique_record_path=Path(critique["critique_path"]),
            revision_path=revision_input,
            store=self.p4.p2.store,
            author="codex/v2-reviser",
            recorded_at=plus_seconds(base_time, 2),
        )
        frozen = compiler.freeze(
            revision_path=Path(revision["revision_path"]),
            store=self.p4.p2.store,
            approved_by="owner/v2-approver",
            approval_scope="OWNER_REVIEWED",
            approval_note="Approved IR v2 after reviewing request, critique closure, and retained constraints.",
            approved_at=plus_seconds(base_time, 3),
        )
        bound = p5.bind_freeze(
            store_dir=self.store_dir,
            proposal_sha256=str(compiled["proposal_sha256"]),
            freeze_receipt=Path(frozen["freeze_receipt_path"]),
        )
        self.assertEqual(bound["stage"], "FROZEN")
        self.assertEqual(bound["child_ir_version"], 2)
        self.assertEqual(p5.verify_store(store_dir=self.store_dir)["stage"], "FROZEN")

    def test_delegated_execution_only_freeze_binds_review_into_p5(self) -> None:
        analysis = self.publish_analysis()
        request = self.publish_request(analysis)
        candidate = copy.deepcopy(self.p4.p2.ir)
        candidate["version"] = 2
        candidate["parent_ir_sha256"] = self.p4.p2.ir_digest
        candidate["experiment_plan"][0]["id"] = "exp-one-recovery"
        candidate["experiment_plan"][0]["intervention"] += " Revalidate the failed scaffold."
        candidate["experiment_plan"][1]["depends_on"] = ["exp-one-recovery"]
        compiled = p5.compile_candidate(
            store_dir=self.store_dir,
            request_sha256=str(request["request_sha256"]),
            candidate_ir=p2_tests.write_json(
                self.p4.p2.root / "delegated-candidate.json", candidate
            ),
            author="codex/recompile-compiler",
        )
        base_time = json.loads(Path(compiled["compiler_proposal_path"]).read_text())[
            "recorded_at"
        ]
        critique = compiler.critique(
            proposal_path=Path(compiled["compiler_proposal_path"]),
            critique_path=p2_tests.write_json(
                self.p4.p2.root / "delegated-critique.json",
                {
                    "summary": "Independent frontier review accepts the execution-plan-only successor.",
                    "verdict": "ACCEPT",
                    "findings": [],
                },
            ),
            store=self.p4.p2.store,
            reviewer="codex/frontier-reviewer",
            recorded_at=plus_seconds(base_time, 1),
        )
        revision = compiler.confirm_revision(
            proposal_path=Path(compiled["compiler_proposal_path"]),
            critique_record_path=Path(critique["critique_path"]),
            store=self.p4.p2.store,
            author="codex/recompile-revision",
            summary="Confirm the accepted execution-only successor without modifying its bytes.",
            recorded_at=plus_seconds(base_time, 2),
        )
        review = delegated_review.publish_review(
            store_dir=self.store_dir / "delegated-reviews",
            parent_ir_path=(
                self.p4.p2.store
                / "objects"
                / "sha256"
                / f"{self.p4.p2.ir_digest}.json"
            ),
            child_ir_path=Path(compiled["research_ir_path"]),
            request_path=Path(request["request_path"]),
            proposal_path=Path(compiled["proposal_path"]),
            compiler_author="codex/recompile-compiler",
            reviewer="codex/frontier-reviewer",
            revision_author="codex/recompile-revision",
            approver="codex/frontier-approver",
            verdict="ACCEPT",
            summary="Independent review confirms only the authorized experiment plan changed.",
            reviewed_at=plus_seconds(base_time, 3),
        )
        frozen = compiler.freeze(
            revision_path=Path(revision["revision_path"]),
            store=self.p4.p2.store,
            approved_by="codex/frontier-approver",
            approval_scope="DELEGATED_ENGINEERING_REVIEW",
            approval_note="Approve the execution-only successor under its replayable delegated review.",
            approved_at=plus_seconds(base_time, 4),
            delegated_review_receipt=Path(review["review_receipt_path"]),
        )
        bound = p5.bind_freeze(
            store_dir=self.store_dir,
            proposal_sha256=str(compiled["proposal_sha256"]),
            freeze_receipt=Path(frozen["freeze_receipt_path"]),
        )
        bound_value = json.loads(Path(bound["freeze_path"]).read_text())

        self.assertEqual(bound["stage"], "FROZEN")
        self.assertEqual(bound_value["schema_version"], "recompile-freeze/v2")
        self.assertEqual(
            bound_value["delegated_review_sha256"], review["review_receipt_sha256"]
        )
        self.assertEqual(p5.verify_store(store_dir=self.store_dir)["stage"], "FROZEN")

    def test_keep_decision_cannot_initialize_p5(self) -> None:
        other = p4_tests.EvidenceGateContracts(
            "test_keep_requires_thresholds_guardrails_and_baseline_noninferiority"
        )
        other.setUp()
        try:
            other.decide(other.report("keep-for-p5.json"))
            with self.assertRaisesRegex(p5.RecompileError, "PIVOT or RECOMPILE"):
                p5.initialize_store(
                    gate_store=other.store_dir,
                    store_dir=other.p2.root / "forbidden-p5",
                )
        finally:
            other.tearDown()

    def test_recompile_gate_cannot_continue_current_ir(self) -> None:
        other = p4_tests.EvidenceGateContracts(
            "test_frozen_stop_and_recompile_rules_have_distinct_decisions"
        )
        other.setUp()
        try:
            decision_result = other.decide(
                other.report("forced-recompile.json", stop_rule="contract-drift")
            )
            decision = json.loads(Path(decision_result["decision_path"]).read_text())
            store = other.p2.root / "recompile-only"
            p5.initialize_store(gate_store=other.store_dir, store_dir=store)
            original = (self.p4, self.decision_result, self.decision, self.store_dir)
            self.p4, self.decision_result, self.decision, self.store_dir = (
                other,
                decision_result,
                decision,
                store,
            )
            try:
                analysis = self.publish_analysis()
                with self.assertRaisesRegex(p5.RecompileError, "Only a PIVOT"):
                    self.publish_request(analysis, disposition="CONTINUE_CURRENT_IR")
            finally:
                self.p4, self.decision_result, self.decision, self.store_dir = original
        finally:
            other.tearDown()

    def test_tampering_breaks_replay(self) -> None:
        result = self.publish_analysis()
        path = Path(str(result["analysis_path"]))
        path.chmod(0o644)
        with self.assertRaisesRegex(p5.RecompileError, "mutable"):
            p5.verify_store(store_dir=self.store_dir)

    def test_frozen_p5_snapshot_survives_later_p4_append(self) -> None:
        delivered = self.p4.p2.dispatch(
            "task-two", env={"MVP0_FAKE_REPORT_COMMAND": "1"}
        )
        recorded = ledger.record_turn(
            ledger_dir=self.p4.ledger_dir,
            turn_receipt=Path(str(delivered["receipt_path"])),
        )
        self.p4.receipt_digest = str(recorded["receipt_sha256"])
        self.p4.receipt = json.loads(Path(str(recorded["receipt_path"])).read_text())
        self.p4.decide(
            self.p4.report("later-pivot.json", quality=(0.67, 0.64, 0.71))
        )
        verified = p5.verify_store(store_dir=self.store_dir)
        self.assertTrue(verified["verified"])
        self.assertEqual(verified["stage"], "READY_FOR_ANALYSIS")

    def test_p5_module_does_not_import_legacy_harness_or_runtimes(self) -> None:
        tree = ast.parse((SKILL_ROOT / "mvp" / "recompile_loop.py").read_text())
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertFalse(
            imported
            & {
                "harness-runtime",
                "run-claude-harness",
                "dashboard_server",
                "launchd",
            }
        )


if __name__ == "__main__":
    unittest.main()
