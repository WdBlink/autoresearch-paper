#!/usr/bin/env python3
"""Deterministic validator for MiniMax-authored terminal stage reports."""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

VALIDATOR_ID = "autoresearch-paper-stage-report-validator"
VALIDATOR_VERSION = "stage-report-validator/2"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_FIELDS = {
    "schema_version", "stage_report_id", "stage_cycle_id",
    "worker_identity", "candidate_sha256", "evidence_refs",
    "development_validator_receipts", "uncertainties",
    "proposed_next_questions", "scientific_summary", "findings",
}
OPTIONAL_FIELDS: set[str] = set()


class StageReportValidationError(ValueError):
    """Raised when a terminal stage report violates the closed contract."""


def _bounded_strings(value: Any, field: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise StageReportValidationError(f"{field} must be a bounded list")
    if len(value) > 64:
        raise StageReportValidationError(f"{field} has too many entries")
    if any(
        not isinstance(item, str) or not item.strip() or len(item) > 2000
        for item in value
    ):
        raise StageReportValidationError(f"{field} contains an invalid entry")


def _validate_receipt_bindings(
    value: Any, expected: list[dict[str, str]],
) -> None:
    if not isinstance(value, list) or not value or len(value) > 8:
        raise StageReportValidationError(
            "development_validator_receipts must be a bounded list"
        )
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"kind", "path", "sha256"}
            or item.get("kind") not in {
                "observation_validation", "acceptance_evaluator_execution",
            }
            or not isinstance(item.get("path"), str)
            or not item["path"]
            or not SHA256_RE.fullmatch(str(item.get("sha256", "")))
        ):
            raise StageReportValidationError(
                "development_validator_receipts contains an invalid binding"
            )
    if value != expected:
        raise StageReportValidationError(
            "development_validator_receipts must exactly match canonical terminal validation"
        )


def _validate_scientific_content(report: dict[str, Any], candidate_sha256: str) -> None:
    summary = report.get("scientific_summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 8000:
        raise StageReportValidationError("scientific_summary is invalid")
    findings = report.get("findings")
    if not isinstance(findings, list) or not findings or len(findings) > 64:
        raise StageReportValidationError("findings must be a bounded list")
    for item in findings:
        if (
            not isinstance(item, dict)
            or set(item) != {"claim", "evidence_sha256"}
            or not isinstance(item.get("claim"), str)
            or not item["claim"].strip()
            or len(item["claim"]) > 4000
            or item.get("evidence_sha256") != candidate_sha256
        ):
            raise StageReportValidationError(
                "findings must bind each claim to the canonical candidate"
            )


def validate_stage_report(
    report: dict[str, Any], *, stage_cycle_id: str, worker_model: str,
    candidate_sha256: str, authorized_evidence_refs: list[str],
    expected_validator_receipts: list[dict[str, str]],
) -> None:
    """Validate one Worker report against Controller-known stage identity."""
    if not isinstance(report, dict):
        raise StageReportValidationError("stage report must be a JSON object")
    if set(report) - (REQUIRED_FIELDS | OPTIONAL_FIELDS) or not REQUIRED_FIELDS <= set(report):
        raise StageReportValidationError("stage report has an invalid top-level shape")
    if (
        isinstance(report.get("schema_version"), bool)
        or not isinstance(report.get("schema_version"), int)
        or report.get("schema_version") != 1
    ):
        raise StageReportValidationError("stage report schema_version must be 1")
    if not isinstance(report.get("stage_report_id"), str) or not ID_RE.fullmatch(
        report["stage_report_id"]
    ):
        raise StageReportValidationError("stage_report_id is invalid")
    if report.get("stage_cycle_id") != stage_cycle_id:
        raise StageReportValidationError("stage_cycle_id does not match canonical state")
    if report.get("candidate_sha256") != candidate_sha256 or not SHA256_RE.fullmatch(
        str(report.get("candidate_sha256", ""))
    ):
        raise StageReportValidationError("candidate_sha256 does not match canonical state")
    worker = report.get("worker_identity")
    if (
        not isinstance(worker, dict)
        or set(worker) != {"model", "agent", "provider"}
        or worker.get("model") != worker_model
        or any(not isinstance(worker.get(key), str) or not worker[key].strip()
               for key in ("model", "agent", "provider"))
    ):
        raise StageReportValidationError("worker_identity is invalid")
    _bounded_strings(report.get("evidence_refs"), "evidence_refs", allow_empty=True)
    if report["evidence_refs"] != authorized_evidence_refs:
        raise StageReportValidationError(
            "evidence_refs must exactly match the frozen stage envelope"
        )
    _validate_receipt_bindings(
        report.get("development_validator_receipts"),
        expected_validator_receipts,
    )
    _validate_scientific_content(report, candidate_sha256)
    _bounded_strings(report.get("uncertainties"), "uncertainties", allow_empty=True)
    _bounded_strings(
        report.get("proposed_next_questions"), "proposed_next_questions",
        allow_empty=True,
    )


def run_conformance_suite() -> dict[str, Any]:
    valid = {
        "schema_version": 1,
        "stage_report_id": "report_stage_1",
        "stage_cycle_id": "stage_1",
        "worker_identity": {
            "model": "MiniMax-M3", "agent": "worker_1", "provider": "MiniMax",
        },
        "candidate_sha256": "a" * 64,
        "evidence_refs": ["evidence_stage_1"],
        "development_validator_receipts": [{
            "kind": "observation_validation",
            "path": "/plan/stage/observation-validation.json",
            "sha256": "b" * 64,
        }],
        "scientific_summary": "The bounded observation stage produced a source inventory.",
        "findings": [{
            "claim": "The candidate records one source-grounded observation.",
            "evidence_sha256": "a" * 64,
        }],
        "uncertainties": ["Transfer is not yet measured."],
        "proposed_next_questions": ["Run the next bounded stage."],
    }
    cases = [
        ("valid", valid, True),
        ("extra_field", {**valid, "summary": "unbound"}, False),
        ("boolean_schema_version", {**valid, "schema_version": True}, False),
        ("wrong_stage", {**valid, "stage_cycle_id": "stage_2"}, False),
        ("wrong_model", {**valid, "worker_identity": {
            **valid["worker_identity"], "model": "other",
        }}, False),
        ("wrong_evidence", {**valid, "evidence_refs": ["other"]}, False),
        ("empty_receipts", {**valid, "development_validator_receipts": []}, False),
        ("wrong_receipt_binding", {**valid, "development_validator_receipts": [{
            "kind": "observation_validation",
            "path": "/plan/stage/other-validation.json",
            "sha256": "d" * 64,
        }]}, False),
        ("worker_authored_controller_provenance", {
            **valid, "role_visible_state_sha256": "e" * 64,
        }, False),
        ("unbound_finding", {**valid, "findings": [{
            "claim": "unbound", "evidence_sha256": "c" * 64,
        }]}, False),
    ]
    results = []
    for case_id, payload, expected in cases:
        accepted = True
        try:
            validate_stage_report(
                payload, stage_cycle_id="stage_1", worker_model="MiniMax-M3",
                candidate_sha256="a" * 64,
                authorized_evidence_refs=["evidence_stage_1"],
                expected_validator_receipts=[{
                    "kind": "observation_validation",
                    "path": "/plan/stage/observation-validation.json",
                    "sha256": "b" * 64,
                }],
            )
        except StageReportValidationError:
            accepted = False
        results.append({
            "case_id": case_id,
            "expected": "accept" if expected else "reject",
            "observed": "accept" if accepted else "reject",
            "passed": accepted is expected,
        })
    if not all(item["passed"] for item in results):
        raise StageReportValidationError("stage report conformance suite failed")
    return {
        "validator_id": VALIDATOR_ID,
        "validator_version": VALIDATOR_VERSION,
        "case_count": len(results),
        "cases": results,
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conformance", action="store_true")
    args = parser.parse_args()
    if not args.conformance:
        parser.error("only --conformance is supported; Runtime supplies stage bindings")
    print(json.dumps(run_conformance_suite(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
