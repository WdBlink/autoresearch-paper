#!/usr/bin/env bash
# bootstrap-watchdog.sh — one-shot setup of per-topic watchdog.
#
# Usage:
#   bootstrap-watchdog.sh <topic-slug> <tier> <plan-dir> [--rescue]
#
# Arguments:
#   topic-slug   kebab-case, e.g. "uav-coverage"
#   tier         arxiv | conference | journal-q1
#   plan-dir     absolute path to the plan output directory
#                (must contain watchdog-system-prompt.md already
#                filled in by the skill)
#
# What this script does, in order:
#   1. Verify preconditions (mavis CLI for `team plan ...`, plan-dir, prompt file).
#   2. Register the watchdog agent by writing `~/.mavis/agents/<name>/agent.md`
#      + `config.yaml` directly (the daemon picks the file up on its next
#      scan; the legacy `mavis agent new` CLI is removed in v0.7.0).
#   3. Register an hourly cron task by writing
#      `~/.mavis/agents/<agent>/crons/<name>.md` (markdown with frontmatter).
#      The daemon picks it up; the legacy `mavis cron create` CLI is removed.
#   4. Register a first-action-last-seen hook by writing
#      `~/.mavis/hooks/<name>.json.md` (markdown with frontmatter). The
#      legacy `mavis hook create` CLI is removed — hooks are plain files
#      in v0.7.0+.
#   5. Write {plan-dir}/WATCHDOG.md describing the watchdog setup and
#      how the user can manually ping it.
#
# Idempotent: re-running with the same arguments detects existing
# resources and skips creation (with a log line). Runtime resources are
# registered in <plan-dir>/resource_manifest.json so stop/resume/cleanup
# can manage the full lifecycle.

set -euo pipefail

if [[ $# -lt 3 ]]; then
  cat >&2 <<EOF
Usage: $0 <topic-slug> <tier> <plan-dir> [--rescue]

  topic-slug   kebab-case, e.g. "uav-coverage"
  tier         arxiv | conference | journal-q1
  plan-dir     absolute path to the plan output directory
  --rescue     install launchd-managed L0/L1 rescue scripts
EOF
  exit 2
fi

TOPIC_SLUG="$1"
TIER="$2"
PLAN_DIR="$3"
shift 3
RESCUE="${RESCUE:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rescue)
      RESCUE=1
      shift
      ;;
    --no-rescue)
      RESCUE=0
      shift
      ;;
    *)
      printf '[bootstrap-watchdog][ERROR] unknown arg: %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

# Resolve script directory so we can find sibling reference files.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Agent names are capped at 20 chars by the Mavis daemon (validation
# error 40002). We append `-wd` (2 chars) to a topic-slug that is
# truncated to 17 chars so the full agent name stays ≤ 20.
MAX_SLUG_LEN=17
if [[ ${#TOPIC_SLUG} -gt ${MAX_SLUG_LEN} ]]; then
  TOPIC_SLUG_TRUNC="${TOPIC_SLUG:0:${MAX_SLUG_LEN}}"
else
  TOPIC_SLUG_TRUNC="${TOPIC_SLUG}"
fi
AGENT_NAME="${TOPIC_SLUG_TRUNC}-wd"

# Cron and hook filenames can be longer, so use the full topic slug.
CRON_NAME="${TOPIC_SLUG_TRUNC}-wd-liveness"
HOOK_FILE_NAME="first-action-last-seen-${TOPIC_SLUG_TRUNC}"

PROMPT_FILE="${PLAN_DIR}/watchdog-system-prompt.md"
HOOK_FILE="${SKILL_ROOT}/assets/first-action-last-seen-hook.md"
WATCHDOG_DOC="${PLAN_DIR}/WATCHDOG.md"
STATE_DIR="${PLAN_DIR}/state"
CONTROL_DIR="${PLAN_DIR}/control"
MANIFEST_FILE="${PLAN_DIR}/resource_manifest.json"

log() { printf '[bootstrap-watchdog] %s\n' "$*" >&2; }
die() { printf '[bootstrap-watchdog][ERROR] %s\n' "$*" >&2; exit 1; }

# ----- 1. Preconditions -----------------------------------------------

# v0.7.0+: only `mavis team plan ...` is a CLI in v0.7+. The agent/cron/
# session/hook subcommands are removed; the script writes those resources
# directly to the runtime's well-known file paths.
command -v mavis >/dev/null 2>&1 || die "mavis CLI not found in PATH (needed for `mavis team plan ...`)"
[[ -d "${PLAN_DIR}" ]] || die "plan-dir does not exist: ${PLAN_DIR}"
[[ -f "${PROMPT_FILE}" ]] || die "watchdog prompt not found: ${PROMPT_FILE} (the skill must write it before running this script)"
[[ -f "${HOOK_FILE}" ]] || die "hook file not found: ${HOOK_FILE}"
mkdir -p "${STATE_DIR}" "${CONTROL_DIR}" "${HOME}/.mavis/agents/${AGENT_NAME}" "${HOME}/.mavis/agents/${AGENT_NAME}/crons" "${HOME}/.mavis/hooks"

case "${TIER}" in
  arxiv|conference|journal-q1) ;;
  *) die "tier must be one of: arxiv, conference, journal-q1 (got: ${TIER})" ;;
esac

NOW_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ----- 2. Watchdog agent (must exist before cron) --------------------
#
# v0.7.0+: the legacy `mavis agent new` CLI is removed. The runtime
# discovers agents by scanning `~/.mavis/agents/<name>/agent.md` on each
# tick. We write that file directly. The cron and hook assets will
# appear on the daemon's next scan (~30 s typical).
#
# `display-name`, `description`, and `persona` are still capped at 20
# chars by the daemon (validation error 40002 — same constraint as agent
# name). Truncate the human-readable labels to fit before writing.

log "creating agent: ${AGENT_NAME} (display: ${TOPIC_SLUG} paper watchdog)"

PROMPT_BODY="$(cat "${PROMPT_FILE}")"

MAX_LABEL_LEN=20
DISPLAY_NAME="${TOPIC_SLUG} paper watchdog"
if [[ ${#DISPLAY_NAME} -gt ${MAX_LABEL_LEN} ]]; then
  DISPLAY_NAME="${DISPLAY_NAME:0:${MAX_LABEL_LEN}}"
fi
DESCRIPTION="${TIER} watchdog"
if [[ ${#DESCRIPTION} -gt ${MAX_LABEL_LEN} ]]; then
  DESCRIPTION="${DESCRIPTION:0:${MAX_LABEL_LEN}}"
fi
PERSONA="Watchdog — patrol"
if [[ ${#PERSONA} -gt ${MAX_LABEL_LEN} ]]; then
  PERSONA="${PERSONA:0:${MAX_LABEL_LEN}}"
fi

AGENT_DIR="${HOME}/.mavis/agents/${AGENT_NAME}"
mkdir -p "${AGENT_DIR}"
AGENT_FILE="${AGENT_DIR}/agent.md"
CONFIG_FILE="${AGENT_DIR}/config.yaml"

if [[ -f "${AGENT_FILE}" ]]; then
  log "  agent file already exists: ${AGENT_FILE} — skipping"
else
  cat > "${AGENT_FILE}" <<EOF
<!-- mavis:bootstrap-agent-md v0.7.0 -->
<!--
This file is created by autoresearch-paper/bootstrap-watchdog.sh.
The Mavis daemon scans this directory and treats the file as a
first-class agent (system_prompt is the file body).
-->
name: ${AGENT_NAME}
display_name: ${DISPLAY_NAME}
description: ${DESCRIPTION}
persona: ${PERSONA}
created_at: ${NOW_UTC}
created_by: autoresearch-paper v0.7.0
topic_slug: ${TOPIC_SLUG}
tier: ${TIER}
plan_dir: ${PLAN_DIR}
---

${PROMPT_BODY}
EOF
  log "  wrote ${AGENT_FILE}"
fi

if [[ ! -f "${CONFIG_FILE}" ]]; then
  cat > "${CONFIG_FILE}" <<EOF
channel:
  default: silent
EOF
  log "  wrote ${CONFIG_FILE}"
fi

# ----- 3. Hourly cron --------------------------------------------------
#
# v0.7.0+: the legacy `mavis cron create` CLI is removed. Crons are
# markdown files at `~/.mavis/agents/<agent>/crons/<name>.md`. Each
# tick spawns a fresh session (session_mode: new) and sends the
# watchdog system prompt. The session runs the patrol procedure,
# emits findings to {PLAN_DIR}/watchdog-log.md, and exits. No
# persistent session means no per-session context bloat.
#
# keep_sessions=5 limits visible sessions to the most recent 5 patrols,
# so the agent's session list does not grow unbounded.

log "creating hourly cron: ${CRON_NAME}"
log "  schedule: 0 * * * *"
log "  session-mode: new"
log "  agent: ${AGENT_NAME}"

CRON_DIR="${AGENT_DIR}/crons"
mkdir -p "${CRON_DIR}"
CRON_FILE="${CRON_DIR}/${CRON_NAME}.md"

if [[ -f "${CRON_FILE}" ]]; then
  log "  cron file already exists: ${CRON_FILE} — skipping"
else
  cat > "${CRON_FILE}" <<EOF
---
name: ${CRON_NAME}
schedule: 0 * * * *
timezone: Asia/Shanghai
agent: ${AGENT_NAME}
session_mode: new
keep_sessions: 5
created_at: ${NOW_UTC}
---

Hourly watchdog patrol for ${TOPIC_SLUG} (tier=${TIER}). Run the patrol
procedure described in your system prompt. Read ${PLAN_DIR}/last_seen.jsonl
and ${PLAN_DIR}/watchdog-log.md, emit findings.
EOF
  log "  wrote ${CRON_FILE}"
fi

# ----- 4. First-action-last-seen hook ---------------------------------
#
# v0.7.0+: the legacy `mavis hook create` CLI is removed. Hooks are
# markdown files at `~/.mavis/hooks/<name>.json.md`. PostToolUse hook
# that, on every tool invocation by any worker agent in this plan,
# appends a line to {PLAN_DIR}/last_seen.jsonl. This is how the
# watchdog detects liveness — if a task has not invoked a tool in 2×
# its expected wall-clock, the watchdog flags it as stale.

log "creating hook: ${HOOK_FILE_NAME}.json"
log "  event: PostToolUse"

HOOK_DIR="${HOME}/.mavis/hooks"
mkdir -p "${HOOK_DIR}"
HOOK_DEST="${HOOK_DIR}/${HOOK_FILE_NAME}.json.md"
HOOK_BODY="$(cat "${HOOK_FILE}")"

if [[ -f "${HOOK_DEST}" ]]; then
  log "  hook file already exists: ${HOOK_DEST} — skipping"
else
  cat > "${HOOK_DEST}" <<EOF
---
hookEvent: PostToolUse
type: script
priority: 100
matcher: ^(Read|Write|Edit|Bash)\$
timeout: 5000
created_at: ${NOW_UTC}
created_by: autoresearch-paper v0.7.0
plan_dir: ${PLAN_DIR}
---

${HOOK_BODY}
EOF
  log "  wrote ${HOOK_DEST}"
fi

# ----- 5. Resource manifest + research state ---------------------------
#
# Register every runtime resource this script creates. stop/resume/L0
# scripts use this manifest instead of forcing the user to hunt through
# Mavis agent, cron, and hook lists manually.

log "writing resource manifest: ${MANIFEST_FILE}"

python3 - "${MANIFEST_FILE}" "${PLAN_DIR}" "${TOPIC_SLUG}" "${TIER}" "${AGENT_NAME}" "${CRON_NAME}" "${HOOK_FILE_NAME}.json" "${SCRIPT_DIR}/bootstrap-watchdog.sh" "${NOW_UTC}" "${RESCUE}" <<'PY'
import json
import sys
from pathlib import Path

manifest_path, plan_dir, topic_slug, tier, agent_name, cron_name, hook_name, bootstrap_script, now, rescue = sys.argv[1:]
data = {
    "schema_version": 1,
    "plan_id": None,
    "plan_dir": plan_dir,
    "topic_slug": topic_slug,
    "tier": tier,
    "status": "running",
    "created_at": now,
    "updated_at": now,
    "bootstrap_script": bootstrap_script,
    "agents": [
        {"name": agent_name, "role": "watchdog", "ephemeral": True}
    ],
    "sessions": [],
    "crons": [
        {"agent": agent_name, "name": cron_name, "schedule": "0 * * * *", "ephemeral": True}
    ],
    "hooks": [
        {"name": hook_name, "event": "PostToolUse", "ephemeral": True}
    ],
    "launchd": [],
    "local_processes": [],
    "remote_processes": [],
    "locks": []
}
if rescue == "1":
    data["launchd"].append({
        "label": "com.mavis.plan-rescue-daemon",
        "plist": "$HOME/Library/LaunchAgents/com.mavis.plan-rescue-daemon.plist",
        "run_scoped": False
    })
Path(manifest_path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
PY

if [[ ! -f "${STATE_DIR}/progress.json" ]]; then
  cat > "${STATE_DIR}/progress.json" <<EOF
{
  "status": "running",
  "tier": "${TIER}",
  "iteration": 0,
  "best_score": null,
  "stale_count": 0,
  "research_status": "not_started",
  "last_direction": null,
  "last_heartbeat_ts": null,
  "last_stale_heartbeat_ts": null,
  "updated_at": "${NOW_UTC}"
}
EOF
fi

if [[ ! -f "${STATE_DIR}/research_acceptance.md" ]]; then
  cat > "${STATE_DIR}/research_acceptance.md" <<EOF
FAIL

Research acceptance has not been granted yet. Conference and journal
writing tasks must not start until T6.2 changes this file to PASS or
WAIVED_BY_HUMAN. Arxiv negative-result writing may use
WAIVED_NEGATIVE_RESULT.
EOF
fi

if [[ ! -f "${STATE_DIR}/directions_tried.json" ]]; then
  printf '{"directions":[]}\n' > "${STATE_DIR}/directions_tried.json"
fi

touch "${STATE_DIR}/candidate_registry.jsonl"

if [[ ! -f "${STATE_DIR}/scoreboard.tsv" ]]; then
  printf 'iteration\tdirection\tprimary_metric\tbaseline_delta\tverdict\treason\n' > "${STATE_DIR}/scoreboard.tsv"
fi

touch "${PLAN_DIR}/last_seen.jsonl" "${PLAN_DIR}/watchdog-log.md"

# ----- 6. WATCHDOG.md --------------------------------------------------
#
# Human-readable summary of the watchdog setup. The user reads this
# to understand what is watching the pipeline and how to interact
# with the watchdog manually.

log "writing watchdog doc: ${WATCHDOG_DOC}"

cat > "${WATCHDOG_DOC}" <<EOF
# Watchdog Setup — ${TOPIC_SLUG}

This document describes the watchdog that is monitoring the
autoresearch paper pipeline for topic **${TOPIC_SLUG}** at tier
**${TIER}**.

## What is monitoring

- **Hourly cron**: \`${CRON_NAME}\` (agent \`${AGENT_NAME}\`) runs every
  hour on the hour (Asia/Shanghai timezone). Each tick spawns a fresh
  session that patrols the plan directory and emits findings to
  \`watchdog-log.md\` in this directory.

- **Last-seen hook**: every tool invocation by a worker agent in
  this plan appends a timestamped line to
  \`last_seen.jsonl\` in this directory. The watchdog reads this
  on every patrol tick to detect staleness.

## What the watchdog watches

1. **Liveness** — every task's last_seen must be within 2× its
   expected wall-clock.
2. **Evaluator signal** — at experiment task completion, the
   watchdog checks whether the headline metric improvement is met.
3. **Reviewer-readiness** — at T11, the watchdog enforces the
   tier-specific threshold per dimension.
4. **Stuck tasks** — any task in \`running\` for more than 3× its
   expected wall-clock is flagged.

## How to interact manually

- **Ping the watchdog now** (force an out-of-band patrol) — v0.7.0+:
  \`mavis({ command: "cron trigger", args: { cron_id: "${AGENT_NAME}/${CRON_NAME}" } })\`
  (the legacy \`mavis cron trigger <agent> <name>\` CLI is removed; the
  native tool form is the supported way. As a fallback, touching the
  cron file at \`~/.mavis/agents/${AGENT_NAME}/crons/${CRON_NAME}.md\`
  bumps its mtime and the daemon will re-fire on its next tick).
- **Read recent findings**:
  \`cat ${PLAN_DIR}/watchdog-log.md | tail -40\`
- **Check last_seen freshness**:
  \`tail -20 ${PLAN_DIR}/last_seen.jsonl\`

## What to do if the watchdog reports an issue

The watchdog emits one of these recommendations per finding:

- \`wait\` — no action needed; the watchdog will re-check in 1 hour.
- \`steer\` — the worker task needs guidance; write a steer message to
  the worker via the plan owner's session using the native \`mavis\`
  tool (\`mavis communication send\` is removed in v0.7.0; use the
  owner's session API instead).
- \`cancel\` — the plan is unlikely to recover; ask the user before
  calling \`mavis team plan cancel\` (formerly \`abort\`).
- \`reopen\` — the task completed but the watchdog detected a
  problem; reopen the task in plan.yaml and re-run.
- \`escalate-to-human\` — the watchdog cannot decide; surface the
  finding to the human owner and wait.

The watchdog will **never auto-abort** or **never auto-edit** any
file. It only emits recommendations.

## Naming convention (for future reference)

- Agent name: \`${AGENT_NAME}\` (≤ 20 chars enforced by daemon)
- Cron name: \`${CRON_NAME}\`
- Hook name: \`${HOOK_FILE_NAME}.json\`

## Mac sleep caveat

If this Mac sleeps, the hourly cron does not fire. The watchdog
will resume patrols on next wake. For stronger liveness, bootstrap
with \`--rescue\`; the launchd-managed L0 guard patrols every 60s
and resumes on wake.
EOF

# ----- 7. Rescue Layer (v0.3.0+) — opt-in -----
#
# Installs launchd plist for plan-rescue-daemon.py (auto-judge paused plans
# via local Codex gpt-5.5 + xhigh). Skipped unless --rescue flag is passed
# OR \`$HOME/.mavis/agents/mavis/scripts/plan-rescue-daemon.py\` already exists
# (idempotent opt-in).
#
# v0.3.1+ also copies skill-bundled scripts from references/scripts/ to
# \`$HOME/.mavis/agents/mavis/scripts/\` so the skill is self-contained — no
# external user-scope script dependencies required for fresh installs.

if [[ "${RESCUE:-0}" == "1" ]] || [[ -f "${HOME}/.mavis/agents/mavis/scripts/plan-rescue-daemon.py" ]]; then
  # Step 6a: copy skill-bundled scripts to runtime path (idempotent)
  RUNTIME_SCRIPTS="${HOME}/.mavis/agents/mavis/scripts"
  mkdir -p "${RUNTIME_SCRIPTS}"
  if [[ -d "${SCRIPT_DIR}/scripts" ]]; then
    log "syncing Rescue Layer scripts: ${SCRIPT_DIR}/scripts -> ${RUNTIME_SCRIPTS}"
    for f in local_llm_judge.py plan-rescue-daemon.py plan-l0-guard.py cleanup-plan-resources.sh research-state-guard.py resolve-plan-dir.py register-plan-id.py pause-plan.sh resume-plan.sh stop-plan.sh; do
      if [[ -f "${SCRIPT_DIR}/scripts/${f}" ]]; then
        cp "${SCRIPT_DIR}/scripts/${f}" "${RUNTIME_SCRIPTS}/${f}"
        chmod +x "${RUNTIME_SCRIPTS}/${f}"
      fi
    done
  fi

  # Step 6b: copy launchd plist (prefer skill-bundled over user-scope copy)
  PLIST_DST="${HOME}/Library/LaunchAgents/com.mavis.plan-rescue-daemon.plist"
  PLIST_SRC=""
  if [[ -f "${SCRIPT_DIR}/launchd/com.mavis.plan-rescue-daemon.plist" ]]; then
    PLIST_SRC="${SCRIPT_DIR}/launchd/com.mavis.plan-rescue-daemon.plist"
  elif [[ -f "${HOME}/.mavis/agents/mavis/scripts/com.mavis.plan-rescue-daemon.plist" ]]; then
    PLIST_SRC="${HOME}/.mavis/agents/mavis/scripts/com.mavis.plan-rescue-daemon.plist"
  fi
  if [[ -n "${PLIST_SRC}" ]]; then
    log "installing Rescue Layer launchd plist from ${PLIST_SRC}"
    mkdir -p "$(dirname "${PLIST_DST}")"
    LOG_DIR="${HOME}/.mavis/agents/mavis/logs"
    mkdir -p "${LOG_DIR}"
    python3 - "${PLIST_SRC}" "${PLIST_DST}" "${HOME}" "${RUNTIME_SCRIPTS}" "${LOG_DIR}" <<'PY'
import os
import sys
from pathlib import Path

src, dst, home, runtime_scripts, log_dir = sys.argv[1:]
path_value = os.environ.get("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin")
text = Path(src).read_text()
replacements = {
    "{{HOME}}": home,
    "{{RUNTIME_SCRIPTS}}": runtime_scripts,
    "{{LOG_DIR}}": log_dir,
    "{{PATH}}": path_value,
}
for key, value in replacements.items():
    text = text.replace(key, value)
Path(dst).write_text(text)
PY
    launchctl load -w "${PLIST_DST}" 2>/dev/null || log "  launchctl load failed (may already be loaded)"
    log "  Rescue daemon will patrol every 60s (sleep-resilient)"
  else
    log "  no launchd plist found in ${SCRIPT_DIR}/launchd/ or ${HOME}/.mavis/agents/mavis/scripts/ — skipping"
  fi
else
  log "Rescue Layer not requested (pass --rescue to enable)"
fi

log "done."
log ""
log "Resources created:"
log "  - agent: ${AGENT_NAME}"
log "  - cron:  ${CRON_NAME}"
log "  - hook:  ${HOOK_FILE_NAME}.json"
log "  - doc:   ${WATCHDOG_DOC}"
if [[ "${RESCUE:-0}" == "1" ]]; then
  log "  - launchd plist: com.mavis.plan-rescue-daemon (Rescue Layer enabled)"
fi
log ""
log "Manual ping: mavis({ command: 'cron trigger', args: { cron_id: '${AGENT_NAME}/${CRON_NAME}' } })  # legacy 'mavis cron trigger' CLI removed in v0.7.0"
log "Read findings: cat ${PLAN_DIR}/watchdog-log.md"
log ""
log "Rescue Layer commands (if enabled):"
log "  pause-plan.sh <plan_id>     # soft pause"
log "  resume-plan.sh <plan_id>    # resume after pause"
log "  stop-plan.sh <plan_id>      # cancel + mark stopped_by_user"
log "  plan-rescue-daemon.py --once --dry-run  # preview without applying"
