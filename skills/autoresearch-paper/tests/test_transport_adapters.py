#!/usr/bin/env python3
"""Unit tests for behavior-preserving transport seams."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "references" / "scripts" / "harness-runtime.py"
SPEC = importlib.util.spec_from_file_location("autoresearch_harness_runtime", RUNTIME_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load harness runtime")
RUNTIME = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNTIME
SPEC.loader.exec_module(RUNTIME)


class TransportAdapterTests(unittest.TestCase):
    def test_claude_worker_adapter_preserves_cli_contract(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["claude"], returncode=0, stdout='{"ok":true}', stderr="",
        )
        with mock.patch.object(RUNTIME.subprocess, "run", return_value=completed) as run:
            outcome = RUNTIME.ClaudeCliWorkerTransport("/opt/claude").dispatch(
                model="MiniMax-M3",
                output_schema={"type": "object"},
                max_budget_usd=0.25,
                allowed_tools=["Read", "Grep"],
                prompt="bounded",
                cwd=ROOT,
                timeout=90,
            )

        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["/opt/claude", "-p", "--model", "MiniMax-M3"])
        self.assertIn("--no-session-persistence", command)
        self.assertEqual(run.call_args.kwargs["input"], "bounded")
        self.assertEqual(run.call_args.kwargs["timeout"], 90)
        self.assertEqual(outcome.adapter_id, "claude-cli")
        self.assertEqual(outcome.exit_code, 0)

    def test_worker_adapter_does_not_reclassify_missing_executable(self) -> None:
        with mock.patch.object(
            RUNTIME.subprocess, "run", side_effect=FileNotFoundError("missing"),
        ):
            with self.assertRaises(FileNotFoundError):
                RUNTIME.ClaudeCliWorkerTransport("/missing").dispatch(
                    model="MiniMax-M3",
                    output_schema={"type": "object"},
                    max_budget_usd=0.25,
                    allowed_tools=[],
                    prompt="bounded",
                    cwd=ROOT,
                    timeout=1,
                )

    def test_codex_frontier_adapter_preserves_cli_contract(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["codex"], returncode=7, stdout='{"event":"failed"}\n', stderr="no",
        )
        with tempfile.TemporaryDirectory() as temporary:
            raw_response = Path(temporary) / "response.raw.json"
            with mock.patch.object(RUNTIME.subprocess, "run", return_value=completed) as run:
                outcome = RUNTIME.CodexCliFrontierTransport("/opt/codex").send(
                    model="gpt-frontier",
                    reasoning_effort="xhigh",
                    response_schema=RUNTIME.RESPONSE_SCHEMA,
                    raw_response=raw_response,
                    prompt="checkpoint",
                    cwd=ROOT,
                    timeout=120,
                )

        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["/opt/codex", "exec", "-m", "gpt-frontier"])
        self.assertIn("model_reasoning_effort=xhigh", command)
        self.assertIn(str(raw_response), command)
        self.assertEqual(run.call_args.kwargs["input"], "checkpoint")
        self.assertEqual(outcome.adapter_id, "codex-cli")
        self.assertEqual(outcome.exit_code, 7)
        self.assertEqual(outcome.stderr, "no")

    def test_frontier_adapter_propagates_timeout_for_controller_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(
                RUNTIME.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(["codex"], 5),
            ):
                with self.assertRaises(subprocess.TimeoutExpired):
                    RUNTIME.CodexCliFrontierTransport("/opt/codex").send(
                        model="gpt-frontier",
                        reasoning_effort="high",
                        response_schema=RUNTIME.RESPONSE_SCHEMA,
                        raw_response=Path(temporary) / "response.raw.json",
                        prompt="checkpoint",
                        cwd=ROOT,
                        timeout=5,
                    )


if __name__ == "__main__":
    unittest.main()
