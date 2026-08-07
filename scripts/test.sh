#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-all}"

run_modular() {
  (cd "${ROOT_DIR}" && python3 -m unittest discover -s tests -p 'test_*.py' -v)
}

run_legacy() {
  (cd "${ROOT_DIR}/skills/autoresearch-paper" && scripts/setup.sh test)
}

case "${MODE}" in
  modular) run_modular ;;
  legacy) run_legacy ;;
  all) run_modular; run_legacy ;;
  *) printf 'usage: %s [modular|legacy|all]\n' "$0" >&2; exit 2 ;;
esac
