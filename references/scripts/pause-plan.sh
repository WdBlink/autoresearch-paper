#!/usr/bin/env bash
# pause-plan.sh <plan_id> — request pause for an autoresearch plan.
#
# Writes pause_requested.json to the plan directory. The rescue daemon detects
# this on its next patrol cycle and stops spawning new task producers. Existing
# active workers finish their current cycle, then the engine idles.
#
# State on resume:
#   - plan/state.json keeps last good snapshot
#   - plan/resume_signal.json (created by resume-plan.sh) tells rescue daemon to restart
#
# Usage: pause-plan.sh <plan_id>

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <plan_id>" >&2
  echo "Example: $0 plan_cdefc387" >&2
  exit 2
fi

PLAN_ID="$1"
PLAN_DIR="${HOME}/.mavis/plans/${PLAN_ID}"

if [[ ! -d "$PLAN_DIR" ]]; then
  echo "ERROR: plan dir not found: $PLAN_DIR" >&2
  exit 1
fi

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "${PLAN_DIR}/pause_requested.json" <<EOF
{
  "ts": "${NOW}",
  "requested_by": "$(whoami)",
  "session": "${MAVIS_SESSION_ID:-unknown}",
  "reason": "user requested pause",
  "checkpoint_at_cycle": $(jq -r '.state.cycle // 0' "${PLAN_DIR}/state.json" 2>/dev/null || echo 0)
}
EOF

echo "[pause-plan] ${PLAN_ID}: pause requested at ${NOW}"
echo "[pause-plan] rescue daemon will detect within ${RESCUE_INTERVAL:-60}s and stop spawning"
echo "[pause-plan] to resume: resume-plan.sh ${PLAN_ID}"