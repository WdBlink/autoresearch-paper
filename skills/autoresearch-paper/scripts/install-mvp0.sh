#!/usr/bin/env bash
# Install the isolated MVP-0 preview for Agents, Codex, and Claude Code.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHARED_DIR="${HOME}/.agents/skills/autoresearch-paper-mvp0"

mkdir -p "${SHARED_DIR}/agents" "${SHARED_DIR}/examples" "${SHARED_DIR}/mvp"
cp "${ROOT_DIR}/mvp0/SKILL.md" "${SHARED_DIR}/SKILL.md"
cp "${ROOT_DIR}/mvp0/agents/openai.yaml" "${SHARED_DIR}/agents/openai.yaml"
rsync --archive --delete --delete-excluded --exclude '__pycache__/' "${ROOT_DIR}/mvp/" "${SHARED_DIR}/mvp/"
rsync --archive --delete "${ROOT_DIR}/examples/mvp0/" "${SHARED_DIR}/examples/"

mkdir -p "${HOME}/.codex/skills" "${HOME}/.claude/skills"
ln -sfn "${SHARED_DIR}" "${HOME}/.codex/skills/autoresearch-paper-mvp0"
ln -sfn "${SHARED_DIR}" "${HOME}/.claude/skills/autoresearch-paper-mvp0"

printf '[autoresearch-paper/install-mvp0] installed %s\n' "${SHARED_DIR}"
