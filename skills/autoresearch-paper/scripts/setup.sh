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
need_cmd jq "validates JSON prompts and runtime state during checks" "macOS: brew install jq"
need_cmd mavis "runs `mavis team plan ...` CLI subset (status / cancel / resume / decision / run); v0.7.0+ removes the legacy `mavis agent|cron|session|hook` subcommands — those are file-direct or tool-form calls" "install or activate Mavis / MiniMax Code, then ensure mavis is on PATH"
need_cmd codex "runs the optional local-LLM rescue judge" "install Codex CLI and sign in, or disable rescue with local_llm_disabled"
need_cmd npx "installs skills from GitHub" "install Node.js 18+ so npx is available"

if [[ "$(uname -s)" == "Darwin" ]]; then
  need_cmd launchctl "loads the optional launchd L0 rescue daemon" "launchctl is normally present on macOS; repair the base system PATH"
else
  warn "launchctl is macOS-only; --rescue launchd mode is unavailable on this platform"
fi

need_cmd pdflatex "verifies final LaTeX package" "install TeX Live or MacTeX"
need_cmd bibtex "verifies bibliography resolution" "install TeX Live or MacTeX"
need_cmd pdftotext "checks rendered PDFs for unresolved markers" "macOS: brew install poppler"

for path in \
  "${ROOT_DIR}/SKILL.md" \
  "${ROOT_DIR}/assets/task-prompt-snippets.md" \
  "${ROOT_DIR}/assets/first-action-last-seen-hook.md" \
  "${ROOT_DIR}/references/bootstrap-watchdog.sh" \
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
  python3 -m unittest "${ROOT_DIR}/tests/test_runtime_contracts.py"
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
