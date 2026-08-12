#!/usr/bin/env bash
# Install the isolated MVP-0 preview for Agents, Codex, and Claude Code.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_ROOT="${AUTORESEARCH_SKILLS_HOME:-${HOME}}"
SHARED_DIR="${INSTALL_ROOT}/.agents/skills/autoresearch-paper-mvp0"
CODEX_LINK="${INSTALL_ROOT}/.codex/skills/autoresearch-paper-mvp0"
CLAUDE_LINK="${INSTALL_ROOT}/.claude/skills/autoresearch-paper-mvp0"
OWNER_MARKER="${SHARED_DIR}/.autoresearch-paper-mvp0-installer"
OWNER_MARKER_VALUE="autoresearch-paper-mvp0 installer-owned v1"

refuse() {
  printf '[autoresearch-paper/install-mvp0] refusing: %s\n' "$*" >&2
  exit 1
}

preflight_frontend_link() {
  local target="$1"
  local existing_target
  if [[ -L "${target}" ]]; then
    existing_target="$(readlink "${target}")"
    if [[ "${existing_target}" != "${SHARED_DIR}" ]]; then
      refuse "${target} is an unexpected symlink to ${existing_target}"
    fi
  elif [[ -e "${target}" ]]; then
    refuse "${target} already exists and is not an installer-owned symlink"
  fi
}

ensure_frontend_link() {
  local target="$1"
  if [[ ! -L "${target}" ]]; then
    ln -s "${SHARED_DIR}" "${target}"
  fi
}

# Validate every destination before copying anything. A conflict must leave the
# owner-managed path and the existing shared installation untouched.
preflight_frontend_link "${CODEX_LINK}"
preflight_frontend_link "${CLAUDE_LINK}"
if [[ -L "${SHARED_DIR}" ]]; then
  refuse "${SHARED_DIR} must be a real directory, not a symlink"
elif [[ -e "${SHARED_DIR}" && ! -d "${SHARED_DIR}" ]]; then
  refuse "${SHARED_DIR} already exists and is not a directory"
elif [[ -d "${SHARED_DIR}" ]]; then
  if [[ -L "${OWNER_MARKER}" || ! -f "${OWNER_MARKER}" ]]; then
    refuse "${SHARED_DIR} is not marked as an installer-owned directory"
  fi
  if [[ "$(<"${OWNER_MARKER}")" != "${OWNER_MARKER_VALUE}" ]]; then
    refuse "${SHARED_DIR} has an unexpected installer ownership marker"
  fi
  if ! INSTALL_SAFETY_ERROR="$(python3 - "${SHARED_DIR}" <<'PY'
import os
from pathlib import Path
import stat
import sys

root = Path(sys.argv[1])
for parent, directories, files in os.walk(root, followlinks=False):
    for name in sorted((*directories, *files)):
        path = Path(parent) / name
        details = path.lstat()
        relative = path.relative_to(root)
        if stat.S_ISLNK(details.st_mode):
            print(f"installer-owned tree contains a symlink: {relative}")
            raise SystemExit(1)
        if stat.S_ISREG(details.st_mode):
            if details.st_nlink != 1:
                print(f"installer-owned tree contains a multi-link file: {relative}")
                raise SystemExit(1)
        elif not stat.S_ISDIR(details.st_mode):
            print(f"installer-owned tree contains an unsupported entry: {relative}")
            raise SystemExit(1)
PY
  )"; then
    refuse "${INSTALL_SAFETY_ERROR}"
  fi
fi

mkdir -p "${SHARED_DIR}/agents" "${SHARED_DIR}/examples/mvp0" "${SHARED_DIR}/mvp"
printf '%s\n' "${OWNER_MARKER_VALUE}" > "${OWNER_MARKER}"
cp "${ROOT_DIR}/mvp0/SKILL.compat.md" "${SHARED_DIR}/SKILL.md"
cp "${ROOT_DIR}/mvp0/agents/openai.yaml" "${SHARED_DIR}/agents/openai.yaml"
rsync --archive --delete --delete-excluded --exclude '__pycache__/' "${ROOT_DIR}/mvp/" "${SHARED_DIR}/mvp/"
rsync --archive --delete "${ROOT_DIR}/examples/mvp0/" "${SHARED_DIR}/examples/mvp0/"

mkdir -p "${INSTALL_ROOT}/.codex/skills" "${INSTALL_ROOT}/.claude/skills"
ensure_frontend_link "${CODEX_LINK}"
ensure_frontend_link "${CLAUDE_LINK}"

printf '[autoresearch-paper/install-mvp0] installed %s\n' "${SHARED_DIR}"
