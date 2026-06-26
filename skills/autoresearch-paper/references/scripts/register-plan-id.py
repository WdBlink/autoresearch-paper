#!/usr/bin/env python3
"""Register the Mavis engine plan id in an autoresearch plan directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-dir", required=True)
    parser.add_argument("--plan-id", required=True)
    args = parser.parse_args()

    plan_dir = Path(args.plan_dir).expanduser().resolve()
    manifest_path = plan_dir / "resource_manifest.json"
    data = {}
    if manifest_path.exists():
        data = json.loads(manifest_path.read_text())
    data["plan_id"] = args.plan_id
    data["plan_dir"] = str(plan_dir)
    data["updated_at"] = now_iso()
    manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    state = plan_dir / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "plan_id").write_text(args.plan_id + "\n")
    with (state / "control_history.jsonl").open("a") as f:
        f.write(json.dumps({"ts": now_iso(), "action": "register_plan_id", "plan_id": args.plan_id}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
