#!/usr/bin/env python3
"""
plan-l0-guard.py — session-independent supervisor for autoresearch plans.

L0 is intentionally file-backed and conservative. It reads plan state,
control files, last_seen heartbeat, and resource_manifest.json, then writes
status back into state/l0_status.json and state/watchdog_health.json.

It does not write paper outputs and it does not invent research claims.
When a running plan is stale, it increments progress.stale_count once per
stale heartbeat and requests pivot/escalation according to the research
state contract.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAVIS_PLANS_DIR = Path.home() / ".mavis" / "plans"
DEFAULT_STALE_SEC = int(os.environ.get("AUTORESEARCH_STALE_SEC", "7200"))


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: str | None) -> float | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def append_watchdog(plan_dir: Path, severity: str, kind: str, finding: str, recommendation: str) -> None:
    line = (
        f"[{now_iso()}] {severity} {kind}\n"
        f"task: plan-level\n"
        f"finding: {finding}\n"
        f"recommendation: {recommendation}\n"
        f"evidence: {plan_dir}/state/l0_status.json\n\n"
    )
    with (plan_dir / "watchdog-log.md").open("a") as f:
        f.write(line)


def signal_paths(plan_dir: Path, name: str) -> list[Path]:
    return [
        plan_dir / "control" / name,
        plan_dir / "state" / name,
        plan_dir / name,
    ]


def has_signal(plan_dir: Path, name: str) -> bool:
    return any(p.exists() for p in signal_paths(plan_dir, name))


def remove_signal(plan_dir: Path, name: str) -> None:
    for p in signal_paths(plan_dir, name):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def read_state(plan_dir: Path) -> dict[str, Any]:
    raw = read_json(plan_dir / "state.json", {})
    return raw.get("state", raw) if isinstance(raw, dict) else {}


def read_progress(plan_dir: Path) -> dict[str, Any]:
    progress = read_json(plan_dir / "state" / "progress.json", {})
    if not isinstance(progress, dict):
        progress = {}
    progress.setdefault("status", "running")
    progress.setdefault("iteration", 0)
    progress.setdefault("stale_count", 0)
    progress.setdefault("research_status", "not_started")
    return progress


def write_progress(plan_dir: Path, progress: dict[str, Any]) -> None:
    progress["updated_at"] = now_iso()
    write_json(plan_dir / "state" / "progress.json", progress)


def latest_heartbeat(plan_dir: Path) -> dict[str, Any] | None:
    path = plan_dir / "last_seen.jsonl"
    if not path.exists():
        return None
    latest: dict[str, Any] | None = None
    latest_epoch: float | None = None
    for line in path.read_text(errors="ignore").splitlines()[-2000:]:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = parse_ts(rec.get("ts") or rec.get("timestamp"))
        if ts is not None and (latest_epoch is None or ts > latest_epoch):
            latest = rec
            latest_epoch = ts
    if latest is not None:
        latest["_epoch"] = latest_epoch
    return latest


def mavis_available() -> bool:
    return any((Path(p) / "mavis").exists() for p in os.environ.get("PATH", "").split(os.pathsep))


def run_cmd(cmd: list[str], dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"cmd": cmd, "returncode": 0, "stdout": "", "stderr": "", "dry_run": True}
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=90)
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-1000:],
            "stderr": proc.stderr[-1000:],
            "dry_run": False,
        }
    except Exception as exc:  # pragma: no cover - defensive for user machines
        return {"cmd": cmd, "returncode": 127, "stdout": "", "stderr": str(exc), "dry_run": False}


def verify_resources(plan_dir: Path, repair: bool, dry_run: bool) -> dict[str, Any]:
    manifest_path = plan_dir / "resource_manifest.json"
    manifest = read_json(manifest_path, {})
    result: dict[str, Any] = {
        "ts": now_iso(),
        "healthy": True,
        "missing": [],
        "repaired": [],
        "notes": [],
    }
    if not manifest:
        result["healthy"] = False
        result["missing"].append("resource_manifest.json")
        if not dry_run:
            write_json(plan_dir / "state" / "watchdog_health.json", result)
        return result

    if mavis_available():
        # v0.7.0+: `mavis cron list` and `mavis hook list` are removed.
        # Use the native `mavis` tool to list crons/hooks for the agent.
        # For now, fall through to the direct-file branch below — it
        # is sufficient and works whether or not the CLI subset is
        # available. If a future tool form is required, plug it in here.
        pass
    # Direct file check (works with or without the `mavis team plan`
    # CLI subset; in v0.7.0+ the CLI for cron/hook/list is removed,
    # so the file-based check is the primary path).
    cron_root = Path.home() / ".mavis" / "agents"
    for cron in manifest.get("crons", []) or []:
        if not isinstance(cron, dict):
            continue
        agent = cron.get("agent")
        name = cron.get("name")
        if not agent or not name:
            continue
        cron_file = cron_root / agent / "crons" / f"{name}.md"
        if not cron_file.exists():
            result["missing"].append(f"cron:{agent}/{name}")
    hook_root = Path.home() / ".mavis" / "hooks"
    for hook in manifest.get("hooks", []) or []:
        if not isinstance(hook, dict):
            continue
        name = hook.get("name")
        if not name:
            continue
        # v0.7.0+: canonical file is `<name>.md` (manifest stores
        # `first-action-last-seen-<topic>.json`, file is
        # `first-action-last-seen-<topic>.json.md`). Also accept the
        # pre-v0.7 convention `<name>.json.md` and the bare `<name>`
        # form for safety against older manifests.
        hook_canonical = hook_root / f"{name}.md"
        hook_pre_v07 = hook_root / f"{name}.json.md"
        hook_legacy = hook_root / name
        if not (hook_canonical.exists() or hook_pre_v07.exists() or hook_legacy.exists()):
            result["missing"].append(f"hook:{name}")

    for proc in manifest.get("local_processes", []) or []:
        if not isinstance(proc, dict):
            continue
        pid = proc.get("pid")
        label = proc.get("label") or pid
        if pid:
            try:
                os.kill(int(pid), 0)
            except OSError:
                result["missing"].append(f"local_process:{label}")

    launchd_items = manifest.get("launchd", []) or []
    if launchd_items and sys.platform == "darwin":
        for item in launchd_items:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            if label:
                check = run_cmd(["launchctl", "list", label], dry_run)
                if check["returncode"] != 0:
                    result["missing"].append(f"launchd:{label}")
    elif launchd_items:
        result["notes"].append("launchd health skipped on non-darwin platform")

    for proc in manifest.get("remote_processes", []) or []:
        if isinstance(proc, dict):
            label = proc.get("label") or proc.get("pid") or "remote-process"
            result["notes"].append(f"remote process health not checked automatically: {label}")

    result["healthy"] = not result["missing"]

    if repair and result["missing"]:
        bootstrap = manifest.get("bootstrap_script")
        topic_slug = manifest.get("topic_slug")
        tier = manifest.get("tier")
        if bootstrap and topic_slug and tier and Path(bootstrap).exists():
            repair_result = run_cmd([bootstrap, topic_slug, tier, str(plan_dir), "--rescue"], dry_run)
            result["repair_command"] = repair_result
            if repair_result["returncode"] == 0:
                result["repaired"] = list(result["missing"])
                result["missing"] = []
                result["healthy"] = True
            else:
                result["notes"].append("bootstrap repair failed; rebootstrap_required")
        else:
            result["notes"].append("missing bootstrap_script/topic_slug/tier; rebootstrap_required")

    if not dry_run:
        write_json(plan_dir / "state" / "watchdog_health.json", result)
    return result


def request_pivot(plan_dir: Path, progress: dict[str, Any], reason: str, dry_run: bool = False) -> str:
    stale_count = int(progress.get("stale_count", 0))
    if stale_count >= 4:
        progress["research_status"] = "escalate_to_human"
        if not dry_run:
            write_json(plan_dir / "control" / "override_requested.json", {
                "ts": now_iso(),
                "kind": "stale_research_loop",
                "stale_count": stale_count,
                "reason": reason,
                "allowed_actions": ["change_evaluator", "waive_to_arxiv", "stop", "manual_direction"],
            })
            append_watchdog(plan_dir, "critical", "research-escalation", reason, "escalate-to-human")
        return "escalate_to_human"
    if stale_count >= 2:
        progress["research_status"] = "pivot_required"
        if not dry_run:
            write_json(plan_dir / "control" / "pivot_requested.json", {
                "ts": now_iso(),
                "kind": "stale_research_loop",
                "stale_count": stale_count,
                "reason": reason,
                "require_structural_change": True,
            })
            append_watchdog(plan_dir, "warn", "research-pivot", reason, "steer")
        return "pivot_required"
    progress["research_status"] = "stale_observed"
    if not dry_run:
        append_watchdog(plan_dir, "warn", "stale-heartbeat", reason, "wait")
    return "stale_observed"


def patrol_plan(plan_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    plan_id = plan_dir.name
    (plan_dir / "state").mkdir(exist_ok=True)
    (plan_dir / "control").mkdir(exist_ok=True)

    state = read_state(plan_dir)
    status = state.get("status", "unknown")
    progress = read_progress(plan_dir)
    resource_health = verify_resources(plan_dir, repair=args.repair_resources, dry_run=args.dry_run)

    actions: list[str] = []

    if has_signal(plan_dir, "resume_signal.json"):
        if not args.dry_run:
            remove_signal(plan_dir, "pause_requested.json")
        if mavis_available():
            actions.append("resume:" + json.dumps(run_cmd(["mavis", "team", "plan", "resume", plan_id], args.dry_run)))
        if not args.dry_run:
            remove_signal(plan_dir, "resume_signal.json")

    if has_signal(plan_dir, "stop_requested.json"):
        cleanup_script = Path(args.cleanup_script)
        if cleanup_script.exists():
            cleanup = run_cmd([
                str(cleanup_script),
                str(plan_dir),
                "--reason",
                "L0 observed stop_requested.json",
                "--mode",
                "stop",
            ], args.dry_run)
            actions.append("cleanup:" + json.dumps(cleanup))
        else:
            actions.append("cleanup_missing")
        progress["status"] = "stopped"
        if not args.dry_run:
            write_progress(plan_dir, progress)
        result = {
            "plan_id": plan_id,
            "action": "stop_cleanup_requested",
            "status": status,
            "actions": actions,
            "resource_health": resource_health,
        }
        if not args.dry_run:
            write_json(plan_dir / "state" / "l0_status.json", result | {"ts": now_iso()})
            append_jsonl(plan_dir / "state" / "rescue_history.jsonl", result | {"ts": now_iso()})
        return result

    heartbeat = latest_heartbeat(plan_dir)
    now_epoch = time.time()
    stale_sec = args.stale_sec
    if heartbeat is None:
        cycle_started_ms = state.get("cycle_started_at")
        age = None
        if cycle_started_ms:
            age = now_epoch - float(cycle_started_ms) / 1000.0
        if status == "running" and (age is None or age >= stale_sec):
            hb_token = f"NO_HEARTBEAT:{cycle_started_ms or 'unknown'}"
            if progress.get("last_stale_heartbeat_ts") != hb_token:
                progress["stale_count"] = int(progress.get("stale_count", 0)) + 1
                progress["last_stale_heartbeat_ts"] = hb_token
            action = request_pivot(plan_dir, progress, f"running plan has no last_seen heartbeat for >= {stale_sec}s", dry_run=args.dry_run)
            if not args.dry_run:
                write_progress(plan_dir, progress)
            result = {"plan_id": plan_id, "action": action, "status": status, "heartbeat": None, "resource_health": resource_health}
            if not args.dry_run:
                write_json(plan_dir / "state" / "l0_status.json", result | {"ts": now_iso()})
                append_jsonl(plan_dir / "state" / "rescue_history.jsonl", result | {"ts": now_iso()})
            return result
    else:
        hb_epoch = float(heartbeat.get("_epoch") or 0)
        age = now_epoch - hb_epoch
        progress["last_heartbeat_ts"] = heartbeat.get("ts") or heartbeat.get("timestamp")
        if status == "running" and age >= stale_sec:
            hb_token = heartbeat.get("ts") or heartbeat.get("timestamp") or str(hb_epoch)
            if progress.get("last_stale_heartbeat_ts") != hb_token:
                progress["stale_count"] = int(progress.get("stale_count", 0)) + 1
                progress["last_stale_heartbeat_ts"] = hb_token
            action = request_pivot(plan_dir, progress, f"last heartbeat is stale: {int(age)}s >= {stale_sec}s", dry_run=args.dry_run)
            if not args.dry_run:
                write_progress(plan_dir, progress)
            result = {"plan_id": plan_id, "action": action, "status": status, "heartbeat_age_sec": int(age), "resource_health": resource_health}
            if not args.dry_run:
                write_json(plan_dir / "state" / "l0_status.json", result | {"ts": now_iso()})
                append_jsonl(plan_dir / "state" / "rescue_history.jsonl", result | {"ts": now_iso()})
            return result

    progress["status"] = status if status != "unknown" else progress.get("status", "running")
    if not args.dry_run:
        write_progress(plan_dir, progress)
    result = {
        "plan_id": plan_id,
        "action": "ok",
        "status": status,
        "stale_count": progress.get("stale_count", 0),
        "resource_health": resource_health,
    }
    if not args.dry_run:
        write_json(plan_dir / "state" / "l0_status.json", result | {"ts": now_iso()})
    return result


def find_plan_dirs(plan_id: str | None, plan_dir: str | None) -> list[Path]:
    if plan_dir:
        return [Path(plan_dir).expanduser().resolve()]
    if plan_id:
        resolver = Path(__file__).with_name("resolve-plan-dir.py")
        if resolver.exists():
            resolved = run_cmd(["python3", str(resolver), plan_id], dry_run=False)
            if resolved["returncode"] == 0 and resolved["stdout"].strip():
                return [Path(resolved["stdout"].strip()).expanduser().resolve()]
        return [MAVIS_PLANS_DIR / plan_id]
    if not MAVIS_PLANS_DIR.exists():
        return []
    dirs: list[Path] = []
    for d in MAVIS_PLANS_DIR.iterdir():
        if not d.is_dir():
            continue
        if (d / "state.json").exists() or (d / "resource_manifest.json").exists():
            dirs.append(d)
    return dirs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-id")
    parser.add_argument("--plan-dir")
    parser.add_argument("--once", action="store_true", help="run one patrol round")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repair-resources", action="store_true", help="attempt idempotent bootstrap repair")
    parser.add_argument("--stale-sec", type=int, default=DEFAULT_STALE_SEC)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument(
        "--cleanup-script",
        default=str(Path(__file__).with_name("cleanup-plan-resources.sh")),
    )
    args = parser.parse_args()

    while True:
        plan_dirs = find_plan_dirs(args.plan_id, args.plan_dir)
        if not plan_dirs:
            print(json.dumps({"ts": now_iso(), "action": "no_plans"}))
        for plan_dir in plan_dirs:
            if not plan_dir.exists():
                print(json.dumps({"ts": now_iso(), "plan_dir": str(plan_dir), "action": "missing_plan_dir"}))
                continue
            result = patrol_plan(plan_dir, args)
            print(json.dumps(result, sort_keys=True))
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
