#!/usr/bin/env bash
# resume-plan.sh <plan_id> — resume a paused plan.
#
# Removes pause_requested.json and writes resume_signal.json. The rescue
# daemon detects resume_signal.json on its next patrol cycle and resumes the
# plan via `mavis team plan resume`.
#
# Usage: resume-plan.sh <plan_id>

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <plan_id>" >&2
  exit 2
fi

PLAN_ID="$1"
PLAN_DIR="${HOME}/.mavis/plans/${PLAN_ID}"

if [[ ! -d "$PLAN_DIR" ]]; then
  echo "ERROR: plan dir not found: $PLAN_DIR" >&2
  exit 1
fi

rm -f "${PLAN_DIR}/pause_requested.json" 2>/dev/null || true

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "${PLAN_DIR}/resume_signal.json" <<EOF
{
  "ts": "${NOW}",
  "requested_by": "$(whoami)",
  "session": "${MAVIS_SESSION_ID:-unknown}"
}
EOF

echo "[resume-plan] ${PLAN_ID}: resume signal written at ${NOW}"
echo "[resume-plan] rescue daemon will detect within ${RESCUE_INTERVAL:-60}s and resume the plan"

# Trigger resume immediately if engine is paused
if mavis team plan status "$PLAN_ID" 2>&1 | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    s = d.get('state', d)
    print('yes' if s.get('status') == 'paused' else 'no')
except:
    print('error')
" | grep -q "yes"; then
  mavis team plan resume "$PLAN_ID" 2>&1 | head -5
  echo "[resume-plan] engine resumed"
fi