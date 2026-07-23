#!/usr/bin/env python3
"""T007 production transport tests for durable worker/frontier bindings."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_runtime_contracts as runtime_contracts


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "references" / "scripts" / "harness-runtime.py"


class ProductionTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = runtime_contracts.RuntimeContracts(methodName="runTest")

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

    def call_concurrently(self, *args: str) -> list[dict[str, object]]:
        argv = [sys.executable, str(RUNTIME), *args]
        processes = [
            subprocess.Popen(
                argv, cwd=ROOT, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            for _ in range(2)
        ]
        results: list[dict[str, object]] = []
        for process in processes:
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                self.fail(
                    f"concurrent command failed: {args}\n"
                    f"stdout={stdout}\nstderr={stderr}"
                )
            results.append(json.loads(stdout))
        return results

    @staticmethod
    def artifact(path: Path, purpose: str | None = None) -> dict[str, str]:
        item = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        if purpose is not None:
            item["purpose"] = purpose
        return item

    def ready_plan(self, root: Path) -> Path:
        plan = self.base.make_plan(root / "plan")
        self.base.write_manifest(plan)
        self.base.init_model_policy(plan)
        self.base.approve_cp01(plan, root)
        return plan

    def durable_graph(
        self,
        plan: Path,
        *,
        task_id: str,
        contract: Path,
        inputs: list[dict[str, str]],
    ) -> Path:
        objective = plan / f"{task_id}-objective.md"
        constraints = plan / f"{task_id}-constraints.json"
        evaluator = plan / f"{task_id}-evaluator.json"
        objective.write_text("bounded production task\n")
        constraints.write_text('{"budget":"bounded"}\n')
        evaluator.write_text('{"kind":"controller-verified"}\n')
        graph = plan / f"{task_id}-durable-plan.json"
        graph.write_text(json.dumps({
            "schema_version": 1,
            "plan_id": "plan_abc",
            "target_tier": "arxiv",
            "execution_mode": "unattended",
            "objective": self.artifact(objective),
            "constraints": self.artifact(constraints),
            "evaluator": self.artifact(evaluator),
            "tasks": [{
                "task_id": task_id,
                "phase": "research",
                "depends_on": [],
                "task_contract": self.artifact(contract),
                "inputs": inputs,
            }],
        }, indent=2))
        return graph

    def fake_artifact_worker(self, root: Path, target: Path) -> Path:
        executable = root / "fake-claude-production"
        content = '{"score":0.91}\n'
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import hashlib,json,sys\n"
            "prompt=json.load(sys.stdin)\n"
            f"content={content!r};target={str(target)!r}\n"
            "proposal={'artifact_id':'candidate','path':target,'content':content,"
            "'sha256':hashlib.sha256(content.encode()).hexdigest()}\n"
            "json.dump({'structured_output':{'summary':'bounded result','ok':True,"
            "'artifacts':[proposal]}},sys.stdout)\n"
        )
        executable.chmod(0o755)
        return executable

    def test_minimax_worker_is_capsule_bound_and_commits_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.ready_plan(root)
            task_id = "worker-task"
            source = plan / "worker-input.json"
            source.write_text('{"seed":7}\n')
            output = plan / "artifacts" / "intermediate" / task_id / "candidate.json"
            contract = plan / "worker-task-contract.json"
            output_schema = {
                "type": "object",
                "additionalProperties": False,
                "required": ["summary", "ok", "artifacts"],
                "properties": {
                    "summary": {"type": "string"},
                    "ok": {"type": "boolean"},
                    "artifacts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["artifact_id", "path", "content", "sha256"],
                            "properties": {
                                "artifact_id": {"type": "string"},
                                "path": {"type": "string"},
                                "content": {"type": "string"},
                                "sha256": {"type": "string"},
                            },
                        },
                    },
                },
            }
            contract.write_text(json.dumps({
                "schema_version": 1,
                "task_id": task_id,
                "instruction": "Produce one bounded candidate artifact.",
                "inputs": [{**self.artifact(source), "purpose": "task_input"}],
                "allowed_tools": [],
                "allowed_write_paths": [],
                "artifact_outputs": [{
                    "artifact_id": "candidate",
                    "path": str(output),
                    "content_field": "content",
                    "max_bytes": 1000,
                    "capability": {"class": "research-intermediate"},
                }],
                "completion_check": {"type": "output_schema", "assertion": "valid"},
                "output_schema": output_schema,
            }, indent=2))
            graph = self.durable_graph(
                plan,
                task_id=task_id,
                contract=contract,
                inputs=[self.artifact(source, "task_input")],
            )
            self.call("init-durable-plan", "--plan-dir", str(plan), "--graph", str(graph))
            advanced = json.loads(self.call(
                "advance-durable-plan", "--plan-dir", str(plan),
            ).stdout)
            capsule = advanced["capsule_path"]
            worker = self.fake_artifact_worker(root, output.resolve())
            dispatched = json.loads(self.call(
                "dispatch-worker",
                "--plan-dir", str(plan),
                "--task-contract", str(contract),
                "--context-capsule", capsule,
                "--claude-bin", str(worker),
            ).stdout)
            self.assertEqual(dispatched["context_capsule_id"], advanced["capsule"]["capsule_id"])
            promoted = json.loads(self.call(
                "promote-worker-artifacts",
                "--plan-dir", str(plan),
                "--worker-run-id", dispatched["run_id"],
            ).stdout)
            self.assertEqual(promoted["context_capsule_id"], advanced["capsule"]["capsule_id"])
            commits = self.call_concurrently(
                "commit-durable-worker-result",
                "--plan-dir", str(plan),
                "--worker-run-id", dispatched["run_id"],
            )
            committed = next(item for item in commits if not item.get("idempotent"))
            self.assertEqual(committed["state_revision"], 2)
            self.assertEqual(committed["capsule_id"], advanced["capsule"]["capsule_id"])
            self.assertEqual(sum(bool(item.get("idempotent")) for item in commits), 1)
            again = json.loads(self.call(
                "commit-durable-worker-result",
                "--plan-dir", str(plan),
                "--worker-run-id", dispatched["run_id"],
            ).stdout)
            self.assertTrue(again["idempotent"])
            projection = json.loads(
                (plan / "state" / "durable_loop" / "projection.json").read_text()
            )
            self.assertEqual(projection["phase"], "complete")
            self.assertEqual(projection["next_action"]["kind"], "complete")
            self.assertEqual(len(projection["evidence_refs"]), 1)

    def test_codex_frontier_is_capsule_derived_advisory_and_exact_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = self.ready_plan(root)
            roles = (
                "evaluator_contract",
                "evaluator_verdict",
                "dispute_record",
                "candidate",
            )
            inputs: list[dict[str, str]] = []
            for role in roles:
                artifact_path = plan / f"{role}.json"
                artifact_path.write_text(json.dumps({"role": role}) + "\n")
                inputs.append(self.artifact(artifact_path, role))
            contract = plan / "frontier-task-contract.json"
            contract.write_text('{"schema_version":1,"task_id":"frontier-task"}\n')
            graph = self.durable_graph(
                plan,
                task_id="frontier-task",
                contract=contract,
                inputs=inputs,
            )
            self.call("init-durable-plan", "--plan-dir", str(plan), "--graph", str(graph))
            advanced = json.loads(self.call(
                "advance-durable-plan", "--plan-dir", str(plan),
            ).stdout)
            capsule = advanced["capsule_path"]
            wrong_profile = self.call(
                "create-durable-frontier-request",
                "--plan-dir", str(plan),
                "--context-capsule", capsule,
                "--checkpoint", "CP-01",
                "--attempt", "1",
                "--objective", "wrong profile",
                "--decision-required", "approve_execution",
                "--max-input-tokens", "1000",
                "--max-output-tokens", "500",
                "--request-id", "far_wrong_profile",
                check=False,
            )
            self.assertEqual(wrong_profile.returncode, 2)
            self.assertIn("evidence profile mismatch", wrong_profile.stderr)
            created = json.loads(self.call(
                "create-durable-frontier-request",
                "--plan-dir", str(plan),
                "--context-capsule", capsule,
                "--checkpoint", "CP-04",
                "--checkpoint-subtype", "acceptance_dispute",
                "--attempt", "1",
                "--objective", "Resolve the bounded evidence dispute.",
                "--decision-required", "resolve_acceptance_dispute",
                "--constraint", "advisory only",
                "--max-input-tokens", "1000",
                "--max-output-tokens", "500",
                "--request-id", "far_durable_dispute",
            ).stdout)
            request = json.loads(Path(created["request_path"]).read_text())
            self.assertEqual(request["durable_context"]["capsule_id"], advanced["capsule"]["capsule_id"])
            self.assertEqual(request["context_manifest"], advanced["capsule"]["input_manifest"])
            codex = self.base.fake_codex(root)
            self.call(
                "send-frontier-request",
                "--plan-dir", str(plan),
                "--request-id", "far_durable_dispute",
                "--codex-bin", str(codex),
            )
            self.call(
                "validate-frontier-response",
                "--plan-dir", str(plan),
                "--request-id", "far_durable_dispute",
            )
            self.call(
                "apply-frontier-response",
                "--plan-dir", str(plan),
                "--request-id", "far_durable_dispute",
                "--dependent-transition", "resolve_acceptance_dispute",
                "--controller-note", "bounded evidence accepted; advice remains non-authoritative",
            )
            commits = self.call_concurrently(
                "commit-durable-frontier-result",
                "--plan-dir", str(plan),
                "--request-id", "far_durable_dispute",
            )
            committed = next(item for item in commits if not item.get("idempotent"))
            self.assertEqual(committed["transition"], "resolve_acceptance_dispute")
            self.assertEqual(committed["state_revision"], 2)
            self.assertEqual(sum(bool(item.get("idempotent")) for item in commits), 1)
            self.call(
                "assert-transition",
                "--plan-dir", str(plan),
                "--plan-id", "plan_abc",
                "--transition", "resolve_acceptance_dispute",
                "--request-id", "far_durable_dispute",
            )
            again = json.loads(self.call(
                "commit-durable-frontier-result",
                "--plan-dir", str(plan),
                "--request-id", "far_durable_dispute",
            ).stdout)
            self.assertTrue(again["idempotent"])
            projection = json.loads(
                (plan / "state" / "durable_loop" / "projection.json").read_text()
            )
            self.assertEqual(projection["phase"], "complete")
            self.assertEqual(projection["next_action"]["kind"], "complete")
            self.assertEqual(len(projection["evidence_refs"]), 1)


if __name__ == "__main__":
    unittest.main()
