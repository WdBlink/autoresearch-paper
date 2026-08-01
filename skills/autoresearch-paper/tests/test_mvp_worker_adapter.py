#!/usr/bin/env python3
"""Contracts for the isolated MVP-0 P2 Worker Adapter."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from mvp import worker_adapter as adapter  # noqa: E402


def canonical_digest(value: object) -> str:
    return hashlib.sha256(adapter._canonical_bytes(value)).hexdigest()  # noqa: SLF001


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class WorkerAdapterContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        subprocess.run(["git", "init", "-q", str(self.source)], check=True)
        subprocess.run(
            ["git", "-C", str(self.source), "config", "user.email", "mvp0@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.source), "config", "user.name", "MVP0 Test"],
            check=True,
        )
        (self.source / "src").mkdir()
        (self.source / "src" / "base.txt").write_text("base\n", encoding="utf-8")
        (self.source / ".gitignore").write_text("artifacts/\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.source), "add", ".gitignore", "src/base.txt"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.source), "commit", "-qm", "base"], check=True)
        self.ir = {
            "source": {"code_root": str(self.source)},
            "allowed_search_space": [
                {
                    "id": "implementation",
                    "paths": ["src/**", "artifacts/**"],
                    "operations": ["CREATE", "MODIFY"],
                }
            ],
            "experiment_plan": [
                {
                    "id": "exp-one",
                    "search_space_ids": ["implementation"],
                    "command_argv": ["python3", "run.py", "--stage", "one"],
                    "expected_artifacts": ["artifacts/**"],
                }
            ],
        }
        self.ir_digest = canonical_digest(self.ir)
        self.store = self.root / "compiler-store"
        ir_path = self.store / "objects" / "sha256" / f"{self.ir_digest}.json"
        ir_path.parent.mkdir(parents=True)
        ir_path.write_bytes(adapter._canonical_bytes(self.ir))  # noqa: SLF001
        self.freeze = write_json(self.root / "freeze.json", {"approval_scope": "OWNER_REVIEWED"})
        self.freeze_digest = hashlib.sha256(self.freeze.read_bytes()).hexdigest()
        self.claude, self.log = self.make_fake_claude()
        self.adapter_dir = self.root / "adapter"
        self.worktree = self.root / "research-worktree"
        with mock.patch.object(
            adapter,
            "_load_verified_ir",
            return_value=(
                self.ir,
                {"approval_scope": "OWNER_REVIEWED"},
                self.freeze_digest,
                self.ir_digest,
            ),
        ):
            adapter.initialize_adapter(
                freeze_receipt=self.freeze,
                compiler_store=self.store,
                source_repo=self.source,
                adapter_dir=self.adapter_dir,
                worktree=self.worktree,
                claude_bin=str(self.claude),
                worker_model="MiniMax-M3",
                max_budget_usd_per_turn=1.5,
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_fake_claude(self) -> tuple[Path, Path]:
        executable = self.root / "fake-claude"
        log = self.root / "claude-argv.jsonl"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import hashlib, json, os, pathlib, subprocess, sys, time\n"
            "args = sys.argv[1:]\n"
            "with open(os.environ['MVP0_CLAUDE_ARGV_LOG'], 'a') as handle:\n"
            "  handle.write(json.dumps(args) + '\\n')\n"
            "prompt = json.loads(sys.stdin.read())\n"
            "task = prompt['task_contract']\n"
            "flag = '--session-id' if '--session-id' in args else '--resume'\n"
            "session_id = args[args.index(flag) + 1]\n"
            "session_id = os.environ.get('MVP0_FAKE_SESSION', session_id)\n"
            "model = os.environ.get('MVP0_FAKE_MODEL', args[args.index('--model') + 1])\n"
            "second_model = os.environ.get('MVP0_FAKE_SECOND_MODEL', model)\n"
            "mode = os.environ.get('MVP0_FAKE_MODE', 'complete')\n"
            "if mode == 'invalid-utf8':\n"
            "  sys.stdout.buffer.write(b'\\xff')\n"
            "  sys.stdout.buffer.flush()\n"
            "  raise SystemExit(0)\n"
            "if mode == 'timeout-child':\n"
            "  subprocess.Popen([sys.executable, '-c', \"import pathlib,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(1.5); pathlib.Path('src/late.txt').write_text('late\\\\n')\"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "  time.sleep(10)\n"
            "artifacts = []\n"
            "observations = []\n"
            "if mode == 'complete':\n"
            "  relative = 'src/one.txt' if task['task_id'] == 'task-one' else 'artifacts/two.json'\n"
            "  content = ('one\\n' if task['task_id'] == 'task-one' else '{\\\"two\\\": true}\\n')\n"
            "  target = pathlib.Path(relative)\n"
            "  target.parent.mkdir(parents=True, exist_ok=True)\n"
            "  target.write_text(content)\n"
            "  digest = hashlib.sha256(target.read_bytes()).hexdigest()\n"
            "  artifacts = [{'path': relative, 'change_type': 'CREATED', 'sha256': digest, 'purpose': 'Bounded experiment artifact'}]\n"
            "  observations = [{'statement': 'The bounded artifact was created.', 'evidence': [{'path': relative, 'sha256': digest}]}]\n"
            "elif mode == 'out-of-scope':\n"
            "  pathlib.Path('forbidden.txt').write_text('bad\\n')\n"
            "  digest = hashlib.sha256(pathlib.Path('forbidden.txt').read_bytes()).hexdigest()\n"
            "  artifacts = [{'path': 'forbidden.txt', 'change_type': 'CREATED', 'sha256': digest, 'purpose': 'Out of scope artifact'}]\n"
            "elif mode == 'symlink-dir':\n"
            "  pathlib.Path('artifacts').mkdir(exist_ok=True)\n"
            "  os.symlink(os.environ['MVP0_FAKE_SYMLINK_TARGET'], 'artifacts/link')\n"
            "elif mode == 'break-git':\n"
            "  pathlib.Path('.git').write_text('broken\\n')\n"
            "elif mode == 'observation-no-evidence':\n"
            "  observations = [{'statement': 'This statement has no controller-verifiable evidence.', 'evidence': []}]\n"
            "result = {\n"
            "  'schema_version': 'worker-result/v1',\n"
            "  'task_id': task['task_id'],\n"
            "  'status': 'BLOCKED' if mode == 'blocked' else 'COMPLETED',\n"
            "  'summary': 'Bounded task completed with controller-verifiable output.',\n"
            "  'artifacts': artifacts,\n"
            "  'commands_run': [],\n"
            "  'observations': observations,\n"
            "  'proposed_next_actions': [],\n"
            "}\n"
            "usage = {'input_tokens': int(os.environ.get('MVP0_FAKE_INPUT', '40')), 'output_tokens': int(os.environ.get('MVP0_FAKE_OUTPUT', '9')), 'cache_creation_input_tokens': 2, 'cache_read_input_tokens': 31}\n"
            "print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': session_id, 'model': model}))\n"
            "print(json.dumps({'type': 'assistant', 'session_id': session_id, 'message': {'model': second_model}}))\n"
            "terminal = {'type': 'result', 'session_id': session_id, 'model': model, 'structured_output': result}\n"
            "if os.environ.get('MVP0_FAKE_OMIT_USAGE') != '1':\n"
            "  terminal['usage'] = usage\n"
            "print(json.dumps(terminal))\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return executable, log

    def task(self, task_id: str) -> dict[str, object]:
        base = self.worktree / "src" / "base.txt"
        return {
            "schema_version": "worker-task-contract/v1",
            "task_id": task_id,
            "research_ir_sha256": self.ir_digest,
            "experiment_id": "exp-one",
            "objective": "Produce one bounded implementation artifact for the frozen experiment.",
            "search_space_ids": ["implementation"],
            "allowed_paths": ["src/**", "artifacts/**"],
            "allowed_operations": ["READ", "CREATE", "MODIFY", "EXECUTE"],
            "input_artifacts": [
                {
                    "path": "src/base.txt",
                    "sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
                    "purpose": "Frozen starting implementation",
                }
            ],
            "command_argv": ["python3", "run.py", "--stage", "one"],
            "acceptance_checks": [
                {"argv": ["python3", "-m", "unittest"], "purpose": "Run deterministic tests"}
            ],
            "stop_conditions": ["Stop if the frozen input hash differs."],
            "max_runtime_seconds": 30,
        }

    def dispatch(
        self,
        task_id: str,
        *,
        env: dict[str, str] | None = None,
        max_runtime_seconds: int = 30,
    ) -> dict[str, object]:
        contract = self.task(task_id)
        contract["max_runtime_seconds"] = max_runtime_seconds
        contract_path = write_json(self.root / f"{task_id}.json", contract)
        with mock.patch.dict(
            os.environ,
            {"MVP0_CLAUDE_ARGV_LOG": str(self.log), **(env or {})},
            clear=False,
        ):
            return adapter.dispatch_task(
                adapter_dir=self.adapter_dir,
                task_contract=contract_path,
            )

    def test_init_binds_detached_worktree_and_immutable_session_manifest(self) -> None:
        manifest_path = self.adapter_dir / "adapter-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest_path.stat().st_mode & 0o777, 0o444)
        self.assertEqual(manifest["worker_model"], "MiniMax-M3")
        self.assertEqual(manifest["worktree_root"], str(self.worktree.resolve()))
        self.assertEqual(
            subprocess.run(
                ["git", "-C", str(self.worktree), "rev-parse", "--abbrev-ref", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "HEAD",
        )
        inspected = adapter.inspect_adapter(adapter_dir=self.adapter_dir)
        self.assertEqual(inspected["session_state"], "READY")
        self.assertEqual(inspected["turn_count"], 0)
        self.assertIn("not an OS sandbox", inspected["isolation_assurance"])

    def test_fixed_session_creates_then_resumes_and_records_usage(self) -> None:
        first = self.dispatch("task-one")
        second = self.dispatch("task-two", env={"MVP0_FAKE_INPUT": "0", "MVP0_FAKE_OUTPUT": "0"})
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertIn("--session-id", calls[0])
        self.assertNotIn("--resume", calls[0])
        session_id = calls[0][calls[0].index("--session-id") + 1]
        self.assertIn("--resume", calls[1])
        self.assertEqual(calls[1][calls[1].index("--resume") + 1], session_id)
        self.assertNotIn("--continue", calls[0])
        self.assertNotIn("--continue", calls[1])
        allowed_start = calls[0].index("--allowedTools") + 1
        allowed_end = calls[0].index("--name")
        allowed = calls[0][allowed_start:allowed_end]
        self.assertNotIn("Bash", allowed)
        self.assertIn("Bash(python3 run.py --stage one)", allowed)
        self.assertIn("Bash(python3 -m unittest)", allowed)
        self.assertEqual(first["outcome"], "COMPLETED")
        self.assertEqual(second["outcome"], "COMPLETED")
        self.assertTrue(first["worker_model_verified"])
        second_result = json.loads(Path(second["result_path"]).read_text())
        self.assertEqual(second_result["artifacts"][0]["path"], "artifacts/two.json")
        receipt = json.loads(Path(second["receipt_path"]).read_text())
        self.assertEqual(receipt["usage"]["input_tokens"], 0)
        self.assertEqual(receipt["usage"]["output_tokens"], 0)
        self.assertEqual(receipt["usage"]["cache_read_input_tokens"], 31)
        self.assertTrue(receipt["usage_complete"])
        session = json.loads((self.adapter_dir / "session.json").read_text())
        self.assertEqual(session["state"], "READY")
        self.assertEqual(session["turn_count"], 2)

    def test_blocked_result_preserves_ready_session_without_changes(self) -> None:
        delivered = self.dispatch("task-one", env={"MVP0_FAKE_MODE": "blocked"})
        self.assertEqual(delivered["outcome"], "BLOCKED")
        self.assertEqual(delivered["session_state"], "READY")
        self.assertFalse((self.worktree / "src" / "one.txt").exists())

    def test_out_of_scope_change_fails_and_pauses_session(self) -> None:
        delivered = self.dispatch("task-one", env={"MVP0_FAKE_MODE": "out-of-scope"})
        self.assertEqual(delivered["outcome"], "FAILED")
        self.assertEqual(delivered["session_state"], "PAUSED")
        receipt = json.loads(Path(delivered["receipt_path"]).read_text())
        self.assertIn("outside the task contract", receipt["failure"])
        rejected = json.loads(Path(receipt["change_manifest_path"]).read_text())
        self.assertEqual(rejected["changes"][0]["path"], "forbidden.txt")
        with self.assertRaisesRegex(adapter.AdapterError, "does not auto-retry"):
            self.dispatch("task-two")

    def test_wrong_reported_model_fails_identity_and_pauses(self) -> None:
        delivered = self.dispatch("task-one", env={"MVP0_FAKE_MODEL": "claude-opus-4"})
        self.assertEqual(delivered["outcome"], "FAILED")
        receipt = json.loads(Path(delivered["receipt_path"]).read_text())
        self.assertFalse(receipt["worker_model_verified"])
        self.assertIn("frozen MiniMax model", receipt["failure"])

    def test_mixed_reported_models_fail_and_receipt_does_not_claim_identity(self) -> None:
        delivered = self.dispatch(
            "task-one",
            env={"MVP0_FAKE_SECOND_MODEL": "claude-opus-4"},
        )
        self.assertEqual(delivered["outcome"], "FAILED")
        receipt = json.loads(Path(delivered["receipt_path"]).read_text())
        self.assertEqual(receipt["reported_models"], ["MiniMax-M3", "claude-opus-4"])
        self.assertFalse(receipt["worker_model_verified"])

    def test_completed_noop_is_rejected(self) -> None:
        delivered = self.dispatch("task-one", env={"MVP0_FAKE_MODE": "noop"})
        self.assertEqual(delivered["outcome"], "FAILED")
        receipt = json.loads(Path(delivered["receipt_path"]).read_text())
        self.assertIn("requires delivery or execution evidence", receipt["failure"])

    def test_completed_observation_without_evidence_is_rejected(self) -> None:
        delivered = self.dispatch(
            "task-one",
            env={"MVP0_FAKE_MODE": "observation-no-evidence"},
        )
        self.assertEqual(delivered["outcome"], "FAILED")
        receipt = json.loads(Path(delivered["receipt_path"]).read_text())
        self.assertIn("schema.minItems", receipt["failure"])

    def test_ignored_directory_symlink_is_detected_and_rejected(self) -> None:
        external = self.root / "external"
        external.mkdir()
        delivered = self.dispatch(
            "task-one",
            env={
                "MVP0_FAKE_MODE": "symlink-dir",
                "MVP0_FAKE_SYMLINK_TARGET": str(external),
            },
        )
        self.assertEqual(delivered["outcome"], "FAILED")
        receipt = json.loads(Path(delivered["receipt_path"]).read_text())
        rejected = json.loads(Path(receipt["change_manifest_path"]).read_text())
        self.assertEqual(rejected["changes"][0]["kind"], "symlink")

    def test_symlink_ancestor_is_rejected_before_input_hashing(self) -> None:
        external = self.root / "external-input"
        external.mkdir()
        secret = external / "secret.txt"
        secret.write_text("outside\n", encoding="utf-8")
        os.symlink(external, self.worktree / "src" / "link")
        contract = self.task("task-one")
        contract["input_artifacts"] = [{
            "path": "src/link/secret.txt",
            "sha256": hashlib.sha256(secret.read_bytes()).hexdigest(),
            "purpose": "Must not traverse a worktree symlink",
        }]
        contract_path = write_json(self.root / "symlink-input.json", contract)
        with self.assertRaisesRegex(adapter.AdapterError, "traverses a symbolic link"):
            adapter.dispatch_task(adapter_dir=self.adapter_dir, task_contract=contract_path)
        self.assertEqual(adapter.inspect_adapter(adapter_dir=self.adapter_dir)["turn_count"], 0)

    def test_existing_symlink_in_write_root_is_rejected_before_transport(self) -> None:
        external = self.root / "external-output"
        external.mkdir()
        os.symlink(external, self.worktree / "src" / "link")
        contract_path = write_json(self.root / "existing-symlink.json", self.task("task-one"))
        with self.assertRaisesRegex(adapter.AdapterError, "write boundary contains a symbolic link"):
            adapter.dispatch_task(adapter_dir=self.adapter_dir, task_contract=contract_path)
        self.assertFalse(self.log.exists())
        self.assertEqual(adapter.inspect_adapter(adapter_dir=self.adapter_dir)["turn_count"], 0)

    def test_broken_git_still_publishes_failed_receipt_and_pauses(self) -> None:
        delivered = self.dispatch("task-one", env={"MVP0_FAKE_MODE": "break-git"})
        self.assertEqual(delivered["outcome"], "FAILED")
        self.assertEqual(delivered["session_state"], "PAUSED")
        receipt = json.loads(Path(delivered["receipt_path"]).read_text())
        rejected = json.loads(Path(receipt["change_manifest_path"]).read_text())
        self.assertFalse(rejected["evidence_complete"])
        self.assertIsNotNone(rejected["evidence_capture_error"])

    def test_timeout_quiesces_process_group_before_receipt(self) -> None:
        delivered = self.dispatch(
            "task-one",
            env={"MVP0_FAKE_MODE": "timeout-child"},
            max_runtime_seconds=1,
        )
        self.assertEqual(delivered["outcome"], "FAILED")
        receipt = json.loads(Path(delivered["receipt_path"]).read_text())
        self.assertEqual(receipt["failure"], "worker_timeout")
        time.sleep(1.8)
        self.assertFalse((self.worktree / "src" / "late.txt").exists())

    def test_invalid_utf8_transport_still_pauses_with_failed_receipt(self) -> None:
        delivered = self.dispatch("task-one", env={"MVP0_FAKE_MODE": "invalid-utf8"})
        self.assertEqual(delivered["outcome"], "FAILED")
        self.assertEqual(delivered["session_state"], "PAUSED")
        receipt = json.loads(Path(delivered["receipt_path"]).read_text())
        self.assertIn("invalid_transport_encoding", receipt["failure"])
        self.assertEqual((Path(receipt["run_dir"]) / "transport.jsonl").read_bytes(), b"\xff")

    def test_wrong_reported_session_fails_identity_and_pauses(self) -> None:
        delivered = self.dispatch(
            "task-one",
            env={"MVP0_FAKE_SESSION": "00000000-0000-4000-8000-000000000000"},
        )
        self.assertEqual(delivered["outcome"], "FAILED")
        receipt = json.loads(Path(delivered["receipt_path"]).read_text())
        self.assertNotEqual(receipt["reported_session_ids"], [receipt["session_id"]])
        self.assertIn("exact bound session_id", receipt["failure"])

    def test_missing_usage_remains_null_observation(self) -> None:
        delivered = self.dispatch("task-one", env={"MVP0_FAKE_OMIT_USAGE": "1"})
        receipt = json.loads(Path(delivered["receipt_path"]).read_text())
        self.assertFalse(receipt["usage_complete"])
        self.assertEqual(
            receipt["usage"],
            {
                "input_tokens": None,
                "output_tokens": None,
                "cache_creation_input_tokens": None,
                "cache_read_input_tokens": None,
            },
        )

    def test_task_contract_cannot_escape_frozen_ir(self) -> None:
        contract = self.task("task-one")
        contract["allowed_paths"] = ["secrets/**"]
        manifest = adapter._adapter_manifest(self.adapter_dir)  # noqa: SLF001
        with self.assertRaisesRegex(adapter.AdapterError, "exact patterns"):
            adapter.validate_task_contract(contract, manifest, self.ir)

    def test_task_contract_input_hash_is_checked_before_transport(self) -> None:
        contract = self.task("task-one")
        contract["input_artifacts"][0]["sha256"] = "0" * 64
        contract_path = write_json(self.root / "wrong-input.json", contract)
        with mock.patch.dict(os.environ, {"MVP0_CLAUDE_ARGV_LOG": str(self.log)}, clear=False):
            with self.assertRaisesRegex(adapter.AdapterError, "input hash changed"):
                adapter.dispatch_task(adapter_dir=self.adapter_dir, task_contract=contract_path)
        self.assertFalse(self.log.exists())
        self.assertEqual(adapter.inspect_adapter(adapter_dir=self.adapter_dir)["turn_count"], 0)

    def test_source_repo_must_be_clean_before_init(self) -> None:
        second_adapter = self.root / "second-adapter"
        second_worktree = self.root / "second-worktree"
        (self.source / "untracked.txt").write_text("dirty\n", encoding="utf-8")
        with mock.patch.object(
            adapter,
            "_load_verified_ir",
            return_value=(
                self.ir,
                {"approval_scope": "OWNER_REVIEWED"},
                self.freeze_digest,
                self.ir_digest,
            ),
        ):
            with self.assertRaisesRegex(adapter.AdapterError, "must be clean"):
                adapter.initialize_adapter(
                    freeze_receipt=self.freeze,
                    compiler_store=self.store,
                    source_repo=self.source,
                    adapter_dir=second_adapter,
                    worktree=second_worktree,
                    claude_bin=str(self.claude),
                    worker_model="MiniMax-M3",
                    max_budget_usd_per_turn=1.5,
                )
        self.assertFalse(second_adapter.exists())
        self.assertFalse(second_worktree.exists())


if __name__ == "__main__":
    unittest.main()
