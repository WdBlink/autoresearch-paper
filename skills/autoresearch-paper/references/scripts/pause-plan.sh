#!/usr/bin/env bash
# Authenticated compatibility wrapper for a target-runtime pause.
set -euo pipefail
if [[ $# -ne 5 || "$2" != "--record" || "$4" != "--key-file" ]]; then
  echo "Usage: $0 <plan_id|plan_dir> --record <signed-record.json> --key-file <key>" >&2
  exit 2
fi
TARGET="$1"; RECORD="$3"; KEY_FILE="$5"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAN_DIR="$(python3 "${SCRIPT_DIR}/resolve-plan-dir.py" "${TARGET}")"
python3 "${SCRIPT_DIR}/harness-runtime.py" apply-human-action \
  --plan-dir "${PLAN_DIR}" --record "${RECORD}" --key-file "${KEY_FILE}" --expected-action pause
