#!/usr/bin/env python3
"""Validate autoresearch-paper research-first and lifecycle contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def contains(path: str, *needles: str) -> bool:
    text = read(path)
    return all(needle in text for needle in needles)


def main() -> int:
    errors: list[str] = []

    for path in [
        "references/research-state-contract.md",
        "references/lifecycle-contract.md",
        "references/scripts/plan-l0-guard.py",
        "references/scripts/research-state-guard.py",
        "references/scripts/cleanup-plan-resources.sh",
        "references/scripts/resolve-plan-dir.py",
        "references/scripts/register-plan-id.py",
        "references/scripts/harness-runtime.py",
        "references/scripts/run-claude-harness.py",
        "references/claude-code-runtime.md",
        "references/frontier-response.schema.json",
        "references/human-action.schema.json",
        "references/evaluator-verdict.schema.json",
        "references/metric-contract.schema.json",
        "references/declarative-evaluator.schema.json",
        "references/durable-plan.schema.json",
        "references/context-capsule.schema.json",
        "references/guardian-observation.schema.json",
        "references/evaluator-admission.schema.json",
        "references/figure-artifact.schema.json",
        "references/staged-research.schema.json",
        "references/role-visible-state.schema.json",
        "references/scientific-figure-pipeline.md",
        "references/scripts/validate-figure-artifacts.py",
        "references/learning-promotion-contract.md",
        "references/fault-soak-acceptance-contract.md",
        "references/canonical-conformance-workflow.json",
        "tests/test_runtime_contracts.py",
        "tests/test_claude_cutover_e2e.py",
        "tests/test_runtime_v2_security.py",
        "tests/test_durable_loop_runtime.py",
        "tests/test_evaluator_admission.py",
        "tests/test_production_transport.py",
        "tests/test_scientific_truth_and_failure_routing.py",
        "tests/test_gated_learning_promotion.py",
        "tests/test_fault_soak_acceptance.py",
        "tests/test_scientific_figure_pipeline.py",
        "tests/test_staged_research_governance.py",
    ]:
        require((ROOT / path).exists(), f"missing {path}", errors)

    require(
        contains("SKILL.md", "research_acceptance.md", "plan-l0-guard.py", "cleanup-plan-resources.sh", "resource_manifest.json"),
        "SKILL.md must document research gate, L0, cleanup, and resource manifest",
        errors,
    )
    require(
        contains("SKILL.md", "Target Runtime: Claude Code", "MiniMax M3", "CP-01", "CP-04", "harness-runtime.py"),
        "SKILL.md must expose the Claude Code target runtime and sparse frontier path",
        errors,
    )
    require(
        contains(
            "references/claude-code-runtime.md", "init-policy", "create-human-action",
            "freeze-evaluator", "record-failure", "dispatch-worker", "inspect-worker",
            "schedule-patrol", "remove-resource", "create-frontier-request",
            "assert-transition", "reconcile-frontier-request", "promote-worker-artifacts",
            "run-evaluator", "register-durable-trigger", "init-durable-plan",
            "apply-work-unit-result", "apply-guardian-proposal",
            "guardian-validate-lifecycle", "admit-evaluator",
            "check-autonomy-eligibility", "create-durable-frontier-request",
            "commit-durable-frontier-result", "commit-durable-worker-result",
            "check-scientific-acceptance", "check-research-integrity",
            "promote-episode-memory", "promote-learning-proposal",
            "authorize_evaluator_change",
            "start-acceptance-profile", "complete-acceptance-profile",
            "validate-acceptance-claim",
            "context-capsule", "applied", "advisory",
        ),
        "Claude runtime reference must document the complete target controller",
        errors,
    )
    require(
        contains("SKILL.md", "❌-11", "❌-12", "❌-13", "FM-20", "FM-21", "FM-22", "FM-23"),
        "SKILL.md must include new anti-patterns and failure modes",
        errors,
    )
    require(
        contains(
            "SKILL.md", "Scientific Figure Gate", "scientific-visualization",
            "scientific-schematics", "validate-figure-artifacts.py",
            "check-figure-gate", "--figure-gate-receipt", "required-figures.json",
            "❌-16", "FM-26",
        ),
        "SKILL.md must expose the executable figure/writing gate and proposal-only AI boundary",
        errors,
    )
    require(
        contains(
            "scripts/setup.sh",
            "70a0d595e54b8d92ca54f216d4315e0ab8c7d967",
            "has_pinned_skill_for_agent",
            "claude-code",
            "codex",
        ),
        "setup must require the audited scientific-visualization pin for both hosts",
        errors,
    )
    require(
        contains("references/plan-template-conference.md", "T0 evaluator-freeze", "T6.1 evaluate-candidate", "T6.2 research-decision", "T6.3 pivot-or-retry", "T6.4", "record-evaluator-verdict", "pivot-eligibility"),
        "conference template must include research-first gate",
        errors,
    )
    require(
        contains("references/plan-template-journal-q1.md", "T0 evaluator-freeze", "T6.1 evaluate-candidate", "T6.2 research-decision", "T6.3 pivot-or-retry", "T6.4"),
        "journal-q1 template must include research-first gate",
        errors,
    )
    require(
        contains("references/plan-template-arxiv.md", "T2.5", "T2.6", "authenticated", "check-writing-gate"),
        "arxiv template must explicitly handle negative-result waiver",
        errors,
    )
    require(
        contains("references/task-prompt-snippets.md", "T0-evaluator-freeze", "T6.1-evaluate-candidate", "T6.2-research-decision", "T6.3-pivot-or-retry", "T6.4-figure-build", "directions_tried.json", "research-state-guard.py"),
        "task snippet index must expose research loop snippets",
        errors,
    )
    require(
        contains("assets/task-prompt-snippets.md", "T0-evaluator-freeze", "T6.1-evaluate-candidate", "T6.2-research-decision", "T6.3-pivot-or-retry", "T6.4-figure-build", "validate-figure-artifacts.py", "check-figure-gate", "--figure-gate-receipt", "record-evaluator-verdict", "pivot-eligibility", "research-state-guard.py"),
        "task snippet asset must propagate research loop state to generated plans",
        errors,
    )
    require(
        contains("references/bootstrap-watchdog.sh", "--rescue", "resource_manifest.json", "research_acceptance.md", "plan-l0-guard.py", "cleanup-plan-resources.sh", "resolve-plan-dir.py", "register-plan-id.py"),
        "bootstrap must parse rescue, write manifest/state, and copy L0/cleanup scripts",
        errors,
    )
    require(
        contains("references/scripts/plan-rescue-daemon.py", "call_l0_guard", "cleanup-plan-resources.sh", "control", "status != \"paused\""),
        "rescue daemon must delegate non-paused plans to L0 and cleanup stop requests",
        errors,
    )
    require(
        contains("references/scripts/stop-plan.sh", "apply-human-action", "--record", "--key-file", "cleanup-plan-resources.sh"),
        "stop script must require authenticated authority and pass a receipt to cleanup",
        errors,
    )
    require(
        contains("references/scripts/resume-plan.sh", "apply-human-action", "--legacy-mavis", "plan-l0-guard.py"),
        "resume script must use target authority and isolate legacy repair",
        errors,
    )
    require(
        contains(
            "tests/test_runtime_v2_security.py", "test_frontier_semantic_failures",
            "test_concurrent_frontier_send_has_one_transport_claim",
            "test_worker_escape_malformed_output", "test_human_action_crash_rolls_forward",
            "test_aggregate_cleanup_is_disabled", "test_acceptance_dispute_consumer",
        ),
        "v2 runtime tests must cover authority recovery, checkpoint consumers, concurrency, and cleanup negatives",
        errors,
    )
    require(
        contains("tests/test_claude_cutover_e2e.py", "assertIsNone", "canonical-conformance-workflow.json", "workflow_kind", "terminal_artifacts", "simulate-crash-after-step"),
        "end-to-end test must prove the closed no-MAVIS conformance path",
        errors,
    )
    require(
        contains(
            "references/scripts/run-claude-harness.py", "claude-research-conformance-v1",
            "CANONICAL_TEMPLATE", "closed template", "PREPARED", "operation_id",
            "AWAITING_HUMAN_AUTHORIZATION", "terminal-manifest.json",
        ),
        "conformance runner must validate closed semantics, journal, pause, and finalize detached evidence",
        errors,
    )
    workflow = json.loads(read("references/canonical-conformance-workflow.json"))
    require(workflow.get("workflow_kind") == "claude-research-conformance-v1", "conformance workflow kind mismatch", errors)
    require(len(workflow.get("steps", [])) == 41, "canonical workflow must retain the complete 41-step sequence", errors)
    require(
        {"figure_requirements", "figure_inventory"}.issubset(
            set(workflow.get("required_inputs", []))
        ),
        "canonical workflow must require the frozen figure set and completed inventory",
        errors,
    )
    require(
        contains(
            "references/canonical-conformance-workflow.json",
            "${input.figure_requirements}::figure_requirements",
            "\"requirements\":\"${input.figure_requirements}\"",
        ),
        "CP-01 and the figure gate must bind the same frozen requirements",
        errors,
    )
    require("stop_record" not in workflow.get("required_inputs", []), "stop authority must not be a startup input", errors)
    require("cleanup_record" not in workflow.get("required_inputs", []), "cleanup authority must not be a startup input", errors)
    require(any(step.get("id") == "writer_dispatch" for step in workflow.get("steps", [])), "canonical workflow must dispatch a post-gate writer", errors)
    require(workflow.get("steps", [])[-1].get("command") == "await-human-actions", "canonical workflow must end at the JIT human boundary", errors)
    require(
        {item.get("type") for item in workflow.get("terminal_artifacts", [])} == {
            "workflow_journal", "evaluator_contract", "evaluator_verdict", "structural_pivot",
            "figure_gate", "writing_gate_audit", "paper_deliverable", "cleanup_receipt",
        },
        "canonical workflow terminal artifacts are incomplete", errors,
    )
    runtime_tests = read("tests/test_runtime_contracts.py")
    require("legacy_test_" not in runtime_tests, "legacy runtime regressions must remain discoverable", errors)
    for test_name in (
        "test_claude_worker_dispatch_is_pinned_and_mavis_free",
        "test_frontier_bridge_is_durable_bounded_and_idempotent",
        "test_frontier_preflight_and_https_route_precede_budget",
        "test_cp01_strong_profile_overrides_minimax_generic_frontier",
        "test_cp04_acceptance_dispute_dependent_transition",
        "test_frontier_bridge_does_not_redeliver_uncertain_request",
        "test_frontier_bridge_blocks_oversized_context_before_budget",
        "test_frontier_expiration_malformed_response_and_budget_exhaustion",
        "test_cleanup_complete_status", "test_research_writing_gate", "test_structural_pivot_guard",
        "test_resolve_plan_dir_and_stop_json_escaping",
        "test_typed_failures_runtime_operations_and_owned_cleanup",
    ):
        require(f"def {test_name}" in runtime_tests, f"missing restored runtime regression {test_name}", errors)
    security_tests = read("tests/test_runtime_v2_security.py")
    require(
        "def test_worker_dispatch_rechecks_strong_cp01_reviewer_identity"
        in security_tests,
        "missing strongest-model CP-01 reviewer identity regression",
        errors,
    )
    require(
        "def test_cp01_request_contract_prevents_legacy_policy_downgrade"
        in security_tests,
        "missing CP-01 immutable request downgrade regression",
        errors,
    )
    production_tests = read("tests/test_production_transport.py")
    for test_name in (
        "test_minimax_worker_is_capsule_bound_and_commits_exactly_once",
        "test_codex_frontier_is_capsule_derived_advisory_and_exact_once",
    ):
        require(f"def {test_name}" in production_tests, f"missing T007 regression {test_name}", errors)
    m3_tests = read("tests/test_scientific_truth_and_failure_routing.py")
    for test_name in (
        "test_scientific_acceptance_replays_machine_truth_and_current_admission",
        "test_integrity_drift_has_isolated_controller_owned_routes",
    ):
        require(f"def {test_name}" in m3_tests, f"missing M3 regression {test_name}", errors)
    learning_tests = read("tests/test_gated_learning_promotion.py")
    for test_name in (
        "test_two_stage_promotion_rejects_lapse_and_rejected_novelty",
        "test_evaluator_proposal_requires_hash_bound_human_authorization",
    ):
        require(f"def {test_name}" in learning_tests, f"missing M4 regression {test_name}", errors)
    acceptance_tests = read("tests/test_fault_soak_acceptance.py")
    require(
        "def test_seven_faults_multisession_soak_and_bounded_claim" in acceptance_tests,
        "missing T008 fault/soak acceptance regression", errors,
    )
    for scenario in (
        "process_death", "missed_tick", "duplicate_trigger", "state_corruption",
        "budget_exhaustion", "evaluator_drift", "multi_session_restart",
    ):
        require(scenario in acceptance_tests, f"missing T008 scenario {scenario}", errors)
    require('version: "0.16.1"' in read("SKILL.md"), "SKILL.md version must be 0.16.1", errors)
    repository_readme = ROOT.parents[1] / "README.md"
    if repository_readme.is_file():
        repository_readme_text = repository_readme.read_text()
        require(
            "Current version:** v0.16.1" in repository_readme_text,
            "README version must be 0.16.1",
            errors,
        )
        require(
            "Figure Gate | CP-01 freezes expected IDs" not in repository_readme_text
            and "authorized figure-production stage" in repository_readme_text,
            "README must describe v0.16 figure freeze at the authorized figure-production stage",
            errors,
        )
    require(
        all(token in read("references/scripts/harness-runtime.py") for token in (
            "create-human-action", "apply-human-action", "run-evaluator", "record-evaluator-verdict",
            "pivot-eligibility", "wait-worker", "cancel-worker", "run-patrol",
            "promote-worker-artifacts", "reconcile-frontier-request",
            "apply-frontier-response", "dependent-transition", "assert-transition",
            "top_level_plan_audit", "PLAN_AUDIT_MODEL",
            "PLAN_AUDIT_REASONING_EFFORT", "reviewer_profile",
            "top-level-plan-review-v1", "review_contract",
        )),
        "harness runtime is missing target commands",
        errors,
    )
    require(
        all(token in read("references/scripts/harness-runtime.py") for token in (
            "declarative-evaluator-v1", "read_finite_number", "require_finite_number",
            "pivot_epoch", "consumed_event_ids", "writing_gate_receipt",
            "operation_effect_path", "reconcile_ambiguous_prepared_operation",
            "claim_tick_locked", "commit_durable_revision", "validate_context_capsule",
            "command_create_durable_request", "command_commit_durable_worker_result",
            "command_commit_durable_frontier_result", "validate_request_durable_context",
            "command_check_scientific_acceptance", "command_check_research_integrity",
            "goal_drift", "evaluator_integrity", "freeze_controller_material",
            "command_promote_episode_memory", "command_promote_learning_proposal",
            "application_authority", "authorize_evaluator_change",
            "command_start_acceptance_profile",
            "command_complete_acceptance_profile",
            "command_validate_acceptance_claim",
            "ACCEPTANCE_FAULT_SCENARIOS",
        )),
        "harness runtime is missing run-4 safety and reconciliation contracts",
        errors,
    )
    require(
        all(token in read("references/scripts/harness-runtime.py") for token in (
            "init-staged-research", "preflight-staged-research",
            "record-role-visible-state", "freeze-stage-candidate",
            "create-logical-gate-query", "record-gate-transport-attempt",
            "apply-logical-gate-decision", "record-stage-report",
            "record-strong-stage-review", "compile-next-stage",
            "record-evaluator-rebaseline", "amend-staged-contract",
            "release-staged-evidence", "retrieve-staged-evidence",
            "replay-role-visible-state", "classify-staged-failure",
            "reauthorize-staged-research",
            "HARNESS_FAULT_AFTER_COMBINED_STAGED_CAPACITY",
            "compile-journals", "staged_locked_command",
            "STAGED_CP01_EVIDENCE_PROFILE", "mandatory_future_calls",
        )),
        "harness runtime is missing v0.16 staged governance commands",
        errors,
    )
    staged_tests = read("tests/test_staged_research_governance.py")
    for boundary in (
        "test_contract_preflight_and_cp01_bind_exactly_one_stage",
        "test_gate_truth_table_negative_evidence_and_escalation_block",
        "test_gate_query_is_single_and_transport_retries_are_independent",
        "test_minimax_report_fresh_non_m3_review_and_one_next_stage",
        "test_figure_inventory_freezes_only_at_figure_stage",
        "test_preflight_rejects_self_attestation_zero_budget_and_hash_drift",
        "test_gate_crash_recovery_is_exact_once_and_maturity_skip_fails",
        "test_forged_worker_identity_and_role_visible_source_drift_fail",
        "test_combined_capacity_concurrency_and_crash_recovery",
        "test_evaluator_adoption_drift_requires_rebaseline_and_owner_lineage",
        "test_stage_stop_requires_canonical_human_reauthorization",
        "test_concurrent_staged_mutators_have_unique_audit_revisions",
        "test_concurrent_and_crashed_next_stage_compile_are_exact_once",
    ):
        require(
            f"def {boundary}" in staged_tests,
            f"missing v0.16 staged governance regression {boundary}", errors,
        )
    require(
        "first authorized figure-production stage"
        in read("references/figure-requirements.schema.json")
        and "Legacy v0.15 plans retain"
        in read("references/scientific-figure-pipeline.md"),
        "figure requirements documentation has stale CP-01 timing",
        errors,
    )
    require(
        "--preflight-inputs raw-preflight-evidence.json"
        in read("references/claude-code-runtime.md")
        and "--validators validators.json"
        not in read("references/claude-code-runtime.md"),
        "staged runtime documentation still permits caller-authored preflight verdicts",
        errors,
    )
    durable_tests = read("tests/test_durable_loop_runtime.py")
    require(
        all(name in durable_tests for name in (
            "test_external_registration_concurrent_claim_and_reconciliation",
            "test_state_capsule_rebuild_and_integrity_drift",
            "test_guardian_rejects_content_and_requires_applied_lifecycle_authority",
            "test_registration_and_applied_tick_crash_recover_without_duplicate",
        )),
        "T006 durable-loop tests are incomplete",
        errors,
    )
    admission_tests = read("tests/test_evaluator_admission.py")
    require(
        all(name in admission_tests for name in (
            "test_unattended_conference_is_blocked_then_admitted_and_drift_revokes",
            "test_replay_human_review_and_writable_authority_fail_closed",
        )),
        "T002-A evaluator-admission tests are incomplete",
        errors,
    )
    e2e_tests = read("tests/test_claude_cutover_e2e.py")
    require(
        all(name in e2e_tests for name in (
            "test_declarative_evaluator_and_nonfinite_values_fail_closed",
            "test_stateful_operation_faults_reconcile_without_duplicate_effects",
            "test_waiver_requires_cp04_for_exact_candidate_contract_and_verdict",
        )),
        "run-4 focused safety regressions are missing",
        errors,
    )

    prompts = json.loads((ROOT / "test-prompts.json").read_text())
    prompt_text = json.dumps(prompts, ensure_ascii=False)
    require("hash-bound verdict" in prompt_text, "root test prompts must cover evidence-bound acceptance", errors)
    require("signed stop" in prompt_text, "root test prompts must cover authenticated stop", errors)
    require("allowed_write_paths=[]" in prompt_text, "root test prompts must cover bounded worker policy", errors)

    test_prompts = json.loads((ROOT / "tests/test-prompts.json").read_text())
    names = {item["name"] for item in test_prompts}
    require({"research_gate_blocks_writing", "typed_failure_pivot", "cleanup_manifest", "target_path_no_mavis"}.issubset(names), "tests/test-prompts.json missing target contract tests", errors)

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("contracts ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
