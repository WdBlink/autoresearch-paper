#!/usr/bin/env python3
"""Pure plan-wide deadline and frontier-capacity decisions.

The Runtime imports these functions for mutation-time enforcement and snapshots
this module plus its conformance result for CP-01.  The proof artifact and the
live controller therefore cannot silently use different inequalities.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


IMPLEMENTATION_ID = "plan-execution-boundaries/1"
FRONTIER_FIELDS = (
    ("calls", "reserved_calls", "max_calls"),
    ("input_tokens", "reserved_input_tokens", "max_input_tokens"),
    ("output_tokens", "reserved_output_tokens", "max_output_tokens"),
)


class PlanExecutionBoundaryError(ValueError):
    pass


def parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise PlanExecutionBoundaryError("invalid UTC timestamp") from exc
    if parsed.tzinfo is None:
        raise PlanExecutionBoundaryError("UTC timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def make_plan_deadline(
    activated_at: str, wall_clock_seconds: int,
) -> dict[str, Any]:
    if (
        isinstance(wall_clock_seconds, bool)
        or not isinstance(wall_clock_seconds, int)
        or wall_clock_seconds < 60
    ):
        raise PlanExecutionBoundaryError(
            "wall_clock_seconds must be an integer of at least 60"
        )
    activated = parse_utc(activated_at)
    deadline = activated + timedelta(seconds=wall_clock_seconds)
    return {
        "activated_at": activated.isoformat().replace("+00:00", "Z"),
        "wall_clock_seconds": wall_clock_seconds,
        "deadline_at": deadline.isoformat().replace("+00:00", "Z"),
    }


def require_deadline_active(boundary: dict[str, Any], observed_at: str) -> None:
    expected = make_plan_deadline(
        boundary.get("activated_at"), boundary.get("wall_clock_seconds"),
    )
    if {
        key: boundary.get(key) for key in expected
    } != expected:
        raise PlanExecutionBoundaryError("plan deadline boundary changed")
    if parse_utc(observed_at) >= parse_utc(boundary["deadline_at"]):
        raise PlanExecutionBoundaryError("plan wall-clock deadline exhausted")


def next_frontier_totals(
    ledger: dict[str, Any], requested: dict[str, Any],
    limits: dict[str, Any],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for request_field, ledger_field, limit_field in FRONTIER_FIELDS:
        request_value = requested.get(request_field)
        ledger_value = ledger.get(ledger_field)
        limit_value = limits.get(limit_field)
        for label, value in (
            (request_field, request_value),
            (ledger_field, ledger_value),
            (limit_field, limit_value),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PlanExecutionBoundaryError(
                    f"{label} must be a non-negative integer"
                )
        total = ledger_value + request_value
        if total > limit_value:
            raise PlanExecutionBoundaryError(
                f"frontier {request_field} capacity exhausted"
            )
        totals[ledger_field] = total
    return totals


def run_conformance_suite() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []

    def record(case_id: str, passed: bool) -> None:
        cases.append({"case_id": case_id, "passed": passed})

    boundary = make_plan_deadline("2026-01-01T00:00:00Z", 3600)
    try:
        require_deadline_active(boundary, "2026-01-01T00:59:59Z")
    except PlanExecutionBoundaryError:
        record("deadline_before_boundary_accepts", False)
    else:
        record("deadline_before_boundary_accepts", True)
    for case_id, observed in (
        ("deadline_exact_boundary_rejects", "2026-01-01T01:00:00Z"),
        ("deadline_after_boundary_rejects", "2026-01-01T01:00:01Z"),
    ):
        try:
            require_deadline_active(boundary, observed)
        except PlanExecutionBoundaryError:
            record(case_id, True)
        else:
            record(case_id, False)

    limits = {
        "max_calls": 2, "max_input_tokens": 20, "max_output_tokens": 10,
    }
    ledger = {
        "reserved_calls": 1,
        "reserved_input_tokens": 10,
        "reserved_output_tokens": 5,
    }
    try:
        totals = next_frontier_totals(
            ledger, {"calls": 1, "input_tokens": 10, "output_tokens": 5},
            limits,
        )
    except PlanExecutionBoundaryError:
        record("frontier_exact_boundary_accepts", False)
    else:
        record(
            "frontier_exact_boundary_accepts",
            totals == {
                "reserved_calls": 2,
                "reserved_input_tokens": 20,
                "reserved_output_tokens": 10,
            },
        )
    for field in ("calls", "input_tokens", "output_tokens"):
        requested = {"calls": 1, "input_tokens": 10, "output_tokens": 5}
        requested[field] += 1
        try:
            next_frontier_totals(ledger, requested, limits)
        except PlanExecutionBoundaryError:
            record(f"frontier_{field}_overflow_rejects", True)
        else:
            record(f"frontier_{field}_overflow_rejects", False)
    return {
        "schema_version": 1,
        "implementation_id": IMPLEMENTATION_ID,
        "case_count": len(cases),
        "status": "PASS" if all(item["passed"] for item in cases) else "FAIL",
        "cases": cases,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_conformance_suite(), ensure_ascii=False, sort_keys=True))
