#!/usr/bin/env python3
"""Deterministic Worker artifact byte and staged-order authority.

This small module is intentionally reviewable as a CP-01 artifact.  The main
Runtime imports these functions for every Worker proposal and promoted byte
stream instead of asking a read-only Worker to provide acceptance-critical
hashing authority.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any


IMPLEMENTATION_ID = "worker-artifact-lifecycle/2"


class WorkerArtifactLifecycleError(ValueError):
    pass


def exact_utf8_sha256(content: str) -> str:
    if not isinstance(content, str):
        raise WorkerArtifactLifecycleError("artifact content must be a string")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def controller_owned_digest(content: str, declared: Any) -> str:
    """Compute the digest only when the Worker delegates that authority."""
    if declared != "controller-compute":
        raise WorkerArtifactLifecycleError(
            "worker artifact sha256 must be literal controller-compute"
        )
    return exact_utf8_sha256(content)


def controller_digest_authority_record(
    artifact_id: str, path: str, content: str, declared: Any,
) -> dict[str, str]:
    """Persist proof that a literal Worker delegation produced one digest."""
    digest = controller_owned_digest(content, declared)
    return {
        "artifact_id": artifact_id,
        "path": path,
        "delegation_literal": "controller-compute",
        "sha256": digest,
    }


def validate_controller_digest_authority_record(
    artifact_id: str, path: str, content: str, canonical_digest: Any,
    record: Any,
) -> None:
    """Replay persisted marker-to-digest authority without accepting a digest as delegation."""
    expected = {
        "artifact_id": artifact_id,
        "path": path,
        "delegation_literal": "controller-compute",
        "sha256": exact_utf8_sha256(content),
    }
    if record != expected or canonical_digest != expected["sha256"]:
        raise WorkerArtifactLifecycleError(
            "persisted controller digest authority binding mismatch"
        )


def write_exact_utf8(path: Path, content: str, expected_sha256: str) -> None:
    """Write exact UTF-8 bytes and prove no newline/canonicalization drift."""
    encoded = content.encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != expected_sha256:
        raise WorkerArtifactLifecycleError("pre-write artifact hash mismatch")
    path.write_bytes(encoded)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise WorkerArtifactLifecycleError("staged artifact hash mismatch")


STAGED_TRANSITIONS = {
    "freeze_candidate": {
        "from": {"STAGE_AUTHORIZED", "DEVELOPING", "CANDIDATE_FROZEN"},
        "to": "CANDIDATE_FROZEN",
    },
    "complete_observation": {
        "from": {"CANDIDATE_FROZEN", "RECORDED"},
        "to": "RECORDED",
    },
    "compile_continuation": {
        "from": {"RECORDED"},
        "to": "CONTRACTED",
    },
    "authorize_continuation": {
        "from": {"CONTRACTED"},
        "to": "STAGE_AUTHORIZED",
    },
    "start_continuation_worker": {
        "from": {"STAGE_AUTHORIZED", "DEVELOPING"},
        "to": "DEVELOPING",
    },
}


def require_staged_transition(event: str, current: str, target: str) -> None:
    rule = STAGED_TRANSITIONS.get(event)
    if rule is None or current not in rule["from"] or target != rule["to"]:
        raise WorkerArtifactLifecycleError(
            f"invalid staged transition: {event} {current}->{target}"
        )


def run_conformance_suite() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []

    def record(case_id: str, passed: bool) -> None:
        cases.append({"case_id": case_id, "passed": passed})

    no_newline = '{"value":1}'
    with_newline = no_newline + "\n"
    record(
        "terminal_newline_changes_digest",
        exact_utf8_sha256(no_newline) != exact_utf8_sha256(with_newline),
    )
    record(
        "controller_computes_exact_returned_content",
        controller_owned_digest(no_newline, "controller-compute")
        == exact_utf8_sha256(no_newline),
    )
    try:
        controller_owned_digest(no_newline, exact_utf8_sha256(no_newline))
    except WorkerArtifactLifecycleError:
        record("worker_declared_digest_rejected", True)
    else:
        record("worker_declared_digest_rejected", False)
    canonical_digest = controller_owned_digest(no_newline, "controller-compute")
    authority = controller_digest_authority_record(
        "artifact_1", "artifact.json", no_newline, "controller-compute",
    )
    try:
        validate_controller_digest_authority_record(
            "artifact_1", "artifact.json", no_newline,
            canonical_digest, authority,
        )
    except WorkerArtifactLifecycleError:
        record("persisted_digest_authority_replays", False)
    else:
        record("persisted_digest_authority_replays", True)
    with tempfile.TemporaryDirectory() as temp_dir:
        target = Path(temp_dir) / "artifact.json"
        digest = exact_utf8_sha256(no_newline)
        write_exact_utf8(target, no_newline, digest)
        record(
            "promotion_stage_preserves_exact_bytes",
            target.read_bytes() == no_newline.encode("utf-8")
            and hashlib.sha256(target.read_bytes()).hexdigest() == digest,
        )
    ordered = [
        ("freeze_candidate", "DEVELOPING", "CANDIDATE_FROZEN"),
        ("complete_observation", "CANDIDATE_FROZEN", "RECORDED"),
        ("compile_continuation", "RECORDED", "CONTRACTED"),
        ("authorize_continuation", "CONTRACTED", "STAGE_AUTHORIZED"),
        ("start_continuation_worker", "STAGE_AUTHORIZED", "DEVELOPING"),
    ]
    try:
        for event, current, target in ordered:
            require_staged_transition(event, current, target)
    except WorkerArtifactLifecycleError:
        record("two_stage_transition_order_accepts", False)
    else:
        record("two_stage_transition_order_accepts", True)
    try:
        require_staged_transition("compile_continuation", "DEVELOPING", "CONTRACTED")
    except WorkerArtifactLifecycleError:
        record("premature_continuation_rejected", True)
    else:
        record("premature_continuation_rejected", False)
    try:
        require_staged_transition("compile_continuation", "PAUSED", "CONTRACTED")
    except WorkerArtifactLifecycleError:
        record("paused_continuation_rejected", True)
    else:
        record("paused_continuation_rejected", False)
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
