#!/usr/bin/env python3
"""Session-independent, metadata-only P6 L0 watchdog entry point."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from .launchd_registration import LaunchctlScheduler
    from .runtime_assurance import AssuranceError, run_l0_health_tick
except ImportError:  # direct launchd/script execution
    from launchd_registration import LaunchctlScheduler  # type: ignore[no-redef]
    from runtime_assurance import AssuranceError, run_l0_health_tick  # type: ignore[no-redef]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-dir", type=Path, required=True)
    parser.add_argument("--once", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        result = run_l0_health_tick(
            store_dir=args.store_dir,
            scheduler=LaunchctlScheduler(),
            now=_now(),
        )
    except AssuranceError as exc:
        print(json.dumps({"error": str(exc), "model_dispatches": 0}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
