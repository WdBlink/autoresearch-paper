#!/usr/bin/env python3
"""
plan-rescue-daemon.py — Patrol running plans + record local-model advice.

Designed to run every minute (cron or launchd). For each running/paused plan:
  1. Read state.json to detect anomalies:
     - paused > 10 min without owner decision → request bounded advice
     - Awaiting Your Verdict > 30 min → request advice via local_llm_judge
     - engine not running > 5 min but plan is "running" → restart
     - auto_reject_retries exceeded with 0 passes → escalate to a human
  2. Call local_llm_judge.py with the decision context (state + verifier
     feedback) to get a structured verdict.
  3. Persist the advice under control/ for the deterministic controller or
     authenticated human owner. Model advice never accepts, waives, or cancels.
  4. Log everything to plan/watchdog-log.md + state/rescue_history.jsonl.

Honors:
  - state/pause_requested.json  → emit pause checkpoint, do NOT auto-judge
  - state/stop_requested.json   → cancel plan + mark stopped
  - state/local_llm_disabled     → skip model advice (fall back to nudge only)

Single source of truth: this daemon is a patrol and advisory component. Formal
state transitions remain owned by the deterministic controller, and human-only
lifecycle actions require an authenticated owner request.

Run mode:
  - Default: scan $HOME/.mavis/plans/*/state.json for status in
    {running, paused}
  - --plan-id <id>: only patrol one plan (debug)
  - --dry-run: show actions without applying
  - --once: run once and exit (cron-friendly)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAVIS_PLANS_DIR = Path.home() / ".mavis" / "plans"
LOCAL_LLM_JUDGE = Path.home() / ".mavis" / "agents" / "mavis" / "scripts" / "local_llm_judge.py"
L0_GUARD = Path.home() / ".mavis" / "agents" / "mavis" / "scripts" / "plan-l0-guard.py"
CLEANUP_PLAN_RESOURCES = Path.home() / ".mavis" / "agents" / "mavis" / "scripts" / "cleanup-plan-resources.sh"
RESCUE_HISTORY = "rescue_history.jsonl"
PAUSE_REQUEST = "pause_requested.json"
STOP_REQUEST = "stop_requested.json"
RESUME_SIGNAL = "resume_signal.json"
DISABLE_FLAG = "local_llm_disabled"

# Thresholds (seconds)
PAUSED_TIMEOUT_SEC = 600      # 10 min — auto-judge if no owner action
AWAITING_VERDICT_TIMEOUT = 1800  # 30 min
ENGINE_NOT_RUNNING_TIMEOUT = 300  # 5 min


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(f"[rescue-daemon {now_iso()}] {msg}", flush=True)


def plan_roots() -> list[Path]:
    roots = [MAVIS_PLANS_DIR]
    for raw in os.environ.get("AUTORESEARCH_PLAN_ROOTS", "").split(os.pathsep):
        if raw:
            roots.append(Path(raw).expanduser())
    roots.append(Path.home() / ".mavis" / "scratchpads")
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except FileNotFoundError:
            resolved = root
        if resolved not in seen:
            seen.add(resolved)
            out.append(root)
    return out


def find_active_plans() -> list[Path]:
    """Return plan directories with active state.json."""
    plans = []
    seen: set[Path] = set()
    candidates: list[Path] = []
    for root in plan_roots():
        if not root.exists():
            continue
        if root == MAVIS_PLANS_DIR:
            candidates.extend([d for d in root.iterdir() if d.is_dir()])
        else:
            candidates.extend([p.parent for p in root.rglob("resource_manifest.json")])
    for d in candidates:
        try:
            resolved = d.resolve()
        except FileNotFoundError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        state = read_state(d)
        status = state.get("status")
        if status in ("running", "paused"):
            plans.append(d)
    return plans


def read_state(plan_dir: Path) -> dict[str, Any]:
    state_json = plan_dir / "state.json"
    if state_json.exists():
        try:
            data = json.loads(state_json.read_text())
            return data.get("state", data)
        except json.JSONDecodeError:
            pass
    progress = plan_dir / "state" / "progress.json"
    try:
        data = json.loads(progress.read_text())
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_rescue_log(plan_dir: Path, entry: dict[str, Any]) -> None:
    history_file = plan_dir / "state" / RESCUE_HISTORY
    history_file.parent.mkdir(parents=True, exist_ok=True)
    with history_file.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def write_advisory_proposal(plan_dir: Path, proposal: dict[str, Any]) -> Path:
    """Atomically persist model advice without applying a plan transition."""
    control_dir = plan_dir / "control"
    control_dir.mkdir(parents=True, exist_ok=True)
    target = control_dir / "model_advisory_proposal.json"
    temporary = control_dir / f".{target.name}.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(proposal, indent=2) + "\n")
    os.replace(temporary, target)
    return target


def append_watchdog_log(plan_dir: Path, severity: str, kind: str, msg: str) -> None:
    log_file = plan_dir / "watchdog-log.md"
    line = f"[{now_iso()}] {severity} {kind}\nfinding: {msg}\nrecommendation: see rescue_history\n\n"
    with log_file.open("a") as f:
        f.write(line)


def signal_paths(plan_dir: Path, name: str) -> list[Path]:
    """Return the canonical controller receipt location only."""
    return [plan_dir / "control" / name]


def has_signal(plan_dir: Path, name: str) -> bool:
    return any(p.exists() for p in signal_paths(plan_dir, name))


def remove_signal(plan_dir: Path, name: str) -> None:
    for path in signal_paths(plan_dir, name):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def call_l0_guard(plan_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    """Delegate running-plan liveness/resource checks to the L0 guard."""
    if not L0_GUARD.exists():
        return {"action": "l0_missing", "reason": f"{L0_GUARD} not found"}
    cmd = [
        "python3",
        str(L0_GUARD),
        "--plan-dir",
        str(plan_dir),
        "--once",
        "--repair-resources",
    ]
    if dry_run:
        cmd.append("--dry-run")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return {"action": "l0_timeout", "reason": "plan-l0-guard timed out"}
    if proc.returncode != 0:
        return {"action": "l0_failed", "reason": proc.stderr[:300]}
    for line in reversed(proc.stdout.splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return {"action": "l0_unparsed", "reason": proc.stdout[:300]}


def call_local_llm_judge(prompt: str, system: str = "") -> tuple[int, dict[str, Any] | str]:
    """Call local_llm_judge.py and return (exit_code, parsed_dict_or_raw)."""
    if not LOCAL_LLM_JUDGE.exists():
        return 3, "local_llm_judge.py not found"
    cmd = [
        "python3", str(LOCAL_LLM_JUDGE),
        "--prompt", prompt,
        "--json-mode",
        "--quiet",
    ]
    if system:
        cmd += ["--system", system]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            return proc.returncode, f"judge failed: {proc.stderr[:300]}"
        # Try parse as JSON
        raw = proc.stdout.strip()
        try:
            return 0, json.loads(raw)
        except json.JSONDecodeError:
            return 0, {"verdict": "nudge", "reason": f"non-json judge output: {raw[:200]}"}
    except subprocess.TimeoutExpired:
        return 3, "judge timeout"


def build_judge_prompt(plan_id: str, state: dict, paused_reason: str) -> tuple[str, str]:
    """Build the judge prompt given a paused plan state."""
    cycle = state.get("cycle")
    status = state.get("status")
    phase = state.get("phase")

    # Find failing / paused task
    failing_task = None
    for r in state.get("results", []):
        if r.get("status") in ("verifying", "ready"):
            failing_task = r
            break

    task_summary = ""
    if failing_task:
        vr = failing_task.get("verifier_results", [])
        last_v = vr[-1] if vr else {}
        task_summary = f"""\
Task: {failing_task.get('task_id')}
Status: {failing_task.get('status')}
Attempt: {failing_task.get('attempt')}
Last verifier passed: {last_v.get('passed')}
Last verifier summary (first 800 chars): {(last_v.get('summary') or '')[:800]}
"""

    system = """\
You are an advisory model for an autonomous research plan engine.
Your role: when the plan engine is paused, recommend one bounded next step:
  - "recommend_retry" — there is a small fixable issue; provide a repair hint
  - "escalate_human" — acceptance, waiver, cancellation, or a structural owner decision is required
  - "nudge" — wait and re-check in N minutes (return a positive "wait_minutes" int)

You have no authority to accept, waive, override acceptance, cancel, resume,
or mutate lifecycle state. Never emit one of those actions.

Output strict JSON only:
{"verdict": "<one of recommend_retry|escalate_human|nudge>",
 "reason": "<one-sentence justification>",
 "hint": "<if recommend_retry, one-sentence directive to producer; else null>",
 "wait_minutes": <int if nudge, else null>}
"""

    prompt = f"""\
Plan ID: {plan_id}
Cycle: {cycle}, Phase: {phase}, Status: {status}
Pause reason: {paused_reason}

Current failing/awaiting task:
{task_summary or '(no specific task — plan-level pause)'}

Recent rescue history (last 3 entries):
{json.dumps([json.loads(l) for l in Path(__file__).parent.glob('*')], default=str)[:500] if False else '(unavailable)'}

Decide: take one action and emit strict JSON.
"""
    return prompt, system


def apply_explicit_stop_request(plan_id: str) -> tuple[str, str]:
    """Apply a legacy explicit stop signal; never call this for model output."""
    cmd = ["mavis", "team", "plan", "cancel", plan_id]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    action = "cancelled" if proc.returncode == 0 else f"failed: {proc.stderr[:200]}"
    return action, " ".join(cmd)


def patrol_plan(plan_dir: Path, dry_run: bool = False, legacy_mavis: bool = False) -> dict[str, Any]:
    """Patrol one plan, return action taken."""
    plan_id = plan_dir.name
    state = read_state(plan_dir)
    if not state:
        return {"plan_id": plan_id, "action": "skipped", "reason": "no state"}

    status = state.get("status")
    cycle = state.get("cycle")
    phase = state.get("phase")

    # Honor user pause/resume/stop requests. New scripts write under
    # control/, but root/state paths remain supported for older runs.
    if has_signal(plan_dir, RESUME_SIGNAL):
        if dry_run:
            return {"plan_id": plan_id, "action": "dry_run_resume",
                    "reason": "resume_signal.json present"}
        if legacy_mavis:
            proc = subprocess.run(["mavis", "team", "plan", "resume", plan_id],
                                  capture_output=True, text=True, timeout=60)
            action = "legacy_resumed" if proc.returncode == 0 else f"legacy_resume_failed: {proc.stderr[:200]}"
        else:
            action = "target_resume_receipt_observed"
        entry = {"ts": now_iso(), "plan_id": plan_id, "action": action,
                 "reason": "resume_signal.json present"}
        write_rescue_log(plan_dir, entry)
        return entry

    if has_signal(plan_dir, PAUSE_REQUEST):
        return {"plan_id": plan_id, "action": "pause_respected",
                "reason": "pause_requested.json present; skipping auto-judge"}

    if has_signal(plan_dir, STOP_REQUEST):
        runtime = Path(__file__).with_name("harness-runtime.py")
        authority = plan_dir / "control" / STOP_REQUEST
        validation = subprocess.run([
            sys.executable, str(runtime), "validate-action-receipt", "--plan-dir", str(plan_dir),
            "--receipt", str(authority), "--action", "stop",
        ], capture_output=True, text=True, timeout=60)
        if validation.returncode != 0:
            entry = {"ts": now_iso(), "plan_id": plan_id, "action": "invalid_stop_authority",
                     "reason": validation.stderr[-300:]}
            if not dry_run:
                write_rescue_log(plan_dir, entry)
            return entry
        if dry_run:
            action, cmd = "dry_run_stop_receipt", "deterministic target cleanup"
        elif legacy_mavis:
            action, cmd = apply_explicit_stop_request(plan_id)
        else:
            action, cmd = "target_stop_receipt_observed", "(no lifecycle command)"
        cleanup_action = "cleanup_script_missing"
        cleanup_cmd = ""
        if CLEANUP_PLAN_RESOURCES.exists():
            cleanup_cmd_list = [
                str(CLEANUP_PLAN_RESOURCES),
                str(plan_dir),
                "--authorization",
                str(authority),
                "--reason",
                "rescue daemon observed stop_requested.json",
            ]
            if dry_run:
                cleanup_action = "dry_run_cleanup"
                cleanup_cmd = " ".join(cleanup_cmd_list)
            else:
                proc = subprocess.run(cleanup_cmd_list, capture_output=True, text=True, timeout=180)
                cleanup_action = "cleanup_ok" if proc.returncode == 0 else f"cleanup_failed: {proc.stderr[:200]}"
                cleanup_cmd = " ".join(cleanup_cmd_list)
        entry = {"plan_id": plan_id, "action": action, "command": cmd,
                 "cleanup_action": cleanup_action, "cleanup_command": cleanup_cmd,
                 "reason": "stop_requested.json present"}
        if not dry_run:
            write_rescue_log(plan_dir, {"ts": now_iso(), **entry})
        return entry

    if status != "paused":
        l0 = call_l0_guard(plan_dir, dry_run=dry_run)
        return {"plan_id": plan_id, "action": f"l0_{l0.get('action', 'checked')}",
                "reason": f"status={status}; delegated non-paused patrol to L0",
                "l0": l0}

    # Honor local LLM disable flag only for paused auto-judge. L0 liveness
    # still runs above even when local LLM judging is disabled.
    if has_signal(plan_dir, DISABLE_FLAG):
        return {"plan_id": plan_id, "action": "skipped",
                "reason": f"{DISABLE_FLAG} present; local LLM disabled for this plan"}

    # Plan is paused. Find pause age.
    # state.cycle_started_at is in milliseconds
    cycle_started_ms = state.get("cycle_started_at")
    if not cycle_started_ms:
        return {"plan_id": plan_id, "action": "skipped",
                "reason": "no cycle_started_at; cannot compute pause age"}

    pause_age_sec = (time.time() * 1000 - cycle_started_ms) / 1000

    if pause_age_sec < PAUSED_TIMEOUT_SEC:
        return {"plan_id": plan_id, "action": "wait",
                "reason": f"paused {int(pause_age_sec)}s < {PAUSED_TIMEOUT_SEC}s threshold"}

    log(f"plan {plan_id} paused for {int(pause_age_sec)}s — calling local_llm_judge")

    # Determine pause reason
    failing_task = None
    for r in state.get("results", []):
        if r.get("status") in ("verifying", "ready"):
            failing_task = r
            break
    pause_reason = "Awaiting owner decision"
    if failing_task:
        vr = failing_task.get("verifier_results", [])
        if vr:
            pause_reason = f"verifier: {(vr[-1].get('summary') or '')[:300]}"
        elif failing_task.get("status") == "ready":
            pause_reason = f"task {failing_task['task_id']} in ready state (re-eval needed)"

    prompt, system = build_judge_prompt(plan_id, state, pause_reason)
    code, verdict_obj = call_local_llm_judge(prompt, system)

    if code != 0:
        return {"plan_id": plan_id, "action": "judge_failed",
                "reason": f"judge exit {code}: {str(verdict_obj)[:200]}"}

    if not isinstance(verdict_obj, dict):
        return {"plan_id": plan_id, "action": "judge_invalid",
                "reason": f"judge returned non-dict: {str(verdict_obj)[:200]}"}

    verdict = verdict_obj.get("verdict", "nudge")
    allowed_verdicts = {"recommend_retry", "escalate_human", "nudge"}
    if verdict not in allowed_verdicts:
        verdict_obj = {
            "verdict": "escalate_human",
            "reason": f"model proposed forbidden lifecycle action: {verdict}",
            "hint": None,
            "wait_minutes": None,
            "rejected_model_output": verdict_obj,
        }
        verdict = "escalate_human"
    reason = verdict_obj.get("reason", "")
    hint = verdict_obj.get("hint")
    wait_minutes = verdict_obj.get("wait_minutes")

    log(f"plan {plan_id} judge verdict: {verdict} — {reason}")

    if dry_run:
        return {"plan_id": plan_id, "action": "dry_run",
                "verdict": verdict, "reason": reason, "hint": hint,
                "wait_minutes": wait_minutes}

    proposal_path = write_advisory_proposal(plan_dir, {
        "schema_version": 1,
        "created_at": now_iso(),
        "plan_id": plan_id,
        "source": "local_llm_judge",
        "advisory_only": True,
        "requires_controller_or_human_review": True,
        "advice": verdict_obj,
    })
    action, cmd = "advisory_recorded", "(no lifecycle command)"

    entry = {
        "ts": now_iso(),
        "plan_id": plan_id,
        "pause_age_sec": int(pause_age_sec),
        "judge_verdict": verdict,
        "judge_reason": reason,
        "judge_hint": hint,
        "action": action,
        "command": cmd,
        "proposal_path": str(proposal_path),
        "raw_judge": verdict_obj,
    }
    write_rescue_log(plan_dir, entry)
    append_watchdog_log(plan_dir, "warn",
                        "rescue-daemon",
                        f"judge {verdict}: {reason} (action: {action})")

    return entry


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--plan-id", help="only patrol one plan")
    p.add_argument("--dry-run", action="store_true", help="show actions without applying")
    p.add_argument("--once", action="store_true", help="run once and exit (cron-friendly)")
    p.add_argument("--legacy-mavis", action="store_true", help="enable explicit legacy plan resume/cancel commands")
    p.add_argument("--interval", type=int, default=60,
                   help="seconds between patrol rounds (default 60; ignored if --once)")
    args = p.parse_args()

    if args.plan_id:
        plan_dirs = [MAVIS_PLANS_DIR / args.plan_id]
        if not plan_dirs[0].exists():
            print(f"ERROR: plan dir not found: {plan_dirs[0]}", file=sys.stderr)
            return 1
    else:
        plan_dirs = find_active_plans()

    if not plan_dirs:
        log("no active plans to patrol")
        return 0

    log(f"patrolling {len(plan_dirs)} plan(s): {[p.name for p in plan_dirs]}")

    if args.once:
        for pd in plan_dirs:
            result = patrol_plan(pd, dry_run=args.dry_run, legacy_mavis=args.legacy_mavis)
            log(f"  {pd.name}: {result.get('action')} — {result.get('reason', '')[:100]}")
        return 0

    # Daemon mode: loop
    log(f"entering daemon loop (interval={args.interval}s, dry_run={args.dry_run})")
    while True:
        for pd in find_active_plans():
            try:
                result = patrol_plan(pd, dry_run=args.dry_run, legacy_mavis=args.legacy_mavis)
                log(f"  {pd.name}: {result.get('action')} — {result.get('reason', '')[:100]}")
            except Exception as e:
                log(f"  {pd.name}: ERROR — {e}")
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main() or 0)
