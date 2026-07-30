#!/usr/bin/env python3
"""T031 installed Codex Host closed-brief entry contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "references" / "scripts" / "harness-runtime.py"
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import test_durable_loop_runtime as durable_tests
import test_staged_research_governance as staged_tests


class CodexHostEntryTests(unittest.TestCase):
    def call(
        self, runtime: Path, *args: str, check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [sys.executable, str(runtime), *args],
            cwd=runtime.parents[2], text=True, capture_output=True,
            env={**os.environ, **(env or {})},
        )
        if check and proc.returncode != 0:
            self.fail(f"command failed: {args}\nstdout={proc.stdout}\nstderr={proc.stderr}")
        return proc

    @staticmethod
    def fake_claude(root: Path) -> Path:
        path = root / "claude"
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
        return path

    @staticmethod
    def brief(root: Path) -> dict[str, object]:
        code = root / "code"
        materials = root / "materials"
        plans = root / "plans"
        for path in (code, materials, plans):
            path.mkdir()
        baseline = materials / "baseline.json"
        evaluator = code / "evaluate.py"
        baseline.write_text('{"score": 1.0}\n')
        evaluator.write_text("print('score')\n")
        return {
            "schema_version": 1,
            "objective": "Improve fixed-window visual guidance over the frozen baseline.",
            "target_tier": "conference",
            "target_venue": "ICRA",
            "candidate_ideas": ["Calibrated temporal fusion"],
            "code_roots": [str(code)],
            "material_roots": [str(materials)],
            "initial_direction": "Start with a bounded observation stage.",
            "strongest_comparable_baseline": {
                "name": "Frozen FWVG baseline",
                "evidence_paths": [str(baseline)],
                "comparison_scope": "Same data, evaluator, seeds, and harness.",
            },
            "evaluator_metric_context": {
                "primary_metric": "success_rate",
                "optimization_direction": "maximize",
                "improvement_margin": 0.01,
                "uncertainty_rule": "95% bootstrap interval excludes zero.",
                "evaluator_paths": [str(evaluator)],
            },
            "resource_bounds": {
                "wall_clock_seconds": 7200,
                "worker_dispatches": 4,
                "worker_max_budget_usd": 1.0,
                "frontier_calls": 6,
                "frontier_input_tokens": 900000,
                "frontier_output_tokens": 30000,
            },
            "permissions": {
                "owner_id": "wdblink",
                "owned_write_roots": [str(plans)],
                "allowed_read_roots": [str(root)],
                "network_access": True,
                "external_model_calls": True,
                "unattended_execution": True,
            },
            "stop_conditions": [
                "Stop on exhausted declared capacity.",
                "Pause on new authority or provider quota.",
            ],
        }

    def prepare(
        self, runtime: Path, root: Path, brief: dict[str, object],
    ) -> tuple[Path, dict[str, object]]:
        source = root / "brief.json"
        source.write_text(json.dumps(brief, indent=2) + "\n")
        plan = Path(brief["permissions"]["owned_write_roots"][0]) / "plan-t031"
        result = self.call(
            runtime, "prepare-codex-host-plan",
            "--brief", str(source), "--plan-dir", str(plan),
            "--claude-bin", str(self.fake_claude(root)),
        )
        return plan, json.loads(result.stdout)

    def test_valid_closed_brief_is_published_atomically_and_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            brief = self.brief(root)
            plan, prepared = self.prepare(RUNTIME, root, brief)
            self.assertEqual(prepared["status"], "PREPARED")
            self.assertEqual(prepared["plan_id"], "plan_" + hashlib.sha256(
                json.dumps(
                    brief, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                ).encode()
            ).hexdigest()[:24])
            for field in (
                "closed_brief_path", "model_policy_path",
                "worker_session_policy_path", "initial_planning_request_path",
                "resource_manifest_initial_path",
            ):
                path = Path(prepared[field])
                self.assertTrue(path.is_file())
                self.assertEqual(path.stat().st_mode & 0o777, 0o444)
            planning = json.loads(Path(prepared["initial_planning_request_path"]).read_text())
            self.assertEqual(planning["author_runtime"], "codex")
            self.assertEqual(planning["executable_stage_limit"], 1)
            session = json.loads(Path(prepared["worker_session_policy_path"]).read_text())
            self.assertEqual(session["session_mode"], "persistent_exact_resume")
            source = root / "brief.json"
            again = self.call(
                RUNTIME, "prepare-codex-host-plan",
                "--brief", str(source), "--plan-dir", str(plan),
                "--claude-bin", str(root / "claude"),
            )
            self.assertTrue(json.loads(again.stdout)["idempotent"])

    def test_invalid_brief_reports_exact_field_without_plan_mutation(self) -> None:
        cases = (
            ("missing", lambda value: value.pop("objective"), "$.objective is required"),
            (
                "unowned",
                lambda value: value["permissions"].update(
                    {"owned_write_roots": [value["code_roots"][0]]}
                ),
                "plan_dir is outside $.permissions.owned_write_roots",
            ),
            (
                "unbounded",
                lambda value: value["resource_bounds"].update(
                    {"frontier_input_tokens": 1}
                ),
                "$.resource_bounds.frontier_input_tokens",
            ),
            (
                "path-invalid",
                lambda value: value.update({"code_roots": ["relative/code"]}),
                "$.code_roots[0] must be a canonical absolute path",
            ),
        )
        for label, mutate, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve()
                brief = self.brief(root)
                mutate(brief)
                source = root / "brief.json"
                source.write_text(json.dumps(brief) + "\n")
                plan = root / "plans" / "must-not-exist"
                proc = self.call(
                    RUNTIME, "prepare-codex-host-plan",
                    "--brief", str(source), "--plan-dir", str(plan),
                    "--claude-bin", str(self.fake_claude(root)), check=False,
                )
                self.assertEqual(proc.returncode, 2)
                self.assertIn(expected, proc.stderr)
                self.assertFalse(plan.exists())

    def test_installed_copy_runs_the_real_entry_without_repository_parents(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            installed = root / ".agents" / "skills" / "autoresearch-paper"
            shutil.copytree(ROOT, installed, ignore=shutil.ignore_patterns("node_modules"))
            brief = self.brief(root)
            plan, prepared = self.prepare(
                installed / "references" / "scripts" / "harness-runtime.py",
                root, brief,
            )
            self.assertTrue(plan.is_dir())
            self.assertEqual(prepared["status"], "PREPARED")
            self.assertFalse((installed.parents[2] / "README.md").exists())

    def test_authenticated_activation_binds_first_stage_and_fixed_session_policy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            plan, entry = self.prepare(RUNTIME, root, self.brief(root))
            plan_id = entry["plan_id"]
            staged = staged_tests.StagedResearchGovernanceTests(methodName="runTest")
            incumbent = staged_tests.digest("t031-incumbent")
            gate = staged.write(
                plan / "control" / "staged-inputs" / "gate-evaluator.json",
                {"schema_version": 1, "kind": "isolated-gate-evaluator-v1"},
            )
            contract_value = staged.contract()
            contract_value.update({
                "contract_version": "contract_t031_v1",
                "authorization_receipt_id": "har_t031_activation",
                "acceptance_evaluator_sha256": hashlib.sha256(gate.read_bytes()).hexdigest(),
            })
            contract = staged.write(
                plan / "control" / "staged-inputs" / "contract.json", contract_value,
            )
            envelope_value = staged.envelope("stage_t031", incumbent=incumbent)
            envelope_value["contract_version"] = "contract_t031_v1"
            envelope = staged.write(
                plan / "control" / "staged-inputs" / "stage.json", envelope_value,
            )
            evaluation = staged.write(
                plan / "control" / "staged-inputs" / "evaluation.json",
                staged.evaluation_profile(),
            )
            capacity = staged.write(
                plan / "control" / "staged-inputs" / "capacity.json",
                staged.capacity_v2(workers=3),
            )
            prepared = json.loads(self.call(
                RUNTIME, "prepare-staged-research",
                "--plan-dir", str(plan), "--plan-id", plan_id,
                "--contract", str(contract), "--stage-envelope", str(envelope),
                "--evaluation-profile", str(evaluation),
                "--checkpoint-capacity", str(capacity),
                "--incumbent-sha256", incumbent,
                "--record-id", "har_t031_activation",
                "--prepared-operation-id", "prepare_t031_activation",
                "--continuation-stage-id", "stage_t032",
            ).stdout)
            key = root / "owner.key"
            key.write_bytes(b"x" * 32)
            key.chmod(0o600)
            created = json.loads(self.call(
                RUNTIME, "create-human-action", "--plan-dir", str(plan),
                "--plan-id", plan_id, "--action", "authorize_contract",
                "--key-file", str(key), "--expires-in", "3600",
                "--record-id", prepared["record_id"], "--actor", "owner",
                "--contract-version", prepared["contract_version"],
                "--stage-id", prepared["stage_id"],
                "--contract-sha256", prepared["contract_sha256"],
                "--stage-envelope-sha256", prepared["stage_envelope_sha256"],
                "--continuation-stage-id", prepared["continuation_stage_id"],
                "--continuation-stage-limit", "1",
                "--authorization-proposal", prepared["authorization_proposal_path"],
                "--prepared-operation-id", prepared["prepared_operation_id"],
            ).stdout)
            applied = json.loads(self.call(
                RUNTIME, "apply-human-action", "--plan-dir", str(plan),
                "--record", created["record_path"], "--key-file", str(key),
                "--expected-action", "authorize_contract",
            ).stdout)
            preflight = staged.write(
                plan / "control" / "staged-inputs" / "preflight.json",
                staged.raw_preflight(),
            )
            durable = durable_tests.DurableLoopRuntimeTests(methodName="runTest")
            durable.base = durable_tests.runtime_contracts.RuntimeContracts(methodName="runTest")
            graph = durable.graph(plan)
            graph_value = json.loads(graph.read_text())
            graph_value["plan_id"] = plan_id
            graph.write_text(json.dumps(graph_value, indent=2) + "\n")
            for path in (contract, envelope, evaluation, capacity, preflight, graph):
                path.chmod(0o444)
            activated = json.loads(self.call(
                RUNTIME, "activate-codex-host-plan",
                "--plan-dir", str(plan),
                "--prepared-receipt", str(
                    plan / "control" / "codex-host-entry" / "v1" / "prepared-receipt.json"
                ),
                "--authorization-receipt", applied["receipt"]["receipt_path"],
                "--contract", str(contract), "--stage-envelope", str(envelope),
                "--evaluation-profile", str(evaluation),
                "--checkpoint-capacity", str(capacity),
                "--preflight-inputs", str(preflight), "--graph", str(graph),
                "--incumbent-sha256", incumbent,
            ).stdout)
            self.assertEqual(activated["status"], "ACTIVATED")
            self.assertEqual(activated["staged_state"], "CONTRACTED")
            self.assertEqual(
                activated["worker_session_policy_sha256"],
                entry["worker_session_policy_sha256"],
            )
            again = json.loads(self.call(
                RUNTIME, "activate-codex-host-plan",
                "--plan-dir", str(plan),
                "--prepared-receipt", str(
                    plan / "control" / "codex-host-entry" / "v1" / "prepared-receipt.json"
                ),
                "--authorization-receipt", applied["receipt"]["receipt_path"],
                "--contract", str(contract), "--stage-envelope", str(envelope),
                "--evaluation-profile", str(evaluation),
                "--checkpoint-capacity", str(capacity),
                "--preflight-inputs", str(preflight), "--graph", str(graph),
                "--incumbent-sha256", incumbent,
            ).stdout)
            self.assertTrue(again["idempotent"])
            staged_root = plan / "state" / "staged_research" / "v1"
            cp01_args = [
                "create-frontier-request", "--plan-dir", str(plan),
                "--plan-id", plan_id, "--checkpoint", "CP-01",
                "--objective", "audit Codex-authored first stage",
                "--decision-required", "approve_execution",
                "--max-input-tokens", "150000", "--max-output-tokens", "5000",
                "--request-id", "far_t031_activation",
            ]
            for role, path in {
                "optimization_contract": staged_root / "contracts" / "contract_t031_v1.json",
                "first_stage_envelope": staged_root / "stages" / "stage_t031" / "envelope.json",
                "current_stage_preflight": staged_root / "stages" / "stage_t031" / "preflight.json",
                "checkpoint_capacity": staged_root / "checkpoint-capacity.json",
            }.items():
                cp01_args += ["--artifact", f"{path}::{role}"]
            created_cp01 = json.loads(self.call(RUNTIME, *cp01_args).stdout)
            cp01 = json.loads(Path(created_cp01["request_path"]).read_text())
            roles = {item["purpose"] for item in cp01["context_manifest"]}
            self.assertIn(
                "execution_dependency:host_preparation_receipt", roles,
            )
            self.assertIn(
                "execution_dependency:host_activation_receipt", roles,
            )
            self.assertIn(
                "execution_dependency:lifecycle_implementation", roles,
            )
            self.assertIn(
                "execution_dependency:lifecycle_conformance", roles,
            )
            self.assertTrue(any(
                role.startswith("execution_dependency:task_contract:")
                for role in roles
            ))
            self.call(
                RUNTIME, "send-frontier-request", "--plan-dir", str(plan),
                "--request-id", "far_t031_activation",
                "--codex-bin", str(staged.fake_codex(plan)),
            )
            self.call(
                RUNTIME, "validate-frontier-response", "--plan-dir", str(plan),
                "--request-id", "far_t031_activation",
            )
            self.call(
                RUNTIME, "apply-frontier-response", "--plan-dir", str(plan),
                "--request-id", "far_t031_activation",
                "--dependent-transition", "approve_execution",
                "--controller-note", "controller accepted bounded CP-01 advice",
            )
            launchctl, _ = durable.multi_service_launchctl(root)
            bootstrapped = json.loads(self.call(
                RUNTIME, "bootstrap-host-runtime", "--plan-dir", str(plan),
                "--graph", str(graph), "--interval-seconds", "300",
                "--jitter-seconds", "0", "--session-budget-seconds", "600",
                "--human-escalation-after-seconds", "300",
                "--lease-seconds", "30", "--health-interval-seconds", "300",
                "--worker-stale-seconds", "1200",
                "--frontier-stale-seconds", "1200",
                "--heartbeat-stale-seconds", "600",
                "--dashboard-port", "8765", "--launchctl-bin", str(launchctl),
            ).stdout)
            self.assertEqual(bootstrapped["status"], "READY")
            self.assertEqual(
                bootstrapped["entry_activation_receipt_sha256"],
                hashlib.sha256(
                    (plan / "state" / "codex_host_entry" / "v1" / "activation-receipt.json")
                    .read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(
                bootstrapped["closed_brief_sha256"], entry["closed_brief_sha256"]
            )
            retry = json.loads(self.call(
                RUNTIME, "bootstrap-host-runtime", "--plan-dir", str(plan),
                "--graph", str(graph), "--interval-seconds", "300",
                "--jitter-seconds", "0", "--session-budget-seconds", "600",
                "--human-escalation-after-seconds", "300",
                "--lease-seconds", "30", "--health-interval-seconds", "300",
                "--worker-stale-seconds", "1200",
                "--frontier-stale-seconds", "1200",
                "--heartbeat-stale-seconds", "600",
                "--dashboard-port", "8765", "--launchctl-bin", str(launchctl),
            ).stdout)
            self.assertTrue(retry["idempotent"])


if __name__ == "__main__":
    unittest.main()
