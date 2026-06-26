#!/usr/bin/env bash
# stop-plan.sh <plan_id|plan_dir> — forcefully stop a plan and mark it stopped.
#
# Writes control/stop_requested.json, asks the plan engine to cancel, then
# runs cleanup-plan-resources.sh. The cleanup script deletes run-scoped
# crons, hooks, temporary agents/sessions, processes, and locks recorded in
# resource_manifest.json.
#
# State after stop:
#   - state/stop_history.jsonl appended with timestamp
#   - resource_manifest.json status = stopped_cleaned or stopped_with_residuals
#   - cleanup_report.md names all cleaned and residual runtime resources
#
# Usage: stop-plan.sh <plan_id|plan_dir> [--reason <text>]

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <plan_id|plan_dir> [--reason <text>]" >&2
  exit 2
fi

TARGET="$1"
REASON="user requested stop"
shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reason)
      if [[ $# -lt 2 ]]; then
        echo "--reason requires an argument" >&2
        exit 2
      fi
      REASON="$2"
      shift 2
      ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

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

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 - "${PLAN_DIR}/control/stop_requested.json" "${NOW}" "$(whoami)" "${MAVIS_SESSION_ID:-unknown}" "${REASON}" <<'PY'
import json, sys
from pathlib import Path

path, now, user, session, reason = sys.argv[1:]
Path(path).write_text(json.dumps({
    "ts": now,
    "requested_by": user,
    "session": session,
    "reason": reason,
}, indent=2) + "\n")
PY
cp "${PLAN_DIR}/control/stop_requested.json" "${PLAN_DIR}/stop_requested.json"

# Append to stop history
python3 - "${PLAN_DIR}/state/stop_history.jsonl" "${NOW}" "${REASON}" <<'PY'
import json, sys
from pathlib import Path

path, now, reason = sys.argv[1:]
with Path(path).open("a") as f:
    f.write(json.dumps({"ts": now, "reason": reason}) + "\n")
PY

echo "[stop-plan] ${PLAN_ID}: stop requested at ${NOW} (reason: ${REASON})"
if command -v mavis >/dev/null 2>&1; then
  mavis team plan cancel "${PLAN_ID}" >/dev/null 2>&1 || true
fi

CLEANUP_SCRIPT="${SCRIPT_DIR}/cleanup-plan-resources.sh"
if [[ -x "${CLEANUP_SCRIPT}" ]]; then
  "${CLEANUP_SCRIPT}" "${PLAN_DIR}" --reason "${REASON}" --mode stop
  echo "[stop-plan] cleanup report: ${PLAN_DIR}/cleanup_report.md"
else
  echo "[stop-plan] WARNING: cleanup script not found/executable: ${CLEANUP_SCRIPT}" >&2
  echo "[stop-plan] rescue daemon will still detect within ${RESCUE_INTERVAL:-60}s and attempt cleanup"
fi
