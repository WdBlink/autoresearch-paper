#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m unittest discover -s foundation/tests -p 'test_*.py' -v
python3 foundation/vendor/deli-local/run-tests.py
