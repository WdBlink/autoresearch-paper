#!/usr/bin/env bash
# bootstrap-watchdog.sh — one-shot setup of per-topic watchdog.
#
# Usage:
#   bootstrap-watchdog.sh <topic-slug> <tier> <plan-dir>
#
# Arguments:
#   topic-slug   kebab-case, e.g. "uav-coverage"
#   tier         arxiv | conference | journal-q1
#   plan-dir     absolute path to the plan output directory
#                (must contain watchdog-system-prompt.md already
#                filled in by the skill)
#
# What this script does, in order:
#   1. Verify preconditions (mavis CLI, plan-dir, prompt file).
#   2. Register an hourly cron task that, on each tick, spawns a fresh
#      session running the watchdog patrol (using --session-mode new).
#   3. Register a first-action-last-seen hook so every worker task
#      writes a timestamp to {plan-dir}/last_seen.jsonl on first tool
#      use.
#   4. Write {plan-dir}/WATCHDOG.md describing the watchdog setup and
#      how the user can manually ping it.
#
# Idempotent: re-running with the same arguments detects existing
# resources and skips creation (with a log line). Conflict on
# agent/cron name is resolved by appending a numeric suffix.

set -euo pipefail

if [[ $# -ne 3 ]]; then
  cat >&2 <<EOF
Usage: $0 <topic-slug> <tier> <plan-dir>

  topic-slug   kebab-case, e.g. "uav-coverage"
  tier         arxiv | conference | journal-q1
  plan-dir     absolute path to the plan output directory
EOF
  exit 2
fi

TOPIC_SLUG="$1"
TIER="$2"
PLAN_DIR="$3"

# Resolve script directory so we can find sibling reference files.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
HOOK_FILE="${SCRIPT_DIR}/first-action-last-seen.json"
WATCHDOG_DOC="${PLAN_DIR}/WATCHDOG.md"

log() { printf '[bootstrap-watchdog] %s\n' "$*" >&2; }
die() { printf '[bootstrap-watchdog][ERROR] %s\n' "$*" >&2; exit 1; }

# ----- 1. Preconditions -----------------------------------------------

command -v mavis >/dev/null 2>&1 || die "mavis CLI not found in PATH"
[[ -d "${PLAN_DIR}" ]] || die "plan-dir does not exist: ${PLAN_DIR}"
[[ -f "${PROMPT_FILE}" ]] || die "watchdog prompt not found: ${PROMPT_FILE} (the skill must write it before running this script)"
[[ -f "${HOOK_FILE}" ]] || die "hook file not found: ${HOOK_FILE}"

case "${TIER}" in
  arxiv|conference|journal-q1) ;;
  *) die "tier must be one of: arxiv, conference, journal-q1 (got: ${TIER})" ;;
esac

# ----- 2. Watchdog agent (must exist before cron) --------------------
#
# `mavis cron create` requires the agent to already be registered.
# We register it here with `mavis agent new` using the watchdog system
# prompt as the agent's system prompt. This makes the watchdog a
# first-class Mavis agent with hourly cron-driven patrols.

log "creating agent: ${AGENT_NAME} (display: ${TOPIC_SLUG} paper watchdog)"

PROMPT_BODY="$(cat "${PROMPT_FILE}")"

# `display-name` and `description` are both capped at 20 chars by the
# Mavis daemon (validation error 40002 — same constraint as agent
# name). Truncate the human-readable labels to fit.
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

# shellcheck disable=SC2086
mavis agent new "${AGENT_NAME}" \
  --display-name "${DISPLAY_NAME}" \
  --description "${DESCRIPTION}" \
  --system-prompt "${PROMPT_BODY}" \
  --persona "${PERSONA}" \
  || log "  agent create failed (likely already exists) — skipping"

# ----- 3. Hourly cron --------------------------------------------------
#
# Each cron tick creates a fresh session (--session-mode new) and sends
# the watchdog system prompt. The session runs the patrol procedure,
# emits findings to {PLAN_DIR}/watchdog-log.md, and exits. No persistent
# session means no per-session context bloat.
#
# --keep-sessions 5 limits visible sessions to the most recent 5 patrols,
# so the agent's session list does not grow unbounded.

log "creating hourly cron: ${CRON_NAME}"
log "  schedule: 0 * * * *"
log "  session-mode: new"
log "  agent: ${AGENT_NAME}"

# shellcheck disable=SC2086  # CRON_NAME is intentionally positional
mavis cron create "${AGENT_NAME}" "${CRON_NAME}" \
  --schedule "0 * * * *" \
  --prompt "Hourly watchdog patrol for ${TOPIC_SLUG} (tier=${TIER}). Run the patrol procedure described in your system prompt. Read \${PLAN_DIR}/last_seen.jsonl and \${PLAN_DIR}/watchdog-log.md, emit findings." \
  --session-mode new \
  --keep-sessions 5 \
  --timezone "Asia/Shanghai" || \
  log "  cron create failed (likely already exists) — skipping"

# ----- 4. First-action-last-seen hook ---------------------------------
#
# PostToolUse hook that, on every tool invocation by any worker agent
# in this plan, appends a line to {PLAN_DIR}/last_seen.jsonl. This is
# how the watchdog detects liveness — if a task has not invoked a tool
# in 2× its expected wall-clock, the watchdog flags it as stale.

log "creating hook: ${HOOK_FILE_NAME}.json"
log "  event: PostToolUse"

HOOK_BODY="$(cat "${HOOK_FILE}")"

# shellcheck disable=SC2086
mavis hook create "${HOOK_FILE_NAME}.json" \
  -e PostToolUse \
  -t script \
  --body "${HOOK_BODY}" \
  --matcher '^(Read|Write|Edit|Bash)$' \
  --timeout 5000 || \
  log "  hook create failed (likely already exists) — skipping"

# ----- 5. WATCHDOG.md --------------------------------------------------
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

- **Ping the watchdog now** (force an out-of-band patrol):
  \`mavis cron trigger ${AGENT_NAME} ${CRON_NAME}\`
- **Read recent findings**:
  \`cat ${PLAN_DIR}/watchdog-log.md | tail -40\`
- **Check last_seen freshness**:
  \`tail -20 ${PLAN_DIR}/last_seen.jsonl\`

## What to do if the watchdog reports an issue

The watchdog emits one of these recommendations per finding:

- \`wait\` — no action needed; the watchdog will re-check in 1 hour.
- \`steer\` — the worker task needs guidance; reply to the worker
  via \`mavis communication send\` with a steer message.
- \`abort\` — the plan is unlikely to recover; ask the user before
  calling \`mavis team plan abort\`.
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
will resume patrols on next wake. If you need hardened liveness,
re-bootstrap with \`--mode=hardened\` (not yet implemented in v0.1).
EOF

# ----- 6. Rescue Layer (v0.3.0+) — opt-in -----
#
# Installs launchd plist for plan-rescue-daemon.py (auto-judge paused plans
# via local Codex gpt-5.5 + xhigh). Skipped unless --rescue flag is passed
# OR \`~/.mavis/agents/mavis/scripts/plan-rescue-daemon.py\` already exists
# (idempotent opt-in).

if [[ "${RESCUE:-0}" == "1" ]] || [[ -f "${HOME}/.mavis/agents/mavis/scripts/plan-rescue-daemon.py" ]]; then
  PLIST_SRC="${HOME}/.mavis/agents/mavis/scripts/com.mavis.plan-rescue-daemon.plist"
  PLIST_DST="${HOME}/Library/LaunchAgents/com.mavis.plan-rescue-daemon.plist"
  if [[ -f "${PLIST_SRC}" ]]; then
    log "installing Rescue Layer launchd plist"
    cp "${PLIST_SRC}" "${PLIST_DST}"
    launchctl load -w "${PLIST_DST}" 2>/dev/null || log "  launchctl load failed (may already be loaded)"
    log "  Rescue daemon will patrol every 60s (sleep-resilient)"
  else
    log "  rescue scripts not found at ${PLIST_SRC} — skipping Rescue Layer install"
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
log "Manual ping: mavis cron trigger ${AGENT_NAME} ${CRON_NAME}"
log "Read findings: cat ${PLAN_DIR}/watchdog-log.md"
log ""
log "Rescue Layer commands (if enabled):"
log "  pause-plan.sh <plan_id>     # soft pause"
log "  resume-plan.sh <plan_id>    # resume after pause"
log "  stop-plan.sh <plan_id>      # cancel + mark stopped_by_user"
log "  plan-rescue-daemon.py --once --dry-run  # preview without applying"