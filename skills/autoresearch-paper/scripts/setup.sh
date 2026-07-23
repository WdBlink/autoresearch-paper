#!/usr/bin/env bash
# Verify dependencies for the autoresearch-paper skill.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-check}"

ok() { printf '[autoresearch-paper/setup] ok: %s\n' "$*"; }
warn() { printf '[autoresearch-paper/setup] warn: %s\n' "$*" >&2; }
fail() { printf '[autoresearch-paper/setup] missing: %s\n' "$*" >&2; MISSING=1; }

MISSING=0

need_cmd() {
  local cmd="$1"
  local why="$2"
  local hint="$3"
  if command -v "${cmd}" >/dev/null 2>&1; then
    ok "${cmd} (${why})"
  else
    fail "${cmd} (${why})"
    printf '  fix: %s\n' "${hint}" >&2
  fi
}

need_cmd python3 "runs bundled guards and runtime tests" "install Python 3 and ensure python3 is on PATH"
if [[ "${MODE}" != "test" ]]; then
  need_cmd jq "validates JSON prompts and runtime state during checks" "macOS: brew install jq"
  need_cmd claude "hosts the target Harness and dispatches the plan-pinned low-cost worker" "install Claude Code and ensure claude is on PATH"
  if command -v mavis >/dev/null 2>&1; then
    ok "mavis (optional legacy compatibility runtime)"
  else
    warn "mavis not found; legacy compatibility paths are unavailable, but the target Claude Code runtime does not require it"
  fi
  need_cmd codex "runs registered sparse frontier-advisor checkpoints" "install Codex CLI and sign in"
  need_cmd npx "installs skills from GitHub" "install Node.js 18+ so npx is available"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    need_cmd launchctl "loads the optional launchd L0 rescue daemon" "launchctl is normally present on macOS"
  else
    warn "launchctl is macOS-only; legacy --rescue launchd mode is unavailable"
  fi
  need_cmd pdflatex "verifies final LaTeX package" "install TeX Live or MacTeX"
  need_cmd bibtex "verifies bibliography resolution" "install TeX Live or MacTeX"
  need_cmd pdftotext "checks rendered PDFs for unresolved markers" "macOS: brew install poppler"
else
  ok "test mode uses local fake Claude/Codex transports and no paid or live calls"
fi

for path in \
  "${ROOT_DIR}/SKILL.md" \
  "${ROOT_DIR}/assets/task-prompt-snippets.md" \
  "${ROOT_DIR}/assets/first-action-last-seen-hook.md" \
  "${ROOT_DIR}/references/bootstrap-watchdog.sh" \
  "${ROOT_DIR}/references/claude-code-runtime.md" \
  "${ROOT_DIR}/references/frontier-response.schema.json" \
  "${ROOT_DIR}/references/human-action.schema.json" \
  "${ROOT_DIR}/references/evaluator-verdict.schema.json" \
  "${ROOT_DIR}/references/metric-contract.schema.json" \
  "${ROOT_DIR}/references/durable-plan.schema.json" \
  "${ROOT_DIR}/references/context-capsule.schema.json" \
  "${ROOT_DIR}/references/guardian-observation.schema.json" \
  "${ROOT_DIR}/references/evaluator-admission.schema.json" \
  "${ROOT_DIR}/references/canonical-conformance-workflow.json" \
  "${ROOT_DIR}/references/scripts/harness-runtime.py" \
  "${ROOT_DIR}/references/scripts/run-claude-harness.py" \
  "${ROOT_DIR}/references/scripts/cleanup-plan-resources.sh" \
  "${ROOT_DIR}/references/scripts/plan-l0-guard.py" \
  "${ROOT_DIR}/references/scripts/research-state-guard.py"; do
  if [[ -f "${path}" ]]; then
    ok "found ${path#${ROOT_DIR}/}"
  else
    fail "required file ${path#${ROOT_DIR}/}"
    printf '  fix: reinstall with: npx skills add WdBlink/autoresearch-paper -g --copy\n' >&2
  fi
done

if [[ "${MODE}" == "test" ]]; then
  ok "running contract checks"
  python3 "${ROOT_DIR}/tests/validate_contracts.py"
  python3 -m unittest discover -s "${ROOT_DIR}/tests" -p 'test_*.py'
fi

if [[ "${MISSING}" != "0" ]]; then
  cat >&2 <<'EOF'

autoresearch-paper setup is blocked. Install the missing dependencies above,
then rerun:
  scripts/setup.sh

For GitHub installation:
  npx skills add WdBlink/autoresearch-paper -g --copy
EOF
  exit 1
fi

ok "all required dependencies are ready"
