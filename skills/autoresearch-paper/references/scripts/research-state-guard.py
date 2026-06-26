#!/usr/bin/env python3
"""Research state guard for autoresearch-paper plans.

This script turns the research-first contract into executable checks:

- `check-writing-gate` blocks T7 unless research_acceptance.md permits it.
- `validate-pivot` rejects hyperparameter-only retries when stale_count >= 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

STRUCTURAL_FIELDS = {
    "algorithm_family",
    "data_representation",
    "objective",
    "evaluator",
    "baseline_framing",
}


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def acceptance_status(plan_dir: Path) -> str:
    path = plan_dir / "state" / "research_acceptance.md"
    if not path.exists():
        return "MISSING"
    for line in path.read_text().splitlines():
        value = line.strip()
        if value:
            return value
    return "EMPTY"


def check_writing_gate(args: argparse.Namespace) -> int:
    plan_dir = Path(args.plan_dir).expanduser().resolve()
    tier = args.tier
    status = acceptance_status(plan_dir)
    allowed = {"PASS", "WAIVED_BY_HUMAN"}
    if tier == "arxiv":
        allowed.add("WAIVED_NEGATIVE_RESULT")
    if status in allowed:
        print(json.dumps({"ok": True, "status": status, "tier": tier}))
        return 0
    print(json.dumps({
        "ok": False,
        "status": status,
        "tier": tier,
        "reason": "writing gate blocked; run T6.1/T6.2 or request a human waiver",
    }))
    return 20


def load_changed_fields(path: Path) -> set[str]:
    text = path.read_text()
    try:
        data = json.loads(text)
        fields = data.get("changed_fields") or data.get("structural_changes") or []
        return {str(item).strip() for item in fields if str(item).strip()}
    except json.JSONDecodeError:
        fields: set[str] = set()
        lowered = text.lower()
        for field in STRUCTURAL_FIELDS:
            if field.replace("_", " ") in lowered or field in lowered:
                fields.add(field)
        return fields


def validate_pivot(args: argparse.Namespace) -> int:
    plan_dir = Path(args.plan_dir).expanduser().resolve()
    proposal = Path(args.proposal).expanduser().resolve()
    progress = read_json(plan_dir / "state" / "progress.json", {})
    stale_count = int(progress.get("stale_count", 0) or 0)
    changed = load_changed_fields(proposal)
    structural = sorted(changed & STRUCTURAL_FIELDS)

    if stale_count < 2:
        print(json.dumps({
            "ok": True,
            "stale_count": stale_count,
            "structural_changes": structural,
            "reason": "tactical retry allowed before stale_count >= 2",
        }))
        return 0

    if structural:
        print(json.dumps({
            "ok": True,
            "stale_count": stale_count,
            "structural_changes": structural,
        }))
        return 0

    print(json.dumps({
        "ok": False,
        "stale_count": stale_count,
        "structural_changes": [],
        "reason": "stale_count >= 2 requires a structural pivot, not a hyperparameter-only retry",
        "allowed_fields": sorted(STRUCTURAL_FIELDS),
    }))
    return 21


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    gate = sub.add_parser("check-writing-gate")
    gate.add_argument("--plan-dir", required=True)
    gate.add_argument("--tier", required=True, choices=["arxiv", "conference", "journal-q1"])
    gate.set_defaults(func=check_writing_gate)

    pivot = sub.add_parser("validate-pivot")
    pivot.add_argument("--plan-dir", required=True)
    pivot.add_argument("--proposal", required=True)
    pivot.set_defaults(func=validate_pivot)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
