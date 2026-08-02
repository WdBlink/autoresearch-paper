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
from mvp import research_compiler as compiler  # noqa: E402


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
        base_digest = hashlib.sha256((self.source / "src" / "base.txt").read_bytes()).hexdigest()
        self.brief = self.root / "brief.md"
        self.brief.write_text(
            "A bounded unit research brief for the MVP thin-loop contract.\n",
            encoding="utf-8",
        )
        brief_digest = hashlib.sha256(self.brief.read_bytes()).hexdigest()
        self.ir = {
            "schema_version": "research-ir/v1",
            "ir_id": "unit-research",
            "version": 1,
            "parent_ir_sha256": None,
            "source": {
                "source_task_id": "unit-research-task-0001",
                "source_summary": "Compile one bounded unit intervention into a falsifiable and replayable research contract.",
                "brief_artifact": {
                    "path": str(self.brief),
                    "sha256": brief_digest,
                },
                "workspace_root": str(self.root),
                "code_root": str(self.source),
            },
            "problem_statement": "Determine whether one bounded unit intervention improves fixture quality without violating the latency guardrail.",
            "central_claim": {
                "statement": "The bounded unit intervention improves fixture quality over the unit baseline without regressing latency.",
                "baseline_id": "unit-baseline",
                "primary_metric_id": "quality",
                "evaluation_scope": "Identical fixture inputs, seeds, evaluator implementation, and execution environment.",
            },
            "related_work_gap": {
                "statement": "The fixture has a baseline implementation but no prior content-addressed intervention comparison.",
                "evidence_refs": [
                    {
                        "source_id": "unit-baseline-source",
                        "locator": str(self.source / "src" / "base.txt"),
                        "supports": "The unit baseline implementation exists before the intervention.",
                        "sha256": base_digest,
                    }
                ],
            },
            "baseline_contract": {
                "baseline_id": "unit-baseline",
                "status": "READY",
                "description": "The unchanged base fixture evaluated under the same command, seeds, and environment.",
                "source_artifacts": [
                    {
                        "path": str(self.source / "src" / "base.txt"),
                        "sha256": base_digest,
                    }
                ],
                "implementation_artifact": str(self.source / "src" / "base.txt"),
                "implementation_sha256": base_digest,
                "training_argv": ["python3", "run.py", "--stage", "baseline"],
                "comparison_scope": ["same input", "same seeds", "same evaluator"],
            },
            "metric_contract": {
                "primary_metric": {
                    "metric_id": "quality",
                    "name": "Fixture quality",
                    "direction": "maximize",
                    "unit": "ratio",
                    "acceptance": {
                        "aggregation": "ci_lower",
                        "operator": ">=",
                        "value": 0.7,
                        "confidence_level": 0.95,
                        "minimum_seeds": 1,
                    },
                },
                "guardrails": [
                    {
                        "metric_id": "latency",
                        "name": "Fixture latency",
                        "direction": "minimize",
                        "unit": "ms",
                        "acceptance": {
                            "aggregation": "ci_upper",
                            "operator": "<=",
                            "value": 100.0,
                            "confidence_level": 0.95,
                            "minimum_seeds": 1,
                        },
                    }
                ],
            },
            "falsification_conditions": [
                {
                    "id": "quality-collapse",
                    "metric_id": "quality",
                    "aggregation": "ci_lower",
                    "operator": "<",
                    "value": 0.4,
                    "decision": "REJECT_CLAIM",
                },
                {
                    "id": "latency-collapse",
                    "metric_id": "latency",
                    "aggregation": "ci_upper",
                    "operator": ">",
                    "value": 150.0,
                    "decision": "REJECT_CLAIM",
                }
            ],
            "evaluator_spec": {
                "status": "READY",
                "working_directory": str(self.source),
                "command_argv": ["python3", "evaluate.py", "--json"],
                "implementation_artifact": str(self.source / "src" / "base.txt"),
                "implementation_sha256": base_digest,
                "input_contract": "One immutable task contract binds the exact fixture inputs and explicit seeds.",
                "output_contract": "Strict JSON contains per-seed results, aggregate confidence intervals, and artifact hashes.",
                "metric_bindings": [
                    {"metric_id": "quality", "json_path": "$.metrics.quality"},
                    {"metric_id": "latency", "json_path": "$.metrics.latency"},
                ],
            },
            "budget": {
                "max_experiments": 8,
                "max_failed_experiments": 2,
                "max_wall_clock_seconds": 3600,
            },
            "stop_rules": [
                {
                    "id": "catastrophic-safety",
                    "condition": "A frozen catastrophic safety condition is observed.",
                    "action": "STOP",
                    "evidence_required": ["safety-log"],
                },
                {
                    "id": "contract-drift",
                    "condition": "The frozen evaluator contract cannot represent the observation.",
                    "action": "RECOMPILE",
                    "evidence_required": ["schema-drift"],
                },
            ],
            "allowed_search_space": [
                {
                    "id": "implementation",
                    "description": "Modify only the bounded fixture implementation and generated research artifacts.",
                    "paths": ["src/**", "artifacts/**"],
                    "operations": ["CREATE", "MODIFY"],
                }
            ],
            "forbidden_changes": [
                "problem_statement",
                "central_claim",
                "falsification_conditions",
                "related_work_gap",
                "baseline_contract",
                "metric_contract",
                "evaluator_spec",
                "allowed_search_space",
                "experiment_plan",
                "budget",
                "stop_rules",
            ],
            "experiment_plan": [
                {
                    "id": "exp-one",
                    "stage": "BASELINE",
                    "hypothesis": "The bounded unit intervention produces one verifiable artifact.",
                    "intervention": "Modify the bounded fixture implementation and run the frozen command once.",
                    "controls": ["same evaluator", "same seeds"],
                    "expected_observation": "One content-addressed artifact is present.",
                    "falsification_condition_ids": ["quality-collapse", "latency-collapse"],
                    "search_space_ids": ["implementation"],
                    "depends_on": [],
                    "command_argv": ["python3", "run.py", "--stage", "one"],
                    "expected_artifacts": ["artifacts/**"],
                },
                {
                    "id": "exp-two",
                    "stage": "METHOD",
                    "hypothesis": "A second bounded intervention can test the remaining causal uncertainty.",
                    "intervention": "Modify the same bounded implementation while preserving every frozen evaluator control.",
                    "controls": ["same evaluator", "same seeds"],
                    "expected_observation": "The second artifact distinguishes the remaining causal hypotheses.",
                    "falsification_condition_ids": ["quality-collapse", "latency-collapse"],
                    "search_space_ids": ["implementation"],
                    "depends_on": ["exp-one"],
                    "command_argv": ["python3", "run.py", "--stage", "two"],
                    "expected_artifacts": ["artifacts/second.json"],
                },
            ],
        }
        self.store = self.root / "compiler-store"
        proposal_ir = write_json(self.root / "proposal-ir.json", self.ir)
        proposal = compiler.propose(
            ir_path=proposal_ir,
            store=self.store,
            author="codex/unit-proposer",
            recorded_at="2026-08-01T00:00:00Z",
        )
        critique_input = write_json(
            self.root / "critique.json",
            {
                "summary": "Clarify that the unit problem is explicitly content addressed.",
                "verdict": "REVISE",
                "findings": [
                    {
                        "finding_id": "clarify-problem",
                        "severity": "minor",
                        "path": "$.problem_statement",
                        "message": "The fixture problem should name its evidence boundary.",
                        "required_change": "State that all accepted evidence is content addressed.",
                    }
                ],
            },
        )
        critique = compiler.critique(
            proposal_path=Path(proposal["proposal_path"]),
            critique_path=critique_input,
            store=self.store,
            reviewer="owner/unit-critic",
            recorded_at="2026-08-01T00:00:01Z",
        )
        revised_problem = (
            self.ir["problem_statement"]
            + " Every accepted observation is bound to content-addressed evidence."
        )
        revision_input = write_json(
            self.root / "revision.json",
            {
                "summary": "Bind the problem statement to content-addressed evidence.",
                "addressed_finding_ids": ["clarify-problem"],
                "changes": [
                    {
                        "op": "replace",
                        "path": "/problem_statement",
                        "value": revised_problem,
                    }
                ],
            },
        )
        revision = compiler.revise(
            proposal_path=Path(proposal["proposal_path"]),
            critique_record_path=Path(critique["critique_path"]),
            revision_path=revision_input,
            store=self.store,
            author="codex/unit-reviser",
            recorded_at="2026-08-01T00:00:02Z",
        )
        frozen = compiler.freeze(
            revision_path=Path(revision["revision_path"]),
            store=self.store,
            approved_by="owner/unit-approver",
            approval_scope="OWNER_REVIEWED",
            approval_note="Approved as a live-style unit fixture after explicit review.",
            approved_at="2026-08-01T00:00:03Z",
        )
        self.freeze = Path(frozen["freeze_receipt_path"])
        self.freeze_digest = str(frozen["freeze_receipt_sha256"])
        self.ir_digest = str(frozen["research_ir_sha256"])
        self.ir = json.loads(Path(frozen["research_ir_path"]).read_text())
        self.claude, self.log = self.make_fake_claude()
        self.adapter_dir = self.root / "adapter"
        self.worktree = self.root / "research-worktree"
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
            "  'commands_run': ([{'argv': task['command_argv'], 'exit_code': 0, 'summary': 'Frozen experiment command completed.'}] if os.environ.get('MVP0_FAKE_REPORT_COMMAND') == '1' else []),\n"
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
            "experiment_context": {
                "config": {"stage": "one", "optimizer": "test-only"},
                "seeds": [7],
                "data_artifacts": [
                    {
                        "path": "src/base.txt",
                        "sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
                        "version": "fixture-v1",
                        "purpose": "Synthetic unit-test dataset",
                    }
                ],
                "environment": {
                    "description": "Deterministic unit-test environment",
                    "artifacts": [
                        {
                            "path": "src/base.txt",
                            "sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
                            "version": "fixture-env-v1",
                            "purpose": "Synthetic environment lock",
                        }
                    ],
                },
            },
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

    def test_prompt_requires_exact_noninteractive_bash_capabilities(self) -> None:
        contract = self.task("task-exact-bash")
        rendered = adapter._prompt(  # noqa: SLF001
            manifest=adapter._adapter_manifest(self.adapter_dir),  # noqa: SLF001
            contract=contract,
            contract_digest=canonical_digest(contract),
        )
        self.assertIn("Do not append 2>&1", rendered)
        self.assertIn("do not run extra Bash diagnostic commands", rendered)
        self.assertIn("Host already verified every input_artifact", rendered)

    def test_inventory_excludes_interpreter_and_pytest_caches(self) -> None:
        pycache = self.worktree / "src" / "__pycache__"
        pycache.mkdir()
        (pycache / "module.cpython-312.pyc").write_bytes(b"cache")
        pytest_cache = self.worktree / "src" / ".pytest_cache"
        pytest_cache.mkdir()
        (pytest_cache / "README.md").write_text("cache\n", encoding="utf-8")
        observed = adapter._inventory(self.worktree, ("src/**",))  # noqa: SLF001
        self.assertNotIn("src/__pycache__/module.cpython-312.pyc", observed)
        self.assertNotIn("src/.pytest_cache/README.md", observed)

    def test_transport_result_classifies_adapter_turn_budget(self) -> None:
        failure = adapter._classify_failure(  # noqa: SLF001
            1,
            "",
            ({"type": "result", "subtype": "error_max_budget_usd"},),
        )
        self.assertEqual(failure, "adapter_turn_budget_exhausted")

    def test_claude_transport_schema_drops_unsupported_2020_12_metaschema(self) -> None:
        schema = adapter._result_transport_schema()  # noqa: SLF001
        rendered = json.dumps(schema, sort_keys=True)
        self.assertNotIn("$schema", schema)
        self.assertNotIn("$id", schema)
        self.assertNotIn("$defs", rendered)
        self.assertNotIn("#/$defs/", rendered)
        self.assertNotIn("2020-12", rendered)
        self.assertIn("definitions", schema)

        delivered = self.dispatch("task-one")
        self.assertEqual(delivered["outcome"], "COMPLETED")
        argv = json.loads(self.log.read_text().splitlines()[0])
        transported = json.loads(argv[argv.index("--json-schema") + 1])
        self.assertEqual(transported, schema)

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
        input_archive = Path(receipt["input_archive_path"])
        self.assertEqual(input_archive.stat().st_mode & 0o777, 0o444)
        self.assertEqual(
            hashlib.sha256(input_archive.read_bytes()).hexdigest(),
            receipt["input_archive_sha256"],
        )
        archived = json.loads(input_archive.read_text())["artifacts"][0]
        self.assertEqual(archived["path"], "src/base.txt")
        self.assertEqual(
            hashlib.sha256(Path(archived["blob_path"]).read_bytes()).hexdigest(),
            archived["sha256"],
        )
        self.assertEqual(receipt["usage"]["input_tokens"], 0)
        self.assertEqual(receipt["usage"]["output_tokens"], 0)
        self.assertEqual(receipt["usage"]["cache_read_input_tokens"], 31)
        self.assertTrue(receipt["usage_complete"])
        session = json.loads((self.adapter_dir / "session.json").read_text())
        self.assertEqual(session["state"], "READY")
        self.assertEqual(session["turn_count"], 2)

    def test_failed_predecessor_session_is_resumed_by_successor_adapter(self) -> None:
        failed = self.dispatch("task-one", env={"MVP0_FAKE_MODE": "out-of-scope"})
        child_ir = json.loads(json.dumps(self.ir))
        child_ir["version"] = 2
        child_ir["parent_ir_sha256"] = self.ir_digest
        child_ir["budget"]["max_experiments"] += 1
        proposal = compiler.propose(
            ir_path=write_json(self.root / "successor-ir.json", child_ir),
            store=self.store,
            author="codex/successor-compiler",
            recorded_at="2026-08-01T01:00:00Z",
        )
        critique = compiler.critique(
            proposal_path=Path(proposal["proposal_path"]),
            critique_path=write_json(
                self.root / "successor-critique.json",
                {
                    "summary": "Request an explicit confirmation of the bounded successor budget.",
                    "verdict": "REVISE",
                    "findings": [
                        {
                            "finding_id": "confirm-budget",
                            "severity": "minor",
                            "path": "$.budget.max_experiments",
                            "message": "The bounded budget should be explicitly confirmed.",
                            "required_change": "Confirm the exact successor experiment count.",
                        }
                    ],
                },
            ),
            store=self.store,
            reviewer="owner/successor-critic",
            recorded_at="2026-08-01T01:00:01Z",
        )
        revision = compiler.revise(
            proposal_path=Path(proposal["proposal_path"]),
            critique_record_path=Path(critique["critique_path"]),
            revision_path=write_json(
                self.root / "successor-revision.json",
                {
                    "summary": "Confirm the exact bounded successor experiment count.",
                    "addressed_finding_ids": ["confirm-budget"],
                    "changes": [
                        {
                            "op": "replace",
                            "path": "/budget/max_experiments",
                            "value": child_ir["budget"]["max_experiments"],
                        }
                    ],
                },
            ),
            store=self.store,
            author="codex/successor-reviser",
            recorded_at="2026-08-01T01:00:02Z",
        )
        frozen = compiler.freeze(
            revision_path=Path(revision["revision_path"]),
            store=self.store,
            approved_by="owner/successor-approver",
            approval_scope="OWNER_REVIEWED",
            approval_note="Approve the bounded successor for fixed-session resume testing.",
            approved_at="2026-08-01T01:00:03Z",
        )
        p5_store = self.root / "p5"
        freeze_root = p5_store / "freezes" / "sha256"
        freeze_root.mkdir(parents=True)
        p5_value = {
            "approval_scope": "OWNER_REVIEWED",
            "bound_at": "2026-08-01T01:00:03Z",
            "child_freeze_receipt_path": frozen["freeze_receipt_path"],
            "child_freeze_receipt_sha256": frozen["freeze_receipt_sha256"],
            "child_ir_sha256": frozen["research_ir_sha256"],
            "child_ir_version": 2,
            "parent_freeze_receipt_sha256": self.freeze_digest,
            "parent_ir_sha256": self.ir_digest,
            "proposal_sha256": "1" * 64,
            "request_sha256": "2" * 64,
            "schema_version": "recompile-freeze/v1",
        }
        p5_payload = adapter._canonical_bytes(p5_value)  # noqa: SLF001
        p5_digest = hashlib.sha256(p5_payload).hexdigest()
        p5_path = freeze_root / f"{p5_digest}.json"
        p5_path.write_bytes(p5_payload)
        p5_path.chmod(0o444)
        child_adapter = self.root / "successor-adapter"
        child_worktree = self.root / "successor-worktree"
        with mock.patch("mvp.recompile_loop.verify_store", return_value={"stage": "FROZEN"}):
            initialized = adapter.initialize_adapter(
                freeze_receipt=Path(frozen["freeze_receipt_path"]),
                compiler_store=self.store,
                source_repo=self.source,
                adapter_dir=child_adapter,
                worktree=child_worktree,
                claude_bin=str(self.claude),
                worker_model="MiniMax-M3",
                max_budget_usd_per_turn=2.0,
                predecessor_turn_receipt=Path(failed["receipt_path"]),
                p5_store=p5_store,
                p5_freeze_binding=p5_path,
            )
        self.assertEqual(initialized["session_id"], failed["session_id"])
        child_manifest = adapter._adapter_manifest(child_adapter)  # noqa: SLF001
        self.assertEqual(child_manifest["session_start_mode"], "RESUME_PREDECESSOR")
        child_contract = self.task("task-successor")
        child_contract["research_ir_sha256"] = frozen["research_ir_sha256"]
        child_contract["input_artifacts"][0]["sha256"] = hashlib.sha256(
            (child_worktree / "src" / "base.txt").read_bytes()
        ).hexdigest()
        child_contract["experiment_context"]["data_artifacts"][0]["sha256"] = child_contract["input_artifacts"][0]["sha256"]
        child_contract["experiment_context"]["environment"]["artifacts"][0]["sha256"] = child_contract["input_artifacts"][0]["sha256"]
        with mock.patch.dict(
            os.environ, {"MVP0_CLAUDE_ARGV_LOG": str(self.log)}, clear=False
        ):
            delivered = adapter.dispatch_task(
                adapter_dir=child_adapter,
                task_contract=write_json(self.root / "successor-task.json", child_contract),
            )
        argv = json.loads(self.log.read_text().splitlines()[-1])
        self.assertEqual(delivered["outcome"], "COMPLETED")
        self.assertIn("--resume", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], failed["session_id"])
        self.assertNotIn("--session-id", argv)

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
        contract["experiment_context"]["data_artifacts"] = []
        contract["experiment_context"]["environment"]["artifacts"] = []
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
        contract["experiment_context"]["data_artifacts"][0]["sha256"] = "0" * 64
        contract["experiment_context"]["environment"]["artifacts"][0]["sha256"] = "0" * 64
        contract_path = write_json(self.root / "wrong-input.json", contract)
        with mock.patch.dict(os.environ, {"MVP0_CLAUDE_ARGV_LOG": str(self.log)}, clear=False):
            with self.assertRaisesRegex(adapter.AdapterError, "input hash changed"):
                adapter.dispatch_task(adapter_dir=self.adapter_dir, task_contract=contract_path)
        self.assertFalse(self.log.exists())
        self.assertEqual(adapter.inspect_adapter(adapter_dir=self.adapter_dir)["turn_count"], 0)

    def test_unattended_dispatch_requires_runtime_assurance(self) -> None:
        contract_path = write_json(self.root / "unattended.json", self.task("task-one"))
        with self.assertRaisesRegex(adapter.AdapterError, "runtime assurance"):
            adapter.dispatch_task(
                adapter_dir=self.adapter_dir,
                task_contract=contract_path,
                unattended=True,
            )
        self.assertFalse(self.log.exists())
        self.assertEqual(adapter.inspect_adapter(adapter_dir=self.adapter_dir)["turn_count"], 0)

    def test_unattended_dispatch_fails_before_transport_when_activation_is_invalid(self) -> None:
        contract_path = write_json(self.root / "invalid-activation.json", self.task("task-one"))
        with mock.patch.object(
            adapter.runtime_assurance,
            "verify_activation",
            side_effect=adapter.runtime_assurance.AssuranceError("L0 service is unloaded"),
        ) as verify:
            with self.assertRaisesRegex(adapter.AdapterError, "L0 service is unloaded"):
                adapter.dispatch_task(
                    adapter_dir=self.adapter_dir,
                    task_contract=contract_path,
                    unattended=True,
                    runtime_store=self.root / "runtime",
                    scheduler=object(),
                )
        verify.assert_called_once()
        self.assertFalse(self.log.exists())
        self.assertEqual(adapter.inspect_adapter(adapter_dir=self.adapter_dir)["turn_count"], 0)

    def test_unattended_dispatch_emits_identity_bound_l2_heartbeat(self) -> None:
        contract_path = write_json(self.root / "heartbeat-task.json", self.task("task-one"))
        binding_path = self.root / "runtime" / "assurance" / "workers" / "binding.json"
        binding_path.parent.mkdir(parents=True)
        binding_path.write_text("{}\n", encoding="utf-8")
        with (
            mock.patch.object(adapter.runtime_assurance, "verify_activation", return_value={"status": "VERIFIED"}),
            mock.patch.object(adapter.runtime_assurance, "heartbeat_interval_seconds", return_value=60),
            mock.patch.object(
                adapter.runtime_assurance,
                "bind_worker",
                return_value={"worker_binding_path": str(binding_path)},
            ) as bind,
            mock.patch.object(adapter.runtime_assurance, "record_worker_heartbeat", return_value={}) as pulse,
            mock.patch.object(adapter.runtime_assurance, "complete_worker", return_value={}) as complete,
            mock.patch.object(adapter, "_process_identity", return_value="pid-start-token"),
            mock.patch.dict(os.environ, {"MVP0_CLAUDE_ARGV_LOG": str(self.log)}, clear=False),
        ):
            delivered = adapter.dispatch_task(
                adapter_dir=self.adapter_dir,
                task_contract=contract_path,
                unattended=True,
                runtime_store=self.root / "runtime",
                scheduler=object(),
            )
        self.assertEqual(delivered["outcome"], "COMPLETED")
        self.assertEqual(bind.call_count, 1)
        self.assertGreaterEqual(pulse.call_count, 1)
        self.assertEqual(complete.call_count, 1)
        self.assertEqual(pulse.call_args_list[0].kwargs["sequence"], 1)
        self.assertEqual(pulse.call_args_list[0].kwargs["process_identity"], "pid-start-token")

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
