#!/usr/bin/env python3
"""Behavioral tests for autoresearch-paper runtime contracts."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    proc = subprocess.run(cmd, cwd=cwd, env=merged, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise AssertionError(f"command failed {cmd}\nstdout={proc.stdout}\nstderr={proc.stderr}")
    return proc


class RuntimeContracts(unittest.TestCase):
    def make_plan(self, tmp: Path, name: str = "plan-artifacts") -> Path:
        plan = tmp / name
        (plan / "state").mkdir(parents=True)
        (plan / "control").mkdir()
        return plan

    def write_manifest(self, plan: Path, **overrides: object) -> None:
        data = {
            "schema_version": 1,
            "plan_id": "plan_abc",
            "plan_dir": str(plan),
            "status": "running",
            "agents": [],
            "sessions": [],
            "crons": [],
            "hooks": [],
            "launchd": [],
            "local_processes": [],
            "remote_processes": [],
            "locks": [],
        }
        data.update(overrides)
        (plan / "resource_manifest.json").write_text(json.dumps(data, indent=2) + "\n")

    def fake_mavis_env(self, tmp: Path) -> dict[str, str]:
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        log = tmp / "mavis.log"
        (bin_dir / "mavis").write_text(
            "#!/usr/bin/env bash\n"
            "echo \"$*\" >> \"$MAVIS_FAKE_LOG\"\n"
            "case \"$1 $2\" in\n"
            "  'cron list') echo keep-cron; echo delete-cron ;;\n"
            "  'hook list') echo keep-hook.json; echo delete-hook.json ;;\n"
            "  'team plan') echo '{\"state\":{\"status\":\"paused\"}}' ;;\n"
            "esac\n"
        )
        (bin_dir / "mavis").chmod(0o755)
        return {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}", "MAVIS_FAKE_LOG": str(log)}

    def harness(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([
            sys.executable,
            "references/scripts/harness-runtime.py",
            *args,
        ], check=check)

    def init_model_policy(self, plan: Path) -> None:
        self.harness(
            "init-policy",
            "--plan-dir", str(plan),
            "--worker-model", "MiniMax-M3-test",
            "--worker-max-budget-usd", "0.25",
            "--frontier-model", "gpt-frontier-test",
            "--max-frontier-calls", "2",
            "--max-frontier-input-tokens", "400000",
            "--max-frontier-output-tokens", "20000",
        )

    def human_key(self, tmp: Path, content: bytes = b"k" * 32) -> Path:
        key = tmp / "human.key"
        key.write_bytes(content)
        key.chmod(0o600)
        return key

    def create_action(
        self, plan: Path, key: Path, action: str, *, record_id: str,
        extra: tuple[str, ...] = (), expires_in: int = 300,
    ) -> Path:
        result = self.harness(
            "create-human-action", "--plan-dir", str(plan), "--plan-id", "plan_abc",
            "--action", action, "--key-file", str(key), "--expires-in", str(expires_in),
            "--record-id", record_id, *extra,
        )
        return Path(json.loads(result.stdout)["record_path"])

    def fake_claude(self, tmp: Path) -> tuple[Path, Path]:
        executable = tmp / "fake-claude"
        log = tmp / "claude-args.json"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "json.dump(sys.argv[1:], open(os.environ['CLAUDE_TEST_LOG'], 'w'))\n"
            "json.dump({'structured_output': {'summary': 'bounded result', 'ok': True, 'artifacts': []}}, sys.stdout)\n"
        )
        executable.chmod(0o755)
        return executable, log

    def fake_codex(self, tmp: Path) -> Path:
        executable = tmp / "fake-codex"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "args = sys.argv[1:]\n"
            "if args == ['login', 'status']:\n"
            "  print('Logged in using ChatGPT')\n"
            "  raise SystemExit(0)\n"
            "if args[-2:] == ['features', 'list']:\n"
            "  print('multi_agent stable false')\n"
            "  raise SystemExit(0)\n"
            "if os.environ.get('CODEX_TEST_LOG'):\n"
            "  json.dump(args, open(os.environ['CODEX_TEST_LOG'], 'w'))\n"
            "out = args[args.index('--output-last-message') + 1]\n"
            "prompt = sys.stdin.read()\n"
            "if os.environ.get('CODEX_TEST_PROMPT_LOG'):\n"
            "  open(os.environ['CODEX_TEST_PROMPT_LOG'], 'w').write(prompt)\n"
            "request = json.loads(prompt[prompt.index('{'):])\n"
            "import hashlib\n"
            "canonical = json.dumps(request['context_manifest'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()\n"
            "critical = os.environ.get('CODEX_TEST_CRITICAL') == '1'\n"
            "response = {\n"
            "  'schema_version': 1, 'request_id': request['request_id'],\n"
            "  'plan_id': request['plan_id'], 'checkpoint': request['checkpoint'],\n"
            "  'checkpoint_subtype': request['checkpoint_subtype'],\n"
            "  'request_sha256': hashlib.sha256(json.dumps(request, indent=2, sort_keys=True).encode() + b'\\n').hexdigest(),\n"
            "  'context_manifest_sha256': hashlib.sha256(canonical).hexdigest(),\n"
            "  'status': 'completed', 'response_kind': {'CP-01':'plan_audit','CP-02':'evaluator_audit','CP-03':'pivot_advice','CP-04':'evidence_audit'}[request['checkpoint']],\n"
            "  'recommendation': os.environ.get('CODEX_TEST_RECOMMENDATION', 'accept'),\n"
            "  'findings': ([{'severity':'critical','claim':'bounded blocker','evidence':[request['context_manifest'][0]['path']]}] if critical else []),\n"
            "  'proposed_actions': [{'action': 'add baseline', 'rationale': 'comparison required'}],\n"
            "  'assumptions': [], 'blockers': (['cannot proceed'] if critical else []), 'model_id': 'untrusted-model-claim',\n"
            "  'usage': {'input_tokens': 0, 'output_tokens': 0},\n"
            "  'completed_at': '2026-07-17T00:00:00Z'\n"
            "}\n"
            "json.dump(response, open(out, 'w'))\n"
            "print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': int(os.environ.get('CODEX_TEST_USAGE_INPUT','321')), 'output_tokens': int(os.environ.get('CODEX_TEST_USAGE_OUTPUT','123'))}}))\n"
        )
        executable.chmod(0o755)
        return executable

    def evidence_profile(
        self,
        plan: Path,
        checkpoint: str,
        subtype: str | None = None,
        *,
        plan_id: str | None = None,
    ) -> dict[str, Path]:
        profiles = {
            ("CP-01", None): (
                "normalized_brief", "execution_plan", "risk_budget",
                "figure_requirements",
            ),
            ("CP-04", "acceptance_dispute"): (
                "evaluator_contract", "evaluator_verdict", "dispute_record", "candidate",
            ),
        }
        result: dict[str, Path] = {}
        for role in profiles[(checkpoint, subtype)]:
            path = plan / f"{checkpoint.lower()}-{role}.json"
            if role == "figure_requirements":
                path.write_text(json.dumps({
                    "schema_version": 1,
                    "plan_id": plan_id or plan.name,
                    "tier": "arxiv",
                    "expected_figure_ids": ["fig-required"],
                }))
            else:
                path.write_text("{}")
            result[role] = path
        return result

    def cp01_create_args(self, plan: Path, plan_id: str, request_id: str) -> list[str]:
        args = [
            "create-frontier-request", "--plan-dir", str(plan), "--plan-id", plan_id,
            "--checkpoint", "CP-01", "--objective", "audit", "--decision-required", "approve_execution",
            "--max-input-tokens", "150000", "--max-output-tokens", "5000", "--request-id", request_id,
        ]
        for role, path in self.evidence_profile(
            plan, "CP-01", plan_id=plan_id
        ).items():
            args += ["--artifact", f"{path}::{role}"]
        return args

    def approve_cp01(self, plan: Path, tmp: Path, plan_id: str = "plan_abc") -> None:
        self.write_manifest(plan, plan_id=plan_id)
        request_id = "far_worker_approval"
        self.harness(*self.cp01_create_args(plan, plan_id, request_id))
        self.harness(
            "send-frontier-request", "--plan-dir", str(plan), "--request-id", request_id,
            "--codex-bin", str(self.fake_codex(tmp)),
        )
        self.harness("validate-frontier-response", "--plan-dir", str(plan), "--request-id", request_id)
        self.harness(
            "apply-frontier-response", "--plan-dir", str(plan), "--request-id", request_id,
            "--dependent-transition", "approve_execution", "--controller-note", "worker approved",
        )

    def test_cleanup_preserves_non_ephemeral_resources(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp)
            self.write_manifest(
                plan,
                crons=[
                    {"agent": "a", "name": "keep-cron", "ephemeral": False},
                    {"agent": "a", "name": "delete-cron", "ephemeral": True},
                ],
                hooks=[
                    {"name": "keep-hook.json", "ephemeral": False},
                    {"name": "delete-hook.json", "ephemeral": True},
                ],
                agents=[
                    {"name": "stable-agent", "ephemeral": False},
                    {"name": "tmp-agent", "ephemeral": True},
                ],
                local_processes=[
                    {"label": "shared-proc", "pid": 999999, "ephemeral": False},
                    {"label": "owned-proc", "pid": 999999, "ephemeral": True},
                ],
            )
            run([
                "bash",
                "references/scripts/cleanup-plan-resources.sh",
                str(plan),
                "--dry-run",
                "--legacy-mavis",
            ], env=self.fake_mavis_env(tmp))
            report = (plan / "cleanup_report.md").read_text()
            self.assertIn("non-ephemeral; left in place", report)
            self.assertIn("DRY-RUN cron:a/delete-cron", report)
            self.assertIn("DRY-RUN hook:delete-hook.json", report)
            self.assertIn("DRY-RUN agent-archive:tmp-agent", report)
            self.assertNotIn("DRY-RUN cron:a/keep-cron", report)
            self.assertNotIn("DRY-RUN hook:keep-hook.json", report)
            self.assertNotIn("DRY-RUN agent-archive:stable-agent", report)

    def test_claude_worker_dispatch_is_pinned_and_mavis_free(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.init_model_policy(plan)
            self.approve_cp01(plan, tmp)
            artifact = plan / "brief.md"
            artifact.write_text("bounded brief\n")
            contract = plan / "task.json"
            contract.write_text(json.dumps({
                "schema_version": 1,
                "task_id": "draft-evaluator",
                "instruction": "Produce a bounded evaluator outline.",
                "inputs": [{"path": "brief.md", "purpose": "research brief"}],
                "allowed_tools": [],
                "allowed_write_paths": [],
                "artifact_outputs": [],
                "completion_check": {"type": "output_schema", "assertion": "valid"},
                "output_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["summary", "ok", "artifacts"],
                    "properties": {
                        "summary": {"type": "string"},
                        "ok": {"type": "boolean"},
                        "artifacts": {"type": "array", "items": {"type": "object"}},
                    },
                },
            }))
            missing = run([
                sys.executable,
                "references/scripts/harness-runtime.py",
                "dispatch-worker",
                "--plan-dir", str(plan),
                "--task-contract", str(contract),
                "--claude-bin", str(tmp / "missing-claude"),
            ], check=False)
            self.assertEqual(missing.returncode, 2)
            self.assertIn("Claude Code executable is unavailable", missing.stderr)
            self.assertFalse((plan / "state" / "worker_runs").exists())
            claude, log = self.fake_claude(tmp)
            proc = run([
                sys.executable,
                "references/scripts/harness-runtime.py",
                "dispatch-worker",
                "--plan-dir", str(plan),
                "--task-contract", str(contract),
                "--claude-bin", str(claude),
            ], env={"CLAUDE_TEST_LOG": str(log)})
            result = json.loads(proc.stdout)
            self.assertEqual(result["status"], "COMPLETED")
            argv = json.loads(log.read_text())
            self.assertEqual(argv[argv.index("--model") + 1], "MiniMax-M3-test")
            self.assertIn("--json-schema", argv)
            self.assertIn("--add-dir", argv)
            self.assertEqual(
                Path(argv[argv.index("--add-dir") + 1]).resolve(),
                plan.resolve(),
            )
            self.assertNotIn("mavis", " ".join(argv).lower())

    def test_frontier_bridge_is_durable_bounded_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.init_model_policy(plan)
            profile = self.evidence_profile(
                plan, "CP-01", plan_id="plan_bridge"
            )
            artifact = profile["normalized_brief"]
            artifact.write_text("objective and frozen constraints\n")
            create_args = [
                "create-frontier-request", "--plan-dir", str(plan), "--plan-id", "plan_bridge",
                "--checkpoint", "CP-01", "--objective", "Audit the initial research plan.",
                "--decision-required", "approve_execution", "--constraint", "do not mutate lifecycle state",
                "--max-input-tokens", "150000", "--max-output-tokens", "5000", "--request-id", "far_test_request",
            ]
            for role, path in profile.items():
                create_args += ["--artifact", f"{path}::{role}"]
            created = self.harness(*create_args)
            created_obj = json.loads(created.stdout)
            request_path = Path(created_obj["request_path"])
            request_hash = created_obj["request_sha256"]
            self.assertEqual(request_path.stat().st_mode & 0o222, 0)
            codex = self.fake_codex(tmp)
            self.harness(
                "send-frontier-request",
                "--plan-dir", str(plan),
                "--request-id", "far_test_request",
                "--codex-bin", str(codex),
            )
            response = json.loads((request_path.parent / "response.json").read_text())
            self.assertEqual(response["model_id"], "gpt-5.6-sol")
            self.assertEqual(response["usage"], {"input_tokens": 321, "output_tokens": 123})
            transport_argv = json.loads(
                (request_path.parent / "preflight.json").read_text()
            )
            self.assertEqual(transport_argv["frontier_transport"], "chatgpt-https")
            self.assertEqual(transport_argv["frontier_model"], "gpt-5.6-sol")
            self.assertEqual(transport_argv["reasoning_effort"], "ultra")
            self.assertEqual(
                transport_argv["review_profile_kind"],
                "top_level_plan_audit",
            )
            self.assertEqual(request_hash, __import__("hashlib").sha256(request_path.read_bytes()).hexdigest())
            validated = self.harness(
                "validate-frontier-response",
                "--plan-dir", str(plan),
                "--request-id", "far_test_request",
            )
            self.assertEqual(json.loads(validated.stdout)["state"], "VALIDATED")
            self.harness(
                "apply-frontier-response",
                "--plan-dir", str(plan),
                "--request-id", "far_test_request",
                "--controller-note", "revision task queued; no lifecycle mutation",
                "--dependent-transition", "approve_execution",
            )
            again = self.harness(
                "apply-frontier-response",
                "--plan-dir", str(plan),
                "--request-id", "far_test_request",
                "--controller-note", "duplicate delivery",
                "--dependent-transition", "approve_execution",
            )
            self.assertTrue(json.loads(again.stdout)["idempotent"])
            self.harness(
                "assert-transition", "--plan-dir", str(plan), "--plan-id", "plan_bridge",
                "--transition", "approve_execution",
            )
            artifact.write_text("changed after apply\n")
            drift = self.harness(
                "assert-transition", "--plan-dir", str(plan), "--plan-id", "plan_bridge",
                "--transition", "approve_execution", check=False,
            )
            self.assertEqual(drift.returncode, 2)
            transitions = (plan / "state" / "controller_transitions.jsonl").read_text().splitlines()
            self.assertEqual(len(transitions), 1)
            self.assertFalse(json.loads(transitions[0])["lifecycle_mutation"])
            ledger = json.loads((plan / "state" / "frontier" / "budget.json").read_text())
            self.assertEqual(ledger["reserved_calls"], 1)

    def test_frontier_negative_advice_usage_fallback_and_semantic_split(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            for request_id, recommendation, critical, usage, expected in (
                ("far_valid_block", "block", "1", "321", "VALIDATED"),
                ("far_accept_critical", "accept", "1", "321", "PAUSED"),
                ("far_zero_usage", "accept", "0", "0", "VALIDATED"),
                (
                    "far_reservation_overrun_within_plan",
                    "accept", "0", "160000", "VALIDATED",
                ),
                ("far_plan_budget_overrun", "accept", "0", "400001", "PAUSED"),
            ):
                plan = self.make_plan(tmp / request_id)
                self.init_model_policy(plan)
                self.harness(*self.cp01_create_args(plan, plan.name, request_id))
                codex = self.fake_codex(tmp / request_id)
                run(
                    [
                        sys.executable, "references/scripts/harness-runtime.py",
                        "send-frontier-request", "--plan-dir", str(plan),
                        "--request-id", request_id, "--codex-bin", str(codex),
                    ],
                    env={
                        "CODEX_TEST_RECOMMENDATION": recommendation,
                        "CODEX_TEST_CRITICAL": critical,
                        "CODEX_TEST_USAGE_INPUT": usage,
                        "CODEX_TEST_USAGE_OUTPUT": "0" if usage == "0" else "123",
                    },
                )
                validated = self.harness(
                    "validate-frontier-response", "--plan-dir", str(plan),
                    "--request-id", request_id, check=expected == "VALIDATED",
                )
                status = json.loads(
                    (plan / "state" / "frontier" / "requests" / request_id
                     / "status.json").read_text()
                )
                self.assertEqual(status["state"], expected)
                if request_id == "far_valid_block":
                    blocked = self.harness(
                        "apply-frontier-response", "--plan-dir", str(plan),
                        "--request-id", request_id,
                        "--dependent-transition", "approve_execution",
                        "--controller-note", "negative advice retained",
                        check=False,
                    )
                    self.assertIn("leaves dependent transition blocked", blocked.stderr)
                elif request_id == "far_accept_critical":
                    self.assertNotEqual(validated.returncode, 0)
                    self.assertEqual(
                        status["failure"], "response_semantic_inconsistency",
                    )
                elif request_id == "far_plan_budget_overrun":
                    self.assertNotEqual(validated.returncode, 0)
                    self.assertEqual(status["failure"], "response_budget_overrun")
                elif request_id == "far_reservation_overrun_within_plan":
                    receipt_path = (
                        plan / "state" / "frontier" / "requests" / request_id
                        / "budget-overrun-receipt.json"
                    )
                    receipt = json.loads(receipt_path.read_text())
                    self.assertEqual(
                        receipt["delta"],
                        {"input_tokens": 10000, "output_tokens": 0},
                    )
                    ledger = json.loads(
                        (plan / "state" / "frontier" / "budget.json").read_text()
                    )
                    self.assertEqual(ledger["reserved_input_tokens"], 160000)
                    self.assertEqual(
                        Path(status["budget_overrun_receipt"]).resolve(),
                        receipt_path.resolve(),
                    )
                else:
                    response = json.loads(
                        (plan / "state" / "frontier" / "requests" / request_id
                         / "response.json").read_text()
                    )
                    self.assertEqual(response["usage"], {
                        "input_tokens": 150000, "output_tokens": 5000,
                    })
                    self.assertEqual(
                        status["usage_accounting"]["authority"],
                        "conservative_reservation_fallback",
                    )

    def test_chatgpt_usage_floor_rejects_before_preflight_or_budget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.init_model_policy(plan)
            args = self.cp01_create_args(plan, "plan_floor", "far_floor")
            args[args.index("150000")] = "149999"
            self.harness(*args)
            failed = self.harness(
                "send-frontier-request", "--plan-dir", str(plan),
                "--request-id", "far_floor", "--codex-bin", str(self.fake_codex(tmp)),
                check=False,
            )
            self.assertIn("below the frozen ChatGPT usage floor", failed.stderr)
            request_root = (
                plan / "state" / "frontier" / "requests" / "far_floor"
            )
            self.assertFalse((request_root / "preflight.json").exists())
            self.assertFalse((plan / "state" / "frontier" / "budget.json").exists())

    def test_frontier_preflight_and_https_route_precede_budget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.init_model_policy(plan)
            policy = json.loads(
                (plan / "state" / "model_policy.json").read_text()
            )
            self.assertEqual(policy["top_level_plan_audit"], {
                "required": True,
                "declared_author_model_family": "MiniMax-M3",
                "reviewer_runtime": "codex",
                "reviewer_model": "gpt-5.6-sol",
                "reasoning_effort": "ultra",
                "checkpoint": "CP-01",
                "dependent_transition": "approve_execution",
            })
            self.harness(*self.cp01_create_args(plan, "plan_route", "far_route"))
            argv_log = tmp / "codex-argv.json"
            prompt_log = tmp / "codex-prompt.txt"
            proc = run(
                [
                    sys.executable,
                    "references/scripts/harness-runtime.py",
                    "send-frontier-request",
                    "--plan-dir", str(plan),
                    "--request-id", "far_route",
                    "--codex-bin", str(self.fake_codex(tmp)),
                ],
                env={
                    "CODEX_TEST_LOG": str(argv_log),
                    "CODEX_TEST_PROMPT_LOG": str(prompt_log),
                },
            )
            self.assertEqual(proc.returncode, 0)
            argv = json.loads(argv_log.read_text())
            self.assertEqual(argv[argv.index("-m") + 1], "gpt-5.6-sol")
            self.assertIn("model_reasoning_effort=ultra", argv)
            self.assertIn("--skip-git-repo-check", argv)
            self.assertIn("--ephemeral", argv)
            self.assertIn("--ignore-user-config", argv)
            self.assertIn("--ignore-rules", argv)
            self.assertIn("plugins", argv)
            self.assertIn("apps", argv)
            self.assertIn("multi_agent", argv)
            self.assertIn("multi_agent_v2", argv)
            self.assertNotIn("agents.enabled=false", argv)
            self.assertIn(
                "include_collaboration_mode_instructions=false", argv
            )
            self.assertTrue(any(
                value.startswith('developer_instructions="Act as the sole ')
                for value in argv
            ))
            self.assertIn('model_provider="chatgpt_http"', argv)
            self.assertIn(
                "model_providers.chatgpt_http.supports_websockets=false", argv
            )
            request_path = (
                plan
                / "state"
                / "frontier"
                / "requests"
                / "far_route"
                / "request.json"
            )
            request = json.loads(request_path.read_text())
            self.assertEqual(
                request["review_contract"]["kind"],
                "top-level-plan-review-v1",
            )
            self.assertEqual(
                request["review_contract"]["reviewer_profile"],
                {
                    "kind": "top_level_plan_audit",
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "ultra",
                },
            )
            self.assertEqual(
                request["review_contract"]["evidence_roles"],
                [
                    "execution_plan",
                    "figure_requirements",
                    "normalized_brief",
                    "risk_budget",
                ],
            )
            prompt = prompt_log.read_text()
            self.assertIn(
                "mandatory independent CP-01 review of the exact top-level "
                "execution plan declared as MiniMax M3 output",
                prompt,
            )
            self.assertIn(
                f"request_sha256: {hashlib.sha256(request_path.read_bytes()).hexdigest()}",
                prompt,
            )
            self.assertIn('recommendation: one of ["accept", "block", "revise"]', prompt)

            missing_plan = self.make_plan(tmp / "missing")
            self.init_model_policy(missing_plan)
            self.harness(
                *self.cp01_create_args(missing_plan, "plan_missing", "far_missing")
            )
            failed = self.harness(
                "send-frontier-request",
                "--plan-dir", str(missing_plan),
                "--request-id", "far_missing",
                "--codex-bin", str(tmp / "does-not-exist"),
                check=False,
            )
            self.assertEqual(failed.returncode, 2)
            self.assertIn("executable is unavailable", failed.stderr)
            self.assertFalse(
                (missing_plan / "state" / "frontier" / "budget.json").exists()
            )
            failure = json.loads(
                (
                    missing_plan
                    / "state"
                    / "frontier"
                    / "requests"
                    / "far_missing"
                    / "preflight-failure.json"
                ).read_text()
            )
            self.assertFalse(failure["budget_reserved"])

            invalid_timeout_plan = self.make_plan(tmp / "invalid-timeout")
            self.init_model_policy(invalid_timeout_plan)
            self.harness(
                *self.cp01_create_args(
                    invalid_timeout_plan, "plan_invalid_timeout", "far_invalid_timeout"
                )
            )
            invalid_timeout = self.harness(
                "send-frontier-request",
                "--plan-dir", str(invalid_timeout_plan),
                "--request-id", "far_invalid_timeout",
                "--codex-bin", str(self.fake_codex(tmp)),
                "--timeout", "0",
                check=False,
            )
            self.assertEqual(invalid_timeout.returncode, 2)
            self.assertIn("between 1 and 86400", invalid_timeout.stderr)
            self.assertFalse(
                (
                    invalid_timeout_plan
                    / "state"
                    / "frontier"
                    / "budget.json"
                ).exists()
            )

    def test_frontier_timeout_keeps_charge_and_durable_events(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.init_model_policy(plan)
            self.harness(*self.cp01_create_args(plan, "plan_timeout", "far_timeout"))
            codex = tmp / "slow-codex"
            descendant_marker = tmp / "descendant-survived"
            codex.write_text(
                "#!/usr/bin/env python3\n"
                "import subprocess, sys, time\n"
                "if sys.argv[1:] == ['login', 'status']:\n"
                "  print('Logged in using ChatGPT')\n"
                "  raise SystemExit(0)\n"
                "if sys.argv[-2:] == ['features', 'list']:\n"
                "  print('multi_agent stable false')\n"
                "  raise SystemExit(0)\n"
                f"subprocess.Popen([sys.executable, '-c', "
                f"\"import signal,time;from pathlib import Path;"
                f"signal.signal(signal.SIGTERM, signal.SIG_IGN);time.sleep(3);"
                f"Path({str(descendant_marker)!r}).write_text('alive')\"])\n"
                "print('{\"type\":\"thread.started\"}', flush=True)\n"
                "time.sleep(30)\n"
            )
            codex.chmod(0o755)
            failed = self.harness(
                "send-frontier-request",
                "--plan-dir", str(plan),
                "--request-id", "far_timeout",
                "--codex-bin", str(codex),
                "--timeout", "1",
                check=False,
            )
            self.assertEqual(failed.returncode, 2)
            self.assertIn("outcome is uncertain", failed.stderr)
            run_dir = (
                plan / "state" / "frontier" / "requests" / "far_timeout"
            )
            self.assertIn("thread.started", (run_dir / "transport.events.jsonl").read_text())
            status = json.loads((run_dir / "status.json").read_text())
            self.assertEqual(status["failure"], "transport_outcome_uncertain")
            ledger = json.loads(
                (plan / "state" / "frontier" / "budget.json").read_text()
            )
            self.assertEqual(ledger["reserved_calls"], 1)
            reconciled = self.harness(
                "reconcile-frontier-request",
                "--plan-dir", str(plan),
                "--request-id", "far_timeout",
            )
            self.assertEqual(json.loads(reconciled.stdout)["state"], "PAUSED")
            time.sleep(3.2)
            self.assertFalse(descendant_marker.exists())

    def test_frontier_rejects_collaboration_event_even_with_valid_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.init_model_policy(plan)
            self.harness(*self.cp01_create_args(plan, "plan_collab", "far_collab"))
            codex = self.fake_codex(tmp)
            original = codex.read_text()
            codex.write_text(original.replace(
                "print(json.dumps({'type': 'turn.completed',",
                "print(json.dumps({'type':'item.completed','item':"
                "{'type':'collab_tool_call','tool':'wait'}}))\n"
                "print(json.dumps({'type': 'turn.completed',",
            ))
            failed = self.harness(
                "send-frontier-request", "--plan-dir", str(plan),
                "--request-id", "far_collab", "--codex-bin", str(codex),
                check=False,
            )
            self.assertEqual(failed.returncode, 2)
            self.assertIn("single-reviewer boundary", failed.stderr)
            status = json.loads((
                plan / "state" / "frontier" / "requests" / "far_collab"
                / "status.json"
            ).read_text())
            self.assertEqual(status["state"], "PAUSED")
            self.assertEqual(status["failure"], "frontier_surface_violation")

    def test_frontier_preflight_rejects_minimax_without_budget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.harness(
                "init-policy",
                "--plan-dir", str(plan),
                "--worker-model", "MiniMax-M3-test",
                "--worker-max-budget-usd", "0.25",
                "--frontier-model", "MiniMax-M3",
                "--max-frontier-calls", "2",
                "--max-frontier-input-tokens", "400000",
                "--max-frontier-output-tokens", "20000",
            )
            policy_path = plan / "state" / "model_policy.json"
            policy_path.chmod(0o644)
            policy = json.loads(policy_path.read_text())
            policy.pop("top_level_plan_audit")
            policy_path.write_text(
                json.dumps(policy, indent=2, sort_keys=True) + "\n"
            )
            policy_path.chmod(0o444)
            self.harness(
                *self.cp01_create_args(plan, "plan_wrong_model", "far_wrong_model")
            )
            failed = self.harness(
                "send-frontier-request",
                "--plan-dir", str(plan),
                "--request-id", "far_wrong_model",
                "--codex-bin", str(self.fake_codex(tmp)),
                check=False,
            )
            self.assertEqual(failed.returncode, 2)
            self.assertIn("rejected MiniMax", failed.stderr)
            self.assertFalse(
                (plan / "state" / "frontier" / "budget.json").exists()
            )

    def test_cp01_strong_profile_overrides_minimax_generic_frontier(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.harness(
                "init-policy",
                "--plan-dir", str(plan),
                "--worker-model", "MiniMax-M3-test",
                "--worker-max-budget-usd", "0.25",
                "--frontier-model", "MiniMax-M3",
                "--max-frontier-calls", "2",
                "--max-frontier-input-tokens", "400000",
                "--max-frontier-output-tokens", "20000",
            )
            self.harness(
                *self.cp01_create_args(
                    plan, "plan_strong_override", "far_strong_override"
                )
            )
            sent = self.harness(
                "send-frontier-request",
                "--plan-dir", str(plan),
                "--request-id", "far_strong_override",
                "--codex-bin", str(self.fake_codex(tmp)),
            )
            self.assertEqual(json.loads(sent.stdout)["state"], "RECEIVED")
            run_dir = (
                plan / "state" / "frontier" / "requests"
                / "far_strong_override"
            )
            response = json.loads((run_dir / "response.json").read_text())
            self.assertEqual(response["model_id"], "gpt-5.6-sol")
            preflight = json.loads((run_dir / "preflight.json").read_text())
            self.assertEqual(
                preflight["review_profile_kind"], "top_level_plan_audit"
            )
            self.assertEqual(preflight["reasoning_effort"], "ultra")

    def test_frontier_unstarted_transport_refunds_and_operation_retries_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.init_model_policy(plan)
            self.harness(
                *self.cp01_create_args(
                    plan, "plan_unstarted", "far_unstarted"
                )
            )
            codex = tmp / "fake-codex"
            codex.write_text(
                "#!/usr/bin/env python3\n"
                "import os, sys\n"
                "if sys.argv[1:] == ['login', 'status']:\n"
                "  print('Logged in using ChatGPT')\n"
                "  raise SystemExit(0)\n"
                "if sys.argv[-2:] == ['features', 'list']:\n"
                "  os.unlink(sys.argv[0])\n"
                "  print('multi_agent stable false')\n"
                "  raise SystemExit(0)\n"
                "raise SystemExit(99)\n"
            )
            codex.chmod(0o755)
            operation_id = "op_" + "a" * 64
            first = self.harness(
                "send-frontier-request",
                "--plan-dir", str(plan),
                "--request-id", "far_unstarted",
                "--codex-bin", str(codex),
                "--operation-id", operation_id,
                check=False,
            )
            self.assertEqual(first.returncode, 2)
            self.assertIn("did not start", first.stderr)
            ledger = json.loads(
                (plan / "state" / "frontier" / "budget.json").read_text()
            )
            self.assertEqual(ledger["reserved_calls"], 0)
            self.assertNotIn("far_unstarted", ledger["request_ids"])
            status = json.loads(
                (
                    plan
                    / "state"
                    / "frontier"
                    / "requests"
                    / "far_unstarted"
                    / "status.json"
                ).read_text()
            )
            self.assertEqual(status["state"], "CREATED")
            self.assertEqual(status["failure"], "transport_not_started")
            releases = list(
                (
                    plan
                    / "state"
                    / "frontier"
                    / "requests"
                    / "far_unstarted"
                    / "budget-releases"
                ).glob("*.json")
            )
            self.assertEqual(len([path for path in releases if ".intent." not in path.name]), 1)

            self.fake_codex(tmp)
            argv_log = tmp / "successful-argv.json"
            second = run(
                [
                    sys.executable,
                    "references/scripts/harness-runtime.py",
                    "send-frontier-request",
                    "--plan-dir", str(plan),
                    "--request-id", "far_unstarted",
                    "--codex-bin", str(codex),
                    "--operation-id", operation_id,
                ],
                env={"CODEX_TEST_LOG": str(argv_log)},
            )
            self.assertEqual(second.returncode, 0)
            self.assertTrue(json.loads(second.stdout)["operation_reconciled"])
            self.assertTrue(argv_log.exists())
            ledger = json.loads(
                (plan / "state" / "frontier" / "budget.json").read_text()
            )
            self.assertEqual(ledger["reserved_calls"], 1)
            self.assertEqual(ledger["request_ids"], ["far_unstarted"])

    def test_frontier_ledger_crash_reenters_without_duplicate_send(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.init_model_policy(plan)
            self.harness(
                *self.cp01_create_args(
                    plan, "plan_reservation_crash", "far_reservation_crash"
                )
            )
            codex = self.fake_codex(tmp)
            operation_id = "op_" + "b" * 64
            first = run(
                [
                    sys.executable,
                    "references/scripts/harness-runtime.py",
                    "send-frontier-request",
                    "--plan-dir", str(plan),
                    "--request-id", "far_reservation_crash",
                    "--codex-bin", str(codex),
                    "--operation-id", operation_id,
                ],
                env={"HARNESS_FAULT_AFTER_FRONTIER_LEDGER": "1"},
                check=False,
            )
            self.assertEqual(first.returncode, 2)
            status_path = (
                plan
                / "state"
                / "frontier"
                / "requests"
                / "far_reservation_crash"
                / "status.json"
            )
            self.assertEqual(json.loads(status_path.read_text())["state"], "CREATED")
            ledger = json.loads(
                (plan / "state" / "frontier" / "budget.json").read_text()
            )
            self.assertEqual(ledger["reserved_calls"], 1)

            argv_log = tmp / "reservation-retry-argv.json"
            second = run(
                [
                    sys.executable,
                    "references/scripts/harness-runtime.py",
                    "send-frontier-request",
                    "--plan-dir", str(plan),
                    "--request-id", "far_reservation_crash",
                    "--codex-bin", str(codex),
                    "--operation-id", operation_id,
                ],
                env={"CODEX_TEST_LOG": str(argv_log)},
            )
            self.assertEqual(second.returncode, 0)
            self.assertTrue(json.loads(second.stdout)["operation_reconciled"])
            self.assertTrue(argv_log.exists())
            ledger = json.loads(
                (plan / "state" / "frontier" / "budget.json").read_text()
            )
            self.assertEqual(ledger["reserved_calls"], 1)
            self.assertEqual(ledger["request_ids"], ["far_reservation_crash"])

    def test_reserved_frontier_preflight_failure_releases_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.init_model_policy(plan)
            self.harness(
                *self.cp01_create_args(
                    plan, "plan_preflight_recovery", "far_preflight_recovery"
                )
            )
            codex = self.fake_codex(tmp)
            operation_id = "op_" + "c" * 64
            first = run(
                [
                    sys.executable,
                    "references/scripts/harness-runtime.py",
                    "send-frontier-request",
                    "--plan-dir", str(plan),
                    "--request-id", "far_preflight_recovery",
                    "--codex-bin", str(codex),
                    "--operation-id", operation_id,
                ],
                env={"HARNESS_FAULT_AFTER_FRONTIER_LEDGER": "1"},
                check=False,
            )
            self.assertEqual(first.returncode, 2)
            codex.unlink()

            second = run(
                [
                    sys.executable,
                    "references/scripts/harness-runtime.py",
                    "send-frontier-request",
                    "--plan-dir", str(plan),
                    "--request-id", "far_preflight_recovery",
                    "--codex-bin", str(codex),
                    "--operation-id", operation_id,
                ],
                check=False,
            )
            self.assertEqual(second.returncode, 2)
            self.assertIn("executable is unavailable", second.stderr)
            ledger = json.loads(
                (plan / "state" / "frontier" / "budget.json").read_text()
            )
            self.assertEqual(ledger["reserved_calls"], 0)
            self.assertEqual(ledger["request_ids"], [])
            run_dir = (
                plan / "state" / "frontier" / "requests"
                / "far_preflight_recovery"
            )
            status = json.loads((run_dir / "status.json").read_text())
            self.assertEqual(status["state"], "PAUSED")
            failure = json.loads((run_dir / "preflight-failure.json").read_text())
            self.assertTrue(failure["budget_reserved"])
            self.assertTrue(failure["budget_released"])
            self.assertIsNotNone(failure["budget_recovery"])
            self.fake_codex(tmp)
            third = run(
                [
                    sys.executable,
                    "references/scripts/harness-runtime.py",
                    "send-frontier-request",
                    "--plan-dir", str(plan),
                    "--request-id", "far_preflight_recovery",
                    "--codex-bin", str(codex),
                    "--operation-id", operation_id,
                ],
                check=False,
            )
            self.assertEqual(third.returncode, 2)
            self.assertIn("never redelivered", third.stderr)
            ledger = json.loads(
                (plan / "state" / "frontier" / "budget.json").read_text()
            )
            self.assertEqual(ledger["reserved_calls"], 0)
            self.assertEqual(ledger["request_ids"], [])
            final_status = json.loads((run_dir / "status.json").read_text())
            self.assertEqual(final_status["state"], "PAUSED")
            self.assertEqual(
                final_status["failure"], "frontier_preflight_failed"
            )

    def test_reserved_frontier_deadline_releases_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.init_model_policy(plan)
            create_args = self.cp01_create_args(
                plan, "plan_deadline_recovery", "far_deadline_recovery"
            )
            create_args += ["--deadline-seconds", "60"]
            self.harness(*create_args)
            codex = self.fake_codex(tmp)
            operation_id = "op_" + "d" * 64
            first = run(
                [
                    sys.executable,
                    "references/scripts/harness-runtime.py",
                    "send-frontier-request",
                    "--plan-dir", str(plan),
                    "--request-id", "far_deadline_recovery",
                    "--codex-bin", str(codex),
                    "--operation-id", operation_id,
                ],
                env={"HARNESS_FAULT_AFTER_FRONTIER_LEDGER": "1"},
                check=False,
            )
            self.assertEqual(first.returncode, 2)
            (
                plan / "cp-01-normalized_brief.json"
            ).write_text('{"changed":"after-reservation"}')
            expired = self.harness(
                "expire-frontier-request",
                "--plan-dir", str(plan),
                "--request-id", "far_deadline_recovery",
                "--now", "2099-01-01T00:00:00Z",
            )
            self.assertEqual(json.loads(expired.stdout)["state"], "PAUSED")
            ledger = json.loads(
                (plan / "state" / "frontier" / "budget.json").read_text()
            )
            self.assertEqual(ledger["reserved_calls"], 0)
            self.assertEqual(ledger["request_ids"], [])
            status = json.loads(
                (
                    plan / "state" / "frontier" / "requests"
                    / "far_deadline_recovery" / "status.json"
                ).read_text()
            )
            self.assertEqual(status["state"], "PAUSED")
            self.assertEqual(status["failure"], "deadline_expired")
            self.assertIsNotNone(status["budget_recovery"])

    def test_reserved_frontier_invalid_policy_releases_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.init_model_policy(plan)
            self.harness(
                *self.cp01_create_args(
                    plan, "plan_policy_recovery", "far_policy_recovery"
                )
            )
            codex = self.fake_codex(tmp)
            operation_id = "op_" + "e" * 64
            first = run(
                [
                    sys.executable,
                    "references/scripts/harness-runtime.py",
                    "send-frontier-request",
                    "--plan-dir", str(plan),
                    "--request-id", "far_policy_recovery",
                    "--codex-bin", str(codex),
                    "--operation-id", operation_id,
                ],
                env={"HARNESS_FAULT_AFTER_FRONTIER_LEDGER": "1"},
                check=False,
            )
            self.assertEqual(first.returncode, 2)
            policy_path = plan / "state" / "model_policy.json"
            policy_path.chmod(0o644)
            policy_path.write_text("{not-json")

            second = run(
                [
                    sys.executable,
                    "references/scripts/harness-runtime.py",
                    "send-frontier-request",
                    "--plan-dir", str(plan),
                    "--request-id", "far_policy_recovery",
                    "--codex-bin", str(codex),
                    "--operation-id", operation_id,
                ],
                check=False,
            )
            self.assertEqual(second.returncode, 2)
            ledger = json.loads(
                (plan / "state" / "frontier" / "budget.json").read_text()
            )
            self.assertEqual(ledger["reserved_calls"], 0)
            self.assertEqual(ledger["request_ids"], [])
            run_dir = (
                plan / "state" / "frontier" / "requests"
                / "far_policy_recovery"
            )
            status = json.loads((run_dir / "status.json").read_text())
            self.assertEqual(status["state"], "PAUSED")
            self.assertEqual(status["failure"], "prelaunch_validation_failed")
            failure = json.loads(
                (run_dir / "prelaunch-validation-failure.json").read_text()
            )
            self.assertTrue(failure["budget_reserved"])
            self.assertTrue(failure["budget_released"])

    def test_expiring_waiting_frontier_keeps_uncertain_charge(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.init_model_policy(plan)
            self.harness(
                *self.cp01_create_args(
                    plan, "plan_waiting_expiry", "far_waiting_expiry"
                )
            )
            codex = self.fake_codex(tmp)
            first = run(
                [
                    sys.executable,
                    "references/scripts/harness-runtime.py",
                    "send-frontier-request",
                    "--plan-dir", str(plan),
                    "--request-id", "far_waiting_expiry",
                    "--codex-bin", str(codex),
                ],
                env={"HARNESS_FAULT_AFTER_FRONTIER_LEDGER": "1"},
                check=False,
            )
            self.assertEqual(first.returncode, 2)
            status_path = (
                plan / "state" / "frontier" / "requests"
                / "far_waiting_expiry" / "status.json"
            )
            status = json.loads(status_path.read_text())
            status["state"] = "WAITING"
            status["send_claim"] = "uncertain-test-claim"
            status_path.write_text(json.dumps(status))

            expired = self.harness(
                "expire-frontier-request",
                "--plan-dir", str(plan),
                "--request-id", "far_waiting_expiry",
                "--now", "2099-01-01T00:00:00Z",
            )
            self.assertEqual(json.loads(expired.stdout)["state"], "PAUSED")
            ledger = json.loads(
                (plan / "state" / "frontier" / "budget.json").read_text()
            )
            self.assertEqual(ledger["reserved_calls"], 1)
            self.assertEqual(ledger["request_ids"], ["far_waiting_expiry"])
            final_status = json.loads(status_path.read_text())
            self.assertIsNone(final_status["budget_recovery"])

    def test_legacy_policy_preserves_codex_default_transport(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.init_model_policy(plan)
            policy_path = plan / "state" / "model_policy.json"
            policy_path.chmod(0o644)
            policy = json.loads(policy_path.read_text())
            policy.pop("frontier_transport")
            policy.pop("top_level_plan_audit")
            policy_path.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n")
            policy_path.chmod(0o444)
            self.harness(
                *self.cp01_create_args(plan, "plan_legacy", "far_legacy")
            )
            argv_log = tmp / "legacy-argv.json"
            proc = run(
                [
                    sys.executable,
                    "references/scripts/harness-runtime.py",
                    "send-frontier-request",
                    "--plan-dir", str(plan),
                    "--request-id", "far_legacy",
                    "--codex-bin", str(self.fake_codex(tmp)),
                ],
                env={"CODEX_TEST_LOG": str(argv_log)},
            )
            self.assertEqual(proc.returncode, 0)
            argv = json.loads(argv_log.read_text())
            self.assertNotIn('model_provider="chatgpt_http"', argv)
            status = json.loads(
                (
                    plan
                    / "state"
                    / "frontier"
                    / "requests"
                    / "far_legacy"
                    / "status.json"
                ).read_text()
            )
            self.assertEqual(status["transport"], "codex-default")
            status_path = (
                plan / "state" / "frontier" / "requests"
                / "far_legacy" / "status.json"
            )
            status.pop("reviewer_profile")
            status_path.chmod(0o644)
            status_path.write_text(json.dumps(status))
            self.harness(
                "validate-frontier-response",
                "--plan-dir", str(plan),
                "--request-id", "far_legacy",
            )
            applied = self.harness(
                "apply-frontier-response",
                "--plan-dir", str(plan),
                "--request-id", "far_legacy",
                "--dependent-transition", "approve_execution",
                "--controller-note", "legacy in-flight request accepted",
            )
            self.assertEqual(json.loads(applied.stdout)["state"], "APPLIED")

    def test_frontier_request_rejects_unregistered_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = self.make_plan(Path(td) / "plan")
            self.init_model_policy(plan)
            proc = self.harness(
                "create-frontier-request",
                "--plan-dir", str(plan),
                "--plan-id", "plan_bad_checkpoint",
                "--checkpoint", "CP-99",
                "--objective", "bypass registry",
                "--decision-required", "unsafe_decision",
                "--max-input-tokens", "10",
                "--max-output-tokens", "10",
                check=False,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("unregistered checkpoint", proc.stderr)
            wrong_decision = self.harness(
                "create-frontier-request",
                "--plan-dir", str(plan),
                "--plan-id", "plan_bad_checkpoint",
                "--checkpoint", "CP-01",
                "--objective", "bypass execution approval",
                "--decision-required", "initial_plan_approval",
                "--max-input-tokens", "10",
                "--max-output-tokens", "10",
                check=False,
            )
            self.assertEqual(wrong_decision.returncode, 2)
            self.assertIn(
                "registered checkpoint transition", wrong_decision.stderr
            )

    def test_cp04_acceptance_dispute_dependent_transition(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.init_model_policy(plan)
            profile = self.evidence_profile(plan, "CP-04", "acceptance_dispute")
            profile["dispute_record"].write_text("bounded dispute evidence\n")
            args = [
                "create-frontier-request", "--plan-dir", str(plan), "--plan-id", "plan_dispute",
                "--checkpoint", "CP-04", "--checkpoint-subtype", "acceptance_dispute",
                "--objective", "resolve evidence dispute", "--decision-required", "resolve_acceptance_dispute",
                "--max-input-tokens", "150000",
                "--max-output-tokens", "5000", "--request-id", "far_test_request",
            ]
            for role, path in profile.items():
                args += ["--artifact", f"{path}::{role}"]
            self.harness(*args)
            self.harness(
                "send-frontier-request", "--plan-dir", str(plan), "--request-id", "far_test_request",
                "--codex-bin", str(self.fake_codex(tmp)),
            )
            self.harness(
                "validate-frontier-response", "--plan-dir", str(plan), "--request-id", "far_test_request",
            )
            self.harness(
                "apply-frontier-response", "--plan-dir", str(plan), "--request-id", "far_test_request",
                "--dependent-transition", "resolve_acceptance_dispute", "--controller-note", "bounded evidence accepted",
            )
            self.harness(
                "assert-transition", "--plan-dir", str(plan), "--plan-id", "plan_dispute",
                "--transition", "resolve_acceptance_dispute",
            )

    def test_frontier_bridge_does_not_redeliver_uncertain_request(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = self.make_plan(Path(td) / "plan")
            self.init_model_policy(plan)
            self.harness(*self.cp01_create_args(plan, "plan_uncertain", "far_uncertain"))
            status_path = plan / "state" / "frontier" / "requests" / "far_uncertain" / "status.json"
            status = json.loads(status_path.read_text())
            status["state"] = "WAITING"
            status_path.write_text(json.dumps(status))
            proc = self.harness(
                "send-frontier-request",
                "--plan-dir", str(plan),
                "--request-id", "far_uncertain",
                "--codex-bin", str(Path(td) / "must-not-run"),
                check=False,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(json.loads(proc.stdout)["state"], "PAUSED")
            self.assertEqual(json.loads(proc.stdout)["failure"], "transport_outcome_uncertain")
            self.assertFalse((plan / "state" / "frontier" / "budget.json").exists())

    def test_frontier_bridge_blocks_oversized_context_before_budget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = self.make_plan(Path(td) / "plan")
            self.init_model_policy(plan)
            profile = self.evidence_profile(
                plan, "CP-01", plan_id="plan_large_context"
            )
            profile["normalized_brief"].write_text("x" * 3000)
            args = [
                "create-frontier-request", "--plan-dir", str(plan), "--plan-id", "plan_large_context",
                "--checkpoint", "CP-01", "--objective", "audit", "--decision-required", "approve_execution",
                "--max-input-tokens", "100", "--max-output-tokens", "100", "--request-id", "far_large_context",
            ]
            for role, path in profile.items():
                args += ["--artifact", f"{path}::{role}"]
            self.harness(*args)
            proc = self.harness(
                "send-frontier-request",
                "--plan-dir", str(plan),
                "--request-id", "far_large_context",
                "--codex-bin", str(Path(td) / "must-not-run"),
                check=False,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("exceeds reservation", proc.stderr)
            self.assertFalse((plan / "state" / "frontier" / "budget.json").exists())

    def test_frontier_expiration_malformed_response_and_budget_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            expired_plan = self.make_plan(tmp / "expired")
            self.init_model_policy(expired_plan)
            args = self.cp01_create_args(expired_plan, "plan_expired", "far_expired")
            args += ["--deadline-seconds", "1"]
            self.harness(*args)
            expired = self.harness(
                "expire-frontier-request", "--plan-dir", str(expired_plan),
                "--request-id", "far_expired", "--now", "2099-01-01T00:00:00Z",
            )
            self.assertEqual(json.loads(expired.stdout)["state"], "PAUSED")

            malformed_plan = self.make_plan(tmp / "malformed")
            self.init_model_policy(malformed_plan)
            self.harness(*self.cp01_create_args(malformed_plan, "plan_malformed", "far_test_request"))
            self.harness(
                "send-frontier-request", "--plan-dir", str(malformed_plan),
                "--request-id", "far_test_request", "--codex-bin", str(self.fake_codex(tmp)),
            )
            response = malformed_plan / "state" / "frontier" / "requests" / "far_test_request" / "response.json"
            response.chmod(0o644)
            bad = json.loads(response.read_text())
            bad.pop("plan_id")
            response.write_text(json.dumps(bad))
            invalid = self.harness(
                "validate-frontier-response", "--plan-dir", str(malformed_plan),
                "--request-id", "far_test_request", check=False,
            )
            self.assertEqual(invalid.returncode, 2)
            status = json.loads((response.parent / "status.json").read_text())
            self.assertEqual(status["state"], "PAUSED")

            budget_plan = self.make_plan(tmp / "budget")
            self.harness(
                "init-policy", "--plan-dir", str(budget_plan), "--worker-model", "MiniMax-M3-test",
                "--worker-max-budget-usd", "0.25", "--frontier-model", "frontier",
                "--max-frontier-calls", "0", "--max-frontier-input-tokens", "1000",
                "--max-frontier-output-tokens", "1000",
            )
            self.harness(*self.cp01_create_args(budget_plan, "plan_budget", "far_budget"))
            exhausted = self.harness(
                "send-frontier-request", "--plan-dir", str(budget_plan), "--request-id", "far_budget",
                "--codex-bin", str(self.fake_codex(tmp)), check=False,
            )
            self.assertEqual(exhausted.returncode, 2)
            self.assertIn("budget exhausted", exhausted.stderr)

    def test_model_rescue_cannot_apply_forbidden_accept(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            self.write_manifest(plan)
            (plan / "state.json").write_text(json.dumps({
                "state": {
                    "status": "paused",
                    "cycle_started_at": int((time.time() - 1200) * 1000),
                    "results": [],
                }
            }))
            judge = tmp / ".mavis" / "agents" / "mavis" / "scripts" / "local_llm_judge.py"
            judge.parent.mkdir(parents=True)
            judge.write_text(
                "#!/usr/bin/env python3\n"
                "print('{\"verdict\":\"accept\",\"reason\":\"looks fine\"}')\n"
            )
            judge.chmod(0o755)
            env = self.fake_mavis_env(tmp)
            run([
                sys.executable,
                "references/scripts/plan-rescue-daemon.py",
                "--once",
            ], env={**env, "HOME": str(tmp), "AUTORESEARCH_PLAN_ROOTS": str(tmp)})
            proposal = json.loads((plan / "control" / "model_advisory_proposal.json").read_text())
            self.assertTrue(proposal["advisory_only"])
            self.assertEqual(proposal["advice"]["verdict"], "escalate_human")
            self.assertIn("forbidden lifecycle action", proposal["advice"]["reason"])
            log = Path(env["MAVIS_FAKE_LOG"])
            self.assertFalse(log.exists(), "model advice must not call mavis lifecycle commands")

    def test_cleanup_complete_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = self.make_plan(Path(td))
            self.write_manifest(plan, plan_id=None)
            run(["bash", "references/scripts/cleanup-plan-resources.sh", str(plan), "--mode", "complete"])
            manifest = json.loads((plan / "resource_manifest.json").read_text())
            self.assertEqual(manifest["status"], "running")
            self.assertIn("no resources removed", (plan / "cleanup_report.md").read_text())

    def test_bootstrap_rescue_creates_launchagents_parent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan")
            (plan / "watchdog-system-prompt.md").write_text("watchdog prompt\n")
            env = {**self.fake_mavis_env(tmp), "HOME": str(tmp)}
            run([
                "bash",
                "references/bootstrap-watchdog.sh",
                "smoke",
                "conference",
                str(plan),
                "--rescue",
            ], env=env)
            self.assertTrue((tmp / "Library" / "LaunchAgents").is_dir())
            self.assertTrue((plan / "WATCHDOG.md").read_text().find("--rescue") >= 0)
            manifest = json.loads((plan / "resource_manifest.json").read_text())
            self.assertEqual(manifest["topic_slug"], "smoke")
            self.assertEqual(manifest["launchd"][0]["run_scoped"], False)

    def test_research_writing_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp)
            self.write_manifest(plan)
            gate = plan / "state" / "research_acceptance.md"
            gate.write_text("PASS\n")
            proc = run([
                "python3",
                "references/scripts/research-state-guard.py",
                "check-writing-gate",
                "--plan-dir",
                str(plan),
                "--tier",
                "arxiv",
            ], check=False)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("--figure-gate-receipt", proc.stderr)

            # Positive evaluator/writing coverage now executes through the
            # packaged canonical workflow; this legacy entry remains a
            # fail-closed compatibility regression for bare PASS text.

    def test_structural_pivot_guard(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = self.make_plan(Path(td))
            (plan / "state" / "failure_state.json").write_text(json.dumps({
                "scientific_pivot_threshold": 2,
                "distinct_scientific_fingerprints": ["direction-a", "direction-b"],
            }) + "\n")
            weak = plan / "weak-pivot.json"
            weak.write_text(json.dumps({"changed_fields": ["learning_rate"]}))
            proc = run([
                "python3",
                "references/scripts/research-state-guard.py",
                "validate-pivot",
                "--plan-dir",
                str(plan),
                "--proposal",
                str(weak),
            ], check=False)
            self.assertEqual(proc.returncode, 2)

            strong = plan / "strong-pivot.json"
            strong.write_text(json.dumps({"changed_fields": ["algorithm_family"]}))
            proc = run([
                "python3",
                "references/scripts/research-state-guard.py",
                "validate-pivot",
                "--plan-dir",
                str(plan),
                "--proposal",
                str(strong),
            ], check=False)
            self.assertEqual(proc.returncode, 2)

    def test_l0_dry_run_does_not_mutate_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = self.make_plan(Path(td))
            self.write_manifest(plan)
            (plan / "state.json").write_text(json.dumps({"state": {"status": "running", "cycle_started_at": 0}}))
            before = sorted(str(p.relative_to(plan)) for p in plan.rglob("*") if p.is_file())
            proc = run([
                "python3",
                "references/scripts/plan-l0-guard.py",
                "--plan-dir",
                str(plan),
                "--once",
                "--stale-sec",
                "1",
                "--dry-run",
            ])
            self.assertIn("stale_observed", proc.stdout)
            after = sorted(str(p.relative_to(plan)) for p in plan.rglob("*") if p.is_file())
            self.assertEqual(before, after)

    def test_l0_staged_state_wins_without_rewriting_progress_projection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = self.make_plan(Path(td))
            self.write_manifest(plan)
            staged = plan / "state" / "staged_research" / "v1"
            staged.mkdir(parents=True)
            (staged / "state.json").write_text(json.dumps({
                "plan_id": "plan_abc",
                "state": "PAUSED",
                "active_stage_id": "stage_1",
            }) + "\n")
            # Both legacy sources deliberately disagree with staged authority.
            (plan / "state.json").write_text(json.dumps({
                "state": {"status": "running", "cycle_started_at": 0},
            }) + "\n")
            progress = plan / "state" / "progress.json"
            progress.write_text(json.dumps({
                "status": "running",
                "projection_version": "staged-research-progress/v1",
                "sentinel": "controller-owned-bytes",
            }, indent=2) + "\n")
            before = progress.read_bytes()

            proc = run([
                "python3", "references/scripts/plan-l0-guard.py",
                "--plan-dir", str(plan), "--once", "--stale-sec", "1",
            ])

            result = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertEqual(result["status"], "PAUSED")
            self.assertEqual(result["state_source"], "staged_research/v1")
            self.assertEqual(result["action"], "ok")
            self.assertEqual(progress.read_bytes(), before)
            l0 = json.loads((plan / "state" / "l0_status.json").read_text())
            self.assertEqual(l0["state_source"], "staged_research/v1")

    def test_malformed_or_unknown_staged_state_never_falls_back_to_legacy(self) -> None:
        for case in ("malformed", "unknown"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                plan = self.make_plan(tmp, f"staged_invalid_{case}")
                self.write_manifest(plan)
                staged = plan / "state" / "staged_research" / "v1"
                staged.mkdir(parents=True)
                staged_state = staged / "state.json"
                if case == "malformed":
                    staged_state.write_text("{not-json\n")
                else:
                    staged_state.write_text(json.dumps({
                        "plan_id": "plan_staged",
                        "state": "UNKNOWN_FUTURE_STATE",
                    }) + "\n")
                (plan / "state.json").write_text(json.dumps({
                    "state": {"status": "running", "cycle_started_at": 0},
                }) + "\n")
                progress = plan / "state" / "progress.json"
                progress.write_text(json.dumps({
                    "status": "running", "sentinel": "legacy-must-not-win",
                }, indent=2) + "\n")
                before = progress.read_bytes()

                l0_proc = run([
                    "python3", "references/scripts/plan-l0-guard.py",
                    "--plan-dir", str(plan), "--once", "--stale-sec", "1",
                ])
                l0 = json.loads(l0_proc.stdout.strip().splitlines()[-1])
                self.assertEqual(l0["action"], "invalid_staged_state")
                self.assertEqual(l0["state_source"], "staged_invalid")
                self.assertEqual(progress.read_bytes(), before)

                rescue_proc = run([
                    "python3", "references/scripts/plan-rescue-daemon.py",
                    "--dry-run", "--once",
                ], env={
                    "HOME": str(tmp),
                    "AUTORESEARCH_PLAN_ROOTS": str(tmp),
                })
                self.assertIn(
                    f"staged_invalid_{case}: invalid_staged_state",
                    rescue_proc.stdout,
                )
                self.assertEqual(progress.read_bytes(), before)

    def test_l0_runtime_stall_never_enables_scientific_pivot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = self.make_plan(Path(td))
            self.write_manifest(plan)
            (plan / "state.json").write_text(json.dumps({"state": {"status": "running", "cycle_started_at": 0}}))
            (plan / "last_seen.jsonl").write_text('{"ts":"2020-01-01T00:00:00Z"}\n')
            run(["python3", "references/scripts/plan-l0-guard.py", "--plan-dir", str(plan), "--once", "--stale-sec", "1"])
            run(["python3", "references/scripts/plan-l0-guard.py", "--plan-dir", str(plan), "--once", "--stale-sec", "1"])
            failures = json.loads((plan / "state" / "failure_state.json").read_text())
            self.assertEqual(failures["runtime_stall_count"], 1)
            self.assertEqual(failures["scientific_no_improvement_count"], 0)
            self.assertFalse((plan / "control" / "pivot_requested.json").exists())
            eligibility = json.loads(self.harness("pivot-eligibility", "--plan-dir", str(plan)).stdout)
            self.assertFalse(eligibility["eligible"])

    def test_rescue_prefers_staged_state_then_falls_back_to_legacy_progress(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            staged_plan = self.make_plan(tmp, "staged_priority")
            self.write_manifest(staged_plan)
            staged = staged_plan / "state" / "staged_research" / "v1"
            staged.mkdir(parents=True)
            (staged / "state.json").write_text(json.dumps({
                "plan_id": "plan_staged",
                "state": "PAUSED",
                "active_stage_id": "stage_1",
                "cycle_started_at": int(time.time() * 1000),
            }) + "\n")
            (staged_plan / "state.json").write_text(json.dumps({
                "state": {"status": "running"},
            }) + "\n")
            (staged_plan / "state" / "progress.json").write_text(json.dumps({
                "status": "running",
            }) + "\n")

            legacy_plan = self.make_plan(tmp, "legacy_fallback")
            self.write_manifest(legacy_plan)
            (legacy_plan / "state" / "progress.json").write_text(json.dumps({
                "status": "running",
            }) + "\n")

            proc = run([
                "python3", "references/scripts/plan-rescue-daemon.py",
                "--dry-run", "--once",
            ], env={"HOME": str(tmp), "AUTORESEARCH_PLAN_ROOTS": str(tmp)})

            self.assertIn("staged_priority: wait", proc.stdout)
            self.assertIn("legacy_fallback: l0_l0_missing", proc.stdout)

    def test_resolve_plan_dir_and_stop_json_escaping(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            root = tmp / "scratchpads"
            plan = self.make_plan(root / "autoresearch" / "topic")
            self.write_manifest(plan, plan_id="plan_quote")
            env = {**self.fake_mavis_env(tmp), "AUTORESEARCH_PLAN_ROOTS": str(root)}
            resolved = run(["python3", "references/scripts/resolve-plan-dir.py", "plan_quote"], env=env).stdout.strip()
            self.assertEqual(Path(resolved), plan.resolve())

            reason = 'bad " quote and slash \\ ok'
            key = self.human_key(tmp)
            action = self.harness(
                "create-human-action", "--plan-dir", str(plan), "--plan-id", "plan_quote",
                "--action", "stop", "--key-file", str(key), "--expires-in", "300",
                "--record-id", "har_stop_quote", "--reason", reason,
            )
            record = json.loads(action.stdout)["record_path"]
            run([
                "bash", "references/scripts/stop-plan.sh", "plan_quote",
                "--record", record, "--key-file", str(key), "--reason", reason,
            ], env=env)
            manifest = json.loads((plan / "resource_manifest.json").read_text())
            self.assertEqual(manifest["status"], "running")
            self.assertEqual(json.loads((plan / "state" / "controller.json").read_text())["status"], "stopped")
            audit = [json.loads(line) for line in (plan / "state" / "human_action_audit.jsonl").read_text().splitlines()]
            self.assertEqual(audit[-1]["action"], "stop")
            self.assertIn("no resources removed", (plan / "cleanup_report.md").read_text())

    def test_human_actions_reject_forgery_replay_cross_plan_and_bad_key_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "a")
            self.write_manifest(plan)
            key = self.human_key(tmp)
            record = self.create_action(plan, key, "pause", record_id="har_pause")
            forged = tmp / "forged.json"
            data = json.loads(record.read_text())
            data["action"] = "stop"
            forged.write_text(json.dumps(data))
            rejected = self.harness(
                "apply-human-action", "--plan-dir", str(plan), "--record", str(forged),
                "--key-file", str(key), check=False,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertFalse((plan / "control" / "stop_requested.json").exists())

            applied = self.harness(
                "apply-human-action", "--plan-dir", str(plan), "--record", str(record),
                "--key-file", str(key), "--expected-action", "pause",
            )
            self.assertEqual(json.loads(applied.stdout)["receipt"]["action"], "pause")
            replay = self.harness(
                "apply-human-action", "--plan-dir", str(plan), "--record", str(record),
                "--key-file", str(key), check=False,
            )
            self.assertEqual(replay.returncode, 2)

            other = self.make_plan(tmp / "b")
            self.write_manifest(other, plan_id="plan_other")
            cross = self.harness(
                "apply-human-action", "--plan-dir", str(other), "--record", str(record),
                "--key-file", str(key), check=False,
            )
            self.assertEqual(cross.returncode, 2)
            key.chmod(0o644)
            bad_mode = self.harness(
                "create-human-action", "--plan-dir", str(plan), "--plan-id", "plan_abc",
                "--action", "resume", "--key-file", str(key), "--expires-in", "60", check=False,
            )
            self.assertEqual(bad_mode.returncode, 2)

    def test_expired_and_wrong_human_action_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp)
            self.write_manifest(plan)
            key = self.human_key(tmp)
            record = self.create_action(plan, key, "pause", record_id="har_expired")
            data = json.loads(record.read_text())
            payload = {k: v for k, v in data.items() if k != "signature"}
            payload["expires_at"] = "2020-01-01T00:00:00Z"
            data = {**payload, "signature": __import__("hmac").new(key.read_bytes(), json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(), hashlib.sha256).hexdigest()}
            expired = tmp / "expired.json"
            expired.write_text(json.dumps(data))
            proc = self.harness(
                "apply-human-action", "--plan-dir", str(plan), "--record", str(expired),
                "--key-file", str(key), check=False,
            )
            self.assertEqual(proc.returncode, 2)
            wrong = self.harness(
                "apply-human-action", "--plan-dir", str(plan), "--record", str(record),
                "--key-file", str(key), "--expected-action", "resume", check=False,
            )
            self.assertEqual(wrong.returncode, 2)
            self.assertFalse((plan / "state" / "human_action_replay.json").exists())

    def test_authenticated_pause_and_resume_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp)
            self.write_manifest(plan)
            key = self.human_key(tmp)
            pause = self.create_action(plan, key, "pause", record_id="har_wrapper_pause")
            run([
                "bash", "references/scripts/pause-plan.sh", str(plan),
                "--record", str(pause), "--key-file", str(key),
            ])
            self.assertEqual(json.loads((plan / "state" / "controller.json").read_text())["status"], "paused")
            resume = self.create_action(plan, key, "resume", record_id="har_wrapper_resume")
            run([
                "bash", "references/scripts/resume-plan.sh", str(plan),
                "--record", str(resume), "--key-file", str(key),
            ])
            self.assertEqual(json.loads((plan / "state" / "controller.json").read_text())["status"], "running")

    def test_typed_failures_runtime_operations_and_owned_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp)
            owned = plan / "scratch.tmp"
            owned.write_text("owned")
            nonce = "ownership-1"
            self.write_manifest(plan, resources=[{
                "resource_id": "scratch", "path": str(owned), "ephemeral": True,
                "run_scoped": True, "ownership_nonce": nonce,
            }])
            for kind, fingerprint in (
                ("runtime_stall", "runtime-a"),
                ("implementation_failure", "implementation-a"),
            ):
                self.harness(
                    "record-failure", "--plan-dir", str(plan), "--class", kind,
                    "--fingerprint", fingerprint, "--source", "test",
                )
            duplicate = json.loads(self.harness(
                "record-failure", "--plan-dir", str(plan), "--class", "runtime_stall",
                "--fingerprint", "runtime-a", "--source", "test",
            ).stdout)
            self.assertTrue(duplicate["idempotent"])
            self.assertFalse(json.loads(self.harness("pivot-eligibility", "--plan-dir", str(plan)).stdout)["eligible"])

            run_id = "cwr_" + "a" * 32
            run_dir = plan / "state" / "worker_runs" / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "status.json").write_text(json.dumps({
                "schema_version": 1, "run_id": run_id, "status": "RUNNING",
                "started_at": "2020-01-01T00:00:00Z",
            }))
            self.assertEqual(json.loads(self.harness(
                "inspect-worker", "--plan-dir", str(plan), "--worker-run-id", run_id,
            ).stdout)["status"], "RUNNING")
            self.harness(
                "send-worker-message", "--plan-dir", str(plan), "--worker-run-id", run_id,
                "--message", "advisory only",
            )
            self.harness("schedule-patrol", "--plan-dir", str(plan), "--interval-seconds", "60")
            patrol = json.loads(self.harness(
                "run-patrol", "--plan-dir", str(plan), "--stale-seconds", "1",
            ).stdout)
            self.assertEqual(patrol["stale_workers"], [run_id])

            key = self.human_key(tmp)
            cancel = self.create_action(
                plan, key, "cancel_worker", record_id="har_cancel",
                extra=("--worker-run-id", run_id),
            )
            self.harness(
                "cancel-worker", "--plan-dir", str(plan), "--record", str(cancel),
                "--key-file", str(key), "--worker-run-id", run_id,
            )
            waited = self.harness(
                "wait-worker", "--plan-dir", str(plan), "--worker-run-id", run_id,
                "--deadline-seconds", "1", check=False,
            )
            self.assertEqual(waited.returncode, 2)
            terminal_message = self.harness(
                "send-worker-message", "--plan-dir", str(plan), "--worker-run-id", run_id,
                "--message", "must be rejected", check=False,
            )
            self.assertEqual(terminal_message.returncode, 2)

            cleanup = self.create_action(
                plan, key, "cleanup_resource", record_id="har_cleanup",
                extra=("--resource-id", "scratch"),
            )
            receipt = json.loads(self.harness(
                "apply-human-action", "--plan-dir", str(plan), "--record", str(cleanup),
                "--key-file", str(key), "--expected-action", "cleanup_resource",
            ).stdout)["receipt"]
            token = hashlib.sha256(f"plan_abc\0{owned.resolve()}\0{nonce}".encode()).hexdigest()
            wrong_token = self.harness(
                "remove-resource", "--plan-dir", str(plan), "--resource-id", "scratch",
                "--ownership-token", "0" * 64, "--authorization", receipt["authorization_path"],
                check=False,
            )
            self.assertEqual(wrong_token.returncode, 2)
            self.assertTrue(owned.exists())
            self.harness(
                "remove-resource", "--plan-dir", str(plan), "--resource-id", "scratch",
                "--ownership-token", token, "--authorization", receipt["authorization_path"],
            )
            self.assertFalse(owned.exists())

    def test_rescue_dry_run_does_not_call_mavis_or_write_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            plan = self.make_plan(tmp / "plan_stop")
            self.write_manifest(plan)
            (plan / "state.json").write_text(json.dumps({"state": {"status": "running"}}))
            (plan / "control" / "stop_requested.json").write_text("{}")
            env = self.fake_mavis_env(tmp)
            run([
                "python3",
                "references/scripts/plan-rescue-daemon.py",
                "--dry-run",
                "--once",
            ], env={**env, "HOME": str(tmp), "AUTORESEARCH_PLAN_ROOTS": str(tmp)})
            log = Path(env["MAVIS_FAKE_LOG"])
            self.assertFalse(log.exists(), "dry-run should not call mavis")
            self.assertFalse((plan / "state" / "rescue_history.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
