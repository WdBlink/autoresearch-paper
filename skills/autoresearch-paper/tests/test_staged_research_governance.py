#!/usr/bin/env python3
"""Focused REQ-051..REQ-066 rolling-stage governance regressions."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
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

    def test_immutable_atomic_publication_freezes_before_replace(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "atomic_publication_runtime", RUNTIME,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            json_path = root / "authority.json"
            bytes_path = root / "authority.bin"
            json_value = {"schema_version": 1, "authority": "terminal"}
            bytes_value = b"terminal-authority\x00bytes"
            real_replace = runtime.os.replace
            real_chmod = Path.chmod
            observations: list[tuple[int, int]] = []
            published: set[Path] = set()
            post_publication_chmod: list[Path] = []

            def observed_replace(source: object, destination: object) -> None:
                source_path = Path(source)
                destination_path = Path(destination)
                source_mode = source_path.stat().st_mode & 0o777
                real_replace(source, destination)
                destination_mode = destination_path.stat().st_mode & 0o777
                observations.append((source_mode, destination_mode))
                published.add(destination_path)

            def observed_chmod(path: Path, mode: int, *args: object, **kwargs: object) -> None:
                if path in published:
                    post_publication_chmod.append(path)
                real_chmod(path, mode, *args, **kwargs)

            runtime.os.replace = observed_replace
            Path.chmod = observed_chmod
            try:
                runtime.atomic_write_json(json_path, json_value, immutable=True)
                runtime.atomic_write_bytes(bytes_path, bytes_value, immutable=True)
            finally:
                runtime.os.replace = real_replace
                Path.chmod = real_chmod
            self.assertEqual(observations, [(0o444, 0o444), (0o444, 0o444)])
            self.assertEqual(post_publication_chmod, [])
            expected_json = (
                json.dumps(json_value, indent=2, sort_keys=True) + "\n"
            ).encode()
            self.assertEqual(json_path.read_bytes(), expected_json)
            self.assertEqual(bytes_path.read_bytes(), bytes_value)
            self.assertEqual(
                hashlib.sha256(json_path.read_bytes()).hexdigest(),
                runtime.atomic_json_sha256(json_value),
            )

    def invoke(
        self, *args: str, ok: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [sys.executable, str(RUNTIME), *args],
            cwd=ROOT, text=True, capture_output=True, env=env,
        )
        if ok and proc.returncode != 0:
            self.fail(f"command failed: {proc.stderr}\n{proc.stdout}")
        if not ok and proc.returncode == 0:
            self.fail(f"command unexpectedly passed: {proc.stdout}")
        return proc

    def write(self, path: Path, value: object) -> Path:
        if isinstance(value, dict) and {
            "stage_id", "stage_objective_sha256", "stage_budget_and_stop",
            "required_report_schema_sha256",
        }.issubset(value):
            plan = path.parent
            cursor = path.parent
            while cursor.parent != cursor:
                if (cursor / "resource_manifest.json").exists():
                    plan = cursor
                    break
                cursor = cursor.parent
            materials_root = plan / "control" / "review-materials" / value["stage_id"]
            digest_targets = {
                "stage_objective": (value, "stage_objective_sha256"),
                "allowed_intervention": (value, "allowed_intervention_sha256"),
                "entry_criteria": (value, "entry_criteria_sha256"),
                "exit_criteria": (value, "exit_criteria_sha256"),
                "stage_budget": (value, "stage_budget_sha256"),
                "required_report_schema": (value, "required_report_schema_sha256"),
                "stop_policy": (
                    value["stage_budget_and_stop"], "stop_policy_sha256",
                ),
            }
            manifest = []
            for purpose, (container, field) in digest_targets.items():
                material = materials_root / f"{purpose}.txt"
                material.parent.mkdir(parents=True, exist_ok=True)
                if material.exists():
                    material.chmod(0o644)
                material.write_text(f"{value['stage_id']}:{purpose}")
                material.chmod(0o444)
                container[field] = hashlib.sha256(material.read_bytes()).hexdigest()
                manifest.append({
                    "id": f"material_{value['stage_id']}_{purpose}",
                    "path": str(material.relative_to(plan)),
                    "sha256": container[field],
                    "purpose": purpose,
                })
            for purpose in (
                "execution_plan", "acceptance_evaluator",
                "risk_and_stop_rules", "figure_strategy",
            ):
                material = materials_root / f"{purpose}.txt"
                if material.exists():
                    material.chmod(0o644)
                material.write_text(f"{value['stage_id']}:{purpose}")
                material.chmod(0o444)
                manifest.append({
                    "id": f"material_{value['stage_id']}_{purpose}",
                    "path": str(material.relative_to(plan)),
                    "sha256": hashlib.sha256(material.read_bytes()).hexdigest(),
                    "purpose": purpose,
                })
            evaluator_implementation = materials_root / "source_inventory_validator.py"
            if evaluator_implementation.exists():
                evaluator_implementation.chmod(0o644)
            evaluator_implementation.write_bytes(
                (ROOT / "references" / "scripts" / "source_inventory_validator.py").read_bytes()
            )
            evaluator_implementation.chmod(0o444)
            manifest.append({
                "id": f"material_{value['stage_id']}_evaluator_implementation",
                "path": str(evaluator_implementation.relative_to(plan)),
                "sha256": hashlib.sha256(
                    evaluator_implementation.read_bytes()
                ).hexdigest(),
                "purpose": "evaluator_implementation",
            })
            evaluator_conformance = materials_root / "evaluator_conformance.txt"
            if evaluator_conformance.exists():
                evaluator_conformance.chmod(0o644)
            evaluator_conformance.write_text("source-inventory-validator/2 conformance")
            evaluator_conformance.chmod(0o444)
            manifest.append({
                "id": f"material_{value['stage_id']}_evaluator_conformance",
                "path": str(evaluator_conformance.relative_to(plan)),
                "sha256": hashlib.sha256(evaluator_conformance.read_bytes()).hexdigest(),
                "purpose": "evaluator_conformance",
            })
            report_validator_source = (
                ROOT / "references" / "scripts" / "stage_report_validator.py"
            )
            report_validator = materials_root / "stage_report_validator.py"
            if report_validator.exists():
                report_validator.chmod(0o644)
            report_validator.write_bytes(report_validator_source.read_bytes())
            report_validator.chmod(0o444)
            manifest.append({
                "id": f"material_{value['stage_id']}_stage_report_validator",
                "path": str(report_validator.relative_to(plan)),
                "sha256": hashlib.sha256(report_validator.read_bytes()).hexdigest(),
                "purpose": "stage_report_validator_implementation",
            })
            conformance_result = json.loads(subprocess.run(
                [sys.executable, str(report_validator_source), "--conformance"],
                check=True, text=True, capture_output=True,
            ).stdout)
            report_conformance = materials_root / "stage-report-conformance.json"
            if report_conformance.exists():
                report_conformance.chmod(0o644)
            report_conformance.write_text(
                json.dumps(conformance_result, sort_keys=True, indent=2) + "\n"
            )
            report_conformance.chmod(0o444)
            manifest.append({
                "id": f"material_{value['stage_id']}_stage_report_conformance",
                "path": str(report_conformance.relative_to(plan)),
                "sha256": hashlib.sha256(report_conformance.read_bytes()).hexdigest(),
                "purpose": "stage_report_validator_conformance",
            })
            if value.get("stage_kind") == "figure_production":
                expected = value.get("figure_requirements_sha256")
                candidate = next((
                    item for item in plan.rglob("*.json")
                    if item != path and item.is_file() and not item.is_symlink()
                    and hashlib.sha256(item.read_bytes()).hexdigest() == expected
                ), None)
                if candidate is None:
                    candidate = materials_root / "figure_requirements.json"
                    candidate.write_text('{"figures":[]}')
                candidate.chmod(0o444)
                value["figure_requirements_sha256"] = hashlib.sha256(
                    candidate.read_bytes()
                ).hexdigest()
                manifest.append({
                    "id": f"material_{value['stage_id']}_figure_requirements",
                    "path": str(candidate.relative_to(plan)),
                    "sha256": value["figure_requirements_sha256"],
                    "purpose": "figure_requirements",
                })
            value["review_material_manifest"] = manifest
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
            "authorization_receipt_id": "har_owner_auth_1",
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
            "gate_metric": "score",
            "gate_operator": "ge",
            "gate_threshold": 0.5,
            "gate_escalation_margin": 0.05,
        }

    def inactive_observation_evaluation_profile(self) -> dict:
        return {
            "schema_version": 1,
            "profile_id": "observation_evaluation_v1",
            "applicable": False,
            "reason": "observation_only_no_logical_gate",
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

    def capacity_v2(self, *, workers: int = 2, cp03: bool = False) -> dict:
        checkpoints = {
            name: {
                "slot_id": f"slot_{name.lower().replace('-', '')}",
                "reserved": 1, "spent": 0, "transferable": False,
            }
            for name in ("CP-01", "CP-02", "CP-04")
        }
        if cp03:
            checkpoints["CP-03"] = {
                "slot_id": "slot_cp03", "reserved": 1,
                "spent": 0, "transferable": False,
            }
        return {
            "schema_version": 2,
            "worker_dispatch_capacity": {
                "authorized_calls": workers,
                "spent_calls": 0,
                "remaining_calls": workers,
            },
            "stage_review_capacity": {
                "authorized_calls": 2, "spent_calls": 0,
                "remaining_calls": 2, "transferable": False,
            },
            "checkpoint_capacity": checkpoints,
            "retry_budget": {
                "remaining_attempts": 3,
                "per_attempt_call_limit": 1,
                "per_attempt_token_limit": 1000,
            },
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
                "review_tokens": 30000,
                "retry_attempts": 3,
                "evaluation_calls": 1,
                "worker_dispatches": 2,
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
            "--max-frontier-input-tokens", "1600000",
            "--max-frontier-output-tokens", "100000",
        )

    def test_policy_rejects_plan_budget_that_only_funds_one_call(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            rejected = self.invoke(
                "init-policy", "--plan-dir", str(plan),
                "--worker-model", "MiniMax-M3",
                "--worker-max-budget-usd", "1",
                "--frontier-model", "gpt-5.6-sol",
                "--max-frontier-calls", "4",
                "--max-frontier-input-tokens", "150000",
                "--max-frontier-output-tokens", "5000",
                ok=False,
            )
            self.assertIn(
                "cannot fund every declared ChatGPT call", rejected.stderr,
            )
            self.assertFalse((plan / "state" / "model_policy.json").exists())

    def initialize(
        self, plan: Path, *, remaining: int = 8,
        envelope: dict | None = None,
        noncanonical_contract: bool = False,
        capacity_value: dict | None = None,
        continuation_stage_id: str | None = None,
        development_validator_sha256: str | None = None,
        evaluation_profile_value: dict | None = None,
    ) -> dict:
        plan.mkdir(parents=True, exist_ok=True)
        if not (plan / "state" / "model_policy.json").exists():
            self.init_policy(plan)
        self.write(plan / "resource_manifest.json", {
            "schema_version": 1, "plan_id": "plan_staged",
            "resources": [],
        })
        gate_evaluator = self.write(plan / "inputs" / "gate-evaluator.json", {
            "schema_version": 1, "kind": "isolated-gate-evaluator-v1",
            "metric": "score",
        })
        contract_value = self.contract()
        contract_value["acceptance_evaluator_sha256"] = hashlib.sha256(
            gate_evaluator.read_bytes()
        ).hexdigest()
        if development_validator_sha256 is not None:
            contract_value["development_validator_sha256"] = (
                development_validator_sha256
            )
        contract = self.write(plan / "inputs" / "contract.json", contract_value)
        if noncanonical_contract:
            contract.write_text(json.dumps(contract_value, separators=(",", ":")))
        stage = self.write(
            plan / "inputs" / "stage.json", envelope or self.envelope(),
        )
        evaluation = self.write(
            plan / "inputs" / "evaluation.json",
            evaluation_profile_value or (
                self.inactive_observation_evaluation_profile()
                if (envelope or self.envelope())["stage_budget_and_stop"][
                    "evaluation_calls"
                ] == 0
                else self.evaluation_profile()
            ),
        )
        capacity = self.write(
            plan / "inputs" / "capacity.json",
            capacity_value or self.capacity(remaining=remaining),
        )
        key = plan / "owner.key"
        key.write_bytes(b"x" * 32)
        key.chmod(0o600)
        create_args = [
            "create-human-action", "--plan-dir", str(plan),
            "--plan-id", "plan_staged", "--action", "authorize_contract",
            "--key-file", str(key), "--expires-in", "3600",
            "--record-id", "har_owner_auth_1", "--actor", "research-owner",
            "--contract-version", "contract_v1", "--stage-id",
            (envelope or self.envelope())["stage_id"],
            "--contract-sha256", hashlib.sha256(contract.read_bytes()).hexdigest(),
            "--stage-envelope-sha256", hashlib.sha256(stage.read_bytes()).hexdigest(),
        ]
        if continuation_stage_id is not None:
            create_args += [
                "--continuation-stage-id", continuation_stage_id,
                "--continuation-stage-limit", "1",
            ]
        created = json.loads(self.invoke(*create_args).stdout)
        applied = json.loads(self.invoke(
            "apply-human-action", "--plan-dir", str(plan),
            "--record", created["record_path"], "--key-file", str(key),
            "--expected-action", "authorize_contract",
        ).stdout)
        proc = self.invoke(
            "init-staged-research", "--plan-dir", str(plan),
            "--plan-id", "plan_staged", "--contract", str(contract),
            "--stage-envelope", str(stage),
            "--evaluation-profile", str(evaluation),
            "--checkpoint-capacity", str(capacity),
            "--authorization-receipt", applied["receipt"]["receipt_path"],
            "--incumbent-sha256", digest("incumbent"),
        )
        return json.loads(proc.stdout)

    def test_init_preserves_authorized_contract_bytes_and_repairs_legacy_copy(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            initialized = self.initialize(plan, noncanonical_contract=True)
            source = plan / "inputs" / "contract.json"
            target = (
                plan / "state" / "staged_research" / "v1" / "contracts"
                / "contract_v1.json"
            )
            state_path = plan / "state" / "staged_research" / "v1" / "state.json"
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(
                initialized["contract_sha256"],
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )

            # Recreate the pre-fix state: the staged copy was canonicalized and
            # controller state bound that new hash, while the signed receipt
            # continued to bind the original source bytes.
            target.chmod(0o644)
            canonical = json.dumps(
                json.loads(source.read_text()), indent=2, sort_keys=True,
            ) + "\n"
            target.write_text(canonical)
            target.chmod(0o444)
            state = json.loads(state_path.read_text())
            state["contract_sha256"] = hashlib.sha256(
                target.read_bytes(),
            ).hexdigest()
            state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

            applied = next((plan / "state" / "human_actions" / "applied").glob("*.json"))
            replay = self.invoke(
                "init-staged-research", "--plan-dir", str(plan),
                "--plan-id", "plan_staged", "--contract", str(source),
                "--stage-envelope", str(plan / "inputs" / "stage.json"),
                "--evaluation-profile", str(plan / "inputs" / "evaluation.json"),
                "--checkpoint-capacity", str(plan / "inputs" / "capacity.json"),
                "--authorization-receipt", str(applied),
                "--incumbent-sha256", digest("incumbent"),
            )
            recovered = json.loads(replay.stdout)
            self.assertTrue(recovered["idempotent"])
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(
                recovered["contract_sha256"],
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )
            preflight = self.write(plan / "inputs" / "preflight.json", self.raw_preflight())
            self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(preflight),
            )

    def test_owner_can_revise_first_stage_before_preflight_without_spending_slot(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            root = plan / "state" / "staged_research" / "v1"
            contract_value = json.loads((plan / "inputs" / "contract.json").read_text())
            contract_value.update({
                "contract_version": "contract_v2",
                "authorization_receipt_id": "har_owner_auth_2",
            })
            contract = self.write(plan / "inputs" / "contract-v2.json", contract_value)
            envelope_value = self.envelope("stage_1_rev2")
            envelope_value["contract_version"] = "contract_v2"
            envelope = self.write(plan / "inputs" / "stage-v2.json", envelope_value)
            key = plan / "owner.key"
            created = json.loads(self.invoke(
                "create-human-action", "--plan-dir", str(plan),
                "--plan-id", "plan_staged", "--action", "authorize_contract",
                "--key-file", str(key), "--expires-in", "3600",
                "--record-id", "har_owner_auth_2", "--actor", "research-owner",
                "--contract-version", "contract_v2", "--stage-id", "stage_1_rev2",
                "--contract-sha256", hashlib.sha256(contract.read_bytes()).hexdigest(),
                "--stage-envelope-sha256", hashlib.sha256(envelope.read_bytes()).hexdigest(),
            ).stdout)
            applied = json.loads(self.invoke(
                "apply-human-action", "--plan-dir", str(plan),
                "--record", created["record_path"], "--key-file", str(key),
                "--expected-action", "authorize_contract",
            ).stdout)
            revised = json.loads(self.invoke(
                "revise-unstarted-stage", "--plan-dir", str(plan),
                "--contract", str(contract), "--stage-envelope", str(envelope),
                "--evaluation-profile", str(plan / "inputs" / "evaluation.json"),
                "--checkpoint-capacity", str(plan / "inputs" / "capacity.json"),
                "--authorization-receipt", applied["receipt"]["receipt_path"],
            ).stdout)
            self.assertEqual(revised["contract_version"], "contract_v2")
            self.assertEqual(revised["active_stage_id"], "stage_1_rev2")
            self.assertTrue((root / "contracts" / "contract_v1.json").exists())
            self.assertTrue((root / "contracts" / "contract_v2.json").exists())
            capacity = json.loads((root / "capacity-ledger.json").read_text())
            self.assertEqual(capacity["remaining_calls"], 8)
            self.assertEqual(capacity["checkpoint_capacity"]["CP-01"]["spent"], 0)
            preflight = self.write(plan / "inputs" / "preflight-v2.json", self.raw_preflight())
            self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(preflight),
            )

    def test_preflight_allows_first_attempt_with_zero_retry_and_evaluation_budget(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            envelope = self.envelope()
            envelope["stage_budget_and_stop"]["retry_attempts"] = 0
            envelope["stage_budget_and_stop"]["evaluation_calls"] = 0
            self.initialize(plan, envelope=envelope)
            preflight = self.write(
                plan / "inputs" / "preflight.json",
                self.raw_observation_preflight(plan),
            )
            result = json.loads(self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(preflight),
            ).stdout)
            payload = json.loads(Path(result["preflight_path"]).read_text())
            self.assertEqual(
                payload["critical_path"]["mandatory_checkpoint_ids"],
                ["CP-01"],
            )
            self.assertEqual(
                payload["critical_path"]["deferred_checkpoint_ids"],
                ["CP-02", "CP-04"],
            )

    def test_evaluation_profile_and_stage_envelope_are_bidirectionally_bound(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            evaluative = self.envelope()
            plan = root / "active-observation"
            observation = self.envelope()
            observation["stage_budget_and_stop"]["evaluation_calls"] = 0
            with self.assertRaises(AssertionError) as caught:
                self.initialize(
                    plan, envelope=observation,
                    evaluation_profile_value=self.evaluation_profile(),
                )
            self.assertIn("inactive evaluation profile required", str(caught.exception))

            plan = root / "inactive-evaluative"
            with self.assertRaises(AssertionError) as caught:
                self.initialize(
                    plan, envelope=evaluative,
                    evaluation_profile_value=(
                        self.inactive_observation_evaluation_profile()
                    ),
                )
            self.assertIn("active evaluation profile required", str(caught.exception))

    def test_inactive_profile_rejects_logical_gate_query(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            envelope = self.envelope()
            envelope["stage_budget_and_stop"]["evaluation_calls"] = 0
            self.initialize(plan, envelope=envelope)
            rejected = self.invoke(
                "create-logical-gate-query", "--plan-dir", str(plan),
                "--candidate-sha256", digest("candidate"),
                "--evaluator-sha256", digest("gate"),
                "--requesting-role", "controller",
                "--logical-gate-query-id", "lgq_inactive", ok=False,
            )
            self.assertIn(
                "inactive evaluation profile forbids", rejected.stderr,
            )

    def test_orphan_worker_budget_reconciliation_is_idempotent_and_rolls_forward(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            self.preflight(plan)
            self.authorize_fixture(plan)
            root = plan / "state" / "staged_research" / "v1"
            ledger_path = root / "stages" / "stage_1" / "usage-ledger.json"
            ledger = json.loads(ledger_path.read_text())
            run_id = "cwr_" + "a" * 32
            ledger["reservation_ids"].append(f"worker:{run_id}")
            ledger["used"]["tool_calls"] = 2
            ledger["used"]["worker_tokens"] = 100
            ledger["stop_reason"] = "tool_calls_exhausted"
            ledger_path.write_text(json.dumps(ledger, sort_keys=True, indent=2) + "\n")
            task = self.write(plan / "inputs" / "orphan-task.json", {
                "stage_resource_request": {
                    "tool_calls": 2, "worker_tokens": 100,
                },
            })
            first = json.loads(self.invoke(
                "reconcile-orphan-worker-budget", "--plan-dir", str(plan),
                "--worker-run-id", run_id, "--task-contract", str(task),
            ).stdout)
            self.assertTrue(first["ok"])
            after = json.loads(ledger_path.read_text())
            self.assertNotIn(f"worker:{run_id}", after["reservation_ids"])
            self.assertEqual(after["used"]["tool_calls"], 0)
            self.assertEqual(after["used"]["worker_tokens"], 0)
            self.assertIsNone(after["stop_reason"])

            state_path = root / "state.json"
            state = json.loads(state_path.read_text())
            state["state"] = "DEVELOPING"
            state_path.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")
            replay = json.loads(self.invoke(
                "reconcile-orphan-worker-budget", "--plan-dir", str(plan),
                "--worker-run-id", run_id, "--task-contract", str(task),
            ).stdout)
            self.assertTrue(replay["idempotent"])

            journal_path = (
                root / "worker-budget-reconciliations" / f"{run_id}.json"
            )
            journal_path.chmod(0o644)
            journal = json.loads(journal_path.read_text())
            journal["phase"] = "PREPARED"
            journal.pop("committed_at", None)
            journal_path.write_text(json.dumps(journal, sort_keys=True, indent=2) + "\n")
            state["state"] = "PAUSED"
            state_path.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")
            recovered = json.loads(self.invoke(
                "reconcile-orphan-worker-budget", "--plan-dir", str(plan),
                "--worker-run-id", run_id, "--task-contract", str(task),
            ).stdout)
            self.assertTrue(recovered["recovered"])
            self.assertEqual(recovered["phase"], "COMMITTED")
            self.assertEqual(
                json.loads(state_path.read_text())["state"], "STAGE_AUTHORIZED",
            )

    def test_observation_preflight_rejects_non_utf8_before_state_or_budget_change(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            envelope = self.envelope()
            envelope["stage_budget_and_stop"]["evaluation_calls"] = 0
            self.initialize(plan, envelope=envelope)
            raw = self.raw_observation_preflight(plan)
            source = plan / "inputs" / "non-utf8.py"
            source.write_bytes(b"\xff\xfe\x00")
            raw["source_manifest"] = [{
                "path": str(source.resolve()),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "symbol": "invalid",
                "line_start": 1,
            }]
            raw_path = self.write(plan / "inputs" / "non-utf8-preflight.json", raw)
            root = plan / "state" / "staged_research" / "v1"
            state_before = (root / "state.json").read_bytes()
            usage_path = root / "stages" / "stage_1" / "usage-ledger.json"
            usage_before = usage_path.read_bytes()
            rejected = self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(raw_path), ok=False,
            )
            self.assertIn("must be UTF-8 text", rejected.stderr)
            self.assertEqual((root / "state.json").read_bytes(), state_before)
            self.assertEqual(usage_path.read_bytes(), usage_before)
            self.assertFalse(
                (root / "stages" / "stage_1" / "preflight.json").exists()
            )

    def test_observation_stage_completes_without_logical_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            envelope = self.envelope()
            envelope["stage_budget_and_stop"]["evaluation_calls"] = 0
            validator_sha = hashlib.sha256(
                (ROOT / "references" / "scripts" / "source_inventory_validator.py")
                .read_bytes()
            ).hexdigest()
            self.initialize(
                plan,
                envelope=envelope,
                capacity_value=self.capacity_v2(workers=3),
                development_validator_sha256=validator_sha,
            )
            raw = self.raw_observation_preflight(plan)
            preflight = self.write(plan / "inputs" / "preflight.json", raw)
            self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(preflight),
            )
            self.apply_cp01(plan)
            source = Path(raw["source_manifest"][0]["path"])
            candidate = self.write(plan / "out" / "source-inventory.json", {
                "schema_version": 1,
                "records": [{
                    "path": str(source.resolve()),
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "symbol": "source",
                    "line_start": 2,
                    "observation": '"source": "immutable observation input"',
                    "hypothesis": "source may identify the immutable fixture input",
                }],
                "uncertainties_and_next_questions": [
                    "Which later stage should interpret this observation?",
                ],
            })
            promotion = self.prepare_candidate_promotion(plan, candidate, "observation")
            self.invoke(
                "freeze-stage-candidate", "--plan-dir", str(plan),
                "--candidate", str(candidate),
                "--promotion-receipt", str(promotion),
            )
            completed = json.loads(self.invoke(
                "complete-observation-stage", "--plan-dir", str(plan),
            ).stdout)
            self.assertEqual(completed["state"], "RECORDED")
            root = plan / "state" / "staged_research" / "v1"
            stage = root / "stages" / "stage_1"
            decision = json.loads((stage / "decision.json").read_text())
            self.assertEqual(decision["decision_kind"], "observation_validation")
            self.assertEqual(decision["decision"], "accept")
            self.assertFalse((stage / "gate-query.json").exists())
            self.assertFalse((stage / "evidence-receipt.json").exists())
            receipt = json.loads((stage / "observation-validation.json").read_text())
            self.assertEqual(receipt["result"], "pass")
            replay = json.loads(self.invoke(
                "complete-observation-stage", "--plan-dir", str(plan),
            ).stdout)
            self.assertEqual(replay["decision_sha256"], completed["decision_sha256"])

    def test_observation_preflight_requires_exact_symbol_and_line_binding(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            envelope = self.envelope()
            envelope["stage_budget_and_stop"]["evaluation_calls"] = 0
            validator_sha = hashlib.sha256(
                (ROOT / "references" / "scripts" / "source_inventory_validator.py")
                .read_bytes()
            ).hexdigest()
            self.initialize(
                plan,
                envelope=envelope,
                capacity_value=self.capacity_v2(workers=2),
                development_validator_sha256=validator_sha,
            )
            missing = self.raw_observation_preflight(plan)
            del missing["source_manifest"][0]["symbol"]
            missing_path = self.write(
                plan / "inputs" / "missing-symbol.json", missing,
            )
            rejected = self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(missing_path), ok=False,
            )
            self.assertIn("must bind path, sha256, symbol", rejected.stderr)

            mismatch = self.raw_observation_preflight(plan)
            mismatch["source_manifest"][0]["symbol"] = "missing_symbol"
            mismatch_path = self.write(
                plan / "inputs" / "wrong-symbol.json", mismatch,
            )
            rejected = self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(mismatch_path), ok=False,
            )
            self.assertIn("symbol/line_start is not exact", rejected.stderr)

            prefix = self.raw_observation_preflight(plan)
            prefix["source_manifest"][0]["symbol"] = "sour"
            prefix_path = self.write(
                plan / "inputs" / "prefix-symbol.json", prefix,
            )
            rejected = self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(prefix_path), ok=False,
            )
            self.assertIn("symbol/line_start is not exact", rejected.stderr)

    def test_observation_stage_rejects_ungrounded_candidate_without_transition(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            envelope = self.envelope()
            envelope["stage_budget_and_stop"]["evaluation_calls"] = 0
            validator_sha = hashlib.sha256(
                (ROOT / "references" / "scripts" / "source_inventory_validator.py")
                .read_bytes()
            ).hexdigest()
            self.initialize(
                plan,
                envelope=envelope,
                capacity_value=self.capacity_v2(workers=2),
                development_validator_sha256=validator_sha,
            )
            raw = self.raw_observation_preflight(plan)
            preflight = self.write(plan / "inputs" / "preflight.json", raw)
            self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(preflight),
            )
            self.authorize_fixture(plan)
            source = Path(raw["source_manifest"][0]["path"])
            candidate = self.write(plan / "out" / "invalid-inventory.json", {
                "schema_version": 1,
                "records": [{
                    "path": str(source.resolve()),
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "symbol": "source",
                    "line_start": 2,
                    "observation": "invented source claim",
                    "hypothesis": "invalid fixture",
                }],
                "uncertainties_and_next_questions": ["Is this grounded?"],
            })
            promotion = self.prepare_candidate_promotion(plan, candidate, "bad-observation")
            self.invoke(
                "freeze-stage-candidate", "--plan-dir", str(plan),
                "--candidate", str(candidate),
                "--promotion-receipt", str(promotion),
            )
            rejected = self.invoke(
                "complete-observation-stage", "--plan-dir", str(plan),
                ok=False,
            )
            self.assertIn("source inventory validator rejected", rejected.stderr)
            root = plan / "state" / "staged_research" / "v1"
            stage = root / "stages" / "stage_1"
            self.assertEqual(
                json.loads((root / "state.json").read_text())["state"],
                "CANDIDATE_FROZEN",
            )
            self.assertFalse((stage / "decision.json").exists())
            self.assertFalse((stage / "observation-validation.json").exists())

    def test_observation_stage_review_crosses_and_starts_second_worker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            envelope = self.envelope()
            envelope["stage_budget_and_stop"]["evaluation_calls"] = 0
            validator_sha = hashlib.sha256(
                (ROOT / "references" / "scripts" / "source_inventory_validator.py")
                .read_bytes()
            ).hexdigest()
            self.initialize(
                plan,
                envelope=envelope,
                capacity_value=self.capacity_v2(workers=3),
                continuation_stage_id="stage_2",
                development_validator_sha256=validator_sha,
                evaluation_profile_value=(
                    self.inactive_observation_evaluation_profile()
                ),
            )
            raw = self.raw_observation_preflight(plan)
            preflight = self.write(plan / "inputs" / "preflight.json", raw)
            self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(preflight),
            )
            self.apply_cp01(plan)
            source = Path(raw["source_manifest"][0]["path"])
            candidate = self.write(plan / "out" / "source-inventory.json", {
                "schema_version": 1,
                "records": [{
                    "path": str(source.resolve()),
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "symbol": "source",
                    "line_start": 2,
                    "observation": '"source": "immutable observation input"',
                    "hypothesis": "source may identify the immutable fixture input",
                }],
                "uncertainties_and_next_questions": [
                    "Which later stage should interpret this observation?",
                ],
            })
            promotion = self.prepare_candidate_promotion(plan, candidate, "crossing")
            self.invoke(
                "freeze-stage-candidate", "--plan-dir", str(plan),
                "--candidate", str(candidate),
                "--promotion-receipt", str(promotion),
            )
            cycle = json.loads(self.invoke(
                "complete-observation-stage", "--plan-dir", str(plan),
            ).stdout)
            report_path, worker_run_id = self.prepare_worker_report(
                plan, cycle, "a",
            )
            report = json.loads(self.invoke(
                "record-stage-report", "--plan-dir", str(plan),
                "--stage-report", str(report_path),
                "--worker-run-id", worker_run_id,
            ).stdout)
            self.apply_strong_review(plan, Path(report["path"]))

            root = plan / "state" / "staged_research" / "v1"
            decision_path = root / "stages" / "stage_1" / "decision.json"
            canonical_decision = decision_path.read_bytes()
            forged_decision = json.loads(canonical_decision)
            forged_decision["resulting_incumbent_sha256"] = "f" * 64
            decision_path.chmod(0o644)
            decision_path.write_text(
                json.dumps(forged_decision, sort_keys=True, indent=2) + "\n"
            )
            decision_path.chmod(0o444)
            forged_stage2_value = self.envelope(
                "stage_2", source="stage_1", incumbent="f" * 64,
            )
            forged_stage2_value["stage_budget_and_stop"]["evaluation_calls"] = 0
            forged_stage2_value["authorized_evidence_refs"] = []
            forged_stage2 = self.write(
                plan / "inputs" / "forged-stage-2.json", forged_stage2_value,
            )
            rejected = self.invoke(
                "advance-staged-research", "--plan-dir", str(plan),
                "--stage-envelope", str(forged_stage2),
                "--preflight-inputs", str(self.write(
                    plan / "inputs" / "forged-stage-2-preflight.json",
                    self.raw_observation_preflight(plan),
                )),
                "--task-contract", str(self.empty_worker_contract(
                    plan, "stage_2",
                )),
                "--claude-bin", str(self.fake_claude(plan)), ok=False,
            )
            self.assertIn("hash mismatch", rejected.stderr)
            decision_path.chmod(0o644)
            decision_path.write_bytes(canonical_decision)
            decision_path.chmod(0o444)

            stage2_value = self.envelope(
                "stage_2", source="stage_1",
                incumbent=cycle["candidate_sha256"],
            )
            stage2_value["stage_budget_and_stop"]["evaluation_calls"] = 0
            stage2_value["authorized_evidence_refs"] = []
            stage2 = self.write(plan / "inputs" / "stage-2.json", stage2_value)
            preflight2 = self.write(
                plan / "inputs" / "stage-2-preflight.json",
                self.raw_observation_preflight(plan),
            )
            task = self.empty_worker_contract(plan, "stage_2")
            advanced = json.loads(self.invoke(
                "advance-staged-research", "--plan-dir", str(plan),
                "--stage-envelope", str(stage2),
                "--preflight-inputs", str(preflight2),
                "--task-contract", str(task),
                "--claude-bin", str(self.fake_claude(plan)),
            ).stdout)
            self.assertEqual(advanced["stage_id"], "stage_2")
            self.assertEqual(advanced["state"], "DEVELOPING")
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(state["active_stage_id"], "stage_2")
            self.assertEqual(state["state"], "DEVELOPING")
            capacity = json.loads((root / "capacity-ledger.json").read_text())
            self.assertEqual(
                capacity["worker_dispatch_capacity"]["spent_calls"], 1,
            )

    def test_stage_review_revise_vetoes_automatic_second_stage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            envelope = self.envelope()
            envelope["stage_budget_and_stop"]["evaluation_calls"] = 0
            validator_sha = hashlib.sha256(
                (ROOT / "references" / "scripts" / "source_inventory_validator.py")
                .read_bytes()
            ).hexdigest()
            self.initialize(
                plan, envelope=envelope,
                capacity_value=self.capacity_v2(workers=3),
                continuation_stage_id="stage_2",
                development_validator_sha256=validator_sha,
                evaluation_profile_value=(
                    self.inactive_observation_evaluation_profile()
                ),
            )
            raw = self.raw_observation_preflight(plan)
            self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(self.write(
                    plan / "inputs" / "preflight.json", raw,
                )),
            )
            self.apply_cp01(plan)
            source = Path(raw["source_manifest"][0]["path"])
            candidate = self.write(plan / "out" / "source-inventory.json", {
                "schema_version": 1,
                "records": [{
                    "path": str(source.resolve()),
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "symbol": "source", "line_start": 2,
                    "observation": '"source": "immutable observation input"',
                    "hypothesis": "source may identify the immutable fixture input",
                }],
                "uncertainties_and_next_questions": ["What should follow?"],
            })
            promotion = self.prepare_candidate_promotion(plan, candidate, "b")
            self.invoke(
                "freeze-stage-candidate", "--plan-dir", str(plan),
                "--candidate", str(candidate),
                "--promotion-receipt", str(promotion),
            )
            cycle = json.loads(self.invoke(
                "complete-observation-stage", "--plan-dir", str(plan),
            ).stdout)
            report_path, worker_run_id = self.prepare_worker_report(
                plan, cycle, "c",
            )
            report = json.loads(self.invoke(
                "record-stage-report", "--plan-dir", str(plan),
                "--stage-report", str(report_path),
                "--worker-run-id", worker_run_id,
            ).stdout)
            self.apply_strong_review(
                plan, Path(report["path"]), recommendation="revise",
            )
            stage2_value = self.envelope(
                "stage_2", source="stage_1",
                incumbent=cycle["candidate_sha256"],
            )
            stage2_value["stage_budget_and_stop"]["evaluation_calls"] = 0
            stage2_value["authorized_evidence_refs"] = []
            stage2 = self.write(plan / "inputs" / "stage-2.json", stage2_value)
            rejected = self.invoke(
                "advance-staged-research", "--plan-dir", str(plan),
                "--stage-envelope", str(stage2),
                "--preflight-inputs", str(self.write(
                    plan / "inputs" / "stage-2-preflight.json",
                    self.raw_observation_preflight(plan),
                )),
                "--task-contract", str(self.empty_worker_contract(plan, "stage_2")),
                "--claude-bin", str(self.fake_claude(plan)), ok=False,
            )
            self.assertIn("accepted canonical strongest review", rejected.stderr)
            state = json.loads((
                plan / "state" / "staged_research" / "v1" / "state.json"
            ).read_text())
            self.assertEqual(state["active_stage_id"], "stage_1")
            self.assertEqual(state["state"], "RECORDED")

    def test_developing_dispatch_capacity_rejects_before_scientific_budget(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            self.preflight(plan)
            self.authorize_fixture(plan)
            root = plan / "state" / "staged_research" / "v1"
            state_path = root / "state.json"
            state = json.loads(state_path.read_text())
            state["state"] = "DEVELOPING"
            state_path.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")
            capacity_path = root / "capacity-ledger.json"
            capacity = json.loads(capacity_path.read_text())
            capacity["remaining_calls"] = capacity["mandatory_future_calls"]
            capacity_path.chmod(0o644)
            capacity_path.write_text(
                json.dumps(capacity, sort_keys=True, indent=2) + "\n"
            )
            usage_path = root / "stages" / "stage_1" / "usage-ledger.json"
            usage_before = usage_path.read_bytes()
            spec = importlib.util.spec_from_file_location(
                "dispatch_capacity_runtime", RUNTIME,
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            runtime = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(runtime)
            run_id = "cwr_" + "b" * 32
            with self.assertRaisesRegex(
                runtime.ContractError, "mandatory_future_calls",
            ):
                runtime.staged_reserve_worker_dispatch_and_budget(
                    plan.resolve(), dispatch_id=run_id,
                    usage={"tool_calls": 2, "worker_tokens": 100},
                )
            self.assertEqual(usage_path.read_bytes(), usage_before)
            self.assertFalse(
                (root / "dispatch-reservations" / f"{run_id}.json").exists()
            )
            self.assertFalse(
                (root / "dispatch-journals" / f"{run_id}.json").exists()
            )

    def test_orphan_budget_recovery_preserves_developing_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            self.preflight(plan)
            self.authorize_fixture(plan)
            root = plan / "state" / "staged_research" / "v1"
            state_path = root / "state.json"
            state = json.loads(state_path.read_text())
            state["state"] = "DEVELOPING"
            state_path.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")
            usage_path = root / "stages" / "stage_1" / "usage-ledger.json"
            usage = json.loads(usage_path.read_text())
            run_id = "cwr_" + "c" * 32
            usage["reservation_ids"].append(f"worker:{run_id}")
            usage["used"]["tool_calls"] = 2
            usage["used"]["worker_tokens"] = 100
            usage_path.write_text(json.dumps(usage, sort_keys=True, indent=2) + "\n")
            task = self.write(plan / "inputs" / "developing-orphan-task.json", {
                "stage_resource_request": {
                    "tool_calls": 2, "worker_tokens": 100,
                },
            })
            recovered = json.loads(self.invoke(
                "reconcile-orphan-worker-budget", "--plan-dir", str(plan),
                "--worker-run-id", run_id, "--task-contract", str(task),
            ).stdout)
            self.assertTrue(recovered["ok"])
            self.assertEqual(json.loads(state_path.read_text())["state"], "DEVELOPING")
            after = json.loads(usage_path.read_text())
            self.assertNotIn(f"worker:{run_id}", after["reservation_ids"])
            self.assertEqual(after["used"]["tool_calls"], 0)
            self.assertEqual(after["used"]["worker_tokens"], 0)

    def raw_preflight(self) -> dict:
        return {
            "verdict_truth_table": {
                "accept": {
                    "resulting_incumbent": "candidate", "advancement": "record",
                },
                "reject": {
                    "resulting_incumbent": "incumbent", "advancement": "record",
                },
                "escalate": {
                    "resulting_incumbent": "incumbent", "advancement": "paused",
                },
            },
            "statistical_design": {
                "applicable": False,
                "rationale": "deterministic engineering stage",
            },
            "training_evaluation_matrix": {
                "applicable": False,
                "rationale": "no learned parameters",
            },
            "conditional_state_machine": {
                "initial": "CONTRACTED",
                "transitions": [
                    {"id": "authorize", "from": "CONTRACTED", "event": "cp01", "to": "STAGE_AUTHORIZED"},
                    {"id": "freeze", "from": "STAGE_AUTHORIZED", "event": "freeze", "to": "CANDIDATE_FROZEN"},
                    {"id": "query", "from": "CANDIDATE_FROZEN", "event": "gate", "to": "GATE_QUERIED"},
                    {"id": "accept", "from": "GATE_QUERIED", "event": "accept", "to": "RECORDED"},
                    {"id": "reject", "from": "GATE_QUERIED", "event": "reject", "to": "RECORDED"},
                    {"id": "escalate", "from": "GATE_QUERIED", "event": "escalate", "to": "PAUSED"},
                ],
            },
            "critical_path": {
                "ordered_transition_ids": [
                    "authorize", "freeze", "query", "accept",
                ],
                "checkpoint_after_transition": {
                    "CP-01": "authorize", "CP-02": "freeze", "CP-04": "accept",
                },
            },
        }

    def raw_observation_preflight(self, plan: Path) -> dict:
        source = self.write(
            plan / "inputs" / "bounded-source.py",
            {"source": "immutable observation input"},
        )
        return {
            "source_manifest": [{
                "path": str(source.resolve()),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "symbol": "source",
                "line_start": 2,
            }],
            "verdict_truth_table": {
                "applicable": False,
                "rationale": (
                    "The first stage only records source-bound observations; "
                    "the controller compiles a later Gate stage from its report."
                ),
            },
            "statistical_design": {
                "applicable": False,
                "rationale": "source inventory only",
            },
            "training_evaluation_matrix": {
                "applicable": False,
                "rationale": "no training or evaluation in this stage",
            },
            "conditional_state_machine": {
                "initial": "CONTRACTED",
                "transitions": [
                    {"id": "authorize", "from": "CONTRACTED", "event": "cp01", "to": "STAGE_AUTHORIZED"},
                    {"id": "develop", "from": "STAGE_AUTHORIZED", "event": "dispatch", "to": "DEVELOPING"},
                    {"id": "record", "from": "DEVELOPING", "event": "report", "to": "RECORDED"},
                    {"id": "complete", "from": "RECORDED", "event": "compile", "to": "COMPLETE"},
                    {"id": "pause", "from": "DEVELOPING", "event": "stop", "to": "PAUSED"},
                ],
            },
            "critical_path": {
                "ordered_transition_ids": [
                    "authorize", "develop", "record", "complete",
                ],
                "checkpoint_after_transition": {"CP-01": "authorize"},
            },
        }
    def preflight(self, plan: Path, *, validators: dict | None = None) -> dict:
        values = validators or self.raw_preflight()
        path = self.write(plan / "inputs" / "validators.json", values)
        args = [
            "preflight-staged-research", "--plan-dir", str(plan),
            "--preflight-inputs", str(path),
        ]
        proc = self.invoke(*args)
        return json.loads(proc.stdout)

    def authorize_fixture(self, plan: Path) -> None:
        """Represent an already controller-applied CP-01 in cycle-only tests."""
        state_path = plan / "state" / "staged_research" / "v1" / "state.json"
        state = json.loads(state_path.read_text())
        state["state"] = "STAGE_AUTHORIZED"
        state_path.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")

    def authorize_next_stage(
        self, plan: Path, envelope_path: Path, *,
        negative_evidence_id: str | None = None,
    ) -> str:
        envelope = json.loads(envelope_path.read_text())
        root = plan / "state" / "staged_research" / "v1"
        state = json.loads((root / "state.json").read_text())
        key = plan / "owner.key"
        record_id = f"har_authorize_{envelope['stage_id']}"
        create_args = [
            "create-human-action", "--plan-dir", str(plan),
            "--plan-id", "plan_staged", "--action", "reauthorize_stage",
            "--key-file", str(key), "--expires-in", "3600",
            "--record-id", record_id, "--actor", "research-owner",
            "--contract-version", state["contract_version"],
            "--contract-sha256", state["contract_sha256"],
            "--stage-id", envelope["stage_id"],
            "--stage-envelope-sha256",
            hashlib.sha256(envelope_path.read_bytes()).hexdigest(),
        ]
        if negative_evidence_id is not None:
            create_args += [
                "--evidence-id", negative_evidence_id,
                "--reason", "negative_context",
            ]
        created = json.loads(self.invoke(*create_args).stdout)
        applied = json.loads(self.invoke(
            "apply-human-action", "--plan-dir", str(plan),
            "--record", created["record_path"], "--key-file", str(key),
            "--expected-action", "reauthorize_stage",
        ).stdout)
        return applied["receipt"]["receipt_path"]

    def visible(
        self, plan: Path, call_id: str, role: str, *,
        crash_record: bool = False,
    ) -> dict:
        args = (
            "record-role-visible-state", "--plan-dir", str(plan),
            "--call-kind", "worker" if role == "worker" else "frontier",
            "--call-id", call_id,
        )
        if crash_record:
            env = dict(os.environ)
            env["HARNESS_FAULT_AFTER_STAGED_ARTIFACT"] = "role_visible"
            crashed = self.invoke(*args, ok=False, env=env)
            self.assertEqual(crashed.returncode, 88)
        proc = self.invoke(*args)
        return json.loads(proc.stdout)

    def prepare_candidate_promotion(
        self, plan: Path, candidate_path: Path, suffix: str,
    ) -> Path:
        run_id = "cwr_" + digest(f"candidate:{suffix}")[:32]
        run_dir = plan / "state" / "worker_runs" / run_id
        contract_path = self.write(
            plan / "inputs" / f"candidate-contract-{suffix}.json",
            {"schema_version": 1, "task_id": f"candidate-{suffix}"},
        )
        result_path = self.write(
            run_dir / "result.json", {"result": {"candidate": str(candidate_path)}},
        )
        policy_path = plan / "state" / "model_policy.json"
        self.write(run_dir / "status.json", {
            "schema_version": 1, "run_id": run_id,
            "task_id": f"candidate-{suffix}", "status": "COMPLETED",
            "worker_model": "MiniMax-M3", "contract_path": str(contract_path),
            "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
            "result_path": str(result_path),
            "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "model_policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        })
        (run_dir / "status.json").chmod(0o444)
        promotion = self.write(run_dir / "promotion-receipt.json", {
            "schema_version": 1, "plan_id": "plan_staged",
            "worker_run_id": run_id,
            "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
            "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "artifacts": [{
                "artifact_id": "candidate", "path": str(candidate_path),
                "sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
            }],
        })
        promotion.chmod(0o444)
        self.write(run_dir / "promotion-journal.json", {
            "schema_version": 1, "phase": "COMMITTED",
            "worker_run_id": run_id,
            "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
            "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "artifacts": [{
                "artifact_id": "candidate", "path": str(candidate_path),
                "sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
                "staged_path": str(run_dir / "promotion-stage" / "0000.stage"),
            }],
            "prepared_at": "2026-07-26T00:00:00Z",
            "committed_at": "2026-07-26T00:00:01Z",
            "receipt_sha256": hashlib.sha256(promotion.read_bytes()).hexdigest(),
        })
        (run_dir / "promotion-journal.json").chmod(0o444)
        return promotion

    def prepare_worker_report(
        self, plan: Path, cycle: dict, suffix: str, *,
        visible_crash: bool = False, omit_visible_binding: bool = True,
    ) -> tuple[Path, str]:
        run_id = "cwr_" + (suffix * 32)[:32]
        run_dir = plan / "state" / "worker_runs" / run_id
        contract_path = self.write(
            plan / "inputs" / f"worker-contract-{suffix}.json",
            {"schema_version": 1, "task_id": f"stage-report-{suffix}"},
        )
        result_path = self.write(
            run_dir / "result.json", {"result": {"ok": True}},
        )
        policy_path = plan / "state" / "model_policy.json"
        status_path = self.write(run_dir / "status.json", {
            "schema_version": 1, "run_id": run_id,
            "task_id": f"stage-report-{suffix}", "status": "COMPLETED",
            "worker_model": "MiniMax-M3", "contract_path": str(contract_path),
            "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
            "result_path": str(result_path),
            "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "model_policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        })
        visible = self.visible(
            plan, run_id, "worker", crash_record=visible_crash,
        )
        envelope = json.loads((
            plan / "state" / "staged_research" / "v1" / "stages"
            / "stage_1" / "envelope.json"
        ).read_text())
        stage_dir = (
            plan / "state" / "staged_research" / "v1" / "stages"
            / "stage_1"
        )
        decision_path = stage_dir / "decision.json"
        if not decision_path.exists():
            validator_path = stage_dir / "pending-terminal-validation.json"
            validator_kind = "observation_validation"
            validator_sha = "0" * 64
        else:
            decision = json.loads(decision_path.read_text())
            if decision.get("decision_kind") == "observation_validation":
                validator_path = stage_dir / "observation-validation.json"
                validator_kind = "observation_validation"
            else:
                validator_path = Path(decision["evaluator_execution_receipt_path"])
                validator_kind = "acceptance_evaluator_execution"
            validator_sha = hashlib.sha256(validator_path.read_bytes()).hexdigest()
        report_value = {
            "schema_version": 1,
            "stage_report_id": "report_stage_1",
            "stage_cycle_id": "stage_1",
            "worker_identity": {
                "agent": "worker_1", "model": "MiniMax-M3",
                "provider": "MiniMax",
            },
            "role_visible_state_sha256": visible["sha256"],
            "candidate_sha256": cycle["candidate_sha256"],
            "evidence_refs": envelope["authorized_evidence_refs"],
            "development_validator_receipts": [{
                "kind": validator_kind,
                "path": str(validator_path.resolve()),
                "sha256": validator_sha,
            }],
            "scientific_summary": "The bounded stage produced a validated candidate.",
            "findings": [{
                "claim": "The candidate is bound to the terminal validation receipt.",
                "evidence_sha256": cycle["candidate_sha256"],
            }],
            "uncertainties": ["transfer not yet measured"],
            "proposed_next_questions": ["run bounded ablation"],
        }
        if omit_visible_binding:
            report_value.pop("role_visible_state_sha256")
        report_path = self.write(
            plan / "out" / f"stage-report-{suffix}.json", report_value,
        )
        promotion = self.write(run_dir / "promotion-receipt.json", {
            "schema_version": 1, "plan_id": "plan_staged",
            "worker_run_id": run_id,
            "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
            "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "artifacts": [{
                "artifact_id": "stage_report", "path": str(report_path),
                "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
            }],
        })
        self.write(run_dir / "promotion-journal.json", {
            "schema_version": 1, "phase": "COMMITTED",
            "worker_run_id": run_id,
            "receipt_sha256": hashlib.sha256(promotion.read_bytes()).hexdigest(),
        })
        return report_path, run_id

    def fake_codex(
        self, plan: Path, *, stage_review_recommendation: str = "accept",
    ) -> Path:
        executable = plan / "fake-codex"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import hashlib,json,sys\n"
            "from pathlib import Path\n"
            "a=sys.argv[1:]\n"
            "if a[:2]==['login','status']:\n"
            " print('Logged in with ChatGPT'); raise SystemExit(0)\n"
            "if a[-2:]==['features','list']:\n"
            " print('multi_agent stable false'); raise SystemExit(0)\n"
            "out=Path(a[a.index('--output-last-message')+1])\n"
            "request_path=out.parent/'request.json'\n"
            "request=json.loads(request_path.read_text())\n"
            "manifest=request['context_manifest']\n"
            "canonical=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()\n"
            "response={\n"
            " 'schema_version':1,'request_id':request['request_id'],\n"
            " 'plan_id':request['plan_id'],'checkpoint':request['checkpoint'],\n"
            " 'checkpoint_subtype':request['checkpoint_subtype'],\n"
            " 'request_sha256':hashlib.sha256(request_path.read_bytes()).hexdigest(),\n"
            " 'context_manifest_sha256':hashlib.sha256(canonical).hexdigest(),\n"
            " 'status':'completed','response_kind':"
            "{'CP-01':'plan_audit','CP-02':'evaluator_audit',"
            "'CP-03':'pivot_advice','CP-04':'evidence_audit',"
            "'STAGE-REVIEW':'stage_review'}[request['checkpoint']],\n"
            " 'recommendation':"
            f"({stage_review_recommendation!r} if request['checkpoint']=='STAGE-REVIEW' else 'accept'),"
            "'findings':[], 'proposed_actions':[],\n"
            " 'assumptions':[],'blockers':[],'model_id':'transport-overwrites',\n"
            " 'usage':{'input_tokens':0,'output_tokens':0},\n"
            " 'completed_at':'2026-07-25T00:00:00Z'}\n"
            "out.write_text(json.dumps(response))\n"
            "print(json.dumps({'type':'turn.completed','usage':"
            "{'input_tokens':321,'output_tokens':123}}))\n"
        )
        executable.chmod(0o755)
        return executable

    def disappearing_codex(self, plan: Path) -> Path:
        """Pass preflight, then make the actual Popen path provably absent."""
        executable = plan / "fake-codex"
        child_marker = plan / "child-started"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import os,sys\n"
            "from pathlib import Path\n"
            "a=sys.argv[1:]\n"
            "if a[:2]==['login','status']:\n"
            " print('Logged in with ChatGPT')\n"
            " raise SystemExit(0)\n"
            "if a[-2:]==['features','list']:\n"
            " os.unlink(__file__)\n"
            " print('multi_agent stable false')\n"
            " raise SystemExit(0)\n"
            f"Path({str(child_marker)!r}).write_text('started')\n"
        )
        executable.chmod(0o755)
        return executable

    def apply_strong_review(
        self, plan: Path, report_path: Path, *,
        crash_record: bool = False, recommendation: str = "accept",
    ) -> str:
        root = plan / "state" / "staged_research" / "v1"
        state = json.loads((root / "state.json").read_text())
        artifacts = {
            "optimization_contract": (
                root / "contracts" / f"{state['contract_version']}.json"
            ),
            "stage_envelope": (
                root / "stages" / state["active_stage_id"] / "envelope.json"
            ),
            "stage_report": report_path,
        }
        stage_dir = root / "stages" / state["active_stage_id"]
        decision_path = stage_dir / "decision.json"
        decision = json.loads(decision_path.read_text())
        artifacts["stage_candidate"] = stage_dir / "candidate.json"
        artifacts["stage_decision"] = decision_path
        artifacts["terminal_validation_receipt"] = (
            stage_dir / "observation-validation.json"
            if decision.get("decision_kind") == "observation_validation"
            else Path(decision["evaluator_execution_receipt_path"])
        )
        args = [
            "create-frontier-request", "--plan-dir", str(plan),
            "--plan-id", "plan_staged", "--checkpoint", "STAGE-REVIEW",
            "--objective", "review terminal stage report",
            "--decision-required", "record_stage_review",
            "--max-input-tokens", "150000", "--max-output-tokens", "5000",
            "--request-id", "far_stage_review",
        ]
        for role, path in artifacts.items():
            args += ["--artifact", f"{path}::{role}"]
        self.invoke(*args)
        self.invoke(
            "send-frontier-request", "--plan-dir", str(plan),
            "--request-id", "far_stage_review",
            "--codex-bin", str(self.fake_codex(
                plan, stage_review_recommendation=recommendation,
            )),
        )
        self.invoke(
            "validate-frontier-response", "--plan-dir", str(plan),
            "--request-id", "far_stage_review",
        )
        self.invoke(
            "apply-frontier-response", "--plan-dir", str(plan),
            "--request-id", "far_stage_review",
            "--dependent-transition", "record_stage_review",
            "--controller-note", "controller recorded advisory review",
        )
        self.visible(plan, "far_stage_review", "reviewer")
        review_args = (
            "record-strong-stage-review", "--plan-dir", str(plan),
            "--request-id", "far_stage_review",
        )
        if crash_record:
            env = dict(os.environ)
            env["HARNESS_FAULT_AFTER_STAGED_ARTIFACT"] = "strong_review"
            crashed = self.invoke(*review_args, ok=False, env=env)
            self.assertEqual(crashed.returncode, 88)
        self.invoke(*review_args)
        return "far_stage_review"

    def run_terminal_cycle(
        self, plan: Path, decision: str, *,
        crash_transport: bool = False,
        crash_decision: bool = False,
        fault_decision: str | None = None,
        tamper_maturity: str | None = None,
    ) -> dict:
        value = {"accept": 0.8, "reject": 0.2, "escalate": 0.5}[decision]
        candidate_path = self.write(
            plan / "inputs" / f"candidate-{decision}.json", {"score": value},
        )
        candidate_sha = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
        promotion = self.prepare_candidate_promotion(
            plan, candidate_path, decision,
        )
        self.invoke(
            "freeze-stage-candidate", "--plan-dir", str(plan),
            "--candidate", str(candidate_path),
            "--promotion-receipt", str(promotion),
        )
        contract = json.loads((plan / "inputs" / "contract.json").read_text())
        self.invoke(
            "create-logical-gate-query", "--plan-dir", str(plan),
            "--logical-gate-query-id", f"gate_{decision}",
            "--candidate-sha256", candidate_sha,
            "--evaluator-sha256", contract["acceptance_evaluator_sha256"],
        )
        stage_candidate = json.loads(
            (plan / "state" / "staged_research" / "v1" / "stages"
             / "stage_1" / "candidate.json").read_text()
        )
        if tamper_maturity is not None:
            maturity_path = (
                plan / "state" / "staged_research" / "v1" / "stages"
                / "stage_1" / "evidence-maturity.json"
            )
            maturity = json.loads(maturity_path.read_text())
            maturity["current_maturity"] = tamper_maturity
            maturity_path.chmod(0o600)
            self.write(maturity_path, maturity)
        evidence_path = self.write(
            plan / "inputs" / f"gate-evidence-{decision}.json",
            {"split": "private", "decision_case": decision},
        )
        evaluator_path = plan / "inputs" / "gate-evaluator.json"
        execution_path = self.write(
            plan / "state" / "evaluator_runs" / f"evr_gate_{decision}.json",
            {
                "schema_version": 1, "run_id": f"evr_gate_{decision}",
                "purpose": "candidate", "plan_id": "plan_staged",
                "evaluator_path": str(evaluator_path.resolve()),
                "evaluator_sha256": hashlib.sha256(evaluator_path.read_bytes()).hexdigest(),
                "evidence_path": str(evidence_path.resolve()),
                "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                "candidate_path": stage_candidate["candidate_path"],
                "candidate_sha256": candidate_sha,
                "metric": "score", "value": value, "exit_code": 0,
            },
        )
        execution_path.chmod(0o444)
        transport_args = [
            "record-gate-transport-attempt", "--plan-dir", str(plan),
            "--logical-gate-query-id", f"gate_{decision}",
            "--transport-attempt-id", f"attempt_{decision}",
            "--execution-receipt", str(execution_path),
        ]
        if crash_transport:
            self.invoke(
                *transport_args, "--simulate-crash-after-prepare", ok=False,
            )
        self.invoke(*transport_args)
        decision_args = [
            "apply-logical-gate-decision", "--plan-dir", str(plan),
            "--logical-gate-query-id", f"gate_{decision}",
            "--execution-receipt", str(execution_path),
        ]
        if crash_decision:
            self.invoke(
                *decision_args, "--simulate-crash-after-prepare", ok=False,
            )
        if fault_decision is not None:
            env = dict(os.environ)
            env["HARNESS_FAULT_AFTER_STAGED_ARTIFACT"] = fault_decision
            crashed = self.invoke(*decision_args, ok=False, env=env)
            self.assertEqual(crashed.returncode, 88, crashed.stderr)
        if tamper_maturity is not None:
            proc = self.invoke(*decision_args, ok=False)
            return {"error": proc.stderr}
        proc = self.invoke(
            *decision_args,
        )
        stage_dir = (
            plan / "state" / "staged_research" / "v1" / "stages"
            / "stage_1"
        )
        terminal_authority = (
            promotion.parent / "status.json",
            promotion.parent / "promotion-journal.json",
            stage_dir / "gate-query.json",
            stage_dir / "gate-attempt-journals" / f"attempt_{decision}.json",
            stage_dir / "gate-decision-journal.json",
        )
        self.assertTrue(all(
            path.stat().st_mode & 0o777 == 0o444
            for path in terminal_authority
        ))
        projection = {
            str(path): (path.read_bytes(), path.stat().st_mode & 0o777)
            for path in plan.rglob("*") if path.is_file()
        }
        self.invoke(*transport_args)
        self.invoke(*decision_args)
        self.assertEqual(projection, {
            str(path): (path.read_bytes(), path.stat().st_mode & 0o777)
            for path in plan.rglob("*") if path.is_file()
        })
        return json.loads(proc.stdout)

    def create_cp01_request(self, plan: Path, request_id: str) -> None:
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
            "--objective", "audit staged contract",
            "--decision-required", "approve_execution",
            "--max-input-tokens", "150000", "--max-output-tokens", "5000",
            "--request-id", request_id,
        ]
        for role, path in artifacts.items():
            args += ["--artifact", f"{path}::{role}"]
        self.invoke(*args)

    def apply_cp01(self, plan: Path, request_id: str = "far_initial_cp01") -> None:
        self.create_cp01_request(plan, request_id)
        self.invoke(
            "send-frontier-request", "--plan-dir", str(plan),
            "--request-id", request_id,
            "--codex-bin", str(self.fake_codex(plan)),
        )
        self.invoke(
            "validate-frontier-response", "--plan-dir", str(plan),
            "--request-id", request_id,
        )
        self.invoke(
            "apply-frontier-response", "--plan-dir", str(plan),
            "--request-id", request_id,
            "--dependent-transition", "approve_execution",
            "--controller-note", "controller accepted bounded CP-01 advice",
        )

    def fake_claude(self, plan: Path) -> Path:
        executable = plan / "fake-claude"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "print(json.dumps({'artifacts': []}))\n"
        )
        executable.chmod(0o755)
        return executable

    def empty_worker_contract(self, plan: Path, stage_id: str) -> Path:
        return self.write(plan / "inputs" / f"{stage_id}-worker.json", {
            "schema_version": 1,
            "task_id": f"{stage_id}-first-worker",
            "instruction": "Perform one bounded read-only development step.",
            "inputs": [],
            "allowed_tools": [],
            "allowed_write_paths": [],
            "artifact_outputs": [],
            "output_schema": {
                "type": "object", "additionalProperties": False,
                "required": ["artifacts"],
                "properties": {
                    "artifacts": {"type": "array", "items": {"type": "object"}},
                },
            },
            "completion_check": {"type": "output_schema", "assertion": "valid"},
            "stage_resource_request": {"tool_calls": 1, "worker_tokens": 10},
        })

    def prepare_compilable_stage(self, plan: Path, suffix: str) -> dict:
        self.initialize(plan)
        self.preflight(plan)
        self.authorize_fixture(plan)
        cycle = self.run_terminal_cycle(plan, "accept")
        report_path, worker_run_id = self.prepare_worker_report(
            plan, cycle, suffix,
        )
        report = json.loads(self.invoke(
            "record-stage-report", "--plan-dir", str(plan),
            "--stage-report", str(report_path),
            "--worker-run-id", worker_run_id,
        ).stdout)
        self.apply_strong_review(plan, Path(report["path"]))
        return cycle

    def test_forged_gate_resulting_incumbent_cannot_compile_empty_evidence_stage(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.prepare_compilable_stage(plan, "e")
            root = plan / "state" / "staged_research" / "v1"
            decision_path = root / "stages" / "stage_1" / "decision.json"
            decision = json.loads(decision_path.read_text())
            decision["resulting_incumbent_sha256"] = "f" * 64
            decision_path.chmod(0o644)
            decision_path.write_text(
                json.dumps(decision, sort_keys=True, indent=2) + "\n"
            )
            decision_path.chmod(0o444)
            envelope = self.envelope(
                "stage_2", source="stage_1", incumbent="f" * 64,
            )
            envelope["authorized_evidence_refs"] = []
            envelope_path = self.write(
                plan / "inputs" / "forged-gate-stage-2.json", envelope,
            )
            authorization = self.authorize_next_stage(plan, envelope_path)
            rejected = self.invoke(
                "compile-next-stage", "--plan-dir", str(plan),
                "--stage-envelope", str(envelope_path),
                "--authorization-receipt", authorization, ok=False,
            )
            self.assertIn("hash mismatch", rejected.stderr)
            self.assertFalse(
                (root / "stages" / "stage_1" / "next-stage.json").exists()
            )

    def test_forged_gate_semantics_fail_before_stage_report_review(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            self.preflight(plan)
            self.authorize_fixture(plan)
            cycle = self.run_terminal_cycle(plan, "accept")
            root = plan / "state" / "staged_research" / "v1"
            decision_path = root / "stages" / "stage_1" / "decision.json"
            decision = json.loads(decision_path.read_text())
            decision["resulting_incumbent_sha256"] = "f" * 64
            decision_path.chmod(0o644)
            decision_path.write_text(
                json.dumps(decision, sort_keys=True, indent=2) + "\n"
            )
            decision_path.chmod(0o444)
            report_path, worker_run_id = self.prepare_worker_report(
                plan, cycle, "f",
            )
            rejected = self.invoke(
                "record-stage-report", "--plan-dir", str(plan),
                "--stage-report", str(report_path),
                "--worker-run-id", worker_run_id, ok=False,
            )
            self.assertIn("canonical Gate execution binding changed", rejected.stderr)
            self.assertFalse(
                (root / "stages" / "stage_1" / "stage-report.json").exists()
            )

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
                "--max-input-tokens", "150000", "--max-output-tokens", "5000",
                "--request-id", "far_staged_cp01",
            ]
            for role, path in artifacts.items():
                args += ["--artifact", f"{path}::{role}"]
            created = json.loads(self.invoke(*args).stdout)
            request = json.loads(Path(created["request_path"]).read_text())
            self.assertEqual(request["evidence_profile_version"], 3)
            self.assertEqual(
                request["review_contract"]["kind"],
                "staged-contract-stage-review-v2",
            )
            purposes = {
                item["purpose"] for item in request["context_manifest"]
            }
            self.assertTrue(set(artifacts).issubset(purposes))
            self.assertTrue({
                "review_material:execution_plan",
                "review_material:acceptance_evaluator",
                "review_material:risk_and_stop_rules",
                "review_material:figure_strategy",
            }.issubset(purposes))
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
                "--authorization-receipt", str(plan / "missing-auth.json"),
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
                "--authorization-receipt", str(plan / "missing-auth.json"),
                "--incumbent-sha256", digest("incumbent"), ok=False,
            )
            self.assertIn("remaining_calls < mandatory_future_calls", proc.stderr)
            self.assertFalse((plan / "state" / "staged_research").exists())

    def test_preflight_typed_failure_and_no_global_dag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            validators = self.raw_preflight()
            validators["statistical_design"] = {
                "applicable": True,
                "planned_sample_size": 2,
                "minimum_sample_size": 10,
                "planned_power": 0.2,
                "minimum_power": 0.8,
            }
            path = self.write(plan / "inputs" / "bad-validators.json", validators)
            proc = self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(path),
                ok=False,
            )
            self.assertIn("statistical design is infeasible", proc.stderr)
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
                "--authorization-receipt", str(plan2 / "missing-auth.json"),
                "--incumbent-sha256", digest("incumbent"), ok=False,
            )
            self.assertIn("forbidden fields", proc.stderr)

    def test_capacity_topup_is_prospective_exact_once_and_crash_safe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            key = plan / "owner.key"
            root = plan / "state" / "staged_research" / "v1"
            before_capacity = json.loads((root / "capacity-ledger.json").read_text())
            before_usage = json.loads(
                (root / "stages" / "stage_1" / "usage-ledger.json").read_text()
            )
            created = json.loads(self.invoke(
                "create-human-action", "--plan-dir", str(plan),
                "--plan-id", "plan_staged", "--action",
                "authorize_frontier_capacity", "--key-file", str(key),
                "--expires-in", "3600", "--record-id", "har_capacity_1",
                "--add-frontier-calls", "2",
                "--add-frontier-input-tokens", "300000",
                "--add-frontier-output-tokens", "10000",
                "--reason", "bounded prospective recovery",
            ).stdout)
            created_record = json.loads(Path(created["record_path"]).read_text())
            self.assertEqual(
                created_record["details"]["active_stage_envelope_sha256"],
                json.loads((root / "state.json").read_text())[
                    "active_stage_envelope_sha256"
                ],
            )
            operation_id = "op_" + "a" * 64
            env = dict(os.environ)
            env["HARNESS_FAULT_AFTER_CAPACITY_TOPUP_GLOBAL"] = "1"
            crashed = self.invoke(
                "apply-human-action", "--plan-dir", str(plan),
                "--record", created["record_path"], "--key-file", str(key),
                "--expected-action", "authorize_frontier_capacity",
                "--operation-id", operation_id, ok=False, env=env,
            )
            self.assertEqual(crashed.returncode, 91)
            applied = json.loads(self.invoke(
                "apply-human-action", "--plan-dir", str(plan),
                "--record", created["record_path"], "--key-file", str(key),
                "--expected-action", "authorize_frontier_capacity",
                "--operation-id", operation_id,
            ).stdout)
            self.assertTrue(applied["recovered"])
            global_budget = json.loads(
                (plan / "state" / "frontier" / "budget.json").read_text()
            )
            capacity = json.loads((root / "capacity-ledger.json").read_text())
            usage = json.loads(
                (root / "stages" / "stage_1" / "usage-ledger.json").read_text()
            )
            self.assertEqual(global_budget["authorized_capacity"], {
                "calls": 2, "input_tokens": 300000,
                "output_tokens": 10000,
            })
            self.assertEqual(
                capacity["remaining_calls"], before_capacity["remaining_calls"] + 2,
            )
            self.assertEqual(
                usage["limits"]["review_tokens"],
                before_usage["limits"]["review_tokens"] + 10000,
            )
            replay = json.loads(self.invoke(
                "apply-human-action", "--plan-dir", str(plan),
                "--record", created["record_path"], "--key-file", str(key),
                "--expected-action", "authorize_frontier_capacity",
                "--operation-id", operation_id,
            ).stdout)
            self.assertTrue(replay["operation_reconciled"])
            self.assertEqual(
                json.loads((root / "capacity-ledger.json").read_text()), capacity,
            )
            audit = [json.loads(line) for line in (root / "audit.jsonl").read_text().splitlines() if line.strip()]
            self.assertEqual(sum(
                item.get("event") == "frontier_capacity_authorized"
                and item.get("record_id") == "har_capacity_1"
                for item in audit
            ), 1)

    def test_new_stage_materials_stage_review_route_and_legacy_reinit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            root = plan / "state" / "staged_research" / "v1"
            canonical = root / "stages" / "stage_1" / "envelope.json"
            envelope = json.loads(canonical.read_text())
            self.assertIn("stop_policy", {
                item["purpose"] for item in envelope["review_material_manifest"]
            })
            misuse = self.invoke(
                "create-frontier-request", "--plan-dir", str(plan),
                "--plan-id", "plan_staged", "--checkpoint", "STAGE-REVIEW",
                "--objective", "incorrect initial review",
                "--decision-required", "record_stage_review",
                "--max-input-tokens", "150000", "--max-output-tokens", "5000",
                ok=False,
            )
            self.assertIn("Create CP-01 and apply approve_execution first", misuse.stderr)

            legacy = dict(envelope)
            legacy.pop("review_material_manifest")
            canonical.chmod(0o644)
            canonical.write_text(json.dumps(legacy, sort_keys=True, indent=2) + "\n")
            canonical.chmod(0o444)
            state_path = root / "state.json"
            state = json.loads(state_path.read_text())
            state["active_stage_envelope_sha256"] = hashlib.sha256(canonical.read_bytes()).hexdigest()
            applied_path = Path(state["owner_authorization_path"])
            applied = json.loads(applied_path.read_text())
            source_record_path = Path(applied["source_record_path"])
            source_record = json.loads(source_record_path.read_text())
            source_record["details"]["stage_envelope_sha256"] = state[
                "active_stage_envelope_sha256"
            ]
            unsigned = {
                key: value for key, value in source_record.items()
                if key != "signature"
            }
            source_record["signature"] = hmac.new(
                b"x" * 32,
                json.dumps(
                    unsigned, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False, allow_nan=False,
                ).encode(),
                hashlib.sha256,
            ).hexdigest()
            source_record_path.chmod(0o644)
            source_record_path.write_text(
                json.dumps(source_record, sort_keys=True, indent=2) + "\n"
            )
            source_record_path.chmod(0o444)
            applied["details"]["stage_envelope_sha256"] = state[
                "active_stage_envelope_sha256"
            ]
            applied["record_sha256"] = hashlib.sha256(
                source_record_path.read_bytes()
            ).hexdigest()
            applied_path.chmod(0o644)
            applied_path.write_text(json.dumps(applied, sort_keys=True, indent=2) + "\n")
            applied_path.chmod(0o444)
            action_audit = plan / "state" / "human_action_audit.jsonl"
            action_audit.write_text(json.dumps(applied, sort_keys=True) + "\n")
            receipt_sha = hashlib.sha256(applied_path.read_bytes()).hexdigest()
            state["owner_authorization_sha256"] = receipt_sha
            state["active_stage_authorization_sha256"] = receipt_sha
            state_path.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")
            staged_audit_path = root / "audit.jsonl"
            staged_audit = [
                json.loads(line) for line in staged_audit_path.read_text().splitlines()
                if line.strip()
            ]
            for record in staged_audit:
                if record.get("event") == "staged_research_initialized":
                    record["stage_envelope_sha256"] = state[
                        "active_stage_envelope_sha256"
                    ]
            staged_audit_path.write_text(
                "".join(json.dumps(item, sort_keys=True) + "\n" for item in staged_audit)
            )
            source = plan / "inputs" / "stage.json"
            source.write_text(json.dumps(legacy, sort_keys=True, indent=2) + "\n")
            reapplied = self.invoke(
                "init-staged-research", "--plan-dir", str(plan),
                "--plan-id", "plan_staged",
                "--contract", str(plan / "inputs" / "contract.json"),
                "--stage-envelope", str(source),
                "--evaluation-profile", str(plan / "inputs" / "evaluation.json"),
                "--checkpoint-capacity", str(plan / "inputs" / "capacity.json"),
                "--authorization-receipt", state["owner_authorization_path"],
                "--incumbent-sha256", digest("incumbent"),
            )
            self.assertTrue(json.loads(reapplied.stdout)["idempotent"])

    def test_capacity_topup_rejects_ledger_drift_and_concurrent_replay(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            mismatch = base / "mismatch"
            self.initialize(mismatch)
            key = mismatch / "owner.key"
            created = json.loads(self.invoke(
                "create-human-action", "--plan-dir", str(mismatch),
                "--plan-id", "plan_staged", "--action",
                "authorize_frontier_capacity", "--key-file", str(key),
                "--expires-in", "3600", "--record-id", "har_capacity_drift",
                "--add-frontier-calls", "1",
                "--add-frontier-input-tokens", "150000",
                "--add-frontier-output-tokens", "5000",
            ).stdout)
            capacity_path = (
                mismatch / "state" / "staged_research" / "v1"
                / "capacity-ledger.json"
            )
            capacity = json.loads(capacity_path.read_text())
            capacity["remaining_calls"] += 1
            capacity_path.chmod(0o644)
            capacity_path.write_text(json.dumps(capacity, sort_keys=True, indent=2) + "\n")
            failed = self.invoke(
                "apply-human-action", "--plan-dir", str(mismatch),
                "--record", created["record_path"], "--key-file", str(key),
                "--expected-action", "authorize_frontier_capacity", ok=False,
            )
            self.assertIn("ledger binding changed", failed.stderr)
            self.assertFalse(
                (mismatch / "state" / "frontier" / "budget.json").exists()
            )

            envelope_mismatch = base / "envelope-mismatch"
            self.initialize(envelope_mismatch)
            key = envelope_mismatch / "owner.key"
            created = json.loads(self.invoke(
                "create-human-action", "--plan-dir", str(envelope_mismatch),
                "--plan-id", "plan_staged", "--action",
                "authorize_frontier_capacity", "--key-file", str(key),
                "--expires-in", "3600", "--record-id", "har_capacity_envelope",
                "--add-frontier-calls", "1",
                "--add-frontier-input-tokens", "150000",
                "--add-frontier-output-tokens", "5000",
            ).stdout)
            record_path = Path(created["record_path"])
            record = json.loads(record_path.read_text())
            record["details"]["active_stage_envelope_sha256"] = "0" * 64
            unsigned = {key: value for key, value in record.items() if key != "signature"}
            record["signature"] = hmac.new(
                b"x" * 32,
                json.dumps(unsigned, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode(),
                hashlib.sha256,
            ).hexdigest()
            record_path.chmod(0o644)
            record_path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
            record_path.chmod(0o444)
            failed = self.invoke(
                "apply-human-action", "--plan-dir", str(envelope_mismatch),
                "--record", str(record_path), "--key-file", str(key),
                "--expected-action", "authorize_frontier_capacity", ok=False,
            )
            self.assertIn("active stage or envelope changed", failed.stderr)
            self.assertFalse(
                (envelope_mismatch / "state" / "frontier" / "budget.json").exists()
            )

            concurrent = base / "concurrent"
            self.initialize(concurrent)
            key = concurrent / "owner.key"
            created = json.loads(self.invoke(
                "create-human-action", "--plan-dir", str(concurrent),
                "--plan-id", "plan_staged", "--action",
                "authorize_frontier_capacity", "--key-file", str(key),
                "--expires-in", "3600", "--record-id", "har_capacity_concurrent",
                "--add-frontier-calls", "1",
                "--add-frontier-input-tokens", "150000",
                "--add-frontier-output-tokens", "5000",
            ).stdout)
            command = [
                sys.executable, str(RUNTIME), "apply-human-action",
                "--plan-dir", str(concurrent), "--record", created["record_path"],
                "--key-file", str(key), "--expected-action",
                "authorize_frontier_capacity", "--operation-id", "op_" + "b" * 64,
            ]
            processes = [
                subprocess.Popen(command, cwd=ROOT, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for _ in range(2)
            ]
            results = [process.communicate() + (process.returncode,) for process in processes]
            self.assertEqual([item[2] for item in results], [0, 0], results)
            root = concurrent / "state" / "staged_research" / "v1"
            capacity = json.loads((root / "capacity-ledger.json").read_text())
            self.assertEqual(capacity["authorized_additions"]["calls"], 1)
            audit = [json.loads(line) for line in (root / "audit.jsonl").read_text().splitlines() if line.strip()]
            self.assertEqual(sum(
                item.get("event") == "frontier_capacity_authorized"
                for item in audit
            ), 1)

    def test_review_material_path_escape_and_live_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            escape = base / "escape"
            escape.mkdir()
            self.write(escape / "resource_manifest.json", {
                "schema_version": 1, "plan_id": "plan_staged", "resources": [],
            })
            envelope = self.envelope()
            envelope_path = self.write(escape / "inputs" / "stage.json", envelope)
            envelope["review_material_manifest"][0]["path"] = "../outside.txt"
            envelope_path.write_text(json.dumps(envelope, sort_keys=True, indent=2) + "\n")
            failed = self.invoke(
                "init-staged-research", "--plan-dir", str(escape),
                "--plan-id", "plan_staged",
                "--contract", str(self.write(escape / "inputs" / "contract.json", self.contract())),
                "--stage-envelope", str(envelope_path),
                "--evaluation-profile", str(self.write(escape / "inputs" / "evaluation.json", self.evaluation_profile())),
                "--checkpoint-capacity", str(self.write(escape / "inputs" / "capacity.json", self.capacity())),
                "--authorization-receipt", str(escape / "missing.json"),
                "--incumbent-sha256", digest("incumbent"), ok=False,
            )
            self.assertIn("canonical and plan-relative", failed.stderr)

            drift = base / "drift"
            self.initialize(drift)
            canonical = (
                drift / "state" / "staged_research" / "v1"
                / "stages" / "stage_1" / "envelope.json"
            )
            material = drift / json.loads(canonical.read_text())[
                "review_material_manifest"
            ][0]["path"]
            material.chmod(0o644)
            material.write_text("drifted")
            failed = self.invoke(
                "preflight-staged-research", "--plan-dir", str(drift),
                "--preflight-inputs", str(self.write(
                    drift / "inputs" / "preflight.json", self.raw_preflight(),
                )), ok=False,
            )
            self.assertTrue(
                "immutable mode 0444" in failed.stderr
                or "content hash mismatch" in failed.stderr
            )

    def test_preflight_rejects_self_attestation_zero_budget_and_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "labels"
            self.initialize(plan)
            raw = self.raw_preflight()
            raw["statistical_design"]["verdict"] = "pass"
            path = self.write(plan / "inputs" / "labels.json", raw)
            proc = self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(path), ok=False,
            )
            self.assertIn("caller verdict labels", proc.stderr)
            raw = self.raw_preflight()
            raw["conditional_state_machine"]["embedded_future_stage"] = {
                "stage_id": "stage_2",
            }
            path = self.write(plan / "inputs" / "embedded-stage.json", raw)
            proc = self.invoke(
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(path), ok=False,
            )
            self.assertIn("invalid", proc.stderr)

            zero = Path(td) / "zero"
            envelope = self.envelope()
            envelope["stage_budget_and_stop"]["tool_calls"] = 0
            self.initialize(zero, envelope=envelope)
            raw_path = self.write(
                zero / "inputs" / "raw.json", self.raw_preflight(),
            )
            proc = self.invoke(
                "preflight-staged-research", "--plan-dir", str(zero),
                "--preflight-inputs", str(raw_path), ok=False,
            )
            self.assertIn("tool_calls=0", proc.stderr)

            drift = Path(td) / "drift"
            self.initialize(drift)
            contract_path = (
                drift / "state" / "staged_research" / "v1" / "contracts"
                / "contract_v1.json"
            )
            contract_path.chmod(0o600)
            contract = json.loads(contract_path.read_text())
            contract["objective"]["statement_sha256"] = digest("drifted")
            self.write(contract_path, contract)
            proc = self.invoke(
                "preflight-staged-research", "--plan-dir", str(drift),
                "--preflight-inputs",
                str(self.write(drift / "inputs" / "raw.json", self.raw_preflight())),
                ok=False,
            )
            self.assertIn("optimization contract hash changed", proc.stderr)

    def test_gate_truth_table_negative_evidence_and_escalation_block(self) -> None:
        for decision in ("accept", "reject", "escalate"):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as td:
                plan = Path(td) / "plan"
                self.initialize(plan)
                self.preflight(plan)
                self.authorize_fixture(plan)
                result = self.run_terminal_cycle(plan, decision)
                expected = (
                    hashlib.sha256(
                        (plan / "inputs" / f"candidate-{decision}.json").read_bytes()
                    ).hexdigest()
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
            envelope = self.envelope()
            envelope["stage_budget_and_stop"]["evaluation_calls"] = 3
            self.initialize(plan, envelope=envelope)
            self.preflight(plan)
            self.authorize_fixture(plan)
            candidate_path = self.write(
                plan / "inputs" / "candidate.json", {"score": 0.8},
            )
            candidate = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
            promotion = self.prepare_candidate_promotion(
                plan, candidate_path, "retry",
            )
            self.invoke(
                "freeze-stage-candidate", "--plan-dir", str(plan),
                "--candidate", str(candidate_path),
                "--promotion-receipt", str(promotion),
            )
            contract = json.loads((plan / "inputs" / "contract.json").read_text())
            proc = self.invoke(
                "create-logical-gate-query", "--plan-dir", str(plan),
                "--logical-gate-query-id", "gate_1",
                "--candidate-sha256", candidate,
                "--evaluator-sha256", contract["acceptance_evaluator_sha256"],
                "--requesting-role", "development", ok=False,
            )
            self.assertIn("Development must not query", proc.stderr)
            self.invoke(
                "create-logical-gate-query", "--plan-dir", str(plan),
                "--logical-gate-query-id", "gate_1",
                "--candidate-sha256", candidate,
                "--evaluator-sha256", contract["acceptance_evaluator_sha256"],
            )
            stage_candidate = json.loads(
                (plan / "state" / "staged_research" / "v1" / "stages"
                 / "stage_1" / "candidate.json").read_text()
            )
            for index in (1, 2):
                evidence_path = self.write(
                    plan / "inputs" / f"evidence-{index}.json", {"attempt": index},
                )
                evaluator_path = plan / "inputs" / "gate-evaluator.json"
                execution_path = self.write(
                    plan / "state" / "evaluator_runs" / f"evr_retry_{index}.json",
                    {
                        "schema_version": 1, "run_id": f"evr_retry_{index}",
                        "purpose": "candidate", "plan_id": "plan_staged",
                        "evaluator_path": str(evaluator_path.resolve()),
                        "evaluator_sha256": hashlib.sha256(evaluator_path.read_bytes()).hexdigest(),
                        "evidence_path": str(evidence_path.resolve()),
                        "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                        "candidate_path": stage_candidate["candidate_path"],
                        "candidate_sha256": candidate, "metric": "score",
                        "value": 0.8, "exit_code": 0,
                    },
                )
                execution_path.chmod(0o444)
                self.invoke(
                    "record-gate-transport-attempt", "--plan-dir", str(plan),
                    "--logical-gate-query-id", "gate_1",
                    "--transport-attempt-id", f"attempt_{index}",
                    "--execution-receipt", str(execution_path),
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

    def test_artifact_first_mutators_resume_complete_operation_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)

            def crash_then_replay(
                operation: str, args: tuple[str, ...],
            ) -> dict:
                env = dict(os.environ)
                env["HARNESS_FAULT_AFTER_STAGED_ARTIFACT"] = operation
                crashed = self.invoke(*args, ok=False, env=env)
                self.assertEqual(crashed.returncode, 88, crashed.stderr)
                return json.loads(self.invoke(*args).stdout)

            validators = self.write(
                plan / "inputs" / "validators.json", self.raw_preflight(),
            )
            crash_then_replay("preflight", (
                "preflight-staged-research", "--plan-dir", str(plan),
                "--preflight-inputs", str(validators),
            ))
            self.authorize_fixture(plan)
            candidate = self.write(
                plan / "inputs" / "candidate-accept.json", {"score": 0.8},
            )
            promotion = self.prepare_candidate_promotion(
                plan, candidate, "accept",
            )
            crash_then_replay("candidate", (
                "freeze-stage-candidate", "--plan-dir", str(plan),
                "--candidate", str(candidate),
                "--promotion-receipt", str(promotion),
            ))
            contract = json.loads(
                (plan / "inputs" / "contract.json").read_text()
            )
            candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
            query_args = (
                "create-logical-gate-query", "--plan-dir", str(plan),
                "--logical-gate-query-id", "gate_accept",
                "--candidate-sha256", candidate_sha,
                "--evaluator-sha256",
                contract["acceptance_evaluator_sha256"],
            )
            crash_then_replay("gate_query", query_args)
            human_args = (
                "record-human-stage-input", "--plan-dir", str(plan),
                "--input-id", "proposal_recovery", "--kind", "proposal",
                "--content-sha256", digest("proposal recovery"),
            )
            crash_then_replay("human_input", human_args)
            drifted = self.invoke(
                "record-human-stage-input", "--plan-dir", str(plan),
                "--input-id", "proposal_recovery", "--kind", "proposal",
                "--content-sha256", digest("changed proposal"), ok=False,
            )
            self.assertIn("identity collision", drifted.stderr)
            drifted_query = self.invoke(
                "create-logical-gate-query", "--plan-dir", str(plan),
                "--logical-gate-query-id", "gate_changed",
                "--candidate-sha256", candidate_sha,
                "--evaluator-sha256",
                contract["acceptance_evaluator_sha256"],
                ok=False,
            )
            self.assertIn("logical Gate query", drifted_query.stderr)
            root = plan / "state" / "staged_research" / "v1"
            audit = [
                json.loads(line)
                for line in (root / "audit.jsonl").read_text().splitlines()
                if line.strip()
            ]
            for event in (
                "stage_preflight_passed",
                "stage_candidate_frozen",
                "logical_gate_query_created",
                "human_stage_input_recorded",
            ):
                self.assertEqual(
                    len([item for item in audit if item["event"] == event]), 1,
                    event,
                )
            self.assertEqual(
                [item["audit_revision"] for item in audit],
                list(range(1, len(audit) + 1)),
            )

    def test_evidence_release_resumes_maturity_ledger_and_audit_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            self.preflight(plan)
            self.authorize_fixture(plan)
            cycle = self.run_terminal_cycle(plan, "accept")
            root = plan / "state" / "staged_research" / "v1"
            stage_dir = root / "stages" / "stage_1"
            report_path, worker_run_id = self.prepare_worker_report(
                plan, cycle, "7",
            )
            report = json.loads(self.invoke(
                "record-stage-report", "--plan-dir", str(plan),
                "--stage-report", str(report_path),
                "--worker-run-id", worker_run_id,
            ).stdout)
            self.apply_strong_review(plan, Path(report["path"]))
            roles = {
                role: self.write(
                    plan / "inputs" / f"cp04-{role}.json",
                    {"schema_version": 1, "role": role},
                )
                for role in (
                    "candidate", "claim_evidence_map", "evaluator_contract",
                    "evaluator_verdict", "raw_result_manifest", "baselines",
                    "uncertainty_robustness", "figure_gate",
                )
            }
            roles["candidate"] = stage_dir / "candidate-artifact"
            request_id = "far_release_evidence"
            create_args = [
                "create-frontier-request", "--plan-dir", str(plan),
                "--plan-id", "plan_staged", "--checkpoint", "CP-04",
                "--checkpoint-subtype", "prewriting_final_evidence",
                "--objective", "audit released staged evidence",
                "--decision-required", "start_writing",
                "--max-input-tokens", "150000", "--max-output-tokens", "5000",
                "--request-id", request_id,
            ]
            for role, path in roles.items():
                create_args += ["--artifact", f"{path}::{role}"]
            self.invoke(*create_args)
            self.invoke(
                "send-frontier-request", "--plan-dir", str(plan),
                "--request-id", request_id,
                "--codex-bin", str(self.fake_codex(plan)),
            )
            self.invoke(
                "validate-frontier-response", "--plan-dir", str(plan),
                "--request-id", request_id,
            )
            self.invoke(
                "apply-frontier-response", "--plan-dir", str(plan),
                "--request-id", request_id,
                "--dependent-transition", "start_writing",
                "--controller-note", "controller accepted CP-04",
            )
            key = plan / "owner.key"
            created = json.loads(self.invoke(
                "create-human-action", "--plan-dir", str(plan),
                "--plan-id", "plan_staged", "--action", "release_evidence",
                "--key-file", str(key), "--expires-in", "3600",
                "--record-id", "har_release_evidence",
                "--actor", "research-owner",
                "--evidence-id", "evidence_stage_1",
                "--binding-sha256", cycle["candidate_sha256"],
            ).stdout)
            applied = json.loads(self.invoke(
                "apply-human-action", "--plan-dir", str(plan),
                "--record", created["record_path"], "--key-file", str(key),
                "--expected-action", "release_evidence",
            ).stdout)
            release_args = (
                "release-staged-evidence", "--plan-dir", str(plan),
                "--authorization-receipt",
                applied["receipt"]["receipt_path"],
                "--cp04-request-id", request_id,
            )
            env = dict(os.environ)
            env["HARNESS_FAULT_AFTER_STAGED_ARTIFACT"] = "evidence_release"
            crashed = self.invoke(*release_args, ok=False, env=env)
            self.assertEqual(crashed.returncode, 88)
            released = json.loads(self.invoke(*release_args).stdout)
            self.assertEqual(released["evidence"]["maturity"], "released")
            maturity = json.loads(
                (stage_dir / "evidence-maturity.json").read_text()
            )
            self.assertEqual(maturity["current_maturity"], "released")
            ledger = [
                json.loads(line)
                for line in (root / "evidence-ledger.jsonl")
                .read_text().splitlines()
                if line.strip()
            ]
            self.assertEqual(
                len([
                    item for item in ledger
                    if item["evidence_id"] == "evidence_stage_1"
                    and item["maturity"] == "released"
                ]),
                1,
            )
            audit = [
                json.loads(line)
                for line in (root / "audit.jsonl").read_text().splitlines()
                if line.strip()
            ]
            self.assertEqual(
                len([
                    item for item in audit
                    if item["event"] == "staged_evidence_released"
                ]),
                1,
            )
            envelope = self.envelope(
                "stage_2", source="stage_1",
                incumbent=cycle["resulting_incumbent_sha256"],
            )
            envelope["authorized_evidence_refs"] = ["evidence_stage_1"]
            envelope_path = self.write(
                plan / "inputs" / "released-stage-2.json", envelope,
            )
            authorization = self.authorize_next_stage(plan, envelope_path)
            compile_args = (
                "compile-next-stage", "--plan-dir", str(plan),
                "--stage-envelope", str(envelope_path),
                "--authorized-evidence", "evidence_stage_1",
                "--authorization-receipt", authorization,
            )
            env = dict(os.environ)
            env["HARNESS_FAULT_AFTER_COMPILE_ENVELOPE"] = "1"
            self.assertEqual(
                self.invoke(*compile_args, ok=False, env=env).returncode, 87,
            )
            audit_path = root / "audit.jsonl"
            query_path = stage_dir / "gate-query.json"
            maturity_path = stage_dir / "evidence-maturity.json"
            originals = {
                path: (path.read_bytes(), path.stat().st_mode & 0o777)
                for path in (audit_path, query_path, maturity_path)
            }
            for name, mutate in (
                ("gate", lambda: query_path.unlink()),
                ("release_audit", lambda: audit_path.write_text("".join(
                    line + "\n" for line in audit_path.read_text().splitlines()
                    if json.loads(line).get("event") != "staged_evidence_released"
                ))),
                ("release_maturity", lambda: (
                    maturity_path.chmod(0o600),
                    self.write(maturity_path, {
                        **json.loads(maturity_path.read_text()),
                        "transitions": [
                            *json.loads(maturity_path.read_text())["transitions"][:-1],
                            {**json.loads(maturity_path.read_text())["transitions"][-1],
                             "recorded_at": "drifted"},
                        ],
                    }),
                    maturity_path.chmod(0o444),
                )),
            ):
                with self.subTest(released_drift=name):
                    for path, (content, mode) in originals.items():
                        path.parent.mkdir(parents=True, exist_ok=True)
                        if path.exists():
                            path.chmod(0o600)
                        path.write_bytes(content)
                        path.chmod(mode)
                    mutate()
                    snapshot = {
                        str(path.relative_to(root)): path.read_bytes()
                        for path in root.rglob("*") if path.is_file()
                    }
                    self.invoke(*compile_args, ok=False)
                    self.assertEqual(snapshot, {
                        str(path.relative_to(root)): path.read_bytes()
                        for path in root.rglob("*") if path.is_file()
                    })
            for path, (content, mode) in originals.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    path.chmod(0o600)
                path.write_bytes(content)
                path.chmod(mode)
            self.invoke(*compile_args)
            journal = json.loads(
                (root / "compile-journals" / "stage_1.json").read_text()
            )
            binding = journal["operation_identity"][
                "canonical_evidence_bindings"
            ][0]
            self.assertEqual(binding["classification"], "released_reusable")
            self.assertEqual(binding["maturity"], "released")

    def test_gate_crash_recovery_is_exact_once_and_maturity_skip_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "recover"
            self.initialize(plan)
            self.preflight(plan)
            self.authorize_fixture(plan)
            result = self.run_terminal_cycle(
                plan, "accept", crash_transport=True, crash_decision=True,
            )
            self.assertEqual(result["decision"], "accept")
            root = plan / "state" / "staged_research" / "v1"
            evidence = [
                json.loads(line)
                for line in (root / "evidence-ledger.jsonl").read_text().splitlines()
                if line.strip()
            ]
            self.assertEqual(
                len([item for item in evidence if item["evidence_id"] == "evidence_stage_1"]),
                1,
            )
            capacity = json.loads((root / "capacity-ledger.json").read_text())
            self.assertEqual(capacity["retry_budget"]["remaining_attempts"], 2)
            usage = json.loads(
                (root / "stages" / "stage_1" / "usage-ledger.json").read_text()
            )
            self.assertEqual(usage["used"]["retry_attempts"], 1)
            self.assertEqual(usage["used"]["evaluation_calls"], 1)
            with (root / "evidence-ledger.jsonl").open("a") as handle:
                handle.write(json.dumps({
                    "schema_version": 1, "evidence_id": "forged",
                    "stage_cycle_id": "stage_1", "decision": "accept",
                    "maturity": "released", "environment_version": "forged",
                    "evaluator_version": digest("forged"),
                    "applicability": ["forged"], "confidence": "high",
                    "validation_status": "validated",
                    "provenance_sha256": digest("forged"),
                    "active_for_retrieval": True,
                }) + "\n")
            retrieved = json.loads(self.invoke(
                "retrieve-staged-evidence", "--plan-dir", str(plan),
            ).stdout)
            self.assertEqual(
                [item["evidence_id"] for item in retrieved["active_evidence"]],
                ["evidence_stage_1"],
            )

            for fault in (
                "gate_evidence_receipt", "gate_evidence_ledger",
                "gate_decision_state", "gate_decision_audit",
            ):
                with self.subTest(fault=fault):
                    fault_plan = Path(td) / fault
                    self.initialize(fault_plan)
                    self.preflight(fault_plan)
                    self.authorize_fixture(fault_plan)
                    recovered = self.run_terminal_cycle(
                        fault_plan, "accept", fault_decision=fault,
                    )
                    self.assertEqual(recovered["decision"], "accept")

            tampered = Path(td) / "maturity"
            self.initialize(tampered)
            self.preflight(tampered)
            self.authorize_fixture(tampered)
            failed = self.run_terminal_cycle(
                tampered, "accept", tamper_maturity="released",
            )
            self.assertIn("maturity transition sequence", failed["error"])
            state = json.loads(
                (tampered / "state" / "staged_research" / "v1"
                 / "state.json").read_text()
            )
            self.assertEqual(state["current_incumbent_sha256"], digest("incumbent"))

    def test_canonical_negative_evidence_is_context_only(self) -> None:
        for decision in ("reject", "escalate"):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as td:
                plan = Path(td) / "plan"
                self.initialize(plan)
                self.preflight(plan)
                self.authorize_fixture(plan)
                cycle = self.run_terminal_cycle(plan, decision)
                report_path, worker_run_id = self.prepare_worker_report(
                    plan, cycle, "6",
                )
                report = json.loads(self.invoke(
                    "record-stage-report", "--plan-dir", str(plan),
                    "--stage-report", str(report_path),
                    "--worker-run-id", worker_run_id,
                ).stdout)
                self.apply_strong_review(plan, Path(report["path"]))
                envelope = self.envelope(
                    "stage_2", source="stage_1",
                    incumbent=cycle["resulting_incumbent_sha256"],
                )
                envelope["authorized_evidence_refs"] = ["evidence_stage_1"]
                envelope_path = self.write(
                    plan / "inputs" / "negative-stage-2.json", envelope,
                )
                authorization = self.authorize_next_stage(
                    plan, envelope_path,
                    negative_evidence_id="evidence_stage_1",
                )
                compiled = json.loads(self.invoke(
                    "compile-next-stage", "--plan-dir", str(plan),
                    "--stage-envelope", str(envelope_path),
                    "--authorized-evidence", "evidence_stage_1",
                    "--authorization-receipt", authorization,
                ).stdout)
                self.assertEqual(compiled["next_stage_id"], "stage_2")
                root = plan / "state" / "staged_research" / "v1"
                journal = json.loads(
                    (root / "compile-journals" / "stage_1.json").read_text()
                )
                binding = journal["operation_identity"][
                    "canonical_evidence_bindings"
                ][0]
                self.assertEqual(binding["classification"], "negative_context")
                self.assertEqual(binding["decision"], decision)
                self.assertEqual(binding["maturity"], "full_experiment")
                evidence = json.loads(
                    (root / "stages" / "stage_1" / "evidence-receipt.json")
                    .read_text()
                )
                self.assertFalse(evidence["active_for_retrieval"])
                retrieved = json.loads(self.invoke(
                    "retrieve-staged-evidence", "--plan-dir", str(plan),
                ).stdout)
                self.assertEqual(retrieved["active_evidence"], [])

    def test_compile_rejects_noncanonical_evidence_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            cycle = self.prepare_compilable_stage(plan, "5")
            root = plan / "state" / "staged_research" / "v1"

            def compile_args(
                stage_id: str, evidence_refs: list[str], cli_refs: list[str],
            ) -> list[str]:
                envelope = self.envelope(
                    stage_id, source="stage_1",
                    incumbent=cycle["resulting_incumbent_sha256"],
                )
                envelope["authorized_evidence_refs"] = evidence_refs
                path = self.write(
                    plan / "inputs" / f"{stage_id}.json", envelope,
                )
                authorization = self.authorize_next_stage(plan, path)
                args = [
                    "compile-next-stage", "--plan-dir", str(plan),
                    "--stage-envelope", str(path),
                ]
                for evidence_id in cli_refs:
                    args += ["--authorized-evidence", evidence_id]
                args += ["--authorization-receipt", authorization]
                return args

            def reject_without_projection(args: list[str]) -> str:
                before = {
                    str(path.relative_to(root)): path.read_bytes()
                    for path in root.rglob("*") if path.is_file()
                }
                proc = self.invoke(*args, ok=False)
                self.assertEqual(
                    {
                        str(path.relative_to(root)): path.read_bytes()
                        for path in root.rglob("*") if path.is_file()
                    },
                    before,
                )
                self.assertFalse((root / "compile-journals").exists())
                return proc.stderr

            forged = compile_args(
                "stage_forged", ["evidence_does_not_exist"],
                ["evidence_does_not_exist"],
            )
            self.assertIn("not canonical", reject_without_projection(forged))
            cli_only = compile_args(
                "stage_cli_only", [], ["evidence_stage_1"],
            )
            self.assertIn("exactly match", reject_without_projection(cli_only))

            canonical = compile_args(
                "stage_2", ["evidence_stage_1"], ["evidence_stage_1"],
            )
            stage_dir = root / "stages" / "stage_1"
            receipt_path = stage_dir / "evidence-receipt.json"
            ledger_path = root / "evidence-ledger.jsonl"
            audit_path = root / "audit.jsonl"
            maturity_path = stage_dir / "evidence-maturity.json"
            originals = {
                path: path.read_bytes()
                for path in (
                    receipt_path, ledger_path, audit_path, maturity_path,
                )
            }
            original_receipt = json.loads(receipt_path.read_text())

            def restore() -> None:
                for path, value in originals.items():
                    path.chmod(0o600)
                    path.write_bytes(value)
                receipt_path.chmod(0o444)
                maturity_path.chmod(0o444)

            ledger_path.write_text("")
            self.assertIn("ledger", reject_without_projection(canonical))
            restore()
            audit_records = [
                json.loads(line) for line in audit_path.read_text().splitlines()
                if line.strip()
            ]
            audit_path.write_text("".join(
                json.dumps(record, sort_keys=True) + "\n"
                for record in audit_records
                if record.get("event") != "logical_gate_decision_applied"
            ))
            self.assertIn("audit", reject_without_projection(canonical))
            restore()
            receipt_path.chmod(0o600)
            self.assertIn("mode", reject_without_projection(canonical))
            restore()

            mutation_cases = {
                "unvalidated": lambda value: value.update(
                    validation_status="unvalidated"
                ),
                "empty_applicability": lambda value: value.update(
                    applicability=[]
                ),
                "environment": lambda value: value.update(
                    environment_version="stale_environment"
                ),
                "evaluator": lambda value: value.update(
                    evaluator_version=digest("stale_evaluator")
                ),
                "inactive": lambda value: value.update(
                    active_for_retrieval=False
                ),
                "provenance": lambda value: value.update(
                    provenance_sha256=digest("drifted_provenance")
                ),
                "retired": lambda value: value.update(retired=True),
                "external": lambda value: value.update(applicability=[
                    self.evaluation_profile()[
                        "external_suite_identity_sha256"
                    ]
                ]),
            }
            for name, mutate in mutation_cases.items():
                with self.subTest(case=name):
                    receipt = json.loads(json.dumps(original_receipt))
                    mutate(receipt)
                    receipt_path.chmod(0o600)
                    self.write(receipt_path, receipt)
                    ledger_path.write_text(json.dumps(
                        receipt, sort_keys=True,
                    ) + "\n")
                    reject_without_projection(canonical)
                    restore()

            original_maturity = json.loads(maturity_path.read_text())
            for length, maturity_name in ((1, "idea"), (2, "screened")):
                maturity = json.loads(json.dumps(original_maturity))
                maturity["transitions"] = maturity["transitions"][:length]
                maturity["current_maturity"] = maturity_name
                maturity_path.chmod(0o600)
                self.write(maturity_path, maturity)
                reject_without_projection(canonical)
                restore()

            duplicate = root / "stages" / "duplicate" / "evidence-receipt.json"
            self.write(duplicate, original_receipt)
            self.assertIn("duplicated", reject_without_projection(canonical))
            duplicate.unlink()
            duplicate.parent.rmdir()

    def test_complete_compile_provenance_chain_rejects_fresh_and_recovery_drift(self) -> None:
        for prepared in (False, True):
            with self.subTest(prepared=prepared), tempfile.TemporaryDirectory() as td:
                plan = Path(td) / "plan"
                cycle = self.prepare_compilable_stage(
                    plan, "a" if prepared else "b",
                )
                root = plan / "state" / "staged_research" / "v1"
                stage = root / "stages" / "stage_1"
                envelope = self.envelope(
                    "stage_2", source="stage_1",
                    incumbent=cycle["resulting_incumbent_sha256"],
                )
                envelope_path = self.write(
                    plan / "inputs" / "provenance-stage-2.json", envelope,
                )
                authorization = self.authorize_next_stage(plan, envelope_path)
                args = [
                    "compile-next-stage", "--plan-dir", str(plan),
                    "--stage-envelope", str(envelope_path),
                    "--authorized-evidence", "evidence_stage_1",
                    "--authorization-receipt", authorization,
                ]
                if prepared:
                    env = dict(os.environ)
                    env["HARNESS_FAULT_AFTER_COMPILE_ENVELOPE"] = "1"
                    self.assertEqual(
                        self.invoke(*args, ok=False, env=env).returncode, 87,
                    )
                decision_path = stage / "decision.json"
                decision = json.loads(decision_path.read_text())
                execution_path = Path(
                    decision["evaluator_execution_receipt_path"]
                )
                execution = json.loads(execution_path.read_text())
                execution_copy = self.write(
                    plan / "inputs" / "execution-copy.json", execution,
                )
                execution_copy.chmod(0o444)
                candidate_path = stage / "candidate.json"
                candidate = json.loads(candidate_path.read_text())
                promotion_path = Path(candidate["promotion_receipt_path"])
                promotion = json.loads(promotion_path.read_text())
                run_dir = promotion_path.parent
                query_path = stage / "gate-query.json"
                query = json.loads(query_path.read_text())
                attempt_path = (
                    stage / "gate-attempt-journals"
                    / f"{query['transport_attempts'][0]['transport_attempt_id']}.json"
                )
                decision_journal_path = stage / "gate-decision-journal.json"
                maturity_path = stage / "evidence-maturity.json"
                ledger_path = root / "evidence-ledger.jsonl"
                audit_path = root / "audit.jsonl"

                def alter_json(path: Path, key: str, value: object) -> None:
                    body = json.loads(path.read_text())
                    body[key] = value
                    path.chmod(0o600)
                    self.write(path, body)
                    path.chmod(0o444 if path in {
                        execution_path, candidate_path, promotion_path,
                        decision_path, maturity_path, run_dir / "status.json",
                        run_dir / "promotion-journal.json", query_path,
                        attempt_path, decision_journal_path,
                    } else 0o600)

                def alter_transition(index: int, key: str, value: object) -> None:
                    body = json.loads(maturity_path.read_text())
                    body["transitions"][index][key] = value
                    maturity_path.chmod(0o600)
                    self.write(maturity_path, body)
                    maturity_path.chmod(0o444)

                def alter_bytes(path: Path) -> None:
                    path.chmod(0o600)
                    path.write_bytes(b"drifted")

                originals = {
                    path: (path.read_bytes(), path.stat().st_mode & 0o777)
                    for path in {
                        execution_path, Path(execution["evaluator_path"]),
                        candidate_path, Path(candidate["candidate_path"]),
                        promotion_path, run_dir / "status.json",
                        run_dir / "promotion-journal.json", query_path,
                        attempt_path, decision_journal_path, decision_path,
                        maturity_path,
                        ledger_path, audit_path,
                    }
                }

                def restore() -> None:
                    for path, (content, mode) in originals.items():
                        if path.is_symlink():
                            path.unlink()
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.chmod(0o600) if path.exists() else None
                        path.write_bytes(content)
                        path.chmod(mode)

                def projection() -> dict[str, tuple[bytes, int]]:
                    paths = {
                        path for path in root.rglob("*") if path.is_file()
                    } | set(originals)
                    return {
                        str(path): (
                            path.read_bytes(), path.lstat().st_mode & 0o777,
                        )
                        for path in paths if path.exists() or path.is_symlink()
                    }

                def append_duplicate(path: Path, event: str | None = None) -> None:
                    lines = path.read_text().splitlines()
                    selected = next(
                        line for line in lines
                        if event is None or json.loads(line).get("event") == event
                    )
                    path.write_text(path.read_text() + selected + "\n")

                def remove_line(path: Path, event: str | None = None) -> None:
                    lines = path.read_text().splitlines()
                    removed = False
                    kept = []
                    for line in lines:
                        match = event is None or json.loads(line).get("event") == event
                        if match and not removed:
                            removed = True
                        else:
                            kept.append(line)
                    path.write_text("\n".join(kept) + ("\n" if kept else ""))

                def symlink_execution() -> None:
                    execution_path.chmod(0o600)
                    execution_path.unlink()
                    execution_path.symlink_to(execution_copy)

                cases = [
                    ("execution_mode", lambda: execution_path.chmod(0o600)),
                    ("execution_symlink", symlink_execution),
                    ("execution_path", lambda: alter_json(
                        decision_path, "evaluator_execution_receipt_path",
                        str(execution_copy),
                    )),
                    ("execution_plan", lambda: alter_json(
                        execution_path, "plan_id", "plan_forged",
                    )),
                    ("execution_content", lambda: alter_json(
                        execution_path, "completed_at", "drifted",
                    )),
                    ("referenced_bytes", lambda: alter_bytes(Path(
                        execution["evaluator_path"]
                    ))),
                    ("candidate_record", lambda: alter_json(
                        candidate_path, "frozen_at", "drifted",
                    )),
                    ("candidate_record_mode", lambda: candidate_path.chmod(0o600)),
                    ("candidate_bytes", lambda: alter_bytes(Path(
                        candidate["candidate_path"]
                    ))),
                    ("worker_status", lambda: alter_json(
                        run_dir / "status.json", "worker_model", "forged",
                    )),
                    ("worker_status_anchored", lambda: alter_json(
                        run_dir / "status.json", "task_id", "candidate-forged",
                    )),
                    ("promotion_receipt", lambda: alter_json(
                        promotion_path, "plan_id", "plan_forged",
                    )),
                    ("promotion_mode", lambda: promotion_path.chmod(0o600)),
                    ("promotion_journal", lambda: alter_json(
                        run_dir / "promotion-journal.json", "phase", "PREPARED",
                    )),
                    ("promotion_journal_time", lambda: alter_json(
                        run_dir / "promotion-journal.json", "committed_at",
                        "2026-07-26T01:00:00Z",
                    )),
                    ("gate_query", lambda: alter_json(
                        query_path, "idempotency_key", digest("drifted-query"),
                    )),
                    ("missing_gate_query", query_path.unlink),
                    ("attempt_journal", lambda: alter_json(
                        attempt_path, "phase", "PREPARED",
                    )),
                    ("attempt_journal_extra", lambda: alter_json(
                        attempt_path, "extra", "drifted",
                    )),
                    ("missing_attempt_journal", attempt_path.unlink),
                    ("decision", lambda: alter_json(
                        decision_path, "decided_at", "drifted",
                    )),
                    ("decision_journal_extra", lambda: alter_json(
                        decision_journal_path, "extra", "drifted",
                    )),
                    ("decision_journal_correlation", lambda: alter_json(
                        decision_journal_path, "logical_gate_query_id", "gate_forged",
                    )),
                    ("decision_mode", lambda: decision_path.chmod(0o600)),
                    ("maturity_authority", lambda: alter_transition(
                        1, "authority", "promotion:forged",
                    )),
                    ("maturity_timestamp", lambda: alter_transition(
                        0, "recorded_at", "drifted",
                    )),
                    ("maturity_content", lambda: alter_transition(
                        2, "extra", "drifted",
                    )),
                    ("maturity_mode", lambda: maturity_path.chmod(0o600)),
                    ("missing_ledger", lambda: remove_line(ledger_path)),
                    ("duplicate_ledger", lambda: append_duplicate(ledger_path)),
                    ("missing_terminal_audit", lambda: remove_line(
                        audit_path, "logical_gate_decision_applied",
                    )),
                    ("duplicate_terminal_audit", lambda: append_duplicate(
                        audit_path, "logical_gate_decision_applied",
                    )),
                ]
                terminal_authorities = {
                    "worker_status": run_dir / "status.json",
                    "promotion_journal": run_dir / "promotion-journal.json",
                    "gate_query": query_path,
                    "attempt_journal": attempt_path,
                    "decision_journal": decision_journal_path,
                }
                self.assertTrue(all(
                    path.stat().st_mode & 0o777 == 0o444
                    for path in terminal_authorities.values()
                ))
                transport_retry = [
                    "record-gate-transport-attempt", "--plan-dir", str(plan),
                    "--logical-gate-query-id", query["logical_gate_query_id"],
                    "--transport-attempt-id",
                    query["transport_attempts"][0]["transport_attempt_id"],
                    "--execution-receipt", str(execution_path),
                ]
                decision_retry = [
                    "apply-logical-gate-decision", "--plan-dir", str(plan),
                    "--logical-gate-query-id", query["logical_gate_query_id"],
                    "--execution-receipt", str(execution_path),
                ]
                for authority, producer in (
                    (query_path, decision_retry),
                    (attempt_path, transport_retry),
                    (decision_journal_path, decision_retry),
                ):
                    for mode in (0o644, 0o600, 0o666):
                        restore()
                        authority.chmod(mode)
                        snapshot = projection()
                        self.invoke(*producer, ok=False)
                        self.assertEqual(snapshot, projection())
                for mutate, producer in (
                    (lambda: alter_json(query_path, "extra", "drifted"), decision_retry),
                    (lambda: alter_json(attempt_path, "extra", "drifted"), transport_retry),
                    (lambda: alter_json(
                        decision_journal_path, "logical_gate_query_id", "gate_forged",
                    ), decision_retry),
                ):
                    restore()
                    mutate()
                    snapshot = projection()
                    self.invoke(*producer, ok=False)
                    self.assertEqual(snapshot, projection())
                cases += [
                    (f"{name}_mode_{mode:o}",
                     lambda path=path, mode=mode: path.chmod(mode))
                    for name, path in terminal_authorities.items()
                    for mode in (0o644, 0o600, 0o666)
                ]
                for name, mutate in cases:
                    with self.subTest(case=name):
                        restore()
                        mutate()
                        snapshot = projection()
                        self.invoke(*args, ok=False)
                        self.assertEqual(snapshot, projection())
                restore()
                completed = json.loads(self.invoke(*args).stdout)
                self.assertEqual(completed["next_stage_id"], "stage_2")

    def test_forged_worker_identity_and_role_visible_source_drift_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            self.preflight(plan)
            self.authorize_fixture(plan)
            candidate = self.write(
                plan / "inputs" / "forged-candidate.json", {"score": 0.8},
            )
            promotion = self.prepare_candidate_promotion(
                plan, candidate, "forged",
            )
            status_path = promotion.parent / "status.json"
            status = json.loads(status_path.read_text())
            status["worker_model"] = "gpt-5.6-sol"
            status_path.chmod(0o600)
            self.write(status_path, status)
            status_path.chmod(0o444)
            proc = self.invoke(
                "freeze-stage-candidate", "--plan-dir", str(plan),
                "--candidate", str(candidate),
                "--promotion-receipt", str(promotion), ok=False,
            )
            self.assertIn("not a committed MiniMax artifact", proc.stderr)

            visible_plan = Path(td) / "visible"
            self.initialize(visible_plan)
            _, run_id = self.prepare_worker_report(
                visible_plan, {"candidate_sha256": digest("unused")}, "d",
            )
            result_path = (
                visible_plan / "state" / "worker_runs" / run_id / "result.json"
            )
            self.write(result_path, {"result": {"tampered": True}})
            proc = self.invoke(
                "replay-role-visible-state", "--plan-dir", str(visible_plan),
                "--call-id", run_id, ok=False,
            )
            self.assertIn("source artifact changed", proc.stderr)

    def test_combined_capacity_concurrency_and_crash_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "concurrent"
            self.initialize(plan)
            self.preflight(plan)
            self.create_cp01_request(plan, "far_concurrent_a")
            self.create_cp01_request(plan, "far_concurrent_b")
            codex = self.fake_codex(plan)
            commands = [
                [
                    sys.executable, str(RUNTIME), "send-frontier-request",
                    "--plan-dir", str(plan), "--request-id", request_id,
                    "--codex-bin", str(codex),
                ]
                for request_id in ("far_concurrent_a", "far_concurrent_b")
            ]
            processes = [
                subprocess.Popen(
                    command, cwd=ROOT, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                for command in commands
            ]
            results = [process.communicate(timeout=30) for process in processes]
            self.assertEqual(
                sum('"ok": true' in stdout for stdout, _ in results), 1,
            )
            root = plan / "state" / "staged_research" / "v1"
            reservations = list((root / "dispatch-reservations").glob("*.json"))
            self.assertEqual(len(reservations), 1)
            global_budget = json.loads(
                (plan / "state" / "frontier" / "budget.json").read_text()
            )
            self.assertEqual(global_budget["reserved_calls"], 1)

            recovery = Path(td) / "recovery"
            self.initialize(recovery)
            self.preflight(recovery)
            self.create_cp01_request(recovery, "far_crash_recovery")
            command = [
                sys.executable, str(RUNTIME), "send-frontier-request",
                "--plan-dir", str(recovery),
                "--request-id", "far_crash_recovery",
                "--codex-bin", str(self.fake_codex(recovery)),
            ]
            env = dict(os.environ)
            env["HARNESS_FAULT_AFTER_COMBINED_STAGED_CAPACITY"] = "1"
            first = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True, env=env,
            )
            self.assertEqual(first.returncode, 86)
            recovery_root = recovery / "state" / "staged_research" / "v1"
            prepared = json.loads(
                (recovery_root / "capacity-journals"
                 / "far_crash_recovery.json").read_text()
            )
            self.assertEqual(prepared["phase"], "PREPARED")
            capacity_after_crash = json.loads(
                (recovery_root / "capacity-ledger.json").read_text()
            )
            self.assertEqual(
                capacity_after_crash["checkpoint_capacity"]["CP-01"]["spent"], 1,
            )
            self.assertFalse(
                (recovery_root / "dispatch-reservations"
                 / "far_crash_recovery.json").exists()
            )
            second = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            journal = json.loads(
                (recovery_root / "capacity-journals"
                 / "far_crash_recovery.json").read_text()
            )
            self.assertEqual(journal["phase"], "COMMITTED")
            budget = json.loads(
                (recovery / "state" / "frontier" / "budget.json").read_text()
            )
            self.assertEqual(budget["reserved_calls"], 1)
            self.assertEqual(
                len(list((recovery_root / "dispatch-reservations").glob("*.json"))),
                1,
            )
            conflict = Path(td) / "conflict"
            self.initialize(conflict)
            self.preflight(conflict)
            self.create_cp01_request(conflict, "far_conflict")
            conflict_command = [
                sys.executable, str(RUNTIME), "send-frontier-request",
                "--plan-dir", str(conflict), "--request-id", "far_conflict",
                "--codex-bin", str(self.fake_codex(conflict)),
            ]
            crashed = subprocess.run(
                conflict_command, cwd=ROOT, text=True, capture_output=True,
                env=env,
            )
            self.assertEqual(crashed.returncode, 86)
            conflict_capacity_path = (
                conflict / "state" / "staged_research" / "v1"
                / "capacity-ledger.json"
            )
            conflict_capacity = json.loads(conflict_capacity_path.read_text())
            conflict_capacity["remaining_calls"] = 6
            self.write(conflict_capacity_path, conflict_capacity)
            conflicted = subprocess.run(
                conflict_command, cwd=ROOT, text=True, capture_output=True,
            )
            self.assertNotEqual(conflicted.returncode, 0)
            self.assertIn("irreconcilable", conflicted.stderr)
            self.assertEqual(
                json.loads(conflict_capacity_path.read_text())["remaining_calls"],
                6,
            )

    def test_proven_unstarted_release_is_recoverable_and_rereservable(self) -> None:
        boundaries = (
            "PREPARED", "GLOBAL", "USAGE", "CAPACITY", "MARKER", "COMBINED",
        )
        with tempfile.TemporaryDirectory() as td:
            for index, boundary in enumerate(boundaries):
                plan = Path(td) / boundary.lower()
                self.initialize(plan)
                self.preflight(plan)
                request_id = f"far_release_{boundary.lower()}"
                self.create_cp01_request(plan, request_id)
                command = [
                    sys.executable, str(RUNTIME), "send-frontier-request",
                    "--plan-dir", str(plan), "--request-id", request_id,
                    "--codex-bin", str(self.disappearing_codex(plan)),
                ]
                env = dict(os.environ)
                env[
                    f"HARNESS_FAULT_AFTER_STAGED_RELEASE_{boundary}"
                ] = "1"
                crashed = subprocess.run(
                    command, cwd=ROOT, text=True, capture_output=True, env=env,
                )
                self.assertEqual(crashed.returncode, 89, crashed.stderr)
                self.assertFalse((plan / "child-started").exists())
                root = plan / "state" / "staged_research" / "v1"
                release_path = (
                    root / "capacity-release-journals"
                    / f"{request_id}.1.json"
                )
                prepared = json.loads(release_path.read_text())
                self.assertEqual(prepared["phase"], "PREPARED")
                self.fake_codex(plan)
                recovered = subprocess.run(
                    command, cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(recovered.returncode, 0, recovered.stderr)
                released = json.loads(release_path.read_text())
                self.assertEqual(released["phase"], "RELEASED")
                combined = json.loads(
                    (root / "capacity-journals" / f"{request_id}.json")
                    .read_text()
                )
                self.assertEqual(combined["phase"], "COMMITTED")
                self.assertEqual(combined["reservation_generation"], 2)
                budget = json.loads(
                    (plan / "state" / "frontier" / "budget.json").read_text()
                )
                self.assertEqual(budget["request_ids"].count(request_id), 1)
                capacity = json.loads(
                    (root / "capacity-ledger.json").read_text()
                )
                self.assertEqual(
                    capacity["checkpoint_capacity"]["CP-01"]["spent"], 1,
                )
                usage = json.loads(
                    (root / "stages" / "stage_1" / "usage-ledger.json")
                    .read_text()
                )
                self.assertEqual(
                    usage["reservation_ids"].count(f"frontier:{request_id}"), 1,
                )
                self.assertTrue(
                    (root / "dispatch-reservations" / f"{request_id}.json")
                    .is_file()
                )
                audit = [
                    json.loads(line)
                    for line in (root / "audit.jsonl").read_text().splitlines()
                    if line.strip()
                ]
                self.assertEqual(
                    len([
                        item for item in audit
                        if item["event"]
                        == "model_dispatch_released_unstarted"
                    ]),
                    1,
                )

            for dimension in (
                "global", "staged", "usage", "marker", "combined",
            ):
                conflict = Path(td) / f"conflict_{dimension}"
                self.initialize(conflict)
                self.preflight(conflict)
                request_id = f"far_release_conflict_{dimension}"
                self.create_cp01_request(conflict, request_id)
                command = [
                    sys.executable, str(RUNTIME), "send-frontier-request",
                    "--plan-dir", str(conflict), "--request-id", request_id,
                    "--codex-bin", str(self.disappearing_codex(conflict)),
                ]
                env = dict(os.environ)
                env["HARNESS_FAULT_AFTER_STAGED_RELEASE_PREPARED"] = "1"
                crashed = subprocess.run(
                    command, cwd=ROOT, text=True,
                    capture_output=True, env=env,
                )
                self.assertEqual(crashed.returncode, 89)
                root = conflict / "state" / "staged_research" / "v1"
                paths = {
                    "global": (
                        conflict / "state" / "frontier" / "budget.json"
                    ),
                    "staged": root / "capacity-ledger.json",
                    "usage": (
                        root / "stages" / "stage_1" / "usage-ledger.json"
                    ),
                    "marker": (
                        root / "dispatch-reservations"
                        / f"{request_id}.json"
                    ),
                    "combined": (
                        root / "capacity-journals" / f"{request_id}.json"
                    ),
                }
                value = json.loads(paths[dimension].read_text())
                if dimension == "global":
                    value["reserved_calls"] += 5
                elif dimension == "staged":
                    value["remaining_calls"] -= 2
                elif dimension == "usage":
                    value["used"]["review_tokens"] += 13
                elif dimension == "marker":
                    value["remaining_calls"] -= 2
                else:
                    value["tampered"] = True
                paths[dimension].chmod(0o600)
                self.write(paths[dimension], value)
                before_rejection = {
                    name: path.read_bytes() for name, path in paths.items()
                }
                self.fake_codex(conflict)
                rejected = subprocess.run(
                    command, cwd=ROOT, text=True, capture_output=True,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("irreconcilable", rejected.stderr)
                self.assertEqual(
                    {
                        name: path.read_bytes()
                        for name, path in paths.items()
                    },
                    before_rejection,
                )

            ambiguous = Path(td) / "ambiguous_started"
            self.initialize(ambiguous)
            self.preflight(ambiguous)
            request_id = "far_started_failure"
            self.create_cp01_request(ambiguous, request_id)
            executable = ambiguous / "started-codex"
            child_marker = ambiguous / "child-started"
            executable.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "from pathlib import Path\n"
                "if sys.argv[1:3] == ['login','status']:\n"
                " print('Logged in with ChatGPT'); raise SystemExit(0)\n"
                "if sys.argv[-2:] == ['features','list']:\n"
                " print('multi_agent stable false'); raise SystemExit(0)\n"
                f"Path({str(child_marker)!r}).write_text('started')\n"
                "raise SystemExit(7)\n"
            )
            executable.chmod(0o755)
            failed = self.invoke(
                "send-frontier-request", "--plan-dir", str(ambiguous),
                "--request-id", request_id, "--codex-bin", str(executable),
                ok=False,
            )
            self.assertIn("transport failed", failed.stderr)
            self.assertTrue(child_marker.is_file())
            ambiguous_root = (
                ambiguous / "state" / "staged_research" / "v1"
            )
            self.assertFalse(
                (ambiguous_root / "capacity-release-journals").exists()
            )
            budget = json.loads(
                (ambiguous / "state" / "frontier" / "budget.json").read_text()
            )
            self.assertIn(request_id, budget["request_ids"])
            self.assertTrue(
                (ambiguous_root / "dispatch-reservations"
                 / f"{request_id}.json").is_file()
            )

    def test_evaluator_adoption_drift_requires_rebaseline_and_owner_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            self.preflight(plan)
            self.authorize_fixture(plan)
            cycle = self.run_terminal_cycle(plan, "accept")
            root = plan / "state" / "staged_research" / "v1"

            new_evaluator = self.write(
                plan / "inputs" / "gate-evaluator-v2.json",
                {"schema_version": 1, "kind": "isolated-gate-evaluator-v2",
                 "metric": "score"},
            )
            contract = self.contract()
            contract.update({
                "contract_version": "contract_v2",
                "authorization_receipt_id": "har_rebaseline_v2",
                "acceptance_evaluator_sha256": hashlib.sha256(
                    new_evaluator.read_bytes()
                ).hexdigest(),
                "adoption_policy_sha256": digest("adoption-v2"),
            })
            contract_path = self.write(
                plan / "inputs" / "contract-v2.json", contract,
            )
            envelope = self.envelope(
                "stage_2", source="stage_1",
                incumbent=cycle["resulting_incumbent_sha256"],
            )
            envelope["contract_version"] = "contract_v2"
            envelope_path = self.write(
                plan / "inputs" / "stage-v2.json", envelope,
            )
            key = plan / "owner.key"
            created = json.loads(self.invoke(
                "create-human-action", "--plan-dir", str(plan),
                "--plan-id", "plan_staged", "--action", "authorize_rebaseline",
                "--key-file", str(key), "--expires-in", "3600",
                "--record-id", "har_rebaseline_v2", "--actor", "research-owner",
                "--contract-version", "contract_v2",
                "--contract-sha256",
                hashlib.sha256(contract_path.read_bytes()).hexdigest(),
                "--stage-id", "stage_2", "--stage-envelope-sha256",
                hashlib.sha256(envelope_path.read_bytes()).hexdigest(),
            ).stdout)
            applied = json.loads(self.invoke(
                "apply-human-action", "--plan-dir", str(plan),
                "--record", created["record_path"], "--key-file", str(key),
                "--expected-action", "authorize_rebaseline",
            ).stdout)
            authorization = applied["receipt"]["receipt_path"]

            candidate = root / "stages" / "stage_1" / "candidate-artifact"
            calibration_evidence = self.write(
                plan / "inputs" / "calibration-evidence.json",
                {"calibration": "v2"},
            )
            calibration_path = self.write(
                plan / "state" / "evaluator_runs"
                / "evr_rebaseline_v2.json",
                {
                    "schema_version": 1, "run_id": "evr_rebaseline_v2",
                    "purpose": "calibration", "plan_id": "plan_staged",
                    "evaluator_path": str(new_evaluator.resolve()),
                    "evaluator_sha256": hashlib.sha256(
                        new_evaluator.read_bytes()
                    ).hexdigest(),
                    "evidence_path": str(calibration_evidence.resolve()),
                    "evidence_sha256": hashlib.sha256(
                        calibration_evidence.read_bytes()
                    ).hexdigest(),
                    "candidate_path": str(candidate.resolve()),
                    "candidate_sha256": hashlib.sha256(
                        candidate.read_bytes()
                    ).hexdigest(),
                    "metric": "score", "value": 0.75, "exit_code": 0,
                },
            )
            calibration_path.chmod(0o444)
            forged = self.write(
                plan / "inputs" / "forged-rebaseline.json",
                {"record_id": "har_rebaseline_v2",
                 "action": "authorize_rebaseline"},
            )
            proc = self.invoke(
                "record-evaluator-rebaseline", "--plan-dir", str(plan),
                "--contract", str(contract_path),
                "--execution-receipt", str(calibration_path),
                "--authorization-receipt", str(forged), ok=False,
            )
            self.assertIn("canonical applied receipt", proc.stderr)
            rebaseline_args = (
                "record-evaluator-rebaseline", "--plan-dir", str(plan),
                "--contract", str(contract_path),
                "--execution-receipt", str(calibration_path),
                "--authorization-receipt", authorization,
            )
            env = dict(os.environ)
            env["HARNESS_FAULT_AFTER_STAGED_ARTIFACT"] = "rebaseline"
            crashed = self.invoke(*rebaseline_args, ok=False, env=env)
            self.assertEqual(crashed.returncode, 88)
            rebaseline = json.loads(self.invoke(*rebaseline_args).stdout)
            evaluation = self.evaluation_profile()
            evaluation["profile_id"] = "evaluation_v2"
            evaluation_path = self.write(
                plan / "inputs" / "evaluation-v2.json", evaluation,
            )
            amend_args = (
                "amend-staged-contract", "--plan-dir", str(plan),
                "--contract", str(contract_path),
                "--evaluation-profile", str(evaluation_path),
                "--stage-envelope", str(envelope_path),
                "--rebaseline-receipt", rebaseline["receipt_path"],
            )
            env["HARNESS_FAULT_AFTER_STAGED_ARTIFACT"] = "amend"
            crashed = self.invoke(*amend_args, ok=False, env=env)
            self.assertEqual(crashed.returncode, 88)
            env.pop("HARNESS_FAULT_AFTER_STAGED_ARTIFACT")
            env["HARNESS_FAULT_AFTER_AMEND_EVALUATION"] = "1"
            crashed = self.invoke(*amend_args, ok=False, env=env)
            self.assertEqual(crashed.returncode, 90)
            amended = json.loads(self.invoke(*amend_args).stdout)
            self.assertEqual(amended["contract_version"], "contract_v2")
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(state["active_stage_id"], "stage_2")
            self.assertEqual(
                state["owner_authorization_action"], "authorize_rebaseline",
            )

    def test_stage_stop_requires_canonical_human_reauthorization(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            self.preflight(plan)
            self.authorize_fixture(plan)
            pause_args = (
                "pause-staged-research", "--plan-dir", str(plan),
                "--reason", "risk",
            )
            env = dict(os.environ)
            env["HARNESS_FAULT_AFTER_STAGED_ARTIFACT"] = "pause"
            crashed = self.invoke(*pause_args, ok=False, env=env)
            self.assertEqual(crashed.returncode, 88)
            paused = json.loads(self.invoke(*pause_args).stdout)
            self.assertEqual(paused["reason"], "risk")
            self.assertEqual(
                json.loads(
                    (plan / "state" / "staged_research" / "v1"
                     / "state.json").read_text()
                )["state"],
                "PAUSED",
            )
            candidate = self.write(
                plan / "inputs" / "paused-candidate.json", {"score": 0.8},
            )
            promotion = self.prepare_candidate_promotion(
                plan, candidate, "paused",
            )
            proc = self.invoke(
                "freeze-stage-candidate", "--plan-dir", str(plan),
                "--candidate", str(candidate),
                "--promotion-receipt", str(promotion), ok=False,
            )
            self.assertIn("controller-authorized stage", proc.stderr)
            envelope_path = (
                plan / "state" / "staged_research" / "v1" / "stages"
                / "stage_1" / "envelope.json"
            )
            authorization = self.authorize_next_stage(plan, envelope_path)
            reauthorize_args = (
                "reauthorize-staged-research", "--plan-dir", str(plan),
                "--authorization-receipt", authorization,
            )
            env["HARNESS_FAULT_AFTER_STAGED_ARTIFACT"] = "reauthorize"
            crashed = self.invoke(*reauthorize_args, ok=False, env=env)
            self.assertEqual(crashed.returncode, 88)
            resumed = json.loads(self.invoke(*reauthorize_args).stdout)
            self.assertEqual(resumed["stage_id"], "stage_1")
            state = json.loads(
                (plan / "state" / "staged_research" / "v1"
                 / "state.json").read_text()
            )
            self.assertEqual(state["state"], "STAGE_AUTHORIZED")
            self.assertEqual(
                state["active_stage_authorization_action"], "reauthorize_stage",
            )

    def test_concurrent_staged_mutators_have_unique_audit_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            commands = [
                [
                    sys.executable, str(RUNTIME),
                    "record-human-stage-input", "--plan-dir", str(plan),
                    "--input-id", f"proposal_{index}", "--kind", "proposal",
                    "--content-sha256", digest(f"proposal:{index}"),
                ]
                for index in range(24)
            ]
            processes = [
                subprocess.Popen(
                    command, cwd=ROOT, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                for command in commands
            ]
            results = [process.communicate(timeout=30) for process in processes]
            self.assertTrue(
                all(process.returncode == 0 for process in processes),
                results,
            )
            root = plan / "state" / "staged_research" / "v1"
            audit = [
                json.loads(line)
                for line in (root / "audit.jsonl").read_text().splitlines()
                if line.strip()
            ]
            revisions = [item["audit_revision"] for item in audit]
            self.assertEqual(revisions, list(range(1, 26)))
            self.assertEqual(len(set(revisions)), 25)
            self.assertEqual(
                json.loads((root / "state.json").read_text())["audit_revision"],
                25,
            )
            inputs = [
                json.loads(line)
                for line in (root / "human-inputs.jsonl").read_text().splitlines()
                if line.strip()
            ]
            self.assertEqual(len({item["input_id"] for item in inputs}), 24)

    def test_visible_state_transfer_isolation_and_human_proposal_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.init_policy(plan)
            self.initialize(plan)
            _, worker_run_id = self.prepare_worker_report(
                plan, {"candidate_sha256": digest("unused")}, "c",
            )
            visible = json.loads(
                (plan / "state" / "staged_research" / "v1" / "role-visible"
                 / f"{worker_run_id}.json").read_text()
            )
            visible_path = (
                plan / "state" / "staged_research" / "v1" / "role-visible"
                / f"{worker_run_id}.json"
            )
            self.assertTrue(visible_path.is_file())
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
                "--call-kind", "worker", "--call-id", "cwr_" + "f" * 32,
                ok=False,
            )
            self.assertIn("worker run not found", proc.stderr)
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
            report_path, worker_run_id = self.prepare_worker_report(
                plan, cycle, "a", visible_crash=True,
                omit_visible_binding=True,
            )
            promotion_journal_path = (
                plan / "state" / "worker_runs" / worker_run_id
                / "promotion-journal.json"
            )
            promotion_journal = json.loads(promotion_journal_path.read_text())
            promotion_journal["phase"] = "PREPARED"
            self.write(promotion_journal_path, promotion_journal)
            proc = self.invoke(
                "record-stage-report", "--plan-dir", str(plan),
                "--stage-report", str(report_path),
                "--worker-run-id", worker_run_id, ok=False,
            )
            self.assertIn("COMMITTED MiniMax promotion", proc.stderr)
            promotion_journal["phase"] = "COMMITTED"
            self.write(promotion_journal_path, promotion_journal)
            report_args = (
                "record-stage-report", "--plan-dir", str(plan),
                "--stage-report", str(report_path),
                "--worker-run-id", worker_run_id,
            )
            env = dict(os.environ)
            env["HARNESS_FAULT_AFTER_STAGED_ARTIFACT"] = "stage_report"
            crashed = self.invoke(*report_args, ok=False, env=env)
            self.assertEqual(crashed.returncode, 88)
            report = json.loads(self.invoke(
                *report_args,
            ).stdout)
            canonical_report = json.loads(Path(report["path"]).read_text())
            visible_path = (
                plan / "state" / "staged_research" / "v1" / "role-visible"
                / f"{worker_run_id}.json"
            )
            self.assertEqual(
                canonical_report["role_visible_state_sha256"],
                hashlib.sha256(visible_path.read_bytes()).hexdigest(),
            )
            self.assertNotIn(
                "role_visible_state_sha256", json.loads(report_path.read_text()),
            )
            self.apply_strong_review(
                plan, Path(report["path"]), crash_record=True,
            )
            next_envelope = self.envelope(
                "stage_2", source="stage_1",
                incumbent=cycle["resulting_incumbent_sha256"],
            )
            next_path = self.write(plan / "inputs" / "stage-2.json", next_envelope)
            next_authorization = self.authorize_next_stage(plan, next_path)
            compiled = json.loads(self.invoke(
                "compile-next-stage", "--plan-dir", str(plan),
                "--stage-envelope", str(next_path),
                "--authorized-evidence", "evidence_stage_1",
                "--authorization-receipt", next_authorization,
            ).stdout)
            self.assertEqual(compiled["next_stage_id"], "stage_2")
            proc = self.invoke(
                "compile-next-stage", "--plan-dir", str(plan),
                "--stage-envelope", str(next_path),
                "--authorization-receipt", next_authorization,
                "--authorized-evidence", "evidence_stage_1", ok=False,
            )
            self.assertIn("identity conflict", proc.stderr)

    def test_concurrent_and_crashed_next_stage_compile_are_exact_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "concurrent"
            cycle = self.prepare_compilable_stage(plan, "e")
            commands = []
            for suffix in ("a", "b"):
                envelope = self.envelope(
                    f"stage_2{suffix}", source="stage_1",
                    incumbent=cycle["resulting_incumbent_sha256"],
                )
                path = self.write(
                    plan / "inputs" / f"stage-2{suffix}.json", envelope,
                )
                authorization = self.authorize_next_stage(plan, path)
                commands.append([
                    sys.executable, str(RUNTIME), "compile-next-stage",
                    "--plan-dir", str(plan), "--stage-envelope", str(path),
                    "--authorized-evidence", "evidence_stage_1",
                    "--authorization-receipt", authorization,
                ])
            processes = [
                subprocess.Popen(
                    command, cwd=ROOT, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                for command in commands
            ]
            results = [process.communicate(timeout=30) for process in processes]
            self.assertEqual(
                sum(process.returncode == 0 for process in processes), 1,
                results,
            )
            self.assertIn(
                "identity conflict",
                next(
                    stderr for process, (_, stderr)
                    in zip(processes, results)
                    if process.returncode != 0
                ),
            )
            root = plan / "state" / "staged_research" / "v1"
            state = json.loads((root / "state.json").read_text())
            winner = state["active_stage_id"]
            loser = "stage_2b" if winner == "stage_2a" else "stage_2a"
            self.assertIn(winner, {"stage_2a", "stage_2b"})
            self.assertTrue((root / "stages" / winner / "envelope.json").is_file())
            self.assertFalse((root / "stages" / loser / "envelope.json").exists())
            marker = json.loads(
                (root / "stages" / "stage_1" / "next-stage.json").read_text()
            )
            self.assertEqual(marker["next_stage_id"], winner)
            audit = [
                json.loads(line)
                for line in (root / "audit.jsonl").read_text().splitlines()
                if line.strip()
            ]
            self.assertEqual(
                len([item for item in audit
                     if item["event"] == "next_stage_compiled"]),
                1,
            )

            recovery = Path(td) / "recovery"
            recovery_cycle = self.prepare_compilable_stage(recovery, "f")
            envelope = self.envelope(
                "stage_2", source="stage_1",
                incumbent=recovery_cycle["resulting_incumbent_sha256"],
            )
            path = self.write(recovery / "inputs" / "stage-2.json", envelope)
            authorization = self.authorize_next_stage(recovery, path)
            command = [
                sys.executable, str(RUNTIME), "compile-next-stage",
                "--plan-dir", str(recovery), "--stage-envelope", str(path),
                "--authorized-evidence", "evidence_stage_1",
                "--authorization-receipt", authorization,
            ]
            env = dict(os.environ)
            env["HARNESS_FAULT_AFTER_COMPILE_ENVELOPE"] = "1"
            crashed = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True, env=env,
            )
            self.assertEqual(crashed.returncode, 87)
            recovery_root = recovery / "state" / "staged_research" / "v1"
            self.assertTrue(
                (recovery_root / "stages" / "stage_2" / "envelope.json").is_file()
            )
            self.assertFalse(
                (recovery_root / "stages" / "stage_1"
                 / "next-stage.json").exists()
            )
            frozen_projection = {
                str(item.relative_to(recovery_root)): item.read_bytes()
                for item in recovery_root.rglob("*") if item.is_file()
            }
            drifted_evidence = (
                ["evidence_stage_1", "evidence_added"],
                [],
            )
            for evidence_values in drifted_evidence:
                drifted_command = [
                    sys.executable, str(RUNTIME), "compile-next-stage",
                    "--plan-dir", str(recovery),
                    "--stage-envelope", str(path),
                ]
                for evidence in evidence_values:
                    drifted_command += ["--authorized-evidence", evidence]
                drifted_command += [
                    "--authorization-receipt", authorization,
                ]
                rejected = subprocess.run(
                    drifted_command, cwd=ROOT, text=True,
                    capture_output=True,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("compile evidence", rejected.stderr)
                self.assertEqual(
                    {
                        str(item.relative_to(recovery_root)): item.read_bytes()
                        for item in recovery_root.rglob("*") if item.is_file()
                    },
                    frozen_projection,
                )
            audit_path = recovery_root / "audit.jsonl"
            original_audit = audit_path.read_bytes()
            audit_records = [
                json.loads(line) for line in audit_path.read_text().splitlines()
                if line.strip()
            ]
            next(
                item for item in audit_records
                if item["event"] == "logical_gate_decision_applied"
            )["binding_drift"] = True
            audit_path.write_text("".join(
                json.dumps(item, sort_keys=True) + "\n"
                for item in audit_records
            ))
            drifted_projection = {
                str(item.relative_to(recovery_root)): item.read_bytes()
                for item in recovery_root.rglob("*") if item.is_file()
            }
            rejected = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("audit", rejected.stderr)
            self.assertEqual(
                {
                    str(item.relative_to(recovery_root)): item.read_bytes()
                    for item in recovery_root.rglob("*") if item.is_file()
                },
                drifted_projection,
            )
            audit_path.write_bytes(original_audit)
            recovered = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            journal = json.loads(
                (recovery_root / "compile-journals" / "stage_1.json").read_text()
            )
            self.assertEqual(journal["phase"], "COMMITTED")
            self.assertEqual(
                json.loads((recovery_root / "state.json").read_text())[
                    "active_stage_id"
                ],
                "stage_2",
            )

            figure_recovery = Path(td) / "figure_recovery"
            figure_cycle = self.prepare_compilable_stage(
                figure_recovery, "9",
            )
            inventory = self.write(
                figure_recovery / "inputs" / "figure-requirements.json",
                {
                    "schema_version": 1,
                    "plan_id": "plan_staged",
                    "tier": "arxiv",
                    "expected_figure_ids": ["fig_1"],
                },
            )
            original_inventory = inventory.read_bytes()
            figure_envelope = self.envelope(
                "stage_figures", source="stage_1",
                incumbent=figure_cycle["resulting_incumbent_sha256"],
                kind="figure_production",
            )
            figure_envelope["figure_requirements_sha256"] = hashlib.sha256(
                original_inventory
            ).hexdigest()
            figure_path = self.write(
                figure_recovery / "inputs" / "figure-stage.json",
                figure_envelope,
            )
            figure_authorization = self.authorize_next_stage(
                figure_recovery, figure_path,
            )
            figure_command = [
                sys.executable, str(RUNTIME), "compile-next-stage",
                "--plan-dir", str(figure_recovery),
                "--stage-envelope", str(figure_path),
                "--authorized-evidence", "evidence_stage_1",
                "--figure-requirements", str(inventory),
                "--authorization-receipt", figure_authorization,
            ]
            crashed = subprocess.run(
                figure_command, cwd=ROOT, text=True,
                capture_output=True, env=env,
            )
            self.assertEqual(crashed.returncode, 87)
            figure_root = (
                figure_recovery / "state" / "staged_research" / "v1"
            )
            frozen_figure_projection = {
                str(item.relative_to(figure_root)): item.read_bytes()
                for item in figure_root.rglob("*") if item.is_file()
            }

            without_figure = [
                item for item in figure_command
                if item not in {"--figure-requirements", str(inventory)}
            ]
            alternate = figure_recovery / "inputs" / "alternate-figures.json"
            alternate.write_bytes(original_inventory)
            with_alternate = list(figure_command)
            with_alternate[
                with_alternate.index(str(inventory))
            ] = str(alternate)
            inventory.chmod(0o644)
            inventory.write_text('{"changed":true}\n')
            drift_commands = (
                without_figure,
                with_alternate,
                figure_command,
            )
            for drifted_command in drift_commands:
                rejected = subprocess.run(
                    drifted_command, cwd=ROOT, text=True,
                    capture_output=True,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertTrue(
                    "identity conflict" in rejected.stderr
                    or "review material" in rejected.stderr
                )
                self.assertEqual(
                    {
                        str(item.relative_to(figure_root)): item.read_bytes()
                        for item in figure_root.rglob("*") if item.is_file()
                    },
                    frozen_figure_projection,
                )
            inventory.write_bytes(original_inventory)
            inventory.chmod(0o444)
            recovered = subprocess.run(
                figure_command, cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            self.assertEqual(
                json.loads((figure_root / "state.json").read_text())[
                    "active_stage_id"
                ],
                "stage_figures",
            )

    def test_figure_inventory_freezes_only_at_figure_stage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.init_policy(plan)
            self.initialize(plan)  # non-figure first stage has no inventory
            self.preflight(plan)
            self.authorize_fixture(plan)
            cycle = self.run_terminal_cycle(plan, "accept")
            report_path, worker_run_id = self.prepare_worker_report(
                plan, cycle, "b",
            )
            report = json.loads(self.invoke(
                "record-stage-report", "--plan-dir", str(plan),
                "--stage-report", str(report_path),
                "--worker-run-id", worker_run_id,
            ).stdout)
            self.apply_strong_review(plan, Path(report["path"]))
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
            figure_authorization = self.authorize_next_stage(plan, stage_path)
            proc = self.invoke(
                "compile-next-stage", "--plan-dir", str(plan),
                "--stage-envelope", str(stage_path),
                "--authorization-receipt", figure_authorization,
                "--authorized-evidence", "evidence_stage_1", ok=False,
            )
            self.assertIn("freeze exact figure requirements", proc.stderr)
            empty_inventory = self.write(
                plan / "inputs" / "empty-figure-requirements.json", {},
            )
            proc = self.invoke(
                "compile-next-stage", "--plan-dir", str(plan),
                "--stage-envelope", str(stage_path),
                "--authorization-receipt", figure_authorization,
                "--authorized-evidence", "evidence_stage_1",
                "--figure-requirements", str(empty_inventory), ok=False,
            )
            self.assertIn("figure requirements", proc.stderr)
            compiled = json.loads(self.invoke(
                "compile-next-stage", "--plan-dir", str(plan),
                "--stage-envelope", str(stage_path),
                "--authorized-evidence", "evidence_stage_1",
                "--figure-requirements", str(inventory),
                "--authorization-receipt", figure_authorization,
            ).stdout)
            self.assertEqual(compiled["next_stage_id"], "stage_figures")

    def test_staged_projection_rebuild_ignores_tampering_and_is_byte_stable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan)
            root = plan / "state" / "staged_research" / "v1"
            state_before = (root / "state.json").read_bytes()
            audit_before = (root / "audit.jsonl").read_bytes()
            progress = plan / "state" / "progress.json"
            dossier = plan / "state" / "research-dossier.md"
            canonical_progress = progress.read_bytes()
            canonical_dossier = dossier.read_bytes()
            progress.write_text('{"status":"forged","authoritative":true}\n')
            dossier.write_text("# forged authority\n")

            first = json.loads(self.invoke(
                "rebuild-staged-projections", "--plan-dir", str(plan),
            ).stdout)
            self.assertEqual(progress.read_bytes(), canonical_progress)
            self.assertEqual(dossier.read_bytes(), canonical_dossier)
            self.assertEqual((root / "state.json").read_bytes(), state_before)
            self.assertEqual((root / "audit.jsonl").read_bytes(), audit_before)
            second = json.loads(self.invoke(
                "rebuild-staged-projections", "--plan-dir", str(plan),
            ).stdout)
            self.assertEqual(first["progress_sha256"], second["progress_sha256"])
            self.assertEqual(first["dossier_sha256"], second["dossier_sha256"])
            view = json.loads(progress.read_text())
            self.assertFalse(view["authoritative"])
            self.assertEqual(
                view["canonical"]["audit_revision"],
                json.loads(state_before)["audit_revision"],
            )

    def test_legacy_v1_capacity_and_stage_budget_remain_readable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            legacy_envelope = self.envelope()
            legacy_envelope["stage_budget_and_stop"].pop("worker_dispatches")
            initialized = self.initialize(
                plan, envelope=legacy_envelope, capacity_value=self.capacity(),
            )
            self.assertEqual(initialized["state"], "CONTRACTED")
            preflight = self.preflight(plan)
            self.assertTrue(Path(preflight["preflight_path"]).is_file())
            ledger = json.loads((
                plan / "state" / "staged_research" / "v1" / "capacity-ledger.json"
            ).read_text())
            self.assertEqual(ledger["schema_version"], 1)

    def test_capacity_v2_keeps_worker_review_and_named_slots_isolated(self) -> None:
        spec = importlib.util.spec_from_file_location("capacity_v2_runtime", RUNTIME)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan, capacity_value=self.capacity_v2(workers=3, cp03=True))
            self.preflight(plan)
            self.authorize_fixture(plan)
            root = plan / "state" / "staged_research" / "v1"
            capacity_path = root / "capacity-ledger.json"

            runtime.staged_reserve_worker_dispatch_and_budget(
                plan.resolve(), dispatch_id="cwr_" + "d" * 32,
                usage={"tool_calls": 1, "worker_tokens": 10},
            )
            after_worker = json.loads(capacity_path.read_text())
            self.assertEqual(
                after_worker["worker_dispatch_capacity"],
                {"authorized_calls": 3, "spent_calls": 1, "remaining_calls": 2},
            )
            self.assertEqual(after_worker["stage_review_capacity"]["spent_calls"], 0)
            self.assertTrue(all(
                slot["spent"] == 0
                for slot in after_worker["checkpoint_capacity"].values()
            ))

            runtime.staged_reserve_dispatch(
                plan.resolve(), checkpoint="STAGE-REVIEW", dispatch_id="far_v2_review",
            )
            after_review = json.loads(capacity_path.read_text())
            self.assertEqual(
                after_review["worker_dispatch_capacity"],
                after_worker["worker_dispatch_capacity"],
            )
            self.assertEqual(after_review["stage_review_capacity"]["spent_calls"], 1)
            runtime.staged_reserve_dispatch(
                plan.resolve(), checkpoint="CP-03", dispatch_id="far_v2_cp03",
            )
            after_cp03 = json.loads(capacity_path.read_text())
            self.assertEqual(
                after_cp03["worker_dispatch_capacity"],
                after_worker["worker_dispatch_capacity"],
            )
            self.assertEqual(after_cp03["stage_review_capacity"], after_review["stage_review_capacity"])
            self.assertEqual(after_cp03["checkpoint_capacity"]["CP-03"]["spent"], 1)
            runtime.staged_reserve_worker_dispatch_and_budget(
                plan.resolve(), dispatch_id="cwr_" + "e" * 32,
                usage={"tool_calls": 1, "worker_tokens": 10},
            )
            before_rejected = capacity_path.read_bytes()
            with self.assertRaisesRegex(
                runtime.ContractError, "stage worker_dispatches capacity is exhausted",
            ):
                runtime.staged_reserve_worker_dispatch_and_budget(
                    plan.resolve(), dispatch_id="cwr_" + "f" * 32,
                    usage={"tool_calls": 1, "worker_tokens": 10},
                )
            self.assertEqual(capacity_path.read_bytes(), before_rejected)
            self.assertEqual(
                json.loads(capacity_path.read_text())["worker_dispatch_capacity"][
                    "remaining_calls"
                ],
                1,
            )

    def test_advance_staged_research_fault_retry_starts_one_second_stage_worker(self) -> None:
        for phase in ("continuation", "compile", "preflight", "authorize", "dispatch"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as td:
                plan = Path(td) / "plan"
                self.initialize(
                    plan, capacity_value=self.capacity_v2(workers=3),
                    continuation_stage_id="stage_2",
                )
                self.preflight(plan)
                self.apply_cp01(plan)
                cycle = self.run_terminal_cycle(plan, "accept")
                report_path, worker_run_id = self.prepare_worker_report(plan, cycle, "9")
                report = json.loads(self.invoke(
                    "record-stage-report", "--plan-dir", str(plan),
                    "--stage-report", str(report_path), "--worker-run-id", worker_run_id,
                ).stdout)
                self.apply_strong_review(plan, Path(report["path"]))
                stage2 = self.write(
                    plan / "inputs" / "stage-2.json",
                    self.envelope(
                        "stage_2", source="stage_1",
                        incumbent=cycle["resulting_incumbent_sha256"],
                    ),
                )
                preflight2 = self.write(
                    plan / "inputs" / "stage-2-preflight.json", self.raw_preflight(),
                )
                task = self.empty_worker_contract(plan, "stage_2")
                args = (
                    "advance-staged-research", "--plan-dir", str(plan),
                    "--stage-envelope", str(stage2),
                    "--preflight-inputs", str(preflight2),
                    "--task-contract", str(task),
                    "--authorized-evidence", "evidence_stage_1",
                    "--claude-bin", str(self.fake_claude(plan)),
                )
                env = dict(os.environ)
                env["HARNESS_FAULT_AFTER_STAGED_ADVANCE_PHASE"] = phase
                crashed = self.invoke(*args, ok=False, env=env)
                self.assertEqual(crashed.returncode, 89, crashed.stderr)
                advanced = json.loads(self.invoke(*args).stdout)
                replay = json.loads(self.invoke(*args).stdout)
                self.assertEqual(advanced["state"], "DEVELOPING")
                self.assertEqual(replay["worker_run_id"], advanced["worker_run_id"])
                root = plan / "state" / "staged_research" / "v1"
                state = json.loads((root / "state.json").read_text())
                self.assertEqual(state["active_stage_id"], "stage_2")
                self.assertEqual(state["state"], "DEVELOPING")
                runs = [
                    path for path in (plan / "state" / "worker_runs").glob("cwr_*")
                    if path.name == advanced["worker_run_id"]
                ]
                self.assertEqual(len(runs), 1)
                reservations = list((root / "dispatch-reservations").glob(
                    f"{advanced['worker_run_id']}.json"
                ))
                self.assertEqual(len(reservations), 1)
                capacity = json.loads((root / "capacity-ledger.json").read_text())
                self.assertEqual(capacity["worker_dispatch_capacity"]["spent_calls"], 1)
                receipts = list((root / "continuation-receipts").glob("*.json"))
                self.assertEqual(len(receipts), 1)
                audit = [
                    json.loads(line) for line in (root / "audit.jsonl").read_text().splitlines()
                    if line.strip()
                ]
                self.assertEqual(sum(
                    item.get("event") == "bounded_stage_crossing_completed"
                    for item in audit
                ), 1)

    def test_advance_staged_research_rejects_legacy_shared_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan, continuation_stage_id="stage_2")
            stage2 = self.write(
                plan / "inputs" / "stage-2.json",
                self.envelope("stage_2", source="stage_1"),
            )
            preflight2 = self.write(
                plan / "inputs" / "stage-2-preflight.json", self.raw_preflight(),
            )
            task = self.empty_worker_contract(plan, "stage_2")
            capacity_path = (
                plan / "state" / "staged_research" / "v1"
                / "capacity-ledger.json"
            )
            before = capacity_path.read_bytes()
            proc = self.invoke(
                "advance-staged-research", "--plan-dir", str(plan),
                "--stage-envelope", str(stage2),
                "--preflight-inputs", str(preflight2),
                "--task-contract", str(task),
                "--claude-bin", str(self.fake_claude(plan)), ok=False,
            )
            self.assertIn("requires separated capacity v2", proc.stderr)
            self.assertEqual(capacity_path.read_bytes(), before)

    def test_v2_frontier_topup_does_not_mint_worker_or_checkpoint_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan"
            self.initialize(plan, capacity_value=self.capacity_v2(workers=3, cp03=True))
            root = plan / "state" / "staged_research" / "v1"
            capacity_path = root / "capacity-ledger.json"
            before = json.loads(capacity_path.read_text())
            created = json.loads(self.invoke(
                "create-human-action", "--plan-dir", str(plan),
                "--plan-id", "plan_staged", "--action", "authorize_frontier_capacity",
                "--key-file", str(plan / "owner.key"), "--expires-in", "3600",
                "--record-id", "har_v2_frontier_only", "--actor", "research-owner",
                "--add-frontier-calls", "2",
                "--add-frontier-input-tokens", "10000",
                "--add-frontier-output-tokens", "1000",
            ).stdout)
            self.invoke(
                "apply-human-action", "--plan-dir", str(plan),
                "--record", created["record_path"],
                "--key-file", str(plan / "owner.key"),
                "--expected-action", "authorize_frontier_capacity",
            )
            after = json.loads(capacity_path.read_text())
            self.assertEqual(
                after["worker_dispatch_capacity"], before["worker_dispatch_capacity"],
            )
            self.assertEqual(after["stage_review_capacity"], before["stage_review_capacity"])
            self.assertEqual(after["checkpoint_capacity"], before["checkpoint_capacity"])
            self.assertEqual(after["capacity_authorization_ids"], ["har_v2_frontier_only"])


if __name__ == "__main__":
    unittest.main()
