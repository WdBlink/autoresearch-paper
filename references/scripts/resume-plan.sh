#!/usr/bin/env bash
# resume-plan.sh <plan_id|plan_dir> — resume a paused plan.
#
# Removes pause_requested.json and writes control/resume_signal.json. The rescue
# daemon detects resume_signal.json on its next patrol cycle and resumes the
# plan via `mavis team plan resume`.
#
# Usage: resume-plan.sh <plan_id|plan_dir>

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <plan_id|plan_dir>" >&2
  exit 2
fi

TARGET="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVER="${SCRIPT_DIR}/resolve-plan-dir.py"
if [[ -x "${RESOLVER}" ]]; then
  PLAN_DIR="$(python3 "${RESOLVER}" "${TARGET}")"
elif [[ -d "${TARGET}" ]]; then
  PLAN_DIR="$(cd "${TARGET}" && pwd)"
else
  PLAN_DIR="${HOME}/.mavis/plans/${TARGET}"
fi
PLAN_ID="$(python3 - "${PLAN_DIR}" "${TARGET}" <<'PY'
import json, sys
from pathlib import Path
plan_dir = Path(sys.argv[1])
target = sys.argv[2]
try:
    manifest = json.loads((plan_dir / "resource_manifest.json").read_text())
    print(manifest.get("plan_id") or target)
except Exception:
    print(target)
PY
)"

if [[ ! -d "$PLAN_DIR" ]]; then
  echo "ERROR: plan dir not found: $PLAN_DIR" >&2
  exit 1
fi

mkdir -p "${PLAN_DIR}/control" "${PLAN_DIR}/state"

rm -f \
  "${PLAN_DIR}/pause_requested.json" \
  "${PLAN_DIR}/control/pause_requested.json" \
  "${PLAN_DIR}/state/pause_requested.json" \
  2>/dev/null || true

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 - "${PLAN_DIR}/control/resume_signal.json" "${NOW}" "$(whoami)" "${MAVIS_SESSION_ID:-unknown}" <<'PY'
import json, sys
from pathlib import Path

path, now, user, session = sys.argv[1:]
Path(path).write_text(json.dumps({
    "ts": now,
    "requested_by": user,
    "session": session,
}, indent=2) + "\n")
PY
cp "${PLAN_DIR}/control/resume_signal.json" "${PLAN_DIR}/resume_signal.json"

python3 - "${PLAN_DIR}/state/control_history.jsonl" "${NOW}" <<'PY'
import json, sys
from pathlib import Path

path, now = sys.argv[1:]
with Path(path).open("a") as f:
    f.write(json.dumps({"ts": now, "action": "resume"}) + "\n")
PY

echo "[resume-plan] ${PLAN_ID}: resume signal written at ${NOW}"
echo "[resume-plan] rescue daemon will detect within ${RESCUE_INTERVAL:-60}s and resume the plan"

if [[ -x "${SCRIPT_DIR}/plan-l0-guard.py" ]]; then
  python3 "${SCRIPT_DIR}/plan-l0-guard.py" --plan-dir "${PLAN_DIR}" --once --repair-resources >/dev/null 2>&1 || \
    echo "[resume-plan] warning: L0 resource health check failed; see state/watchdog_health.json"
fi

# Trigger resume immediately if engine is paused
if command -v mavis >/dev/null 2>&1 && mavis team plan status "$PLAN_ID" 2>&1 | python3 -c "
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
