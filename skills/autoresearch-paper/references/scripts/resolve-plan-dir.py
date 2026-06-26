#!/usr/bin/env python3
"""Resolve an autoresearch plan target to the plan artifact directory."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def candidate_roots(extra: list[str]) -> list[Path]:
    roots = [Path(p).expanduser() for p in extra if p]
    env = os.environ.get("AUTORESEARCH_PLAN_ROOTS", "")
    roots.extend(Path(p).expanduser() for p in env.split(os.pathsep) if p)
    roots.extend([
        Path.home() / ".mavis" / "plans",
        Path.home() / ".mavis" / "scratchpads",
    ])
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except FileNotFoundError:
            resolved = root
        if resolved not in seen:
            seen.add(resolved)
            unique.append(root)
    return unique


def manifest_matches(path: Path, target: str) -> bool:
    manifest = read_json(path / "resource_manifest.json")
    if isinstance(manifest, dict):
        if manifest.get("plan_id") == target:
            return True
        if manifest.get("topic_slug") == target:
            return True
    plan_id_file = path / "state" / "plan_id"
    if plan_id_file.exists() and plan_id_file.read_text().strip() == target:
        return True
    return False


def resolve(target: str, roots: list[str]) -> Path | None:
    direct = Path(target).expanduser()
    if direct.is_dir():
        return direct.resolve()

    home_plan = Path.home() / ".mavis" / "plans" / target
    if home_plan.is_dir() and (home_plan / "resource_manifest.json").exists():
        return home_plan.resolve()

    for root in candidate_roots(roots):
        if not root.exists():
            continue
        for manifest in root.rglob("resource_manifest.json"):
            plan_dir = manifest.parent
            if manifest_matches(plan_dir, target):
                return plan_dir.resolve()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="plan id, topic slug, or plan directory")
    parser.add_argument("--root", action="append", default=[], help="extra root to search")
    args = parser.parse_args()

    resolved = resolve(args.target, args.root)
    if resolved is None:
        print(f"ERROR: could not resolve plan target: {args.target}", file=sys.stderr)
        return 1
    print(resolved)
    return 0


if __name__ == "__main__":
    sys.exit(main())
