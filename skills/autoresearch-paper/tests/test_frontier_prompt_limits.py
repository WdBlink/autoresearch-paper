#!/usr/bin/env python3
"""Frontier prompt byte-inlining and transport character-limit contracts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "references" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "autoresearch_paper_harness_runtime",
    SCRIPTS / "harness-runtime.py",
)
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


class FrontierPromptLimitTests(unittest.TestCase):
    def test_oversized_text_is_hash_bound_without_inline_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            small = root / "plan.md"
            large = root / "runtime.py"
            small.write_text("bounded plan evidence\n")
            large.write_text("UNIQUE_RUNTIME_LINE\n" * 20_000)
            request_path = root / "request.json"
            manifest = [
                {
                    "path": str(small),
                    "sha256": hashlib.sha256(small.read_bytes()).hexdigest(),
                    "purpose": "execution_plan",
                },
                {
                    "path": str(large),
                    "sha256": hashlib.sha256(large.read_bytes()).hexdigest(),
                    "purpose": "execution_dependency:harness_runtime",
                },
            ]
            request = {
                "schema_version": 1,
                "request_id": "far_prompt_limit",
                "plan_id": "plan_prompt_limit",
                "checkpoint": "CP-02",
                "checkpoint_subtype": None,
                "attempt": 1,
                "objective": "review bounded evidence",
                "decision_required": "approve_evaluator",
                "context_manifest": manifest,
                "constraints": [],
                "budget_reservation": {
                    "call": 1,
                    "max_input_tokens": 400_000,
                    "max_output_tokens": 10_000,
                },
                "created_at": "2026-07-30T00:00:00Z",
                "deadline_at": "2026-07-30T01:00:00Z",
            }
            request_path.write_text(json.dumps(request, indent=2) + "\n")

            prompt = RUNTIME.build_frontier_prompt(request_path, request)

            self.assertIn("bounded plan evidence", prompt)
            self.assertIn(
                "oversized evidence; hash and size only", prompt,
            )
            self.assertIn(str(large), prompt)
            self.assertIn(manifest[1]["sha256"], prompt)
            self.assertIn(f'"size_bytes": {large.stat().st_size}', prompt)
            self.assertNotIn("UNIQUE_RUNTIME_LINE", prompt)
            self.assertLessEqual(
                len(prompt), RUNTIME.CODEX_TURN_START_MAX_CHARS,
            )
            self.assertEqual(
                RUNTIME.FRONTIER_INLINE_TEXT_MAX_BYTES, 256 * 1024,
            )


if __name__ == "__main__":
    unittest.main()
