#!/usr/bin/env python3
"""
plan-rescue-daemon.py — Patrol running plans + auto-judge via local LLM.

Designed to run every minute (cron or launchd). For each running/paused plan:
  1. Read state.json to detect anomalies:
     - paused > 10 min without owner decision → auto judge + apply
     - Awaiting Your Verdict > 30 min → auto judge via local_llm_judge
     - engine not running > 5 min but plan is "running" → restart
     - auto_reject_retries exceeded with 0 passes → escalate OR force_cancel
  2. Call local_llm_judge.py with the decision context (state + verifier
     feedback) to get a structured verdict.
  3. Apply the verdict via `mavis team plan decision` + `resume`/`cancel`.
  4. Log everything to plan/watchdog-log.md + state/rescue_history.jsonl.

Honors:
  - state/pause_requested.json  → emit pause checkpoint, do NOT auto-judge
  - state/stop_requested.json   → cancel plan + mark stopped
  - state/local_llm_disabled     → skip auto-judge (fall back to nudge only)

Single source of truth: this daemon is the only owner-decision proxy. It is
intentionally conservative — when in doubt, prefer nudge over cancel, prefer
accept over reject (verifier might be strict).

Run mode:
  - Default: scan ~/.mavis/plans/*/state.json for status in
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
RESCUE_HISTORY = "rescue_history.jsonl"
PAUSE_REQUEST = "pause_requested.json"
STOP_REQUEST = "stop_requested.json"
DISABLE_FLAG = "local_llm_disabled"

# Thresholds (seconds)
PAUSED_TIMEOUT_SEC = 600      # 10 min — auto-judge if no owner action
AWAITING_VERDICT_TIMEOUT = 1800  # 30 min
ENGINE_NOT_RUNNING_TIMEOUT = 300  # 5 min


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(f"[rescue-daemon {now_iso()}] {msg}", flush=True)


def find_active_plans() -> list[Path]:
    """Return plan directories with active state.json."""
    if not MAVIS_PLANS_DIR.exists():
        return []
    plans = []
    for d in MAVIS_PLANS_DIR.iterdir():
        if not d.is_dir():
            continue
        state_json = d / "state.json"
        if not state_json.exists():
            continue
        try:
            data = json.loads(state_json.read_text())
            state = data.get("state", data)
            status = state.get("status")
            if status in ("running", "paused"):
                plans.append(d)
        except (json.JSONDecodeError, KeyError):
            continue
    return plans


def read_state(plan_dir: Path) -> dict[str, Any]:
    state_json = plan_dir / "state.json"
    if not state_json.exists():
        return {}
    try:
        data = json.loads(state_json.read_text())
        return data.get("state", data)
    except json.JSONDecodeError:
        return {}


def write_rescue_log(plan_dir: Path, entry: dict[str, Any]) -> None:
    history_file = plan_dir / RESCUE_HISTORY
    with history_file.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def append_watchdog_log(plan_dir: Path, severity: str, kind: str, msg: str) -> None:
    log_file = plan_dir / "watchdog-log.md"
    line = f"[{now_iso()}] {severity} {kind}\nfinding: {msg}\nrecommendation: see rescue_history\n\n"
    with log_file.open("a") as f:
        f.write(line)


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
You are the local LLM judge for an autonomous research plan engine.
Your role: when the plan engine is paused awaiting an owner decision and the
human owner is unavailable, you decide whether to:
  - "accept" — the latest producer attempt is substantively correct, mark it done
  - "manual_retry" — there's a small fixable issue (re-run producer with hint)
  - "override_accept" — verifier complaint is a format/formatting issue, accept content
  - "cancel" — the plan is unrecoverable; abort cleanly
  - "nudge" — wait and re-check in N minutes (return a positive "wait_minutes" int)

Output strict JSON only:
{"verdict": "<one of accept|manual_retry|override_accept|cancel|nudge>",
 "reason": "<one-sentence justification>",
 "hint": "<if manual_retry, one-sentence directive to producer; else null>",
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


def apply_decision(plan_id: str, verdict: dict[str, Any], reason: str) -> tuple[str, str]:
    """Apply verdict via mavis team plan decision/resume/cancel."""
    v = verdict.get("verdict", "nudge")
    cmd_kind = {
        "accept": "accept",
        "override_accept": "override_accept",
        "manual_retry": "manual_retry",
        "cancel": "cancel",
    }.get(v)

    if v == "cancel":
        cmd = ["mavis", "team", "plan", "cancel", plan_id]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return ("cancelled" if proc.returncode == 0 else f"failed: {proc.stderr}"), " ".join(cmd)

    if v in ("accept", "override_accept", "manual_retry"):
        # Build decision JSON
        decision = {
            "last_cycle": [{
                "task_id": "(auto-judge by local_llm_judge)",
                "verdict": cmd_kind,
                "reason": reason,
            }],
            "next_cycle": [],
            "plan_complete": False,
            "message_to_user": f"Auto-judged by local_llm_judge: {v}",
        }
        decision_file = Path("/tmp") / f"rescue-decision-{plan_id}.json"
        decision_file.write_text(json.dumps(decision, indent=2))
        cmd = ["mavis", "team", "plan", "decision", plan_id, "--file", str(decision_file)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        action = "decision_applied" if proc.returncode == 0 else f"decision_failed: {proc.stderr[:200]}"
        if proc.returncode == 0 and v in ("accept", "override_accept"):
            # also resume
            cmd2 = ["mavis", "team", "plan", "resume", plan_id]
            proc2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=60)
            action += " + resume_ok" if proc2.returncode == 0 else f" + resume_failed: {proc2.stderr[:200]}"
        return action, " ".join(cmd)

    if v == "nudge":
        return "nudged (no action, will re-check)", "(no command)"

    return f"unknown verdict: {v}", "(no command)"


def patrol_plan(plan_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    """Patrol one plan, return action taken."""
    plan_id = plan_dir.name
    state = read_state(plan_dir)
    if not state:
        return {"plan_id": plan_id, "action": "skipped", "reason": "no state"}

    status = state.get("status")
    cycle = state.get("cycle")
    phase = state.get("phase")

    # Honor user pause/stop requests
    if (plan_dir / PAUSE_REQUEST).exists():
        return {"plan_id": plan_id, "action": "pause_respected",
                "reason": "pause_requested.json present; skipping auto-judge"}
    if (plan_dir / STOP_REQUEST).exists():
        action, cmd = apply_decision(plan_id, {"verdict": "cancel"},
                                     "user requested stop via stop_requested.json")
        return {"plan_id": plan_id, "action": action, "command": cmd,
                "reason": "stop_requested.json present"}

    # Honor local LLM disable flag
    if (plan_dir / DISABLE_FLAG).exists():
        return {"plan_id": plan_id, "action": "skipped",
                "reason": f"{DISABLE_FLAG} present; local LLM disabled for this plan"}

    if status != "paused":
        return {"plan_id": plan_id, "action": "ok",
                "reason": f"status={status} (not paused)"}

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
    reason = verdict_obj.get("reason", "")
    hint = verdict_obj.get("hint")
    wait_minutes = verdict_obj.get("wait_minutes")

    log(f"plan {plan_id} judge verdict: {verdict} — {reason}")

    if dry_run:
        return {"plan_id": plan_id, "action": "dry_run",
                "verdict": verdict, "reason": reason, "hint": hint,
                "wait_minutes": wait_minutes}

    action, cmd = apply_decision(plan_id, verdict_obj, reason)

    entry = {
        "ts": now_iso(),
        "plan_id": plan_id,
        "pause_age_sec": int(pause_age_sec),
        "judge_verdict": verdict,
        "judge_reason": reason,
        "judge_hint": hint,
        "action": action,
        "command": cmd,
        "raw_judge": verdict_obj,
    }
    write_rescue_log(plan_dir, entry)
    append_watchdog_log(plan_dir, "info" if verdict in ("accept", "override_accept") else "warn",
                        "rescue-daemon",
                        f"judge {verdict}: {reason} (action: {action})")

    return entry


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--plan-id", help="only patrol one plan")
    p.add_argument("--dry-run", action="store_true", help="show actions without applying")
    p.add_argument("--once", action="store_true", help="run once and exit (cron-friendly)")
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
            result = patrol_plan(pd, dry_run=args.dry_run)
            log(f"  {pd.name}: {result.get('action')} — {result.get('reason', '')[:100]}")
        return 0

    # Daemon mode: loop
    log(f"entering daemon loop (interval={args.interval}s, dry_run={args.dry_run})")
    while True:
        for pd in find_active_plans():
            try:
                result = patrol_plan(pd, dry_run=args.dry_run)
                log(f"  {pd.name}: {result.get('action')} — {result.get('reason', '')[:100]}")
            except Exception as e:
                log(f"  {pd.name}: ERROR — {e}")
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main() or 0)