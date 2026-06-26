#!/usr/bin/env bash
# cleanup-plan-resources.sh — best-effort cleanup for one autoresearch plan.
#
# Usage:
#   cleanup-plan-resources.sh <plan_id|plan_dir> [--reason <text>] [--mode stop|abort|complete|cleanup] [--dry-run]
#
# The script reads <plan-dir>/resource_manifest.json and deletes only
# resources marked ephemeral=true or run_scoped=true. It preserves outputs,
# state, and logs, then writes cleanup_report.md and appends
# state/cleanup_history.jsonl.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <plan_id|plan_dir> [--reason <text>] [--mode stop|abort|complete|cleanup] [--dry-run]" >&2
  exit 2
fi

TARGET="$1"
shift
REASON="cleanup requested"
DRY_RUN=0
MODE="stop"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reason)
      REASON="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --mode)
      MODE="${2:-}"
      case "${MODE}" in
        stop|abort|complete|cleanup) ;;
        *) echo "Invalid --mode: ${MODE}" >&2; exit 2 ;;
      esac
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVER="${SCRIPT_DIR}/resolve-plan-dir.py"

if [[ -x "${RESOLVER}" ]]; then
  PLAN_DIR="$(python3 "${RESOLVER}" "${TARGET}" 2>/dev/null || true)"
  if [[ -n "${PLAN_DIR}" ]]; then
    PLAN_ID="${TARGET}"
  fi
fi

if [[ -z "${PLAN_DIR:-}" && -d "${TARGET}" ]]; then
  PLAN_DIR="$(cd "${TARGET}" && pwd)"
  PLAN_ID="$(basename "${PLAN_DIR}")"
elif [[ -z "${PLAN_DIR:-}" ]]; then
  PLAN_ID="${TARGET}"
  PLAN_DIR="${HOME}/.mavis/plans/${PLAN_ID}"
fi

if [[ -f "${PLAN_DIR}/resource_manifest.json" ]]; then
  PLAN_ID="$(python3 - "${PLAN_DIR}" "${PLAN_ID}" <<'PY'
import json, sys
from pathlib import Path
plan_dir = Path(sys.argv[1])
fallback = sys.argv[2]
try:
    manifest = json.loads((plan_dir / "resource_manifest.json").read_text())
    print(manifest.get("plan_id") or fallback)
except Exception:
    print(fallback)
PY
)"
fi

if [[ ! -d "${PLAN_DIR}" ]]; then
  echo "ERROR: plan dir not found: ${PLAN_DIR}" >&2
  exit 1
fi

STATE_DIR="${PLAN_DIR}/state"
CONTROL_DIR="${PLAN_DIR}/control"
MANIFEST="${PLAN_DIR}/resource_manifest.json"
REPORT="${PLAN_DIR}/cleanup_report.md"
HISTORY="${STATE_DIR}/cleanup_history.jsonl"

mkdir -p "${STATE_DIR}" "${CONTROL_DIR}"

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

log() { printf '[cleanup-plan] %s\n' "$*" >&2; }
record() { printf '%s\n' "$*" >> "${TMP_DIR}/actions.log"; }
residual() { printf '%s\n' "$*" >> "${TMP_DIR}/residuals.log"; }

json_field() {
  local field="$1"
  python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d.get(sys.argv[1], ""))' "${field}"
}

json_bool() {
  local field="$1"
  local default="${2:-false}"
  python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(str(d.get(sys.argv[1], sys.argv[2].lower()=="true")).lower())' "${field}" "${default}"
}

run_cmd() {
  local label="$1"
  shift
  if [[ "${DRY_RUN}" == "1" ]]; then
    record "DRY-RUN ${label}: $*"
    return 0
  fi
  if "$@" >> "${TMP_DIR}/command.out" 2>> "${TMP_DIR}/command.err"; then
    record "OK ${label}: $*"
    return 0
  fi
  local code=$?
  record "FAIL ${label}: $* (exit ${code})"
  residual "${label}: $*"
  return 0
}

if [[ ! -f "${MANIFEST}" ]]; then
  cat > "${MANIFEST}" <<EOF
{
  "schema_version": 1,
  "plan_id": "${PLAN_ID}",
  "plan_dir": "${PLAN_DIR}",
  "status": "unknown_no_manifest",
  "agents": [],
  "sessions": [],
  "crons": [],
  "hooks": [],
  "launchd": [],
  "local_processes": [],
  "remote_processes": [],
  "locks": []
}
EOF
  record "WARN manifest missing; wrote empty manifest at ${MANIFEST}"
fi

python3 - "$MANIFEST" "$TMP_DIR/resources.jsonl" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
out = Path(sys.argv[2])

def items(kind):
    value = manifest.get(kind, [])
    return value if isinstance(value, list) else []

with out.open("w") as f:
    for kind in ("local_processes", "remote_processes", "crons", "hooks", "launchd", "sessions", "agents", "locks"):
        for item in items(kind):
            if isinstance(item, str):
                item = {"name": item}
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item["_kind"] = kind
            f.write(json.dumps(item) + "\n")
PY

# 1. Mark stop/cleanup intent before touching runtime resources.
python3 - "${CONTROL_DIR}/cleanup_requested.json" "${NOW}" "$(whoami)" "${REASON}" "${MODE}" "${DRY_RUN}" <<'PY'
import json
import sys
from pathlib import Path

path, now, user, reason, mode, dry_run = sys.argv[1:]
Path(path).write_text(json.dumps({
    "ts": now,
    "requested_by": user,
    "reason": reason,
    "mode": mode,
    "dry_run": dry_run == "1",
}, indent=2) + "\n")
PY

# 2. Ask plan engine to stop/cancel when possible.
if command -v mavis >/dev/null 2>&1 && [[ "${PLAN_ID}" == plan_* ]]; then
  run_cmd "plan-cancel" mavis team plan cancel "${PLAN_ID}"
fi

while IFS= read -r line; do
  [[ -n "${line}" ]] || continue
  kind="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("_kind",""))' <<<"${line}")"
  case "${kind}" in
    local_processes)
      ephemeral="$(json_bool ephemeral false <<<"${line}")"
      if [[ "${ephemeral}" != "true" ]]; then
        label="$(json_field label <<<"${line}")"
        record "OK local-process:${label:-unknown}: non-ephemeral; left in place"
        continue
      fi
      pid="$(json_field pid <<<"${line}")"
      label="$(json_field label <<<"${line}")"
      label="${label:-local-process}"
      if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
        run_cmd "local-process:${label}" kill -TERM "${pid}"
        sleep 1
        if kill -0 "${pid}" 2>/dev/null; then
          run_cmd "local-process-force:${label}" kill -KILL "${pid}"
        fi
      else
        record "OK local-process:${label}: not running"
      fi
      ;;
    remote_processes)
      ephemeral="$(json_bool ephemeral false <<<"${line}")"
      if [[ "${ephemeral}" != "true" ]]; then
        label="$(json_field label <<<"${line}")"
        record "OK remote-process:${label:-unknown}: non-ephemeral; left in place"
        continue
      fi
      host="$(json_field host <<<"${line}")"
      pid="$(json_field pid <<<"${line}")"
      label="$(json_field label <<<"${line}")"
      label="${label:-remote-process}"
      if [[ -n "${host}" && -n "${pid}" ]]; then
        run_cmd "remote-process:${label}" ssh "${host}" "kill -TERM ${pid} 2>/dev/null || true"
      else
        residual "remote-process:${label}: missing host or pid"
      fi
      ;;
    crons)
      ephemeral="$(json_bool ephemeral false <<<"${line}")"
      if [[ "${ephemeral}" != "true" ]]; then
        name="$(json_field name <<<"${line}")"
        record "OK cron:${name:-unknown}: non-ephemeral; left in place"
        continue
      fi
      if ! command -v mavis >/dev/null 2>&1; then
        residual "cron: mavis CLI unavailable"
        continue
      fi
      agent="$(json_field agent <<<"${line}")"
      name="$(json_field name <<<"${line}")"
      if [[ -n "${agent}" && -n "${name}" ]]; then
        run_cmd "cron:${agent}/${name}" mavis cron delete "${agent}" "${name}"
      else
        residual "cron: missing agent or name"
      fi
      ;;
    hooks)
      ephemeral="$(json_bool ephemeral false <<<"${line}")"
      if [[ "${ephemeral}" != "true" ]]; then
        name="$(json_field name <<<"${line}")"
        record "OK hook:${name:-unknown}: non-ephemeral; left in place"
        continue
      fi
      if ! command -v mavis >/dev/null 2>&1; then
        residual "hook: mavis CLI unavailable"
        continue
      fi
      name="$(json_field name <<<"${line}")"
      if [[ -n "${name}" ]]; then
        run_cmd "hook:${name}" mavis hook delete "${name}"
      else
        residual "hook: missing name"
      fi
      ;;
    launchd)
      run_scoped="$(json_bool run_scoped false <<<"${line}")"
      plist="$(python3 -c 'import json,os,sys; p=json.loads(sys.stdin.read()).get("plist",""); print(os.path.expanduser(p))' <<<"${line}")"
      label="$(json_field label <<<"${line}")"
      label="${label:-launchd}"
      if [[ "${run_scoped}" == "true" && -n "${plist}" && -f "${plist}" ]]; then
        run_cmd "launchd-unload:${label}" launchctl unload -w "${plist}"
        run_cmd "launchd-remove:${label}" rm -f "${plist}"
      else
        record "OK launchd:${label}: shared or missing; left in place"
      fi
      ;;
    sessions)
      if ! command -v mavis >/dev/null 2>&1; then
        residual "session: mavis CLI unavailable"
        continue
      fi
      ephemeral="$(json_bool ephemeral false <<<"${line}")"
      name="$(python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d.get("id") or d.get("name") or "")' <<<"${line}")"
      if [[ "${ephemeral}" == "true" && -n "${name}" ]]; then
        run_cmd "session:${name}" mavis session archive "${name}"
      else
        record "OK session:${name:-unknown}: non-ephemeral or unnamed; left in place"
      fi
      ;;
    agents)
      if ! command -v mavis >/dev/null 2>&1; then
        residual "agent: mavis CLI unavailable"
        continue
      fi
      ephemeral="$(json_bool ephemeral false <<<"${line}")"
      name="$(json_field name <<<"${line}")"
      if [[ "${ephemeral}" == "true" && -n "${name}" ]]; then
        run_cmd "agent-archive:${name}" mavis agent archive "${name}"
      else
        record "OK agent:${name:-unknown}: non-ephemeral or unnamed; left in place"
      fi
      ;;
    locks)
      ephemeral="$(json_bool ephemeral false <<<"${line}")"
      if [[ "${ephemeral}" != "true" ]]; then
        path="$(json_field path <<<"${line}")"
        record "OK lock:${path:-unknown}: non-ephemeral; left in place"
        continue
      fi
      path="$(python3 -c 'import json,os,sys; print(os.path.expanduser(json.loads(sys.stdin.read()).get("path","")))' <<<"${line}")"
      if [[ -n "${path}" && "${path}" == "${PLAN_DIR}"* ]]; then
        run_cmd "lock:${path}" rm -f "${path}"
      elif [[ -n "${path}" ]]; then
        residual "lock outside plan dir skipped: ${path}"
      fi
      ;;
  esac
done < "${TMP_DIR}/resources.jsonl"

RESIDUAL_COUNT=0
if [[ -f "${TMP_DIR}/residuals.log" ]]; then
  RESIDUAL_COUNT="$(wc -l < "${TMP_DIR}/residuals.log" | tr -d ' ')"
fi

if [[ "${DRY_RUN}" == "1" ]]; then
  STATUS="cleanup_dry_run"
elif [[ "${RESIDUAL_COUNT}" == "0" ]]; then
  case "${MODE}" in
    stop) STATUS="stopped_cleaned" ;;
    abort) STATUS="aborted_cleaned" ;;
    complete) STATUS="completed_cleaned" ;;
    cleanup) STATUS="cleaned" ;;
  esac
else
  case "${MODE}" in
    stop) STATUS="stopped_with_residuals" ;;
    abort) STATUS="aborted_with_residuals" ;;
    complete) STATUS="completed_with_residuals" ;;
    cleanup) STATUS="cleanup_with_residuals" ;;
  esac
fi

python3 - "$MANIFEST" "$STATUS" "$NOW" "$REASON" "$RESIDUAL_COUNT" "$MODE" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text())
data["status"] = sys.argv[2]
data["updated_at"] = sys.argv[3]
data["cleanup_reason"] = sys.argv[4]
data["cleanup_residual_count"] = int(sys.argv[5])
data["cleanup_mode"] = sys.argv[6]
path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
PY

if [[ "${DRY_RUN}" != "1" ]]; then
  python3 - "${PLAN_DIR}" "${NOW}" <<'PY'
from pathlib import Path
import shutil
import sys

plan_dir = Path(sys.argv[1])
stamp = sys.argv[2].replace(":", "").replace("-", "")
handled = plan_dir / "control" / "handled"
handled.mkdir(parents=True, exist_ok=True)
for name in ("stop_requested.json", "pause_requested.json", "resume_signal.json"):
    for path in (plan_dir / "control" / name, plan_dir / "state" / name, plan_dir / name):
        if path.exists():
            dest = handled / f"{stamp}-{path.parent.name}-{name}"
            shutil.move(str(path), str(dest))
PY
fi

{
  echo "# Cleanup Report"
  echo
  echo "- plan_id: \`${PLAN_ID}\`"
  echo "- plan_dir: \`${PLAN_DIR}\`"
  echo "- timestamp: \`${NOW}\`"
  echo "- reason: ${REASON}"
  echo "- mode: \`${MODE}\`"
  echo "- status: \`${STATUS}\`"
  echo "- dry_run: \`${DRY_RUN}\`"
  echo
  echo "## Actions"
  if [[ -f "${TMP_DIR}/actions.log" ]]; then
    sed 's/^/- /' "${TMP_DIR}/actions.log"
  else
    echo "- No runtime resources were listed in the manifest."
  fi
  echo
  echo "## Residuals"
  if [[ -f "${TMP_DIR}/residuals.log" ]]; then
    sed 's/^/- /' "${TMP_DIR}/residuals.log"
  else
    echo "- None."
  fi
} > "${REPORT}"

python3 - "$HISTORY" "$NOW" "$PLAN_ID" "$STATUS" "$REASON" "$RESIDUAL_COUNT" "$MODE" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
entry = {
    "ts": sys.argv[2],
    "plan_id": sys.argv[3],
    "status": sys.argv[4],
    "mode": sys.argv[7],
    "reason": sys.argv[5],
    "residual_count": int(sys.argv[6]),
}
with path.open("a") as f:
    f.write(json.dumps(entry) + "\n")
PY

log "${PLAN_ID}: ${STATUS}; report=${REPORT}"
if [[ "${RESIDUAL_COUNT}" != "0" ]]; then
  log "residual runtime resources remain; see ${REPORT}"
fi
