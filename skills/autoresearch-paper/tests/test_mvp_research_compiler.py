#!/usr/bin/env python3
"""Contracts for the isolated MVP-0 Research Compiler."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from mvp import research_compiler as compiler  # noqa: E402


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class ResearchCompilerContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "paper"
        self.code = self.root / "code"
        self.workspace.mkdir()
        (self.code / "train").mkdir(parents=True)
        (self.code / "eval").mkdir()
        (self.code / "train" / "baseline.py").write_text("print('train')\n", encoding="utf-8")
        self.brief = self.root / "brief.md"
        self.brief.write_text("Test brief for privileged-to-perceptual fixed-wing visual guidance.\n", encoding="utf-8")
        self.store = self.root / "store"
        self.ir = self.valid_ir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def valid_ir(self) -> dict[str, object]:
        evaluator_path = self.code / "eval" / "unified_evaluator.py"
        return {
            "schema_version": "research-ir/v1",
            "ir_id": "fixed-wing-visual-guidance",
            "version": 1,
            "parent_ir_sha256": None,
            "source": {
                "source_task_id": "019fb6a0-a1cc-7422-ae35-8e9625de1c13",
                "source_summary": "Compile privileged-to-perceptual fixed-wing visual guidance into a falsifiable contract.",
                "brief_artifact": {
                    "path": str(self.brief),
                    "sha256": hashlib.sha256(self.brief.read_bytes()).hexdigest(),
                },
                "workspace_root": str(self.workspace),
                "code_root": str(self.code),
            },
            "problem_statement": "Determine whether privileged critic inputs improve a deployable onboard-vision fixed-wing guidance policy under wind, occlusion, and obstacles.",
            "central_claim": {
                "statement": "The asymmetric recurrent policy improves safe task success over the state-leaking PPO baseline under a paired degraded-perception evaluation.",
                "baseline_id": "state-leaking-ppo",
                "primary_metric_id": "safe-success-delta",
                "evaluation_scope": "Paired truth, degraded-truth, and detector rollouts under identical seeds and environment parameters.",
            },
            "falsification_conditions": [
                {
                    "id": "no-safe-success-gain",
                    "metric_id": "safe-success-delta",
                    "aggregation": "ci_lower",
                    "operator": "<=",
                    "value": 0.0,
                    "decision": "REJECT_CLAIM",
                },
                {
                    "id": "collision-regression",
                    "metric_id": "collision-rate-delta",
                    "aggregation": "ci_upper",
                    "operator": ">",
                    "value": 0.02,
                    "decision": "REJECT_CLAIM",
                },
            ],
            "related_work_gap": {
                "statement": "Existing components do not yet isolate privileged training from perception degradation in a fair fixed-wing closed-loop comparison.",
                "evidence_refs": [
                    {
                        "source_id": "baseline-source",
                        "locator": str(self.code / "train" / "baseline.py"),
                        "supports": "The baseline implementation exists but no frozen fair evaluator exists.",
                        "sha256": hashlib.sha256((self.code / "train" / "baseline.py").read_bytes()).hexdigest(),
                    }
                ],
            },
            "baseline_contract": {
                "baseline_id": "state-leaking-ppo",
                "status": "PLANNED",
                "description": "Current PPO Actor observes privileged target-relative state and is retrained under the frozen seed manifest.",
                "source_artifacts": [{
                    "path": str(self.code / "train" / "baseline.py"),
                    "sha256": hashlib.sha256((self.code / "train" / "baseline.py").read_bytes()).hexdigest(),
                }],
                "implementation_artifact": str(self.code / "train" / "research" / "baseline.py"),
                "implementation_sha256": None,
                "training_argv": ["python3", "train/baseline.py", "--seed-manifest", "artifacts/seeds.json"],
                "comparison_scope": ["same dynamics", "same reward", "same training steps", "same evaluation seeds"],
            },
            "metric_contract": {
                "primary_metric": {
                    "metric_id": "safe-success-delta",
                    "name": "paired safe task success delta",
                    "direction": "maximize",
                    "unit": "proportion",
                    "acceptance": {
                        "aggregation": "ci_lower",
                        "operator": ">=",
                        "value": 0.05,
                        "confidence_level": 0.95,
                        "minimum_seeds": 5,
                    },
                },
                "guardrails": [
                    {
                        "metric_id": "collision-rate-delta",
                        "name": "paired collision rate delta",
                        "direction": "minimize",
                        "unit": "proportion",
                        "acceptance": {
                            "aggregation": "ci_upper",
                            "operator": "<=",
                            "value": 0.02,
                            "confidence_level": 0.95,
                            "minimum_seeds": 5,
                        },
                    }
                ],
            },
            "evaluator_spec": {
                "status": "PLANNED",
                "working_directory": str(self.code),
                "command_argv": ["python3", "eval/unified_evaluator.py", "--manifest", "artifacts/eval-manifest.json", "--output", "artifacts/evaluator-result.json"],
                "implementation_artifact": str(evaluator_path),
                "implementation_sha256": None,
                "input_contract": "One immutable manifest binds policy artifacts, environment config, perception modes, and paired seeds.",
                "output_contract": "Strict JSON includes raw per-seed episode outcomes, aggregate metrics, confidence intervals, and artifact hashes.",
                "metric_bindings": [
                    {"metric_id": "safe-success-delta", "json_path": "$.comparison.safe_success.delta"},
                    {"metric_id": "collision-rate-delta", "json_path": "$.comparison.collision_rate.delta"},
                ],
            },
            "allowed_search_space": [
                {
                    "id": "evaluator-implementation",
                    "description": "Create the unified evaluator and deterministic conformance tests.",
                    "paths": ["eval/unified_evaluator.py", "eval/tests/**"],
                    "operations": ["CREATE", "MODIFY"],
                },
                {
                    "id": "privileged-visual-method",
                    "description": "Implement asymmetric critic and recurrent vision policy without changing evaluator or environment fairness.",
                    "paths": ["train/**", "envs/wrappers/**", "configs/research/**"],
                    "operations": ["CREATE", "MODIFY"],
                },
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
                    "id": "exp-evaluator",
                    "stage": "EVALUATOR_BUILD",
                    "hypothesis": "One shared evaluator can hold dynamics, rewards, seeds, and perception perturbations constant across policies.",
                    "intervention": "Implement manifest-driven paired evaluation and regression fixtures before method development.",
                    "controls": ["legacy truth evaluator", "legacy detector evaluator"],
                    "expected_observation": "Conformance fixtures show no non-perception environment differences across evaluator modes.",
                    "falsification_condition_ids": ["no-safe-success-gain", "collision-regression"],
                    "search_space_ids": ["evaluator-implementation"],
                    "depends_on": [],
                    "command_argv": ["python3", "-m", "unittest", "discover", "-s", "eval/tests"],
                    "expected_artifacts": ["eval/unified_evaluator.py", "artifacts/evaluator-conformance.json"],
                },
                {
                    "id": "exp-baseline",
                    "stage": "BASELINE",
                    "hypothesis": "The frozen state-leaking PPO can be reproduced under the unified evaluator with stable paired-seed variance.",
                    "intervention": "Retrain the baseline with the frozen seed manifest and run all perception conditions without changing its policy inputs.",
                    "controls": ["identical training budget", "identical evaluation manifest"],
                    "expected_observation": "Raw per-seed baseline metrics and variance estimates are complete enough for paired comparison.",
                    "falsification_condition_ids": ["no-safe-success-gain", "collision-regression"],
                    "search_space_ids": ["privileged-visual-method"],
                    "depends_on": ["exp-evaluator"],
                    "command_argv": ["python3", "train/baseline.py", "--seed-manifest", "artifacts/seeds.json"],
                    "expected_artifacts": ["artifacts/baseline-models.json", "artifacts/baseline-evaluation.json"],
                },
                {
                    "id": "exp-asymmetric",
                    "stage": "METHOD",
                    "hypothesis": "Privileged critic inputs plus recurrent onboard vision improve safe task success without a collision-rate regression.",
                    "intervention": "Remove target truth from Actor inputs, add privileged Critic inputs, and encode visual history recurrently.",
                    "controls": ["same PPO family", "same training steps", "same evaluator manifest"],
                    "expected_observation": "The paired confidence interval satisfies the primary threshold and every guardrail.",
                    "falsification_condition_ids": ["no-safe-success-gain", "collision-regression"],
                    "search_space_ids": ["privileged-visual-method"],
                    "depends_on": ["exp-baseline"],
                    "command_argv": ["python3", "train/train_asymmetric_visual.py", "--seed-manifest", "artifacts/seeds.json"],
                    "expected_artifacts": ["artifacts/candidate-models.json", "artifacts/candidate-evaluation.json"],
                },
            ],
            "budget": {
                "max_experiments": 8,
                "max_failed_experiments": 4,
                "max_wall_clock_seconds": 86400,
            },
            "stop_rules": [
                {
                    "id": "stop-claim-rejected",
                    "condition": "All frozen method variants meet any claim falsification condition after the seed floor.",
                    "action": "STOP",
                    "evidence_required": ["raw per-seed evaluator JSON", "paired confidence intervals"],
                },
                {
                    "id": "recompile-search-space",
                    "condition": "Evidence motivates changing any protected field or expanding paths outside the allowed search space.",
                    "action": "RECOMPILE",
                    "evidence_required": ["experiment receipts", "failed direction summary"],
                },
            ],
        }

    def publish_proposal(self) -> dict[str, str]:
        ir_path = write_json(self.root / "ir.json", self.ir)
        return compiler.propose(
            ir_path=ir_path,
            store=self.store,
            author="codex/compiler",
            recorded_at="2026-08-01T09:00:00Z",
        )

    def publish_critique(self, proposal: dict[str, str]) -> dict[str, str]:
        critique_input = {
            "summary": "The proposal is structurally sound but must make the detector condition part of the frozen evaluation scope.",
            "verdict": "REVISE",
            "findings": [
                {
                    "finding_id": "bind-detector-scope",
                    "severity": "major",
                    "path": "$.central_claim.evaluation_scope",
                    "message": "The claim does not explicitly bind the real detector condition.",
                    "required_change": "Name the detector condition in the central claim scope.",
                }
            ],
        }
        return compiler.critique(
            proposal_path=Path(proposal["proposal_path"]),
            critique_path=write_json(self.root / "critique.json", critique_input),
            store=self.store,
            reviewer="codex/critic",
            recorded_at="2026-08-01T09:10:00Z",
        )

    def test_valid_ir_passes_schema_semantics_and_path_checks(self) -> None:
        self.assertEqual(compiler.validate_research_ir(self.ir, check_paths=True), [])

    def test_extra_property_is_rejected_by_schema(self) -> None:
        self.ir["watchdog"] = {"interval": 60}
        issues = compiler.validate_research_ir(self.ir)
        self.assertIn("schema.additionalProperties", {issue.code for issue in issues})

    def test_planned_evaluator_gates_every_later_experiment(self) -> None:
        self.ir["experiment_plan"][2]["depends_on"] = []
        issues = compiler.validate_research_ir(self.ir)
        self.assertIn("semantic.evaluator_gate", {issue.code for issue in issues})

    def test_metric_direction_and_evaluator_bindings_are_checked(self) -> None:
        self.ir["metric_contract"]["primary_metric"]["acceptance"]["operator"] = "<="
        self.ir["evaluator_spec"]["metric_bindings"].pop()
        codes = {issue.code for issue in compiler.validate_research_ir(self.ir)}
        self.assertIn("semantic.metric_direction", codes)
        self.assertIn("semantic.binding_complete", codes)

    def test_every_metric_requires_an_opposing_falsification_predicate(self) -> None:
        self.ir["falsification_conditions"] = self.ir["falsification_conditions"][:1]
        self.ir["falsification_conditions"][0]["operator"] = ">="
        codes = {issue.code for issue in compiler.validate_research_ir(self.ir)}
        self.assertIn("semantic.falsification_direction", codes)
        self.assertIn("semantic.falsification_complete", codes)

    def test_dependency_cycle_is_rejected(self) -> None:
        self.ir["experiment_plan"][0]["depends_on"] = ["exp-asymmetric"]
        codes = {issue.code for issue in compiler.validate_research_ir(self.ir)}
        self.assertIn("semantic.dependency_cycle", codes)

    def test_method_experiment_must_depend_on_a_baseline(self) -> None:
        self.ir["experiment_plan"][2]["depends_on"] = ["exp-evaluator"]
        codes = {issue.code for issue in compiler.validate_research_ir(self.ir)}
        self.assertIn("semantic.baseline_gate", codes)

    def test_worker_paths_cannot_escape_code_root(self) -> None:
        self.ir["allowed_search_space"][0]["paths"] = ["../outside/**"]
        self.ir["experiment_plan"][0]["expected_artifacts"] = ["/tmp/result.json"]
        codes = {issue.code for issue in compiler.validate_research_ir(self.ir)}
        self.assertIn("semantic.search_space_path", codes)
        self.assertIn("semantic.expected_artifact_path", codes)

    def test_live_path_validation_detects_bound_input_drift(self) -> None:
        (self.code / "train" / "baseline.py").write_text("print('changed')\n", encoding="utf-8")
        self.brief.write_text("Changed source brief.\n", encoding="utf-8")
        codes = {issue.code for issue in compiler.validate_research_ir(self.ir, check_paths=True)}
        self.assertIn("semantic.baseline_hash", codes)
        self.assertIn("semantic.source_brief_hash", codes)

    def test_baseline_readiness_cannot_claim_unbound_bytes(self) -> None:
        self.ir["baseline_contract"]["status"] = "READY"
        codes = {issue.code for issue in compiler.validate_research_ir(self.ir)}
        self.assertIn("semantic.baseline_ready_hash", codes)

        self.ir["baseline_contract"]["status"] = "PLANNED"
        self.ir["baseline_contract"]["implementation_sha256"] = "0" * 64
        codes = {issue.code for issue in compiler.validate_research_ir(self.ir)}
        self.assertIn("semantic.baseline_planned_hash", codes)

    def test_full_proposal_critique_revision_freeze_lineage(self) -> None:
        proposal = self.publish_proposal()
        critique = self.publish_critique(proposal)
        revision_input = {
            "changes": [{
                "op": "replace",
                "path": "/central_claim/evaluation_scope",
                "value": "Paired truth, degraded-truth, and FastSAM detector rollouts under identical seeds and environment parameters.",
            }],
            "summary": "Bound the detector condition explicitly while preserving the research identity and all protected contracts.",
            "addressed_finding_ids": ["bind-detector-scope"],
        }
        revision = compiler.revise(
            proposal_path=Path(proposal["proposal_path"]),
            critique_record_path=Path(critique["critique_path"]),
            revision_path=write_json(self.root / "revision.json", revision_input),
            store=self.store,
            author="codex/reviser",
            recorded_at="2026-08-01T09:20:00Z",
        )
        frozen = compiler.freeze(
            revision_path=Path(revision["revision_path"]),
            store=self.store,
            approved_by="owner/engineering-acceptance",
            approval_scope="ENGINEERING_ACCEPTANCE",
            approval_note="Approve only the P1 compiler acceptance fixture; this does not authorize research execution.",
            approved_at="2026-08-01T09:30:00Z",
        )
        verified = compiler.verify_freeze(
            receipt_path=Path(frozen["freeze_receipt_path"]),
            store=self.store,
        )

        self.assertEqual(verified["valid"], "true")
        self.assertEqual(frozen["approval_scope"], "ENGINEERING_ACCEPTANCE")
        self.assertEqual(Path(frozen["freeze_receipt_path"]).stem, frozen["freeze_receipt_sha256"])
        self.assertEqual(Path(frozen["research_ir_path"]).stem, frozen["research_ir_sha256"])
        self.assertEqual(Path(frozen["freeze_receipt_path"]).stat().st_mode & 0o222, 0)

    def test_revision_cannot_skip_major_finding(self) -> None:
        proposal = self.publish_proposal()
        critique = self.publish_critique(proposal)
        revision_input = {
            "changes": [{
                "op": "replace",
                "path": "/problem_statement",
                "value": self.ir["problem_statement"],
            }],
            "summary": "This revision deliberately fails to acknowledge the required major finding.",
            "addressed_finding_ids": [],
        }
        with self.assertRaisesRegex(compiler.CompilerError, "did not address required findings"):
            compiler.revise(
                proposal_path=Path(proposal["proposal_path"]),
                critique_record_path=Path(critique["critique_path"]),
                revision_path=write_json(self.root / "bad-revision.json", revision_input),
                store=self.store,
                author="codex/reviser",
            )

    def test_freeze_revalidates_a_manually_forged_revision_record(self) -> None:
        proposal = self.publish_proposal()
        critique = self.publish_critique(proposal)
        forged_revision = {
            "addressed_finding_ids": [],
            "author": "codex/reviser",
            "critique_sha256": critique["critique_sha256"],
            "proposal_sha256": proposal["proposal_sha256"],
            "record_kind": "research-ir-revision/v1",
            "recorded_at": "2026-08-01T09:20:00Z",
            "research_ir_sha256": proposal["research_ir_sha256"],
            "summary": "A manually published record must not bypass required critique findings.",
        }
        _, forged_path = compiler.publish_object(self.store, forged_revision)
        with self.assertRaisesRegex(compiler.CompilerError, "did not address required findings"):
            compiler.freeze(
                revision_path=forged_path,
                store=self.store,
                approved_by="owner/engineering-acceptance",
                approval_scope="ENGINEERING_ACCEPTANCE",
                approval_note="This approval must fail because the revision lineage was forged.",
            )

    def test_role_separation_is_enforced(self) -> None:
        proposal = self.publish_proposal()
        critique_input = {
            "summary": "This otherwise valid review improperly reuses the proposal author identity.",
            "verdict": "REVISE",
            "findings": [{
                "finding_id": "one-finding",
                "severity": "minor",
                "path": "$.problem_statement",
                "message": "Clarify one phrase.",
                "required_change": "Clarify the phrase.",
            }],
        }
        with self.assertRaisesRegex(compiler.CompilerError, "must differ"):
            compiler.critique(
                proposal_path=Path(proposal["proposal_path"]),
                critique_path=write_json(self.root / "same-author.json", critique_input),
                store=self.store,
                reviewer="codex/compiler",
            )

    def test_workflow_timestamps_must_advance_monotonically(self) -> None:
        proposal = self.publish_proposal()
        critique_input = {
            "summary": "The review is valid in content but deliberately predates the proposal record.",
            "verdict": "REVISE",
            "findings": [{
                "finding_id": "time-order",
                "severity": "minor",
                "path": "$.problem_statement",
                "message": "Clarify the temporal scope.",
                "required_change": "Clarify the temporal scope.",
            }],
        }
        with self.assertRaisesRegex(compiler.CompilerError, "timestamp precedes"):
            compiler.critique(
                proposal_path=Path(proposal["proposal_path"]),
                critique_path=write_json(self.root / "early-critique.json", critique_input),
                store=self.store,
                reviewer="codex/critic",
                recorded_at="2026-08-01T08:59:59Z",
            )

    def test_mvp_module_does_not_import_or_execute_legacy_harness(self) -> None:
        source = compiler.VALIDATOR_PATH.read_text(encoding="utf-8")
        self.assertNotIn("harness-runtime", source)
        self.assertNotIn("references.scripts", source)
        self.assertNotIn("subprocess", source)

    def test_committed_fixed_wing_acceptance_fixture_replays(self) -> None:
        fixture = SKILL_ROOT / "examples" / "mvp0" / "fixed-wing-visual-guidance"
        store = fixture / "acceptance-store"
        receipts = list((store / "receipts" / "sha256").glob("*.json"))
        self.assertEqual(len(receipts), 1)

        verified = compiler.verify_freeze(receipt_path=receipts[0], store=store)
        receipt = compiler.load_json(receipts[0])

        self.assertEqual(verified["valid"], "true")
        self.assertEqual(verified["approval_scope"], "ENGINEERING_ACCEPTANCE")
        self.assertEqual(
            verified["research_ir_sha256"],
            "88096110be7a32b9f57d719442a50ebbba7e0358a7228a34a5e50c495850bcb5",
        )
        self.assertEqual(receipt["compiler_prompt_sha256"], compiler.sha256_file(compiler.COMPILER_PROMPT_PATH))
        self.assertEqual(receipt["research_ir_schema_sha256"], compiler.sha256_file(compiler.SCHEMA_PATH))
        self.assertEqual(receipt["semantic_validator_sha256"], compiler.sha256_file(compiler.VALIDATOR_PATH))


if __name__ == "__main__":
    unittest.main()
