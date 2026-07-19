#!/usr/bin/env bash
# Authenticated target-runtime resume; MAVIS repair is opt-in compatibility.
set -euo pipefail
if [[ $# -lt 5 ]]; then
  echo "Usage: $0 <plan_id|plan_dir> --record <signed-record.json> --key-file <key> [--legacy-mavis]" >&2
  exit 2
fi
TARGET="$1"; shift
RECORD=""; KEY_FILE=""; LEGACY_MAVIS=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --record) RECORD="${2:-}"; shift 2 ;;
    --key-file) KEY_FILE="${2:-}"; shift 2 ;;
    --legacy-mavis) LEGACY_MAVIS=1; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done
[[ -n "${RECORD}" && -n "${KEY_FILE}" ]] || { echo "--record and --key-file are required" >&2; exit 2; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAN_DIR="$(python3 "${SCRIPT_DIR}/resolve-plan-dir.py" "${TARGET}")"
python3 "${SCRIPT_DIR}/harness-runtime.py" apply-human-action \
  --plan-dir "${PLAN_DIR}" --record "${RECORD}" --key-file "${KEY_FILE}" --expected-action resume
if [[ "${LEGACY_MAVIS}" == "1" ]]; then
  python3 "${SCRIPT_DIR}/plan-l0-guard.py" --plan-dir "${PLAN_DIR}" --once --repair-resources --legacy-mavis
fi
