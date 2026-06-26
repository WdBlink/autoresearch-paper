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
        "tests/test_runtime_contracts.py",
    ]:
        require((ROOT / path).exists(), f"missing {path}", errors)

    require(
        contains("SKILL.md", "research_acceptance.md", "plan-l0-guard.py", "cleanup-plan-resources.sh", "resource_manifest.json"),
        "SKILL.md must document research gate, L0, cleanup, and resource manifest",
        errors,
    )
    require(
        contains("SKILL.md", "❌-11", "❌-12", "❌-13", "FM-20", "FM-21", "FM-22", "FM-23"),
        "SKILL.md must include new anti-patterns and failure modes",
        errors,
    )
    require(
        contains("references/plan-template-conference.md", "T0 evaluator-freeze", "T6.1 evaluate-candidate", "T6.2 research-decision", "T6.3 pivot-or-retry", "WAIVED_BY_HUMAN"),
        "conference template must include research-first gate",
        errors,
    )
    require(
        contains("references/plan-template-journal-q1.md", "T0 evaluator-freeze", "T6.1 evaluate-candidate", "T6.2 research-decision", "T6.3 pivot-or-retry"),
        "journal-q1 template must include research-first gate",
        errors,
    )
    require(
        contains("references/plan-template-arxiv.md", "T2.5", "WAIVED_NEGATIVE_RESULT", "research_acceptance.md"),
        "arxiv template must explicitly handle negative-result waiver",
        errors,
    )
    require(
        contains("references/task-prompt-snippets.md", "T0-evaluator-freeze", "T6.1-evaluate-candidate", "T6.2-research-decision", "T6.3-pivot-or-retry", "directions_tried.json", "research-state-guard.py"),
        "task snippet index must expose research loop snippets",
        errors,
    )
    require(
        contains("assets/task-prompt-snippets.md", "T0-evaluator-freeze", "T6.1-evaluate-candidate", "T6.2-research-decision", "T6.3-pivot-or-retry", "directions_tried.json", "research-state-guard.py"),
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
        contains("references/scripts/stop-plan.sh", "control/stop_requested.json", "cleanup-plan-resources.sh"),
        "stop script must use control file and cleanup script",
        errors,
    )
    require(
        contains("references/scripts/resume-plan.sh", "plan-l0-guard.py", "--repair-resources"),
        "resume script must run L0 resource verification/repair",
        errors,
    )
    require(
        contains("tests/test_runtime_contracts.py", "test_cleanup_preserves_non_ephemeral_resources", "test_research_writing_gate", "test_l0_dry_run_does_not_mutate_state", "test_resolve_plan_dir_and_stop_json_escaping"),
        "runtime contract tests must cover cleanup, research gate, dry-run, and plan-dir mapping",
        errors,
    )

    prompts = json.loads((ROOT / "test-prompts.json").read_text())
    prompt_text = json.dumps(prompts, ensure_ascii=False)
    require("research_acceptance.md" in prompt_text, "root test prompts must cover research acceptance gate", errors)
    require("cleanup-plan-resources.sh" in prompt_text, "root test prompts must cover cleanup", errors)
    require("ephemeral=true" in prompt_text, "root test prompts must cover ephemeral agent policy", errors)

    test_prompts = json.loads((ROOT / "tests/test-prompts.json").read_text())
    names = {item["name"] for item in test_prompts}
    require({"research_gate_blocks_writing", "l0_stale_pivot", "cleanup_manifest"}.issubset(names), "tests/test-prompts.json missing new contract tests", errors)

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("contracts ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
