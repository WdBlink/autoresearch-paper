#!/usr/bin/env python3
"""M4 tests for two-stage audited memory and proposal promotion."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "references" / "scripts" / "harness-runtime.py"


class GatedLearningPromotionTests(unittest.TestCase):
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

    @staticmethod
    def canonical_sha(value: object) -> str:
        return hashlib.sha256(json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode()).hexdigest()

    def plan(self, root: Path) -> tuple[Path, Path]:
        plan = root / "plan"
        (plan / "state").mkdir(parents=True)
        (plan / "control").mkdir()
        (plan / "resource_manifest.json").write_text(json.dumps({
            "schema_version": 1,
            "plan_id": "plan_learning",
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
        }))
        key = root / "human.key"
        key.write_bytes(b"l" * 32)
        key.chmod(0o600)
        return plan, key

    def auditor(self, plan: Path) -> Path:
        path = plan / "independent-auditor.json"
        path.write_text('{"auditor":"external-heldout-review"}\n')
        path.chmod(0o444)
        return path

    def gate_files(
        self,
        plan: Path,
        *,
        stem: str,
        subject: Path,
        subject_kind: str,
        auditor: Path,
        diagnosis: Path | None,
        pass_gate: bool = True,
        audit_pass: bool = True,
    ) -> tuple[Path, Path, Path]:
        subject_sha = self.sha(subject)
        replay = plan / f"{stem}-replay.json"
        first = "a" * 64
        replay.write_text(json.dumps({
            "schema_version": 1,
            "subject_sha256": subject_sha,
            "first_result_sha256": first,
            "second_result_sha256": first if pass_gate else "b" * 64,
            "status": "PASS",
        }))
        validation = plan / f"{stem}-validation.json"
        validation.write_text(json.dumps({
            "schema_version": 1,
            "subject_sha256": subject_sha,
            "kind": "held_out",
            "status": "PASS",
            "failed_cases": 0,
            "total_cases": 5,
        }))
        audit = plan / f"{stem}-audit.json"
        audit.write_text(json.dumps({
            "schema_version": 1,
            "audit_id": f"audit-{stem}",
            "subject_kind": subject_kind,
            "subject_sha256": subject_sha,
            "diagnosis_sha256": self.sha(diagnosis) if diagnosis else None,
            "auditor_identity_sha256": self.sha(auditor),
            "independent": True,
            "status": "PASS" if audit_pass else "FAIL",
            "findings": [] if audit_pass else ["scope mismatch"],
        }))
        return replay, validation, audit

    def memory(
        self,
        plan: Path,
        auditor: Path,
        *,
        episode_id: str,
        classification: str,
        audit_pass: bool = True,
    ) -> dict[str, object]:
        evidence_path = plan / f"{episode_id}-evidence.json"
        evidence_path.write_text('{"observed":"bounded episode"}\n')
        evidence = [{
            "path": str(evidence_path.resolve()),
            "sha256": self.sha(evidence_path),
            "purpose": "episode evidence",
        }]
        episode = plan / f"{episode_id}.json"
        episode.write_text(json.dumps({
            "schema_version": 1,
            "episode_id": episode_id,
            "plan_id": "plan_learning",
            "outcome": "failure",
            "evidence": evidence,
        }))
        diagnosis = plan / f"{episode_id}-diagnosis.json"
        diagnosis.write_text(json.dumps({
            "schema_version": 1,
            "episode_id": episode_id,
            "classification": classification,
            "rationale": "The held-out failure localizes the cause.",
            "evidence_manifest_sha256": self.canonical_sha(evidence),
        }))
        replay, validation, audit = self.gate_files(
            plan,
            stem=episode_id,
            subject=episode,
            subject_kind="episode",
            auditor=auditor,
            diagnosis=diagnosis,
            audit_pass=audit_pass,
        )
        return json.loads(self.call(
            "promote-episode-memory",
            "--plan-dir", str(plan),
            "--episode-manifest", str(episode),
            "--diagnosis", str(diagnosis),
            "--replay", str(replay),
            "--validation", str(validation),
            "--audit", str(audit),
            "--auditor-identity", str(auditor),
        ).stdout)

    def proposal_args(
        self,
        plan: Path,
        auditor: Path,
        memory: dict[str, object],
        proposal: Path,
        *,
        stem: str,
        target_kind: str,
        pass_gate: bool = True,
        authorization: Path | None = None,
    ) -> list[str]:
        replay, validation, audit = self.gate_files(
            plan,
            stem=stem,
            subject=proposal,
            subject_kind="proposal",
            auditor=auditor,
            diagnosis=None,
            pass_gate=pass_gate,
        )
        args = [
            "promote-learning-proposal",
            "--plan-dir", str(plan),
            "--memory-receipt", str(memory["memory_receipt"]),
            "--proposal", str(proposal),
            "--target-kind", target_kind,
            "--replay", str(replay),
            "--validation", str(validation),
            "--audit", str(audit),
            "--auditor-identity", str(auditor),
        ]
        if authorization:
            args += ["--authorization", str(authorization)]
        return args

    def test_two_stage_promotion_rejects_lapse_and_rejected_novelty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan, _ = self.plan(Path(td))
            auditor = self.auditor(plan)
            memory = self.memory(
                plan, auditor,
                episode_id="episode-skill-defect",
                classification="skill_defect",
            )
            self.assertEqual(memory["status"], "AUDITED")
            self.assertTrue(memory["proposal_eligible"])
            proposal = plan / "skill-change.patch"
            proposal.write_text("tighten the task contract\n")
            approved = json.loads(self.call(*self.proposal_args(
                plan, auditor, memory, proposal,
                stem="skill-proposal", target_kind="skill",
            )).stdout)
            self.assertEqual(approved["status"], "APPROVED")
            self.assertTrue(approved["proposal_only"])
            self.assertFalse(approved["application_authority"])
            self.assertEqual(proposal.read_text(), "tighten the task contract\n")
            again = json.loads(self.call(*self.proposal_args(
                plan, auditor, memory, proposal,
                stem="skill-proposal", target_kind="skill",
            )).stdout)
            self.assertTrue(again["idempotent"])

            lapse = self.memory(
                plan, auditor,
                episode_id="episode-execution-lapse",
                classification="execution_lapse",
            )
            self.assertEqual(lapse["status"], "AUDITED")
            self.assertFalse(lapse["proposal_eligible"])
            lapse_proposal = plan / "lapse-skill-change.patch"
            lapse_proposal.write_text("incorrectly blame the skill\n")
            rejected_lapse = json.loads(self.call(*self.proposal_args(
                plan, auditor, lapse, lapse_proposal,
                stem="lapse-proposal", target_kind="skill",
            )).stdout)
            self.assertEqual(rejected_lapse["status"], "REJECTED")
            self.assertIn(
                "diagnosed_as_execution_lapse",
                rejected_lapse["rejection_reasons"],
            )

            rejected_proposal = plan / "rejected-change.patch"
            rejected_proposal.write_text("unreproducible change\n")
            rejected_args = self.proposal_args(
                plan, auditor, memory, rejected_proposal,
                stem="rejected-proposal", target_kind="policy",
                pass_gate=False,
            )
            rejected = json.loads(self.call(*rejected_args).stdout)
            self.assertEqual(rejected["status"], "REJECTED")
            self.assertIn("replay_failed", rejected["rejection_reasons"])
            duplicate_with_new_review = self.call(*self.proposal_args(
                plan, auditor, memory, rejected_proposal,
                stem="rejected-proposal-new", target_kind="policy",
            ), check=False)
            self.assertEqual(duplicate_with_new_review.returncode, 2)
            self.assertIn("cannot reenter as novelty", duplicate_with_new_review.stderr)

            rejected_memory = self.memory(
                plan, auditor,
                episode_id="episode-rejected-audit",
                classification="skill_defect",
                audit_pass=False,
            )
            self.assertEqual(rejected_memory["status"], "REJECTED")
            self.assertIn(
                "independent_audit_failed", rejected_memory["reasons"],
            )

    def test_evaluator_proposal_requires_hash_bound_human_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, key = self.plan(root)
            auditor = self.auditor(plan)
            memory = self.memory(
                plan, auditor,
                episode_id="episode-evaluator-defect",
                classification="skill_defect",
            )
            proposal = plan / "evaluator-change.json"
            proposal.write_text('{"change":"raise-heldout-coverage"}\n')
            base_args = self.proposal_args(
                plan, auditor, memory, proposal,
                stem="evaluator-proposal", target_kind="evaluator",
            )
            blocked = self.call(*base_args, check=False)
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("authenticated human authorization", blocked.stderr)
            pending = json.loads(self.call(
                "create-human-action",
                "--plan-dir", str(plan),
                "--plan-id", "plan_learning",
                "--action", "authorize_evaluator_change",
                "--key-file", str(key),
                "--expires-in", "300",
                "--record-id", "har_evaluator_learning",
                "--reason", "Owner approves proposal-only evaluator review.",
                "--learning-proposal", str(proposal),
            ).stdout)
            applied = json.loads(self.call(
                "apply-human-action",
                "--plan-dir", str(plan),
                "--record", pending["record_path"],
                "--key-file", str(key),
                "--expected-action", "authorize_evaluator_change",
            ).stdout)
            receipt = Path(applied["receipt"]["receipt_path"])
            approved = json.loads(self.call(
                *base_args, "--authorization", str(receipt),
            ).stdout)
            self.assertEqual(approved["status"], "APPROVED")
            self.assertEqual(
                approved["human_authorization_record_id"],
                "har_evaluator_learning",
            )
            proposal.write_text('{"change":"silently-different"}\n')
            drift = self.call(
                *base_args, "--authorization", str(receipt), check=False,
            )
            self.assertEqual(drift.returncode, 2)


if __name__ == "__main__":
    unittest.main()
