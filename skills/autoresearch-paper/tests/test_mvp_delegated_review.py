#!/usr/bin/env python3
"""Contracts for P6 delegated execution-only Research IR review."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from mvp import delegated_review as review  # noqa: E402


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(review.canonical_bytes(value))
    return path


class DelegatedEngineeringReviewContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.parent = {
            "schema_version": "research-ir/v1",
            "ir_id": "unit-ir",
            "version": 1,
            "parent_ir_sha256": None,
            "source": {"code_root": "/tmp/unit"},
            "problem_statement": "Frozen problem",
            "central_claim": {"statement": "Frozen claim"},
            "baseline_contract": {"baseline_id": "baseline"},
            "metric_contract": {"primary_metric": {"metric_id": "quality"}},
            "evaluator_spec": {
                "status": "PLANNED",
                "implementation_artifact": "/tmp/evaluator.py",
                "implementation_sha256": None,
                "command_argv": ["python3", "evaluate.py"],
            },
            "falsification_conditions": [{"id": "reject"}],
            "allowed_search_space": [{"id": "code"}],
            "forbidden_changes": ["central_claim"],
            "budget": {
                "max_experiments": 2,
                "max_failed_experiments": 1,
                "max_wall_clock_seconds": 3600,
            },
            "experiment_plan": [{
                "id": "failed-build",
                "stage": "EVALUATOR_BUILD",
                "hypothesis": "A bounded evaluator build can satisfy the frozen contract.",
                "falsification_condition_ids": ["reject"],
                "search_space_ids": ["code"],
                "command_argv": ["python3", "build.py"],
                "depends_on": [],
            }],
            "stop_rules": [{"id": "stop"}],
        }
        parent_digest = hashlib.sha256(review.canonical_bytes(self.parent)).hexdigest()
        self.child = copy.deepcopy(self.parent)
        self.child["version"] = 2
        self.child["parent_ir_sha256"] = parent_digest
        self.child["experiment_plan"][0]["id"] = "successor-build"
        self.parent_path = write_json(self.root / "parent.json", self.parent)
        self.child_path = write_json(self.root / "child.json", self.child)
        self.request_path = write_json(self.root / "request.json", {"requested_changes": [{"path": "/experiment_plan"}]})
        self.proposal_path = write_json(
            self.root / "proposal.json",
            {"changed_roots": ["/experiment_plan"], "child_ir_sha256": hashlib.sha256(self.child_path.read_bytes()).hexdigest()},
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def publish(self, *, child_path: Path | None = None) -> dict[str, str]:
        return review.publish_review(
            store_dir=self.root / "reviews",
            parent_ir_path=self.parent_path,
            child_ir_path=self.child_path if child_path is None else child_path,
            request_path=self.request_path,
            proposal_path=self.proposal_path,
            compiler_author="codex/recompile-compiler",
            reviewer="codex/frontier-reviewer",
            revision_author="codex/recompile-revision",
            approver="codex/frontier-approver",
            verdict="ACCEPT",
            summary="Independent strong review confirms an execution-only successor plan.",
            reviewed_at="2026-08-02T09:00:00Z",
        )

    def test_execution_only_delta_is_content_addressed_and_replayable(self) -> None:
        published = self.publish()
        receipt_path = Path(published["review_receipt_path"])
        self.assertEqual(receipt_path.stat().st_mode & 0o777, 0o444)
        self.assertEqual(hashlib.sha256(receipt_path.read_bytes()).hexdigest(), published["review_receipt_sha256"])
        verified = review.verify_review(receipt_path=receipt_path)
        self.assertEqual(verified["verdict"], "ACCEPT")
        self.assertEqual(verified["changed_roots"], ["/experiment_plan"])

    def test_scientific_root_change_is_rejected(self) -> None:
        changed = copy.deepcopy(self.child)
        changed["central_claim"]["statement"] = "Broadened claim"
        child_path = write_json(self.root / "scientific-change.json", changed)
        with self.assertRaisesRegex(review.DelegatedReviewError, "not delegated"):
            self.publish(child_path=child_path)

    def test_evaluator_semantics_cannot_hide_behind_evaluator_root(self) -> None:
        changed = copy.deepcopy(self.child)
        changed["evaluator_spec"]["command_argv"] = ["python3", "different.py"]
        child_path = write_json(self.root / "evaluator-change.json", changed)
        with self.assertRaisesRegex(review.DelegatedReviewError, "not delegated"):
            self.publish(child_path=child_path)

    def test_experiment_plan_cannot_change_hypothesis_or_command(self) -> None:
        changed = copy.deepcopy(self.child)
        changed["experiment_plan"][0]["hypothesis"] = "A different scientific hypothesis."
        child_path = write_json(self.root / "hypothesis-change.json", changed)
        with self.assertRaisesRegex(review.DelegatedReviewError, "frozen field"):
            self.publish(child_path=child_path)

    def test_budget_increase_is_bounded(self) -> None:
        changed = copy.deepcopy(self.child)
        changed["budget"]["max_experiments"] = 50
        child_path = write_json(self.root / "budget-change.json", changed)
        request = write_json(
            self.root / "budget-request.json",
            {"requested_changes": [{"path": "/budget"}, {"path": "/experiment_plan"}]},
        )
        proposal = write_json(
            self.root / "budget-proposal.json",
            {
                "changed_roots": ["/budget", "/experiment_plan"],
                "child_ir_sha256": hashlib.sha256(child_path.read_bytes()).hexdigest(),
            },
        )
        with self.assertRaisesRegex(review.DelegatedReviewError, "bounded increase"):
            review.publish_review(
                store_dir=self.root / "reviews",
                parent_ir_path=self.parent_path,
                child_ir_path=child_path,
                request_path=request,
                proposal_path=proposal,
                compiler_author="codex/recompile-compiler",
                reviewer="codex/frontier-reviewer",
                revision_author="codex/recompile-revision",
                approver="codex/frontier-approver",
                verdict="ACCEPT",
                summary="Independent strong review rejects an unbounded execution budget increase.",
                reviewed_at="2026-08-02T09:00:00Z",
            )

    def test_reviewer_and_approver_must_be_distinct_non_minimax_identities(self) -> None:
        with self.assertRaisesRegex(review.DelegatedReviewError, "distinct"):
            review.publish_review(
                store_dir=self.root / "reviews",
                parent_ir_path=self.parent_path,
                child_ir_path=self.child_path,
                request_path=self.request_path,
                proposal_path=self.proposal_path,
                compiler_author="codex/recompile-compiler",
                reviewer="codex/frontier-reviewer",
                revision_author="codex/recompile-revision",
                approver="codex/frontier-reviewer",
                verdict="ACCEPT",
                summary="Independent strong review confirms an execution-only successor plan.",
                reviewed_at="2026-08-02T09:00:00Z",
            )
        with self.assertRaisesRegex(review.DelegatedReviewError, "MiniMax"):
            review.publish_review(
                store_dir=self.root / "reviews",
                parent_ir_path=self.parent_path,
                child_ir_path=self.child_path,
                request_path=self.request_path,
                proposal_path=self.proposal_path,
                compiler_author="codex/recompile-compiler",
                reviewer="minimax/m3-reviewer",
                revision_author="codex/recompile-revision",
                approver="codex/frontier-approver",
                verdict="ACCEPT",
                summary="Independent strong review confirms an execution-only successor plan.",
                reviewed_at="2026-08-02T09:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
