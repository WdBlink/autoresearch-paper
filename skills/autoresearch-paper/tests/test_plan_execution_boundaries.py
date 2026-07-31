from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest import mock


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "references" / "scripts" / "plan_execution_boundaries.py"
)
SPEC = importlib.util.spec_from_file_location(
    "plan_execution_boundaries", MODULE_PATH,
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
RUNTIME_PATH = MODULE_PATH.parent / "harness-runtime.py"


def load_runtime():
    spec = importlib.util.spec_from_file_location(
        "harness_runtime_deadline_test", RUNTIME_PATH,
    )
    runtime = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runtime)
    return runtime


class PlanExecutionBoundariesTests(unittest.TestCase):
    def test_conformance_closes_deadline_and_aggregate_frontier_edges(self) -> None:
        result = MODULE.run_conformance_suite()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["case_count"], 7)
        self.assertTrue(all(case["passed"] for case in result["cases"]))

    def test_deadline_rejects_at_the_exact_boundary(self) -> None:
        boundary = MODULE.make_plan_deadline(
            "2026-01-01T00:00:00Z", 60,
        )
        with self.assertRaisesRegex(
            MODULE.PlanExecutionBoundaryError, "deadline exhausted",
        ):
            MODULE.require_deadline_active(
                boundary, "2026-01-01T00:01:00Z",
            )

    def test_frontier_total_is_accepted_at_but_not_above_limit(self) -> None:
        ledger = {
            "reserved_calls": 1,
            "reserved_input_tokens": 10,
            "reserved_output_tokens": 5,
        }
        limits = {
            "max_calls": 2,
            "max_input_tokens": 20,
            "max_output_tokens": 10,
        }
        self.assertEqual(
            MODULE.next_frontier_totals(
                ledger,
                {"calls": 1, "input_tokens": 10, "output_tokens": 5},
                limits,
            )["reserved_calls"],
            2,
        )
        with self.assertRaisesRegex(
            MODULE.PlanExecutionBoundaryError, "calls capacity exhausted",
        ):
            MODULE.next_frontier_totals(
                ledger,
                {"calls": 2, "input_tokens": 10, "output_tokens": 5},
                limits,
            )

    def test_live_deadline_guard_persists_pause_before_other_mutation(self) -> None:
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td).resolve()
            activation_root = (
                plan / "state" / "codex_host_entry" / "v1"
            )
            activation_root.mkdir(parents=True)
            (activation_root / "activation-receipt.json").write_text("{}")
            (plan / "resource_manifest.json").write_text(json.dumps({
                "plan_id": "plan_deadline",
            }))
            boundary_path = activation_root / "plan-boundary.json"
            boundary_path.write_text(json.dumps({
                "schema_version": 1,
                "plan_id": "plan_deadline",
                **MODULE.make_plan_deadline(
                    "2026-01-01T00:00:00Z", 60,
                ),
            }))
            boundary_path.chmod(0o444)
            state_path = plan / "state" / "staged-state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            with (
                mock.patch.object(
                    runtime, "validate_codex_host_activation",
                    return_value={"plan_boundary_path": str(boundary_path)},
                ),
                mock.patch.object(
                    runtime, "staged_is_active", return_value=True,
                ),
                mock.patch.object(
                    runtime, "staged_transaction_lock",
                    side_effect=lambda _plan: nullcontext(),
                ),
                mock.patch.object(
                    runtime, "staged_load_state",
                    return_value={"state": "DEVELOPING"},
                ),
                mock.patch.object(
                    runtime, "staged_state_path", return_value=state_path,
                ),
                mock.patch.object(
                    runtime, "_staged_ensure_audit_once_locked",
                ) as audit,
            ):
                with self.assertRaisesRegex(
                    runtime.ContractError, "deadline exhausted",
                ):
                    runtime.enforce_codex_host_plan_deadline(
                        plan, observed_at="2026-01-01T00:01:00Z",
                    )
            self.assertEqual(json.loads(state_path.read_text())["state"], "PAUSED")
            expiry = activation_root / "plan-deadline-expired.json"
            self.assertTrue(expiry.is_file())
            self.assertEqual(expiry.stat().st_mode & 0o777, 0o444)
            audit.assert_called_once()
            self.assertFalse(
                (plan / "state" / "frontier" / "budget.json").exists(),
            )


if __name__ == "__main__":
    unittest.main()
