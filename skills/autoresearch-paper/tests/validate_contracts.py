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
        "tests/test_runtime_contracts.py",
        "tests/test_claude_cutover_e2e.py",
        "tests/test_runtime_v2_security.py",
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
            "run-evaluator", "applied", "advisory",
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
        contains("references/plan-template-conference.md", "T0 evaluator-freeze", "T6.1 evaluate-candidate", "T6.2 research-decision", "T6.3 pivot-or-retry", "record-evaluator-verdict", "pivot-eligibility"),
        "conference template must include research-first gate",
        errors,
    )
    require(
        contains("references/plan-template-journal-q1.md", "T0 evaluator-freeze", "T6.1 evaluate-candidate", "T6.2 research-decision", "T6.3 pivot-or-retry"),
        "journal-q1 template must include research-first gate",
        errors,
    )
    require(
        contains("references/plan-template-arxiv.md", "T2.5", "authenticated", "check-writing-gate"),
        "arxiv template must explicitly handle negative-result waiver",
        errors,
    )
    require(
        contains("references/task-prompt-snippets.md", "T0-evaluator-freeze", "T6.1-evaluate-candidate", "T6.2-research-decision", "T6.3-pivot-or-retry", "directions_tried.json", "research-state-guard.py"),
        "task snippet index must expose research loop snippets",
        errors,
    )
    require(
        contains("assets/task-prompt-snippets.md", "T0-evaluator-freeze", "T6.1-evaluate-candidate", "T6.2-research-decision", "T6.3-pivot-or-retry", "record-evaluator-verdict", "pivot-eligibility", "research-state-guard.py"),
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
        contains("tests/test_claude_cutover_e2e.py", "assertIsNone", "CP-01", "CP-02", "CP-03", "CP-04", "MiniMax-M3", "remove-resource"),
        "end-to-end test must prove the complete no-MAVIS target path",
        errors,
    )
    require(
        contains("references/scripts/run-claude-harness.py", "completed_steps", "expect_failure", "workflow_sha256", "send-frontier-request"),
        "canonical top-level runner must journal, resume, and retain negative evidence",
        errors,
    )
    require('version: "0.8.0"' in read("SKILL.md"), "SKILL.md version must be 0.8.0", errors)
    require("Current version:** v0.8.0" in (ROOT.parents[1] / "README.md").read_text(), "README version must be 0.8.0", errors)
    require(
        all(token in read("references/scripts/harness-runtime.py") for token in (
            "create-human-action", "apply-human-action", "run-evaluator", "record-evaluator-verdict",
            "pivot-eligibility", "wait-worker", "cancel-worker", "run-patrol",
            "promote-worker-artifacts", "reconcile-frontier-request",
            "apply-frontier-response", "dependent-transition", "assert-transition",
        )),
        "harness runtime is missing target commands",
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
