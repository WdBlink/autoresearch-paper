#!/usr/bin/env python3
"""Contracts for the P6 one-transition supervisory controller."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_ROOT))
sys.path.insert(0, str(TEST_ROOT))

from mvp import automation_registration as automation  # noqa: E402
from mvp import recompile_loop as p5  # noqa: E402
from mvp import supervisory_controller as supervisor  # noqa: E402
import test_mvp_recompile_loop as p5_tests  # noqa: E402
import test_mvp_worker_adapter as p2_tests  # noqa: E402


THREAD_ID = "019fc053-ab31-7333-b5da-85b03372ec24"


class SupervisoryControllerContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.p5 = p5_tests.RecompileLoopContracts(
            "test_recompile_request_and_candidate_enter_p1_human_review"
        )
        self.p5.setUp()
        analysis = self.p5.publish_analysis()
        self.request = self.p5.publish_request(analysis)
        candidate = copy.deepcopy(self.p5.p4.p2.ir)
        candidate["version"] = 2
        candidate["parent_ir_sha256"] = self.p5.p4.p2.ir_digest
        candidate["experiment_plan"][0]["id"] = "exp-one-recovery"
        candidate["experiment_plan"][0]["intervention"] += " Revalidate the failed scaffold."
        candidate["experiment_plan"][1]["depends_on"] = ["exp-one-recovery"]
        self.compiled = p5.compile_candidate(
            store_dir=self.p5.store_dir,
            request_sha256=str(self.request["request_sha256"]),
            candidate_ir=p2_tests.write_json(
                self.p5.p4.p2.root / "p6-candidate.json", candidate
            ),
            author="codex/recompile-compiler",
        )
        self.store = self.p5.p4.p2.root / "supervisor"
        self.automations = self.p5.p4.p2.root / "automations"
        supervisor.initialize_supervisor(
            run_dir=self.p5.p4.p2.root,
            target_thread_id=THREAD_ID,
            adapter_dir=self.p5.p4.p2.adapter_dir,
            ledger_dir=self.p5.p4.ledger_dir,
            gate_store=self.p5.p4.store_dir,
            p5_store=self.p5.store_dir,
            store_dir=self.store,
            automation_root=self.automations,
        )

    def tearDown(self) -> None:
        self.p5.tearDown()

    def review_input(self) -> dict[str, object]:
        base = json.loads(Path(self.compiled["compiler_proposal_path"]).read_text())[
            "recorded_at"
        ]
        return {
            "schema_version": "mvp0-engineering-review-input/v1",
            "reviewer": "codex/frontier-reviewer",
            "recorded_at": p5_tests.plus_seconds(base, 1),
            "critique": {
                "summary": "Independent review accepts the execution-plan-only successor.",
                "verdict": "ACCEPT",
                "findings": [],
            },
            "revision_author": "codex/recompile-revision",
            "revision_recorded_at": p5_tests.plus_seconds(base, 2),
            "revision_summary": "Confirm the accepted execution-only successor without modifying its bytes.",
            "approver": "codex/frontier-approver",
            "reviewed_at": p5_tests.plus_seconds(base, 3),
            "review_summary": "Independent strong review confirms only the authorized experiment plan changed.",
            "approved_at": p5_tests.plus_seconds(base, 4),
            "approval_note": "Approve the execution-only successor under its replayable delegated review.",
        }

    def test_init_derives_engineering_review_and_exact_thread_automation(self) -> None:
        inspected = supervisor.inspect_supervisor(store_dir=self.store)
        rendered = supervisor.render_automation(
            store_dir=self.store, created_at_ms=1_775_000_000_000
        )
        parsed = automation.parse_thread_automation(rendered["automation_toml"])

        self.assertEqual(inspected["phase"], "NEEDS_ENGINEERING_REVIEW")
        self.assertEqual(inspected["action"]["action"], "REVIEW_ENGINEERING_IR")
        self.assertEqual(inspected["action"]["changed_roots"], ["/experiment_plan"])
        self.assertEqual(parsed["kind"], "heartbeat")
        self.assertEqual(parsed["target_thread_id"], THREAD_ID)
        self.assertEqual(parsed["id"], inspected["controller_id"])
        self.assertIn(str(self.store.resolve()), parsed["prompt"])

    def test_one_review_tick_freezes_p5_and_stops_at_child_p2(self) -> None:
        result = supervisor.tick(
            store_dir=self.store,
            action_input=p2_tests.write_json(
                self.p5.p4.p2.root / "p6-review.json", self.review_input()
            ),
            recorded_at=self.review_input()["approved_at"],
        )
        inspected = supervisor.inspect_supervisor(store_dir=self.store)

        self.assertEqual(result["sequence"], 1)
        self.assertEqual(result["next_phase"], "NEEDS_CHILD_P2")
        self.assertEqual(inspected["phase"], "NEEDS_CHILD_P2")
        self.assertEqual(inspected["action"]["action"], "CREATE_CHILD_P2")
        self.assertEqual(p5.verify_store(store_dir=self.p5.store_dir)["stage"], "FROZEN")
        self.assertTrue(supervisor.verify_supervisor(store_dir=self.store)["verified"])

    def test_wrong_or_ambiguous_review_identity_fails_without_tick(self) -> None:
        value = self.review_input()
        value["reviewer"] = "codex/recompile-compiler"
        with self.assertRaisesRegex(supervisor.SupervisorError, "differ"):
            supervisor.tick(
                store_dir=self.store,
                action_input=p2_tests.write_json(
                    self.p5.p4.p2.root / "bad-review.json", value
                ),
            )
        self.assertEqual(supervisor.inspect_supervisor(store_dir=self.store)["sequence"], 0)

    def test_crash_after_prepared_tick_rebuilds_exact_state_projection(self) -> None:
        review_path = p2_tests.write_json(
            self.p5.p4.p2.root / "p6-crash-review.json", self.review_input()
        )
        with self.assertRaisesRegex(supervisor.SupervisorError, "simulated supervisor crash"):
            supervisor.tick(
                store_dir=self.store,
                action_input=review_path,
                recorded_at=self.review_input()["approved_at"],
                simulate_crash_after="PREPARED",
            )
        recovered = supervisor.tick(store_dir=self.store)
        self.assertTrue(recovered["recovered_commit"])
        self.assertEqual(recovered["sequence"], 1)
        self.assertEqual(recovered["next_phase"], "NEEDS_CHILD_P2")
        self.assertTrue(supervisor.verify_supervisor(store_dir=self.store)["verified"])


if __name__ == "__main__":
    unittest.main()
