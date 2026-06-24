#!/usr/bin/env bash
# stop-plan.sh <plan_id> — forcefully stop a plan and mark it stopped.
#
# Writes stop_requested.json; rescue daemon cancels the plan and marks the
# state with status="stopped_by_user". Cleans up active cron entries (best
# effort — manual cleanup may still be required for cron / hook).
#
# State after stop:
#   - plan/state.json status = "stopped_by_user"
#   - state/stop_history.jsonl appended with timestamp
#   - any active workers killed by rescue daemon
#
# Usage: stop-plan.sh <plan_id> [--reason <text>]

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <plan_id> [--reason <text>]" >&2
  exit 2
fi

PLAN_ID="$1"
REASON="user requested stop"
shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reason) REASON="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

PLAN_DIR="${HOME}/.mavis/plans/${PLAN_ID}"

if [[ ! -d "$PLAN_DIR" ]]; then
  echo "ERROR: plan dir not found: $PLAN_DIR" >&2
  exit 1
fi

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "${PLAN_DIR}/stop_requested.json" <<EOF
{
  "ts": "${NOW}",
  "requested_by": "$(whoami)",
  "session": "${MAVIS_SESSION_ID:-unknown}",
  "reason": "${REASON}"
}
EOF

# Append to stop history
cat >> "${PLAN_DIR}/state/stop_history.jsonl" 2>/dev/null <<EOF
{"ts":"${NOW}","reason":"${REASON}"}
EOF
# Ensure state/ dir exists
mkdir -p "${PLAN_DIR}/state"
cat >> "${PLAN_DIR}/state/stop_history.jsonl" <<EOF
{"ts":"${NOW}","reason":"${REASON}"}
EOF

echo "[stop-plan] ${PLAN_ID}: stop requested at ${NOW} (reason: ${REASON})"
echo "[stop-plan] rescue daemon will detect within ${RESCUE_INTERVAL:-60}s and cancel"
echo "[stop-plan] active workers will be killed and plan status set to 'stopped_by_user'"