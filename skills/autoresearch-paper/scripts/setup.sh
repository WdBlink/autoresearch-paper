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

has_skill() {
  local skill_name="$1"
  local candidate
  for candidate in \
    "${HOME}/.agents/skills/${skill_name}/SKILL.md" \
    "${HOME}/.claude/skills/${skill_name}/SKILL.md" \
    "${HOME}/.codex/skills/${skill_name}/SKILL.md"; do
    if [[ -f "${candidate}" ]]; then
      return 0
    fi
  done
  return 1
}

has_pinned_skill_for_agent() {
  local skill_name="$1"
  local pin="$2"
  local agent="$3"
  local candidate
  local primary
  case "${agent}" in
    claude-code) primary="${HOME}/.claude/skills/${skill_name}/SKILL.md" ;;
    codex) primary="${HOME}/.codex/skills/${skill_name}/SKILL.md" ;;
    *) return 1 ;;
  esac
  for candidate in \
    "${primary}" \
    "${HOME}/.agents/skills/${skill_name}/SKILL.md"; do
    if [[ -f "${candidate}" ]] && grep -Eq "^[[:space:]]*github-pinned:[[:space:]]*[\"']?${pin}[\"']?[[:space:]]*$" "${candidate}"; then
      return 0
    fi
  done
  return 1
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
  FIGURE_SKILL_PIN="70a0d595e54b8d92ca54f216d4315e0ab8c7d967"
  if has_pinned_skill_for_agent scientific-visualization "${FIGURE_SKILL_PIN}" claude-code; then
    ok "scientific-visualization for Claude Code (audited revision ${FIGURE_SKILL_PIN})"
  else
    fail "scientific-visualization for Claude Code at audited revision ${FIGURE_SKILL_PIN}"
    printf '  fix: gh skill install K-Dense-AI/scientific-agent-skills scientific-visualization --pin 70a0d595e54b8d92ca54f216d4315e0ab8c7d967 --agent claude-code --scope user\n' >&2
  fi
  if has_pinned_skill_for_agent scientific-visualization "${FIGURE_SKILL_PIN}" codex; then
    ok "scientific-visualization for Codex (audited revision ${FIGURE_SKILL_PIN})"
  else
    fail "scientific-visualization for Codex at audited revision ${FIGURE_SKILL_PIN}"
    printf '  fix: gh skill install K-Dense-AI/scientific-agent-skills scientific-visualization --pin 70a0d595e54b8d92ca54f216d4315e0ab8c7d967 --agent codex --scope user\n' >&2
  fi
  if has_skill scientific-schematics; then
    ok "scientific-schematics (optional proposal-only method-diagram capability)"
  else
    warn "scientific-schematics not found; optional AI method-diagram proposals are unavailable, deterministic figure paths remain valid"
  fi
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
  "${ROOT_DIR}/references/figure-artifact.schema.json" \
  "${ROOT_DIR}/references/figure-requirements.schema.json" \
  "${ROOT_DIR}/references/scientific-figure-pipeline.md" \
  "${ROOT_DIR}/references/canonical-conformance-workflow.json" \
  "${ROOT_DIR}/references/scripts/harness-runtime.py" \
  "${ROOT_DIR}/references/scripts/run-claude-harness.py" \
  "${ROOT_DIR}/references/scripts/cleanup-plan-resources.sh" \
  "${ROOT_DIR}/references/scripts/plan-l0-guard.py" \
  "${ROOT_DIR}/references/scripts/validate-figure-artifacts.py" \
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
