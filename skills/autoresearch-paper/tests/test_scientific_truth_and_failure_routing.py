#!/usr/bin/env python3
"""M3 tests for scientific acceptance and integrity failure routing."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_claude_cutover_e2e as cutover
import test_evaluator_admission as admission_tests


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "references" / "scripts" / "harness-runtime.py"
RUNNER = ROOT / "references" / "scripts" / "run-claude-harness.py"
WORKFLOW = ROOT / "references" / "canonical-conformance-workflow.json"


class ScientificTruthAndFailureRoutingTests(unittest.TestCase):
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

    def run_through_writing_gate(
        self, root: Path,
    ) -> tuple[Path, dict[str, str]]:
        helper = cutover.ClaudeCutoverE2E(methodName="runTest")
        plan, inputs_path, _, _ = helper.prepare(root)
        proc = subprocess.run(
            [
                sys.executable, str(RUNNER),
                "--plan-dir", str(plan),
                "--workflow", str(WORKFLOW),
                "--inputs", str(inputs_path),
                "--simulate-crash-after-step", "writing_gate",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        return plan, json.loads(inputs_path.read_text())

    def install_conference_graph(
        self, plan: Path, evaluator: Path,
    ) -> Path:
        objective = plan / "m3-objective.md"
        constraints = plan / "m3-constraints.json"
        task_contract = plan / "m3-task.json"
        task_input = plan / "m3-input.json"
        objective.write_text("retain the frozen research objective\n")
        constraints.write_text('{"budget":"fixed"}\n')
        task_contract.write_text('{"schema_version":1,"task_id":"m3-task"}\n')
        task_input.write_text('{"candidate":"canonical_final"}\n')
        graph = plan / "m3-durable-plan.json"
        graph.write_text(json.dumps({
            "schema_version": 1,
            "plan_id": "plan_e2e",
            "target_tier": "conference",
            "execution_mode": "unattended",
            "objective": {"path": str(objective), "sha256": self.sha(objective)},
            "constraints": {"path": str(constraints), "sha256": self.sha(constraints)},
            "evaluator": {"path": str(evaluator), "sha256": self.sha(evaluator)},
            "tasks": [{
                "task_id": "m3-task",
                "phase": "research",
                "depends_on": [],
                "task_contract": {
                    "path": str(task_contract),
                    "sha256": self.sha(task_contract),
                },
                "inputs": [{
                    "path": str(task_input),
                    "sha256": self.sha(task_input),
                    "purpose": "candidate",
                }],
            }],
        }, indent=2))
        self.call(
            "init-durable-plan", "--plan-dir", str(plan), "--graph", str(graph),
        )
        return graph

    def admit_evaluator(self, plan: Path, evaluator: Path) -> dict[str, object]:
        authority = plan / "state" / "evaluator_contract.json"
        validation = plan / "m3-validation.json"
        validation.write_text('{"metric":"score","operator":"gte","threshold":0.8}\n')
        source = plan / "m3-admission-input.json"
        source.write_text('{"fixed":true}\n')
        manifest = plan / "m3-admission-manifest.json"
        manifest.write_text(json.dumps({
            "schema_version": 1,
            "artifacts": [{
                "path": str(source),
                "sha256": self.sha(source),
                "purpose": "immutable evaluator input",
            }],
        }))
        verdict_hash = "c" * 64
        replay = plan / "m3-replay.json"
        replay.write_text(json.dumps({
            "schema_version": 1,
            "evaluator_sha256": self.sha(evaluator),
            "input_manifest_sha256": self.sha(manifest),
            "first_verdict_sha256": verdict_hash,
            "second_verdict_sha256": verdict_hash,
            "status": "PASS",
        }))
        regression = plan / "m3-regression.json"
        regression.write_text(json.dumps({
            "schema_version": 1,
            "evaluator_sha256": self.sha(evaluator),
            "status": "PASS",
            "failed_tests": 0,
            "total_tests": 4,
        }))
        search_space = plan / "m3-search-space.json"
        search_space.write_text('{"allowed":["method"],"forbidden":["evaluator"]}\n')
        contract = plan / "m3-admission-contract.json"
        contract.write_text(json.dumps({
            "schema_version": 1,
            "plan_id": "plan_e2e",
            "evaluator_class": "hard_metric",
            "evaluator_sha256": self.sha(evaluator),
            "authority": {
                "kind": "controller_owned",
                "identity_sha256": self.sha(authority),
            },
            "input_manifest_sha256": self.sha(manifest),
            "validation_identity": {
                "kind": "metric",
                "sha256": self.sha(validation),
            },
            "replay_identity_sha256": self.sha(replay),
            "regression_suite_sha256": self.sha(regression),
            "allowed_search_space_sha256": self.sha(search_space),
            "complexity_policy": {
                "kind": "not_applicable",
                "identity_sha256": None,
                "rationale": "The frozen scalar metric has no complexity degree of freedom.",
            },
            "autonomy_tiers": ["conference_unattended"],
            "admitted_by": "controller",
            "admitted_at": "replaced",
        }, indent=2))
        return json.loads(self.call(
            "admit-evaluator",
            "--plan-dir", str(plan),
            "--contract", str(contract),
            "--evaluator", str(evaluator),
            "--authority-identity", str(authority),
            "--input-manifest", str(manifest),
            "--validation-identity", str(validation),
            "--replay-identity", str(replay),
            "--regression-suite", str(regression),
            "--allowed-search-space", str(search_space),
        ).stdout)

    def test_scientific_acceptance_replays_machine_truth_and_current_admission(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, inputs = self.run_through_writing_gate(root)
            pass_verdict = plan / "state" / "evaluator_verdicts" / "canonical_final.json"
            fail_verdict = plan / "state" / "evaluator_verdicts" / "canonical_failure_1.json"
            existing = json.loads(self.call(
                "check-scientific-acceptance",
                "--plan-dir", str(plan),
                "--verdict", str(pass_verdict),
            ).stdout)
            self.assertTrue(existing["idempotent"])
            self.assertEqual(existing["decision"], "PASS")
            failed = json.loads(self.call(
                "check-scientific-acceptance",
                "--plan-dir", str(plan),
                "--verdict", str(fail_verdict),
            ).stdout)
            self.assertEqual(failed["decision"], "FAIL")

            frozen_contract = json.loads(
                (plan / "state" / "evaluator_contract.json").read_text()
            )
            evaluator = Path(frozen_contract["evaluator_path"])
            self.install_conference_graph(plan, evaluator)
            blocked = self.call(
                "check-scientific-acceptance",
                "--plan-dir", str(plan),
                "--verdict", str(pass_verdict),
                check=False,
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("unattended autonomy is blocked", blocked.stderr)
            admission = self.admit_evaluator(plan, evaluator)
            admitted = json.loads(self.call(
                "check-scientific-acceptance",
                "--plan-dir", str(plan),
                "--verdict", str(pass_verdict),
            ).stdout)
            self.assertEqual(
                admitted["evaluator_admission_id"], admission["admission_id"],
            )
            regression_path = Path(admission["materials"]["regression_suite"]["path"])
            regression_path.write_text('{"status":"worker-mutated"}\n')
            revoked = self.call(
                "check-scientific-acceptance",
                "--plan-dir", str(plan),
                "--verdict", str(pass_verdict),
                check=False,
            )
            self.assertEqual(revoked.returncode, 2)
            self.assertIn("unattended autonomy is blocked", revoked.stderr)

    def test_integrity_drift_has_isolated_controller_owned_routes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            helper = admission_tests.EvaluatorAdmissionTests(methodName="runTest")
            helper.setUp()
            plan, _ = helper.conference_plan(root)
            _, admit_args = helper.admission_materials(plan)
            self.call(*admit_args)
            clean = json.loads(self.call(
                "check-research-integrity", "--plan-dir", str(plan),
            ).stdout)
            self.assertEqual(clean["integrity"], "PASS")

            graph = json.loads(
                (plan / "state" / "durable_loop" / "canonical" / "graph.json").read_text()
            )
            objective = Path(graph["objective"]["path"])
            evaluator = Path(graph["evaluator"]["path"])
            objective.write_text("worker drifted objective\n")
            evaluator.chmod(0o644)
            evaluator.write_text('{"kind":"worker-mutated"}\n')
            boundary = self.call(
                "advance-durable-plan", "--plan-dir", str(plan), check=False,
            )
            self.assertEqual(boundary.returncode, 2)
            blocked = json.loads(self.call(
                "check-research-integrity", "--plan-dir", str(plan),
            ).stdout)
            self.assertEqual(blocked["integrity"], "BLOCKED")
            self.assertEqual(
                {item["failure_class"] for item in blocked["findings"]},
                {"goal_drift", "evaluator_integrity"},
            )
            repeated = json.loads(self.call(
                "check-research-integrity", "--plan-dir", str(plan),
            ).stdout)
            self.assertTrue(all(item["idempotent"] for item in blocked["findings"]))
            self.assertTrue(all(item["idempotent"] for item in repeated["findings"]))
            state = repeated["state"]
            self.assertEqual(state["goal_drift_count"], 1)
            self.assertEqual(state["evaluator_integrity_count"], 1)
            self.assertEqual(state["runtime_stall_count"], 0)
            self.assertEqual(state["scientific_no_improvement_count"], 0)
            forged = self.call(
                "record-failure",
                "--plan-dir", str(plan),
                "--class", "goal_drift",
                "--fingerprint", "model-authored-label",
                "--source", "worker",
                check=False,
            )
            self.assertEqual(forged.returncode, 2)


if __name__ == "__main__":
    unittest.main()
