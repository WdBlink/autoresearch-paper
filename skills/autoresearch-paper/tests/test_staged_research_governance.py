#!/usr/bin/env python3
"""Focused REQ-051..REQ-066 rolling-stage governance regressions."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "references" / "scripts" / "harness-runtime.py"


def digest(value: object) -> str:
    if isinstance(value, str):
        raw = value.encode()
    else:
        raw = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()
    return hashlib.sha256(raw).hexdigest()


class StagedResearchGovernanceTests(unittest.TestCase):
    maxDiff = None

    def invoke(self, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [sys.executable, str(RUNTIME), *args],
            cwd=ROOT, text=True, capture_output=True,
        )
        if ok and proc.returncode != 0:
            self.fail(f"command failed: {proc.stderr}\n{proc.stdout}")
        if not ok and proc.returncode == 0:
            self.fail(f"command unexpectedly passed: {proc.stdout}")
        return proc

    def write(self, path: Path, value: object) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
        return path

    def contract(self) -> dict:
        fields = {
            "owner_identity_sha256": "owner",
            "development_evidence_profile_sha256": "development",
            "acceptance_evaluator_sha256": "gate",
            "development_validator_sha256": "validator",
            "admissibility_policy_sha256": "admissibility",
            "adoption_policy_sha256": "adoption",
            "scope_policy_sha256": "scope",
            "permission_policy_sha256": "permission",
            "evaluation_policy_sha256": "evaluation",
            "resource_policy_sha256": "resource",
            "authority_policy_sha256": "authority",
            "per_cycle_budget_sha256": "cycle-budget",
            "frontier_checkpoint_budget_sha256": "frontier-budget",
            "stop_and_reauthorization_policy_sha256": "stop",
            "external_transfer_profile_sha256": "transfer",
        }
        return {
            "schema_version": 1,
            "contract_version": "contract_v1",
            "authorization_receipt_id": "human_auth_1",
            "objective": {"id": "objective_1", "statement_sha256": digest("objective")},
            **{key: digest(value) for key, value in fields.items()},
        }

    def evaluation_profile(self) -> dict:
        return {
            "schema_version": 1,
            "profile_id": "evaluation_v1",
            "logical_gate_query_limit_per_candidate": 1,
            "private_split_policy_sha256": digest("rotating-private-splits"),
            "holdout_refresh_policy_sha256": digest("refresh-hidden-holdouts"),
            "transfer_audit_schedule_sha256": digest("scheduled-transfer-audit"),
            "external_suite_identity_sha256": digest("hidden-external-suite"),
        }

    def capacity(self, *, remaining: int = 8) -> dict:
        return {
            "schema_version": 1,
            "checkpoint_capacity": {
                name: {
                    "slot_id": f"slot_{name.lower().replace('-', '')}",
                    "reserved": 1,
                    "spent": 0,
                    "transferable": False,
                }
                for name in ("CP-01", "CP-02", "CP-04")
            },
            "retry_budget": {
                "remaining_attempts": 3,
                "per_attempt_call_limit": 1,
                "per_attempt_token_limit": 1000,
            },
            "remaining_calls": remaining,
            "mandatory_future_calls": 3,
        }

    def envelope(
        self, stage_id: str = "stage_1", *, source: str | None = None,
        incumbent: str | None = None, kind: str = "research",
    ) -> dict:
        result = {
            "schema_version": 1,
            "stage_id": stage_id,
            "contract_version": "contract_v1",
            "source_cycle_id": source,
            "incumbent_sha256": incumbent or digest("incumbent"),
            "stage_objective_sha256": digest(f"objective:{stage_id}"),
            "authorized_evidence_refs": [] if source is None else [f"evidence_{source}"],
            "allowed_intervention_sha256": digest("intervention"),
            "entry_criteria_sha256": digest("entry"),
            "exit_criteria_sha256": digest("exit"),
            "stage_budget_sha256": digest("stage-budget"),
            "required_report_schema_sha256": digest("report-schema"),
            "stage_kind": kind,
            "stage_budget_and_stop": {
                "profile_id": f"budget_{stage_id}",
                "time_seconds": 3600,
                "tool_calls": 20,
                "worker_tokens": 20000,
                "review_tokens": 8000,
                "retry_attempts": 3,
                "evaluation_calls": 1,
                "stop_policy_sha256": digest(
                    "plateau-rejection-risk-deadline-human-stop"
                ),
            },
        }
        return result

    def init_policy(self, plan: Path) -> None:
        self.invoke(
            "init-policy", "--plan-dir", str(plan),
            "--worker-model", "MiniMax-M3",
            "--worker-max-budget-usd", "1",
            "--frontier-model", "gpt-5.6-sol",
            "--frontier-reasoning-effort", "ultra",
            "--max-frontier-calls", "8",
            "--max-frontier-input-tokens", "100000",
            "--max-frontier-output-tokens", "50000",
        )

    def initialize(
        self, plan: Path, *, remaining: int = 8,
        envelope: dict | None = None,
    ) -> dict:
        plan.mkdir(parents=True, exist_ok=True)
        contract = self.write(plan / "inputs" / "contract.json", self.contract())
        stage = self.write(
            plan / "inputs" / "stage.json", envelope or self.envelope(),
        )
        evaluation = self.write(
            plan / "inputs" / "evaluation.json", self.evaluation_profile(),
        )
        capacity = self.write(
            plan / "inputs" / "capacity.json", self.capacity(remaining=remaining),
        )
        proc = self.invoke(
            "init-staged-research", "--plan-dir", str(plan),
            "--plan-id", "plan_staged", "--contract", str(contract),
            "--stage-envelope", str(stage),
            "--evaluation-profile", str(evaluation),
            "--checkpoint-capacity", str(capacity),
            "--incumbent-sha256", digest("incumbent"),
        )
        return json.loads(proc.stdout)

    def preflight(self, plan: Path, *, validators: dict | None = None) -> dict:
        values = validators or {
            "verdict_truth_table": "pass",
            "statistical_feasibility": "pass",
            "training_evaluation_matrix": "not_applicable",
            "conditional_state_machine": "pass",
            "budget_arithmetic": "pass",
            "current_stage_critical_path": "pass",
        }
        path = self.write(plan / "inputs" / "validators.json", values)
        args = [
            "preflight-staged-research", "--plan-dir", str(plan),
            "--validators", str(path),
            "--input-manifest-sha256", digest("inputs"),
            "--validator-versions-sha256", digest("validators-v1"),
        ]
        for transition in ("authorize", "develop", "gate", "record", "review"):
            args += ["--transition", transition]
        for checkpoint in ("CP-01", "CP-02", "CP-04"):
            args += ["--mandatory-checkpoint", checkpoint]
        proc = self.invoke(*args)
        return json.loads(proc.stdout)

    def authorize_fixture(self, plan: Path) -> None:
        """Represent an already controller-applied CP-01 in cycle-only tests."""
        state_path = plan / "state" / "staged_research" / "v1" / "state.json"
        state = json.loads(state_path.read_text())
        state["state"] = "STAGE_AUTHORIZED"
        state_path.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")

    def visible(self, plan: Path, call_id: str, role: str) -> dict:
        state = json.loads(
            (plan / "state" / "staged_research" / "v1" / "state.json").read_text()
        )
        manifest = digest(f"visible:{call_id}")
        events: list[dict] = []
        path = self.write(plan / "inputs" / f"{call_id}.json", {
            "schema_version": 1,
            "call_id": call_id,
            "role": role,
            "audit_revision": state["audit_revision"],
            "context_policy_version": "context_v1",
            "visible_message_manifest_sha256": manifest,
            "context_events": events,
            "context_event_manifest_sha256": digest(events),
            "source_artifact_refs": ["contract_v1", "stage_1"],
        })
        proc = self.invoke(
            "record-role-visible-state", "--plan-dir", str(plan),
            "--visible-state", str(path),
        )
        return json.loads(proc.stdout)

    def run_terminal_cycle(self, plan: Path, decision: str) -> dict:
        self.invoke(
            "freeze-stage-candidate", "--plan-dir", str(plan),
            "--candidate-sha256", digest(f"candidate:{decision}"),
            "--maturity", "full_experiment",
            "--development-evidence", f"development_{decision}",
        )
        self.invoke(
            "create-logical-gate-query", "--plan-dir", str(plan),
            "--logical-gate-query-id", f"gate_{decision}",
            "--candidate-sha256", digest(f"candidate:{decision}"),
            "--evaluator-sha256", self.contract()["acceptance_evaluator_sha256"],
        )
        self.invoke(
            "record-gate-transport-attempt", "--plan-dir", str(plan),
            "--logical-gate-query-id", f"gate_{decision}",
            "--transport-attempt-id", f"attempt_{decision}",
            "--budget-reservation-id", f"retry_budget_{decision}",
            "--status", "received",
        )
        receipt = self.write(plan / "inputs" / f"gate-{decision}.json", {
            "schema_version": 1,
            "gate_receipt_id": f"receipt_{decision}",
            "logical_gate_query_id": f"gate_{decision}",
            "candidate_sha256": digest(f"candidate:{decision}"),
            "decision": decision,
        })
        proc = self.invoke(
            "apply-logical-gate-decision", "--plan-dir", str(plan),
            "--logical-gate-query-id", f"gate_{decision}",
            "--gate-receipt", str(receipt),
            "--gate-receipt-id", f"receipt_{decision}",
            "--decision", decision,
            "--environment-version", "environment_v1",
            "--evaluator-version", "evaluator_v1",
            "--applicability", "same evaluator and environment",
            "--confidence", "high",
            "--validation-status", "validated",
            "--provenance-sha256", digest(f"provenance:{decision}"),
        )
        return json.loads(proc.stdout)

    def test_contract_preflight_and_cp01_bind_exactly_one_stage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.init_policy(plan)
            initialized = self.initialize(plan)
            preflight = self.preflight(plan)
            self.assertEqual(initialized["executable_stage_count"], 1)
            self.assertTrue(Path(preflight["preflight_path"]).is_file())
            root = plan / "state" / "staged_research" / "v1"
            artifacts = {
                "optimization_contract": root / "contracts" / "contract_v1.json",
                "first_stage_envelope": root / "stages" / "stage_1" / "envelope.json",
                "current_stage_preflight": root / "stages" / "stage_1" / "preflight.json",
                "checkpoint_capacity": root / "checkpoint-capacity.json",
            }
            args = [
                "create-frontier-request", "--plan-dir", str(plan),
                "--plan-id", "plan_staged", "--checkpoint", "CP-01",
                "--objective", "audit contract and first stage",
                "--decision-required", "approve_execution",
                "--max-input-tokens", "10000", "--max-output-tokens", "2000",
                "--request-id", "far_staged_cp01",
            ]
            for role, path in artifacts.items():
                args += ["--artifact", f"{path}::{role}"]
            created = json.loads(self.invoke(*args).stdout)
            request = json.loads(Path(created["request_path"]).read_text())
            self.assertEqual(request["evidence_profile_version"], 2)
            self.assertEqual(
                request["review_contract"]["kind"],
                "staged-contract-stage-review-v1",
            )
            self.assertEqual(
                {item["purpose"] for item in request["context_manifest"]},
                set(artifacts),
            )
            self.assertNotIn("figure_requirements", {
                item["purpose"] for item in request["context_manifest"]
            })

    def test_incomplete_contract_and_budget_shortfall_fail_before_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            plan.mkdir()
            bad_contract = self.contract()
            del bad_contract["authority_policy_sha256"]
            contract = self.write(plan / "contract.json", bad_contract)
            stage = self.write(plan / "stage.json", self.envelope())
            evaluation = self.write(plan / "evaluation.json", self.evaluation_profile())
            capacity = self.write(plan / "capacity.json", self.capacity(remaining=2))
            proc = self.invoke(
                "init-staged-research", "--plan-dir", str(plan),
                "--plan-id", "plan_bad", "--contract", str(contract),
                "--stage-envelope", str(stage),
                "--evaluation-profile", str(evaluation),
                "--checkpoint-capacity", str(capacity),
                "--incumbent-sha256", digest("incumbent"), ok=False,
            )
            self.assertIn("optimization contract is incomplete", proc.stderr)
            self.assertFalse((plan / "state" / "staged_research").exists())
            self.write(contract, self.contract())
            proc = self.invoke(
                "init-staged-research", "--plan-dir", str(plan),
                "--plan-id", "plan_bad", "--contract", str(contract),
                "--stage-envelope", str(stage),
                "--evaluation-profile", str(evaluation),
                "--checkpoint-capacity", str(capacity),
                "--incumbent-sha256", digest("incumbent"), ok=False,
            )
            self.assertIn("remaining_calls < mandatory_future_calls", proc.stderr)
            self.assertFalse((plan / "state" / "staged_research").exists())

    def test_preflight_typed_failure_and_no_global_dag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            validators = {
                "verdict_truth_table": "pass",
                "statistical_feasibility": "fail",
                "training_evaluation_matrix": "not_applicable",
                "conditional_state_machine": "pass",
                "budget_arithmetic": "pass",
                "current_stage_critical_path": "pass",
            }
            path = self.write(plan / "inputs" / "bad-validators.json", validators)
            proc = self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--validators", str(path),
                "--input-manifest-sha256", digest("inputs"),
                "--validator-versions-sha256", digest("validators"),
                "--mandatory-checkpoint", "CP-01",
                "--mandatory-checkpoint", "CP-02",
                "--mandatory-checkpoint", "CP-04",
                ok=False,
            )
            self.assertIn("statistical_feasibility", proc.stderr)
            envelope = self.envelope()
            envelope["depends_on"] = ["unknown_future_stage"]
            plan2 = Path(td) / "plan2"
            plan2.mkdir()
            paths = {
                "contract": self.write(plan2 / "contract.json", self.contract()),
                "stage": self.write(plan2 / "stage.json", envelope),
                "evaluation": self.write(
                    plan2 / "evaluation.json", self.evaluation_profile()
                ),
                "capacity": self.write(plan2 / "capacity.json", self.capacity()),
            }
            proc = self.invoke(
                "init-staged-research", "--plan-dir", str(plan2),
                "--plan-id", "plan_dag", "--contract", str(paths["contract"]),
                "--stage-envelope", str(paths["stage"]),
                "--evaluation-profile", str(paths["evaluation"]),
                "--checkpoint-capacity", str(paths["capacity"]),
                "--incumbent-sha256", digest("incumbent"), ok=False,
            )
            self.assertIn("speculative executable DAG", proc.stderr)

    def test_gate_truth_table_negative_evidence_and_escalation_block(self) -> None:
        for decision in ("accept", "reject", "escalate"):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as td:
                plan = Path(td) / "plan"
                self.initialize(plan)
                self.preflight(plan)
                self.authorize_fixture(plan)
                result = self.run_terminal_cycle(plan, decision)
                expected = (
                    digest(f"candidate:{decision}")
                    if decision == "accept" else digest("incumbent")
                )
                self.assertEqual(result["resulting_incumbent_sha256"], expected)
                self.assertEqual(
                    result["advancement_blocked"], decision == "escalate"
                )
                ledger = (
                    plan / "state" / "staged_research" / "v1"
                    / "evidence-ledger.jsonl"
                ).read_text()
                self.assertIn(f'"decision": "{decision}"', ledger)
                if decision in {"reject", "escalate"}:
                    self.assertIn('"maturity": "full_experiment"', ledger)

    def test_gate_query_is_single_and_transport_retries_are_independent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            self.preflight(plan)
            self.authorize_fixture(plan)
            candidate = digest("candidate")
            self.invoke(
                "freeze-stage-candidate", "--plan-dir", str(plan),
                "--candidate-sha256", candidate, "--maturity", "screened",
            )
            proc = self.invoke(
                "create-logical-gate-query", "--plan-dir", str(plan),
                "--logical-gate-query-id", "gate_1",
                "--candidate-sha256", candidate,
                "--evaluator-sha256", self.contract()["acceptance_evaluator_sha256"],
                "--requesting-role", "development", ok=False,
            )
            self.assertIn("Development must not query", proc.stderr)
            self.invoke(
                "create-logical-gate-query", "--plan-dir", str(plan),
                "--logical-gate-query-id", "gate_1",
                "--candidate-sha256", candidate,
                "--evaluator-sha256", self.contract()["acceptance_evaluator_sha256"],
            )
            for index, status in enumerate(("uncertain", "received"), 1):
                self.invoke(
                    "record-gate-transport-attempt", "--plan-dir", str(plan),
                    "--logical-gate-query-id", "gate_1",
                    "--transport-attempt-id", f"attempt_{index}",
                    "--budget-reservation-id", f"retry_{index}",
                    "--status", status,
                )
            query = json.loads(
                (plan / "state" / "staged_research" / "v1" / "stages"
                 / "stage_1" / "gate-query.json").read_text()
            )
            self.assertEqual(len(query["transport_attempts"]), 2)
            self.assertEqual(len({
                item["transport_attempt_id"] for item in query["transport_attempts"]
            }), 2)
            self.assertEqual(len({
                item["idempotency_key"] for item in query["transport_attempts"]
            }), 1)
            self.assertEqual(
                json.loads(
                    (plan / "state" / "staged_research" / "v1"
                     / "capacity-ledger.json").read_text()
                )["retry_budget"]["remaining_attempts"],
                1,
            )

    def test_visible_state_transfer_isolation_and_human_proposal_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            visible = self.visible(plan, "worker_call", "worker")
            self.assertTrue(Path(visible["path"]).is_file())
            external = self.evaluation_profile()["external_suite_identity_sha256"]
            state = json.loads(
                (plan / "state" / "staged_research" / "v1" / "state.json").read_text()
            )
            leak_path = self.write(plan / "inputs" / "leak.json", {
                "schema_version": 1,
                "call_id": "leak_call",
                "role": "worker",
                "audit_revision": state["audit_revision"],
                "context_policy_version": "context_v1",
                "visible_message_manifest_sha256": external,
                "context_events": [],
                "context_event_manifest_sha256": digest([]),
                "source_artifact_refs": [],
            })
            proc = self.invoke(
                "record-role-visible-state", "--plan-dir", str(plan),
                "--visible-state", str(leak_path), ok=False,
            )
            self.assertIn("external transfer suite leaked", proc.stderr)
            proposal = json.loads(self.invoke(
                "record-human-stage-input", "--plan-dir", str(plan),
                "--input-id", "proposal_1", "--kind", "proposal",
                "--content-sha256", digest("human proposal"),
            ).stdout)
            self.assertEqual(proposal["status"], "candidate_pool")
            self.assertFalse(proposal["authorization_created"])
            proc = self.invoke(
                "record-human-stage-input", "--plan-dir", str(plan),
                "--input-id", "feedback_1", "--kind", "feedback",
                "--content-sha256", digest("feedback"), ok=False,
            )
            self.assertIn("bind a named staged report", proc.stderr)

    def test_minimax_report_fresh_non_m3_review_and_one_next_stage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.init_policy(plan)
            self.initialize(plan)
            self.preflight(plan)
            self.authorize_fixture(plan)
            cycle = self.run_terminal_cycle(plan, "accept")
            worker_visible = self.visible(plan, "worker_terminal", "worker")
            report_path = self.write(plan / "inputs" / "report.json", {
                "schema_version": 1,
                "stage_report_id": "report_stage_1",
                "stage_cycle_id": "stage_1",
                "worker_identity": {
                    "agent": "worker_1", "model": "MiniMax-M3",
                    "provider": "MiniMax",
                },
                "role_visible_state_sha256": worker_visible["sha256"],
                "candidate_sha256": digest("candidate:accept"),
                "evidence_refs": ["evidence_stage_1"],
                "development_validator_receipts": ["validator_receipt_1"],
                "uncertainties": ["transfer not yet measured"],
                "proposed_next_questions": ["run bounded ablation"],
            })
            report = json.loads(self.invoke(
                "record-stage-report", "--plan-dir", str(plan),
                "--stage-report", str(report_path),
            ).stdout)
            reviewer_visible = self.visible(plan, "reviewer_terminal", "reviewer")
            policy_path = plan / "state" / "model_policy.json"
            state = json.loads(
                (plan / "state" / "staged_research" / "v1" / "state.json").read_text()
            )
            review_path = self.write(plan / "inputs" / "review.json", {
                "schema_version": 1,
                "review_receipt_id": "review_stage_1",
                "review_kind": "terminal_stage_report",
                "contract_version": "contract_v1",
                "stage_cycle_id": "stage_1",
                "stage_report_sha256": report["sha256"],
                "stage_envelope_sha256": state["active_stage_envelope_sha256"],
                "reviewer": {
                    "agent": "codex_reviewer",
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "ultra",
                    "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
                },
                "role_visible_state_sha256": reviewer_visible["sha256"],
                "recommendation": "accept",
                "findings_sha256": digest("bounded findings"),
            })
            self.invoke(
                "record-strong-stage-review", "--plan-dir", str(plan),
                "--review-receipt", str(review_path),
            )
            next_envelope = self.envelope(
                "stage_2", source="stage_1",
                incumbent=cycle["resulting_incumbent_sha256"],
            )
            next_path = self.write(plan / "inputs" / "stage-2.json", next_envelope)
            compiled = json.loads(self.invoke(
                "compile-next-stage", "--plan-dir", str(plan),
                "--stage-envelope", str(next_path),
                "--authorized-evidence", "evidence_stage_1",
            ).stdout)
            self.assertEqual(compiled["next_stage_id"], "stage_2")
            proc = self.invoke(
                "compile-next-stage", "--plan-dir", str(plan),
                "--stage-envelope", str(next_path),
                "--authorized-evidence", "evidence_stage_1", ok=False,
            )
            self.assertIn("requires a non-escalated recorded cycle", proc.stderr)

    def test_figure_inventory_freezes_only_at_figure_stage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.init_policy(plan)
            self.initialize(plan)  # non-figure first stage has no inventory
            self.preflight(plan)
            self.authorize_fixture(plan)
            cycle = self.run_terminal_cycle(plan, "accept")
            worker_visible = self.visible(plan, "worker_terminal", "worker")
            report_path = self.write(plan / "inputs" / "report.json", {
                "schema_version": 1, "stage_report_id": "report_stage_1",
                "stage_cycle_id": "stage_1",
                "worker_identity": {
                    "agent": "worker", "model": "MiniMax-M3", "provider": "MiniMax",
                },
                "role_visible_state_sha256": worker_visible["sha256"],
                "candidate_sha256": digest("candidate:accept"),
                "evidence_refs": ["evidence_stage_1"],
                "development_validator_receipts": ["dev_1"],
                "uncertainties": [], "proposed_next_questions": [],
            })
            report = json.loads(self.invoke(
                "record-stage-report", "--plan-dir", str(plan),
                "--stage-report", str(report_path),
            ).stdout)
            reviewer_visible = self.visible(plan, "review_terminal", "reviewer")
            policy = plan / "state" / "model_policy.json"
            state = json.loads(
                (plan / "state" / "staged_research" / "v1" / "state.json").read_text()
            )
            review_path = self.write(plan / "inputs" / "review.json", {
                "schema_version": 1, "review_receipt_id": "review_stage_1",
                "review_kind": "terminal_stage_report",
                "contract_version": "contract_v1", "stage_cycle_id": "stage_1",
                "stage_report_sha256": report["sha256"],
                "stage_envelope_sha256": state["active_stage_envelope_sha256"],
                "reviewer": {
                    "agent": "codex", "model": "gpt-5.6-sol",
                    "reasoning_effort": "ultra",
                    "policy_sha256": hashlib.sha256(policy.read_bytes()).hexdigest(),
                },
                "role_visible_state_sha256": reviewer_visible["sha256"],
                "recommendation": "accept", "findings_sha256": digest("figures"),
            })
            self.invoke(
                "record-strong-stage-review", "--plan-dir", str(plan),
                "--review-receipt", str(review_path),
            )
            inventory = self.write(plan / "inputs" / "figure-requirements.json", {
                "schema_version": 1, "plan_id": "plan_staged",
                "tier": "arxiv", "expected_figure_ids": ["fig_1"],
            })
            figure_stage = self.envelope(
                "stage_figures", source="stage_1",
                incumbent=cycle["resulting_incumbent_sha256"],
                kind="figure_production",
            )
            figure_stage["figure_requirements_sha256"] = hashlib.sha256(
                inventory.read_bytes()
            ).hexdigest()
            stage_path = self.write(plan / "inputs" / "figure-stage.json", figure_stage)
            proc = self.invoke(
                "compile-next-stage", "--plan-dir", str(plan),
                "--stage-envelope", str(stage_path),
                "--authorized-evidence", "evidence_stage_1", ok=False,
            )
            self.assertIn("freeze exact figure requirements", proc.stderr)
            compiled = json.loads(self.invoke(
                "compile-next-stage", "--plan-dir", str(plan),
                "--stage-envelope", str(stage_path),
                "--authorized-evidence", "evidence_stage_1",
                "--figure-requirements", str(inventory),
            ).stdout)
            self.assertEqual(compiled["next_stage_id"], "stage_figures")


if __name__ == "__main__":
    unittest.main()
