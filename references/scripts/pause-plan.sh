#!/usr/bin/env bash
# pause-plan.sh <plan_id|plan_dir> — request pause for an autoresearch plan.
#
# Writes control/pause_requested.json to the plan directory. The rescue daemon detects
# this on its next patrol cycle and stops spawning new task producers. Existing
# active workers finish their current cycle, then the engine idles.
#
# State on resume:
#   - plan/state.json keeps last good snapshot
#   - plan/resume_signal.json (created by resume-plan.sh) tells rescue daemon to restart
#
# Usage: pause-plan.sh <plan_id|plan_dir>

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <plan_id|plan_dir>" >&2
  echo "Example: $0 plan_cdefc387" >&2
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

CHECKPOINT_CYCLE="$(python3 - "${PLAN_DIR}/state.json" <<'PY'
import json
import sys
from pathlib import Path

try:
    data = json.loads(Path(sys.argv[1]).read_text())
    state = data.get("state", data)
    print(state.get("cycle", 0))
except Exception:
    print(0)
PY
)"

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 - "${PLAN_DIR}/control/pause_requested.json" "${NOW}" "$(whoami)" "${MAVIS_SESSION_ID:-unknown}" "${CHECKPOINT_CYCLE}" <<'PY'
import json, sys
from pathlib import Path

path, now, user, session, cycle = sys.argv[1:]
Path(path).write_text(json.dumps({
    "ts": now,
    "requested_by": user,
    "session": session,
    "reason": "user requested pause",
    "checkpoint_at_cycle": int(cycle),
}, indent=2) + "\n")
PY
cp "${PLAN_DIR}/control/pause_requested.json" "${PLAN_DIR}/pause_requested.json"

python3 - "${PLAN_DIR}/state/control_history.jsonl" "${NOW}" "${CHECKPOINT_CYCLE}" <<'PY'
import json, sys
from pathlib import Path

path, now, cycle = sys.argv[1:]
with Path(path).open("a") as f:
    f.write(json.dumps({"ts": now, "action": "pause", "checkpoint_at_cycle": int(cycle)}) + "\n")
PY

echo "[pause-plan] ${PLAN_ID}: pause requested at ${NOW}"
echo "[pause-plan] rescue daemon will detect within ${RESCUE_INTERVAL:-60}s and stop spawning"
echo "[pause-plan] to resume: resume-plan.sh ${PLAN_ID}"
