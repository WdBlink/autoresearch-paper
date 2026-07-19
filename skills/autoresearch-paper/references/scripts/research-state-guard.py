#!/usr/bin/env python3
"""Research state guard for autoresearch-paper plans.

Compatibility entrypoint for the evidence gate and typed scientific pivot.
"""

from __future__ import annotations

import argparse
import json
import subprocess
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


def check_writing_gate(args: argparse.Namespace) -> int:
    plan_dir = Path(args.plan_dir).expanduser().resolve()
    runtime = Path(__file__).with_name("harness-runtime.py")
    command = [sys.executable, str(runtime), "check-writing-gate", "--plan-dir", str(plan_dir), "--tier", args.tier]
    for flag, value in (("--verdict", args.verdict), ("--waiver", args.waiver)):
        if value:
            command.extend([flag, value])
    return subprocess.run(command).returncode


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
    runtime = Path(__file__).with_name("harness-runtime.py")
    return subprocess.run([
        sys.executable, str(runtime), "apply-structural-pivot", "--plan-dir", str(plan_dir),
        "--proposal", str(proposal),
    ]).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    gate = sub.add_parser("check-writing-gate")
    gate.add_argument("--plan-dir", required=True)
    gate.add_argument("--tier", required=True, choices=["arxiv", "conference", "journal-q1"])
    gate.add_argument("--verdict")
    gate.add_argument("--waiver")
    gate.set_defaults(func=check_writing_gate)

    pivot = sub.add_parser("validate-pivot")
    pivot.add_argument("--plan-dir", required=True)
    pivot.add_argument("--proposal", required=True)
    pivot.set_defaults(func=validate_pivot)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
