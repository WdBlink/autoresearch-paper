#!/usr/bin/env python3
"""Focused T002-A tests for executable evaluator admission and autonomy blocking."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_durable_loop_runtime as durable_tests


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "references" / "scripts" / "harness-runtime.py"


class EvaluatorAdmissionTests(unittest.TestCase):
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

    def conference_plan(self, root: Path) -> tuple[Path, Path]:
        plan = self.helper.ready_plan(root)
        graph = self.helper.graph(plan)
        value = json.loads(graph.read_text())
        value["target_tier"] = "conference"
        value["execution_mode"] = "unattended"
        graph.write_text(json.dumps(value, indent=2))
        self.call("init-durable-plan", "--plan-dir", str(plan), "--graph", str(graph))
        return plan, graph

    def admission_materials(
        self, plan: Path, *, replay_match: bool = True, evaluator_class: str = "hard_metric",
    ) -> tuple[Path, list[str]]:
        evaluator = plan / "evaluator.json"
        evaluator.chmod(0o444)
        authority = plan / "external-evaluator-authority.json"
        authority.write_text('{"owner":"external-benchmark","mutable_by_worker":false}\n')
        authority.chmod(0o444)
        validation = plan / "validation-metric.json"
        validation.write_text('{"metric":"score","operator":"gte","threshold":1}\n')
        source_input = plan / "admission-input.json"
        source_input.write_text('{"fixed":true}\n')
        input_manifest = plan / "admission-input-manifest.json"
        input_manifest.write_text(json.dumps({
            "schema_version": 1,
            "artifacts": [{
                "path": str(source_input),
                "sha256": self.sha(source_input),
                "purpose": "immutable evaluator input",
            }],
        }, indent=2))
        verdict_hash = "a" * 64
        replay = plan / "evaluator-replay.json"
        replay.write_text(json.dumps({
            "schema_version": 1,
            "evaluator_sha256": self.sha(evaluator),
            "input_manifest_sha256": self.sha(input_manifest),
            "first_verdict_sha256": verdict_hash,
            "second_verdict_sha256": verdict_hash if replay_match else "b" * 64,
            "status": "PASS",
        }, indent=2))
        regression = plan / "evaluator-regression.json"
        regression.write_text(json.dumps({
            "schema_version": 1,
            "evaluator_sha256": self.sha(evaluator),
            "status": "PASS",
            "failed_tests": 0,
            "total_tests": 3,
        }, indent=2))
        search_space = plan / "allowed-search-space.json"
        search_space.write_text('{"allowed":["method-parameters"],"forbidden":["evaluator"]}\n')
        autonomy_tiers = (
            ["conference_unattended"] if evaluator_class != "human_review"
            else ["conference_unattended"]
        )
        contract = plan / "evaluator-admission-draft.json"
        contract.write_text(json.dumps({
            "schema_version": 1,
            "plan_id": "plan_abc",
            "evaluator_class": evaluator_class,
            "evaluator_sha256": self.sha(evaluator),
            "authority": {
                "kind": "external_readonly",
                "identity_sha256": self.sha(authority),
            },
            "input_manifest_sha256": self.sha(input_manifest),
            "validation_identity": {
                "kind": "human_record" if evaluator_class == "human_review" else "metric",
                "sha256": self.sha(validation),
            },
            "replay_identity_sha256": self.sha(replay),
            "regression_suite_sha256": self.sha(regression),
            "allowed_search_space_sha256": self.sha(search_space),
            "complexity_policy": {
                "kind": "not_applicable",
                "identity_sha256": None,
                "rationale": "The frozen metric has no model-size or program-size degree of freedom."
            },
            "autonomy_tiers": autonomy_tiers,
            "admitted_by": "controller",
            "admitted_at": "caller-value-is-replaced",
        }, indent=2))
        args = [
            "admit-evaluator",
            "--plan-dir", str(plan),
            "--contract", str(contract),
            "--evaluator", str(evaluator),
            "--authority-identity", str(authority),
            "--input-manifest", str(input_manifest),
            "--validation-identity", str(validation),
            "--replay-identity", str(replay),
            "--regression-suite", str(regression),
            "--allowed-search-space", str(search_space),
        ]
        return contract, args

    def test_unattended_conference_is_blocked_then_admitted_and_drift_revokes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, _ = self.conference_plan(root)
            launchctl, _ = self.helper.fake_launchctl(root)
            blocked = self.call(
                "check-autonomy-eligibility", "--plan-dir", str(plan), check=False,
            )
            self.assertEqual(blocked.returncode, 2)
            register_blocked = self.call(
                "register-durable-trigger",
                "--plan-dir", str(plan),
                "--interval-seconds", "60",
                "--session-budget-seconds", "600",
                "--human-escalation-after-seconds", "300",
                "--launchctl-bin", str(launchctl),
                check=False,
            )
            self.assertEqual(register_blocked.returncode, 2)

            _, args = self.admission_materials(plan)
            admitted = json.loads(self.call(*args).stdout)
            repeated = json.loads(self.call(*args).stdout)
            self.assertTrue(repeated["idempotent"])
            self.assertEqual(admitted["admission_id"], repeated["admission_id"])
            eligible = json.loads(self.call(
                "check-autonomy-eligibility", "--plan-dir", str(plan),
            ).stdout)
            self.assertTrue(eligible["eligible"])
            self.assertEqual(eligible["admission_id"], admitted["admission_id"])
            self.helper.register(plan, launchctl)

            evaluator = plan / "evaluator.json"
            evaluator.chmod(0o644)
            evaluator.write_text('{"kind":"worker-mutated"}\n')
            revoked = self.call(
                "check-autonomy-eligibility", "--plan-dir", str(plan), check=False,
            )
            self.assertEqual(revoked.returncode, 2)
            self.assertIn("hash mismatch", revoked.stderr)
            tick = self.call(
                "run-durable-tick",
                "--plan-dir", str(plan),
                "--observed-at", "2026-07-23T00:00:00Z",
                check=False,
            )
            self.assertEqual(tick.returncode, 2)
            audit = (
                plan / "state" / "evaluator_admission" / "audit.jsonl"
            ).read_text()
            self.assertIn("evaluator_admission_invalidated", audit)

    def test_replay_human_review_and_writable_authority_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, _ = self.conference_plan(root)
            _, replay_args = self.admission_materials(plan, replay_match=False)
            replay = self.call(*replay_args, check=False)
            self.assertEqual(replay.returncode, 2)
            self.assertIn("did not reproduce", replay.stderr)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, _ = self.conference_plan(root)
            _, human_args = self.admission_materials(plan, evaluator_class="human_review")
            human = self.call(*human_args, check=False)
            self.assertEqual(human.returncode, 2)
            self.assertIn("human review cannot admit unattended autonomy", human.stderr)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, _ = self.conference_plan(root)
            _, writable_args = self.admission_materials(plan)
            (plan / "evaluator.json").chmod(0o644)
            writable = self.call(*writable_args, check=False)
            self.assertEqual(writable.returncode, 2)
            self.assertIn("filesystem read-only", writable.stderr)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, _ = self.conference_plan(root)
            contract, circular_args = self.admission_materials(plan)
            evaluator = plan / "evaluator.json"
            draft = json.loads(contract.read_text())
            draft["authority"]["identity_sha256"] = self.sha(evaluator)
            contract.write_text(json.dumps(draft, indent=2))
            authority_index = circular_args.index("--authority-identity") + 1
            circular_args[authority_index] = str(evaluator)
            circular = self.call(*circular_args, check=False)
            self.assertEqual(circular.returncode, 2)
            self.assertIn("authority identity must be independent", circular.stderr)


if __name__ == "__main__":
    unittest.main()
