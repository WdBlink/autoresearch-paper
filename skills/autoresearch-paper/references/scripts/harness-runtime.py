#!/usr/bin/env python3
"""Claude Code runtime adapter and durable Codex frontier-advisor bridge.

The script intentionally keeps formal plan transitions in this deterministic
controller. Claude/MiniMax worker output and Codex output are artifacts; neither
is lifecycle authority.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import hmac
import json
import math
import os
import plistlib
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from source_inventory_validator import (
    SYMBOL_RE,
    SourceInventoryValidationError,
    run_conformance_suite as run_source_inventory_conformance_suite,
    symbol_occurs_on_line,
    validate_source_inventory,
)
from stage_report_validator import (
    StageReportValidationError,
    run_conformance_suite as run_stage_report_conformance_suite,
    validate_stage_report,
)
from worker_artifact_lifecycle import (
    WorkerArtifactLifecycleError,
    controller_owned_digest,
    exact_utf8_sha256,
    require_staged_transition,
    run_conformance_suite as run_worker_artifact_lifecycle_conformance,
    write_exact_utf8,
)
from dashboard_server import DashboardError, make_dashboard_server


SCHEMA_VERSION = 1
PLAN_AUDIT_MODEL = "gpt-5.6-sol"
PLAN_AUDIT_REASONING_EFFORT = "ultra"
CHECKPOINTS = {
    "CP-01": {"kind": "plan_audit", "subtypes": {None}, "recommendations": {"accept", "revise", "block"}},
    "CP-02": {"kind": "evaluator_audit", "subtypes": {None}, "recommendations": {"accept", "revise", "block"}},
    "CP-03": {"kind": "pivot_advice", "subtypes": {None}, "recommendations": {"pivot", "repair", "escalate_human", "block"}},
    "CP-04": {
        "kind": "evidence_audit",
        "subtypes": {"acceptance_dispute", "prewriting_final_evidence"},
        "recommendations": {"accept", "repair", "escalate_human", "block"},
    },
    "STAGE-REVIEW": {
        "kind": "stage_review",
        "subtypes": {None},
        "recommendations": {"accept", "revise", "block"},
    },
}
DEPENDENT_TRANSITIONS = {
    ("CP-01", None): ("approve_execution", {"accept"}),
    ("CP-02", None): ("freeze_evaluator", {"accept"}),
    ("CP-03", None): ("authorize_structural_pivot", {"pivot", "repair"}),
    ("CP-04", "acceptance_dispute"): ("resolve_acceptance_dispute", {"accept"}),
    ("CP-04", "prewriting_final_evidence"): ("start_writing", {"accept"}),
    ("STAGE-REVIEW", None): ("record_stage_review", {"accept", "revise"}),
}
HUMAN_ACTIONS = {
    "pause", "resume", "stop", "cancel_worker", "waive_acceptance",
    "override_acceptance", "cleanup_resource", "authorize_evaluator_change",
    "authorize_contract", "reauthorize_stage", "authorize_rebaseline",
    "release_evidence", "authorize_frontier_capacity",
}
INTEGRITY_FAILURE_CLASSES = {"goal_drift", "evaluator_integrity"}
FAILURE_CLASSES = {
    "runtime_stall", "implementation_failure", "scientific_no_improvement",
    "duplicate_direction", "verifier_rejection", *INTEGRITY_FAILURE_CLASSES,
}
FAILURE_ROUTES = {
    "runtime_stall": "deterministic_runtime_recovery",
    "implementation_failure": "bounded_implementation_repair",
    "scientific_no_improvement": "distinct_direction_or_pivot",
    "duplicate_direction": "reject_and_select_distinct_direction",
    "verifier_rejection": "repair_evidence_or_candidate",
    "goal_drift": "pause_and_rebaseline_goal",
    "evaluator_integrity": "revoke_autonomy_and_re_admit_evaluator",
}
TERMINAL_WORKER_STATES = {"COMPLETED", "FAILED", "PAUSED", "CANCELLED"}
READ_ONLY_CLAUDE_TOOLS = {"Read", "Glob", "Grep", "WebSearch", "WebFetch"}
REQUEST_ID_RE = re.compile(r"^far_[A-Za-z0-9_-]+$")
WORKER_ID_RE = re.compile(r"^cwr_[a-f0-9]{32}$")
OPERATION_ID_RE = re.compile(r"^op_[a-f0-9]{64}$")
STATES = {
    "CREATED", "BUDGET_RESERVED", "SENT", "WAITING", "RECEIVED",
    "VALIDATED", "APPLIED", "EXPIRED", "INVALID", "PAUSED",
}
FRONTIER_TRANSPORTS = {"chatgpt-https", "codex-default"}
RESPONSE_SCHEMA = SCRIPT_DIR.parent / "frontier-response.schema.json"
HUMAN_ACTION_SCHEMA = SCRIPT_DIR.parent / "human-action.schema.json"
EVALUATOR_VERDICT_SCHEMA = SCRIPT_DIR.parent / "evaluator-verdict.schema.json"
METRIC_CONTRACT_SCHEMA = SCRIPT_DIR.parent / "metric-contract.schema.json"
DECLARATIVE_EVALUATOR_SCHEMA = SCRIPT_DIR.parent / "declarative-evaluator.schema.json"
DURABLE_PLAN_SCHEMA = SCRIPT_DIR.parent / "durable-plan.schema.json"
CONTEXT_CAPSULE_SCHEMA = SCRIPT_DIR.parent / "context-capsule.schema.json"
GUARDIAN_OBSERVATION_SCHEMA = SCRIPT_DIR.parent / "guardian-observation.schema.json"
EVALUATOR_ADMISSION_SCHEMA = SCRIPT_DIR.parent / "evaluator-admission.schema.json"
STAGED_RESEARCH_SCHEMA = SCRIPT_DIR.parent / "staged-research.schema.json"
ROLE_VISIBLE_STATE_SCHEMA = SCRIPT_DIR.parent / "role-visible-state.schema.json"
CODEX_HOST_BRIEF_SCHEMA = SCRIPT_DIR.parent / "codex-host-brief.schema.json"
FIGURE_VALIDATOR = SCRIPT_DIR / "validate-figure-artifacts.py"
CHECKPOINT_EVIDENCE_PROFILES = {
    ("CP-01", None): {
        "normalized_brief", "execution_plan", "risk_budget", "figure_requirements",
    },
    ("CP-02", None): {
        "evaluator", "evidence_manifest", "metric_contract", "baselines",
        "seeds_splits", "leakage_controls", "calibration_candidate", "promotion_receipt",
    },
    ("CP-03", None): {
        "failure_state", "direction_registry", "pivot_proposal", "evaluator_verdict",
    },
    ("CP-04", "acceptance_dispute"): {
        "evaluator_contract", "evaluator_verdict", "dispute_record", "candidate",
    },
    ("CP-04", "prewriting_final_evidence"): {
        "candidate", "claim_evidence_map", "evaluator_contract", "evaluator_verdict",
        "raw_result_manifest", "baselines", "uncertainty_robustness", "figure_gate",
    },
    ("STAGE-REVIEW", None): {
        "optimization_contract", "stage_envelope", "stage_report",
        "stage_candidate", "stage_decision", "terminal_validation_receipt",
    },
}
STAGE_REVIEW_CONTINUATION_EVIDENCE_PROFILE = {
    "next_stage_envelope", "next_stage_preflight_inputs",
    "next_stage_task_contract",
}
STAGED_CP01_EVIDENCE_PROFILE = {
    "optimization_contract", "first_stage_envelope",
    "current_stage_preflight", "checkpoint_capacity",
}
STAGED_CP01_REVIEW_MATERIAL_PURPOSES = {
    "execution_plan", "acceptance_evaluator", "risk_and_stop_rules",
    "figure_strategy",
}
STAGED_REPORT_VALIDATOR_MATERIAL_PURPOSES = {
    "stage_report_validator_implementation",
    "stage_report_validator_conformance",
}
STAGED_CP01_OPTIONAL_REVIEW_MATERIAL_PURPOSES = {
    "evaluator_implementation", "evaluator_conformance",
    "acceptance_profile", "source_manifest", "citation_universe",
    "evaluation_profile", "evaluator_loader_parameters",
}
STAGED_CP01_REVIEW_ROLE_PREFIX = "review_material:"
DIRECTION_FIELDS = {
    "algorithm_family", "data_representation", "objective", "evaluator",
    "baseline_framing", "lineage", "candidate_sha256",
}
SCIENTIFIC_DIRECTION_FIELDS = DIRECTION_FIELDS - {"candidate_sha256"}
DURABLE_SCHEDULE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
DURABLE_TICK_ID_RE = re.compile(r"^tick_[a-f0-9]{64}$")
DURABLE_CLAIM_ID_RE = re.compile(r"^claim_[a-f0-9]{64}$")
DURABLE_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
STAGED_GOVERNANCE_VERSION = "staged-research/v1"
STAGED_MATURITY = {
    "idea", "screened", "full_experiment", "gate_accepted", "released",
}
EVIDENCE_MATURITY_ORDER = (
    "idea", "screened", "full_experiment", "gate_accepted", "released",
)
STAGED_TERMINAL_DECISIONS = {"accept", "reject", "escalate"}
STAGED_CANDIDATE_FIELDS = {
    "schema_version", "stage_cycle_id", "incumbent_sha256",
    "candidate_sha256", "candidate_path", "maturity",
    "development_evidence_refs", "promotion_receipt_path",
    "promotion_receipt_sha256", "completed_worker_status_path",
    "completed_worker_status_sha256", "promotion_journal_path",
    "promotion_journal_sha256", "frozen_at",
}
STAGED_GATE_ANCHOR_FIELDS = {
    "candidate_record_path", "candidate_record_sha256",
    "logical_gate_query_path", "logical_gate_query_sha256",
    "received_attempt_journal_path", "received_attempt_journal_sha256",
    "gate_decision_journal_path", "gate_decision_journal_sha256",
}
STAGED_EVIDENCE_RECEIPT_FIELDS = {
    "schema_version", "evidence_id", "stage_cycle_id", "decision",
    "maturity", "environment_version", "evaluator_version",
    "applicability", "confidence", "validation_status",
    "provenance_sha256", "active_for_retrieval",
} | STAGED_GATE_ANCHOR_FIELDS
CHATGPT_USAGE_FLOOR = {
    "profile_id": "chatgpt-frontier-v1",
    "min_input_tokens": 150000,
    "min_output_tokens": 5000,
}


class ContractError(RuntimeError):
    """A runtime or data contract was violated."""


class FrontierBudgetOverrunError(ContractError):
    """Controller-observed transport usage exceeded the frozen reservation."""


class FrontierSemanticResponseError(ContractError):
    """A structurally valid response contains an impossible gate verdict."""


def reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def strict_json_loads(raw: str | bytes) -> Any:
    """Load standards-compliant JSON and reject NaN/Infinity spellings."""
    try:
        return json.loads(raw, parse_constant=reject_json_constant)
    except ValueError as exc:
        raise ContractError(f"invalid strict JSON: {exc}") from exc


def require_finite_number(value: Any, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ContractError(f"{name} must be a finite number")
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ContractError(f"invalid UTC timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ContractError("timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def atomic_json_sha256(value: dict[str, Any]) -> str:
    """Hash the exact bytes emitted by atomic_write_json."""
    raw = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    return hashlib.sha256(raw.encode()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = strict_json_loads(path.read_text())
    except FileNotFoundError as exc:
        raise ContractError(f"missing JSON file: {path}") from exc
    except ContractError as exc:
        raise ContractError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def atomic_write_json(path: Path, value: dict[str, Any], *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    with temporary.open("w") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        if immutable:
            os.fchmod(handle.fileno(), 0o444)
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def atomic_write_bytes(path: Path, value: bytes, *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    with temporary.open("wb") as handle:
        handle.write(value)
        handle.flush()
        if immutable:
            os.fchmod(handle.fileno(), 0o444)
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{name} must be a non-negative integer")
    return value


def policy_path(plan_dir: Path) -> Path:
    return plan_dir / "state" / "model_policy.json"


def load_policy(plan_dir: Path) -> dict[str, Any]:
    policy = read_json(policy_path(plan_dir))
    if policy.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("model policy schema_version must be 1")
    if policy.get("runtime") != "claude-code":
        raise ContractError("model policy runtime must be claude-code")
    worker_model = policy.get("worker_model")
    normalized = str(worker_model or "").lower().replace("-", "")
    if "minimax" not in normalized or "m3" not in normalized:
        raise ContractError("worker_model must pin the MiniMax M3 family")
    if not isinstance(policy.get("frontier_model"), str) or not policy["frontier_model"].strip():
        raise ContractError("frontier_model must be pinned")
    plan_audit = policy.get("top_level_plan_audit")
    if plan_audit is not None:
        if (
            not isinstance(plan_audit, dict)
            or set(plan_audit) != {
                "required", "declared_author_model_family", "reviewer_runtime",
                "reviewer_model", "reasoning_effort", "checkpoint",
                "dependent_transition",
            }
        ):
            raise ContractError("top_level_plan_audit has an invalid closed shape")
        if (
            plan_audit.get("required") is not True
            or plan_audit.get("declared_author_model_family")
            != ("Codex" if policy.get("host_runtime") == "codex" else "MiniMax-M3")
            or plan_audit.get("reviewer_runtime") != "codex"
            or plan_audit.get("reviewer_model") != PLAN_AUDIT_MODEL
            or plan_audit.get("reasoning_effort") != PLAN_AUDIT_REASONING_EFFORT
            or plan_audit.get("checkpoint") != "CP-01"
            or plan_audit.get("dependent_transition") != "approve_execution"
        ):
            raise ContractError(
                "top_level_plan_audit must pin the active Host authorship and "
                f"{PLAN_AUDIT_MODEL}/{PLAN_AUDIT_REASONING_EFFORT} Codex review"
            )
    frontier_transport = policy.get("frontier_transport", "codex-default")
    if frontier_transport not in FRONTIER_TRANSPORTS:
        raise ContractError(
            f"frontier_transport must be one of {sorted(FRONTIER_TRANSPORTS)}"
        )
    escalation = policy.get("frontier_escalation")
    if not isinstance(escalation, dict) or escalation.get("enabled") is not True:
        raise ContractError("frontier_escalation must be enabled and frozen")
    for field in ("max_calls", "max_input_tokens", "max_output_tokens"):
        require_non_negative_int(escalation.get(field), f"frontier_escalation.{field}")
    usage_profile = policy.get("frontier_usage_profile")
    if usage_profile is not None and usage_profile != CHATGPT_USAGE_FLOOR:
        raise ContractError("frontier_usage_profile has an invalid frozen shape")
    worker_budget = policy.get("worker_max_budget_usd")
    require_finite_number(worker_budget, "worker_max_budget_usd")
    if worker_budget <= 0:
        raise ContractError("worker_max_budget_usd must be positive")
    return policy


def worker_session_path(plan_dir: Path) -> Path:
    return plan_dir / "state" / "worker_session.json"


def worker_session_binding_path(plan_dir: Path) -> Path:
    return plan_dir / "state" / "worker_session_binding.json"


def record_worker_session_failure(
    plan_dir: Path, failure_class: str, details: dict[str, Any] | None = None,
) -> Path:
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "failure_class": failure_class,
        "details": details or {},
        "observed_at": utc_now(),
    }
    target = (
        plan_dir / "state" / "worker_session_failures"
        / f"{int(time.time_ns())}-{uuid.uuid4().hex}.json"
    )
    atomic_write_json(target, receipt, immutable=True)
    return target


def worker_session_policy(
    plan_dir: Path,
    policy: dict[str, Any],
    resolved_claude_bin: str,
    allowed_tools: list[str],
) -> dict[str, Any]:
    """Return the immutable transport policy bound to one Claude session."""
    result = {
        "plan_id": plan_identity(plan_dir),
        "working_directory": str(plan_dir.resolve()),
        "runtime": "claude-code",
        "worker_model": policy["worker_model"],
        "model_policy_sha256": sha256_file(policy_path(plan_dir)),
        "claude_executable": resolved_claude_bin,
        "permission_mode": "dontAsk",
        "allowed_tools": sorted(allowed_tools),
    }
    entry_policy_path = (
        plan_dir / "control" / "codex-host-entry" / "v1"
        / "worker-session-policy.json"
    )
    if entry_policy_path.is_file():
        validate_immutable_binding(
            entry_policy_path, sha256_file(entry_policy_path),
            "Codex host worker session policy",
        )
        entry_policy = read_json(entry_policy_path)
        ceiling = entry_policy.get("allowed_tool_ceiling")
        if (
            entry_policy.get("plan_id") != plan_identity(plan_dir)
            or entry_policy.get("runtime") != "claude-code"
            or entry_policy.get("worker_model") != policy["worker_model"]
            or entry_policy.get("claude_executable") != resolved_claude_bin
            or entry_policy.get("permission_mode") != "dontAsk"
            or entry_policy.get("session_mode") != "persistent_exact_resume"
            or not isinstance(ceiling, list)
            or not set(allowed_tools).issubset(set(ceiling))
        ):
            raise ContractError("Codex host worker session policy does not authorize this turn")
        try:
            uuid.UUID(entry_policy["session_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("Codex host worker session policy has an invalid session_id") from exc
        result["codex_host_entry_policy_sha256"] = sha256_file(entry_policy_path)
    return result


def acquire_worker_session_lease(plan_dir: Path) -> Any:
    """Acquire the one-writer lease before consuming Worker capacity."""
    path = plan_dir / "state" / ".worker_session.delivery.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        record_worker_session_failure(
            plan_dir, "session_busy",
            {"lock_path": str(path), "transport_launched": False},
        )
        raise ContractError(
            "session_busy: Claude worker session is busy; concurrent delivery is forbidden"
        ) from exc
    return handle


def release_worker_session_lease(handle: Any | None) -> None:
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def load_or_create_worker_session(
    plan_dir: Path,
    policy: dict[str, Any],
    resolved_claude_bin: str,
    allowed_tools: list[str],
) -> dict[str, Any]:
    path = worker_session_path(plan_dir)
    binding_path = worker_session_binding_path(plan_dir)
    bound_policy = worker_session_policy(
        plan_dir, policy, resolved_claude_bin, allowed_tools,
    )
    bound_sha = sha256_json(bound_policy)
    if path.exists() or binding_path.exists():
        if not path.exists() or not binding_path.exists():
            record_worker_session_failure(
                plan_dir, "session_missing",
                {
                    "state_present": path.exists(),
                    "binding_present": binding_path.exists(),
                    "transport_launched": False,
                },
            )
            raise ContractError(
                "session_missing: Claude worker session state/binding pair is incomplete; "
                "automatic session rotation is forbidden"
            )
        if (
            binding_path.is_symlink()
            or not binding_path.is_file()
            or binding_path.stat().st_mode & 0o777 != 0o444
        ):
            record_worker_session_failure(
                plan_dir, "session_binding_drift",
                {"binding_path": str(binding_path), "transport_launched": False},
            )
            raise ContractError("session_binding_drift: immutable session binding changed")
        binding = read_json(binding_path)
        session = read_json(path)
        required = {
            "schema_version", "plan_id", "session_id", "state", "turn_count",
            "bound_policy", "bound_policy_sha256", "binding_path",
            "binding_sha256", "created_at", "updated_at",
        }
        if set(session) - (required | {
            "active_run_id", "last_run_id", "last_turn_receipt",
            "last_turn_receipt_sha256", "paused_reason",
        }):
            raise ContractError("worker session contains unknown fields")
        if not required.issubset(session):
            raise ContractError("worker session is incomplete")
        try:
            uuid.UUID(session["session_id"])
        except (AttributeError, TypeError, ValueError) as exc:
            raise ContractError("worker session_id must be a UUID") from exc
        binding_sha = sha256_file(binding_path)
        binding_required = {
            "schema_version", "plan_id", "session_id", "bound_policy",
            "bound_policy_sha256", "created_at",
        }
        if (
            set(binding) != binding_required
            or binding.get("schema_version") != SCHEMA_VERSION
            or binding.get("plan_id") != plan_identity(plan_dir)
            or not isinstance(binding.get("created_at"), str)
            or binding.get("bound_policy_sha256")
            != sha256_json(binding.get("bound_policy"))
        ):
            record_worker_session_failure(
                plan_dir, "session_binding_drift",
                {"binding_path": str(binding_path), "transport_launched": False},
            )
            raise ContractError("session_binding_drift: immutable session binding contents changed")
        try:
            uuid.UUID(binding["session_id"])
        except (AttributeError, TypeError, ValueError) as exc:
            raise ContractError("session_binding_drift: binding session_id is not a UUID") from exc
        if (
            session["schema_version"] != SCHEMA_VERSION
            or session["plan_id"] != plan_identity(plan_dir)
            or session["session_id"] != binding["session_id"]
            or session["bound_policy"] != bound_policy
            or session["bound_policy_sha256"] != bound_sha
            or Path(session["binding_path"]).resolve() != binding_path.resolve()
            or session["binding_sha256"] != binding_sha
        ):
            mismatches = sorted(
                key for key in set(session.get("bound_policy", {})) | set(bound_policy)
                if session.get("bound_policy", {}).get(key) != bound_policy.get(key)
            )
            record_worker_session_failure(
                plan_dir, "session_policy_drift",
                {"mismatched_fields": mismatches, "transport_launched": False},
            )
            raise ContractError(
                "session_policy_drift: Claude worker session binding drifted "
                f"({','.join(mismatches) or 'identity'}); automatic rebinding is forbidden"
            )
        require_non_negative_int(session["turn_count"], "worker_session.turn_count")
        validate_worker_session_turn_chain(plan_dir, session)
        if session["state"] == "PAUSED":
            record_worker_session_failure(
                plan_dir, "session_paused",
                {"paused_reason": session.get("paused_reason"), "transport_launched": False},
            )
            raise ContractError(
                "session_paused: Claude worker session is PAUSED; inspect the terminal receipt before recovery"
            )
        if session["state"] not in {"READY", "BUSY"}:
            record_worker_session_failure(
                plan_dir, "session_state_invalid",
                {"state": session["state"], "transport_launched": False},
            )
            raise ContractError(f"unsupported Claude worker session state: {session['state']}")
        if session["state"] == "BUSY":
            record_worker_session_failure(
                plan_dir, "delivery_uncertain",
                {"active_run_id": session.get("active_run_id"), "transport_launched": False},
            )
            raise ContractError(
                "delivery_uncertain: Claude worker session has an unresolved BUSY delivery; reconcile before reuse"
            )
        return session
    turns_root = plan_dir / "state" / "worker_session_turns"
    if turns_root.exists() and any(turns_root.glob("*.json")):
        record_worker_session_failure(
            plan_dir, "session_missing", {"transport_launched": False},
        )
        raise ContractError(
            "session_missing: Claude worker session binding is missing after prior turns; "
            "automatic session rotation is forbidden"
        )
    now = utc_now()
    entry_policy_path = codex_host_entry_root(plan_dir) / "worker-session-policy.json"
    session_id = (
        read_json(entry_policy_path)["session_id"]
        if entry_policy_path.is_file()
        else str(uuid.uuid4())
    )
    binding = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "session_id": session_id,
        "bound_policy": bound_policy,
        "bound_policy_sha256": bound_sha,
        "created_at": now,
    }
    atomic_write_json(binding_path, binding, immutable=True)
    session = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "session_id": session_id,
        "state": "READY",
        "turn_count": 0,
        "bound_policy": bound_policy,
        "bound_policy_sha256": bound_sha,
        "binding_path": str(binding_path),
        "binding_sha256": sha256_file(binding_path),
        "created_at": now,
        "updated_at": now,
    }
    atomic_write_json(path, session)
    return session


def validate_worker_session_turn_chain(
    plan_dir: Path, session: dict[str, Any], *, expected_turn_count: int | None = None,
) -> None:
    turn_count = (
        session["turn_count"] if expected_turn_count is None else expected_turn_count
    )
    require_non_negative_int(turn_count, "worker_session.turn_count")
    turns_root = plan_dir / "state" / "worker_session_turns"
    receipts = sorted(turns_root.glob("*.json")) if turns_root.exists() else []
    if len(receipts) != turn_count:
        record_worker_session_failure(
            plan_dir, "session_turn_rollback",
            {
                "declared_turn_count": turn_count,
                "receipt_count": len(receipts),
                "transport_launched": False,
            },
        )
        raise ContractError(
            "session_turn_rollback: mutable turn_count does not match immutable receipts"
        )
    for index, receipt_path in enumerate(receipts, 1):
        if (
            receipt_path.is_symlink()
            or not receipt_path.is_file()
            or receipt_path.stat().st_mode & 0o777 != 0o444
        ):
            raise ContractError("session_turn_rollback: turn receipt is not immutable")
        receipt = read_json(receipt_path)
        if (
            receipt.get("session_id") != session["session_id"]
            or receipt.get("turn_index") != index
            or not receipt_path.name.startswith(f"{index:06d}-")
        ):
            raise ContractError("session_turn_rollback: turn receipt lineage changed")
    if turn_count:
        last = receipts[-1]
        if (
            session.get("last_turn_receipt") != str(last)
            or session.get("last_turn_receipt_sha256") != sha256_file(last)
        ):
            raise ContractError("session_turn_rollback: last turn pointer changed")


def update_worker_session(
    plan_dir: Path, session: dict[str, Any], state: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    if state not in {"READY", "BUSY", "PAUSED", "CLOSED"}:
        raise ContractError(f"invalid Claude worker session state: {state}")
    current = read_json(worker_session_path(plan_dir))
    binding_path = worker_session_binding_path(plan_dir)
    if (
        current.get("session_id") != session.get("session_id")
        or current.get("bound_policy_sha256") != session.get("bound_policy_sha256")
        or current.get("binding_sha256") != sha256_file(binding_path)
    ):
        raise ContractError("Claude worker session changed while its lease was held")
    current.update(updates)
    current["state"] = state
    current["updated_at"] = utc_now()
    validate_worker_session_turn_chain(plan_dir, current)
    atomic_write_json(worker_session_path(plan_dir), current)
    return current


def claude_transport_metadata(raw: str, expected_session_id: str) -> dict[str, Any]:
    """Extract cost observations without making them correctness authority."""
    try:
        envelope = strict_json_loads(raw)
    except ContractError:
        envelope = None
    if not isinstance(envelope, dict):
        return {
            "reported_session_id": None,
            "reported_model": None,
            "reported_provider": None,
            "reported_transcript_sha256": None,
            "input_tokens": None,
            "output_tokens": None,
            "cache_creation_input_tokens": None,
            "cache_read_input_tokens": None,
        }
    reported = envelope.get("session_id")
    if reported is not None and reported != expected_session_id:
        raise ContractError("Claude response reported a different session_id")
    usage = envelope.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    reported_model = envelope.get("model")
    reported_provider = envelope.get("provider")
    reported_transcript_sha256 = envelope.get("transcript_sha256")
    metadata = {
        "reported_session_id": reported,
        "reported_model": reported_model if isinstance(reported_model, str) else None,
        "reported_provider": (
            reported_provider if isinstance(reported_provider, str) else None
        ),
        "reported_transcript_sha256": (
            reported_transcript_sha256
            if isinstance(reported_transcript_sha256, str)
            and re.fullmatch(r"[a-f0-9]{64}", reported_transcript_sha256)
            else None
        ),
    }
    for key in (
        "input_tokens", "output_tokens", "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        value = usage.get(key)
        metadata[key] = (
            value if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else None
        )
    return metadata


def classify_claude_transport_failure(exit_code: int, stderr: str) -> str:
    normalized = stderr.lower()
    if any(marker in normalized for marker in (
        "rate limit", "usage limit", "quota", "5-hour", "5 hour",
        "token plan", "retry after",
    )):
        return "provider_quota"
    if "session" in normalized and any(marker in normalized for marker in (
        "not found", "unknown", "missing", "does not exist", "invalid",
    )):
        return "session_missing"
    if any(marker in normalized for marker in (
        "authentication", "unauthorized", "invalid api key", "login required",
    )):
        return "authentication_failure"
    return f"claude_exit_{exit_code}"


def commit_worker_session_turn(
    plan_dir: Path,
    session: dict[str, Any],
    *,
    run_id: str,
    turn_index: int,
    instruction_path: Path,
    outcome: str,
    transport_metadata: dict[str, Any] | None = None,
    failure: str | None = None,
) -> dict[str, Any]:
    if outcome not in {"COMPLETED", "FAILED", "PAUSED", "CANCELLED"}:
        raise ContractError("invalid Claude worker session turn outcome")
    metadata = transport_metadata or {
        "reported_session_id": None,
        "reported_model": None,
        "reported_provider": None,
        "reported_transcript_sha256": None,
        "input_tokens": None,
        "output_tokens": None,
        "cache_creation_input_tokens": None,
        "cache_read_input_tokens": None,
    }
    instruction = read_json(instruction_path)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "session_id": session["session_id"],
        "turn_index": turn_index,
        "invocation_mode": "created" if turn_index == 1 else "resumed",
        "expected_worker_model": session["bound_policy"]["worker_model"],
        "adapter_identity": {
            "runtime": session["bound_policy"]["runtime"],
            "claude_executable": session["bound_policy"]["claude_executable"],
            "model_policy_sha256": session["bound_policy"]["model_policy_sha256"],
        },
        "exit_class": outcome,
        "worker_run_id": run_id,
        "instruction_path": str(instruction_path),
        "instruction_sha256": sha256_file(instruction_path),
        "task_contract_sha256": instruction["task_contract_sha256"],
        "context_capsule_id": instruction["context_capsule_id"],
        "context_capsule_sha256": instruction["context_capsule_sha256"],
        "context_state_revision": instruction["context_state_revision"],
        "input_manifest_sha256": instruction["input_manifest_sha256"],
        "artifact_outputs_sha256": instruction["artifact_outputs_sha256"],
        "output_schema_sha256": instruction["output_schema_sha256"],
        "outcome": outcome,
        "failure": failure,
        "transport_usage": metadata,
        "transport_stdout_sha256": (
            sha256_file(worker_run_dir(plan_dir, run_id) / "transport.stdout")
            if (worker_run_dir(plan_dir, run_id) / "transport.stdout").is_file()
            else None
        ),
        "result_sha256": (
            sha256_file(worker_run_dir(plan_dir, run_id) / "result.json")
            if (worker_run_dir(plan_dir, run_id) / "result.json").is_file()
            else None
        ),
        "completed_at": utc_now(),
    }
    receipt_path = (
        plan_dir / "state" / "worker_session_turns"
        / f"{turn_index:06d}-{run_id}.json"
    )
    if receipt_path.exists():
        prior = read_json(receipt_path)
        stable_receipt = {key: value for key, value in receipt.items() if key != "completed_at"}
        stable_prior = {key: value for key, value in prior.items() if key != "completed_at"}
        if stable_prior != stable_receipt:
            raise ContractError("Claude worker session turn receipt changed")
        receipt = prior
    else:
        atomic_write_json(receipt_path, receipt, immutable=True)
    next_state = "READY" if outcome == "COMPLETED" else "PAUSED"
    updates = {
        "turn_count": turn_index,
        "active_run_id": None,
        "last_run_id": run_id,
        "last_turn_receipt": str(receipt_path),
        "last_turn_receipt_sha256": sha256_file(receipt_path),
    }
    if failure is not None:
        updates["paused_reason"] = failure
    else:
        updates.pop("paused_reason", None)
    return update_worker_session(plan_dir, session, next_state, updates)


def reconcile_worker_session_turn(
    plan_dir: Path, run_id: str, outcome: str, failure: str | None,
) -> dict[str, Any] | None:
    """Converge a PREPARED operation's Worker and session terminal state."""
    status = read_json(worker_status_path(plan_dir, run_id))
    if status.get("worker_session_mode") != "persistent":
        return None
    session_path = worker_session_path(plan_dir)
    if not session_path.is_file():
        record_worker_session_failure(
            plan_dir, "session_missing",
            {"worker_run_id": run_id, "reconciliation_required": True},
        )
        raise ContractError("session_missing: prepared Worker lost its session state")
    lease = acquire_worker_session_lease(plan_dir)
    try:
        session = read_json(session_path)
        if (
            session.get("last_run_id") == run_id
            and session.get("state") in {"READY", "PAUSED"}
        ):
            validate_worker_session_turn_chain(plan_dir, session)
            return session
        if (
            session.get("state") != "BUSY"
            or session.get("active_run_id") != run_id
            or session.get("session_id") != status.get("worker_session_id")
        ):
            record_worker_session_failure(
                plan_dir, "delivery_uncertain",
                {
                    "worker_run_id": run_id,
                    "session_state": session.get("state"),
                    "active_run_id": session.get("active_run_id"),
                },
            )
            raise ContractError(
                "delivery_uncertain: prepared Worker/session lineage cannot be reconciled"
            )
        instruction_path = Path(status["instruction_path"]).resolve()
        turn_index = status.get("worker_session_turn")
        if not isinstance(turn_index, int) or isinstance(turn_index, bool):
            raise ContractError("prepared Worker has no valid session turn index")
        stdout_path = worker_run_dir(plan_dir, run_id) / "transport.stdout"
        metadata = (
            claude_transport_metadata(stdout_path.read_text(), session["session_id"])
            if stdout_path.is_file()
            else None
        )
        return commit_worker_session_turn(
            plan_dir, session, run_id=run_id, turn_index=turn_index,
            instruction_path=instruction_path, outcome=outcome,
            transport_metadata=metadata, failure=failure,
        )
    finally:
        release_worker_session_lease(lease)


def validate_top_level_plan_review_contract(
    request: dict[str, Any],
) -> dict[str, Any] | None:
    contract = request.get("review_contract")
    if contract is None:
        return None
    if (
        not isinstance(contract, dict)
        or set(contract) != {
            "schema_version", "kind", "declared_author_model_family",
            "reviewer_profile", "model_policy_sha256", "evidence_roles",
            "dependent_transition",
        }
    ):
        raise ContractError("top-level plan review contract has an invalid closed shape")
    expected_profile = {
        "kind": "top_level_plan_audit",
        "model": PLAN_AUDIT_MODEL,
        "reasoning_effort": PLAN_AUDIT_REASONING_EFFORT,
    }
    kind = contract.get("kind")
    evidence_roles = contract.get("evidence_roles")
    if kind == "staged-contract-stage-review-v2":
        expected_evidence_roles = sorted(
            item["purpose"] for item in request.get("context_manifest", [])
        )
        required_staged_roles = STAGED_CP01_EVIDENCE_PROFILE | {
            f"{STAGED_CP01_REVIEW_ROLE_PREFIX}{purpose}"
            for purpose in STAGED_CP01_REVIEW_MATERIAL_PURPOSES
        }
        if not required_staged_roles.issubset(set(expected_evidence_roles)):
            raise ContractError(
                "staged CP-01 review contract lacks substantive review material"
            )
    else:
        expected_evidence_roles = (
            sorted(STAGED_CP01_EVIDENCE_PROFILE)
            if kind == "staged-contract-stage-review-v1"
            else sorted(CHECKPOINT_EVIDENCE_PROFILES[("CP-01", None)])
        )
    if (
        contract.get("schema_version") != SCHEMA_VERSION
        or kind not in {
            "top-level-plan-review-v1", "staged-contract-stage-review-v1",
            "staged-contract-stage-review-v2",
        }
        or contract.get("declared_author_model_family") not in {"MiniMax-M3", "Codex"}
        or contract.get("reviewer_profile") != expected_profile
        or evidence_roles != expected_evidence_roles
        or contract.get("dependent_transition") != "approve_execution"
        or not isinstance(contract.get("model_policy_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", contract["model_policy_sha256"])
    ):
        raise ContractError("top-level plan review contract is invalid")
    if request.get("checkpoint") != "CP-01":
        raise ContractError("top-level plan review contract is only valid for CP-01")
    return contract


def verify_manifest_items(items: Any, *, base_dir: Path) -> list[dict[str, str]]:
    if not isinstance(items, list):
        raise ContractError("artifact manifest must be an array")
    checked: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ContractError("artifact manifest entries must be objects")
        raw_path = item.get("path")
        expected = item.get("sha256")
        if not isinstance(raw_path, str) or not raw_path:
            raise ContractError("artifact path must be a non-empty string")
        path = Path(raw_path)
        if not path.is_absolute():
            path = base_dir / path
        path = path.resolve()
        if not path.is_file():
            raise ContractError(f"artifact does not exist: {path}")
        actual = sha256_file(path)
        if expected is not None and expected != actual:
            raise ContractError(f"artifact hash mismatch: {path}")
        checked.append({
            "path": str(path),
            "sha256": actual,
            "purpose": str(item.get("purpose") or "declared task context"),
        })
    return checked


def verify_source_inventory_manifest_items(
    items: Any, *, base_dir: Path,
) -> list[dict[str, Any]]:
    """Freeze the richer manifest required by source-inventory-validator/6.

    A task input manifest intentionally exposes only path/hash/purpose.  The
    source-inventory content validator additionally needs the exact symbol and
    one-based source line.  Keeping these two shapes separate prevents the
    generic input normalizer from silently discarding scientific citation
    bindings before Worker output validation.
    """
    if not isinstance(items, list) or not items:
        raise ContractError("source-inventory manifest must be a non-empty array")
    checked: list[dict[str, Any]] = []
    seen: set[str] = set()
    required = {"path", "sha256", "symbol", "line_start"}
    optional = {"size_bytes", "line_count"}
    for index, item in enumerate(items):
        if (
            not isinstance(item, dict)
            or not required <= set(item)
            or set(item) - required - optional
        ):
            raise ContractError(
                f"source-inventory manifest entry {index} must bind exactly "
                "path, sha256, symbol, line_start, and optional size metadata"
            )
        raw_path = item.get("path")
        expected = item.get("sha256")
        symbol = item.get("symbol")
        line_start = item.get("line_start")
        if not isinstance(raw_path, str) or not raw_path:
            raise ContractError("source-inventory manifest path must be non-empty")
        declared_path = Path(raw_path)
        if not declared_path.is_absolute():
            declared_path = base_dir / declared_path
        cursor = declared_path
        while True:
            if cursor.is_symlink():
                raise ContractError(
                    "source-inventory manifest source path must not traverse "
                    f"a symlink: {cursor}"
                )
            if cursor == cursor.parent:
                break
            cursor = cursor.parent
        path = declared_path.resolve()
        canonical = str(path)
        if canonical in seen or not path.is_file():
            raise ContractError(
                f"source-inventory manifest source is unavailable or repeated: {path}"
            )
        if not isinstance(expected, str) or SHA256_RE.fullmatch(expected) is None:
            raise ContractError("source-inventory manifest sha256 is invalid")
        source_bytes = path.read_bytes()
        if hashlib.sha256(source_bytes).hexdigest() != expected:
            raise ContractError(f"source-inventory manifest hash mismatch: {path}")
        try:
            lines = source_bytes.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise ContractError(
                f"source-inventory manifest must reference UTF-8 text: {path}"
            ) from exc
        if (
            not isinstance(symbol, str)
            or SYMBOL_RE.fullmatch(symbol) is None
            or isinstance(line_start, bool)
            or not isinstance(line_start, int)
            or not 1 <= line_start <= len(lines)
            or not symbol_occurs_on_line(symbol, lines[line_start - 1])
        ):
            raise ContractError(
                f"source-inventory manifest entry {index} symbol/line_start is not exact"
            )
        size_bytes = item.get("size_bytes", len(source_bytes))
        line_count = item.get("line_count", len(lines))
        if (
            ("size_bytes" in item and (
                isinstance(size_bytes, bool) or not isinstance(size_bytes, int)
            ))
            or ("line_count" in item and (
                isinstance(line_count, bool) or not isinstance(line_count, int)
            ))
            or size_bytes != len(source_bytes)
            or line_count != len(lines)
        ):
            raise ContractError(
                f"source-inventory manifest entry {index} size metadata changed"
            )
        checked.append({
            "path": canonical,
            "sha256": expected,
            "symbol": symbol,
            "line_start": line_start,
            **({"size_bytes": size_bytes} if "size_bytes" in item else {}),
            **({"line_count": line_count} if "line_count" in item else {}),
        })
        seen.add(canonical)
    return checked


def validate_schema(instance: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Validate the JSON-Schema subset used by bundled contracts."""
    if "const" in schema and instance != schema["const"]:
        raise ContractError(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise ContractError(f"{path} is not in the allowed enum")
    expected_type = schema.get("type")
    type_checks = {
        "object": lambda: isinstance(instance, dict),
        "array": lambda: isinstance(instance, list),
        "string": lambda: isinstance(instance, str),
        "integer": lambda: isinstance(instance, int) and not isinstance(instance, bool),
        "number": lambda: isinstance(instance, (int, float)) and not isinstance(instance, bool),
        "boolean": lambda: isinstance(instance, bool),
        "null": lambda: instance is None,
    }
    expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
    type_ok = expected_type is None or any(
        type_checks.get(item, lambda: True)() for item in expected_types
    )
    if not type_ok:
        raise ContractError(f"{path} must have type {expected_type}")
    if isinstance(instance, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                raise ContractError(f"{path}.{key} is required")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = set(instance) - set(properties)
            if extras:
                raise ContractError(f"{path} has unexpected properties: {sorted(extras)}")
        for key, value in instance.items():
            if key in properties:
                validate_schema(value, properties[key], f"{path}.{key}")
    if isinstance(instance, list) and "items" in schema:
        if len(instance) < int(schema.get("minItems", 0)):
            raise ContractError(f"{path} has too few items")
        if "maxItems" in schema and len(instance) > int(schema["maxItems"]):
            raise ContractError(f"{path} has too many items")
        if schema.get("uniqueItems") is True:
            encoded = [canonical_json(value) for value in instance]
            if len(encoded) != len(set(encoded)):
                raise ContractError(f"{path} must contain unique items")
        for index, value in enumerate(instance):
            validate_schema(value, schema["items"], f"{path}[{index}]")
    if isinstance(instance, str):
        if len(instance) < int(schema.get("minLength", 0)):
            raise ContractError(f"{path} is too short")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            raise ContractError(f"{path} does not match the required pattern")
        if "maxLength" in schema and len(instance) > int(schema["maxLength"]):
            raise ContractError(f"{path} is too long")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        require_finite_number(instance, path)
        if "minimum" in schema and instance < schema["minimum"]:
            raise ContractError(f"{path} is below minimum")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            raise ContractError(f"{path} is not above exclusive minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            raise ContractError(f"{path} is above maximum")


def validate_supported_schema(schema: Any, path: str = "$") -> None:
    """Reject schema features the bundled deterministic validator cannot enforce."""
    if not isinstance(schema, dict):
        raise ContractError(f"{path} schema must be an object")
    supported = {
        "$schema", "$id", "title", "description", "type", "properties", "required",
        "additionalProperties", "items", "enum", "const", "minLength",
        "pattern", "minimum", "exclusiveMinimum", "maximum", "maxLength",
        "minItems", "maxItems", "uniqueItems",
    }
    unknown = set(schema) - supported
    if unknown:
        raise ContractError(f"{path} uses unsupported schema keywords: {sorted(unknown)}")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ContractError(f"{path}.properties must be an object")
    for key, child in properties.items():
        validate_supported_schema(child, f"{path}.properties.{key}")
    if "items" in schema:
        validate_supported_schema(schema["items"], f"{path}.items")


def extract_structured_claude_output(raw: str) -> Any:
    try:
        value = strict_json_loads(raw)
    except ContractError as exc:
        raise ContractError(f"Claude Code returned invalid JSON: {exc}") from exc
    if isinstance(value, dict) and "structured_output" in value:
        return value["structured_output"]
    if isinstance(value, dict) and isinstance(value.get("result"), (dict, list)):
        return value["result"]
    return value


def plan_identity(plan_dir: Path) -> str:
    manifest = read_json(plan_dir / "resource_manifest.json")
    plan_id = manifest.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise ContractError("resource_manifest.json must contain plan_id")
    return plan_id


def read_human_key(path: Path) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise ContractError("human key must be a regular non-symlink file")
        mode = path.stat().st_mode & 0o777
        key = path.read_bytes()
    except FileNotFoundError as exc:
        raise ContractError(f"human key file not found: {path}") from exc
    if os.name == "posix" and mode != 0o600:
        raise ContractError("human key file mode must be exactly 0600")
    if len(key) < 32:
        raise ContractError("human key must contain at least 32 bytes")
    return key


def human_signature(payload: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, canonical_json(payload), hashlib.sha256).hexdigest()


def verify_human_record(
    plan_dir: Path,
    record_path: Path,
    key_file: Path,
    *,
    expected_action: str | None = None,
    reserve_replay: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    record = read_json(record_path)
    validate_schema(record, read_json(HUMAN_ACTION_SCHEMA))
    key = read_human_key(key_file)
    signature = record.pop("signature")
    try:
        if record["key_id"] != hashlib.sha256(key).hexdigest()[:16]:
            raise ContractError("human action key_id mismatch")
        if not hmac.compare_digest(signature, human_signature(record, key)):
            raise ContractError("human action signature mismatch")
    finally:
        record["signature"] = signature
    if record["plan_id"] != plan_identity(plan_dir):
        raise ContractError("human action is for another plan")
    if expected_action is not None and record["action"] != expected_action:
        raise ContractError(f"human action must be {expected_action}")
    issued = parse_utc(record["issued_at"])
    expires = parse_utc(record["expires_at"])
    if not 1 <= (expires - issued).total_seconds() <= 3600:
        raise ContractError("human action lifetime must be between 1 and 3600 seconds")
    if issued > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ContractError("human action issued_at is unreasonably in the future")
    if expires <= datetime.now(timezone.utc):
        raise ContractError("human action has expired")
    replay = plan_dir / "state" / "human_action_replay.json"
    pair = {"record_id": record["record_id"], "nonce": record["nonce"]}
    lock_path = plan_dir / "state" / ".human_action.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = read_json(replay) if replay.exists() else {"schema_version": 1, "used": []}
        if pair in state.get("used", []):
            raise ContractError("human action record was already applied")
        if reserve_replay:
            state.setdefault("used", []).append(pair)
            state["updated_at"] = utc_now()
            atomic_write_json(replay, state)
    return record, pair


def read_validated_human_record(
    plan_dir: Path, record_path: Path, key_file: Path, expected_action: str | None,
) -> tuple[dict[str, Any], str]:
    try:
        raw = record_path.read_bytes()
        record = strict_json_loads(raw)
    except (FileNotFoundError, ContractError) as exc:
        raise ContractError(f"invalid human action record: {record_path}") from exc
    if not isinstance(record, dict):
        raise ContractError("human action record must be an object")
    validate_schema(record, read_json(HUMAN_ACTION_SCHEMA))
    key = read_human_key(key_file)
    payload = {key_name: value for key_name, value in record.items() if key_name != "signature"}
    if record["key_id"] != hashlib.sha256(key).hexdigest()[:16]:
        raise ContractError("human action key_id mismatch")
    if not hmac.compare_digest(record["signature"], human_signature(payload, key)):
        raise ContractError("human action signature mismatch")
    if record["plan_id"] != plan_identity(plan_dir):
        raise ContractError("human action is for another plan")
    if expected_action and record["action"] != expected_action:
        raise ContractError(f"human action must be {expected_action}")
    issued, expires = parse_utc(record["issued_at"]), parse_utc(record["expires_at"])
    if not 1 <= (expires - issued).total_seconds() <= 3600:
        raise ContractError("human action lifetime must be between 1 and 3600 seconds")
    if issued > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ContractError("human action issued_at is unreasonably in the future")
    if expires <= datetime.now(timezone.utc):
        raise ContractError("human action has expired")
    return record, hashlib.sha256(raw).hexdigest()


def append_jsonl_once(path: Path, key: str, value: str, entry: dict[str, Any]) -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and strict_json_loads(line).get(key) == value:
                return
    append_jsonl(path, entry)


def validate_applied_action_receipt(
    plan_dir: Path, receipt_path: Path, expected_action: str,
) -> dict[str, Any]:
    receipt = read_json(receipt_path)
    record_id = receipt.get("record_id")
    canonical = plan_dir / "state" / "human_actions" / "applied" / f"{record_id}.json"
    if receipt_path.resolve() != canonical.resolve() and receipt.get("receipt_path") != str(canonical):
        raise ContractError("action receipt is not a canonical applied receipt")
    applied = read_json(canonical)
    if receipt != applied and receipt.get("record_sha256") != applied.get("record_sha256"):
        raise ContractError("action receipt differs from canonical applied receipt")
    if applied.get("plan_id") != plan_identity(plan_dir) or applied.get("action") != expected_action:
        raise ContractError("applied action receipt correlation mismatch")
    audit = plan_dir / "state" / "human_action_audit.jsonl"
    entries = [strict_json_loads(line) for line in audit.read_text().splitlines() if line.strip()] if audit.exists() else []
    match = next((entry for entry in entries if entry.get("record_id") == record_id), None)
    if match is None or any(
        match.get(field) != applied.get(field)
        for field in ("plan_id", "action", "record_id", "record_sha256")
    ):
        raise ContractError("action receipt is absent from authenticated audit")
    source = Path(applied.get("source_record_path", ""))
    if not source.is_file() or sha256_file(source) != applied.get("record_sha256"):
        raise ContractError("applied action source record hash changed")
    return applied


def command_validate_action_receipt(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    receipt = validate_applied_action_receipt(plan_dir, Path(args.receipt).resolve(), args.action)
    return {"ok": True, "receipt": receipt}


def command_create_human_action(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    if args.action not in HUMAN_ACTIONS:
        raise ContractError("unsupported human action")
    if not 1 <= args.expires_in <= 3600:
        raise ContractError("expires_in must be between 1 and 3600 seconds")
    key = read_human_key(Path(args.key_file).resolve())
    now = datetime.now(timezone.utc).replace(microsecond=0)
    record_id = args.record_id or f"har_{uuid.uuid4().hex}"
    details: dict[str, Any] = {}
    if args.reason:
        details["reason"] = args.reason
    if args.worker_run_id:
        details["worker_run_id"] = args.worker_run_id
    if args.resource_id:
        details["resource_id"] = args.resource_id
    for name in (
        "binding_sha256", "contract_version", "stage_id",
        "contract_sha256", "stage_envelope_sha256", "evidence_id",
    ):
        value = getattr(args, name, None)
        if value:
            details[name] = value
    continuation_stage_ids = getattr(args, "continuation_stage_id", []) or []
    continuation_stage_limit = getattr(args, "continuation_stage_limit", None)
    if continuation_stage_ids or continuation_stage_limit is not None:
        if args.action != "authorize_contract":
            raise ContractError(
                "bounded continuation authority is valid only on authorize_contract"
            )
        if continuation_stage_limit != 1 or len(continuation_stage_ids) != 1:
            raise ContractError(
                "unattended continuation must authorize exactly one next stage"
            )
        next_stage_id = staged_require_id(
            continuation_stage_ids[0], "continuation_stage_id",
        )
        if next_stage_id == args.stage_id:
            raise ContractError("continuation stage must differ from the first stage")
        details["bounded_continuation_authority"] = {
            "schema_version": 1,
            "allowed_stage_ids": [next_stage_id],
            "max_automatic_crossings": 1,
            "silence_is_approval": False,
        }
    if bool(args.authorization_proposal) != bool(args.prepared_operation_id):
        raise ContractError("authorization proposal and prepared operation id must be supplied together")
    if args.authorization_proposal:
        proposal_path = Path(args.authorization_proposal).resolve()
        canonical_proposal = (plan_dir / "control" / "human_authorization_required.json").resolve()
        if proposal_path != canonical_proposal:
            raise ContractError("human action must bind the canonical authorization proposal")
        proposal = read_json(proposal_path)
        if (
            proposal.get("status") != "AWAITING_HUMAN_AUTHORIZATION"
            or proposal.get("prepared_operation_id") != args.prepared_operation_id
        ):
            raise ContractError("human action proposal operation identity mismatch")
        if args.action == "authorize_contract":
            proposal_expected = {
                "proposal_kind": "authorize_contract",
                "plan_id": args.plan_id,
                "record_id": record_id,
                "contract_version": args.contract_version,
                "contract_sha256": args.contract_sha256,
                "stage_id": args.stage_id,
                "stage_envelope_sha256": args.stage_envelope_sha256,
                "continuation_stage_id": (
                    continuation_stage_ids[0] if continuation_stage_ids else None
                ),
                "continuation_stage_limit": continuation_stage_limit or 0,
            }
            if any(
                proposal.get(field) != value
                for field, value in proposal_expected.items()
            ):
                raise ContractError(
                    "human action flags do not match the canonical "
                    "authorization proposal"
                )
        details.update({
            "authorization_proposal_path": str(proposal_path),
            "authorization_proposal_sha256": sha256_file(proposal_path),
            "prepared_operation_id": args.prepared_operation_id,
        })
    if args.action == "cleanup_resource":
        manifest = read_json(plan_dir / "resource_manifest.json")
        resource = next(
            (item for item in manifest.get("resources", [])
             if isinstance(item, dict) and item.get("resource_id") == args.resource_id),
            None,
        )
        if resource is None:
            raise ContractError("cleanup_resource requires a declared --resource-id")
        path = normalize_owned_path(plan_dir, str(resource.get("path", "")))
        if path.is_symlink() or not path.is_file():
            raise ContractError("cleanup_resource requires an existing regular non-symlink file")
        stat = path.stat()
        generation = str(resource.get("ownership_generation", resource.get("ownership_nonce", "")))
        if not generation:
            raise ContractError("cleanup resource requires an ownership generation or nonce")
        details.update({
            "resource_path": str(path), "ownership_generation": generation,
            "ownership_token": hashlib.sha256(
                f"{manifest['plan_id']}\0{path}\0{generation}".encode()
            ).hexdigest(),
            "content_sha256": sha256_file(path),
            "resource_identity": f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}",
        })
    if args.action in {"waive_acceptance", "override_acceptance"}:
        if not args.candidate or not args.verdict or not args.tier:
            raise ContractError("waiver actions require --candidate, --verdict, and --tier")
        candidate = Path(args.candidate).resolve()
        contract_path = plan_dir / "state" / "evaluator_contract.json"
        verdict_path = Path(args.verdict).resolve()
        verdict = read_json(verdict_path)
        canonical_verdict = plan_dir / "state" / "evaluator_verdicts" / f"{verdict.get('candidate_id', '')}.json"
        if verdict_path != canonical_verdict.resolve():
            raise ContractError("waiver verdict must be a canonical evaluator verdict")
        if Path(verdict.get("candidate_path", "")).resolve() != candidate:
            raise ContractError("waiver candidate does not match evaluator verdict")
        details.update({
            "candidate_path": str(candidate),
            "candidate_sha256": sha256_file(candidate),
            "evaluator_contract_path": str(contract_path.resolve()),
            "evaluator_contract_sha256": sha256_file(contract_path),
            "evaluator_verdict_path": str(verdict_path),
            "evaluator_verdict_sha256": sha256_file(verdict_path),
            "tier": args.tier,
            "scope": "negative_result" if args.negative_result else "acceptance_override",
        })
        if args.negative_result and args.tier != "arxiv":
            raise ContractError("negative-result waiver is arxiv-only")
    if args.action == "authorize_evaluator_change":
        if not args.learning_proposal:
            raise ContractError(
                "authorize_evaluator_change requires --learning-proposal"
            )
        proposal_path = normalize_owned_path(
            plan_dir, str(Path(args.learning_proposal).resolve()),
        )
        if proposal_path.is_symlink() or not proposal_path.is_file():
            raise ContractError(
                "evaluator-change proposal must be an existing regular file"
            )
        details.update({
            "learning_proposal_path": str(proposal_path),
            "learning_proposal_sha256": sha256_file(proposal_path),
            "learning_target_kind": "evaluator",
        })
    if args.action == "authorize_frontier_capacity":
        additions = {
            "calls": require_non_negative_int(
                args.add_frontier_calls, "add_frontier_calls",
            ),
            "input_tokens": require_non_negative_int(
                args.add_frontier_input_tokens,
                "add_frontier_input_tokens",
            ),
            "output_tokens": require_non_negative_int(
                args.add_frontier_output_tokens,
                "add_frontier_output_tokens",
            ),
        }
        if any(value <= 0 for value in additions.values()):
            raise ContractError(
                "frontier capacity additions must all be positive"
            )
        if not staged_is_active(plan_dir):
            raise ContractError(
                "frontier capacity authorization requires active staged research"
            )
        state = staged_load_state(plan_dir)
        global_path = frontier_root(plan_dir) / "budget.json"
        capacity_path = staged_root(plan_dir) / "capacity-ledger.json"
        usage_path = (
            staged_stage_dir(plan_dir, state["active_stage_id"])
            / "usage-ledger.json"
        )
        global_image = (
            read_json(global_path) if global_path.exists()
            else empty_frontier_budget_image()
        )
        capacity = read_json(capacity_path)
        staged_validate_capacity(capacity)
        usage = read_json(usage_path)
        details.update({
            "scope": "prospective_frontier_request_ids",
            "policy_sha256": sha256_file(policy_path(plan_dir)),
            "active_stage_id": state["active_stage_id"],
            "active_stage_envelope_sha256": state[
                "active_stage_envelope_sha256"
            ],
            "global_budget_path": str(global_path),
            "global_budget_sha256": sha256_json(global_image),
            "staged_capacity_path": str(capacity_path),
            "staged_capacity_sha256": sha256_json(capacity),
            "stage_usage_path": str(usage_path),
            "stage_usage_sha256": sha256_json(usage),
            "additions": additions,
        })
    payload = {
        "schema_version": 1,
        "record_id": record_id,
        "plan_id": args.plan_id,
        "action": args.action,
        "nonce": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(seconds=args.expires_in)).isoformat().replace("+00:00", "Z"),
        "actor": args.actor or os.environ.get("USER", "human"),
        "key_id": hashlib.sha256(key).hexdigest()[:16],
        "details": details,
    }
    if payload["plan_id"] != plan_identity(plan_dir):
        raise ContractError("plan_id does not match resource manifest")
    record = {**payload, "signature": human_signature(payload, key)}
    validate_schema(record, read_json(HUMAN_ACTION_SCHEMA))
    target = plan_dir / "control" / "human_actions" / "pending" / f"{record_id}.json"
    if target.exists():
        raise ContractError("human action record_id already exists")
    atomic_write_json(target, record, immutable=True)
    return {"ok": True, "record_path": str(target), "record_id": record_id}


def worker_run_dir(plan_dir: Path, run_id: str, *, must_exist: bool = True) -> Path:
    if not WORKER_ID_RE.fullmatch(run_id):
        raise ContractError("invalid worker_run_id")
    root = (plan_dir / "state" / "worker_runs").resolve()
    candidate = root / run_id
    if candidate.is_symlink():
        raise ContractError("worker run directory must not be a symlink")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ContractError("worker run path escapes state/worker_runs") from exc
    if must_exist and not resolved.is_dir():
        raise ContractError(f"worker run not found: {run_id}")
    return resolved


def worker_status_path(plan_dir: Path, run_id: str, *, must_exist: bool = True) -> Path:
    return worker_run_dir(plan_dir, run_id, must_exist=must_exist) / "status.json"


def require_controller_not_stopped(plan_dir: Path) -> None:
    controller_path = plan_dir / "state" / "controller.json"
    if (
        controller_path.is_file()
        and read_json(controller_path).get("status") == "stopped"
    ):
        raise ContractError("plan is stopped by canonical human lifecycle state")


def observe_process_identity(pid: int) -> dict[str, Any] | None:
    """Return an OS-verifiable process identity without trusting a stored PID."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
        process_group_id = os.getpgid(pid)
    except (ProcessLookupError, PermissionError, OSError):
        return None
    values: dict[str, str] = {}
    for field, column in (("os_started_at", "lstart="), ("os_command", "command=")):
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", column],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        values[field] = proc.stdout.strip()
    identity = {
        "pid": pid,
        "process_group_id": process_group_id,
        "os_started_at": values["os_started_at"],
        "os_command_sha256": hashlib.sha256(
            values["os_command"].encode("utf-8")
        ).hexdigest(),
    }
    return {**identity, "identity_sha256": sha256_json(identity)}


def worker_process_observation(status: dict[str, Any]) -> dict[str, Any]:
    stored = status.get("process_identity")
    pid = status.get("pid")
    current = observe_process_identity(pid) if isinstance(pid, int) else None
    if not isinstance(stored, dict):
        match: bool | None = None
        reason = "legacy_worker_without_process_identity"
    elif current is None:
        match = False
        reason = "process_absent"
    else:
        match = current == stored
        reason = "matched" if match else "process_identity_mismatch"
    return {
        "declared_status": status.get("status"),
        "alive": current is not None,
        "identity_match": match,
        "reason": reason,
        "stored_identity": stored,
        "observed_identity": current,
    }


def signal_bound_worker_process(
    status: dict[str, Any], *, term_grace_seconds: float,
) -> dict[str, Any]:
    """Terminate only the exact process group frozen in Worker status."""
    observation = worker_process_observation(status)
    if observation["reason"] == "legacy_worker_without_process_identity":
        return {"outcome": "identity_unavailable", "observation": observation}
    if not observation["alive"]:
        return {"outcome": "already_absent", "observation": observation}
    if observation["identity_match"] is not True:
        return {"outcome": "identity_mismatch", "observation": observation}
    stored = observation["stored_identity"]
    assert isinstance(stored, dict)
    process_group_id = stored["process_group_id"]
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return {"outcome": "already_absent", "observation": observation}
    deadline = time.monotonic() + term_grace_seconds
    while time.monotonic() < deadline:
        if observe_process_identity(stored["pid"]) is None:
            return {"outcome": "terminated", "signal": "SIGTERM"}
        time.sleep(0.05)
    current = observe_process_identity(stored["pid"])
    if current != stored:
        return {
            "outcome": "identity_changed_after_sigterm",
            "observation": worker_process_observation(status),
        }
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        return {"outcome": "terminated", "signal": "SIGTERM"}
    kill_deadline = time.monotonic() + max(1.0, term_grace_seconds)
    while time.monotonic() < kill_deadline:
        if observe_process_identity(stored["pid"]) is None:
            return {"outcome": "terminated", "signal": "SIGKILL"}
        time.sleep(0.05)
    return {
        "outcome": "still_running",
        "observation": worker_process_observation(status),
    }


def update_worker_status(
    plan_dir: Path, run_id: str, desired: str, updates: dict[str, Any],
) -> dict[str, Any]:
    run_dir = worker_run_dir(plan_dir, run_id)
    lock_path = run_dir / ".status.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        path = run_dir / "status.json"
        current = read_json(path)
        current_state = current.get("status")
        if current_state == "CANCELLED" and desired != "CANCELLED":
            return current
        if current_state == "COMPLETED" and desired == "COMPLETED":
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_mode & 0o777 != 0o444
                or any(current.get(key) != value for key, value in updates.items())
            ):
                raise ContractError("completed worker status changed after terminal commit")
            return current
        if current_state in {"COMPLETED", "FAILED"} and desired != current_state:
            raise ContractError(f"worker terminal status is monotonic: {current_state}")
        current.update(updates)
        current["status"] = desired
        current["updated_at"] = utc_now()
        atomic_write_json(path, current, immutable=desired == "COMPLETED")
        return current


def apply_frontier_capacity_authorization(
    plan_dir: Path, record: dict[str, Any],
) -> dict[str, Any]:
    """Roll a signed, additive staged capacity grant forward exactly once."""
    details = record["details"]
    required = {
        "scope", "policy_sha256", "active_stage_id",
        "active_stage_envelope_sha256",
        "global_budget_path", "global_budget_sha256",
        "staged_capacity_path", "staged_capacity_sha256",
        "stage_usage_path", "stage_usage_sha256", "additions",
    }
    if not required.issubset(details):
        raise ContractError("frontier capacity authorization is incomplete")
    if (
        details["scope"] != "prospective_frontier_request_ids"
        or details["policy_sha256"] != sha256_file(policy_path(plan_dir))
    ):
        raise ContractError("frontier capacity policy binding mismatch")
    additions = details["additions"]
    if (
        not isinstance(additions, dict)
        or set(additions) != {"calls", "input_tokens", "output_tokens"}
    ):
        raise ContractError("frontier capacity additions have an invalid shape")
    for field, value in additions.items():
        if require_non_negative_int(value, f"capacity additions.{field}") <= 0:
            raise ContractError("frontier capacity additions must all be positive")
    if not staged_is_active(plan_dir):
        raise ContractError("frontier capacity authorization lost staged state")
    journal_path = (
        staged_root(plan_dir) / "capacity-topup-journals"
        / f"{record['record_id']}.json"
    )
    with staged_transaction_lock(plan_dir):
        with budget_lock(plan_dir):
            state = staged_load_state(plan_dir)
            if (
                state["active_stage_id"] != details["active_stage_id"]
                or state["active_stage_envelope_sha256"]
                != details["active_stage_envelope_sha256"]
            ):
                raise ContractError(
                    "frontier capacity active stage or envelope changed"
                )
            global_path = Path(details["global_budget_path"])
            capacity_path = Path(details["staged_capacity_path"])
            usage_path = Path(details["stage_usage_path"])
            expected_paths = {
                "global": frontier_root(plan_dir) / "budget.json",
                "staged": staged_root(plan_dir) / "capacity-ledger.json",
                "usage": (
                    staged_stage_dir(plan_dir, state["active_stage_id"])
                    / "usage-ledger.json"
                ),
            }
            if any(
                path.resolve() != expected_paths[label].resolve()
                for label, path in (
                    ("global", global_path),
                    ("staged", capacity_path),
                    ("usage", usage_path),
                )
            ):
                raise ContractError("frontier capacity ledger path mismatch")
            if journal_path.exists():
                journal = read_json(journal_path)
                if (
                    journal.get("record_id") != record["record_id"]
                    or journal.get("record_sha256") != sha256_json(record)
                ):
                    raise ContractError("frontier capacity journal correlation mismatch")
            else:
                global_before = (
                    read_json(global_path) if global_path.exists()
                    else empty_frontier_budget_image()
                )
                capacity_before = read_json(capacity_path)
                usage_before = read_json(usage_path)
                staged_validate_capacity(capacity_before)
                expected_hashes = {
                    "global": details["global_budget_sha256"],
                    "staged": details["staged_capacity_sha256"],
                    "usage": details["stage_usage_sha256"],
                }
                current = {
                    "global": global_before,
                    "staged": capacity_before,
                    "usage": usage_before,
                }
                if any(
                    sha256_json(current[label]) != expected_hashes[label]
                    for label in current
                ):
                    raise ContractError(
                        "frontier capacity authorization ledger binding changed"
                    )
                global_after = json.loads(json.dumps(global_before))
                prior_global_additions = global_after.setdefault(
                    "authorized_capacity", {
                        "calls": 0, "input_tokens": 0, "output_tokens": 0,
                    },
                )
                authorization_ids = global_after.setdefault(
                    "capacity_authorization_ids", [],
                )
                if record["record_id"] in authorization_ids:
                    raise ContractError(
                        "frontier capacity exists without its top-up journal"
                    )
                for field in additions:
                    prior_global_additions[field] += additions[field]
                authorization_ids.append(record["record_id"])
                global_after["updated_at"] = utc_now()

                capacity_after = json.loads(json.dumps(capacity_before))
                if capacity_after.get("schema_version") == 1:
                    capacity_after["remaining_calls"] += additions["calls"]
                capacity_after.setdefault("capacity_authorization_ids", []).append(
                    record["record_id"]
                )
                if capacity_after.get("schema_version") == 1:
                    capacity_after.setdefault(
                        "authorized_additions", {"calls": 0},
                    )["calls"] += additions["calls"]
                staged_validate_capacity(capacity_after)

                usage_after = json.loads(json.dumps(usage_before))
                usage_after["limits"]["review_tokens"] += additions[
                    "output_tokens"
                ]
                usage_after.setdefault("capacity_authorization_ids", []).append(
                    record["record_id"]
                )
                usage_after.setdefault(
                    "authorized_additions", {"review_tokens": 0},
                )["review_tokens"] += additions["output_tokens"]
                usage_after["updated_at"] = utc_now()

                def images(before: Any, after: Any) -> dict[str, Any]:
                    return {
                        "before": before, "before_sha256": sha256_json(before),
                        "after": after, "after_sha256": sha256_json(after),
                    }

                journal = {
                    "schema_version": 1, "phase": "PREPARED",
                    "record_id": record["record_id"],
                    "record_sha256": sha256_json(record),
                    "additions": additions,
                    "global": images(global_before, global_after),
                    "staged": images(capacity_before, capacity_after),
                    "usage": images(usage_before, usage_after),
                    "prepared_at": utc_now(),
                }
                atomic_write_json(journal_path, journal)

            for label, path in (
                ("global", global_path),
                ("usage", usage_path),
                ("staged", capacity_path),
            ):
                image = journal[label]
                current_value = (
                    read_json(path) if path.exists()
                    else empty_frontier_budget_image()
                )
                current_hash = sha256_json(current_value)
                if current_hash == image["before_sha256"]:
                    atomic_write_json(path, image["after"])
                elif current_hash != image["after_sha256"]:
                    raise ContractError(
                        f"frontier capacity {label} ledger is irreconcilable"
                    )
                if os.environ.get(
                    f"HARNESS_FAULT_AFTER_CAPACITY_TOPUP_{label.upper()}"
                ) == "1":
                    os._exit(91)
            _staged_ensure_audit_once_locked(
                plan_dir, "frontier_capacity_authorized",
                {"record_id": record["record_id"]},
                {
                    "additions": additions,
                    "prospective_only": True,
                    "global_after_sha256": journal["global"]["after_sha256"],
                    "staged_after_sha256": journal["staged"]["after_sha256"],
                    "usage_after_sha256": journal["usage"]["after_sha256"],
                },
            )
            journal.update({
                "phase": "COMMITTED",
                "committed_at": journal.get("committed_at", utc_now()),
            })
            atomic_write_json(journal_path, journal)
            return {
                "journal_path": str(journal_path),
                "journal_sha256": sha256_file(journal_path),
                "additions": additions,
            }


def command_apply_human_action(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    record_path = Path(args.record).resolve()
    lock_path = plan_dir / "state" / ".human_action.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        # A PREPARED journal is the recovery authority. It binds the original
        # bytes and rolls forward without accepting a different/expired record.
        record_id_hint = record_path.stem
        journal_path = plan_dir / "state" / "human_actions" / "journal" / f"{record_id_hint}.json"
        journal = read_json(journal_path) if journal_path.exists() else None
        was_recovery = journal is not None
        if journal:
            if journal.get("operation_id") != getattr(args, "operation_id", None):
                raise ContractError("human action recovery operation identity mismatch")
            if journal.get("phase") == "COMMITTED":
                if not getattr(args, "operation_id", None):
                    raise ContractError("human action record was already applied")
                if sha256_file(record_path) != journal.get("record_sha256"):
                    raise ContractError("committed human action source bytes changed")
                record = journal.get("record", {})
                receipt = journal.get("receipt", {})
                if (
                    (args.expected_action and record.get("action") != args.expected_action)
                    or (args.worker_run_id and receipt.get("worker_run_id") != args.worker_run_id)
                ):
                    raise ContractError("committed human action invocation mismatch")
                exposed = {
                    key: receipt[key] for key in ("receipt_path", "authorization_path", "waiver_path")
                    if key in receipt
                }
                return {
                    "ok": True, "idempotent": True, "recovered": True,
                    "receipt": receipt, **exposed,
                }
            if sha256_file(record_path) != journal.get("record_sha256"):
                raise ContractError("prepared human action source bytes changed")
            record = journal["record"]
            receipt = journal["receipt"]
            run_id = journal.get("worker_run_id")
        else:
            record, record_hash = read_validated_human_record(
                plan_dir, record_path, Path(args.key_file).resolve(), args.expected_action,
            )
            action = record["action"]
            details = record["details"]
            run_id = args.worker_run_id or details.get("worker_run_id")
            if action == "cancel_worker":
                if not run_id or details.get("worker_run_id") != run_id:
                    raise ContractError("cancel_worker record and argument must name the same run")
                status = read_json(worker_status_path(plan_dir, run_id))
                if status.get("status") in {"COMPLETED", "FAILED", "CANCELLED"}:
                    raise ContractError("worker is already terminal")
            elif args.worker_run_id:
                raise ContractError("worker_run_id is valid only for cancel_worker")
            if action == "cleanup_resource" and not details.get("resource_id"):
                raise ContractError("cleanup_resource requires details.resource_id")
            if action == "cleanup_resource":
                cleanup_path = Path(details.get("resource_path", ""))
                if cleanup_path != normalize_owned_path(plan_dir, str(cleanup_path)):
                    raise ContractError("cleanup resource path correlation mismatch")
                if cleanup_path.is_symlink() or not cleanup_path.is_file():
                    raise ContractError("cleanup resource changed before authorization application")
                cleanup_stat = cleanup_path.stat()
                identity = f"{cleanup_stat.st_dev}:{cleanup_stat.st_ino}:{cleanup_stat.st_size}:{cleanup_stat.st_mtime_ns}"
                if sha256_file(cleanup_path) != details.get("content_sha256") or identity != details.get("resource_identity"):
                    raise ContractError("cleanup resource content or identity changed before authorization application")
            if action in {"waive_acceptance", "override_acceptance"}:
                required = {
                    "candidate_path", "candidate_sha256", "evaluator_contract_path",
                    "evaluator_contract_sha256", "evaluator_verdict_path",
                    "evaluator_verdict_sha256", "tier", "scope", "reason",
                }
                if not required.issubset(details):
                    raise ContractError(f"waiver details missing: {sorted(required - set(details))}")
                if sha256_file(Path(details["candidate_path"])) != details["candidate_sha256"]:
                    raise ContractError("waiver candidate hash mismatch")
                contract_path = Path(details["evaluator_contract_path"]).resolve()
                verdict_path = Path(details["evaluator_verdict_path"]).resolve()
                if contract_path != (plan_dir / "state" / "evaluator_contract.json").resolve():
                    raise ContractError("waiver evaluator contract path mismatch")
                if sha256_file(contract_path) != details["evaluator_contract_sha256"]:
                    raise ContractError("waiver evaluator contract hash mismatch")
                if sha256_file(verdict_path) != details["evaluator_verdict_sha256"]:
                    raise ContractError("waiver evaluator verdict hash mismatch")
                verdict = read_json(verdict_path)
                if Path(verdict.get("candidate_path", "")).resolve() != Path(details["candidate_path"]).resolve():
                    raise ContractError("waiver verdict candidate mismatch")
            if action == "authorize_evaluator_change":
                required = {
                    "learning_proposal_path", "learning_proposal_sha256",
                    "learning_target_kind", "reason",
                }
                if not required.issubset(details):
                    raise ContractError(
                        "evaluator-change authorization details are incomplete"
                    )
                proposal_path = Path(details["learning_proposal_path"])
                if (
                    details["learning_target_kind"] != "evaluator"
                    or proposal_path.is_symlink()
                    or not proposal_path.is_file()
                    or sha256_file(proposal_path)
                    != details["learning_proposal_sha256"]
                ):
                    raise ContractError(
                        "evaluator-change proposal hash changed before authorization"
                    )
            applied_at = utc_now()
            canonical = plan_dir / "state" / "human_actions" / "applied" / f"{record['record_id']}.json"
            receipt = {
                "schema_version": 1, "record_id": record["record_id"], "plan_id": record["plan_id"],
                "action": action, "nonce": record["nonce"], "record_sha256": record_hash,
                "source_record_path": str(record_path), "receipt_path": str(canonical),
                "details": details, "applied_at": applied_at,
            }
            if run_id:
                receipt["worker_run_id"] = run_id
            if details.get("resource_id"):
                receipt["resource_id"] = details["resource_id"]
            if action in {"waive_acceptance", "override_acceptance"}:
                receipt["waiver_path"] = str(plan_dir / "state" / "waivers" / f"{record['record_id']}.json")
            if action == "cleanup_resource":
                receipt["authorization_path"] = str(plan_dir / "state" / "cleanup_authorizations" / f"{record['record_id']}.json")
            journal_path = plan_dir / "state" / "human_actions" / "journal" / f"{record['record_id']}.json"
            journal = {
                "schema_version": 1, "phase": "PREPARED", "record": record,
                "record_sha256": record_hash, "receipt": receipt, "worker_run_id": run_id,
                "operation_id": getattr(args, "operation_id", None),
                "prepared_at": applied_at,
            }
            atomic_write_json(journal_path, journal)
        if getattr(args, "simulate_crash_after", None) == "prepared":
            raise ContractError("simulated crash after PREPARED journal")

        replay_path = plan_dir / "state" / "human_action_replay.json"
        replay = read_json(replay_path) if replay_path.exists() else {"schema_version": 1, "used": []}
        pair = {"record_id": record["record_id"], "nonce": record["nonce"]}
        if pair not in replay.get("used", []):
            replay.setdefault("used", []).append(pair)
            replay["updated_at"] = utc_now()
            atomic_write_json(replay_path, replay)
        if getattr(args, "simulate_crash_after", None) == "replay":
            raise ContractError("simulated crash after replay reservation")

        action, details = record["action"], record["details"]
        if action in {"pause", "resume", "stop"}:
            controller_path = plan_dir / "state" / "controller.json"
            controller = read_json(controller_path) if controller_path.exists() else {"schema_version": 1}
            controller.update({
                "status": {"pause": "paused", "resume": "running", "stop": "stopped"}[action],
                "updated_at": receipt["applied_at"], "authority_record_id": record["record_id"],
            })
            atomic_write_json(controller_path, controller)
        elif action == "cancel_worker":
            worker_status = read_json(worker_status_path(plan_dir, run_id))
            termination = signal_bound_worker_process(
                worker_status, term_grace_seconds=5.0,
            )
            receipt["process_termination"] = termination
            update_worker_status(plan_dir, run_id, "CANCELLED", {
                "completed_at": receipt["applied_at"],
                "authority_record_id": record["record_id"],
                "process_termination": termination,
            })
        elif action == "authorize_frontier_capacity":
            receipt["capacity_topup"] = apply_frontier_capacity_authorization(
                plan_dir, record,
            )
        canonical = Path(receipt["receipt_path"])
        if not canonical.exists():
            atomic_write_json(canonical, receipt, immutable=True)
        if action in {"pause", "resume", "stop"}:
            control_name = {"pause": "pause_requested.json", "resume": "resume_signal.json", "stop": "stop_requested.json"}[action]
            atomic_write_json(plan_dir / "control" / control_name, receipt)
        elif action in {"waive_acceptance", "override_acceptance"}:
            target = plan_dir / "state" / "waivers" / f"{record['record_id']}.json"
            if not target.exists():
                atomic_write_json(target, receipt, immutable=True)
        elif action == "cleanup_resource":
            target = plan_dir / "state" / "cleanup_authorizations" / f"{record['record_id']}.json"
            if not target.exists():
                atomic_write_json(target, receipt, immutable=True)
        if getattr(args, "simulate_crash_after", None) == "mutation":
            raise ContractError("simulated crash after action mutation")

        append_jsonl_once(
            plan_dir / "state" / "human_action_audit.jsonl", "record_id", record["record_id"], receipt,
        )
        if getattr(args, "simulate_crash_after", None) == "audit":
            raise ContractError("simulated crash after action audit")
        journal.update({"phase": "COMMITTED", "committed_at": utc_now()})
        atomic_write_json(journal_path, journal)
        exposed = {
            key: receipt[key] for key in ("receipt_path", "authorization_path", "waiver_path")
            if key in receipt
        }
        return {"ok": True, "recovered": was_recovery, "receipt": receipt, **exposed}


def require_transition_evidence(
    plan_dir: Path, transition_name: str, role_paths: dict[str, Path],
) -> dict[str, Any]:
    for candidate in transition_receipt_candidates(plan_dir, transition_name):
        receipt = check_transition_receipt(
            plan_dir, plan_identity(plan_dir), transition_name, candidate.stem,
        )
        _, request = load_request(plan_dir, receipt["request_id"])
        by_role = {item["purpose"]: item for item in request["context_manifest"]}
        if all(
            (item := by_role.get(role)) is not None
            and Path(item["path"]).resolve() == path.resolve()
            and item["sha256"] == sha256_file(path)
            for role, path in role_paths.items()
        ):
            return receipt
    raise ContractError(f"{transition_name} evidence does not bind the required roles")


def command_run_evaluator(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    supplied_evaluator = Path(args.evaluator).resolve()
    supplied_evidence = Path(args.evidence).resolve()
    candidate = Path(args.candidate).resolve()
    evaluator = supplied_evaluator
    evidence = supplied_evidence
    frozen_contract_path = plan_dir / "state" / "evaluator_contract.json"
    if args.purpose == "candidate" and frozen_contract_path.exists():
        frozen = read_json(frozen_contract_path)
        frozen_body = {
            key: value for key, value in frozen.items() if key != "contract_sha256"
        }
        if frozen.get("contract_sha256") != sha256_json(frozen_body):
            raise ContractError("frozen evaluator contract hash changed")
        if (
            sha256_file(supplied_evaluator) != frozen.get("evaluator_sha256")
            or sha256_file(supplied_evidence) != frozen.get("evidence_sha256")
        ):
            raise ContractError("candidate evaluator inputs differ from the frozen controller materials")
        evaluator = Path(frozen["evaluator_path"])
        evidence = Path(frozen["evidence_path"])
        if (
            sha256_file(evaluator) != frozen["evaluator_sha256"]
            or sha256_file(evidence) != frozen["evidence_sha256"]
        ):
            raise ContractError("frozen controller evaluator materials changed")
    else:
        require_transition_evidence(plan_dir, "freeze_evaluator", {
            "evaluator": evaluator, "evidence_manifest": evidence,
        })
    spec = read_json(evaluator)
    validate_schema(spec, read_json(DECLARATIVE_EVALUATOR_SCHEMA))
    if spec["kind"] != "declarative-evaluator-v1" or spec["operation"] != "read_finite_number":
        raise ContractError("only declarative-evaluator-v1 read_finite_number is supported")
    if spec["source"] != "candidate":
        raise ContractError("declarative evaluator must measure the candidate artifact")
    value: Any = strict_json_loads(candidate.read_text())
    for segment in spec["json_path"]:
        if not isinstance(value, dict) or segment not in value:
            raise ContractError(f"declarative evaluator JSON path is absent: {segment}")
        value = value[segment]
    value = require_finite_number(value, "declarative evaluator value")
    operation_id = getattr(args, "operation_id", None)
    run_id = "evr_" + (operation_id[3:35] if operation_id else uuid.uuid4().hex)
    receipt = {
        "schema_version": 1, "run_id": run_id, "purpose": args.purpose,
        "plan_id": plan_identity(plan_dir), "evaluator_path": str(evaluator),
        "evaluator_sha256": sha256_file(evaluator), "evidence_path": str(evidence),
        "evidence_sha256": sha256_file(evidence), "candidate_path": str(candidate),
        "candidate_sha256": sha256_file(candidate), "metric": spec["metric"],
        "value": value, "evaluator_kind": spec["kind"],
        "operation": spec["operation"], "source": spec["source"],
        "json_path": spec["json_path"], "exit_code": 0, "completed_at": utc_now(),
    }
    target = plan_dir / "state" / "evaluator_runs" / f"{run_id}.json"
    if target.exists():
        prior = read_json(target)
        stable = ("purpose", "plan_id", "evaluator_sha256", "evidence_sha256", "candidate_sha256", "metric", "value")
        if any(prior.get(key) != receipt.get(key) for key in stable):
            raise ContractError("deterministic evaluator run identity collision")
        return {"ok": True, "idempotent": True, "execution_receipt": str(target), **prior}
    atomic_write_json(target, receipt, immutable=True)
    return {"ok": True, "execution_receipt": str(target), **receipt}


def load_evaluator_run(plan_dir: Path, path: Path) -> dict[str, Any]:
    plan_dir = plan_dir.resolve()
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not path.is_file()
        or path.stat().st_mode & 0o777 != 0o444
    ):
        raise ContractError(
            "evaluator execution receipt must be canonical immutable 0444"
        )
    run = read_json(path)
    canonical = plan_dir / "state" / "evaluator_runs" / f"{run.get('run_id', '')}.json"
    if (
        path != canonical
        or run.get("plan_id") != plan_identity(plan_dir)
        or not isinstance(run.get("run_id"), str)
        or canonical.name != f"{run['run_id']}.json"
    ):
        raise ContractError("evaluator execution receipt is not canonical for this plan")
    for field in ("evaluator", "evidence", "candidate"):
        artifact_value = run.get(f"{field}_path")
        artifact = Path(artifact_value) if isinstance(artifact_value, str) else Path()
        try:
            artifact.relative_to(plan_dir)
        except ValueError as exc:
            raise ContractError(
                f"evaluator execution {field} path is not canonical"
            ) from exc
        if (
            not artifact.is_absolute()
            or artifact.is_symlink()
            or not artifact.is_file()
            or sha256_file(artifact) != run.get(f"{field}_sha256")
        ):
            raise ContractError(f"evaluator execution {field} hash changed")
    if run.get("exit_code") != 0:
        raise ContractError("evaluator execution did not complete successfully")
    return run


def freeze_controller_material(plan_dir: Path, source: Path, role: str) -> Path:
    digest = sha256_file(source)
    suffix = source.suffix if source.suffix else ".bin"
    target = (
        plan_dir / "state" / "evaluator_materials"
        / f"{role}-{digest}{suffix}"
    )
    if target.exists():
        if sha256_file(target) != digest:
            raise ContractError(f"canonical {role} material hash changed")
        return target
    atomic_write_bytes(target, source.read_bytes(), immutable=True)
    return target


def command_freeze_evaluator(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    target = plan_dir / "state" / "evaluator_contract.json"
    run = load_evaluator_run(plan_dir, Path(args.execution_receipt).resolve())
    if run.get("purpose") != "calibration":
        raise ContractError("evaluator freeze requires a calibration execution receipt")
    evaluator = Path(run["evaluator_path"])
    evidence = Path(run["evidence_path"])
    receipt = require_transition_evidence(plan_dir, "freeze_evaluator", {
        "evaluator": evaluator, "evidence_manifest": evidence,
        "calibration_candidate": Path(run["candidate_path"]),
    })
    _, request = load_request(plan_dir, receipt["request_id"])
    metric_item = next(
        item for item in request["context_manifest"] if item["purpose"] == "metric_contract"
    )
    metric_path = Path(metric_item["path"])
    metric_contract = read_json(metric_path)
    validate_schema(metric_contract, read_json(METRIC_CONTRACT_SCHEMA))
    require_finite_number(metric_contract["threshold"], "metric contract threshold")
    require_finite_number(run["value"], "calibration value")
    if sha256_file(metric_path) != metric_item["sha256"]:
        raise ContractError("audited metric contract hash changed")
    if run["metric"] != metric_contract["metric"]:
        raise ContractError("calibration metric does not match audited metric contract")
    canonical_evaluator = freeze_controller_material(
        plan_dir, evaluator, "evaluator",
    )
    canonical_evidence = freeze_controller_material(
        plan_dir, evidence, "evidence",
    )
    canonical_metric = freeze_controller_material(
        plan_dir, metric_path, "metric-contract",
    )
    contract = {
        "schema_version": 1,
        "evaluator_sha256": sha256_file(canonical_evaluator),
        "evidence_sha256": sha256_file(canonical_evidence),
        "evaluator_path": str(canonical_evaluator),
        "evidence_path": str(canonical_evidence),
        "metric": metric_contract["metric"],
        "operator": metric_contract["operator"],
        "threshold": metric_contract["threshold"],
        "metric_contract_path": str(canonical_metric),
        "metric_contract_sha256": sha256_file(canonical_metric),
        "source_evaluator_path": str(evaluator),
        "source_evidence_path": str(evidence),
        "source_metric_contract_path": str(metric_path),
        "calibration_execution_sha256": sha256_file(Path(args.execution_receipt).resolve()),
        "calibration_value": run["value"],
        "frozen_at": utc_now(),
    }
    contract["contract_sha256"] = sha256_json(contract)
    if target.exists():
        if read_json(target) != contract:
            # Timestamps are not semantic; compare the already frozen provenance.
            prior = read_json(target)
            for key in set(contract) - {"frozen_at", "contract_sha256"}:
                if prior.get(key) != contract.get(key):
                    raise ContractError("evaluator contract is already frozen with different evidence")
            return {"ok": True, "idempotent": True, "contract_path": str(target), **prior}
    atomic_write_json(target, contract, immutable=True)
    return {"ok": True, "contract_path": str(target), **contract}


def command_record_evaluator_verdict(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    contract = read_json(plan_dir / "state" / "evaluator_contract.json")
    contract_body = {key: value for key, value in contract.items() if key != "contract_sha256"}
    if contract.get("contract_sha256") != sha256_json(contract_body):
        raise ContractError("frozen evaluator contract hash changed")
    if sha256_file(Path(contract["evaluator_path"])) != contract["evaluator_sha256"]:
        raise ContractError("frozen evaluator hash changed")
    if sha256_file(Path(contract["evidence_path"])) != contract["evidence_sha256"]:
        raise ContractError("frozen evidence hash changed")
    if sha256_file(Path(contract["metric_contract_path"])) != contract["metric_contract_sha256"]:
        raise ContractError("frozen metric contract hash changed")
    run_path = Path(args.execution_receipt).resolve()
    run = load_evaluator_run(plan_dir, run_path)
    if run.get("purpose") != "candidate":
        raise ContractError("candidate verdict requires a candidate evaluator execution")
    for field in ("evaluator_sha256", "evidence_sha256", "metric"):
        if run[field] != contract[field]:
            raise ContractError(f"evaluator execution {field} mismatch")
    require_finite_number(contract["threshold"], "frozen threshold")
    require_finite_number(contract["calibration_value"], "frozen calibration value")
    require_finite_number(run["value"], "candidate evaluator value")
    candidate = Path(run["candidate_path"])
    passed = run["value"] >= contract["threshold"] if contract["operator"] == "gte" else run["value"] <= contract["threshold"]
    verdict = {
        "schema_version": 1, "candidate_id": args.candidate_id,
        "evaluator_sha256": run["evaluator_sha256"], "evidence_sha256": run["evidence_sha256"],
        "candidate_sha256": run["candidate_sha256"], "metric": run["metric"],
        "threshold": contract["threshold"], "value": run["value"],
        "verdict": "PASS" if passed else "FAIL", "evaluated_at": run["completed_at"],
        "candidate_path": str(candidate), "contract_sha256": contract["contract_sha256"],
        "execution_receipt_sha256": sha256_file(run_path), "execution_receipt_path": str(run_path),
    }
    validate_schema(verdict, read_json(EVALUATOR_VERDICT_SCHEMA))
    target = plan_dir / "state" / "evaluator_verdicts" / f"{verdict['candidate_id']}.json"
    if target.exists():
        if read_json(target) != verdict:
            prior = read_json(target)
            for key in set(verdict) - {"evaluated_at"}:
                if prior.get(key) != verdict.get(key):
                    raise ContractError("candidate verdict is already recorded with different evidence")
            return {"ok": True, "idempotent": True, "verdict_path": str(target), "verdict_sha256": sha256_file(target)}
    atomic_write_json(target, verdict, immutable=True)
    append_jsonl(plan_dir / "state" / "evaluator_audit.jsonl", {
        "ts": utc_now(), "candidate_id": verdict["candidate_id"], "verdict_sha256": sha256_file(target),
        "execution_receipt_sha256": verdict["execution_receipt_sha256"],
    })
    return {"ok": True, "verdict_path": str(target), "verdict_sha256": sha256_file(target)}


def command_check_scientific_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    verdict_path = Path(args.verdict).resolve()
    verdict = read_json(verdict_path)
    validate_schema(verdict, read_json(EVALUATOR_VERDICT_SCHEMA))
    canonical_verdict = (
        plan_dir / "state" / "evaluator_verdicts"
        / f"{verdict.get('candidate_id', '')}.json"
    )
    if verdict_path != canonical_verdict.resolve():
        raise ContractError("scientific acceptance requires a canonical evaluator verdict")
    contract_path = plan_dir / "state" / "evaluator_contract.json"
    contract = read_json(contract_path)
    contract_body = {
        key: value for key, value in contract.items() if key != "contract_sha256"
    }
    if contract.get("contract_sha256") != sha256_json(contract_body):
        raise ContractError("frozen evaluator contract hash changed")
    run_path = Path(verdict["execution_receipt_path"]).resolve()
    if sha256_file(run_path) != verdict.get("execution_receipt_sha256"):
        raise ContractError("scientific acceptance execution receipt hash changed")
    run = load_evaluator_run(plan_dir, run_path)
    checks = {
        "candidate_sha256": run["candidate_sha256"],
        "evaluator_sha256": run["evaluator_sha256"],
        "evidence_sha256": run["evidence_sha256"],
        "metric": run["metric"],
        "value": run["value"],
        "contract_sha256": contract["contract_sha256"],
    }
    if any(verdict.get(field) != expected for field, expected in checks.items()):
        raise ContractError("scientific verdict is not bound to its evaluator execution")
    if (
        contract.get("evaluator_sha256") != verdict["evaluator_sha256"]
        or contract.get("evidence_sha256") != verdict["evidence_sha256"]
        or contract.get("metric") != verdict["metric"]
        or contract.get("threshold") != verdict["threshold"]
    ):
        raise ContractError("scientific verdict is not bound to the frozen evaluator contract")
    for field in ("evaluator", "evidence", "metric_contract"):
        if sha256_file(Path(contract[f"{field}_path"])) != contract[f"{field}_sha256"]:
            raise ContractError(f"scientific acceptance {field} hash changed")
    candidate_path = Path(verdict["candidate_path"])
    if (
        candidate_path.resolve() != Path(run["candidate_path"]).resolve()
        or sha256_file(candidate_path) != verdict["candidate_sha256"]
    ):
        raise ContractError("scientific acceptance candidate hash changed")
    threshold = require_finite_number(contract["threshold"], "frozen threshold")
    value = require_finite_number(run["value"], "candidate evaluator value")
    passed = value >= threshold if contract["operator"] == "gte" else value <= threshold
    expected_verdict = "PASS" if passed else "FAIL"
    if verdict.get("verdict") != expected_verdict:
        raise ContractError("scientific verdict disagrees with the frozen comparison")
    admission_id: str | None = None
    graph_path = plan_dir / "state" / "durable_loop" / "canonical" / "graph.json"
    if graph_path.exists():
        try:
            graph = read_json(graph_path)
            if graph["evaluator"]["sha256"] != contract["evaluator_sha256"]:
                raise ContractError("durable plan evaluator differs from the frozen evaluator")
            admission = require_durable_autonomy_eligibility(plan_dir)
            admission_id = admission.get("admission_id") if admission else None
        except ContractError:
            record_detected_research_integrity(plan_dir)
            raise
    identity = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "candidate_id": verdict["candidate_id"],
        "decision": expected_verdict,
        "candidate_path": str(candidate_path),
        "candidate_sha256": verdict["candidate_sha256"],
        "evaluator_sha256": verdict["evaluator_sha256"],
        "evidence_sha256": verdict["evidence_sha256"],
        "metric": verdict["metric"],
        "operator": contract["operator"],
        "threshold": threshold,
        "value": value,
        "verdict_path": str(verdict_path),
        "verdict_sha256": sha256_file(verdict_path),
        "contract_path": str(contract_path),
        "contract_sha256": sha256_file(contract_path),
        "execution_receipt_path": str(run_path),
        "execution_receipt_sha256": sha256_file(run_path),
        "evaluator_admission_id": admission_id,
        "authority": "deterministic_controller",
    }
    acceptance_id = f"acceptance_{sha256_json(identity)}"
    target = (
        plan_dir / "state" / "scientific_acceptance"
        / verdict["candidate_id"] / f"{acceptance_id}.json"
    )
    if target.exists():
        prior = read_json(target)
        if any(prior.get(key) != value for key, value in identity.items()):
            raise ContractError("scientific acceptance identity collision")
        return {
            "ok": True, "idempotent": True, "acceptance_receipt": str(target),
            **prior,
        }
    receipt = {
        **identity,
        "acceptance_id": acceptance_id,
        "checked_at": utc_now(),
    }
    atomic_write_json(target, receipt, immutable=True)
    append_jsonl_once(
        plan_dir / "state" / "scientific_acceptance_audit.jsonl",
        "acceptance_id", acceptance_id, receipt,
    )
    return {"ok": True, "acceptance_receipt": str(target), **receipt}


def transition_receipt_path(plan_dir: Path, transition_name: str, request_id: str) -> Path:
    if not REQUEST_ID_RE.fullmatch(request_id):
        raise ContractError("invalid request_id")
    return plan_dir / "state" / "frontier" / "transitions" / transition_name / f"{request_id}.json"


def transition_receipt_candidates(plan_dir: Path, transition_name: str) -> list[Path]:
    root = plan_dir / "state" / "frontier" / "transitions" / transition_name
    return sorted(root.glob("far_*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)


def validate_frozen_figure_requirements(
    plan_dir: Path,
    requirements_path: Path,
    expected_plan_id: str,
) -> dict[str, Any]:
    proc = subprocess.run(
        [
            sys.executable,
            str(FIGURE_VALIDATOR),
            "--plan-dir",
            str(plan_dir),
            "--requirements-only",
            str(requirements_path),
        ],
        cwd=plan_dir,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise ContractError(f"frozen figure requirements validation failed: {detail}")
    result = strict_json_loads(proc.stdout)
    if (
        not isinstance(result, dict)
        or result.get("status") != "PASS"
        or result.get("eligible") is not True
        or result.get("plan_id") != expected_plan_id
        or not isinstance(result.get("expected_figure_ids"), list)
        or not result["expected_figure_ids"]
    ):
        raise ContractError("frozen figure requirements validator returned an invalid PASS result")
    return result


def check_transition_receipt(
    plan_dir: Path, plan_id: str, name: str, request_id: str | None = None,
    *, verify_live_manifest: bool = True,
) -> dict[str, Any]:
    candidates = (
        [transition_receipt_path(plan_dir, name, request_id)]
        if request_id else transition_receipt_candidates(plan_dir, name)
    )
    if not candidates:
        raise ContractError(f"missing applied transition receipt: {name}")
    receipt = read_json(candidates[0])
    if receipt.get("plan_id") != plan_id or receipt.get("transition") != name:
        raise ContractError("dependent transition receipt correlation mismatch")
    request_path, request = load_request(
        plan_dir, receipt["request_id"], verify_live_manifest=verify_live_manifest,
    )
    response_path = request_dir(plan_dir, receipt["request_id"]) / "response.json"
    if receipt.get("request_sha256") != sha256_file(request_path):
        raise ContractError("dependent transition request hash changed")
    if receipt.get("response_sha256") != sha256_file(response_path):
        raise ContractError("dependent transition response hash changed")
    context_hash = sha256_json(request["context_manifest"])
    if receipt.get("context_manifest_sha256") != context_hash:
        raise ContractError("dependent transition context hash changed")
    if verify_live_manifest:
        verify_manifest_items(request["context_manifest"], base_dir=plan_dir)
    policy = load_policy(plan_dir)
    review_contract = validate_top_level_plan_review_contract(request)
    if review_contract is not None:
        expected_profile = review_contract["reviewer_profile"]
        response = read_json(response_path)
        if response.get("model_id") != expected_profile["model"]:
            raise ContractError(
                "CP-01 response was not produced by the frozen top-level plan reviewer"
            )
        if receipt.get("reviewer_profile") != expected_profile:
            raise ContractError("CP-01 transition reviewer profile mismatch")
        if receipt.get("model_policy_sha256") != review_contract[
            "model_policy_sha256"
        ]:
            raise ContractError("CP-01 transition model policy binding mismatch")
        if review_contract["model_policy_sha256"] != sha256_file(
            policy_path(plan_dir)
        ):
            raise ContractError("CP-01 transition model policy hash changed")
    return receipt


def command_check_figure_gate(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    inventory_arg = Path(args.inventory)
    inventory_path = (
        inventory_arg if inventory_arg.is_absolute() else plan_dir / inventory_arg
    ).resolve()
    requirements_arg = Path(args.requirements)
    requirements_path = (
        requirements_arg
        if requirements_arg.is_absolute()
        else plan_dir / requirements_arg
    ).resolve()
    cp01_receipt = require_transition_evidence(
        plan_dir,
        "approve_execution",
        {"figure_requirements": requirements_path},
    )
    cp01_receipt_path = transition_receipt_path(
        plan_dir,
        "approve_execution",
        cp01_receipt["request_id"],
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(FIGURE_VALIDATOR),
            "--plan-dir",
            str(plan_dir),
            "--inventory",
            str(inventory_path),
            "--requirements",
            str(requirements_path),
        ],
        cwd=plan_dir,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise ContractError(f"figure inventory validation failed: {detail}")
    result = strict_json_loads(proc.stdout)
    if (
        not isinstance(result, dict)
        or result.get("status") != "PASS"
        or result.get("eligible") is not True
        or result.get("plan_id") != plan_identity(plan_dir)
        or not isinstance(result.get("figures"), list)
        or not result["figures"]
    ):
        raise ContractError("figure inventory validator returned an invalid PASS result")
    identity = {
        "schema_version": 1,
        "plan_id": plan_identity(plan_dir),
        "inventory_path": str(inventory_path),
        "inventory_sha256": sha256_file(inventory_path),
        "requirements_path": str(requirements_path),
        "requirements_sha256": sha256_file(requirements_path),
        "requirements_tier": result["tier"],
        "expected_figure_ids": result["expected_figure_ids"],
        "approve_execution_request_id": cp01_receipt["request_id"],
        "approve_execution_receipt_sha256": sha256_file(cp01_receipt_path),
        "required_figure_count": result["required_figure_count"],
        "figures": [
            {
                "figure_id": item["figure_id"],
                "manifest": item["manifest"],
                "manifest_sha256": item["manifest_sha256"],
            }
            for item in result["figures"]
        ],
        "authority": "deterministic_controller",
    }
    decision_sha256 = sha256_json(identity)
    audit = {
        **identity,
        "decision_sha256": decision_sha256,
        "checked_at": utc_now(),
    }
    audit_path = plan_dir / "state" / "figure_gate_audit.jsonl"
    append_jsonl_once(audit_path, "decision_sha256", decision_sha256, audit)
    gate_path = plan_dir / "state" / "figure_gates" / f"{decision_sha256}.json"
    if not gate_path.exists():
        atomic_write_json(gate_path, audit, immutable=True)
    return {
        "ok": True,
        "status": "PASS",
        "gate_receipt": str(gate_path),
        "decision_sha256": decision_sha256,
        "required_figure_count": result["required_figure_count"],
    }


def validate_figure_gate_receipt(plan_dir: Path, raw_path: str) -> dict[str, Any]:
    raw = Path(raw_path)
    path = (raw if raw.is_absolute() else plan_dir / raw).resolve()
    root = (plan_dir / "state" / "figure_gates").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ContractError("figure gate receipt is outside canonical state") from exc
    gate = read_json(path)
    if path.name != f"{gate.get('decision_sha256')}.json":
        raise ContractError("figure gate receipt identity mismatch")
    identity = {
        key: value for key, value in gate.items()
        if key not in {"checked_at", "decision_sha256"}
    }
    if gate.get("decision_sha256") != sha256_json(identity):
        raise ContractError("figure gate decision identity mismatch")
    if gate.get("plan_id") != plan_identity(plan_dir):
        raise ContractError("figure gate belongs to another plan")
    inventory_path = Path(gate["inventory_path"])
    if sha256_file(inventory_path) != gate["inventory_sha256"]:
        raise ContractError("figure inventory hash changed")
    requirements_path = Path(gate["requirements_path"])
    if sha256_file(requirements_path) != gate["requirements_sha256"]:
        raise ContractError("frozen figure requirements hash changed")
    cp01_receipt_path = transition_receipt_path(
        plan_dir,
        "approve_execution",
        gate["approve_execution_request_id"],
    )
    if sha256_file(cp01_receipt_path) != gate["approve_execution_receipt_sha256"]:
        raise ContractError("figure requirements approval receipt changed")
    audit_path = plan_dir / "state" / "figure_gate_audit.jsonl"
    entries = [
        strict_json_loads(line) for line in audit_path.read_text().splitlines() if line.strip()
    ] if audit_path.exists() else []
    if gate not in entries:
        raise ContractError("figure gate is absent from the canonical audit")
    revalidated = command_check_figure_gate(argparse.Namespace(
        plan_dir=str(plan_dir),
        inventory=str(inventory_path),
        requirements=str(requirements_path),
    ))
    if Path(revalidated["gate_receipt"]).resolve() != path:
        raise ContractError("figure gate no longer matches its inventory and manifests")
    return gate


def command_check_writing_gate(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    figure_gate_arg = Path(args.figure_gate_receipt)
    figure_gate_path = (
        figure_gate_arg
        if figure_gate_arg.is_absolute()
        else plan_dir / figure_gate_arg
    ).resolve()
    figure_gate = validate_figure_gate_receipt(plan_dir, str(figure_gate_path))
    if bool(args.verdict) == bool(args.waiver):
        raise ContractError("writing gate requires exactly one of --verdict or --waiver")
    source: str
    authority_path: Path
    candidate_path: Path
    contract_path = plan_dir / "state" / "evaluator_contract.json"
    verdict_path: Path
    acceptance_path: Path | None = None
    if args.verdict:
        verdict_path = Path(args.verdict).resolve()
        verdict = read_json(verdict_path)
        stored = plan_dir / "state" / "evaluator_verdicts" / f"{verdict.get('candidate_id', '')}.json"
        if stored.resolve() != verdict_path or verdict.get("verdict") != "PASS":
            raise ContractError("writing gate requires a stored validated PASS verdict")
        contract = read_json(contract_path)
        contract_body = {key: value for key, value in contract.items() if key != "contract_sha256"}
        if contract.get("contract_sha256") != sha256_json(contract_body):
            raise ContractError("frozen evaluator contract hash changed")
        if sha256_file(Path(contract["metric_contract_path"])) != contract["metric_contract_sha256"]:
            raise ContractError("frozen metric contract hash changed")
        if verdict.get("contract_sha256") != contract["contract_sha256"]:
            raise ContractError("verdict evaluator contract mismatch")
        if verdict.get("metric") != contract["metric"] or verdict.get("threshold") != contract["threshold"]:
            raise ContractError("verdict metric or threshold changed")
        require_finite_number(verdict.get("value"), "verdict value")
        require_finite_number(verdict.get("threshold"), "verdict threshold")
        require_finite_number(contract["threshold"], "frozen threshold")
        passed = verdict.get("value") >= contract["threshold"] if contract["operator"] == "gte" else verdict.get("value") <= contract["threshold"]
        if not passed:
            raise ContractError("stored PASS no longer satisfies the frozen threshold")
        if sha256_file(Path(verdict["candidate_path"])) != verdict["candidate_sha256"]:
            raise ContractError("candidate artifact hash changed")
        if sha256_file(Path(contract["evaluator_path"])) != verdict["evaluator_sha256"]:
            raise ContractError("evaluator hash changed")
        if sha256_file(Path(contract["evidence_path"])) != verdict["evidence_sha256"]:
            raise ContractError("evidence hash changed")
        candidate_path = Path(verdict["candidate_path"])
        transition_receipt = require_transition_evidence(plan_dir, "start_writing", {
            "candidate": candidate_path,
            "evaluator_verdict": verdict_path,
            "evaluator_contract": contract_path,
            "figure_gate": figure_gate_path,
        })
        acceptance = command_check_scientific_acceptance(argparse.Namespace(
            plan_dir=str(plan_dir), verdict=str(verdict_path),
        ))
        if acceptance.get("decision") != "PASS":
            raise ContractError("writing gate requires a PASS scientific acceptance")
        acceptance_path = Path(acceptance["acceptance_receipt"])
        source, authority_path = "validated_verdict", verdict_path
    else:
        waiver_path = Path(args.waiver).resolve()
        waiver = validate_applied_action_receipt(plan_dir, waiver_path, "waive_acceptance")
        details = waiver["details"]
        if details.get("tier") != args.tier:
            raise ContractError("waiver tier does not match writing tier")
        candidate_path = Path(details["candidate_path"])
        verdict_path = Path(details["evaluator_verdict_path"])
        if sha256_file(candidate_path) != details.get("candidate_sha256"):
            raise ContractError("waiver candidate hash changed")
        if sha256_file(contract_path) != details.get("evaluator_contract_sha256"):
            raise ContractError("waiver evaluator contract hash changed")
        if sha256_file(verdict_path) != details.get("evaluator_verdict_sha256"):
            raise ContractError("waiver evaluator verdict hash changed")
        transition_receipt = require_transition_evidence(plan_dir, "start_writing", {
            "candidate": candidate_path,
            "evaluator_contract": contract_path,
            "evaluator_verdict": verdict_path,
            "figure_gate": figure_gate_path,
        })
        negative = details.get("scope") == "negative_result"
        if negative and args.tier != "arxiv":
            raise ContractError("negative-result waiver is arxiv-only")
        source, authority_path = "applied_waiver_receipt", Path(waiver["receipt_path"])
    audit = {
        "schema_version": 1, "plan_id": plan_identity(plan_dir), "tier": args.tier,
        "source": source, "authority_path": str(authority_path),
        "authority_sha256": sha256_file(authority_path),
        "candidate_path": str(candidate_path.resolve()),
        "candidate_sha256": sha256_file(candidate_path),
        "evaluator_contract_path": str(contract_path.resolve()),
        "evaluator_contract_sha256": sha256_file(contract_path),
        "evaluator_verdict_path": str(verdict_path.resolve()),
        "evaluator_verdict_sha256": sha256_file(verdict_path),
        "figure_gate_path": str(figure_gate_path),
        "figure_gate_sha256": sha256_file(figure_gate_path),
        "required_figure_count": figure_gate["required_figure_count"],
        "start_writing_request_id": transition_receipt["request_id"],
        "start_writing_receipt_sha256": sha256_file(
            transition_receipt_path(plan_dir, "start_writing", transition_receipt["request_id"])
        ),
        "checked_at": utc_now(),
    }
    if acceptance_path is not None:
        audit.update({
            "scientific_acceptance_path": str(acceptance_path),
            "scientific_acceptance_sha256": sha256_file(acceptance_path),
        })
    audit["decision_sha256"] = sha256_json({key: value for key, value in audit.items() if key != "checked_at"})
    append_jsonl_once(plan_dir / "state" / "writing_gate_audit.jsonl", "decision_sha256", audit["decision_sha256"], audit)
    gate_path = plan_dir / "state" / "writing_gates" / f"{audit['decision_sha256']}.json"
    if not gate_path.exists():
        atomic_write_json(gate_path, audit, immutable=True)
    return {"ok": True, "tier": args.tier, "source": source, "audit": audit,
            "gate_receipt": str(gate_path), "transition_request_id": transition_receipt["request_id"]}


def failure_state_default(plan_dir: Path) -> dict[str, Any]:
    policy = policy_path(plan_dir)
    threshold = 2
    if policy.exists():
        threshold = int(read_json(policy).get("scientific_pivot_threshold", 2))
    return {
        "schema_version": 1,
        **{f"{kind}_count": 0 for kind in sorted(FAILURE_CLASSES)},
        "distinct_scientific_fingerprints": [],
        "direction_registry": {},
        "pivot_epoch": 0,
        "pivot_cursor": 0,
        "epoch_direction_fingerprints": [],
        "scientific_failure_events": [],
        "consumed_scientific_event_ids": [],
        "seen": [],
        "scientific_pivot_threshold": threshold,
    }


def command_record_failure(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    if args.failure_class not in FAILURE_CLASSES:
        raise ContractError("unsupported failure class")
    if args.failure_class in INTEGRITY_FAILURE_CLASSES:
        raise ContractError(
            "integrity failures are controller-detected by check-research-integrity"
        )
    if not args.source:
        raise ContractError("source is required")
    fingerprint = getattr(args, "fingerprint", None)
    direction: dict[str, Any] | None = None
    verdict_path: Path | None = None
    if args.failure_class == "scientific_no_improvement":
        if not getattr(args, "direction", None) or not getattr(args, "verdict", None):
            raise ContractError("scientific_no_improvement requires --direction and --verdict")
        raw_direction = read_json(Path(args.direction).resolve())
        if set(raw_direction) != DIRECTION_FIELDS:
            raise ContractError(f"direction descriptor requires exactly {sorted(DIRECTION_FIELDS)}")
        direction = {
            key: " ".join(raw_direction[key].strip().lower().split())
            if isinstance(raw_direction[key], str) else raw_direction[key]
            for key in sorted(DIRECTION_FIELDS)
        }
        if not all(isinstance(direction[key], str) and direction[key] for key in DIRECTION_FIELDS):
            raise ContractError("direction descriptor fields must be non-empty strings")
        verdict_path = Path(args.verdict).resolve()
        verdict = read_json(verdict_path)
        canonical = plan_dir / "state" / "evaluator_verdicts" / f"{verdict.get('candidate_id', '')}.json"
        if verdict_path != canonical.resolve() or verdict.get("verdict") != "FAIL":
            raise ContractError("scientific failure requires a canonical FAIL verdict")
        candidate = Path(verdict["candidate_path"])
        if sha256_file(candidate) != verdict.get("candidate_sha256"):
            raise ContractError("scientific failure candidate hash changed")
        if direction["candidate_sha256"] != verdict["candidate_sha256"]:
            raise ContractError("direction descriptor is not bound to the failed candidate")
        frozen_evaluator_identity = verdict.get("contract_sha256")
        if not isinstance(frozen_evaluator_identity, str) or len(frozen_evaluator_identity) != 64:
            raise ContractError("scientific failure lacks a frozen evaluator identity")
        scientific_descriptor = {
            key: direction[key] for key in sorted(SCIENTIFIC_DIRECTION_FIELDS)
        }
        fingerprint = sha256_json({
            "scientific_descriptor": scientific_descriptor,
            "frozen_evaluator_identity": frozen_evaluator_identity,
        })
    elif not fingerprint:
        raise ContractError("non-scientific failures require --fingerprint")
    target = plan_dir / "state" / "failure_state.json"
    lock_path = plan_dir / "state" / ".failure.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = read_json(target) if target.exists() else failure_state_default(plan_dir)
        expected_threshold = failure_state_default(plan_dir)["scientific_pivot_threshold"]
        if state.get("scientific_pivot_threshold") != expected_threshold:
            raise ContractError("scientific pivot threshold changed from the frozen policy")
        key_fingerprint = fingerprint
        if args.failure_class == "scientific_no_improvement":
            key_fingerprint = hashlib.sha256(
                f"{fingerprint}\0{verdict['candidate_sha256']}\0{sha256_file(verdict_path)}".encode()
            ).hexdigest()
        key = f"{args.failure_class}:{key_fingerprint}"
        if key in state.get("seen", []):
            return {"ok": True, "idempotent": True, "failure_class": args.failure_class, "state": state}
        state.setdefault("seen", []).append(key)
        count_key = f"{args.failure_class}_count"
        state[count_key] = int(state.get(count_key, 0)) + 1
        if args.failure_class == "scientific_no_improvement":
            registry = state.setdefault("direction_registry", {})
            first_direction_outcome = fingerprint not in registry
            if first_direction_outcome:
                state.setdefault("distinct_scientific_fingerprints", []).append(fingerprint)
                registry[fingerprint] = {
                    "scientific_descriptor": scientific_descriptor,
                    "frozen_evaluator_identity": frozen_evaluator_identity,
                    "outcomes": [], "recorded_at": utc_now(),
                }
            registry[fingerprint].setdefault("outcomes", []).append({
                "candidate_sha256": verdict["candidate_sha256"],
                "verdict_path": str(verdict_path),
                "verdict_sha256": sha256_file(verdict_path),
                "recorded_at": utc_now(),
            })
            epoch_fingerprints = state.setdefault("epoch_direction_fingerprints", [])
            if fingerprint not in epoch_fingerprints:
                epoch = int(state.get("pivot_epoch", 0))
                verdict_hash = sha256_file(verdict_path)
                event_id = "sfe_" + hashlib.sha256(
                    f"{epoch}\0{fingerprint}\0{verdict_hash}".encode()
                ).hexdigest()
                state.setdefault("scientific_failure_events", []).append({
                    "event_id": event_id,
                    "epoch": epoch,
                    "fingerprint": fingerprint,
                    "candidate_sha256": verdict["candidate_sha256"],
                    "verdict_path": str(verdict_path),
                    "verdict_sha256": verdict_hash,
                    "validated": True,
                    "recorded_at": utc_now(),
                })
                epoch_fingerprints.append(fingerprint)
        state["updated_at"] = utc_now()
        atomic_write_json(target, state)
        append_jsonl(plan_dir / "state" / "failure_events.jsonl", {
            "ts": utc_now(), "class": args.failure_class, "fingerprint": fingerprint,
            "source": args.source, "direction": direction,
            "route": FAILURE_ROUTES[args.failure_class],
        })
    return {
        "ok": True,
        "idempotent": False,
        "failure_class": args.failure_class,
        "route": FAILURE_ROUTES[args.failure_class],
        "state": state,
    }


def record_integrity_failure(
    plan_dir: Path,
    failure_class: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    if failure_class not in INTEGRITY_FAILURE_CLASSES:
        raise ContractError("invalid integrity failure class")
    fingerprint = sha256_json({
        "class": failure_class,
        "details": details,
    })
    target = plan_dir / "state" / "failure_state.json"
    lock_path = plan_dir / "state" / ".failure.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = read_json(target) if target.exists() else failure_state_default(plan_dir)
        key = f"{failure_class}:{fingerprint}"
        if key in state.get("seen", []):
            return {
                "failure_class": failure_class,
                "fingerprint": fingerprint,
                "route": FAILURE_ROUTES[failure_class],
                "idempotent": True,
            }
        state.setdefault("seen", []).append(key)
        count_key = f"{failure_class}_count"
        state[count_key] = int(state.get(count_key, 0)) + 1
        event = {
            "ts": utc_now(),
            "class": failure_class,
            "fingerprint": fingerprint,
            "source": "deterministic_integrity_check",
            "route": FAILURE_ROUTES[failure_class],
            "details": details,
        }
        state.setdefault("integrity_events", []).append(event)
        state["updated_at"] = event["ts"]
        atomic_write_json(target, state)
        append_jsonl(plan_dir / "state" / "failure_events.jsonl", event)
    return {
        "failure_class": failure_class,
        "fingerprint": fingerprint,
        "route": FAILURE_ROUTES[failure_class],
        "idempotent": False,
    }


def artifact_drift_observation(item: dict[str, Any]) -> dict[str, Any] | None:
    path = Path(str(item.get("path", "")))
    expected = item.get("sha256")
    observed: str | None = None
    if path.is_file() and not path.is_symlink():
        observed = sha256_file(path)
    if observed == expected:
        return None
    return {
        "path": str(path),
        "expected_sha256": expected,
        "observed_sha256": observed,
    }


def command_check_research_integrity(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    graph_path = plan_dir / "state" / "durable_loop" / "canonical" / "graph.json"
    graph = read_json(graph_path)
    goal_drift = {
        role: observation
        for role in ("objective", "constraints")
        if (observation := artifact_drift_observation(graph[role])) is not None
    }
    evaluator_drift: dict[str, Any] = {}
    evaluator_observation = artifact_drift_observation(graph["evaluator"])
    if evaluator_observation is not None:
        evaluator_drift["durable_evaluator"] = evaluator_observation
    contract_path = plan_dir / "state" / "evaluator_contract.json"
    if contract_path.exists():
        try:
            contract = read_json(contract_path)
            contract_body = {
                key: value for key, value in contract.items()
                if key != "contract_sha256"
            }
            if contract.get("contract_sha256") != sha256_json(contract_body):
                raise ContractError("frozen evaluator contract identity changed")
            if contract.get("evaluator_sha256") != graph["evaluator"]["sha256"]:
                raise ContractError("frozen evaluator differs from durable plan evaluator")
            for role in ("evaluator", "evidence", "metric_contract"):
                observation = artifact_drift_observation({
                    "path": contract[f"{role}_path"],
                    "sha256": contract[f"{role}_sha256"],
                })
                if observation is not None:
                    evaluator_drift[f"contract_{role}"] = observation
        except (ContractError, KeyError, TypeError) as exc:
            evaluator_drift["frozen_contract"] = {"error": str(exc)}
    if graph.get("execution_mode") == "unattended" and graph.get("target_tier") in {
        "conference", "journal-q1",
    }:
        try:
            require_durable_autonomy_eligibility(plan_dir)
        except ContractError as exc:
            evaluator_drift["admission"] = {"error": str(exc)}
    findings: list[dict[str, Any]] = []
    if goal_drift:
        findings.append(record_integrity_failure(
            plan_dir, "goal_drift", {"artifacts": goal_drift},
        ))
    if evaluator_drift:
        findings.append(record_integrity_failure(
            plan_dir, "evaluator_integrity", {"artifacts": evaluator_drift},
        ))
    state_path = plan_dir / "state" / "failure_state.json"
    state = read_json(state_path) if state_path.exists() else failure_state_default(plan_dir)
    return {
        "ok": not findings,
        "integrity": "PASS" if not findings else "BLOCKED",
        "findings": findings,
        "state": state,
    }


def record_detected_research_integrity(plan_dir: Path) -> None:
    try:
        command_check_research_integrity(argparse.Namespace(plan_dir=str(plan_dir)))
    except ContractError:
        # Preserve the original boundary error when canonical state is too
        # damaged for a complete classification.
        return


LEARNING_TARGET_KINDS = {"skill", "policy", "spec", "evaluator"}
ACCEPTANCE_FAULT_SCENARIOS = {
    "process_death", "missed_tick", "duplicate_trigger", "state_corruption",
    "budget_exhaustion", "evaluator_drift", "multi_session_restart",
}
ACCEPTANCE_CLAIM_KINDS = {
    "bounded_fault_acceptance", "long_stability", "seven_by_twenty_four",
    "full_cutover",
}
ACCEPTANCE_CLAIM_MINIMUM_SECONDS = {
    "bounded_fault_acceptance": 0,
    "long_stability": 86400,
    "seven_by_twenty_four": 7 * 24 * 60 * 60,
    "full_cutover": 0,
}


def learning_root(plan_dir: Path) -> Path:
    return plan_dir / "state" / "learning"


def validate_learning_gate_artifact(
    plan_dir: Path, raw_path: str, name: str, *, read_only: bool = False,
) -> Path:
    path = Path(raw_path).resolve()
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{name} must be an existing regular non-symlink file")
    normalize_owned_path(plan_dir, str(path))
    worker_roots = (
        (plan_dir / "artifacts" / "intermediate").resolve(),
        (plan_dir / "state" / "worker_runs").resolve(),
    )
    if any(path == root or root in path.parents for root in worker_roots):
        raise ContractError(f"{name} must be independent of worker-owned namespaces")
    if read_only and path.stat().st_mode & 0o222:
        raise ContractError(f"{name} must be filesystem read-only")
    return path


def validate_learning_evidence(
    plan_dir: Path,
    *,
    subject_sha256: str,
    subject_kind: str,
    diagnosis_sha256: str | None,
    replay_path: Path,
    validation_path: Path,
    audit_path: Path,
    auditor_identity_path: Path,
) -> dict[str, Any]:
    replay_path = validate_learning_gate_artifact(
        plan_dir, str(replay_path), "learning replay",
    )
    validation_path = validate_learning_gate_artifact(
        plan_dir, str(validation_path), "learning validation",
    )
    audit_path = validate_learning_gate_artifact(
        plan_dir, str(audit_path), "learning audit",
    )
    auditor_identity_path = validate_learning_gate_artifact(
        plan_dir, str(auditor_identity_path), "learning auditor identity",
        read_only=True,
    )
    replay = read_json(replay_path)
    if set(replay) != {
        "schema_version", "subject_sha256", "first_result_sha256",
        "second_result_sha256", "status",
    }:
        raise ContractError("learning replay has an invalid closed shape")
    replay_passed = (
        replay.get("schema_version") == SCHEMA_VERSION
        and replay.get("subject_sha256") == subject_sha256
        and replay.get("first_result_sha256")
        == replay.get("second_result_sha256")
        and replay.get("status") == "PASS"
    )
    validation = read_json(validation_path)
    if set(validation) != {
        "schema_version", "subject_sha256", "kind", "status",
        "failed_cases", "total_cases",
    }:
        raise ContractError("learning validation has an invalid closed shape")
    validation_passed = (
        validation.get("schema_version") == SCHEMA_VERSION
        and validation.get("subject_sha256") == subject_sha256
        and validation.get("kind") in {"held_out", "regression"}
        and validation.get("status") == "PASS"
        and validation.get("failed_cases") == 0
        and isinstance(validation.get("total_cases"), int)
        and not isinstance(validation.get("total_cases"), bool)
        and validation["total_cases"] > 0
    )
    audit = read_json(audit_path)
    if set(audit) != {
        "schema_version", "audit_id", "subject_kind", "subject_sha256",
        "diagnosis_sha256", "auditor_identity_sha256", "independent",
        "status", "findings",
    }:
        raise ContractError("learning audit has an invalid closed shape")
    audit_passed = (
        audit.get("schema_version") == SCHEMA_VERSION
        and isinstance(audit.get("audit_id"), str)
        and bool(audit["audit_id"])
        and audit.get("subject_kind") == subject_kind
        and audit.get("subject_sha256") == subject_sha256
        and audit.get("diagnosis_sha256") == diagnosis_sha256
        and audit.get("auditor_identity_sha256")
        == sha256_file(auditor_identity_path)
        and audit.get("independent") is True
        and audit.get("status") == "PASS"
        and audit.get("findings") == []
        and sha256_file(auditor_identity_path) != subject_sha256
    )
    reasons = []
    if not replay_passed:
        reasons.append("replay_failed")
    if not validation_passed:
        reasons.append("validation_failed")
    if not audit_passed:
        reasons.append("independent_audit_failed")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "replay_path": str(replay_path),
        "replay_sha256": sha256_file(replay_path),
        "validation_path": str(validation_path),
        "validation_sha256": sha256_file(validation_path),
        "audit_path": str(audit_path),
        "audit_sha256": sha256_file(audit_path),
        "audit_id": audit.get("audit_id"),
        "auditor_identity_path": str(auditor_identity_path),
        "auditor_identity_sha256": sha256_file(auditor_identity_path),
    }


def command_promote_episode_memory(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    episode_path = normalize_owned_path(
        plan_dir, str(Path(args.episode_manifest).resolve()),
    )
    diagnosis_path = normalize_owned_path(
        plan_dir, str(Path(args.diagnosis).resolve()),
    )
    if (
        episode_path.is_symlink() or not episode_path.is_file()
        or diagnosis_path.is_symlink() or not diagnosis_path.is_file()
    ):
        raise ContractError("episode manifest and diagnosis must be regular files")
    episode = read_json(episode_path)
    if set(episode) != {
        "schema_version", "episode_id", "plan_id", "outcome", "evidence",
    }:
        raise ContractError("learning episode manifest has an invalid closed shape")
    if (
        episode.get("schema_version") != SCHEMA_VERSION
        or episode.get("plan_id") != plan_identity(plan_dir)
        or not isinstance(episode.get("episode_id"), str)
        or not episode["episode_id"]
        or episode.get("outcome") not in {"success", "failure", "mixed"}
    ):
        raise ContractError("learning episode manifest correlation mismatch")
    evidence = verify_manifest_items(episode["evidence"], base_dir=plan_dir)
    diagnosis = read_json(diagnosis_path)
    if set(diagnosis) != {
        "schema_version", "episode_id", "classification", "rationale",
        "evidence_manifest_sha256",
    }:
        raise ContractError("learning diagnosis has an invalid closed shape")
    if (
        diagnosis.get("schema_version") != SCHEMA_VERSION
        or diagnosis.get("episode_id") != episode["episode_id"]
        or diagnosis.get("classification")
        not in {"skill_defect", "execution_lapse"}
        or not isinstance(diagnosis.get("rationale"), str)
        or not diagnosis["rationale"].strip()
        or diagnosis.get("evidence_manifest_sha256") != sha256_json(evidence)
    ):
        raise ContractError("learning diagnosis is not bound to the episode evidence")
    episode_sha = sha256_file(episode_path)
    diagnosis_sha = sha256_file(diagnosis_path)
    gate = validate_learning_evidence(
        plan_dir,
        subject_sha256=episode_sha,
        subject_kind="episode",
        diagnosis_sha256=diagnosis_sha,
        replay_path=Path(args.replay),
        validation_path=Path(args.validation),
        audit_path=Path(args.audit),
        auditor_identity_path=Path(args.auditor_identity),
    )
    identity = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": episode["plan_id"],
        "episode_id": episode["episode_id"],
        "episode_manifest_path": str(episode_path),
        "episode_manifest_sha256": episode_sha,
        "diagnosis_path": str(diagnosis_path),
        "diagnosis_sha256": diagnosis_sha,
        "classification": diagnosis["classification"],
        "evidence_manifest": evidence,
        **{key: value for key, value in gate.items() if key != "passed"},
    }
    memory_id = f"memory_{sha256_json(identity)}"
    target = learning_root(plan_dir) / "memories" / f"{memory_id}.json"
    if target.exists():
        prior = read_json(target)
        return {
            "ok": prior["status"] == "AUDITED",
            "idempotent": True,
            "memory_receipt": str(target),
            **prior,
        }
    status = "AUDITED" if gate["passed"] else "REJECTED"
    receipt = {
        **identity,
        "memory_id": memory_id,
        "status": status,
        "proposal_eligible": (
            status == "AUDITED"
            and diagnosis["classification"] == "skill_defect"
        ),
        "recorded_at": utc_now(),
    }
    atomic_write_json(target, receipt, immutable=True)
    append_jsonl_once(
        learning_root(plan_dir) / "memory_audit.jsonl",
        "memory_id", memory_id, receipt,
    )
    return {
        "ok": status == "AUDITED",
        "memory_receipt": str(target),
        **receipt,
    }


def command_promote_learning_proposal(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    memory_path = Path(args.memory_receipt).resolve()
    memory = read_json(memory_path)
    canonical_memory = (
        learning_root(plan_dir) / "memories"
        / f"{memory.get('memory_id', '')}.json"
    )
    if memory_path != canonical_memory.resolve() or memory.get("plan_id") != plan_identity(plan_dir):
        raise ContractError("learning memory receipt is not canonical for this plan")
    for path_key, sha_key in (
        ("episode_manifest_path", "episode_manifest_sha256"),
        ("diagnosis_path", "diagnosis_sha256"),
        ("replay_path", "replay_sha256"),
        ("validation_path", "validation_sha256"),
        ("audit_path", "audit_sha256"),
        ("auditor_identity_path", "auditor_identity_sha256"),
    ):
        source_path = Path(memory[path_key])
        if not source_path.is_file() or sha256_file(source_path) != memory[sha_key]:
            raise ContractError(f"audited memory source changed: {path_key}")
    verify_manifest_items(memory["evidence_manifest"], base_dir=plan_dir)
    proposal_path = normalize_owned_path(
        plan_dir, str(Path(args.proposal).resolve()),
    )
    if proposal_path.is_symlink() or not proposal_path.is_file():
        raise ContractError("learning proposal must be an existing regular file")
    proposal_sha = sha256_file(proposal_path)
    gate = validate_learning_evidence(
        plan_dir,
        subject_sha256=proposal_sha,
        subject_kind="proposal",
        diagnosis_sha256=None,
        replay_path=Path(args.replay),
        validation_path=Path(args.validation),
        audit_path=Path(args.audit),
        auditor_identity_path=Path(args.auditor_identity),
    )
    if gate["audit_sha256"] == memory.get("audit_sha256"):
        raise ContractError("proposal promotion requires a fresh independent audit")
    authorization_id: str | None = None
    authorization_sha: str | None = None
    if args.target_kind == "evaluator":
        if not args.authorization:
            raise ContractError(
                "evaluator-change proposal requires authenticated human authorization"
            )
        authorization_path = Path(args.authorization).resolve()
        authorization = validate_applied_action_receipt(
            plan_dir, authorization_path, "authorize_evaluator_change",
        )
        details = authorization["details"]
        if (
            Path(details.get("learning_proposal_path", "")).resolve()
            != proposal_path
            or details.get("learning_proposal_sha256") != proposal_sha
            or details.get("learning_target_kind") != "evaluator"
        ):
            raise ContractError(
                "human evaluator-change authorization is bound to another proposal"
            )
        authorization_id = authorization["record_id"]
        authorization_sha = sha256_file(authorization_path)
    identity = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "memory_id": memory["memory_id"],
        "memory_receipt_path": str(memory_path),
        "memory_receipt_sha256": sha256_file(memory_path),
        "target_kind": args.target_kind,
        "proposal_path": str(proposal_path),
        "proposal_sha256": proposal_sha,
        "human_authorization_record_id": authorization_id,
        "human_authorization_sha256": authorization_sha,
        **{key: value for key, value in gate.items() if key != "passed"},
    }
    proposal_id = f"proposal_{sha256_json(identity)}"
    registry_path = learning_root(plan_dir) / "proposal_registry" / f"{proposal_sha}.json"
    if registry_path.exists():
        prior_pointer = read_json(registry_path)
        prior_path = Path(prior_pointer["receipt_path"])
        prior = read_json(prior_path)
        if prior.get("proposal_id") != proposal_id:
            raise ContractError(
                "identical proposal bytes were already reviewed and cannot reenter as novelty"
            )
        return {
            "ok": prior["status"] == "APPROVED",
            "idempotent": True,
            "proposal_receipt": str(prior_path),
            **prior,
        }
    eligible = (
        memory.get("status") == "AUDITED"
        and memory.get("proposal_eligible") is True
        and gate["passed"]
    )
    rejection_reasons = list(gate["reasons"])
    if memory.get("status") != "AUDITED":
        rejection_reasons.append("memory_not_audited")
    if memory.get("proposal_eligible") is not True:
        rejection_reasons.append("diagnosed_as_execution_lapse")
    receipt = {
        **identity,
        "proposal_id": proposal_id,
        "status": "APPROVED" if eligible else "REJECTED",
        "rejection_reasons": sorted(set(rejection_reasons)),
        "proposal_only": True,
        "application_authority": False,
        "recorded_at": utc_now(),
    }
    target = learning_root(plan_dir) / "proposals" / f"{proposal_id}.json"
    atomic_write_json(target, receipt, immutable=True)
    atomic_write_json(registry_path, {
        "schema_version": SCHEMA_VERSION,
        "proposal_sha256": proposal_sha,
        "proposal_id": proposal_id,
        "receipt_path": str(target),
        "receipt_sha256": sha256_file(target),
        "status": receipt["status"],
    }, immutable=True)
    append_jsonl_once(
        learning_root(plan_dir) / "proposal_audit.jsonl",
        "proposal_id", proposal_id, receipt,
    )
    return {
        "ok": eligible,
        "proposal_receipt": str(target),
        **receipt,
    }


def acceptance_root(plan_dir: Path) -> Path:
    return plan_dir / "state" / "acceptance"


def acceptance_profile_path(plan_dir: Path, profile_id: Any) -> Path:
    if (
        not isinstance(profile_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", profile_id)
    ):
        raise ContractError("invalid acceptance profile_id")
    return acceptance_root(plan_dir) / "profiles" / f"{profile_id}.json"


def command_start_acceptance_profile(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    source_path = normalize_owned_path(
        plan_dir, str(Path(args.profile).resolve()),
    )
    source = read_json(source_path)
    if set(source) != {
        "schema_version", "profile_id", "planned_duration_seconds",
        "required_session_restarts", "fault_scenarios", "allowed_claims",
    }:
        raise ContractError("acceptance profile has an invalid closed shape")
    fault_scenarios = source.get("fault_scenarios")
    allowed_claims = source.get("allowed_claims")
    if (
        source.get("schema_version") != SCHEMA_VERSION
        or isinstance(source.get("planned_duration_seconds"), bool)
        or not isinstance(source.get("planned_duration_seconds"), int)
        or not 1 <= source["planned_duration_seconds"] <= 31 * 24 * 60 * 60
        or isinstance(source.get("required_session_restarts"), bool)
        or not isinstance(source.get("required_session_restarts"), int)
        or not 1 <= source["required_session_restarts"] <= 10000
        or not isinstance(fault_scenarios, list)
        or not all(isinstance(value, str) for value in fault_scenarios)
        or len(fault_scenarios) != len(set(fault_scenarios))
        or set(fault_scenarios) != ACCEPTANCE_FAULT_SCENARIOS
        or not isinstance(allowed_claims, list)
        or not allowed_claims
        or not all(isinstance(value, str) for value in allowed_claims)
        or len(allowed_claims) != len(set(allowed_claims))
        or not set(allowed_claims).issubset(ACCEPTANCE_CLAIM_KINDS)
    ):
        raise ContractError("acceptance profile values are invalid or incomplete")
    target = acceptance_profile_path(plan_dir, source["profile_id"])
    identity = {
        **source,
        "plan_id": plan_identity(plan_dir),
        "source_profile_path": str(source_path),
        "source_profile_sha256": sha256_file(source_path),
    }
    if target.exists():
        prior = read_json(target)
        stable = {key: value for key, value in prior.items() if key != "started_at"}
        if stable != identity:
            raise ContractError("acceptance profile identity collision")
        return {
            "ok": True, "idempotent": True, "profile_path": str(target), **prior,
        }
    profile = {**identity, "started_at": utc_now()}
    atomic_write_json(target, profile, immutable=True)
    append_jsonl_once(
        acceptance_root(plan_dir) / "profile_audit.jsonl",
        "profile_id", profile["profile_id"], profile,
    )
    return {"ok": True, "profile_path": str(target), **profile}


def load_acceptance_evidence_file(
    plan_dir: Path, path: Path, expected_fields: set[str], name: str,
) -> dict[str, Any]:
    path = normalize_owned_path(plan_dir, str(path.resolve()))
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{name} must be an existing regular file")
    value = read_json(path)
    if set(value) != expected_fields:
        raise ContractError(f"{name} has an invalid closed shape")
    return value


def command_complete_acceptance_profile(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    profile_path = acceptance_profile_path(plan_dir, args.profile_id)
    profile = read_json(profile_path)
    target = acceptance_root(plan_dir) / "completed" / f"{args.profile_id}.json"
    if target.exists():
        return {
            "ok": True, "idempotent": True,
            "acceptance_receipt": str(target), **read_json(target),
        }
    fault_paths = [Path(value).resolve() for value in args.fault_evidence]
    if len(fault_paths) != len(ACCEPTANCE_FAULT_SCENARIOS):
        raise ContractError("acceptance completion requires exactly seven fault records")
    faults: dict[str, dict[str, Any]] = {}
    manifest: list[dict[str, str]] = []
    for path in fault_paths:
        fault = load_acceptance_evidence_file(
            plan_dir, path,
            {
                "schema_version", "profile_id", "scenario", "status",
                "checks", "evidence",
            },
            "fault evidence",
        )
        scenario = fault.get("scenario")
        if (
            fault.get("schema_version") != SCHEMA_VERSION
            or fault.get("profile_id") != args.profile_id
            or scenario not in ACCEPTANCE_FAULT_SCENARIOS
            or scenario in faults
            or fault.get("status") != "PASS"
            or fault.get("checks") != {
                "authority": True,
                "idempotency": True,
                "recovery": True,
                "evidence": True,
            }
        ):
            raise ContractError("fault evidence did not pass the complete acceptance profile")
        checked_evidence = verify_manifest_items(
            fault["evidence"], base_dir=plan_dir,
        )
        faults[scenario] = fault
        manifest.append({
            "path": str(path),
            "sha256": sha256_file(path),
            "purpose": f"fault:{scenario}",
        })
        manifest.extend({
            **item,
            "purpose": f"fault:{scenario}:{item['purpose']}",
        } for item in checked_evidence)
    if set(faults) != ACCEPTANCE_FAULT_SCENARIOS:
        raise ContractError("fault evidence does not cover the exact scenario registry")
    session_paths = [Path(value).resolve() for value in args.session_observation]
    required_sessions = profile["required_session_restarts"] + 1
    if len(session_paths) < required_sessions:
        raise ContractError("soak has fewer sessions than the frozen restart requirement")
    sessions: list[dict[str, Any]] = []
    for path in session_paths:
        session = load_acceptance_evidence_file(
            plan_dir, path,
            {
                "schema_version", "profile_id", "session_id", "started_at",
                "completed_at", "new_transition_ids", "accepted_evidence_ids",
                "max_controller_overlap", "unauthorized_recovery_actions",
            },
            "session observation",
        )
        if (
            session.get("schema_version") != SCHEMA_VERSION
            or session.get("profile_id") != args.profile_id
            or not isinstance(session.get("session_id"), str)
            or not session["session_id"]
            or session["session_id"] in {
                value["session_id"] for value in sessions
            }
            or session.get("max_controller_overlap") != 1
            or session.get("unauthorized_recovery_actions") != 0
            or not isinstance(session.get("new_transition_ids"), list)
            or len(session["new_transition_ids"])
            != len(set(session["new_transition_ids"]))
            or not all(
                isinstance(value, str) and value
                for value in session["new_transition_ids"]
            )
            or not isinstance(session.get("accepted_evidence_ids"), list)
            or len(session["accepted_evidence_ids"])
            != len(set(session["accepted_evidence_ids"]))
            or not all(
                isinstance(value, str) and value
                for value in session["accepted_evidence_ids"]
            )
        ):
            raise ContractError("session observation violates the frozen soak contract")
        started = parse_utc(session["started_at"])
        completed = parse_utc(session["completed_at"])
        if completed <= started:
            raise ContractError("session must have a positive observed duration")
        session["_started"] = started
        session["_completed"] = completed
        sessions.append(session)
        manifest.append({
            "path": str(path),
            "sha256": sha256_file(path),
            "purpose": f"session:{session['session_id']}",
        })
    sessions.sort(key=lambda value: value["_started"])
    transitions: set[str] = set()
    prior_evidence: set[str] = set()
    for session in sessions:
        new_transitions = set(session["new_transition_ids"])
        if transitions & new_transitions:
            raise ContractError("soak contains a duplicate applied transition")
        transitions |= new_transitions
        current_evidence = set(session["accepted_evidence_ids"])
        if not prior_evidence.issubset(current_evidence):
            raise ContractError("soak lost previously accepted evidence")
        prior_evidence = current_evidence
    overlap_events: list[tuple[datetime, int]] = []
    for session in sessions:
        overlap_events.extend([
            (session["_started"], 1),
            (session["_completed"], -1),
        ])
    active = 0
    measured_max_overlap = 0
    for _, delta in sorted(overlap_events, key=lambda item: (item[0], item[1])):
        active += delta
        measured_max_overlap = max(measured_max_overlap, active)
    if measured_max_overlap > 1:
        raise ContractError("soak observed overlapping controller sessions")
    completed_at = datetime.now(timezone.utc).replace(microsecond=0)
    started_at = parse_utc(profile["started_at"])
    if any(
        session["_started"] < started_at
        or session["_completed"] > completed_at + timedelta(seconds=5)
        for session in sessions
    ):
        raise ContractError("session observation falls outside the measured profile interval")
    measured_duration = int((completed_at - started_at).total_seconds())
    if measured_duration < profile["planned_duration_seconds"]:
        raise ContractError("soak completed before its frozen planned duration")
    clean_sessions = [
        {
            key: value for key, value in session.items()
            if not key.startswith("_")
        }
        for session in sessions
    ]
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "profile_id": args.profile_id,
        "profile_path": str(profile_path),
        "profile_sha256": sha256_file(profile_path),
        "status": "PASS",
        "fault_scenarios": sorted(faults),
        "session_ids": [value["session_id"] for value in clean_sessions],
        "observed_session_restarts": len(clean_sessions) - 1,
        "measured_duration_seconds": measured_duration,
        "measured_max_controller_overlap": measured_max_overlap,
        "applied_transition_ids": sorted(transitions),
        "accepted_evidence_ids": sorted(prior_evidence),
        "unauthorized_recovery_actions": 0,
        "evidence_manifest": manifest,
        "evidence_manifest_sha256": sha256_json(manifest),
        "started_at": profile["started_at"],
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
    }
    atomic_write_json(target, receipt, immutable=True)
    append_jsonl_once(
        acceptance_root(plan_dir) / "completion_audit.jsonl",
        "profile_id", args.profile_id, receipt,
    )
    return {"ok": True, "acceptance_receipt": str(target), **receipt}


def reject_acceptance_claim(
    plan_dir: Path, profile_id: str, claim_kind: str, reason: str,
) -> None:
    append_jsonl(acceptance_root(plan_dir) / "claim_rejections.jsonl", {
        "schema_version": SCHEMA_VERSION,
        "profile_id": profile_id,
        "claim_kind": claim_kind,
        "reason": reason,
        "rejected_at": utc_now(),
    })
    raise ContractError(reason)


def command_validate_acceptance_claim(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    claimed = require_non_negative_int(
        args.claimed_duration_seconds, "claimed_duration_seconds",
    )
    profile_path = acceptance_profile_path(plan_dir, args.profile_id)
    profile = read_json(profile_path)
    receipt_path = acceptance_root(plan_dir) / "completed" / f"{args.profile_id}.json"
    receipt = read_json(receipt_path)
    if (
        receipt.get("status") != "PASS"
        or receipt.get("profile_sha256") != sha256_file(profile_path)
        or receipt.get("evidence_manifest_sha256")
        != sha256_json(receipt.get("evidence_manifest"))
    ):
        reject_acceptance_claim(
            plan_dir, args.profile_id, args.claim_kind,
            "acceptance receipt is missing or invalid",
        )
    try:
        verify_manifest_items(receipt["evidence_manifest"], base_dir=plan_dir)
    except ContractError:
        reject_acceptance_claim(
            plan_dir, args.profile_id, args.claim_kind,
            "acceptance evidence changed after completion",
        )
    if args.claim_kind not in profile["allowed_claims"]:
        reject_acceptance_claim(
            plan_dir, args.profile_id, args.claim_kind,
            "claim kind is not authorized by the frozen acceptance profile",
        )
    measured = receipt["measured_duration_seconds"]
    if claimed > measured:
        reject_acceptance_claim(
            plan_dir, args.profile_id, args.claim_kind,
            "claimed duration exceeds the completed measured interval",
        )
    minimum = ACCEPTANCE_CLAIM_MINIMUM_SECONDS[args.claim_kind]
    if measured < minimum or claimed < minimum:
        reject_acceptance_claim(
            plan_dir, args.profile_id, args.claim_kind,
            "measured interval does not satisfy the claim-kind minimum",
        )
    identity = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "profile_id": args.profile_id,
        "claim_kind": args.claim_kind,
        "claimed_duration_seconds": claimed,
        "measured_duration_seconds": measured,
        "acceptance_receipt_path": str(receipt_path),
        "acceptance_receipt_sha256": sha256_file(receipt_path),
        "bounded_by_measured_evidence": True,
    }
    claim_id = f"claim_{sha256_json(identity)}"
    target = acceptance_root(plan_dir) / "claims" / f"{claim_id}.json"
    if target.exists():
        return {
            "ok": True, "idempotent": True, "claim_receipt": str(target),
            **read_json(target),
        }
    claim = {**identity, "claim_id": claim_id, "validated_at": utc_now()}
    atomic_write_json(target, claim, immutable=True)
    append_jsonl_once(
        acceptance_root(plan_dir) / "claim_audit.jsonl",
        "claim_id", claim_id, claim,
    )
    return {"ok": True, "claim_receipt": str(target), **claim}


def pivot_eligibility(plan_dir: Path) -> dict[str, Any]:
    target = plan_dir / "state" / "failure_state.json"
    state = read_json(target) if target.exists() else failure_state_default(plan_dir)
    expected_threshold = failure_state_default(plan_dir)["scientific_pivot_threshold"]
    if state.get("scientific_pivot_threshold") != expected_threshold:
        raise ContractError("scientific pivot threshold changed from the frozen policy")
    epoch = int(state.get("pivot_epoch", 0))
    consumed = set(state.get("consumed_scientific_event_ids", []))
    events = [
        event for event in state.get("scientific_failure_events", [])
        if event.get("epoch") == epoch and event.get("validated") is True
        and event.get("event_id") not in consumed
    ]
    distinct_events: dict[str, dict[str, Any]] = {}
    for event in events:
        distinct_events.setdefault(str(event.get("fingerprint")), event)
    event_ids = sorted(event["event_id"] for event in distinct_events.values())
    distinct = len(event_ids)
    threshold = expected_threshold
    return {
        "eligible": distinct >= threshold,
        "distinct_scientific_failures": distinct,
        "threshold": threshold,
        "pivot_epoch": epoch,
        "pivot_cursor": int(state.get("pivot_cursor", 0)),
        "eligible_event_ids": event_ids,
    }


def command_pivot_eligibility(args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, **pivot_eligibility(Path(args.plan_dir).resolve())}


def command_apply_structural_pivot(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    proposal_path = Path(args.proposal).resolve()
    proposal = read_json(proposal_path)
    failure_state = read_json(plan_dir / "state" / "failure_state.json")
    last_applied = failure_state.get("last_applied_pivot")
    recovering = (
        isinstance(last_applied, dict)
        and last_applied.get("proposal_path") == str(proposal_path)
        and last_applied.get("proposal_sha256") == sha256_file(proposal_path)
    )
    if recovering:
        recovery_request_id = last_applied.get("frontier_request_id")
        if not isinstance(recovery_request_id, str):
            raise ContractError("committed structural pivot request identity is invalid")
        transition_receipt = check_transition_receipt(
            plan_dir, plan_identity(plan_dir), "authorize_structural_pivot",
            recovery_request_id, verify_live_manifest=False,
        )
        _, recovery_request = load_request(
            plan_dir, transition_receipt["request_id"], verify_live_manifest=False,
        )
        proposal_items = [
            item for item in recovery_request["context_manifest"]
            if item.get("purpose") == "pivot_proposal"
        ]
        if len(proposal_items) != 1 or any((
            Path(proposal_items[0]["path"]).resolve() != proposal_path,
            proposal_items[0].get("sha256") != sha256_file(proposal_path),
        )):
            raise ContractError("committed structural pivot proposal binding mismatch")
    else:
        transition_receipt = require_transition_evidence(
            plan_dir, "authorize_structural_pivot", {"pivot_proposal": proposal_path}
        )
    _, frontier_request = load_request(
        plan_dir, transition_receipt["request_id"], verify_live_manifest=not recovering,
    )
    pre_state_items = [
        item for item in frontier_request["context_manifest"]
        if item.get("purpose") == "failure_state"
    ]
    if len(pre_state_items) != 1 or not isinstance(pre_state_items[0].get("sha256"), str):
        raise ContractError("CP-03 request must bind one frozen failure state")
    frozen_event_ids = frontier_request.get("pivot_event_ids")
    request_epoch = frontier_request.get("pivot_epoch")
    if isinstance(request_epoch, bool) or not isinstance(request_epoch, int) or request_epoch < 0:
        raise ContractError("CP-03 request has an invalid pivot epoch")
    if not isinstance(frozen_event_ids, list) or not all(isinstance(value, str) for value in frozen_event_ids):
        raise ContractError("CP-03 request has invalid frozen failure events")
    direction = proposal.get("direction")
    if not isinstance(direction, dict) or set(direction) != SCIENTIFIC_DIRECTION_FIELDS:
        raise ContractError("pivot proposal requires a complete direction descriptor")
    normalized = {
        key: " ".join(value.strip().lower().split()) if isinstance(value, str) else value
        for key, value in sorted(direction.items())
    }
    if not all(isinstance(value, str) and value for value in normalized.values()):
        raise ContractError("pivot direction fields must be non-empty strings")
    evaluator_contract = read_json(plan_dir / "state" / "evaluator_contract.json")
    direction_hash = sha256_json({
        "scientific_descriptor": normalized,
        "frozen_evaluator_identity": evaluator_contract["contract_sha256"],
    })
    receipt_base = {
        "schema_version": 1, "plan_id": plan_identity(plan_dir), "direction": normalized,
        "direction_sha256": direction_hash, "proposal_path": str(proposal_path),
        "proposal_sha256": sha256_file(proposal_path),
        "frontier_request_id": transition_receipt["request_id"],
        "pre_state_sha256": pre_state_items[0]["sha256"],
        "pivot_epoch": request_epoch,
        "consumed_event_ids": frozen_event_ids,
        "frontier_receipt_sha256": sha256_file(
            transition_receipt_path(
                plan_dir, "authorize_structural_pivot", transition_receipt["request_id"]
            )
        ),
    }
    target = plan_dir / "state" / "structural_pivots" / (
        f"pivot_epoch_{request_epoch:04d}_{transition_receipt['request_id']}.json"
    )
    if target.exists():
        prior = read_json(target)
        if all(prior.get(key) == value for key, value in receipt_base.items()):
            return {"ok": True, "idempotent": True, "pivot_receipt": str(target), **prior}
        raise ContractError("structural pivot request was already consumed with another proposal")
    if isinstance(last_applied, dict) and last_applied.get("frontier_request_id") == transition_receipt["request_id"]:
        if (
            not all(last_applied.get(key) == value for key, value in receipt_base.items())
            or last_applied.get("post_state_sha256") != sha256_json({
                key: value for key, value in failure_state.items()
                if key != "last_applied_pivot"
            })
            or failure_state.get("pivot_epoch") != request_epoch + 1
            or not set(frozen_event_ids).issubset(
                set(failure_state.get("consumed_scientific_event_ids", []))
            )
        ):
            raise ContractError("committed structural pivot recovery identity mismatch")
        atomic_write_json(target, last_applied, immutable=True)
        append_jsonl_once(
            plan_dir / "state" / "structural_pivot_audit.jsonl",
            "frontier_request_id", transition_receipt["request_id"], last_applied,
        )
        return {"ok": True, "recovered": True, "pivot_receipt": str(target), **last_applied}
    eligibility = pivot_eligibility(plan_dir)
    if not eligibility["eligible"]:
        raise ContractError("structural pivot threshold is not satisfied")
    if request_epoch != eligibility["pivot_epoch"]:
        raise ContractError("CP-03 request belongs to a different pivot epoch")
    if frozen_event_ids != eligibility["eligible_event_ids"]:
        raise ContractError("CP-03 request does not freeze the current eligible failure events")
    if direction_hash in failure_state.get("direction_registry", {}):
        raise ContractError("pivot direction duplicates a failed scientific direction")
    receipt = {**receipt_base, "applied_at": utc_now()}
    # failure_state is the atomic consumption authority. A receipt can be
    # reconstructed from last_applied_pivot after interruption.
    lock_path = plan_dir / "state" / ".failure.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        failure_state = read_json(plan_dir / "state" / "failure_state.json")
        current = pivot_eligibility(plan_dir)
        if current["pivot_epoch"] != eligibility["pivot_epoch"] or current["eligible_event_ids"] != frozen_event_ids:
            raise ContractError("scientific failure epoch changed while applying pivot")
        failure_state.setdefault("consumed_scientific_event_ids", []).extend(frozen_event_ids)
        failure_state["pivot_cursor"] = int(failure_state.get("pivot_cursor", 0)) + len(frozen_event_ids)
        failure_state["pivot_epoch"] = eligibility["pivot_epoch"] + 1
        failure_state["epoch_direction_fingerprints"] = []
        failure_state["updated_at"] = utc_now()
        receipt["post_state_sha256"] = sha256_json({
            key: value for key, value in failure_state.items()
            if key != "last_applied_pivot"
        })
        failure_state["last_applied_pivot"] = receipt
        atomic_write_json(plan_dir / "state" / "failure_state.json", failure_state)
        if os.environ.get("HARNESS_FAULT_AFTER_PIVOT_STATE") == "1":
            raise ContractError("simulated crash after structural pivot state commit")
    atomic_write_json(target, receipt, immutable=True)
    append_jsonl_once(
        plan_dir / "state" / "structural_pivot_audit.jsonl",
        "frontier_request_id", transition_receipt["request_id"], receipt,
    )
    return {"ok": True, "pivot_receipt": str(target), **receipt}


def command_resolve_acceptance_dispute(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    resolution_path = Path(args.resolution).resolve()
    resolution = read_json(resolution_path)
    transition_receipt = require_transition_evidence(
        plan_dir, "resolve_acceptance_dispute", {"dispute_record": resolution_path}
    )
    if set(resolution) != {"candidate_id", "resolution", "rationale"}:
        raise ContractError("dispute resolution requires exactly candidate_id, resolution, rationale")
    if resolution["resolution"] not in {"accept", "reject", "rerun"}:
        raise ContractError("invalid dispute resolution")
    receipt = {
        "schema_version": 1, "plan_id": plan_identity(plan_dir), **resolution,
        "resolution_path": str(resolution_path), "resolution_sha256": sha256_file(resolution_path),
        "frontier_request_id": transition_receipt["request_id"],
        "frontier_receipt_sha256": sha256_file(transition_receipt_path(
            plan_dir, "resolve_acceptance_dispute", transition_receipt["request_id"]
        )),
        "resolved_at": utc_now(),
    }
    target = (
        plan_dir / "state" / "acceptance_disputes" / resolution["candidate_id"]
        / f"{transition_receipt['request_id']}.json"
    )
    if target.exists():
        prior = read_json(target)
        if (
            prior.get("resolution_sha256") == receipt["resolution_sha256"]
            and prior.get("frontier_request_id") == receipt["frontier_request_id"]
        ):
            return {"ok": True, "idempotent": True, "resolution_receipt": str(target), **prior}
        raise ContractError("acceptance dispute request was already consumed with another resolution")
    atomic_write_json(target, receipt, immutable=True)
    return {"ok": True, "resolution_receipt": str(target), **receipt}


def codex_host_entry_root(plan_dir: Path) -> Path:
    return plan_dir / "control" / "codex-host-entry" / "v1"


def codex_host_activation_root(plan_dir: Path) -> Path:
    return plan_dir / "state" / "codex_host_entry" / "v1"


def validate_closed_brief_path(
    raw: Any, field: str, *, require_directory: bool,
) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ContractError(f"$.{field} must be a non-empty absolute path")
    candidate = Path(raw)
    if not candidate.is_absolute() or str(candidate) != str(candidate.resolve()):
        raise ContractError(f"$.{field} must be a canonical absolute path")
    cursor = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            raise ContractError(f"$.{field} must not traverse a symlink: {cursor}")
    if require_directory and not candidate.is_dir():
        raise ContractError(f"$.{field} must be an existing directory: {candidate}")
    if not require_directory and not candidate.exists():
        raise ContractError(f"$.{field} does not exist: {candidate}")
    return candidate


def validate_closed_brief(brief: dict[str, Any], plan_dir: Path) -> dict[str, Any]:
    schema = read_json(CODEX_HOST_BRIEF_SCHEMA)
    validate_supported_schema(schema)
    validate_schema(brief, schema)
    for field in ("objective", "target_venue", "initial_direction"):
        if not brief[field].strip():
            raise ContractError(f"$.{field} must not be blank")
    for field in ("candidate_ideas", "stop_conditions"):
        if any(not value.strip() for value in brief[field]):
            raise ContractError(f"$.{field} must not contain blank values")
    if not brief["code_roots"] and not brief["material_roots"]:
        raise ContractError("$.code_roots or $.material_roots must contain at least one root")
    resolved: dict[str, list[str]] = {}
    for field in ("code_roots", "material_roots"):
        resolved[field] = [
            str(validate_closed_brief_path(value, f"{field}[{index}]", require_directory=True))
            for index, value in enumerate(brief[field])
        ]
    for section, field in (
        ("strongest_comparable_baseline", "evidence_paths"),
        ("evaluator_metric_context", "evaluator_paths"),
    ):
        values = brief[section][field]
        resolved[f"{section}.{field}"] = [
            str(validate_closed_brief_path(
                value, f"{section}.{field}[{index}]", require_directory=False,
            ))
            for index, value in enumerate(values)
        ]
    permissions = brief["permissions"]
    if not permissions["external_model_calls"]:
        raise ContractError(
            "$.permissions.external_model_calls must authorize the declared Codex/Claude route"
        )
    for field in ("owned_write_roots", "allowed_read_roots"):
        resolved[f"permissions.{field}"] = [
            str(validate_closed_brief_path(
                value, f"permissions.{field}[{index}]", require_directory=True,
            ))
            for index, value in enumerate(permissions[field])
        ]
    plan_dir = plan_dir.absolute()
    if str(plan_dir) != str(plan_dir.resolve()):
        raise ContractError("plan_dir must be a canonical absolute path")
    if plan_dir.parent.is_symlink() or not plan_dir.parent.is_dir():
        raise ContractError("plan_dir parent must be an existing non-symlink directory")
    owned_roots = [Path(value) for value in resolved["permissions.owned_write_roots"]]
    if not any(plan_dir == root or root in plan_dir.parents for root in owned_roots):
        raise ContractError("plan_dir is outside $.permissions.owned_write_roots")
    allowed_roots = [Path(value) for value in resolved["permissions.allowed_read_roots"]]
    for label in (
        "code_roots", "material_roots",
        "strongest_comparable_baseline.evidence_paths",
        "evaluator_metric_context.evaluator_paths",
    ):
        for value in resolved[label]:
            path = Path(value)
            if not any(path == root or root in path.parents for root in allowed_roots):
                raise ContractError(
                    f"$.{label} path is outside $.permissions.allowed_read_roots: {path}"
                )
    bounds = brief["resource_bounds"]
    minimum_input = bounds["frontier_calls"] * CHATGPT_USAGE_FLOOR["min_input_tokens"]
    minimum_output = bounds["frontier_calls"] * CHATGPT_USAGE_FLOOR["min_output_tokens"]
    if bounds["frontier_input_tokens"] < minimum_input:
        raise ContractError(
            "$.resource_bounds.frontier_input_tokens cannot fund every declared frontier call; "
            f"require at least {minimum_input}"
        )
    if bounds["frontier_output_tokens"] < minimum_output:
        raise ContractError(
            "$.resource_bounds.frontier_output_tokens cannot fund every declared frontier call; "
            f"require at least {minimum_output}"
        )
    return brief


def validate_immutable_binding(path: Path, expected_sha256: Any, label: str) -> None:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_mode & 0o777 != 0o444
        or sha256_file(path) != expected_sha256
    ):
        raise ContractError(f"{label} binding changed")


def validate_codex_host_preparation(plan_dir: Path) -> dict[str, Any]:
    receipt_path = codex_host_entry_root(plan_dir) / "prepared-receipt.json"
    validate_immutable_binding(
        receipt_path, sha256_file(receipt_path) if receipt_path.is_file() else None,
        "Codex host prepared receipt",
    )
    receipt = read_json(receipt_path)
    if receipt.get("plan_id") != plan_identity(plan_dir) or receipt.get("status") != "PREPARED":
        raise ContractError("Codex host prepared receipt correlation mismatch")
    for path_field, hash_field in (
        ("closed_brief_path", "closed_brief_sha256"),
        ("model_policy_path", "model_policy_sha256"),
        ("worker_session_policy_path", "worker_session_policy_sha256"),
        ("initial_planning_request_path", "initial_planning_request_sha256"),
        ("resource_manifest_initial_path", "resource_manifest_initial_sha256"),
    ):
        validate_immutable_binding(
            Path(receipt.get(path_field, "")), receipt.get(hash_field),
            f"Codex host {path_field}",
        )
    if sha256_file(policy_path(plan_dir)) != receipt["model_policy_sha256"]:
        raise ContractError("Codex host model policy changed after preparation")
    return receipt


def command_init_policy(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    target = policy_path(plan_dir)
    if target.exists():
        raise ContractError(f"frozen model policy already exists: {target}")
    require_non_negative_int(args.max_frontier_calls, "max_frontier_calls")
    require_non_negative_int(args.max_frontier_input_tokens, "max_frontier_input_tokens")
    require_non_negative_int(args.max_frontier_output_tokens, "max_frontier_output_tokens")
    if args.frontier_transport == "chatgpt-https":
        minimum_input = (
            args.max_frontier_calls * CHATGPT_USAGE_FLOOR["min_input_tokens"]
        )
        minimum_output = (
            args.max_frontier_calls * CHATGPT_USAGE_FLOOR["min_output_tokens"]
        )
        if (
            args.max_frontier_input_tokens < minimum_input
            or args.max_frontier_output_tokens < minimum_output
        ):
            raise ContractError(
                "frontier plan budget cannot fund every declared ChatGPT call; "
                f"require at least {minimum_input} input and {minimum_output} "
                "output tokens for the declared max_frontier_calls"
            )
    if not 2 <= args.scientific_pivot_threshold <= 10:
        raise ContractError("scientific_pivot_threshold must be between 2 and 10")
    policy = {
        "schema_version": SCHEMA_VERSION,
        "runtime": "claude-code",
        "worker_family": "MiniMax-M3",
        "worker_model": args.worker_model,
        "worker_max_budget_usd": args.worker_max_budget_usd,
        "frontier_model": args.frontier_model,
        "frontier_reasoning_effort": args.frontier_reasoning_effort,
        "frontier_transport": args.frontier_transport,
        "frontier_usage_profile": dict(CHATGPT_USAGE_FLOOR),
        "top_level_plan_audit": {
            "required": True,
            "declared_author_model_family": "MiniMax-M3",
            "reviewer_runtime": "codex",
            "reviewer_model": args.plan_audit_model,
            "reasoning_effort": args.plan_audit_reasoning_effort,
            "checkpoint": "CP-01",
            "dependent_transition": "approve_execution",
        },
        "scientific_pivot_threshold": args.scientific_pivot_threshold,
        "frontier_escalation": {
            "enabled": True,
            "checkpoint_registry": "frontier-advisor-v1",
            "max_calls": args.max_frontier_calls,
            "max_input_tokens": args.max_frontier_input_tokens,
            "max_output_tokens": args.max_frontier_output_tokens,
        },
        "frozen_at": utc_now(),
    }
    normalized_worker = args.worker_model.lower().replace("-", "")
    if "minimax" not in normalized_worker or "m3" not in normalized_worker:
        raise ContractError("worker_model must pin the MiniMax M3 family")
    require_finite_number(args.worker_max_budget_usd, "worker_max_budget_usd")
    if args.worker_max_budget_usd <= 0:
        raise ContractError("worker_max_budget_usd must be positive")
    atomic_write_json(target, policy, immutable=True)
    load_policy(plan_dir)
    return {"ok": True, "policy_path": str(target)}


def command_prepare_codex_host_plan(args: argparse.Namespace) -> dict[str, Any]:
    """Atomically publish a validated, plan-owned Codex Host preparation."""
    raw_source = Path(args.brief)
    if raw_source.is_symlink() or not raw_source.is_file():
        raise ContractError("brief must be an existing regular non-symlink JSON file")
    source = raw_source.resolve()
    brief = read_json(source)
    plan_dir = Path(args.plan_dir).absolute()
    validate_closed_brief(brief, plan_dir)
    resolved_claude = resolve_executable(args.claude_bin, label="Claude Code")
    if plan_dir.exists():
        if not plan_dir.is_dir():
            raise ContractError("plan_dir exists and is not a directory")
        receipt = validate_codex_host_preparation(plan_dir)
        if read_json(Path(receipt["closed_brief_path"])) != brief:
            raise ContractError("existing Codex host plan was prepared from another brief")
        return {"ok": True, "idempotent": True, **receipt}
    bounds = brief["resource_bounds"]
    plan_id = f"plan_{sha256_json(brief)[:24]}"
    temp_dir = plan_dir.parent / f".{plan_dir.name}.prepare-{uuid.uuid4().hex}"
    session_id = str(uuid.uuid4())
    try:
        (temp_dir / "state").mkdir(parents=True)
        entry_root = codex_host_entry_root(temp_dir)
        entry_root.mkdir(parents=True)
        (temp_dir / "control" / "staged-inputs").mkdir(parents=True)
        (temp_dir / "control" / "review-materials").mkdir(parents=True)
        closed_brief_path = entry_root / "closed-brief.json"
        atomic_write_json(closed_brief_path, brief, immutable=True)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": plan_id,
            "plan_dir": str(plan_dir),
            "status": "prepared",
            "owner_id": brief["permissions"]["owner_id"],
            "cleanup_owner": brief["permissions"]["owner_id"],
            "agents": [], "sessions": [], "crons": [], "hooks": [],
            "launchd": [], "local_processes": [], "remote_processes": [],
            "locks": [],
            "resources": [{
                "resource_id": "codex_host_entry_v1",
                "kind": "codex_host_entry",
                "path": "control/codex-host-entry/v1",
                "ephemeral": False,
                "run_scoped": True,
                "cleanup_owner": brief["permissions"]["owner_id"],
            }],
        }
        atomic_write_json(temp_dir / "resource_manifest.json", manifest)
        command_init_policy(argparse.Namespace(
            plan_dir=str(temp_dir), worker_model=args.worker_model,
            worker_max_budget_usd=bounds["worker_max_budget_usd"],
            frontier_model=args.frontier_model,
            frontier_reasoning_effort=args.frontier_reasoning_effort,
            plan_audit_model=PLAN_AUDIT_MODEL,
            plan_audit_reasoning_effort=PLAN_AUDIT_REASONING_EFFORT,
            frontier_transport="chatgpt-https",
            max_frontier_calls=bounds["frontier_calls"],
            max_frontier_input_tokens=bounds["frontier_input_tokens"],
            max_frontier_output_tokens=bounds["frontier_output_tokens"],
            scientific_pivot_threshold=2,
        ))
        model_policy_path = policy_path(temp_dir)
        model_policy = read_json(model_policy_path)
        model_policy["host_runtime"] = "codex"
        model_policy["worker_runtime"] = "claude-code"
        model_policy["initial_plan_author"] = {
            "runtime": "codex", "model": args.frontier_model,
            "reasoning_effort": args.frontier_reasoning_effort,
            "executable_stage_limit": 1,
        }
        model_policy["top_level_plan_audit"]["declared_author_model_family"] = "Codex"
        atomic_write_json(model_policy_path, model_policy, immutable=True)
        session_policy_path = entry_root / "worker-session-policy.json"
        session_policy = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": plan_id,
            "runtime": "claude-code",
            "worker_model": args.worker_model,
            "session_id": session_id,
            "session_mode": "persistent_exact_resume",
            "claude_executable": resolved_claude,
            "permission_mode": "dontAsk",
            "allowed_tool_ceiling": [
                "Bash", "Edit", "Glob", "Grep", "Read",
                "WebFetch", "WebSearch", "Write",
            ],
        }
        atomic_write_json(session_policy_path, session_policy, immutable=True)
        planning_path = entry_root / "initial-planning-request.json"
        planning_request = {
            "schema_version": SCHEMA_VERSION,
            "request_kind": "codex_initial_single_stage_plan",
            "plan_id": plan_id,
            "closed_brief_path": str(plan_dir / closed_brief_path.relative_to(temp_dir)),
            "closed_brief_sha256": sha256_file(closed_brief_path),
            "model_policy_sha256": sha256_file(model_policy_path),
            "author_runtime": "codex",
            "author_model": args.frontier_model,
            "reasoning_effort": args.frontier_reasoning_effort,
            "executable_stage_limit": 1,
            "required_outputs": [
                "optimization_contract", "first_stage_envelope",
                "evaluation_profile", "checkpoint_capacity",
                "preflight_inputs", "durable_graph", "cp01_review_materials",
            ],
            "continuation_policy": "exactly_one_named_next_stage_may_be_pre_authorized",
            "controller_only_transitions": True,
        }
        atomic_write_json(planning_path, planning_request, immutable=True)
        manifest_snapshot_path = entry_root / "resource-manifest.initial.json"
        atomic_write_json(manifest_snapshot_path, manifest, immutable=True)
        receipt_path = entry_root / "prepared-receipt.json"
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": plan_id,
            "status": "PREPARED",
            "closed_brief_path": str(plan_dir / closed_brief_path.relative_to(temp_dir)),
            "closed_brief_sha256": sha256_file(closed_brief_path),
            "model_policy_path": str(plan_dir / model_policy_path.relative_to(temp_dir)),
            "model_policy_sha256": sha256_file(model_policy_path),
            "worker_session_policy_path": str(plan_dir / session_policy_path.relative_to(temp_dir)),
            "worker_session_policy_sha256": sha256_file(session_policy_path),
            "initial_planning_request_path": str(plan_dir / planning_path.relative_to(temp_dir)),
            "initial_planning_request_sha256": sha256_file(planning_path),
            "resource_manifest_initial_path": str(plan_dir / manifest_snapshot_path.relative_to(temp_dir)),
            "resource_manifest_initial_sha256": sha256_file(manifest_snapshot_path),
            "owner_id": brief["permissions"]["owner_id"],
            "prepared_at": utc_now(),
        }
        atomic_write_json(receipt_path, receipt, immutable=True)
        os.replace(temp_dir, plan_dir)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
    return {"ok": True, **validate_codex_host_preparation(plan_dir)}


def validate_codex_host_activation(plan_dir: Path) -> dict[str, Any]:
    receipt_path = codex_host_activation_root(plan_dir) / "activation-receipt.json"
    validate_immutable_binding(
        receipt_path, sha256_file(receipt_path) if receipt_path.is_file() else None,
        "Codex host activation receipt",
    )
    receipt = read_json(receipt_path)
    if receipt.get("plan_id") != plan_identity(plan_dir) or receipt.get("status") != "ACTIVATED":
        raise ContractError("Codex host activation receipt correlation mismatch")
    for path_field, hash_field in (
        ("prepared_receipt_path", "prepared_receipt_sha256"),
        ("authorization_receipt_path", "authorization_receipt_sha256"),
        ("contract_path", "contract_sha256"),
        ("stage_envelope_path", "stage_envelope_sha256"),
        ("evaluation_profile_path", "evaluation_profile_sha256"),
        ("checkpoint_capacity_path", "checkpoint_capacity_sha256"),
        ("preflight_inputs_path", "preflight_inputs_sha256"),
        ("durable_graph_path", "durable_graph_sha256"),
        ("staged_state_snapshot_path", "staged_state_snapshot_sha256"),
        ("research_dossier_path", "research_dossier_sha256"),
        ("worker_session_policy_path", "worker_session_policy_sha256"),
        ("harness_runtime_implementation_path", "harness_runtime_implementation_sha256"),
        ("execution_lifecycle_implementation_path", "execution_lifecycle_implementation_sha256"),
        ("execution_lifecycle_conformance_path", "execution_lifecycle_conformance_sha256"),
    ):
        validate_immutable_binding(
            Path(receipt.get(path_field, "")), receipt.get(hash_field),
            f"Codex host activation {path_field}",
        )
    validate_applied_action_receipt(
        plan_dir, Path(receipt["authorization_receipt_path"]), "authorize_contract",
    )
    implementation_path = Path(receipt["execution_lifecycle_implementation_path"])
    conformance_path = Path(receipt["execution_lifecycle_conformance_path"])
    if (
        sha256_file(Path(receipt["harness_runtime_implementation_path"]))
        != sha256_file(SCRIPT_DIR / "harness-runtime.py")
        or
        sha256_file(implementation_path)
        != sha256_file(SCRIPT_DIR / "worker_artifact_lifecycle.py")
        or read_json(conformance_path)
        != run_worker_artifact_lifecycle_conformance()
        or read_json(conformance_path).get("status") != "PASS"
    ):
        raise ContractError(
            "Codex host execution lifecycle implementation/conformance changed"
        )
    return receipt


def ensure_codex_host_activation_manifest(plan_dir: Path, receipt_path: Path) -> None:
    manifest_path = plan_dir / "resource_manifest.json"
    manifest = read_json(manifest_path)
    manifest["status"] = "activated"
    activation_resource = {
        "resource_id": "codex_host_activation_v1",
        "kind": "authenticated_activation",
        "path": str(receipt_path.relative_to(plan_dir)),
        "ephemeral": False,
        "run_scoped": True,
        "cleanup_owner": manifest.get("cleanup_owner"),
    }
    resources = manifest.setdefault("resources", [])
    prior = next(
        (
            item for item in resources
            if isinstance(item, dict)
            and item.get("resource_id") == activation_resource["resource_id"]
        ),
        None,
    )
    if prior is not None and prior != activation_resource:
        raise ContractError("Codex host activation resource ownership changed")
    if prior is None:
        resources.append(activation_resource)
    atomic_write_json(manifest_path, manifest)


def staged_cp01_execution_dependencies(
    plan_dir: Path, existing_manifest: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Expand CP-01 to every directly executable first-stage dependency.

    Review-material manifests close the scientific plan boundary.  This
    activation-derived manifest separately closes the executable Host/Worker
    boundary without creating a circular pre-authorization hash dependency.
    """
    activation_path = codex_host_activation_root(plan_dir) / "activation-receipt.json"
    activation = validate_codex_host_activation(plan_dir)
    graph_path = Path(activation["durable_graph_path"])
    graph = validate_durable_graph(plan_dir, read_json(graph_path))
    raw_items: list[dict[str, str]] = [
        {
            "path": activation["authorization_receipt_path"],
            "sha256": activation["authorization_receipt_sha256"],
            "purpose": "execution_dependency:initial_authorization_receipt",
        },
        {
            "path": activation["prepared_receipt_path"],
            "sha256": activation["prepared_receipt_sha256"],
            "purpose": "execution_dependency:host_preparation_receipt",
        },
        {
            "path": str(activation_path),
            "sha256": sha256_file(activation_path),
            "purpose": "execution_dependency:host_activation_receipt",
        },
        {
            "path": activation["preflight_inputs_path"],
            "sha256": activation["preflight_inputs_sha256"],
            "purpose": "execution_dependency:preflight_inputs",
        },
        {
            "path": str(graph_path),
            "sha256": activation["durable_graph_sha256"],
            "purpose": "execution_dependency:durable_graph",
        },
        {
            "path": activation["worker_session_policy_path"],
            "sha256": activation["worker_session_policy_sha256"],
            "purpose": "execution_dependency:worker_session_policy",
        },
        {
            "path": activation["harness_runtime_implementation_path"],
            "sha256": activation["harness_runtime_implementation_sha256"],
            "purpose": "execution_dependency:harness_runtime",
        },
        {
            "path": activation["execution_lifecycle_implementation_path"],
            "sha256": activation["execution_lifecycle_implementation_sha256"],
            "purpose": "execution_dependency:lifecycle_implementation",
        },
        {
            "path": activation["execution_lifecycle_conformance_path"],
            "sha256": activation["execution_lifecycle_conformance_sha256"],
            "purpose": "execution_dependency:lifecycle_conformance",
        },
    ]
    for task in graph.get("tasks", []):
        task_id = task["task_id"]
        contract = task["task_contract"]
        raw_items.append({
            "path": contract["path"],
            "sha256": contract["sha256"],
            "purpose": f"execution_dependency:task_contract:{task_id}",
        })
        for index, item in enumerate(task.get("inputs", [])):
            raw_items.append({
                "path": item["path"],
                "sha256": item["sha256"],
                "purpose": (
                    f"execution_dependency:task_input:{task_id}:"
                    f"{index}:{item.get('purpose', 'input')}"
                ),
            })
    seen_paths = {str(Path(item["path"]).resolve()) for item in existing_manifest}
    additions = []
    for item in raw_items:
        resolved = str(Path(item["path"]).resolve())
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        additions.append(item)
    return verify_manifest_items(additions, base_dir=plan_dir)


def command_activate_codex_host_plan(args: argparse.Namespace) -> dict[str, Any]:
    """Bind one authenticated first-stage activation to the prepared entry."""
    plan_dir = Path(args.plan_dir).resolve()
    prepared = validate_codex_host_preparation(plan_dir)
    canonical_prepared = codex_host_entry_root(plan_dir) / "prepared-receipt.json"
    if Path(args.prepared_receipt).resolve() != canonical_prepared:
        raise ContractError("prepared receipt must be the canonical Codex host entry receipt")
    activation_root = codex_host_activation_root(plan_dir)
    receipt_path = activation_root / "activation-receipt.json"
    if receipt_path.is_file():
        receipt = validate_codex_host_activation(plan_dir)
        ensure_codex_host_activation_manifest(plan_dir, receipt_path)
        return {"ok": True, "idempotent": True, **receipt}
    authorization_path = Path(args.authorization_receipt).resolve()
    validate_applied_action_receipt(plan_dir, authorization_path, "authorize_contract")
    immutable_inputs = {
        "contract": Path(args.contract).resolve(),
        "stage_envelope": Path(args.stage_envelope).resolve(),
        "evaluation_profile": Path(args.evaluation_profile).resolve(),
        "checkpoint_capacity": Path(args.checkpoint_capacity).resolve(),
        "preflight_inputs": Path(args.preflight_inputs).resolve(),
        "durable_graph": Path(args.graph).resolve(),
    }
    for label, path in immutable_inputs.items():
        validate_immutable_binding(path, sha256_file(path) if path.is_file() else None, label)
    closed_brief = read_json(Path(prepared["closed_brief_path"]))
    declared_capacity = read_json(immutable_inputs["checkpoint_capacity"])
    declared_envelope = read_json(immutable_inputs["stage_envelope"])
    worker_capacity = declared_capacity.get("worker_dispatch_capacity", {})
    if worker_capacity.get("authorized_calls", 0) > closed_brief["resource_bounds"]["worker_dispatches"]:
        raise ContractError(
            "checkpoint capacity exceeds $.resource_bounds.worker_dispatches"
        )
    if (
        declared_envelope.get("stage_budget_and_stop", {}).get("time_seconds", 0)
        > closed_brief["resource_bounds"]["wall_clock_seconds"]
    ):
        raise ContractError("stage time budget exceeds $.resource_bounds.wall_clock_seconds")
    graph_path = immutable_inputs["durable_graph"]
    graph = validate_durable_graph(plan_dir, read_json(graph_path))
    if graph.get("plan_id") != plan_identity(plan_dir):
        raise ContractError("durable graph belongs to another plan")
    staged = command_init_staged_research(argparse.Namespace(
        plan_dir=str(plan_dir), plan_id=plan_identity(plan_dir),
        contract=str(immutable_inputs["contract"]),
        stage_envelope=str(immutable_inputs["stage_envelope"]),
        evaluation_profile=str(immutable_inputs["evaluation_profile"]),
        checkpoint_capacity=str(immutable_inputs["checkpoint_capacity"]),
        authorization_receipt=str(authorization_path),
        incumbent_sha256=args.incumbent_sha256,
    ))
    preflight = command_preflight_staged_research(argparse.Namespace(
        plan_dir=str(plan_dir),
        preflight_inputs=str(immutable_inputs["preflight_inputs"]),
    ))
    projections = command_rebuild_staged_projections(argparse.Namespace(
        plan_dir=str(plan_dir),
    ))
    activation_root.mkdir(parents=True, exist_ok=True)
    staged_snapshot_path = activation_root / "staged-state-at-activation.json"
    atomic_write_json(staged_snapshot_path, staged_load_state(plan_dir), immutable=True)
    dossier_path = plan_dir / "state" / "research-dossier.md"
    dossier_snapshot_path = activation_root / "research-dossier-at-activation.md"
    atomic_write_bytes(dossier_snapshot_path, dossier_path.read_bytes(), immutable=True)
    harness_runtime_path = activation_root / "harness-runtime.py"
    atomic_write_bytes(
        harness_runtime_path, (SCRIPT_DIR / "harness-runtime.py").read_bytes(),
        immutable=True,
    )
    lifecycle_implementation_path = (
        activation_root / "worker-artifact-lifecycle.py"
    )
    atomic_write_bytes(
        lifecycle_implementation_path,
        (SCRIPT_DIR / "worker_artifact_lifecycle.py").read_bytes(),
        immutable=True,
    )
    lifecycle_conformance_path = (
        activation_root / "worker-artifact-lifecycle-conformance.json"
    )
    lifecycle_conformance = run_worker_artifact_lifecycle_conformance()
    if lifecycle_conformance.get("status") != "PASS":
        raise ContractError("Worker artifact lifecycle conformance failed")
    atomic_write_json(
        lifecycle_conformance_path, lifecycle_conformance, immutable=True,
    )
    worker_policy_path = Path(prepared["worker_session_policy_path"])
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "status": "ACTIVATED",
        "prepared_receipt_path": str(canonical_prepared),
        "prepared_receipt_sha256": sha256_file(canonical_prepared),
        "authorization_receipt_path": str(authorization_path),
        "authorization_receipt_sha256": sha256_file(authorization_path),
        "contract_path": str(immutable_inputs["contract"]),
        "contract_sha256": sha256_file(immutable_inputs["contract"]),
        "stage_envelope_path": str(immutable_inputs["stage_envelope"]),
        "stage_envelope_sha256": sha256_file(immutable_inputs["stage_envelope"]),
        "evaluation_profile_path": str(immutable_inputs["evaluation_profile"]),
        "evaluation_profile_sha256": sha256_file(immutable_inputs["evaluation_profile"]),
        "checkpoint_capacity_path": str(immutable_inputs["checkpoint_capacity"]),
        "checkpoint_capacity_sha256": sha256_file(immutable_inputs["checkpoint_capacity"]),
        "preflight_inputs_path": str(immutable_inputs["preflight_inputs"]),
        "preflight_inputs_sha256": sha256_file(immutable_inputs["preflight_inputs"]),
        "durable_graph_path": str(graph_path),
        "durable_graph_sha256": sha256_file(graph_path),
        "staged_state_snapshot_path": str(staged_snapshot_path),
        "staged_state_snapshot_sha256": sha256_file(staged_snapshot_path),
        "research_dossier_path": str(dossier_snapshot_path),
        "research_dossier_sha256": sha256_file(dossier_snapshot_path),
        "worker_session_policy_path": str(worker_policy_path),
        "worker_session_policy_sha256": sha256_file(worker_policy_path),
        "harness_runtime_implementation_path": str(harness_runtime_path),
        "harness_runtime_implementation_sha256": sha256_file(harness_runtime_path),
        "execution_lifecycle_implementation_path": str(lifecycle_implementation_path),
        "execution_lifecycle_implementation_sha256": sha256_file(lifecycle_implementation_path),
        "execution_lifecycle_conformance_path": str(lifecycle_conformance_path),
        "execution_lifecycle_conformance_sha256": sha256_file(lifecycle_conformance_path),
        "staged_state": staged["state"],
        "preflight_status": preflight.get("status", "passed"),
        "projection_revision": projections.get("audit_revision"),
        "activated_at": utc_now(),
    }
    atomic_write_json(receipt_path, receipt, immutable=True)
    ensure_codex_host_activation_manifest(plan_dir, receipt_path)
    return {"ok": True, **validate_codex_host_activation(plan_dir)}


OUTPUT_CAPABILITY_CLASSES = {"research-intermediate", "paper-deliverable"}


def normalized_task_id(raw: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    if not value:
        raise ContractError("task_id does not have a usable normalized identity")
    return value


def normalize_declared_output(plan_dir: Path, raw: Any) -> dict[str, Any]:
    fields = {"artifact_id", "path", "content_field", "max_bytes", "capability"}
    if not isinstance(raw, dict) or frozenset(raw) not in {
        frozenset(fields), frozenset(fields | {"content_validator"}),
    }:
        raise ContractError(
            "artifact_outputs entries require exactly artifact_id, path, content_field, "
            "max_bytes, capability, and optionally content_validator"
        )
    if not all(isinstance(raw.get(key), str) and raw[key] for key in ("artifact_id", "path", "content_field")):
        raise ContractError("artifact output identifiers and paths must be non-empty strings")
    if isinstance(raw.get("max_bytes"), bool) or not isinstance(raw.get("max_bytes"), int) or not 1 <= raw["max_bytes"] <= 100_000_000:
        raise ContractError("artifact output max_bytes must be in 1..100000000")
    capability = raw.get("capability")
    if (
        not isinstance(capability, dict)
        or set(capability) != {"class"}
        or capability.get("class") not in OUTPUT_CAPABILITY_CLASSES
    ):
        raise ContractError("artifact output capability requires one supported exact class")
    path = normalize_owned_path(plan_dir, raw["path"])
    cursor = path.parent
    while cursor != plan_dir.parent:
        if cursor.is_symlink():
            raise ContractError("artifact output path contains a symlink parent")
        if cursor == plan_dir:
            break
        cursor = cursor.parent
    validator = raw.get("content_validator")
    if validator is not None:
        if (
            not isinstance(validator, dict)
            or set(validator) != {"kind", "source_manifest"}
            or validator.get("kind") != "source_inventory_v1"
        ):
            raise ContractError("artifact content_validator is invalid")
        checked_sources = verify_source_inventory_manifest_items(
            validator.get("source_manifest"), base_dir=plan_dir,
        )
        if len(checked_sources) != len(validator["source_manifest"]):
            raise ContractError("artifact source manifest is incomplete")
        validator = {"kind": "source_inventory_v1", "source_manifest": checked_sources}
    return {
        **raw, "path": str(path),
        **({"content_validator": validator} if validator is not None else {}),
    }


def validate_source_inventory_content(
    content: str, source_manifest: list[dict[str, Any]],
) -> None:
    try:
        validate_source_inventory(content, source_manifest)
    except SourceInventoryValidationError as exc:
        raise ContractError(str(exc)) from exc


def enforce_artifact_byte_cap(
    content: bytes, declaration: dict[str, Any],
) -> None:
    if len(content) > declaration["max_bytes"]:
        raise ContractError("worker artifact exceeds declared max_bytes")


def validate_worker_artifact_proposals(
    result: dict[str, Any], declarations: list[dict[str, Any]], *,
    require_controller_marker: bool = False,
) -> list[dict[str, Any]]:
    proposals = result.get("artifacts")
    if not isinstance(proposals, list):
        raise ContractError("worker structured output must contain an artifacts array")
    by_id = {item["artifact_id"]: item for item in declarations}
    if len(by_id) != len(declarations):
        raise ContractError("artifact output declarations must have unique artifact_id values")
    if len(proposals) != len(declarations):
        raise ContractError("worker artifact proposals do not match declarations")
    checked: list[dict[str, Any]] = []
    for proposal in proposals:
        if not isinstance(proposal, dict) or set(proposal) != {"artifact_id", "path", "content", "sha256"}:
            raise ContractError("worker artifact proposals require exactly artifact_id, path, content, sha256")
        declaration = by_id.get(proposal.get("artifact_id"))
        if declaration is None or proposal.get("path") != declaration["path"]:
            raise ContractError("worker proposed an undeclared artifact path")
        content = proposal.get("content")
        if not isinstance(content, str):
            raise ContractError("worker artifact content must be a string")
        encoded = content.encode("utf-8")
        enforce_artifact_byte_cap(encoded, declaration)
        if require_controller_marker:
            try:
                digest = controller_owned_digest(content, proposal.get("sha256"))
            except WorkerArtifactLifecycleError as exc:
                raise ContractError(str(exc)) from exc
        else:
            # Compatibility for pre-v0.19.2 task contracts. New Codex-Host
            # continuation contracts are accepted only with the exact schema
            # below and therefore can never delegate digest authority here.
            digest = exact_utf8_sha256(content)
            if proposal.get("sha256") != digest:
                raise ContractError("worker artifact content hash mismatch")
        validator = declaration.get("content_validator")
        if validator is not None:
            validate_source_inventory_content(
                content, validator["source_manifest"],
            )
        # The canonical proposal always records the Host-computed digest of
        # the exact returned string.
        proposal["sha256"] = digest
        checked.append(proposal)
    if [item["artifact_id"] for item in checked] != [
        item["artifact_id"] for item in declarations
    ]:
        raise ContractError("worker artifact proposal order changed")
    return checked


def validate_writing_gate_receipt(plan_dir: Path, raw_path: str) -> dict[str, Any]:
    path = Path(raw_path).resolve()
    root = (plan_dir / "state" / "writing_gates").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ContractError("writing gate receipt is outside canonical state") from exc
    gate = read_json(path)
    if path.name != f"{gate.get('decision_sha256')}.json":
        raise ContractError("writing gate receipt identity mismatch")
    decision_body = {
        key: value for key, value in gate.items()
        if key not in {"checked_at", "decision_sha256"}
    }
    if gate.get("decision_sha256") != sha256_json(decision_body):
        raise ContractError("writing gate decision identity mismatch")
    if gate.get("plan_id") != plan_identity(plan_dir):
        raise ContractError("writing gate belongs to another plan")
    for role in ("candidate", "evaluator_contract", "evaluator_verdict"):
        artifact = Path(gate[f"{role}_path"])
        if sha256_file(artifact) != gate[f"{role}_sha256"]:
            raise ContractError(f"writing gate {role} hash changed")
    figure_gate_path = Path(gate["figure_gate_path"])
    if sha256_file(figure_gate_path) != gate["figure_gate_sha256"]:
        raise ContractError("writing gate figure gate hash changed")
    figure_gate = validate_figure_gate_receipt(plan_dir, str(figure_gate_path))
    if figure_gate["required_figure_count"] != gate["required_figure_count"]:
        raise ContractError("writing gate figure count changed")
    receipt_path = transition_receipt_path(
        plan_dir, "start_writing", gate["start_writing_request_id"]
    )
    if sha256_file(receipt_path) != gate["start_writing_receipt_sha256"]:
        raise ContractError("writing gate frontier receipt changed")
    audit_path = plan_dir / "state" / "writing_gate_audit.jsonl"
    audit_entries = [
        strict_json_loads(line) for line in audit_path.read_text().splitlines() if line.strip()
    ] if audit_path.exists() else []
    if gate not in audit_entries:
        raise ContractError("writing gate is absent from the canonical audit")
    source = gate.get("source")
    if source == "validated_verdict":
        verdict, waiver = gate["evaluator_verdict_path"], None
    elif source == "applied_waiver_receipt":
        verdict, waiver = None, gate.get("authority_path")
    else:
        raise ContractError("writing gate has an unknown authority source")
    revalidated = command_check_writing_gate(argparse.Namespace(
        plan_dir=str(plan_dir),
        tier=gate.get("tier"),
        verdict=verdict,
        waiver=waiver,
        figure_gate_receipt=str(figure_gate_path),
    ))
    if Path(revalidated["gate_receipt"]).resolve() != path:
        raise ContractError("writing gate no longer matches its complete authority chain")
    return gate


def require_writer_candidate_input(
    inputs: list[dict[str, str]], gate: dict[str, Any],
) -> None:
    matches = [
        item for item in inputs
        if Path(item["path"]).resolve() == Path(gate["candidate_path"]).resolve()
        and item["sha256"] == gate["candidate_sha256"]
    ]
    if len(matches) != 1:
        raise ContractError("post-gate writer must consume the exact authorized candidate once")


def enforce_output_capability(
    plan_dir: Path, task_id: str, declarations: list[dict[str, Any]], gate_path: str | None,
) -> None:
    if gate_path:
        paper_path = (plan_dir / "artifacts" / "paper" / "paper.md").resolve()
        if (
            len(declarations) != 1
            or declarations[0]["artifact_id"] != "paper_deliverable"
            or declarations[0]["capability"] != {"class": "paper-deliverable"}
            or Path(declarations[0]["path"]) != paper_path
        ):
            raise ContractError("post-gate writer requires the exact canonical paper-deliverable capability")
        return
    root = (plan_dir / "artifacts" / "intermediate" / normalized_task_id(task_id)).resolve()
    for declaration in declarations:
        target = Path(declaration["path"])
        if declaration["capability"] != {"class": "research-intermediate"}:
            raise ContractError("ungated workers require the exact research-intermediate capability")
        try:
            relative = target.relative_to(root)
        except ValueError as exc:
            raise ContractError("research-intermediate output is outside its controller-owned task namespace") from exc
        if relative == Path("."):
            raise ContractError("research-intermediate output must name a file inside its task namespace")


def worker_visible_content_contracts(
    declarations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compile evaluator-facing content requirements into Worker-visible form."""
    contracts: list[dict[str, Any]] = []
    for declaration in declarations:
        validator = declaration.get("content_validator")
        if validator is None:
            continue
        if validator.get("kind") != "source_inventory_v1":
            raise ContractError("unknown Worker-visible content validator")
        contracts.append({
            "artifact_id": declaration["artifact_id"],
            "content_encoding": "strict JSON encoded as the artifact content string",
            "exact_top_level_fields": [
                "schema_version", "records",
                "uncertainties_and_next_questions",
            ],
            "schema_version": 1,
            "record_count": len(validator["source_manifest"]),
            "record_order": "exact source_manifest order",
            "exact_record_fields": [
                "path", "source_sha256", "symbol", "line_start",
                "observation", "hypothesis",
            ],
            "record_rules": {
                "path": "exact source_manifest path",
                "source_sha256": "exact source_manifest sha256",
                "symbol": "ASCII identifier or dotted identifier literally present on line_start",
                "line_start": "one-based integer source line",
                "observation": "exact cited source line with leading/trailing whitespace removed",
                "hypothesis": "non-empty explicitly speculative string, at most 1000 characters",
            },
            "uncertainties_and_next_questions": {
                "minimum_items": 1,
                "maximum_items": 10,
                "maximum_characters_per_item": 500,
            },
            "additional_fields": "forbidden at every object level",
        })
    return contracts


def record_worker_heartbeat(
    plan_dir: Path, run_id: str, *, source: str,
) -> dict[str, Any]:
    status = read_json(worker_status_path(plan_dir, run_id))
    if status.get("status") != "RUNNING":
        raise ContractError("worker heartbeat requires a RUNNING worker")
    observed_at = utc_now()
    sequence = require_non_negative_int(
        status.get("heartbeat_sequence", 0), "heartbeat_sequence",
    ) + 1
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "worker_run_id": run_id,
        "sequence": sequence,
        "source": source,
        "model_dispatches": 0,
        "observed_at": observed_at,
    }
    path = worker_run_dir(plan_dir, run_id) / "heartbeats" / f"{sequence}.json"
    atomic_write_json(path, receipt, immutable=True)
    update_worker_status(plan_dir, run_id, "RUNNING", {
        "heartbeat_sequence": sequence,
        "last_heartbeat_at": observed_at,
        "last_heartbeat_path": str(path),
        "last_heartbeat_sha256": sha256_file(path),
    })
    return receipt


def command_record_worker_heartbeat(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    validate_runtime_assurance_activation(plan_dir)
    receipt = record_worker_heartbeat(
        plan_dir, args.worker_run_id, source=args.source,
    )
    return {"ok": True, "receipt": receipt}


def run_worker_with_heartbeats(
    cmd: list[str], prompt: str, plan_dir: Path, run_id: str,
    timeout: int, heartbeat_interval: int | None,
) -> subprocess.CompletedProcess[str]:
    run_dir = worker_run_dir(plan_dir, run_id)
    stdout_path = run_dir / "transport.stdout"
    stderr_path = run_dir / "transport.stderr"
    with stdout_path.open("w") as stdout_handle, stderr_path.open("w") as stderr_handle:
        proc = subprocess.Popen(
            cmd, cwd=plan_dir, stdin=subprocess.PIPE, stdout=stdout_handle,
            stderr=stderr_handle, text=True, start_new_session=os.name == "posix",
        )
        try:
            process_group_id = os.getpgid(proc.pid)
        except OSError:
            process_group_id = proc.pid
        identity = observe_process_identity(proc.pid)
        update_worker_status(plan_dir, run_id, "RUNNING", {
            "pid": proc.pid,
            "process_group_id": process_group_id,
            "process_identity": identity,
            "worker_command_sha256": sha256_json(cmd),
            "transport_stdout_path": str(stdout_path),
            "transport_stderr_path": str(stderr_path),
            "process_started_at": utc_now(),
        })
        if proc.stdin is None:
            raise ContractError("Worker stdin pipe was not created")
        proc.stdin.write(prompt)
        proc.stdin.close()
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                current_status = read_json(worker_status_path(plan_dir, run_id))
                signal_bound_worker_process(
                    current_status, term_grace_seconds=1.0,
                )
                raise subprocess.TimeoutExpired(cmd, timeout)
            wait_window = remaining
            if heartbeat_interval is not None:
                wait_window = min(float(heartbeat_interval), remaining)
            try:
                return_code = proc.wait(timeout=wait_window)
                break
            except subprocess.TimeoutExpired:
                if heartbeat_interval is None:
                    continue
                current_status = read_json(worker_status_path(plan_dir, run_id))
                if current_status.get("status") == "CANCELLED":
                    continue
                record_worker_heartbeat(
                    plan_dir, run_id, source="controller_worker_monitor",
                )
    stdout = stdout_path.read_text()
    stderr = stderr_path.read_text()
    return subprocess.CompletedProcess(cmd, return_code, stdout, stderr)


def command_dispatch_worker(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    require_controller_not_stopped(plan_dir)
    check_transition_receipt(plan_dir, plan_identity(plan_dir), "approve_execution")
    policy = load_policy(plan_dir)
    contract_path = Path(args.task_contract).resolve()
    contract = read_json(contract_path)
    if contract.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("task contract schema_version must be 1")
    task_id = contract.get("task_id")
    instruction = contract.get("instruction")
    output_schema = contract.get("output_schema")
    if not isinstance(task_id, str) or not task_id:
        raise ContractError("task_id must be a non-empty string")
    if not isinstance(instruction, str) or not instruction:
        raise ContractError("instruction must be a non-empty string")
    if not isinstance(output_schema, dict):
        raise ContractError("output_schema must be an object")
    if contract.get("allowed_write_paths") != []:
        raise ContractError("bounded workers require allowed_write_paths: []")
    completion_check = contract.get("completion_check")
    if not isinstance(completion_check, dict) or completion_check.get("type") != "output_schema":
        raise ContractError("task contract requires a closed output-schema completion_check")
    if set(completion_check) != {"type", "assertion"} or completion_check.get("assertion") != "valid":
        raise ContractError("completion_check must assert valid output_schema")
    validate_supported_schema(output_schema)
    raw_outputs = contract.get("artifact_outputs")
    if not isinstance(raw_outputs, list):
        raise ContractError("task contract requires artifact_outputs")
    declarations = [normalize_declared_output(plan_dir, item) for item in raw_outputs]
    if len({item["artifact_id"] for item in declarations}) != len(declarations):
        raise ContractError("artifact output declarations must have unique artifact_id values")
    if len({item["path"] for item in declarations}) != len(declarations):
        raise ContractError("artifact output declarations must have unique paths")
    writing_gate_path = getattr(args, "writing_gate_receipt", None)
    writing_gate: dict[str, Any] | None = None
    if writing_gate_path:
        writing_gate = validate_writing_gate_receipt(plan_dir, writing_gate_path)
    enforce_output_capability(plan_dir, task_id, declarations, writing_gate_path)
    inputs = verify_manifest_items(contract.get("inputs", []), base_dir=plan_dir)
    context_capsule_path_arg = getattr(args, "context_capsule", None)
    context_capsule: dict[str, Any] | None = None
    if context_capsule_path_arg:
        context_capsule, capsule_task = validate_worker_context_capsule(
            plan_dir, Path(context_capsule_path_arg).resolve(),
        )
        if (
            context_capsule["task_id"] != task_id
            or Path(capsule_task["task_contract"]["path"]).resolve() != contract_path
            or capsule_task["task_contract"]["sha256"] != sha256_file(contract_path)
        ):
            raise ContractError("worker task contract is not bound to the current context capsule")
        capsule_inputs = [
            {"path": item["path"], "sha256": item["sha256"], "purpose": item["purpose"]}
            for item in context_capsule["input_manifest"]
        ]
        if inputs != capsule_inputs:
            raise ContractError("worker inputs are not the exact frozen context capsule manifest")
        validate_runtime_assurance_activation(plan_dir)
    if writing_gate is not None:
        require_writer_candidate_input(inputs, writing_gate)
    allowed_tools = contract.get("allowed_tools", [])
    if not isinstance(allowed_tools, list) or not all(isinstance(v, str) for v in allowed_tools):
        raise ContractError("allowed_tools must be an array of strings")
    forbidden_tools = set(allowed_tools) - READ_ONLY_CLAUDE_TOOLS
    if forbidden_tools:
        raise ContractError(
            "this migration slice permits only read-only Claude tools; "
            f"rejected: {sorted(forbidden_tools)}"
        )
    if not 1 <= args.timeout <= 86400:
        raise ContractError("timeout must be between 1 and 86400 seconds")
    resolved_claude_bin = resolve_executable(args.claude_bin, label="Claude Code")
    stateless_worker_session = bool(
        getattr(args, "stateless_worker_session", False)
    )
    if (
        not stateless_worker_session
        and unattended_durable_plan(plan_dir)
        and context_capsule is None
    ):
        record_worker_session_failure(
            plan_dir, "context_capsule_missing",
            {
                "task_contract_sha256": sha256_file(contract_path),
                "transport_launched": False,
            },
        )
        raise ContractError(
            "context_capsule_missing: persistent unattended Worker requires "
            "the current canonical context capsule"
        )
    operation_id = getattr(args, "operation_id", None)
    run_id = "cwr_" + (operation_id[3:35] if operation_id else uuid.uuid4().hex)
    staged_usage: dict[str, int] | None = None
    if staged_is_active(plan_dir):
        # All deterministic and immutable-input checks must pass before a
        # worker reservation can consume the non-refundable stage budget.
        # A v0.16.1 ordering bug consumed the entire work-unit allowance and
        # only then discovered a stale preflight, leaving no worker run to
        # reconcile.  Keep this guard immediately before the first mutation.
        staged_require_preflight(plan_dir)
        resource_request = contract.get("stage_resource_request")
        if (
            not isinstance(resource_request, dict)
            or set(resource_request) != {"tool_calls", "worker_tokens"}
        ):
            raise ContractError(
                "staged worker contract requires a closed stage_resource_request"
            )
        staged_usage = {
            "tool_calls": require_non_negative_int(
                resource_request["tool_calls"], "stage_resource_request.tool_calls",
            ),
            "worker_tokens": require_non_negative_int(
                resource_request["worker_tokens"], "stage_resource_request.worker_tokens",
            ),
        }
    session_lease = (
        None if stateless_worker_session
        else acquire_worker_session_lease(plan_dir)
    )
    worker_session = (
        None if stateless_worker_session
        else load_or_create_worker_session(
            plan_dir, policy, resolved_claude_bin, allowed_tools,
        )
    )
    (plan_dir / "state" / "worker_runs").mkdir(parents=True, exist_ok=True)
    run_dir = worker_run_dir(plan_dir, run_id, must_exist=False)
    if run_dir.exists():
        prior = read_json(run_dir / "status.json")
        if prior.get("contract_sha256") != sha256_file(contract_path):
            release_worker_session_lease(session_lease)
            raise ContractError("deterministic worker operation identity collision")
        if context_capsule and (
            prior.get("context_capsule_id") != context_capsule["capsule_id"]
            or prior.get("context_capsule_sha256") != context_capsule["capsule_sha256"]
        ):
            release_worker_session_lease(session_lease)
            raise ContractError("deterministic worker operation was rebound to another capsule")
        if prior.get("status") == "RUNNING":
            prior = update_worker_status(plan_dir, run_id, "PAUSED", {
                "failure": "transport_outcome_uncertain", "reconciliation_required": True,
            })
            if worker_session is not None:
                update_worker_session(
                    plan_dir, worker_session, "PAUSED",
                    {"paused_reason": "transport_outcome_uncertain"},
                )
            release_worker_session_lease(session_lease)
            raise ContractError("worker delivery outcome is uncertain; inspect and explicitly reconcile")
        release_worker_session_lease(session_lease)
        return {**prior, "idempotent": True}
    if staged_usage is not None:
        staged_reserve_worker_dispatch_and_budget(
            plan_dir, dispatch_id=run_id, usage=staged_usage,
        )
    else:
        staged_reserve_dispatch(plan_dir, dispatch_id=run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    prompt = json.dumps({
        "role": "bounded research worker",
        "authority": "artifact producer only; do not change plan lifecycle state",
        "task_id": task_id,
        "instruction": instruction,
        "inputs": inputs,
        "artifact_outputs": declarations,
        "artifact_content_contracts": worker_visible_content_contracts(
            declarations,
        ),
        "artifact_contract": "return proposals only; the controller validates and promotes them",
        "artifact_sha256_contract": (
            "For every proposal set sha256 to controller-compute. The trusted "
            "Host computes the lowercase SHA-256 from the exact UTF-8 bytes "
            "in the returned content string after final serialization, "
            "including its final newline or lack thereof, and rejects any "
            "declared digest that does not match those exact bytes."
        ),
        "writing_gate": writing_gate,
        "context_capsule": context_capsule,
    }, indent=2)
    turn_index = (
        None if worker_session is None else worker_session["turn_count"] + 1
    )
    instruction_record = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "worker_run_id": run_id,
        "task_id": task_id,
        "task_contract_path": str(contract_path),
        "task_contract_sha256": sha256_file(contract_path),
        "context_capsule_id": (
            None if context_capsule is None else context_capsule["capsule_id"]
        ),
        "context_capsule_sha256": (
            None if context_capsule is None else context_capsule["capsule_sha256"]
        ),
        "context_state_revision": (
            None if context_capsule is None else context_capsule["state_revision"]
        ),
        "input_manifest_sha256": sha256_json(inputs),
        "artifact_outputs_sha256": sha256_json(declarations),
        "output_schema_sha256": sha256_json(output_schema),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "session_id": (
            None if worker_session is None else worker_session["session_id"]
        ),
        "turn_index": turn_index,
        "created_at": utc_now(),
    }
    instruction_path = run_dir / "instruction.json"
    atomic_write_json(instruction_path, instruction_record, immutable=True)
    cmd = [
        resolved_claude_bin, "-p", "--model", policy["worker_model"],
        "--output-format", "json", "--json-schema", json.dumps(output_schema),
        "--max-budget-usd", str(policy["worker_max_budget_usd"]),
        "--permission-mode", "dontAsk", "--tools", ",".join(allowed_tools),
    ]
    if worker_session is None:
        cmd.append("--no-session-persistence")
    elif worker_session["turn_count"] == 0:
        cmd.extend(["--session-id", worker_session["session_id"]])
    else:
        cmd.extend(["--resume", worker_session["session_id"]])
    input_dirs = sorted({str(Path(item["path"]).parent) for item in inputs})
    if input_dirs:
        # Claude Code treats files outside cwd as permission-denied even when
        # Read is the only exposed tool.  Grant directory visibility for the
        # already hash-verified input manifest; this does not grant write tools.
        cmd.extend(["--add-dir", *input_dirs])
    started = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "task_id": task_id,
        "status": "RUNNING",
        "worker_model": policy["worker_model"],
        "contract_path": str(contract_path),
        "contract_sha256": sha256_file(contract_path),
        "artifact_outputs": declarations,
        "output_capability_class": declarations[0]["capability"]["class"] if declarations else None,
        "model_policy_sha256": sha256_file(policy_path(plan_dir)),
        "worker_session_mode": (
            "stateless" if worker_session is None else "persistent"
        ),
        "worker_session_id": (
            None if worker_session is None else worker_session["session_id"]
        ),
        "worker_session_turn": turn_index,
        "instruction_path": str(instruction_path),
        "instruction_sha256": sha256_file(instruction_path),
        "started_at": utc_now(),
    }
    if writing_gate_path:
        started.update({
            "writing_gate_receipt": str(Path(writing_gate_path).resolve()),
            "writing_gate_receipt_sha256": sha256_file(Path(writing_gate_path).resolve()),
        })
    if context_capsule is not None:
        started.update({
            "context_capsule_path": str(Path(context_capsule_path_arg).resolve()),
            "context_capsule_id": context_capsule["capsule_id"],
            "context_capsule_sha256": context_capsule["capsule_sha256"],
            "context_state_revision": context_capsule["state_revision"],
        })
    atomic_write_json(run_dir / "status.json", started)
    if worker_session is not None:
        worker_session = update_worker_session(
            plan_dir, worker_session, "BUSY", {"active_run_id": run_id},
        )
    try:
        if context_capsule is not None and unattended_durable_plan(plan_dir):
            assurance = validate_runtime_assurance_activation(plan_dir)
            assert assurance is not None
            record_worker_heartbeat(
                plan_dir, run_id, source="controller_worker_start",
            )
            proc = run_worker_with_heartbeats(
                cmd, prompt, plan_dir, run_id, args.timeout,
                max(1, min(60, assurance["heartbeat_stale_seconds"] // 3)),
            )
        else:
            proc = run_worker_with_heartbeats(
                cmd, prompt, plan_dir, run_id, args.timeout, None,
            )
    except FileNotFoundError as exc:
        update_worker_status(plan_dir, run_id, "FAILED", {"failure": "claude_not_found", "completed_at": utc_now()})
        if worker_session is not None:
            commit_worker_session_turn(
                plan_dir, worker_session, run_id=run_id,
                turn_index=turn_index, instruction_path=instruction_path,
                outcome="FAILED", failure="claude_not_found",
            )
        release_worker_session_lease(session_lease)
        raise ContractError(f"Claude Code executable not found: {args.claude_bin}") from exc
    except subprocess.TimeoutExpired as exc:
        update_worker_status(plan_dir, run_id, "PAUSED", {"failure": "worker_timeout", "completed_at": utc_now()})
        if worker_session is not None:
            commit_worker_session_turn(
                plan_dir, worker_session, run_id=run_id,
                turn_index=turn_index, instruction_path=instruction_path,
                outcome="PAUSED", failure="worker_timeout",
            )
        release_worker_session_lease(session_lease)
        raise ContractError(f"Claude worker timed out after {args.timeout}s") from exc
    if proc.returncode != 0:
        transport_failure = classify_claude_transport_failure(
            proc.returncode, proc.stderr,
        )
        terminal = update_worker_status(
            plan_dir, run_id, "FAILED",
            {
                "failure": transport_failure,
                "exit_code": proc.returncode,
                "completed_at": utc_now(),
            },
        )
        if worker_session is not None:
            commit_worker_session_turn(
                plan_dir, worker_session, run_id=run_id,
                turn_index=turn_index, instruction_path=instruction_path,
                outcome=("CANCELLED" if terminal.get("status") == "CANCELLED" else "FAILED"),
                failure=transport_failure,
            )
        release_worker_session_lease(session_lease)
        if terminal.get("status") == "CANCELLED":
            return terminal
        raise ContractError(f"Claude worker failed with exit {proc.returncode}: {proc.stderr[:300]}")
    transport_metadata: dict[str, Any] | None = None
    try:
        if worker_session is not None:
            transport_metadata = claude_transport_metadata(
                proc.stdout, worker_session["session_id"],
            )
        result = extract_structured_claude_output(proc.stdout)
        validate_schema(result, output_schema)
        if not isinstance(result, dict):
            raise ContractError("worker structured output must be an object")
        validate_worker_artifact_proposals(
            result, declarations,
            require_controller_marker=(
                output_schema == exact_worker_artifact_output_schema(declarations)
            ),
        )
        result_path = run_dir / "result.json"
        atomic_write_json(result_path, {"result": result, "artifact_outputs": declarations})
    except ContractError as exc:
        invalid_failure = (
            "response_session_drift"
            if "different session_id" in str(exc)
            else "invalid_worker_output"
        )
        update_worker_status(plan_dir, run_id, "FAILED", {
            "failure": invalid_failure, "completed_at": utc_now(),
        })
        if worker_session is not None:
            commit_worker_session_turn(
                plan_dir, worker_session, run_id=run_id,
                turn_index=turn_index, instruction_path=instruction_path,
                outcome="FAILED", transport_metadata=transport_metadata,
                failure=f"{invalid_failure}:{str(exc)[:160]}",
            )
        release_worker_session_lease(session_lease)
        raise
    completed = update_worker_status(plan_dir, run_id, "COMPLETED", {
        "completed_at": utc_now(), "result_path": str(result_path),
        "result_sha256": sha256_file(result_path),
    })
    if completed.get("status") == "CANCELLED":
        if worker_session is not None:
            commit_worker_session_turn(
                plan_dir, worker_session, run_id=run_id,
                turn_index=turn_index, instruction_path=instruction_path,
                outcome="CANCELLED", transport_metadata=transport_metadata,
                failure="cancelled_during_delivery",
            )
        release_worker_session_lease(session_lease)
        return {**completed, "ignored_result_path": str(result_path)}
    if worker_session is not None:
        commit_worker_session_turn(
            plan_dir, worker_session, run_id=run_id,
            turn_index=turn_index, instruction_path=instruction_path,
            outcome="COMPLETED", transport_metadata=transport_metadata,
        )
    release_worker_session_lease(session_lease)
    return completed


def command_reconcile_orphan_worker_budget(args: argparse.Namespace) -> dict[str, Any]:
    """Refund a worker reservation that provably never created a worker run.

    This is intentionally narrower than a general refund mechanism.  It only
    repairs the legacy ordering fault where stage usage was committed before
    the preflight/dispatch reservation.  A run directory, dispatch marker, or
    dispatch journal makes delivery ambiguous and therefore blocks recovery.
    """
    plan_dir = Path(args.plan_dir).resolve()
    run_id = args.worker_run_id
    run_dir = worker_run_dir(plan_dir, run_id, must_exist=False)
    contract_path = Path(args.task_contract).resolve()
    contract = read_json(contract_path)
    request = contract.get("stage_resource_request")
    if (
        not isinstance(request, dict)
        or set(request) != {"tool_calls", "worker_tokens"}
    ):
        raise ContractError(
            "orphan recovery requires a closed stage_resource_request"
        )
    usage = {
        "tool_calls": require_non_negative_int(
            request["tool_calls"], "stage_resource_request.tool_calls",
        ),
        "worker_tokens": require_non_negative_int(
            request["worker_tokens"], "stage_resource_request.worker_tokens",
        ),
    }
    reservation_id = f"worker:{run_id}"
    with staged_transaction_lock(plan_dir):
        state = staged_load_state(plan_dir)
        root = staged_root(plan_dir)
        journal_path = (
            root / "worker-budget-reconciliations" / f"{run_id}.json"
        )
        if journal_path.exists():
            committed = read_json(journal_path)
            if committed.get("phase") == "COMMITTED":
                if (
                    committed.get("reservation_id") != reservation_id
                    or committed.get("contract_sha256")
                    != sha256_file(contract_path)
                    or committed.get("ledger_after_sha256")
                    != sha256_json(committed.get("ledger_after"))
                ):
                    raise ContractError("orphan worker reconciliation changed")
                return {"ok": True, "idempotent": True, **committed}
        if state["state"] not in {
            "STAGE_AUTHORIZED", "DEVELOPING", "PAUSED",
        }:
            raise ContractError(
                "orphan worker recovery requires an active or paused stage"
            )
        if run_dir.exists():
            raise ContractError(
                "worker run exists; delivery is not provably unstarted"
            )
        dispatch_marker = root / "dispatch-reservations" / f"{run_id}.json"
        dispatch_journal = root / "dispatch-journals" / f"{run_id}.json"
        if dispatch_marker.exists() or dispatch_journal.exists():
            raise ContractError(
                "worker dispatch capacity exists; delivery is ambiguous"
            )
        ledger_path = (
            staged_stage_dir(plan_dir, state["active_stage_id"])
            / "usage-ledger.json"
        )
        ledger = read_json(ledger_path)
        if journal_path.exists():
            journal = read_json(journal_path)
            if (
                journal.get("phase") not in {"PREPARED", "COMMITTED"}
                or journal.get("reservation_id") != reservation_id
                or journal.get("contract_sha256") != sha256_file(contract_path)
                or journal.get("ledger_after_sha256")
                != sha256_json(journal.get("ledger_after"))
            ):
                raise ContractError("orphan worker reconciliation changed")
            if journal["phase"] == "COMMITTED":
                return {"ok": True, "idempotent": True, **journal}
            current_sha = sha256_json(ledger)
            if current_sha == journal["ledger_before_sha256"]:
                atomic_write_json(ledger_path, journal["ledger_after"])
            elif current_sha != journal["ledger_after_sha256"]:
                raise ContractError("orphan worker ledger cannot be reconciled")
            if state["state"] == "PAUSED":
                state["state"] = "STAGE_AUTHORIZED"
                atomic_write_json(staged_state_path(plan_dir), state)
            _staged_ensure_audit_once_locked(
                plan_dir,
                "orphan_worker_budget_reconciled",
                {"worker_run_id": run_id},
                {
                    "reservation_id": reservation_id,
                    "contract_sha256": journal["contract_sha256"],
                    "usage_refunded": journal["usage_refunded"],
                    "ledger_before_sha256": journal["ledger_before_sha256"],
                    "ledger_after_sha256": journal["ledger_after_sha256"],
                },
            )
            journal["phase"] = "COMMITTED"
            journal["committed_at"] = utc_now()
            atomic_write_json(journal_path, journal, immutable=True)
            return {"ok": True, "recovered": True, **journal}
        if ledger["reservation_ids"].count(reservation_id) != 1:
            raise ContractError(
                "exactly one orphan worker budget reservation is required"
            )
        if any(ledger["used"][field] < amount for field, amount in usage.items()):
            raise ContractError("orphan worker usage exceeds the recorded stage usage")
        before = json.loads(json.dumps(ledger))
        after = json.loads(json.dumps(ledger))
        after["reservation_ids"].remove(reservation_id)
        for field, amount in usage.items():
            after["used"][field] -= amount
        exhausted_reasons = {f"{field}_exhausted" for field in usage}
        if after.get("stop_reason") in exhausted_reasons:
            after["stop_reason"] = None
        # No Worker ever started, so restart the scientific work-unit clock at
        # the recovery point instead of charging CP-01 audit latency.
        after["started_at"] = utc_now()
        after["updated_at"] = after["started_at"]
        journal = {
            "schema_version": 1,
            "phase": "PREPARED",
            "worker_run_id": run_id,
            "reservation_id": reservation_id,
            "contract_path": str(contract_path),
            "contract_sha256": sha256_file(contract_path),
            "usage_refunded": usage,
            "ledger_before_sha256": sha256_json(before),
            "ledger_after": after,
            "ledger_after_sha256": sha256_json(after),
            "prepared_at": utc_now(),
        }
        atomic_write_json(journal_path, journal)
        atomic_write_json(ledger_path, after)
        if state["state"] == "PAUSED":
            state["state"] = "STAGE_AUTHORIZED"
            atomic_write_json(staged_state_path(plan_dir), state)
        _staged_ensure_audit_once_locked(
            plan_dir,
            "orphan_worker_budget_reconciled",
            {"worker_run_id": run_id},
            {
                "reservation_id": reservation_id,
                "contract_sha256": journal["contract_sha256"],
                "usage_refunded": usage,
                "ledger_before_sha256": journal["ledger_before_sha256"],
                "ledger_after_sha256": journal["ledger_after_sha256"],
            },
        )
        journal["phase"] = "COMMITTED"
        journal["committed_at"] = utc_now()
        atomic_write_json(journal_path, journal, immutable=True)
        return {"ok": True, **journal}


def command_reconcile_denied_input_worker_budget(
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Release scientific capacity when Claude denied every frozen input.

    The failed transport and its real token usage remain permanently recorded;
    only the scientific work-unit reservation is released because no source
    observation was possible.  This is not a content-quality retry path.
    """
    plan_dir = Path(args.plan_dir).resolve()
    run_id = args.worker_run_id
    run_dir = worker_run_dir(plan_dir, run_id)
    status_path = run_dir / "status.json"
    status = read_json(status_path)
    contract_path = Path(args.task_contract).resolve()
    contract = read_json(contract_path)
    if (
        status.get("status") != "FAILED"
        or status.get("failure") != "invalid_worker_output"
        or status.get("contract_path") != str(contract_path)
        or status.get("contract_sha256") != sha256_file(contract_path)
        or (run_dir / "result.json").exists()
        or (run_dir / "promotion-receipt.json").exists()
    ):
        raise ContractError(
            "worker is not a failed, unpromoted denied-input transport"
        )
    stdout_path = run_dir / "transport.stdout"
    transport = strict_json_loads(stdout_path.read_text())
    denials = transport.get("permission_denials")
    expected_paths = [item["path"] for item in contract.get("inputs", [])]
    denied_paths = [
        item.get("tool_input", {}).get("file_path")
        for item in denials if isinstance(item, dict)
    ] if isinstance(denials, list) else []
    if (
        not expected_paths
        or sorted(denied_paths) != sorted(expected_paths)
        or any(item.get("tool_name") != "Read" for item in denials)
    ):
        raise ContractError(
            "transport does not prove that every frozen input read was denied"
        )
    structured = transport.get("structured_output")
    artifacts = structured.get("artifacts") if isinstance(structured, dict) else None
    if not isinstance(artifacts, list) or len(artifacts) != 1:
        raise ContractError("denied-input transport output shape is not bounded")
    try:
        denied_content = strict_json_loads(artifacts[0]["content"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ContractError("denied-input transport content is not JSON") from exc
    if denied_content.get("records") != []:
        raise ContractError("denied-input transport produced scientific records")
    request = contract.get("stage_resource_request")
    if (
        not isinstance(request, dict)
        or set(request) != {"tool_calls", "worker_tokens"}
    ):
        raise ContractError("denied-input recovery requires closed stage usage")
    usage = {
        field: require_non_negative_int(request[field], f"stage_resource_request.{field}")
        for field in ("tool_calls", "worker_tokens")
    }
    reservation_id = f"worker:{run_id}"
    with staged_transaction_lock(plan_dir):
        state = staged_load_state(plan_dir)
        ledger_path = (
            staged_stage_dir(plan_dir, state["active_stage_id"])
            / "usage-ledger.json"
        )
        ledger = read_json(ledger_path)
        journal_path = (
            staged_root(plan_dir) / "worker-budget-reconciliations"
            / f"{run_id}-denied-input.json"
        )
        if journal_path.exists():
            journal = read_json(journal_path)
            if journal.get("phase") != "COMMITTED":
                raise ContractError("denied-input reconciliation is incomplete")
            return {"ok": True, "idempotent": True, **journal}
        if ledger["reservation_ids"].count(reservation_id) != 1:
            raise ContractError("worker scientific reservation is not refundable")
        after = json.loads(json.dumps(ledger))
        after["reservation_ids"].remove(reservation_id)
        for field, amount in usage.items():
            if after["used"][field] < amount:
                raise ContractError("worker scientific usage ledger underflow")
            after["used"][field] -= amount
        if after.get("stop_reason") in {f"{field}_exhausted" for field in usage}:
            after["stop_reason"] = None
        after["updated_at"] = utc_now()
        model_usage = transport.get("usage")
        journal = {
            "schema_version": 1,
            "phase": "PREPARED",
            "worker_run_id": run_id,
            "reservation_id": reservation_id,
            "failure_class": "permission_denied_before_source_access",
            "denied_input_paths": expected_paths,
            "transport_stdout_sha256": sha256_file(stdout_path),
            "observed_model_usage": model_usage,
            "scientific_capacity_released": usage,
            "ledger_before_sha256": sha256_json(ledger),
            "ledger_after": after,
            "ledger_after_sha256": sha256_json(after),
            "prepared_at": utc_now(),
        }
        atomic_write_json(journal_path, journal)
        atomic_write_json(ledger_path, after)
        _staged_ensure_audit_once_locked(
            plan_dir,
            "denied_input_worker_budget_reconciled",
            {"worker_run_id": run_id},
            {
                "failure_class": journal["failure_class"],
                "transport_stdout_sha256": journal["transport_stdout_sha256"],
                "scientific_capacity_released": usage,
                "observed_model_usage": model_usage,
            },
        )
        journal["phase"] = "COMMITTED"
        journal["committed_at"] = utc_now()
        atomic_write_json(journal_path, journal, immutable=True)
        return {"ok": True, **journal}


def command_reconcile_undisclosed_content_contract_budget(
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Release a work unit made impossible by an undisclosed closed schema."""
    plan_dir = Path(args.plan_dir).resolve()
    run_id = args.worker_run_id
    run_dir = worker_run_dir(plan_dir, run_id)
    status = read_json(run_dir / "status.json")
    contract_path = Path(args.task_contract).resolve()
    contract = read_json(contract_path)
    declarations = [
        normalize_declared_output(plan_dir, item)
        for item in contract.get("artifact_outputs", [])
    ]
    if (
        status.get("status") != "FAILED"
        or status.get("failure") != "invalid_worker_output"
        or status.get("contract_path") != str(contract_path)
        or status.get("contract_sha256") != sha256_file(contract_path)
        or len(declarations) != 1
        or declarations[0].get("content_validator", {}).get("kind")
        != "source_inventory_v1"
        or (run_dir / "result.json").exists()
        or (run_dir / "promotion-receipt.json").exists()
    ):
        raise ContractError(
            "worker is not an unpromoted source-inventory contract failure"
        )
    stdout_path = run_dir / "transport.stdout"
    transport = strict_json_loads(stdout_path.read_text())
    if transport.get("permission_denials") != []:
        raise ContractError("content-contract recovery cannot mask permission faults")
    structured = transport.get("structured_output")
    artifacts = structured.get("artifacts") if isinstance(structured, dict) else None
    if not isinstance(artifacts, list) or len(artifacts) != 1:
        raise ContractError("content-contract transport output is not bounded")
    guessed = strict_json_loads(artifacts[0].get("content", ""))
    legacy_top = {"schema", "records", "uncertainties"}
    legacy_record = {
        "index", "path", "purpose", "sha256", "line", "identifier",
        "observation", "hypothesis",
    }
    records = guessed.get("records") if isinstance(guessed, dict) else None
    if (
        set(guessed) != legacy_top
        or guessed.get("schema") != "source_inventory_v1"
        or not isinstance(records, list)
        or len(records) != len(contract.get("inputs", []))
        or any(not isinstance(item, dict) or set(item) != legacy_record for item in records)
    ):
        raise ContractError(
            "output is not the bounded legacy shape caused by the hidden schema"
        )
    request = contract.get("stage_resource_request")
    if not isinstance(request, dict) or set(request) != {"tool_calls", "worker_tokens"}:
        raise ContractError("content-contract recovery requires closed stage usage")
    usage = {
        field: require_non_negative_int(request[field], f"stage_resource_request.{field}")
        for field in ("tool_calls", "worker_tokens")
    }
    reservation_id = f"worker:{run_id}"
    with staged_transaction_lock(plan_dir):
        state = staged_load_state(plan_dir)
        ledger_path = (
            staged_stage_dir(plan_dir, state["active_stage_id"])
            / "usage-ledger.json"
        )
        ledger = read_json(ledger_path)
        journal_path = (
            staged_root(plan_dir) / "worker-budget-reconciliations"
            / f"{run_id}-undisclosed-content-contract.json"
        )
        if journal_path.exists():
            journal = read_json(journal_path)
            if journal.get("phase") != "COMMITTED":
                raise ContractError("content-contract reconciliation is incomplete")
            return {"ok": True, "idempotent": True, **journal}
        if ledger["reservation_ids"].count(reservation_id) != 1:
            raise ContractError("worker scientific reservation is not refundable")
        after = json.loads(json.dumps(ledger))
        after["reservation_ids"].remove(reservation_id)
        for field, amount in usage.items():
            if after["used"][field] < amount:
                raise ContractError("worker scientific usage ledger underflow")
            after["used"][field] -= amount
        if after.get("stop_reason") in {f"{field}_exhausted" for field in usage}:
            after["stop_reason"] = None
        after["updated_at"] = utc_now()
        journal = {
            "schema_version": 1,
            "phase": "PREPARED",
            "worker_run_id": run_id,
            "reservation_id": reservation_id,
            "failure_class": "controller_content_contract_undisclosed",
            "legacy_shape_sha256": sha256_json(guessed),
            "transport_stdout_sha256": sha256_file(stdout_path),
            "observed_model_usage": transport.get("usage"),
            "scientific_capacity_released": usage,
            "ledger_before_sha256": sha256_json(ledger),
            "ledger_after": after,
            "ledger_after_sha256": sha256_json(after),
            "prepared_at": utc_now(),
        }
        atomic_write_json(journal_path, journal)
        atomic_write_json(ledger_path, after)
        _staged_ensure_audit_once_locked(
            plan_dir,
            "undisclosed_content_contract_budget_reconciled",
            {"worker_run_id": run_id},
            {
                "failure_class": journal["failure_class"],
                "legacy_shape_sha256": journal["legacy_shape_sha256"],
                "transport_stdout_sha256": journal["transport_stdout_sha256"],
                "scientific_capacity_released": usage,
                "observed_model_usage": journal["observed_model_usage"],
            },
        )
        journal["phase"] = "COMMITTED"
        journal["committed_at"] = utc_now()
        atomic_write_json(journal_path, journal, immutable=True)
        return {"ok": True, **journal}


def command_normalize_legacy_source_inventory(args: argparse.Namespace) -> dict[str, Any]:
    """Deterministically compile a pre-disclosure alias shape into validator v2."""
    plan_dir = Path(args.plan_dir).resolve()
    run_id = args.worker_run_id
    run_dir = worker_run_dir(plan_dir, run_id)
    contract_path = Path(args.task_contract).resolve()
    contract = read_json(contract_path)
    status = read_json(run_dir / "status.json")
    recovery_path = (
        staged_root(plan_dir) / "worker-budget-reconciliations"
        / f"{run_id}-undisclosed-content-contract.json"
    )
    recovery = read_json(recovery_path)
    if (
        status.get("status") != "FAILED"
        or status.get("failure") != "invalid_worker_output"
        or status.get("contract_sha256") != sha256_file(contract_path)
        or recovery.get("phase") != "COMMITTED"
        or recovery.get("failure_class")
        != "controller_content_contract_undisclosed"
    ):
        raise ContractError("legacy normalization lacks its controller-fault lineage")
    declarations = [
        normalize_declared_output(plan_dir, item)
        for item in contract.get("artifact_outputs", [])
    ]
    if len(declarations) != 1:
        raise ContractError("legacy normalization requires exactly one artifact")
    declaration = declarations[0]
    validator = declaration.get("content_validator")
    if validator is None or validator.get("kind") != "source_inventory_v1":
        raise ContractError("legacy normalization requires source_inventory_v1")
    stdout_path = run_dir / "transport.stdout"
    transport = strict_json_loads(stdout_path.read_text())
    legacy = strict_json_loads(
        transport["structured_output"]["artifacts"][0]["content"],
    )
    records = legacy.get("records") if isinstance(legacy, dict) else None
    if (
        set(legacy) != {"schema", "records", "uncertainties"}
        or legacy.get("schema") != "source_inventory_v1"
        or not isinstance(records, list)
    ):
        raise ContractError("legacy source inventory alias shape changed")
    normalized = {
        "schema_version": 1,
        "records": [{
            "path": item["path"],
            "source_sha256": item["sha256"],
            "symbol": item["identifier"],
            "line_start": item["line"],
            "observation": item["observation"],
            "hypothesis": item["hypothesis"],
        } for item in records],
        "uncertainties_and_next_questions": legacy["uncertainties"],
    }
    content = canonical_json(normalized)
    enforce_artifact_byte_cap(content, declaration)
    validate_source_inventory_content(
        content.decode("utf-8"), validator["source_manifest"],
    )
    target = Path(declaration["path"])
    digest = hashlib.sha256(content).hexdigest()
    journal_path = run_dir / "controller-normalization-journal.json"
    receipt_path = run_dir / "controller-normalization-receipt.json"
    journal = read_json(journal_path) if journal_path.exists() else None
    if journal is None:
        journal = {
            "schema_version": 1,
            "phase": "PREPARED",
            "worker_run_id": run_id,
            "source_transport_sha256": sha256_file(stdout_path),
            "controller_fault_reconciliation_sha256": sha256_file(recovery_path),
            "validator_implementation_sha256": sha256_file(
                SCRIPT_DIR / "source_inventory_validator.py"
            ),
            "artifact_path": str(target),
            "artifact_sha256": digest,
            "prepared_at": utc_now(),
        }
        atomic_write_json(journal_path, journal)
    if (
        journal.get("worker_run_id") != run_id
        or journal.get("source_transport_sha256") != sha256_file(stdout_path)
        or journal.get("artifact_path") != str(target)
        or journal.get("artifact_sha256") != digest
    ):
        raise ContractError("controller normalization journal changed")
    if target.exists():
        if target.is_symlink() or sha256_file(target) != digest:
            raise ContractError("normalized source inventory destination changed")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, content, immutable=True)
    receipt = {
        "schema_version": 1,
        "worker_run_id": run_id,
        "producer": "MiniMax-M3 proposal plus deterministic controller alias normalization",
        "source_transport_path": str(stdout_path),
        "source_transport_sha256": sha256_file(stdout_path),
        "controller_fault_reconciliation_path": str(recovery_path),
        "controller_fault_reconciliation_sha256": sha256_file(recovery_path),
        "validator_id": "source_inventory_v1",
        "validator_implementation_sha256": journal[
            "validator_implementation_sha256"
        ],
        "artifact_path": str(target),
        "artifact_sha256": digest,
    }
    if receipt_path.exists():
        if read_json(receipt_path) != receipt:
            raise ContractError("controller normalization receipt changed")
    else:
        atomic_write_json(receipt_path, receipt, immutable=True)
    if journal.get("phase") != "COMMITTED":
        journal["phase"] = "COMMITTED"
        journal["receipt_sha256"] = sha256_file(receipt_path)
        journal["committed_at"] = utc_now()
        atomic_write_json(journal_path, journal, immutable=True)
    staged_ensure_audit_once(
        plan_dir,
        "legacy_source_inventory_normalized",
        {"worker_run_id": run_id},
        {
            "artifact_path": str(target),
            "artifact_sha256": digest,
            "receipt_sha256": sha256_file(receipt_path),
            "validator_implementation_sha256": journal[
                "validator_implementation_sha256"
            ],
        },
    )
    return {"ok": True, **receipt, "receipt_path": str(receipt_path)}


def validate_committed_promotion_journal(
    journal: dict[str, Any], status: dict[str, Any], run_dir: Path,
    receipt_sha256: str, promoted: list[dict[str, Any]],
) -> None:
    fields = {
        "schema_version", "phase", "worker_run_id", "contract_sha256",
        "result_sha256", "artifacts", "prepared_at", "committed_at",
        "receipt_sha256",
    }
    artifacts = journal.get("artifacts")
    simplified = []
    if isinstance(artifacts, list):
        for item in artifacts:
            if not isinstance(item, dict) or set(item) != {
                "artifact_id", "path", "sha256", "staged_path",
            }:
                raise ContractError("committed promotion journal shape changed")
            staged_path = Path(item["staged_path"])
            if staged_path.parent.resolve() != (run_dir / "promotion-stage").resolve():
                raise ContractError("committed promotion stage path changed")
            simplified.append({
                "artifact_id": item["artifact_id"], "path": item["path"],
                "sha256": item["sha256"],
            })
    if (
        set(journal) != fields
        or journal.get("schema_version") != 1
        or journal.get("phase") != "COMMITTED"
        or journal.get("worker_run_id") != status.get("run_id")
        or journal.get("contract_sha256") != status.get("contract_sha256")
        or journal.get("result_sha256") != status.get("result_sha256")
        or journal.get("receipt_sha256") != receipt_sha256
        or simplified != promoted
    ):
        raise ContractError("committed promotion journal correlation changed")
    parse_utc(journal.get("prepared_at"))
    parse_utc(journal.get("committed_at"))


def command_promote_worker_artifacts(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    transition_receipt = check_transition_receipt(plan_dir, plan_identity(plan_dir), "approve_execution")
    status = read_json(worker_status_path(plan_dir, args.worker_run_id))
    if status.get("status") != "COMPLETED":
        raise ContractError("only COMPLETED worker runs can be promoted")
    bound_capsule: dict[str, Any] | None = None
    if status.get("context_capsule_path"):
        bound_capsule, _ = validate_worker_context_capsule(
            plan_dir, Path(status["context_capsule_path"]),
        )
        if (
            bound_capsule["capsule_id"] != status.get("context_capsule_id")
            or bound_capsule["capsule_sha256"] != status.get("context_capsule_sha256")
            or bound_capsule["state_revision"] != status.get("context_state_revision")
        ):
            raise ContractError("worker context capsule binding changed before promotion")
    contract_path = Path(status["contract_path"])
    result_path = Path(status["result_path"])
    if sha256_file(contract_path) != status["contract_sha256"] or sha256_file(result_path) != status["result_sha256"]:
        raise ContractError("worker contract or result hash changed")
    gate_path = status.get("writing_gate_receipt")
    writing_gate: dict[str, Any] | None = None
    if gate_path:
        writing_gate = validate_writing_gate_receipt(plan_dir, gate_path)
        if sha256_file(Path(gate_path)) != status.get("writing_gate_receipt_sha256"):
            raise ContractError("writer gate receipt changed before promotion")
    contract = read_json(contract_path)
    if writing_gate is not None:
        require_writer_candidate_input(
            verify_manifest_items(contract.get("inputs", []), base_dir=plan_dir),
            writing_gate,
        )
    task_id = contract.get("task_id")
    if not isinstance(task_id, str) or status.get("task_id") != task_id:
        raise ContractError("worker task identity changed before promotion")
    declarations = [normalize_declared_output(plan_dir, item) for item in contract["artifact_outputs"]]
    if status.get("artifact_outputs") != declarations:
        raise ContractError("frozen artifact capability or path changed before promotion")
    classes = {item["capability"]["class"] for item in declarations}
    if declarations:
        if len(classes) != 1 or status.get("output_capability_class") != next(iter(classes)):
            raise ContractError("frozen output capability class changed before promotion")
    elif status.get("output_capability_class") is not None:
        raise ContractError("empty output contract cannot carry an output capability")
    enforce_output_capability(plan_dir, task_id, declarations, gate_path)
    envelope = read_json(result_path)
    proposals = validate_worker_artifact_proposals(
        envelope["result"], declarations,
        require_controller_marker=(
            contract.get("output_schema")
            == exact_worker_artifact_output_schema(declarations)
        ),
    )
    run_dir = worker_run_dir(plan_dir, args.worker_run_id)
    status_path = run_dir / "status.json"
    journal_path = run_dir / "promotion-journal.json"
    stage_dir = run_dir / "promotion-stage"
    journal = read_json(journal_path) if journal_path.exists() else None
    if journal and journal.get("phase") == "ROLLED_BACK":
        journal_path.unlink()
        journal = None
    if journal and journal.get("phase") == "COMMITTED":
        status_binding = staged_canonical_file(
            status_path, status_path, "completed worker status", immutable=True,
        )
        receipt_path = run_dir / "promotion-receipt.json"
        receipt = read_json(receipt_path)
        receipt_sha256 = sha256_file(receipt_path)
        journal_binding = staged_canonical_file(
            journal_path, journal_path, "committed promotion journal",
            immutable=True,
        )
        validate_committed_promotion_journal(
            journal, status, run_dir, receipt_sha256,
            receipt.get("artifacts", []),
        )
        candidate_records = [
            path for path in (
                plan_dir / "state" / "staged_research" / "v1" / "stages"
            ).glob("*/candidate.json")
            if read_json(path).get("promotion_receipt_path") == str(receipt_path)
        ]
        if len(candidate_records) > 1:
            raise ContractError("promotion is anchored by multiple candidates")
        if candidate_records:
            candidate = read_json(candidate_records[0])
            if (
                candidate.get("completed_worker_status_path") != str(status_path)
                or candidate.get("completed_worker_status_sha256")
                != status_binding["sha256"]
                or candidate.get("promotion_journal_path") != str(journal_path)
                or candidate.get("promotion_journal_sha256")
                != journal_binding["sha256"]
            ):
                raise ContractError("candidate terminal promotion anchor changed")
            staged_resolve_candidate_chain(
                plan_dir, candidate_records[0].parent, candidate,
            )
        return {
            "ok": True, "idempotent": True,
            "promotion_receipt": str(receipt_path), **receipt,
        }
    if journal is None:
        # Preflight the complete destination set before creating any destination.
        for proposal in proposals:
            target = Path(proposal["path"])
            if target.exists():
                raise ContractError(f"artifact promotion refuses overwrite: {target}")
            cursor = target.parent
            while cursor != plan_dir.parent:
                if cursor.is_symlink():
                    raise ContractError("artifact promotion destination has a symlink parent")
                if cursor == plan_dir:
                    break
                cursor = cursor.parent
        stage_dir.mkdir(parents=True, exist_ok=True)
        staged: list[dict[str, Any]] = []
        for index, proposal in enumerate(proposals):
            staged_path = stage_dir / f"{index:04d}.stage"
            try:
                write_exact_utf8(
                    staged_path, proposal["content"], proposal["sha256"],
                )
            except WorkerArtifactLifecycleError as exc:
                raise ContractError(str(exc)) from exc
            staged.append({
                "artifact_id": proposal["artifact_id"], "path": proposal["path"],
                "sha256": proposal["sha256"], "staged_path": str(staged_path),
            })
        journal = {
            "schema_version": 1, "phase": "PREPARED", "worker_run_id": args.worker_run_id,
            "contract_sha256": status["contract_sha256"], "result_sha256": status["result_sha256"],
            "artifacts": staged, "prepared_at": utc_now(),
        }
        atomic_write_json(journal_path, journal)
    elif (
        journal.get("worker_run_id") != args.worker_run_id
        or journal.get("contract_sha256") != status["contract_sha256"]
        or journal.get("result_sha256") != status["result_sha256"]
    ):
        raise ContractError("prepared promotion journal does not match worker output")

    promoted: list[dict[str, Any]] = []
    try:
        for index, item in enumerate(journal["artifacts"]):
            target = Path(item["path"])
            staged_path = Path(item["staged_path"])
            if target.exists():
                if sha256_file(target) != item["sha256"] or staged_path.exists():
                    raise ContractError(f"artifact promotion encountered destination conflict: {target}")
            else:
                if not staged_path.is_file() or sha256_file(staged_path) != item["sha256"]:
                    raise ContractError("prepared promotion stage is missing or changed")
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged_path, target)
            promoted.append({"artifact_id": item["artifact_id"], "path": str(target), "sha256": item["sha256"]})
            if getattr(args, "simulate_crash_after", 0) == index + 1:
                raise ContractError(f"simulated crash after promotion destination {index + 1}")
    except ContractError:
        # A deliberate crash leaves PREPARED for deterministic roll-forward.
        if not str(sys.exc_info()[1]).startswith("simulated crash"):
            for item in promoted:
                target = Path(item["path"])
                if target.is_file() and sha256_file(target) == item["sha256"]:
                    target.unlink()
            journal["phase"] = "ROLLED_BACK"
            journal["rolled_back_at"] = utc_now()
            atomic_write_json(journal_path, journal)
        raise
    receipt = {
        "schema_version": 1, "plan_id": plan_identity(plan_dir), "worker_run_id": args.worker_run_id,
        "contract_sha256": status["contract_sha256"], "result_sha256": status["result_sha256"],
        "approve_execution_request_id": transition_receipt["request_id"],
        "approve_execution_receipt_sha256": sha256_file(transition_receipt_path(
            plan_dir, "approve_execution", transition_receipt["request_id"]
        )),
        "artifacts": promoted, "promoted_at": utc_now(),
    }
    if bound_capsule is not None:
        receipt.update({
            "context_capsule_id": bound_capsule["capsule_id"],
            "context_capsule_sha256": bound_capsule["capsule_sha256"],
            "context_state_revision": bound_capsule["state_revision"],
        })
    if gate_path:
        receipt.update({
            "writing_gate_receipt": gate_path,
            "writing_gate_receipt_sha256": status["writing_gate_receipt_sha256"],
        })
    if len(promoted) == 1:
        receipt["primary_artifact_path"] = promoted[0]["path"]
        receipt["primary_artifact_sha256"] = promoted[0]["sha256"]
    target = run_dir / "promotion-receipt.json"
    atomic_write_json(target, receipt, immutable=True)
    journal.update({"phase": "COMMITTED", "committed_at": utc_now(), "receipt_sha256": sha256_file(target)})
    atomic_write_json(journal_path, journal, immutable=True)
    return {"ok": True, "promotion_receipt": str(target), **receipt}


@contextmanager
def durable_result_commit_lock(plan_dir: Path, identity: str) -> Iterator[None]:
    lock_name = hashlib.sha256(identity.encode()).hexdigest()
    lock_path = durable_root(plan_dir) / "commit_locks" / f"{lock_name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def command_commit_durable_worker_result(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    with durable_result_commit_lock(plan_dir, f"worker:{args.worker_run_id}"):
        return commit_durable_worker_result_locked(args, plan_dir)


def commit_durable_worker_result_locked(
    args: argparse.Namespace, plan_dir: Path,
) -> dict[str, Any]:
    run_dir = worker_run_dir(plan_dir, args.worker_run_id)
    target = durable_root(plan_dir) / "worker_commits" / f"{args.worker_run_id}.json"
    if target.exists():
        return {"ok": True, "idempotent": True, **read_json(target)}
    status = read_json(run_dir / "status.json")
    if not status.get("context_capsule_path"):
        raise ContractError("worker run is not bound to a durable context capsule")
    promotion_path = run_dir / "promotion-receipt.json"
    promotion = read_json(promotion_path)
    journal = read_json(run_dir / "promotion-journal.json")
    if (
        journal.get("phase") != "COMMITTED"
        or journal.get("receipt_sha256") != sha256_file(promotion_path)
        or promotion.get("context_capsule_id") != status.get("context_capsule_id")
        or promotion.get("context_capsule_sha256") != status.get("context_capsule_sha256")
    ):
        raise ContractError("durable worker commit requires a matching committed promotion")
    result_path = durable_root(plan_dir) / "controller_results" / f"{args.worker_run_id}.json"
    result = {
        "schema_version": SCHEMA_VERSION,
        "capsule_id": status["context_capsule_id"],
        "task_id": status["task_id"],
        "evidence": [{
            "path": str(promotion_path),
            "sha256": sha256_file(promotion_path),
        }],
    }
    if result_path.exists():
        if read_json(result_path) != result:
            raise ContractError("durable worker controller-result identity collision")
    else:
        atomic_write_json(result_path, result, immutable=True)
    commit_journal_path = run_dir / "durable-commit-journal.json"
    commit_journal = read_json(commit_journal_path) if commit_journal_path.exists() else None
    if commit_journal is None:
        commit_journal = {
            "schema_version": SCHEMA_VERSION,
            "phase": "PREPARED",
            "worker_run_id": args.worker_run_id,
            "capsule_id": status["context_capsule_id"],
            "promotion_receipt_sha256": sha256_file(promotion_path),
            "controller_result_path": str(result_path),
            "controller_result_sha256": sha256_file(result_path),
            "prepared_at": utc_now(),
        }
        atomic_write_json(commit_journal_path, commit_journal)
    elif any(
        commit_journal.get(field) != expected for field, expected in (
            ("worker_run_id", args.worker_run_id),
            ("capsule_id", status["context_capsule_id"]),
            ("promotion_receipt_sha256", sha256_file(promotion_path)),
            ("controller_result_sha256", sha256_file(result_path)),
        )
    ):
        raise ContractError("durable worker commit journal correlation mismatch")
    applied: dict[str, Any] | None = None
    evidence_root = durable_root(plan_dir) / "evidence"
    if evidence_root.exists():
        for evidence_path in evidence_root.glob("evidence_*.json"):
            evidence = read_json(evidence_path)
            if (
                evidence.get("capsule_id") == status["context_capsule_id"]
                and evidence.get("result_path") == str(result_path)
                and evidence.get("result_sha256") == sha256_file(result_path)
            ):
                applied = {
                    "ok": True,
                    "recovered": True,
                    "evidence_record": str(evidence_path),
                    "evidence_id": evidence["evidence_id"],
                    "projection": read_json(durable_root(plan_dir) / "projection.json"),
                }
                break
    if applied is None:
        applied = command_apply_work_unit_result(argparse.Namespace(
            plan_dir=str(plan_dir),
            capsule=status["context_capsule_path"],
            result=str(result_path),
        ))
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "worker_run_id": args.worker_run_id,
        "capsule_id": status["context_capsule_id"],
        "capsule_sha256": status["context_capsule_sha256"],
        "promotion_receipt_path": str(promotion_path),
        "promotion_receipt_sha256": sha256_file(promotion_path),
        "evidence_id": applied["evidence_id"],
        "evidence_record": applied["evidence_record"],
        "state_revision": applied["projection"]["state_revision"],
        "committed_at": utc_now(),
    }
    atomic_write_json(target, receipt, immutable=True)
    commit_journal.update({
        "phase": "COMMITTED",
        "commit_receipt_path": str(target),
        "commit_receipt_sha256": sha256_file(target),
        "committed_at": receipt["committed_at"],
    })
    atomic_write_json(commit_journal_path, commit_journal)
    return {"ok": True, "commit_receipt": str(target), **receipt}


def command_inspect_worker(args: argparse.Namespace) -> dict[str, Any]:
    return read_json(worker_status_path(Path(args.plan_dir).resolve(), args.worker_run_id))


def command_wait_worker(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.deadline_seconds <= 86400:
        raise ContractError("deadline_seconds must be between 1 and 86400")
    plan_dir = Path(args.plan_dir).resolve()
    deadline = time.monotonic() + args.deadline_seconds
    while True:
        status = read_json(worker_status_path(plan_dir, args.worker_run_id))
        if status.get("status") in TERMINAL_WORKER_STATES:
            if status["status"] != "COMPLETED":
                raise ContractError(f"worker finished with {status['status']}")
            return status
        if time.monotonic() >= deadline:
            raise ContractError("worker wait deadline expired")
        time.sleep(0.1)


def command_send_worker_message(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    status = read_json(worker_status_path(plan_dir, args.worker_run_id))
    if status.get("status") not in {"RUNNING", "PAUSED"}:
        raise ContractError("messages are accepted only for RUNNING or PAUSED workers")
    if not args.message or len(args.message) > 4000:
        raise ContractError("message must contain 1..4000 characters")
    operation_id = getattr(args, "operation_id", None)
    messages_path = worker_status_path(plan_dir, args.worker_run_id).parent / "messages.jsonl"
    if operation_id and messages_path.exists():
        for line in messages_path.read_text().splitlines():
            prior = strict_json_loads(line) if line.strip() else None
            if isinstance(prior, dict) and prior.get("operation_id") == operation_id:
                if prior.get("message") != args.message:
                    raise ContractError("worker message operation identity collision")
                return {"ok": True, "idempotent": True, "receipt": prior}
    receipt = {
        "schema_version": 1, "worker_run_id": args.worker_run_id,
        "message": args.message, "authority": "advisory_only", "ts": utc_now(),
    }
    if operation_id:
        receipt["operation_id"] = operation_id
    append_jsonl(messages_path, receipt)
    return {"ok": True, "receipt": receipt}


def command_schedule_patrol(args: argparse.Namespace) -> dict[str, Any]:
    if not 60 <= args.interval_seconds <= 86400:
        raise ContractError("interval_seconds must be between 60 and 86400")
    plan_dir = Path(args.plan_dir).resolve()
    target = plan_dir / "state" / "schedules" / "runtime_patrol.json"
    value = {
        "schema_version": 1, "schedule_id": "runtime_patrol",
        "interval_seconds": args.interval_seconds, "transport": "file-backed",
        "updated_at": utc_now(),
    }
    if target.exists():
        current = read_json(target)
        if current.get("interval_seconds") == args.interval_seconds:
            return {"ok": True, "idempotent": True, "schedule_path": str(target)}
    atomic_write_json(target, value)
    return {"ok": True, "idempotent": False, "schedule_path": str(target)}


def command_run_patrol(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.stale_seconds <= 86400:
        raise ContractError("stale_seconds must be between 1 and 86400")
    plan_dir = Path(args.plan_dir).resolve()
    now = datetime.now(timezone.utc)
    stale: list[str] = []
    workers_root = plan_dir / "state" / "worker_runs"
    for status_file in workers_root.glob("*/status.json") if workers_root.exists() else []:
        status = read_json(status_file)
        if status.get("status") != "RUNNING":
            continue
        stamp = parse_utc(status.get("updated_at") or status.get("started_at"))
        if (now - stamp).total_seconds() > args.stale_seconds:
            fingerprint = f"worker:{status.get('run_id', status_file.parent.name)}:{status.get('started_at', '')}"
            command_record_failure(argparse.Namespace(
                plan_dir=str(plan_dir), failure_class="runtime_stall",
                fingerprint=fingerprint, source="run-patrol",
            ))
            stale.append(status_file.parent.name)
    report = {"schema_version": 1, "ts": utc_now(), "stale_workers": stale}
    atomic_write_json(plan_dir / "state" / "patrol_report.json", report)
    return {"ok": True, **report}


def durable_root(plan_dir: Path) -> Path:
    return plan_dir / "state" / "durable_loop"


@contextmanager
def durable_loop_lock(plan_dir: Path) -> Iterator[None]:
    lock_path = durable_root(plan_dir) / ".controller.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def durable_artifact(
    plan_dir: Path,
    raw: Any,
    name: str,
    *,
    require_purpose: bool = False,
) -> dict[str, str]:
    expected_fields = {"path", "sha256", "purpose"} if require_purpose else {"path", "sha256"}
    if not isinstance(raw, dict) or set(raw) != expected_fields:
        suffix = ", sha256, and purpose" if require_purpose else " and sha256"
        raise ContractError(f"{name} must contain exactly path{suffix}")
    if not isinstance(raw.get("path"), str) or not isinstance(raw.get("sha256"), str):
        raise ContractError(f"{name} path and sha256 must be strings")
    unresolved = Path(raw["path"])
    if not unresolved.is_absolute():
        unresolved = plan_dir / unresolved
    if unresolved.is_symlink():
        raise ContractError(f"{name} must not be a symlink")
    path = normalize_owned_path(plan_dir, str(unresolved))
    if not path.is_file():
        raise ContractError(f"{name} does not exist: {path}")
    digest = sha256_file(path)
    if digest != raw["sha256"]:
        raise ContractError(f"{name} hash mismatch")
    result = {"path": str(path), "sha256": digest}
    if require_purpose:
        purpose = raw.get("purpose")
        if not isinstance(purpose, str) or not purpose:
            raise ContractError(f"{name} purpose must be a non-empty string")
        result["purpose"] = purpose
    return result


def validate_durable_graph(plan_dir: Path, raw: dict[str, Any]) -> dict[str, Any]:
    validate_schema(raw, read_json(DURABLE_PLAN_SCHEMA))
    if raw.get("plan_id") != plan_identity(plan_dir):
        raise ContractError("durable plan graph belongs to another plan")
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": raw["plan_id"],
        "target_tier": raw["target_tier"],
        "execution_mode": raw["execution_mode"],
        "objective": durable_artifact(plan_dir, raw["objective"], "objective"),
        "constraints": durable_artifact(plan_dir, raw["constraints"], "constraints"),
        "evaluator": durable_artifact(plan_dir, raw["evaluator"], "evaluator"),
        "tasks": [],
    }
    task_ids: list[str] = []
    for index, task in enumerate(raw.get("tasks", [])):
        if not isinstance(task, dict) or set(task) != {
            "task_id", "phase", "depends_on", "task_contract", "inputs",
        }:
            raise ContractError(f"tasks[{index}] has an invalid closed shape")
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not DURABLE_TASK_ID_RE.fullmatch(task_id):
            raise ContractError(f"tasks[{index}].task_id is invalid")
        if task_id in task_ids:
            raise ContractError("durable task IDs must be unique")
        task_ids.append(task_id)
        phase = task.get("phase")
        dependencies = task.get("depends_on")
        inputs = task.get("inputs")
        if not isinstance(phase, str) or not phase:
            raise ContractError(f"tasks[{index}].phase must be non-empty")
        if (
            not isinstance(dependencies, list)
            or any(not isinstance(item, str) for item in dependencies)
            or len(dependencies) != len(set(dependencies))
        ):
            raise ContractError(f"tasks[{index}].depends_on must contain unique strings")
        if not isinstance(inputs, list):
            raise ContractError(f"tasks[{index}].inputs must be an array")
        normalized["tasks"].append({
            "task_id": task_id,
            "phase": phase,
            "depends_on": dependencies,
            "task_contract": durable_artifact(
                plan_dir, task["task_contract"], f"tasks[{index}].task_contract",
            ),
            "inputs": [
                durable_artifact(
                    plan_dir, item, f"tasks[{index}].inputs[{input_index}]",
                    require_purpose=True,
                )
                for input_index, item in enumerate(inputs)
            ],
        })
    known = set(task_ids)
    for task in normalized["tasks"]:
        if task["task_id"] in task["depends_on"] or any(
            dependency not in known for dependency in task["depends_on"]
        ):
            raise ContractError("durable task dependency is missing or self-referential")
    visited: set[str] = set()
    visiting: set[str] = set()
    by_id = {item["task_id"]: item for item in normalized["tasks"]}

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ContractError("durable task graph contains a dependency cycle")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in by_id[task_id]["depends_on"]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in task_ids:
        visit(task_id)
    return normalized


def durable_graph_path(plan_dir: Path) -> Path:
    return durable_root(plan_dir) / "canonical" / "graph.json"


def durable_revision_path(plan_dir: Path, revision: int) -> Path:
    return durable_root(plan_dir) / "canonical" / "revisions" / f"{revision:08d}.json"


def read_durable_state(plan_dir: Path) -> dict[str, Any]:
    head = read_json(durable_root(plan_dir) / "canonical" / "head.json")
    revision = require_non_negative_int(head.get("state_revision"), "state_revision")
    path = durable_revision_path(plan_dir, revision)
    state = read_json(path)
    if state.get("state_revision") != revision:
        raise ContractError("durable head revision mismatch")
    if head.get("state_sha256") != sha256_file(path):
        raise ContractError("durable canonical state hash mismatch")
    if state.get("plan_id") != plan_identity(plan_dir):
        raise ContractError("durable canonical state belongs to another plan")
    return state


def last_durable_event(plan_dir: Path) -> dict[str, Any]:
    path = durable_root(plan_dir) / "events.jsonl"
    if not path.exists():
        raise ContractError("durable event log is absent")
    events = [strict_json_loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not events:
        raise ContractError("durable event log is empty")
    prior: str | None = None
    for event in events:
        body = {key: value for key, value in event.items() if key != "event_id"}
        if event.get("event_id") != f"event_{sha256_json(body)}":
            raise ContractError("durable event identity mismatch")
        if event.get("previous_event_id") != prior:
            raise ContractError("durable event chain is broken")
        prior = event["event_id"]
    return events[-1]


def append_durable_event(plan_dir: Path, value: dict[str, Any]) -> dict[str, Any]:
    path = durable_root(plan_dir) / "events.jsonl"
    previous = last_durable_event(plan_dir)["event_id"] if path.exists() else None
    body = {**value, "previous_event_id": previous}
    event = {**body, "event_id": f"event_{sha256_json(body)}"}
    append_jsonl_once(path, "event_id", event["event_id"], event)
    return event


def eligible_durable_task(graph: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    for task in graph["tasks"]:
        if state["task_states"][task["task_id"]] != "PENDING":
            continue
        if all(state["task_states"][dependency] == "COMPLETED" for dependency in task["depends_on"]):
            return task
    return None


def durable_projection(
    graph: dict[str, Any], state: dict[str, Any], event_id: str,
) -> dict[str, Any]:
    active_id = state.get("active_task_id")
    active = next((item for item in graph["tasks"] if item["task_id"] == active_id), None)
    eligible = eligible_durable_task(graph, state)
    complete = all(value == "COMPLETED" for value in state["task_states"].values())
    if complete:
        phase = "complete"
        next_action = {"kind": "complete", "task_id": None, "from_state_revision": state["state_revision"]}
    elif active is not None:
        phase = active["phase"]
        next_action = {
            "kind": "dispatch_task",
            "task_id": active["task_id"],
            "from_state_revision": state["state_revision"],
        }
    elif eligible is not None:
        phase = eligible["phase"]
        next_action = {
            "kind": "dispatch_task",
            "task_id": eligible["task_id"],
            "from_state_revision": state["state_revision"],
        }
    else:
        phase = "blocked"
        next_action = {
            "kind": "await_human",
            "task_id": None,
            "from_state_revision": state["state_revision"],
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_id": state["plan_id"],
        "state_revision": state["state_revision"],
        "objective": {
            "text_sha256": graph["objective"]["sha256"],
            "constraints_sha256": graph["constraints"]["sha256"],
        },
        "phase": phase,
        "evidence_refs": state["evidence_refs"],
        "blocker_refs": state["blocker_refs"],
        "approval_refs": state["approval_refs"],
        "next_action": next_action,
        "rebuilt_through_event_id": event_id,
    }


def write_durable_projection(plan_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    graph_path = durable_graph_path(plan_dir)
    graph = read_json(graph_path)
    if sha256_file(graph_path) != state.get("graph_sha256"):
        raise ContractError("durable graph hash mismatch")
    event = last_durable_event(plan_dir)
    if event.get("state_revision") != state["state_revision"]:
        raise ContractError("durable event/state revision mismatch")
    head = read_json(durable_root(plan_dir) / "canonical" / "head.json")
    if head.get("event_id") != event.get("event_id"):
        raise ContractError("durable head/event identity mismatch")
    projection = durable_projection(graph, state, event["event_id"])
    atomic_write_json(durable_root(plan_dir) / "projection.json", projection)
    return projection


def commit_durable_revision(
    plan_dir: Path,
    state: dict[str, Any],
    *,
    event_kind: str,
    event_details: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    revision = require_non_negative_int(state.get("state_revision"), "state_revision")
    target = durable_revision_path(plan_dir, revision)
    if target.exists():
        if read_json(target) != state:
            raise ContractError("durable state revision identity collision")
    else:
        atomic_write_json(target, state, immutable=True)
    event = append_durable_event(plan_dir, {
        "schema_version": SCHEMA_VERSION,
        "plan_id": state["plan_id"],
        "state_revision": revision,
        "kind": event_kind,
        "details": event_details,
        "recorded_at": state["updated_at"],
    })
    atomic_write_json(durable_root(plan_dir) / "canonical" / "head.json", {
        "schema_version": SCHEMA_VERSION,
        "plan_id": state["plan_id"],
        "state_revision": revision,
        "state_path": str(target),
        "state_sha256": sha256_file(target),
        "event_id": event["event_id"],
        "updated_at": state["updated_at"],
    })
    return state, write_durable_projection(plan_dir, state)


def command_init_durable_plan(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    load_policy(plan_dir)
    approval = check_transition_receipt(plan_dir, plan_identity(plan_dir), "approve_execution")
    graph_source = Path(args.graph).resolve()
    graph = validate_durable_graph(plan_dir, read_json(graph_source))
    root = durable_root(plan_dir)
    target = durable_graph_path(plan_dir)
    with durable_loop_lock(plan_dir):
        if target.exists():
            current = read_json(target)
            if current == graph:
                head_path = durable_root(plan_dir) / "canonical" / "head.json"
                if head_path.exists():
                    state = read_durable_state(plan_dir)
                else:
                    state = read_json(durable_revision_path(plan_dir, 0))
                    commit_durable_revision(
                        plan_dir, state, event_kind="plan_initialized",
                        event_details={
                            "graph_sha256": state["graph_sha256"],
                            "approval_request_id": approval["request_id"],
                        },
                    )
                return {
                    "ok": True,
                    "idempotent": True,
                    "state_revision": state["state_revision"],
                    "projection": write_durable_projection(plan_dir, state),
                }
            raise ContractError("durable plan is already initialized with another graph")
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(target, graph, immutable=True)
        now = utc_now()
        approval_path = transition_receipt_path(
            plan_dir, "approve_execution", approval["request_id"],
        )
        state = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": graph["plan_id"],
            "state_revision": 0,
            "graph_sha256": sha256_file(target),
            "target_tier": graph["target_tier"],
            "execution_mode": graph["execution_mode"],
            "objective_sha256": graph["objective"]["sha256"],
            "constraints_sha256": graph["constraints"]["sha256"],
            "evaluator_sha256": graph["evaluator"]["sha256"],
            "task_states": {item["task_id"]: "PENDING" for item in graph["tasks"]},
            "active_task_id": None,
            "active_capsule_id": None,
            "evidence_refs": [],
            "blocker_refs": [],
            "approval_refs": [f"{approval_path}:{sha256_file(approval_path)}"],
            "prior_direction_refs": [],
            "updated_at": now,
        }
        _, projection = commit_durable_revision(
            plan_dir, state, event_kind="plan_initialized",
            event_details={
                "graph_sha256": state["graph_sha256"],
                "approval_request_id": approval["request_id"],
            },
        )
    return {
        "ok": True,
        "graph_path": str(target),
        "graph_sha256": sha256_file(target),
        "state_revision": 0,
        "projection": projection,
    }


def validate_live_durable_artifacts(
    plan_dir: Path, graph: dict[str, Any], task: dict[str, Any] | None = None,
) -> None:
    for name in ("objective", "constraints", "evaluator"):
        durable_artifact(plan_dir, graph[name], name)
    if task is not None:
        durable_artifact(plan_dir, task["task_contract"], "task_contract")
        for index, item in enumerate(task["inputs"]):
            durable_artifact(plan_dir, item, f"task input {index}", require_purpose=True)


def evaluator_admission_root(plan_dir: Path) -> Path:
    return plan_dir / "state" / "evaluator_admission"


def admission_material_paths(args: argparse.Namespace) -> dict[str, str | None]:
    return {
        "evaluator": str(Path(args.evaluator).resolve()),
        "authority_identity": str(Path(args.authority_identity).resolve()),
        "input_manifest": str(Path(args.input_manifest).resolve()),
        "validation_identity": str(Path(args.validation_identity).resolve()),
        "replay_identity": str(Path(args.replay_identity).resolve()),
        "regression_suite": str(Path(args.regression_suite).resolve()),
        "allowed_search_space": str(Path(args.allowed_search_space).resolve()),
        "complexity_identity": (
            str(Path(args.complexity_identity).resolve())
            if args.complexity_identity else None
        ),
    }


def validate_admission_materials(
    plan_dir: Path,
    contract: dict[str, Any],
    paths: dict[str, str | None],
) -> dict[str, Any]:
    validate_schema(contract, read_json(EVALUATOR_ADMISSION_SCHEMA))
    if contract.get("plan_id") != plan_identity(plan_dir):
        raise ContractError("evaluator admission belongs to another plan")
    expected_validation = {
        "hard_metric": "metric",
        "test_suite": "test_suite",
        "held_out": "held_out_split",
        "human_review": "human_record",
    }[contract["evaluator_class"]]
    if contract["validation_identity"]["kind"] != expected_validation:
        raise ContractError("evaluator class and validation identity are incompatible")
    if (
        contract["evaluator_class"] == "human_review"
        and contract["autonomy_tiers"]
    ):
        raise ContractError("human review cannot admit unattended autonomy")
    evaluator = Path(str(paths["evaluator"]))
    authority = Path(str(paths["authority_identity"]))
    input_manifest_path = Path(str(paths["input_manifest"]))
    validation = Path(str(paths["validation_identity"]))
    replay_path = Path(str(paths["replay_identity"]))
    regression_path = Path(str(paths["regression_suite"]))
    search_space = Path(str(paths["allowed_search_space"]))
    worker_owned_roots = (
        (plan_dir / "artifacts" / "intermediate").resolve(),
        (plan_dir / "state" / "worker_runs").resolve(),
    )
    for name, path, expected in (
        ("evaluator", evaluator, contract["evaluator_sha256"]),
        ("authority identity", authority, contract["authority"]["identity_sha256"]),
        ("input manifest", input_manifest_path, contract["input_manifest_sha256"]),
        ("validation identity", validation, contract["validation_identity"]["sha256"]),
        ("replay identity", replay_path, contract["replay_identity_sha256"]),
        ("regression suite", regression_path, contract["regression_suite_sha256"]),
        ("allowed search space", search_space, contract["allowed_search_space_sha256"]),
    ):
        unresolved = path
        if unresolved.is_symlink() or not unresolved.is_file():
            raise ContractError(f"{name} must be an existing regular non-symlink file")
        resolved = normalize_owned_path(plan_dir, str(unresolved))
        if any(
            resolved == worker_root or worker_root in resolved.parents
            for worker_root in worker_owned_roots
        ):
            raise ContractError(f"{name} is inside a worker-owned namespace")
        if sha256_file(unresolved) != expected:
            raise ContractError(f"{name} hash mismatch")
    authority_kind = contract["authority"]["kind"]
    if authority_kind == "controller_owned":
        canonical = (plan_dir / "state" / "evaluator_contract.json").resolve()
        if authority.resolve() != canonical:
            raise ContractError("controller-owned admission requires the canonical evaluator contract")
        frozen = read_json(canonical)
        if (
            frozen.get("evaluator_sha256") != contract["evaluator_sha256"]
            or Path(frozen.get("evaluator_path", "")).resolve() != evaluator.resolve()
        ):
            raise ContractError("controller-owned evaluator identity mismatch")
    elif authority_kind == "external_readonly":
        if authority.resolve() == evaluator.resolve():
            raise ContractError("external evaluator authority identity must be independent")
        if authority.stat().st_mode & 0o222 or evaluator.stat().st_mode & 0o222:
            raise ContractError("external evaluator authority must be filesystem read-only")
    elif contract["autonomy_tiers"]:
        raise ContractError("human-signed authority is not executable unattended admission")
    manifest = read_json(input_manifest_path)
    if set(manifest) != {"schema_version", "artifacts"} or manifest.get("schema_version") != 1:
        raise ContractError("admission input manifest has an invalid closed shape")
    inputs = verify_manifest_items(manifest.get("artifacts"), base_dir=plan_dir)
    replay = read_json(replay_path)
    if set(replay) != {
        "schema_version", "evaluator_sha256", "input_manifest_sha256",
        "first_verdict_sha256", "second_verdict_sha256", "status",
    }:
        raise ContractError("evaluator replay receipt has an invalid closed shape")
    if (
        replay.get("schema_version") != 1
        or replay.get("evaluator_sha256") != contract["evaluator_sha256"]
        or replay.get("input_manifest_sha256") != contract["input_manifest_sha256"]
        or replay.get("first_verdict_sha256") != replay.get("second_verdict_sha256")
        or replay.get("status") != "PASS"
    ):
        raise ContractError("evaluator replay evidence did not reproduce an identical verdict")
    regression = read_json(regression_path)
    if set(regression) != {
        "schema_version", "evaluator_sha256", "status", "failed_tests", "total_tests",
    }:
        raise ContractError("evaluator regression receipt has an invalid closed shape")
    if (
        regression.get("schema_version") != 1
        or regression.get("evaluator_sha256") != contract["evaluator_sha256"]
        or regression.get("status") != "PASS"
        or regression.get("failed_tests") != 0
        or isinstance(regression.get("total_tests"), bool)
        or not isinstance(regression.get("total_tests"), int)
        or regression["total_tests"] < 1
    ):
        raise ContractError("evaluator regression suite did not pass")
    complexity = contract["complexity_policy"]
    complexity_path = paths.get("complexity_identity")
    if complexity["kind"] == "not_applicable":
        if complexity["identity_sha256"] is not None or complexity_path is not None:
            raise ContractError("not_applicable complexity policy cannot carry an identity")
        if not isinstance(complexity.get("rationale"), str) or not complexity["rationale"].strip():
            raise ContractError("not_applicable complexity policy requires a rationale")
    else:
        if not complexity_path or not isinstance(complexity["identity_sha256"], str):
            raise ContractError("complexity penalty/budget requires an identity artifact")
        path = Path(complexity_path)
        if path.is_symlink() or not path.is_file():
            raise ContractError("complexity identity must be a regular non-symlink file")
        normalize_owned_path(plan_dir, str(path))
        if sha256_file(path) != complexity["identity_sha256"]:
            raise ContractError("complexity identity hash mismatch")
    return {
        "evaluator": {"path": str(evaluator), "sha256": sha256_file(evaluator)},
        "authority_identity": {"path": str(authority), "sha256": sha256_file(authority)},
        "input_manifest": {"path": str(input_manifest_path), "sha256": sha256_file(input_manifest_path)},
        "validation_identity": {"path": str(validation), "sha256": sha256_file(validation)},
        "replay_identity": {"path": str(replay_path), "sha256": sha256_file(replay_path)},
        "regression_suite": {"path": str(regression_path), "sha256": sha256_file(regression_path)},
        "allowed_search_space": {"path": str(search_space), "sha256": sha256_file(search_space)},
        "complexity_identity": (
            {"path": str(complexity_path), "sha256": sha256_file(Path(complexity_path))}
            if complexity_path else None
        ),
        "verified_inputs": inputs,
    }


def command_admit_evaluator(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    source = read_json(Path(args.contract).resolve())
    source["admitted_by"] = "controller"
    source["admitted_at"] = utc_now()
    paths = admission_material_paths(args)
    materials = validate_admission_materials(plan_dir, source, paths)
    identity_body = {key: value for key, value in source.items() if key != "admitted_at"}
    canonical_contract_hash = sha256_json(identity_body)
    admission_id = f"admission_{canonical_contract_hash}"
    root = evaluator_admission_root(plan_dir)
    contract_path = root / "contracts" / f"{admission_id}.json"
    receipt_path = root / "receipts" / f"{admission_id}.json"
    with durable_loop_lock(plan_dir):
        if contract_path.exists():
            stored = read_json(contract_path)
            stored_identity = {key: value for key, value in stored.items() if key != "admitted_at"}
            if stored_identity != identity_body:
                raise ContractError("evaluator admission identity collision")
            source = stored
        else:
            atomic_write_json(contract_path, source, immutable=True)
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": source["plan_id"],
            "admission_id": admission_id,
            "contract_path": str(contract_path),
            "contract_sha256": sha256_file(contract_path),
            "contract_canonical_sha256": sha256_json(source),
            "materials": materials,
            "autonomy_tiers": source["autonomy_tiers"],
            "admitted_at": source["admitted_at"],
            "status": "ADMITTED",
        }
        if receipt_path.exists():
            prior = read_json(receipt_path)
            return {"ok": True, "idempotent": True, "receipt_path": str(receipt_path), **prior}
        atomic_write_json(receipt_path, receipt, immutable=True)
        atomic_write_json(root / "current.json", {
            "schema_version": SCHEMA_VERSION,
            "plan_id": source["plan_id"],
            "admission_id": admission_id,
            "receipt_path": str(receipt_path),
            "receipt_sha256": sha256_file(receipt_path),
            "status": "ADMITTED",
            "updated_at": source["admitted_at"],
        })
        append_jsonl(root / "audit.jsonl", {
            "schema_version": SCHEMA_VERSION,
            "event": "evaluator_admitted",
            "admission_id": admission_id,
            "receipt_sha256": sha256_file(receipt_path),
            "recorded_at": source["admitted_at"],
        })
    return {"ok": True, "receipt_path": str(receipt_path), **receipt}


def validate_current_evaluator_admission(
    plan_dir: Path, graph: dict[str, Any], autonomy_tier: str,
) -> dict[str, Any]:
    root = evaluator_admission_root(plan_dir)
    try:
        current = read_json(root / "current.json")
        receipt_path = Path(current["receipt_path"])
        receipt = read_json(receipt_path)
        if (
            current.get("status") != "ADMITTED"
            or receipt.get("status") != "ADMITTED"
            or current.get("receipt_sha256") != sha256_file(receipt_path)
            or receipt.get("admission_id") != current.get("admission_id")
        ):
            raise ContractError("evaluator admission receipt correlation mismatch")
        contract_path = Path(receipt["contract_path"])
        contract = read_json(contract_path)
        if (
            receipt.get("contract_sha256") != sha256_file(contract_path)
            or receipt.get("contract_canonical_sha256") != sha256_json(contract)
            or autonomy_tier not in contract.get("autonomy_tiers", [])
            or contract.get("evaluator_sha256") != graph["evaluator"]["sha256"]
        ):
            raise ContractError("evaluator admission does not authorize this durable plan")
        paths = {
            role: value["path"] if value else None
            for role, value in receipt["materials"].items()
            if role != "verified_inputs"
        }
        validate_admission_materials(plan_dir, contract, paths)
        return receipt
    except (ContractError, KeyError, TypeError) as exc:
        reason = str(exc)
        fingerprint = hashlib.sha256(reason.encode()).hexdigest()
        append_jsonl_once(root / "audit.jsonl", "fingerprint", fingerprint, {
            "schema_version": SCHEMA_VERSION,
            "event": "evaluator_admission_invalidated",
            "fingerprint": fingerprint,
            "reason": reason,
            "recorded_at": utc_now(),
        })
        raise ContractError(f"unattended autonomy is blocked: {reason}") from None


def require_durable_autonomy_eligibility(plan_dir: Path) -> dict[str, Any] | None:
    graph = read_json(durable_graph_path(plan_dir))
    if graph.get("execution_mode") != "unattended":
        return None
    tier = graph.get("target_tier")
    autonomy_tier = {
        "conference": "conference_unattended",
        "journal-q1": "journal_q1_unattended",
    }.get(tier)
    if autonomy_tier is None:
        return None
    return validate_current_evaluator_admission(plan_dir, graph, autonomy_tier)


def command_check_autonomy_eligibility(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    receipt = require_durable_autonomy_eligibility(plan_dir)
    return {
        "ok": True,
        "eligible": True,
        "admission_id": receipt.get("admission_id") if receipt else None,
    }


def context_capsule_path(plan_dir: Path, capsule_id: str) -> Path:
    if not re.fullmatch(r"capsule_[a-f0-9]{64}", capsule_id):
        raise ContractError("invalid context capsule identity")
    return durable_root(plan_dir) / "capsules" / f"{capsule_id}.json"


def make_context_capsule(
    plan_dir: Path,
    graph: dict[str, Any],
    state: dict[str, Any],
    task: dict[str, Any],
) -> dict[str, Any]:
    manifest = task["inputs"]
    identity = {
        "plan_id": state["plan_id"],
        "task_id": task["task_id"],
        "state_revision": state["state_revision"] + 1,
        "graph_sha256": state["graph_sha256"],
        "task_contract_sha256": task["task_contract"]["sha256"],
        "input_manifest_sha256": sha256_json(manifest),
    }
    capsule_id = f"capsule_{sha256_json(identity)}"
    target = context_capsule_path(plan_dir, capsule_id)
    if target.exists():
        capsule = read_json(target)
        body = {key: value for key, value in capsule.items() if key != "capsule_sha256"}
        if capsule.get("capsule_sha256") != sha256_json(body):
            raise ContractError("stored context capsule hash mismatch")
        return capsule
    body = {
        "schema_version": SCHEMA_VERSION,
        "capsule_id": capsule_id,
        "plan_id": state["plan_id"],
        "task_id": task["task_id"],
        "state_revision": state["state_revision"] + 1,
        "objective_sha256": graph["objective"]["sha256"],
        "constraints_sha256": graph["constraints"]["sha256"],
        "evaluator_sha256": graph["evaluator"]["sha256"],
        "task_contract": task["task_contract"],
        "input_manifest": manifest,
        "input_manifest_sha256": sha256_json(manifest),
        "prior_direction_refs": state["prior_direction_refs"],
        "evidence_refs": state["evidence_refs"],
        "created_at": utc_now(),
    }
    capsule = {**body, "capsule_sha256": sha256_json(body)}
    validate_schema(capsule, read_json(CONTEXT_CAPSULE_SCHEMA))
    atomic_write_json(target, capsule, immutable=True)
    return capsule


def command_advance_durable_plan(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    require_controller_not_stopped(plan_dir)
    try:
        require_durable_autonomy_eligibility(plan_dir)
    except ContractError:
        record_detected_research_integrity(plan_dir)
        raise
    with durable_loop_lock(plan_dir):
        graph = read_json(durable_graph_path(plan_dir))
        state = read_durable_state(plan_dir)
        if state.get("active_task_id"):
            capsule = read_json(context_capsule_path(plan_dir, state["active_capsule_id"]))
            return {
                "ok": True,
                "idempotent": True,
                "capsule_path": str(context_capsule_path(plan_dir, capsule["capsule_id"])),
                "capsule": capsule,
                "projection": write_durable_projection(plan_dir, state),
            }
        task = eligible_durable_task(graph, state)
        if task is None:
            projection = write_durable_projection(plan_dir, state)
            return {"ok": True, "complete": projection["next_action"]["kind"] == "complete", "projection": projection}
        try:
            validate_live_durable_artifacts(plan_dir, graph, task)
        except ContractError:
            record_detected_research_integrity(plan_dir)
            raise
        capsule = make_context_capsule(plan_dir, graph, state, task)
        next_state = {
            **state,
            "state_revision": state["state_revision"] + 1,
            "task_states": {**state["task_states"], task["task_id"]: "READY"},
            "active_task_id": task["task_id"],
            "active_capsule_id": capsule["capsule_id"],
            "updated_at": capsule["created_at"],
        }
        _, projection = commit_durable_revision(
            plan_dir, next_state, event_kind="context_capsule_prepared",
            event_details={
                "task_id": task["task_id"],
                "capsule_id": capsule["capsule_id"],
                "capsule_sha256": capsule["capsule_sha256"],
            },
        )
    return {
        "ok": True,
        "capsule_path": str(context_capsule_path(plan_dir, capsule["capsule_id"])),
        "capsule": capsule,
        "projection": projection,
    }


def validate_context_capsule(
    plan_dir: Path, capsule_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    expected_root = (durable_root(plan_dir) / "capsules").resolve()
    try:
        capsule_path.resolve().relative_to(expected_root)
    except ValueError as exc:
        raise ContractError("context capsule is outside canonical durable state") from exc
    capsule = read_json(capsule_path)
    validate_schema(capsule, read_json(CONTEXT_CAPSULE_SCHEMA))
    if capsule_path.resolve() != context_capsule_path(plan_dir, capsule["capsule_id"]).resolve():
        raise ContractError("context capsule path/identity mismatch")
    body = {key: value for key, value in capsule.items() if key != "capsule_sha256"}
    if capsule["capsule_sha256"] != sha256_json(body):
        raise ContractError("context capsule hash mismatch")
    graph = read_json(durable_graph_path(plan_dir))
    state = read_durable_state(plan_dir)
    if capsule["plan_id"] != state["plan_id"] or capsule["state_revision"] != state["state_revision"]:
        raise ContractError("context capsule state revision drift")
    if state.get("active_capsule_id") != capsule["capsule_id"] or state.get("active_task_id") != capsule["task_id"]:
        raise ContractError("context capsule is not the current claimed work unit")
    task = next((item for item in graph["tasks"] if item["task_id"] == capsule["task_id"]), None)
    if task is None or state["task_states"].get(capsule["task_id"]) != "READY":
        raise ContractError("context capsule task is not ready")
    validate_live_durable_artifacts(plan_dir, graph, task)
    checks = {
        "objective_sha256": graph["objective"]["sha256"],
        "constraints_sha256": graph["constraints"]["sha256"],
        "evaluator_sha256": graph["evaluator"]["sha256"],
        "input_manifest_sha256": sha256_json(task["inputs"]),
    }
    if any(capsule.get(field) != expected for field, expected in checks.items()):
        raise ContractError("context capsule goal, evaluator, or input drift")
    if capsule.get("task_contract") != task["task_contract"] or capsule.get("input_manifest") != task["inputs"]:
        raise ContractError("context capsule task contract drift")
    return capsule, graph, state, task


def command_apply_work_unit_result(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    try:
        require_durable_autonomy_eligibility(plan_dir)
    except ContractError:
        record_detected_research_integrity(plan_dir)
        raise
    with durable_loop_lock(plan_dir):
        try:
            capsule, graph, state, task = validate_context_capsule(
                plan_dir, Path(args.capsule).resolve(),
            )
        except ContractError:
            record_detected_research_integrity(plan_dir)
            raise
        unresolved_result = Path(args.result)
        if not unresolved_result.is_absolute():
            unresolved_result = plan_dir / unresolved_result
        if unresolved_result.is_symlink():
            raise ContractError("work-unit result must not be a symlink")
        result_path = normalize_owned_path(plan_dir, str(unresolved_result))
        result = read_json(result_path)
        if not isinstance(result, dict) or set(result) != {
            "schema_version", "capsule_id", "task_id", "evidence",
        }:
            raise ContractError("work-unit result has an invalid closed shape")
        if (
            result.get("schema_version") != SCHEMA_VERSION
            or result.get("capsule_id") != capsule["capsule_id"]
            or result.get("task_id") != task["task_id"]
            or not isinstance(result.get("evidence"), list)
        ):
            raise ContractError("work-unit result correlation mismatch")
        evidence_manifest = [
            durable_artifact(plan_dir, item, f"result evidence {index}")
            for index, item in enumerate(result["evidence"])
        ]
        evidence_identity = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": state["plan_id"],
            "task_id": task["task_id"],
            "capsule_id": capsule["capsule_id"],
            "capsule_sha256": capsule["capsule_sha256"],
            "result_path": str(result_path),
            "result_sha256": sha256_file(result_path),
            "evidence_manifest": evidence_manifest,
        }
        evidence_id = f"evidence_{sha256_json(evidence_identity)}"
        evidence_path = durable_root(plan_dir) / "evidence" / f"{evidence_id}.json"
        if evidence_path.exists():
            evidence_record = read_json(evidence_path)
            if any(evidence_record.get(key) != value for key, value in evidence_identity.items()):
                raise ContractError("durable evidence identity collision")
        else:
            evidence_record = {
                **evidence_identity,
                "recorded_at": utc_now(),
                "evidence_id": evidence_id,
            }
            atomic_write_json(evidence_path, evidence_record, immutable=True)
        next_state = {
            **state,
            "state_revision": state["state_revision"] + 1,
            "task_states": {**state["task_states"], task["task_id"]: "COMPLETED"},
            "active_task_id": None,
            "active_capsule_id": None,
            "evidence_refs": [*state["evidence_refs"], evidence_id],
            "updated_at": evidence_record["recorded_at"],
        }
        _, projection = commit_durable_revision(
            plan_dir, next_state, event_kind="work_unit_applied",
            event_details={
                "task_id": task["task_id"],
                "capsule_id": capsule["capsule_id"],
                "evidence_id": evidence_id,
            },
        )
    return {
        "ok": True,
        "evidence_record": str(evidence_path),
        "evidence_id": evidence_id,
        "projection": projection,
    }


def command_rebuild_durable_projection(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    with durable_loop_lock(plan_dir):
        state = read_durable_state(plan_dir)
        event = last_durable_event(plan_dir)
        if event.get("state_revision") != state["state_revision"]:
            raise ContractError("durable event log does not reach canonical head")
        projection = write_durable_projection(plan_dir, state)
    return {"ok": True, "projection": projection}


def durable_schedule_root(plan_dir: Path, schedule_id: str) -> Path:
    if not DURABLE_SCHEDULE_ID_RE.fullmatch(schedule_id):
        raise ContractError("invalid durable schedule_id")
    return durable_root(plan_dir) / "schedules" / schedule_id


def scheduler_service_target(label: str) -> str:
    return f"gui/{os.getuid()}/{label}"


def scheduler_is_loaded(binary: str, label: str) -> bool:
    proc = subprocess.run(
        [binary, "print", scheduler_service_target(label)],
        capture_output=True, text=True,
    )
    return proc.returncode == 0


def command_register_durable_trigger(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    load_policy(plan_dir)
    approval = check_transition_receipt(plan_dir, plan_identity(plan_dir), "approve_execution")
    require_durable_autonomy_eligibility(plan_dir)
    if not 60 <= args.interval_seconds <= 86400:
        raise ContractError("interval_seconds must be between 60 and 86400")
    if not 0 <= args.jitter_seconds < args.interval_seconds:
        raise ContractError("jitter_seconds must be non-negative and below interval_seconds")
    for name in ("session_budget_seconds", "human_escalation_after_seconds", "lease_seconds"):
        value = getattr(args, name)
        if not 1 <= value <= 86400:
            raise ContractError(f"{name} must be between 1 and 86400")
    schedule_root = durable_schedule_root(plan_dir, args.schedule_id)
    current_path = schedule_root / "current.json"
    with durable_loop_lock(plan_dir):
        current = read_json(current_path) if current_path.exists() else None
        if current and current.get("active") is True and not args.first_due_at:
            prior_contract = read_json(Path(current["schedule_contract_path"]))
            first_due = parse_utc(prior_contract["next_due_at"])
        else:
            first_due = parse_utc(args.first_due_at) if args.first_due_at else datetime.now(timezone.utc)
        generation = int(current.get("registration_generation", 0)) + 1 if current else 1
        runtime_script = Path(__file__).resolve()
        program = [
            sys.executable, str(runtime_script), "run-durable-tick",
            "--plan-dir", str(plan_dir), "--schedule-id", args.schedule_id,
        ]
        contract = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": plan_identity(plan_dir),
            "schedule_id": args.schedule_id,
            "interval_seconds": args.interval_seconds,
            "jitter_seconds": args.jitter_seconds,
            "session_budget_seconds": args.session_budget_seconds,
            "human_escalation_after_seconds": args.human_escalation_after_seconds,
            "lease_seconds": args.lease_seconds,
            "next_due_at": first_due.isoformat().replace("+00:00", "Z"),
            "registration_generation": generation,
            "controller_command_sha256": sha256_json(program),
        }
        if current and current.get("active") is True:
            prior = read_json(Path(current["schedule_contract_path"]))
            comparable = {key: value for key, value in contract.items() if key not in {"registration_generation"}}
            prior_comparable = {key: value for key, value in prior.items() if key not in {"registration_generation"}}
            if comparable != prior_comparable:
                raise ContractError("active durable trigger must be unregistered before replacement")
            receipt = read_json(Path(current["registration_receipt_path"]))
            if not scheduler_is_loaded(args.launchctl_bin, receipt["scheduler_label"]):
                proc = subprocess.run(
                    [
                        args.launchctl_bin, "bootstrap", f"gui/{os.getuid()}",
                        receipt["scheduler_plist_path"],
                    ],
                    capture_output=True, text=True,
                )
                if proc.returncode != 0:
                    raise ContractError(
                        f"external scheduler recovery failed: {proc.stderr.strip()}"
                    )
                append_jsonl(schedule_root / "registration-events.jsonl", {
                    "schema_version": SCHEMA_VERSION,
                    "event": "external_registration_recovered",
                    "registration_id": receipt["registration_id"],
                    "registration_generation": receipt["registration_generation"],
                    "recovered_at": utc_now(),
                })
                return {
                    "ok": True,
                    "idempotent": True,
                    "external_registration_recovered": True,
                    **receipt,
                }
            return {"ok": True, "idempotent": True, **receipt}
        generation_root = schedule_root / "generations" / str(generation)
        contract_path = generation_root / "schedule-contract.json"
        if contract_path.exists():
            existing_contract = read_json(contract_path)
            requested = dict(contract)
            if not args.first_due_at:
                requested["next_due_at"] = existing_contract.get("next_due_at")
            if requested != existing_contract:
                raise ContractError("durable trigger schedule contract recovery mismatch")
            contract = existing_contract
        else:
            atomic_write_json(contract_path, contract, immutable=True)
        label = f"com.autoresearch-paper.{hashlib.sha256((contract['plan_id'] + ':' + args.schedule_id).encode()).hexdigest()[:24]}"
        plist_path = generation_root / f"{label}.plist"
        scheduler_stdout_path = generation_root / "scheduler.stdout.log"
        scheduler_stderr_path = generation_root / "scheduler.stderr.log"
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist = {
            "Label": label,
            "ProgramArguments": program,
            "RunAtLoad": True,
            "StartInterval": args.interval_seconds,
            "ProcessType": "Background",
            "StandardOutPath": str(scheduler_stdout_path),
            "StandardErrorPath": str(scheduler_stderr_path),
        }
        plist_bytes = plistlib.dumps(plist, fmt=plistlib.FMT_XML)
        if plist_path.exists():
            if plist_path.read_bytes() != plist_bytes:
                raise ContractError("durable scheduler plist recovery mismatch")
        else:
            atomic_write_bytes(plist_path, plist_bytes, immutable=True)
        journal_path = generation_root / "registration-journal.json"
        journal = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": contract["plan_id"],
            "schedule_id": args.schedule_id,
            "registration_generation": generation,
            "phase": "PREPARED",
            "schedule_contract_path": str(contract_path),
            "schedule_contract_sha256": sha256_file(contract_path),
            "scheduler_label": label,
            "scheduler_plist_path": str(plist_path),
            "scheduler_plist_sha256": sha256_file(plist_path),
            "approval_request_id": approval["request_id"],
            "prepared_at": utc_now(),
        }
        if journal_path.exists():
            prior = read_json(journal_path)
            if any(
                prior.get(field) != journal.get(field)
                for field in (
                    "plan_id", "schedule_id", "registration_generation",
                    "schedule_contract_sha256", "scheduler_label", "scheduler_plist_sha256",
                )
            ):
                raise ContractError("durable trigger registration journal collision")
            journal = prior
        else:
            atomic_write_json(journal_path, journal)
        loaded = scheduler_is_loaded(args.launchctl_bin, label)
        if not loaded:
            proc = subprocess.run(
                [args.launchctl_bin, "bootstrap", f"gui/{os.getuid()}", str(plist_path)],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                raise ContractError(f"external scheduler registration failed: {proc.stderr.strip()}")
        if getattr(args, "simulate_crash_after_bootstrap", False):
            raise ContractError("simulated crash after external scheduler bootstrap")
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": contract["plan_id"],
            "schedule_id": args.schedule_id,
            "registration_id": f"registration_{sha256_json(journal)}",
            "registration_generation": generation,
            "schedule_contract_path": str(contract_path),
            "schedule_contract_sha256": sha256_file(contract_path),
            "scheduler_backend": "launchd",
            "scheduler_label": label,
            "scheduler_plist_path": str(plist_path),
            "scheduler_plist_sha256": sha256_file(plist_path),
            "scheduler_stdout_path": str(scheduler_stdout_path),
            "scheduler_stderr_path": str(scheduler_stderr_path),
            "registered_at": utc_now(),
        }
        receipt_path = generation_root / "registration-receipt.json"
        atomic_write_json(receipt_path, receipt, immutable=True)
        journal.update({
            "phase": "COMMITTED",
            "registration_receipt_path": str(receipt_path),
            "registration_receipt_sha256": sha256_file(receipt_path),
            "committed_at": receipt["registered_at"],
        })
        atomic_write_json(journal_path, journal)
        atomic_write_json(current_path, {
            "schema_version": SCHEMA_VERSION,
            "plan_id": contract["plan_id"],
            "schedule_id": args.schedule_id,
            "registration_generation": generation,
            "active": True,
            "schedule_contract_path": str(contract_path),
            "schedule_contract_sha256": sha256_file(contract_path),
            "registration_receipt_path": str(receipt_path),
            "registration_receipt_sha256": sha256_file(receipt_path),
            "updated_at": receipt["registered_at"],
        })
        atomic_write_json(schedule_root / "runtime.json", {
            "schema_version": SCHEMA_VERSION,
            "schedule_id": args.schedule_id,
            "last_tick_at": None,
            "next_due_at": contract["next_due_at"],
            "updated_at": receipt["registered_at"],
        })
    return {"ok": True, "registration_receipt": str(receipt_path), **receipt}


def command_unregister_durable_trigger(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    authorization = validate_applied_action_receipt(
        plan_dir, Path(args.authorization).resolve(), "stop",
    )
    schedule_root = durable_schedule_root(plan_dir, args.schedule_id)
    current_path = schedule_root / "current.json"
    with durable_loop_lock(plan_dir):
        current = read_json(current_path)
        receipt = read_json(Path(current["registration_receipt_path"]))
        removal_path = (
            schedule_root / "generations" / str(current["registration_generation"])
            / "unregistration-receipt.json"
        )
        if current.get("active") is not True:
            return {"ok": True, "idempotent": True, **read_json(removal_path)}
        if scheduler_is_loaded(args.launchctl_bin, receipt["scheduler_label"]):
            proc = subprocess.run(
                [args.launchctl_bin, "bootout", scheduler_service_target(receipt["scheduler_label"])],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                raise ContractError(f"external scheduler removal failed: {proc.stderr.strip()}")
        removal = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": current["plan_id"],
            "schedule_id": args.schedule_id,
            "registration_id": receipt["registration_id"],
            "registration_generation": current["registration_generation"],
            "scheduler_label": receipt["scheduler_label"],
            "stop_record_id": authorization["record_id"],
            "unregistered_at": utc_now(),
        }
        atomic_write_json(removal_path, removal, immutable=True)
        current.update({
            "active": False,
            "unregistration_receipt_path": str(removal_path),
            "unregistration_receipt_sha256": sha256_file(removal_path),
            "updated_at": removal["unregistered_at"],
        })
        atomic_write_json(current_path, current)
    return {"ok": True, "unregistration_receipt": str(removal_path), **removal}


def frontier_retry_trigger_root(plan_dir: Path) -> Path:
    return frontier_root(plan_dir) / "retry-trigger"


def command_register_frontier_retry_trigger(
    args: argparse.Namespace,
) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    if not staged_is_active(plan_dir):
        raise ContractError("frontier retry trigger requires staged research")
    if not 60 <= args.interval_seconds <= 3600:
        raise ContractError("frontier retry interval must be between 60 and 3600")
    if not 1 <= args.timeout <= 86400:
        raise ContractError("frontier retry timeout must be between 1 and 86400")
    resolved_launchctl = resolve_executable(args.launchctl_bin, label="launchctl")
    resolved_codex = resolve_executable(args.codex_bin, label="Codex")
    root = frontier_retry_trigger_root(plan_dir)
    current_path = root / "current.json"
    program = [
        sys.executable, str(Path(__file__).resolve()),
        "recover-due-frontier-retry", "--plan-dir", str(plan_dir),
        "--codex-bin", resolved_codex, "--timeout", str(args.timeout),
    ]
    label = "com.autoresearch-paper.frontier-retry." + hashlib.sha256(
        plan_identity(plan_dir).encode()
    ).hexdigest()[:24]
    if current_path.is_file() and read_json(current_path).get("active") is True:
        current = read_json(current_path)
        receipt = read_json(Path(current["registration_receipt_path"]))
        if (
            receipt.get("interval_seconds") != args.interval_seconds
            or receipt.get("controller_command_sha256") != sha256_json(program)
            or receipt.get("scheduler_label") != label
        ):
            raise ContractError(
                "active frontier retry trigger must be unregistered before replacement"
            )
        recovered = False
        if not scheduler_is_loaded(resolved_launchctl, label):
            proc = subprocess.run([
                resolved_launchctl, "bootstrap", f"gui/{os.getuid()}",
                receipt["scheduler_plist_path"],
            ], capture_output=True, text=True)
            if proc.returncode != 0:
                raise ContractError("frontier retry trigger recovery failed")
            recovered = True
        return {
            "ok": True, "idempotent": True,
            "external_registration_recovered": recovered, **receipt,
        }
    generation = int(read_json(current_path).get("generation", 0)) + 1 \
        if current_path.is_file() else 1
    generation_root = root / "generations" / str(generation)
    plist_path = generation_root / f"{label}.plist"
    scheduler_stdout_path = generation_root / "scheduler.stdout.log"
    scheduler_stderr_path = generation_root / "scheduler.stderr.log"
    plist_bytes = plistlib.dumps({
        "Label": label,
        "ProgramArguments": program,
        "RunAtLoad": True,
        "StartInterval": args.interval_seconds,
        "ProcessType": "Background",
        "StandardOutPath": str(scheduler_stdout_path),
        "StandardErrorPath": str(scheduler_stderr_path),
    }, fmt=plistlib.FMT_XML)
    if plist_path.is_file() and plist_path.read_bytes() != plist_bytes:
        raise ContractError("frontier retry trigger plist recovery mismatch")
    if not plist_path.is_file():
        atomic_write_bytes(plist_path, plist_bytes, immutable=True)
    if not scheduler_is_loaded(resolved_launchctl, label):
        proc = subprocess.run([
            resolved_launchctl, "bootstrap", f"gui/{os.getuid()}", str(plist_path),
        ], capture_output=True, text=True)
        if proc.returncode != 0:
            raise ContractError(
                f"frontier retry trigger registration failed: {proc.stderr.strip()}"
            )
    registered_at = utc_now()
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "generation": generation,
        "scope": "due_provider_quota_frontier_retry_only",
        "worker_dispatch_authority": False,
        "research_transition_authority": False,
        "interval_seconds": args.interval_seconds,
        "launchctl_bin": resolved_launchctl,
        "codex_bin": resolved_codex,
        "scheduler_label": label,
        "scheduler_plist_path": str(plist_path),
        "scheduler_plist_sha256": sha256_file(plist_path),
        "scheduler_stdout_path": str(scheduler_stdout_path),
        "scheduler_stderr_path": str(scheduler_stderr_path),
        "controller_command_sha256": sha256_json(program),
        "registered_at": registered_at,
    }
    receipt_path = generation_root / "registration-receipt.json"
    atomic_write_json(receipt_path, receipt, immutable=True)
    atomic_write_json(current_path, {
        "schema_version": SCHEMA_VERSION,
        "plan_id": receipt["plan_id"],
        "generation": generation,
        "active": True,
        "registration_receipt_path": str(receipt_path),
        "registration_receipt_sha256": sha256_file(receipt_path),
        "updated_at": registered_at,
    })
    return {"ok": True, "registration_receipt": str(receipt_path), **receipt}


def command_unregister_frontier_retry_trigger(
    args: argparse.Namespace,
) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    authorization = validate_applied_action_receipt(
        plan_dir, Path(args.authorization).resolve(), "stop",
    )
    root = frontier_retry_trigger_root(plan_dir)
    current_path = root / "current.json"
    current = read_json(current_path)
    if current.get("active") is not True:
        return {"ok": True, "idempotent": True, **current}
    receipt = read_json(Path(current["registration_receipt_path"]))
    if scheduler_is_loaded(
        receipt["launchctl_bin"], receipt["scheduler_label"],
    ):
        proc = subprocess.run([
            receipt["launchctl_bin"], "bootout",
            scheduler_service_target(receipt["scheduler_label"]),
        ], capture_output=True, text=True)
        if proc.returncode != 0:
            raise ContractError("frontier retry trigger removal failed")
    removal = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": current["plan_id"],
        "generation": current["generation"],
        "scheduler_label": receipt["scheduler_label"],
        "stop_record_id": authorization["record_id"],
        "unregistered_at": utc_now(),
    }
    removal_path = (
        root / "generations" / str(current["generation"])
        / "unregistration-receipt.json"
    )
    atomic_write_json(removal_path, removal, immutable=True)
    current.update({
        "active": False,
        "unregistration_receipt_path": str(removal_path),
        "unregistration_receipt_sha256": sha256_file(removal_path),
        "updated_at": removal["unregistered_at"],
    })
    atomic_write_json(current_path, current)
    return {"ok": True, "unregistration_receipt": str(removal_path), **removal}


def runtime_assurance_root(plan_dir: Path) -> Path:
    return plan_dir / "state" / "runtime_assurance" / "v1"


def unattended_durable_plan(plan_dir: Path) -> bool:
    graph_path = durable_graph_path(plan_dir)
    return graph_path.is_file() and read_json(graph_path).get(
        "execution_mode"
    ) == "unattended"


def validate_runtime_assurance_activation(
    plan_dir: Path, *, require_fresh: bool = True,
    require_l0_loaded: bool = True, require_l1_loaded: bool = True,
) -> dict[str, Any] | None:
    if not unattended_durable_plan(plan_dir):
        return None
    root = runtime_assurance_root(plan_dir)
    current_path = root / "current.json"
    if not current_path.is_file():
        raise ContractError(
            "unattended Worker requires runtime-assurance activation"
        )
    current = read_json(current_path)
    if current.get("active") is not True:
        raise ContractError("runtime-assurance activation is inactive")
    receipt_path = Path(current.get("activation_receipt_path", ""))
    if (
        not receipt_path.is_file()
        or receipt_path.stat().st_mode & 0o777 != 0o444
        or sha256_file(receipt_path) != current.get("activation_receipt_sha256")
    ):
        raise ContractError("runtime-assurance activation receipt changed")
    receipt = read_json(receipt_path)
    expected = {
        "plan_id": plan_identity(plan_dir),
        "schedule_id": current.get("schedule_id"),
        "l0_scheduler_label": current.get("l0_scheduler_label"),
        "l1_scheduler_label": current.get("l1_scheduler_label"),
        "health_interval_seconds": current.get("health_interval_seconds"),
        "worker_stale_seconds": current.get("worker_stale_seconds"),
        "frontier_stale_seconds": current.get("frontier_stale_seconds"),
        "heartbeat_stale_seconds": current.get("heartbeat_stale_seconds"),
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ContractError("runtime-assurance activation binding changed")
    immutable_bindings = (
        ("l0_scheduler_plist_path", "l0_scheduler_plist_sha256"),
        ("l1_registration_receipt_path", "l1_registration_receipt_sha256"),
        ("l2_heartbeat_contract_path", "l2_heartbeat_contract_sha256"),
        ("test_health_tick_path", "test_health_tick_sha256"),
        ("test_heartbeat_path", "test_heartbeat_sha256"),
    )
    for path_field, hash_field in immutable_bindings:
        bound_path = Path(receipt.get(path_field, ""))
        if (
            not bound_path.is_file()
            or bound_path.stat().st_mode & 0o777 != 0o444
            or sha256_file(bound_path) != receipt.get(hash_field)
        ):
            raise ContractError(
                f"runtime-assurance immutable binding changed: {path_field}"
            )
    l1_receipt = read_json(Path(receipt["l1_registration_receipt_path"]))
    if l1_receipt.get("scheduler_label") != receipt["l1_scheduler_label"]:
        raise ContractError("runtime-assurance L1 receipt identity changed")
    heartbeat_contract = read_json(Path(receipt["l2_heartbeat_contract_path"]))
    if (
        heartbeat_contract.get("plan_id") != receipt["plan_id"]
        or heartbeat_contract.get("heartbeat_stale_seconds")
        != receipt["heartbeat_stale_seconds"]
        or heartbeat_contract.get("model_dispatch_authority") is not False
    ):
        raise ContractError("runtime-assurance L2 heartbeat contract changed")
    for probe_field in ("test_health_tick_path", "test_heartbeat_path"):
        if read_json(Path(receipt[probe_field])).get("model_dispatches") != 0:
            raise ContractError("runtime-assurance test probe dispatched a model")
    launchctl_bin = receipt.get("launchctl_bin")
    if not isinstance(launchctl_bin, str):
        raise ContractError("runtime-assurance launchctl binding is missing")
    if require_l0_loaded and not scheduler_is_loaded(
        launchctl_bin, receipt["l0_scheduler_label"],
    ):
        raise ContractError("runtime-assurance L0 supervisor is not loaded")
    if require_l1_loaded and not scheduler_is_loaded(
        launchctl_bin, receipt["l1_scheduler_label"],
    ):
        raise ContractError("runtime-assurance L1 durable trigger is not loaded")
    if require_fresh:
        last_health = parse_utc(current["last_health_at"])
        if (
            datetime.now(timezone.utc) - last_health
        ).total_seconds() > 2 * receipt["health_interval_seconds"]:
            raise ContractError("runtime-assurance health receipt is stale")
    return receipt


def command_activate_runtime_assurance(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    if not unattended_durable_plan(plan_dir):
        raise ContractError("runtime assurance requires an unattended durable plan")
    values = {
        "health_interval_seconds": args.health_interval_seconds,
        "worker_stale_seconds": args.worker_stale_seconds,
        "frontier_stale_seconds": args.frontier_stale_seconds,
        "heartbeat_stale_seconds": args.heartbeat_stale_seconds,
    }
    for name, value in values.items():
        if not 60 <= value <= 86400:
            raise ContractError(f"{name} must be between 60 and 86400")
    shortest_stale = min(
        values["worker_stale_seconds"],
        values["frontier_stale_seconds"],
        values["heartbeat_stale_seconds"],
    )
    if (
        values["health_interval_seconds"] > 3600
        or 2 * values["health_interval_seconds"] > shortest_stale
    ):
        raise ContractError(
            "health interval must be at most one hour and no more than half "
            "the shortest stale threshold"
        )
    schedule_current = read_json(
        durable_schedule_root(plan_dir, args.schedule_id) / "current.json"
    )
    if schedule_current.get("active") is not True:
        raise ContractError("runtime assurance requires an active L1 durable trigger")
    l1_receipt_path = Path(schedule_current["registration_receipt_path"])
    l1_receipt = read_json(l1_receipt_path)
    resolved_launchctl = resolve_executable(args.launchctl_bin, label="launchctl")
    if not scheduler_is_loaded(resolved_launchctl, l1_receipt["scheduler_label"]):
        raise ContractError("runtime assurance requires the L1 scheduler to be loaded")
    root = runtime_assurance_root(plan_dir)
    current_path = root / "current.json"
    if current_path.is_file() and read_json(current_path).get("active") is True:
        receipt = validate_runtime_assurance_activation(
            plan_dir, require_fresh=False, require_l0_loaded=False,
        )
        assert receipt is not None
        if (
            receipt["schedule_id"] != args.schedule_id
            or receipt["launchctl_bin"] != resolved_launchctl
            or any(receipt[name] != value for name, value in values.items())
        ):
            raise ContractError(
                "active runtime assurance must be unregistered before replacement"
            )
        if not scheduler_is_loaded(
            resolved_launchctl, receipt["l0_scheduler_label"],
        ):
            proc = subprocess.run([
                resolved_launchctl, "bootstrap", f"gui/{os.getuid()}",
                receipt["l0_scheduler_plist_path"],
            ], capture_output=True, text=True)
            if proc.returncode != 0:
                raise ContractError("runtime assurance L0 recovery failed")
            return {
                "ok": True, "idempotent": True,
                "external_registration_recovered": True, **receipt,
            }
        return {"ok": True, "idempotent": True, **receipt}
    generation = int(read_json(current_path).get("generation", 0)) + 1 \
        if current_path.is_file() else 1
    generation_root = root / "generations" / str(generation)
    heartbeat_contract = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "source": "controller-worker-heartbeat-v1",
        "heartbeat_stale_seconds": args.heartbeat_stale_seconds,
        "model_dispatch_authority": False,
    }
    heartbeat_contract_path = generation_root / "heartbeat-contract.json"
    atomic_write_json(heartbeat_contract_path, heartbeat_contract, immutable=True)
    program = [
        sys.executable, str(Path(__file__).resolve()),
        "run-runtime-assurance-tick", "--plan-dir", str(plan_dir),
    ]
    l0_label = "com.autoresearch-paper.assurance." + hashlib.sha256(
        f"{plan_identity(plan_dir)}:{args.schedule_id}".encode()
    ).hexdigest()[:24]
    if l0_label == l1_receipt["scheduler_label"]:
        raise ContractError("runtime assurance L0 and L1 scheduler identities collided")
    plist_path = generation_root / f"{l0_label}.plist"
    l0_stdout_path = generation_root / "scheduler.stdout.log"
    l0_stderr_path = generation_root / "scheduler.stderr.log"
    atomic_write_bytes(plist_path, plistlib.dumps({
        "Label": l0_label,
        "ProgramArguments": program,
        "RunAtLoad": True,
        "StartInterval": args.health_interval_seconds,
        "ProcessType": "Background",
        "StandardOutPath": str(l0_stdout_path),
        "StandardErrorPath": str(l0_stderr_path),
    }, fmt=plistlib.FMT_XML), immutable=True)
    if not scheduler_is_loaded(resolved_launchctl, l0_label):
        proc = subprocess.run(
            [resolved_launchctl, "bootstrap", f"gui/{os.getuid()}", str(plist_path)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise ContractError(
                f"runtime assurance L0 registration failed: {proc.stderr.strip()}"
            )
    activated_at = utc_now()
    test_tick = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "kind": "activation_health_probe",
        "l0_loaded": scheduler_is_loaded(resolved_launchctl, l0_label),
        "l1_loaded": scheduler_is_loaded(
            resolved_launchctl, l1_receipt["scheduler_label"],
        ),
        "model_dispatches": 0,
        "observed_at": activated_at,
    }
    test_tick_path = generation_root / "test-health-tick.json"
    atomic_write_json(test_tick_path, test_tick, immutable=True)
    heartbeat_probe = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "kind": "activation_heartbeat_probe",
        "heartbeat_contract_sha256": sha256_file(heartbeat_contract_path),
        "model_dispatches": 0,
        "observed_at": activated_at,
    }
    heartbeat_probe_path = generation_root / "test-heartbeat.json"
    atomic_write_json(heartbeat_probe_path, heartbeat_probe, immutable=True)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "schedule_id": args.schedule_id,
        "generation": generation,
        "launchctl_bin": resolved_launchctl,
        "l0_scheduler_label": l0_label,
        "l0_scheduler_plist_path": str(plist_path),
        "l0_scheduler_plist_sha256": sha256_file(plist_path),
        "l0_scheduler_stdout_path": str(l0_stdout_path),
        "l0_scheduler_stderr_path": str(l0_stderr_path),
        "l0_controller_command_sha256": sha256_json(program),
        "l1_scheduler_label": l1_receipt["scheduler_label"],
        "l1_registration_receipt_path": str(l1_receipt_path),
        "l1_registration_receipt_sha256": sha256_file(l1_receipt_path),
        "l1_controller_command_sha256": read_json(
            Path(l1_receipt["schedule_contract_path"])
        )["controller_command_sha256"],
        "l2_heartbeat_contract_path": str(heartbeat_contract_path),
        "l2_heartbeat_contract_sha256": sha256_file(heartbeat_contract_path),
        **values,
        "test_health_tick_path": str(test_tick_path),
        "test_health_tick_sha256": sha256_file(test_tick_path),
        "test_heartbeat_path": str(heartbeat_probe_path),
        "test_heartbeat_sha256": sha256_file(heartbeat_probe_path),
        "activated_at": activated_at,
    }
    receipt_path = generation_root / "activation-receipt.json"
    atomic_write_json(receipt_path, receipt, immutable=True)
    atomic_write_json(current_path, {
        "schema_version": SCHEMA_VERSION,
        "plan_id": receipt["plan_id"],
        "schedule_id": args.schedule_id,
        "generation": generation,
        "active": True,
        "activation_receipt_path": str(receipt_path),
        "activation_receipt_sha256": sha256_file(receipt_path),
        "l0_scheduler_label": l0_label,
        "l1_scheduler_label": l1_receipt["scheduler_label"],
        **values,
        "last_health_at": activated_at,
        "updated_at": activated_at,
    })
    return {"ok": True, "activation_receipt": str(receipt_path), **receipt}


def command_run_runtime_assurance_tick(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    receipt = validate_runtime_assurance_activation(
        plan_dir, require_fresh=False, require_l1_loaded=False,
    )
    assert receipt is not None
    recovered_l1 = False
    if not scheduler_is_loaded(
        receipt["launchctl_bin"], receipt["l1_scheduler_label"],
    ):
        l1_receipt = read_json(Path(receipt["l1_registration_receipt_path"]))
        proc = subprocess.run([
            receipt["launchctl_bin"], "bootstrap", f"gui/{os.getuid()}",
            l1_receipt["scheduler_plist_path"],
        ], capture_output=True, text=True)
        if proc.returncode != 0:
            raise ContractError("runtime assurance could not recover L1 trigger")
        recovered_l1 = True
    patrol = command_run_patrol(argparse.Namespace(
        plan_dir=str(plan_dir), stale_seconds=receipt["worker_stale_seconds"],
    ))
    observed_at = utc_now()
    tick = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": receipt["plan_id"],
        "kind": "health_only",
        "recovered_l1": recovered_l1,
        "stale_workers": patrol["stale_workers"],
        "model_dispatches": 0,
        "observed_at": observed_at,
    }
    tick_path = runtime_assurance_root(plan_dir) / "ticks" / (
        f"tick_{sha256_json(tick)}.json"
    )
    atomic_write_json(tick_path, tick, immutable=True)
    current_path = runtime_assurance_root(plan_dir) / "current.json"
    current = read_json(current_path)
    current.update({
        "last_health_at": observed_at,
        "last_health_tick_path": str(tick_path),
        "last_health_tick_sha256": sha256_file(tick_path),
        "updated_at": observed_at,
    })
    atomic_write_json(current_path, current)
    return {"ok": True, "health_tick": str(tick_path), **tick}


def host_bootstrap_root(plan_dir: Path) -> Path:
    return plan_dir / "state" / "host_bootstrap" / "v1"


def record_host_bootstrap_failure(plan_dir: Path, error: str) -> None:
    """Attach a typed recoverable failure only after bootstrap has PREPARED."""
    journal_path = host_bootstrap_root(plan_dir) / "journal.json"
    if not journal_path.is_file():
        return
    journal = read_json(journal_path)
    if "simulated crash" in error:
        failure_class = "bootstrap_interrupted"
    elif "binding changed" in error or "changed" in error:
        failure_class = "bootstrap_binding_drift"
    elif "scheduler" in error or "L0" in error or "L1" in error:
        failure_class = "bootstrap_scheduler_failure"
    else:
        failure_class = "bootstrap_component_failure"
    fingerprint = hashlib.sha256(
        f"{journal.get('request_sha256')}\0{failure_class}\0{error}".encode()
    ).hexdigest()
    journal["last_failure"] = {
        "failure_class": failure_class,
        "fingerprint": fingerprint,
        "error": error,
        "recoverable": True,
        "recorded_at": utc_now(),
    }
    journal["updated_at"] = journal["last_failure"]["recorded_at"]
    atomic_write_json(journal_path, journal)


def validate_host_bootstrap_receipt(plan_dir: Path) -> dict[str, Any]:
    """Validate the committed Codex-host runtime bootstrap against live host state."""
    root = host_bootstrap_root(plan_dir)
    current = read_json(root / "current.json")
    if current.get("status") != "READY" or current.get("active") is not True:
        raise ContractError("Codex host runtime bootstrap is not READY")
    receipt_path = Path(current.get("receipt_path", ""))
    if (
        not receipt_path.is_file()
        or receipt_path.stat().st_mode & 0o777 != 0o444
        or sha256_file(receipt_path) != current.get("receipt_sha256")
    ):
        raise ContractError("Codex host bootstrap receipt binding changed")
    receipt = read_json(receipt_path)
    if receipt.get("plan_id") != plan_identity(plan_dir):
        raise ContractError("Codex host bootstrap receipt belongs to another plan")
    bindings = (
        ("request_path", "request_sha256"),
        ("durable_head_probe_path", "durable_head_probe_sha256"),
        ("l1_registration_receipt_path", "l1_registration_receipt_sha256"),
        ("runtime_assurance_receipt_path", "runtime_assurance_receipt_sha256"),
        ("l0_recovery_probe_path", "l0_recovery_probe_sha256"),
        ("l1_functional_probe_path", "l1_functional_probe_sha256"),
        ("l2_heartbeat_contract_path", "l2_heartbeat_contract_sha256"),
        ("l2_conformance_probe_path", "l2_conformance_probe_sha256"),
        ("dashboard_config_path", "dashboard_config_sha256"),
        ("runtime_resources_path", "runtime_resources_sha256"),
    )
    for path_field, hash_field in bindings:
        path = Path(receipt.get(path_field, ""))
        if (
            not path.is_file()
            or path.stat().st_mode & 0o777 != 0o444
            or sha256_file(path) != receipt.get(hash_field)
        ):
            raise ContractError(f"Codex host bootstrap binding changed: {path_field}")
    if "entry_prepared_receipt_path" in receipt:
        entry = validate_codex_host_preparation(plan_dir)
        activation = validate_codex_host_activation(plan_dir)
        for path_field, hash_field in (
            ("entry_prepared_receipt_path", "entry_prepared_receipt_sha256"),
            ("entry_activation_receipt_path", "entry_activation_receipt_sha256"),
            ("closed_brief_path", "closed_brief_sha256"),
            ("worker_session_policy_path", "worker_session_policy_sha256"),
            ("staged_state_snapshot_path", "staged_state_snapshot_sha256"),
        ):
            validate_immutable_binding(
                Path(receipt.get(path_field, "")), receipt.get(hash_field),
                f"Codex host bootstrap {path_field}",
            )
        if (
            receipt["entry_prepared_receipt_sha256"]
            != sha256_file(codex_host_entry_root(plan_dir) / "prepared-receipt.json")
            or receipt["entry_activation_receipt_sha256"]
            != sha256_file(codex_host_activation_root(plan_dir) / "activation-receipt.json")
            or entry["closed_brief_sha256"] != receipt["closed_brief_sha256"]
            or activation["staged_state_snapshot_sha256"]
            != receipt["staged_state_snapshot_sha256"]
        ):
            raise ContractError("Codex host entry lineage changed after bootstrap")
    l1 = read_json(Path(receipt["l1_registration_receipt_path"]))
    assurance = validate_runtime_assurance_activation(plan_dir)
    assert assurance is not None
    if (
        l1.get("scheduler_label") != receipt.get("l1_scheduler_label")
        or assurance.get("l0_scheduler_label") != receipt.get("l0_scheduler_label")
        or not scheduler_is_loaded(
            assurance["launchctl_bin"], receipt["l1_scheduler_label"],
        )
    ):
        raise ContractError("Codex host bootstrap scheduler binding is not live")
    l0_probe = read_json(Path(receipt["l0_recovery_probe_path"]))
    l1_probe = read_json(Path(receipt["l1_functional_probe_path"]))
    l2_probe = read_json(Path(receipt["l2_conformance_probe_path"]))
    l0_health_tick_path = Path(l0_probe.get("health_tick_path", ""))
    if (
        not l0_health_tick_path.is_file()
        or l0_health_tick_path.stat().st_mode & 0o777 != 0o444
        or sha256_file(l0_health_tick_path) != l0_probe.get("health_tick_sha256")
    ):
        raise ContractError("Codex host L0 health-tick binding changed")
    l0_health_tick = read_json(l0_health_tick_path)
    if (
        l0_probe.get("model_dispatches") != 0
        or l0_probe.get("l1_restored") is not True
        or l0_health_tick.get("model_dispatches") != 0
        or l1_probe.get("due") is not False
        or l1_probe.get("model_dispatches") != 0
        or l2_probe.get("model_dispatches") != 0
        or l2_probe.get("live_worker_evidence") is not False
    ):
        raise ContractError("Codex host bootstrap functional probe changed")
    return receipt


def command_bootstrap_host_runtime(args: argparse.Namespace) -> dict[str, Any]:
    """Transactionally compose and exercise L0/L1/L2 for the Codex Host."""
    plan_dir = Path(args.plan_dir).resolve()
    if not plan_dir.is_dir():
        raise ContractError("plan_dir must be an existing directory")
    policy = load_policy(plan_dir)
    check_transition_receipt(plan_dir, plan_identity(plan_dir), "approve_execution")
    entry_prepared = None
    entry_activation = None
    if (codex_host_entry_root(plan_dir) / "prepared-receipt.json").is_file():
        entry_prepared = validate_codex_host_preparation(plan_dir)
        entry_activation = validate_codex_host_activation(plan_dir)
    graph_path = Path(args.graph).resolve()
    graph = validate_durable_graph(plan_dir, read_json(graph_path))
    if graph.get("plan_id") != plan_identity(plan_dir):
        raise ContractError("durable graph belongs to another plan")
    if (
        entry_activation is not None
        and (
            entry_activation.get("durable_graph_path") != str(graph_path)
            or entry_activation.get("durable_graph_sha256") != sha256_file(graph_path)
        )
    ):
        raise ContractError("Codex host activation does not bind this durable graph")
    autonomy_tier = {
        "conference": "conference_unattended",
        "journal-q1": "journal_q1_unattended",
    }.get(graph.get("target_tier")) if graph.get("execution_mode") == "unattended" else None
    if autonomy_tier is not None:
        validate_current_evaluator_admission(plan_dir, graph, autonomy_tier)
    resolved_launchctl = resolve_executable(args.launchctl_bin, label="launchctl")
    if not 60 <= args.interval_seconds <= 86400:
        raise ContractError("interval_seconds must be between 60 and 86400")
    if not 0 <= args.jitter_seconds < args.interval_seconds:
        raise ContractError("jitter_seconds must be non-negative and below interval_seconds")
    for name in (
        "session_budget_seconds", "human_escalation_after_seconds", "lease_seconds",
        "health_interval_seconds", "worker_stale_seconds",
        "frontier_stale_seconds", "heartbeat_stale_seconds",
    ):
        value = getattr(args, name)
        if not 1 <= value <= 86400:
            raise ContractError(f"{name} must be between 1 and 86400")
    if args.health_interval_seconds < 60:
        raise ContractError("health_interval_seconds must be at least 60")
    shortest_stale = min(
        args.worker_stale_seconds,
        args.frontier_stale_seconds,
        args.heartbeat_stale_seconds,
    )
    if (
        args.health_interval_seconds > 3600
        or 2 * args.health_interval_seconds > shortest_stale
    ):
        raise ContractError(
            "health interval must be at most one hour and no more than half "
            "the shortest stale threshold"
        )
    if not 1 <= args.dashboard_port <= 65535:
        raise ContractError("dashboard_port must be between 1 and 65535")
    dashboard_index = SCRIPT_DIR.parent / "dashboard" / "index.html"
    dashboard_server = SCRIPT_DIR / "dashboard_server.py"
    if not dashboard_index.is_file() or not dashboard_server.is_file():
        raise ContractError("compiled Dashboard assets are incomplete")
    target_graph = durable_graph_path(plan_dir)
    if target_graph.is_file() and read_json(target_graph) != graph:
        raise ContractError("durable plan is already initialized with another graph")

    root = host_bootstrap_root(plan_dir)
    root.mkdir(parents=True, exist_ok=True)
    request_path = root / "request.json"
    existing_request = read_json(request_path) if request_path.is_file() else None
    created_at = existing_request.get("created_at") if existing_request else utc_now()
    if existing_request:
        first_due_at = existing_request["first_due_at"]
    else:
        first_due_at = (
            datetime.now(timezone.utc) + timedelta(seconds=args.interval_seconds)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    request = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "host": "codex",
        "graph_path": str(graph_path),
        "graph_sha256": sha256_file(graph_path),
        "graph_canonical_sha256": sha256_json(graph),
        "model_policy_sha256": sha256_file(policy_path(plan_dir)),
        "schedule_id": args.schedule_id,
        "interval_seconds": args.interval_seconds,
        "jitter_seconds": args.jitter_seconds,
        "session_budget_seconds": args.session_budget_seconds,
        "human_escalation_after_seconds": args.human_escalation_after_seconds,
        "lease_seconds": args.lease_seconds,
        "health_interval_seconds": args.health_interval_seconds,
        "worker_stale_seconds": args.worker_stale_seconds,
        "frontier_stale_seconds": args.frontier_stale_seconds,
        "heartbeat_stale_seconds": args.heartbeat_stale_seconds,
        "launchctl_bin": resolved_launchctl,
        "dashboard_host": "127.0.0.1",
        "dashboard_port": args.dashboard_port,
        "dashboard_index_sha256": sha256_file(dashboard_index),
        "dashboard_server_sha256": sha256_file(dashboard_server),
        "first_due_at": first_due_at,
        "created_at": created_at,
    }
    if existing_request and existing_request != request:
        raise ContractError("Codex host bootstrap request changed")
    if not request_path.is_file():
        atomic_write_json(request_path, request, immutable=True)
    current_path = root / "current.json"
    receipt_path = root / "bootstrap-receipt.json"
    if receipt_path.is_file():
        receipt = validate_host_bootstrap_receipt(plan_dir)
        return {"ok": True, "idempotent": True, **receipt}
    journal_path = root / "journal.json"
    journal = read_json(journal_path) if journal_path.is_file() else {
        "schema_version": SCHEMA_VERSION,
        "plan_id": request["plan_id"],
        "request_path": str(request_path),
        "request_sha256": sha256_file(request_path),
        "phase": "PREPARED",
        "prepared_at": utc_now(),
    }
    if (
        journal.get("plan_id") != request["plan_id"]
        or journal.get("request_sha256") != sha256_file(request_path)
    ):
        raise ContractError("Codex host bootstrap journal correlation mismatch")
    atomic_write_json(journal_path, journal)

    durable = command_init_durable_plan(argparse.Namespace(
        plan_dir=str(plan_dir), graph=str(graph_path),
    ))
    journal.update({"phase": "DURABLE_READY", "durable": durable, "updated_at": utc_now()})
    atomic_write_json(journal_path, journal)
    l1 = command_register_durable_trigger(argparse.Namespace(
        plan_dir=str(plan_dir), schedule_id=args.schedule_id,
        interval_seconds=args.interval_seconds, jitter_seconds=args.jitter_seconds,
        session_budget_seconds=args.session_budget_seconds,
        human_escalation_after_seconds=args.human_escalation_after_seconds,
        lease_seconds=args.lease_seconds, first_due_at=first_due_at,
        launchctl_bin=resolved_launchctl, simulate_crash_after_bootstrap=False,
    ))
    journal.update({"phase": "L1_READY", "l1": l1, "updated_at": utc_now()})
    atomic_write_json(journal_path, journal)
    if args.simulate_crash_after == "l1_registered":
        raise ContractError("simulated crash after Codex host L1 registration")
    assurance = command_activate_runtime_assurance(argparse.Namespace(
        plan_dir=str(plan_dir), schedule_id=args.schedule_id,
        health_interval_seconds=args.health_interval_seconds,
        worker_stale_seconds=args.worker_stale_seconds,
        frontier_stale_seconds=args.frontier_stale_seconds,
        heartbeat_stale_seconds=args.heartbeat_stale_seconds,
        launchctl_bin=resolved_launchctl,
    ))
    journal.update({"phase": "L0_L2_READY", "assurance": assurance, "updated_at": utc_now()})
    atomic_write_json(journal_path, journal)
    if args.simulate_crash_after == "assurance_activated":
        raise ContractError("simulated crash after Codex host assurance activation")

    probe_time = (
        parse_utc(first_due_at) - timedelta(seconds=1)
    ).isoformat().replace("+00:00", "Z")
    l1_result = command_run_durable_tick(argparse.Namespace(
        plan_dir=str(plan_dir), schedule_id=args.schedule_id,
        observed_at=probe_time, simulate_crash_after_tick_apply=False,
    ))
    if l1_result.get("due") is not False:
        raise ContractError("Codex host L1 probe unexpectedly advanced the plan")
    l1_probe = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": request["plan_id"],
        "kind": "l1_non_due_functional_probe",
        "controller_command_sha256": read_json(
            Path(l1["schedule_contract_path"])
        )["controller_command_sha256"],
        "due": False,
        "model_dispatches": 0,
        "observed_at": utc_now(),
    }
    l1_probe_path = root / "l1-functional-probe.json"
    if not l1_probe_path.is_file():
        atomic_write_json(l1_probe_path, l1_probe, immutable=True)
    elif {
        key: value for key, value in read_json(l1_probe_path).items()
        if key != "observed_at"
    } != {key: value for key, value in l1_probe.items() if key != "observed_at"}:
        raise ContractError("Codex host L1 probe changed")
    if args.simulate_crash_after == "l1_probe":
        raise ContractError("simulated crash after Codex host L1 probe")

    service_target = scheduler_service_target(l1["scheduler_label"])
    removed = False
    if scheduler_is_loaded(resolved_launchctl, l1["scheduler_label"]):
        proc = subprocess.run(
            [resolved_launchctl, "bootout", service_target],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise ContractError("Codex host could not exercise L1 loss")
        removed = True
    if args.simulate_crash_after == "l1_bootout":
        raise ContractError("simulated crash after Codex host L1 bootout")
    externally_restored = scheduler_is_loaded(
        resolved_launchctl, l1["scheduler_label"],
    )
    health = command_run_runtime_assurance_tick(argparse.Namespace(
        plan_dir=str(plan_dir),
    ))
    l1_restored = scheduler_is_loaded(resolved_launchctl, l1["scheduler_label"])
    if not removed or not l1_restored:
        raise ContractError("Codex host L0 probe did not restore the exact L1")
    l0_probe = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": request["plan_id"],
        "kind": "l0_l1_recovery_probe",
        "l1_was_removed": removed,
        "l1_restored": l1_restored,
        "recovered_by_tick": health.get("recovered_l1") is True,
        "recovered_by_external_l0": externally_restored,
        "health_tick_path": health["health_tick"],
        "health_tick_sha256": sha256_file(Path(health["health_tick"])),
        "model_dispatches": 0,
        "observed_at": utc_now(),
    }
    l0_probe_path = root / "l0-recovery-probe.json"
    if not l0_probe_path.is_file():
        atomic_write_json(l0_probe_path, l0_probe, immutable=True)
    elif any(
        read_json(l0_probe_path).get(key) != l0_probe.get(key)
        for key in ("plan_id", "kind", "l1_was_removed", "l1_restored", "model_dispatches")
    ):
        raise ContractError("Codex host L0 recovery probe changed")

    assurance_receipt_path = Path(
        assurance.get("activation_receipt")
        or assurance.get("activation_receipt_path")
        or read_json(runtime_assurance_root(plan_dir) / "current.json")[
            "activation_receipt_path"
        ]
    )
    assurance_receipt = read_json(assurance_receipt_path)
    l2_probe_path = root / "l2-conformance-probe.json"
    l2_probe = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": request["plan_id"],
        "kind": "l2_heartbeat_contract_conformance",
        "heartbeat_contract_sha256": assurance_receipt["l2_heartbeat_contract_sha256"],
        "activation_probe_sha256": assurance_receipt["test_heartbeat_sha256"],
        "model_dispatches": 0,
        "live_worker_evidence": False,
        "live_worker_gate": "T032",
        "observed_at": utc_now(),
    }
    if not l2_probe_path.is_file():
        atomic_write_json(l2_probe_path, l2_probe, immutable=True)
    elif any(
        read_json(l2_probe_path).get(key) != l2_probe.get(key)
        for key in (
            "plan_id", "kind", "heartbeat_contract_sha256",
            "activation_probe_sha256", "model_dispatches", "live_worker_evidence",
        )
    ):
        raise ContractError("Codex host L2 conformance probe changed")

    dashboard_config_path = root / "dashboard-config.json"
    dashboard_config = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": request["plan_id"],
        "host": "127.0.0.1",
        "port": args.dashboard_port,
        "observation_only": True,
        "index_sha256": request["dashboard_index_sha256"],
        "server_sha256": request["dashboard_server_sha256"],
    }
    if not dashboard_config_path.is_file():
        atomic_write_json(dashboard_config_path, dashboard_config, immutable=True)
    elif read_json(dashboard_config_path) != dashboard_config:
        raise ContractError("Codex host Dashboard configuration changed")

    runtime_resources_path = root / "runtime-resources.json"
    runtime_resources = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": request["plan_id"],
        "ownership_scope": "shutdown-plan",
        "resources": [
            {"kind": "launchd", "layer": "L0", "label": assurance_receipt["l0_scheduler_label"]},
            {"kind": "launchd", "layer": "L1", "label": l1["scheduler_label"]},
        ],
    }
    if not runtime_resources_path.is_file():
        atomic_write_json(runtime_resources_path, runtime_resources, immutable=True)
    elif read_json(runtime_resources_path) != runtime_resources:
        raise ContractError("Codex host runtime resource binding changed")
    manifest_path = plan_dir / "resource_manifest.json"
    manifest = read_json(manifest_path)
    resource_entry = {
        "resource_id": "codex_host_runtime_assurance_v1",
        "kind": "runtime_assurance_bundle",
        "path": str(runtime_resources_path.relative_to(plan_dir)),
        "ephemeral": False,
        "run_scoped": True,
        "ownership_generation": sha256_file(request_path)[:16],
    }
    resources = manifest.setdefault("resources", [])
    prior_resource = next(
        (item for item in resources if isinstance(item, dict)
         and item.get("resource_id") == resource_entry["resource_id"]),
        None,
    )
    if prior_resource is None:
        resources.append(resource_entry)
        atomic_write_json(manifest_path, manifest)
    elif prior_resource != resource_entry:
        raise ContractError("Codex host runtime resource manifest changed")

    durable_head_path = durable_root(plan_dir) / "canonical" / "head.json"
    durable_head_probe_path = root / "durable-head-probe.json"
    durable_head = read_json(durable_head_path)
    durable_head_probe = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": request["plan_id"],
        "kind": "bootstrap_durable_head_binding",
        "head_path": str(durable_head_path),
        "head_sha256_at_bootstrap": sha256_file(durable_head_path),
        "state_revision": durable_head["state_revision"],
        "state_path": durable_head["state_path"],
        "state_sha256": durable_head["state_sha256"],
        "event_id": durable_head["event_id"],
    }
    if not durable_head_probe_path.is_file():
        atomic_write_json(
            durable_head_probe_path, durable_head_probe, immutable=True,
        )
    elif read_json(durable_head_probe_path) != durable_head_probe:
        raise ContractError("Codex host durable head probe changed")
    l1_receipt_path = Path(
        l1.get("registration_receipt")
        or l1.get("registration_receipt_path")
        or read_json(durable_schedule_root(plan_dir, args.schedule_id) / "current.json")[
            "registration_receipt_path"
        ]
    )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": request["plan_id"],
        "host": "codex",
        "status": "READY",
        "request_path": str(request_path),
        "request_sha256": sha256_file(request_path),
        "model_policy_sha256": sha256_file(policy_path(plan_dir)),
        "durable_head_path": str(durable_head_path),
        "durable_head_sha256": sha256_file(durable_head_path),
        "durable_head_probe_path": str(durable_head_probe_path),
        "durable_head_probe_sha256": sha256_file(durable_head_probe_path),
        "l0_scheduler_label": assurance_receipt["l0_scheduler_label"],
        "l1_scheduler_label": l1["scheduler_label"],
        "l1_registration_receipt_path": str(l1_receipt_path),
        "l1_registration_receipt_sha256": sha256_file(l1_receipt_path),
        "runtime_assurance_receipt_path": str(assurance_receipt_path),
        "runtime_assurance_receipt_sha256": sha256_file(assurance_receipt_path),
        "l0_recovery_probe_path": str(l0_probe_path),
        "l0_recovery_probe_sha256": sha256_file(l0_probe_path),
        "l1_functional_probe_path": str(l1_probe_path),
        "l1_functional_probe_sha256": sha256_file(l1_probe_path),
        "l2_heartbeat_contract_path": assurance_receipt["l2_heartbeat_contract_path"],
        "l2_heartbeat_contract_sha256": assurance_receipt["l2_heartbeat_contract_sha256"],
        "l2_conformance_probe_path": str(l2_probe_path),
        "l2_conformance_probe_sha256": sha256_file(l2_probe_path),
        "dashboard_config_path": str(dashboard_config_path),
        "dashboard_config_sha256": sha256_file(dashboard_config_path),
        "runtime_resources_path": str(runtime_resources_path),
        "runtime_resources_sha256": sha256_file(runtime_resources_path),
        "live_l2_worker_evidence": None,
        "live_l2_worker_gate": "T032",
        "committed_at": utc_now(),
    }
    if entry_prepared is not None and entry_activation is not None:
        receipt.update({
            "entry_prepared_receipt_path": str(
                codex_host_entry_root(plan_dir) / "prepared-receipt.json"
            ),
            "entry_prepared_receipt_sha256": sha256_file(
                codex_host_entry_root(plan_dir) / "prepared-receipt.json"
            ),
            "entry_activation_receipt_path": str(
                codex_host_activation_root(plan_dir) / "activation-receipt.json"
            ),
            "entry_activation_receipt_sha256": sha256_file(
                codex_host_activation_root(plan_dir) / "activation-receipt.json"
            ),
            "closed_brief_path": entry_prepared["closed_brief_path"],
            "closed_brief_sha256": entry_prepared["closed_brief_sha256"],
            "worker_session_policy_path": entry_prepared["worker_session_policy_path"],
            "worker_session_policy_sha256": entry_prepared["worker_session_policy_sha256"],
            "staged_state_snapshot_path": entry_activation["staged_state_snapshot_path"],
            "staged_state_snapshot_sha256": entry_activation["staged_state_snapshot_sha256"],
        })
    atomic_write_json(receipt_path, receipt, immutable=True)
    journal.update({
        "phase": "COMMITTED", "receipt_path": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path), "updated_at": utc_now(),
    })
    atomic_write_json(journal_path, journal)
    atomic_write_json(current_path, {
        "schema_version": SCHEMA_VERSION,
        "plan_id": request["plan_id"],
        "status": "READY",
        "active": True,
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
        "last_health_action": "l1_restored",
        "last_health_tick_path": health["health_tick"],
        "live_l2_worker_evidence": None,
        "updated_at": receipt["committed_at"],
    })
    return {"ok": True, **receipt}


def command_unregister_runtime_assurance(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    authorization = validate_applied_action_receipt(
        plan_dir, Path(args.authorization).resolve(), "stop",
    )
    current_path = runtime_assurance_root(plan_dir) / "current.json"
    current = read_json(current_path)
    if current.get("active") is not True:
        return {"ok": True, "idempotent": True, **current}
    receipt = read_json(Path(current["activation_receipt_path"]))
    if scheduler_is_loaded(
        receipt["launchctl_bin"], receipt["l0_scheduler_label"],
    ):
        proc = subprocess.run([
            receipt["launchctl_bin"], "bootout",
            scheduler_service_target(receipt["l0_scheduler_label"]),
        ], capture_output=True, text=True)
        if proc.returncode != 0:
            raise ContractError("runtime assurance L0 removal failed")
    removal = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": current["plan_id"],
        "generation": current["generation"],
        "l0_scheduler_label": current["l0_scheduler_label"],
        "stop_record_id": authorization["record_id"],
        "unregistered_at": utc_now(),
    }
    removal_path = (
        runtime_assurance_root(plan_dir) / "generations"
        / str(current["generation"]) / "unregistration-receipt.json"
    )
    atomic_write_json(removal_path, removal, immutable=True)
    current.update({
        "active": False,
        "unregistration_receipt_path": str(removal_path),
        "unregistration_receipt_sha256": sha256_file(removal_path),
        "updated_at": removal["unregistered_at"],
    })
    atomic_write_json(current_path, current)
    return {"ok": True, "unregistration_receipt": str(removal_path), **removal}


def optional_json(path: Path) -> dict[str, Any] | None:
    return read_json(path) if path.is_file() else None


def observable_file(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return {
        "path": str(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else None,
        "sha256": sha256_file(path) if path.is_file() else None,
    }


def inspect_scheduler_binding(
    *, kind: str, current_path: Path, default_launchctl: str,
    label_field: str = "scheduler_label",
) -> dict[str, Any]:
    current = optional_json(current_path)
    result: dict[str, Any] = {
        "kind": kind,
        "current_path": str(current_path),
        "present": current is not None,
        "active": bool(current and current.get("active") is True),
    }
    if current is None:
        return result
    receipt_path_value = current.get("registration_receipt_path")
    if kind == "l0_runtime_assurance":
        receipt_path_value = current.get("activation_receipt_path")
    receipt_path = (
        Path(receipt_path_value) if isinstance(receipt_path_value, str) else None
    )
    receipt = optional_json(receipt_path) if receipt_path is not None else None
    label = current.get(label_field)
    if not isinstance(label, str) and receipt is not None:
        label = receipt.get(label_field)
    launchctl_bin = default_launchctl
    if receipt is not None and isinstance(receipt.get("launchctl_bin"), str):
        launchctl_bin = receipt["launchctl_bin"]
    loaded = None
    if isinstance(label, str):
        try:
            loaded = scheduler_is_loaded(launchctl_bin, label)
        except OSError:
            loaded = False
    stdout_path = None
    stderr_path = None
    if receipt is not None:
        if isinstance(receipt.get("scheduler_stdout_path"), str):
            stdout_path = Path(receipt["scheduler_stdout_path"])
        if isinstance(receipt.get("scheduler_stderr_path"), str):
            stderr_path = Path(receipt["scheduler_stderr_path"])
        if kind == "l0_runtime_assurance":
            if isinstance(receipt.get("l0_scheduler_stdout_path"), str):
                stdout_path = Path(receipt["l0_scheduler_stdout_path"])
            if isinstance(receipt.get("l0_scheduler_stderr_path"), str):
                stderr_path = Path(receipt["l0_scheduler_stderr_path"])
    result.update({
        "label": label,
        "loaded": loaded,
        "state_matches_scheduler": (
            loaded == result["active"] if loaded is not None else None
        ),
        "receipt": observable_file(receipt_path),
        "stdout": observable_file(stdout_path),
        "stderr": observable_file(stderr_path),
        "current": current,
    })
    return result


def declared_runtime_resources(plan_dir: Path) -> list[dict[str, Any]]:
    manifest_path = plan_dir / "resource_manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = read_json(manifest_path)
    declared: list[dict[str, Any]] = []
    if isinstance(manifest.get("resources"), list):
        for item in manifest["resources"]:
            if isinstance(item, dict):
                declared.append({"kind": item.get("kind", "resource"), **item})
    for kind in (
        "local_processes", "remote_processes", "launchd", "crons", "hooks",
        "sessions", "agents", "locks",
    ):
        values = manifest.get(kind, [])
        if not isinstance(values, list):
            continue
        for value in values:
            item = {"name": value} if isinstance(value, str) else value
            if isinstance(item, dict):
                record = {"kind": kind, **item}
                if kind == "local_processes" and isinstance(item.get("pid"), int):
                    record["process_observation"] = observe_process_identity(item["pid"])
                declared.append(record)
    return declared


def inspect_host_bootstrap_binding(plan_dir: Path) -> dict[str, Any]:
    current_path = host_bootstrap_root(plan_dir) / "current.json"
    if not current_path.is_file():
        return {
            "present": False,
            "status": "ABSENT",
            "active": False,
            "last_health_action": None,
            "live_l2_worker_evidence": None,
            "receipt": observable_file(None),
            "last_health_tick": observable_file(None),
        }
    current = read_json(current_path)
    receipt_path = Path(current["receipt_path"]) \
        if isinstance(current.get("receipt_path"), str) else None
    assurance_current = optional_json(
        runtime_assurance_root(plan_dir) / "current.json"
    ) or {}
    tick_value = assurance_current.get("last_health_tick_path") \
        or current.get("last_health_tick_path")
    tick_path = Path(tick_value) if isinstance(tick_value, str) else None
    tick = optional_json(tick_path) if tick_path is not None else None
    validation_error = None
    try:
        validate_host_bootstrap_receipt(plan_dir)
    except ContractError as exc:
        validation_error = str(exc)
    return {
        "present": True,
        "status": current.get("status"),
        "active": current.get("active") is True,
        "last_health_action": (
            "l1_restored" if isinstance(tick, dict) and tick.get("recovered_l1") is True
            else "healthy" if isinstance(tick, dict)
            else current.get("last_health_action")
        ),
        "live_l2_worker_evidence": current.get("live_l2_worker_evidence"),
        "validation_error": validation_error,
        "receipt": observable_file(receipt_path),
        "last_health_tick": observable_file(tick_path),
    }


def command_inspect_plan_runtime(args: argparse.Namespace) -> dict[str, Any]:
    """Correlate runtime truth without writing state or scheduler resources."""
    plan_dir = Path(args.plan_dir).resolve()
    resolved_launchctl = resolve_executable(args.launchctl_bin, label="launchctl")
    controller_path = plan_dir / "state" / "controller.json"
    staged_path = staged_state_path(plan_dir)
    durable_head_path = durable_root(plan_dir) / "canonical" / "head.json"
    durable_projection_path = durable_root(plan_dir) / "projection.json"
    schedulers: list[dict[str, Any]] = []
    schedulers.append(inspect_scheduler_binding(
        kind="l0_runtime_assurance",
        current_path=runtime_assurance_root(plan_dir) / "current.json",
        default_launchctl=resolved_launchctl,
        label_field="l0_scheduler_label",
    ))
    schedules_root = durable_root(plan_dir) / "schedules"
    for current_path in sorted(schedules_root.glob("*/current.json")) \
            if schedules_root.is_dir() else []:
        schedulers.append(inspect_scheduler_binding(
            kind="l1_durable_trigger", current_path=current_path,
            default_launchctl=resolved_launchctl,
        ))
    schedulers.append(inspect_scheduler_binding(
        kind="frontier_retry_trigger",
        current_path=frontier_retry_trigger_root(plan_dir) / "current.json",
        default_launchctl=resolved_launchctl,
    ))
    workers: list[dict[str, Any]] = []
    workers_root = plan_dir / "state" / "worker_runs"
    for status_path_value in sorted(workers_root.glob("*/status.json")) \
            if workers_root.is_dir() else []:
        status = read_json(status_path_value)
        workers.append({
            "run_id": status.get("run_id", status_path_value.parent.name),
            "status_path": str(status_path_value),
            "status_sha256": sha256_file(status_path_value),
            "status": status,
            "process": worker_process_observation(status),
            "stdout": observable_file(
                Path(status["transport_stdout_path"])
                if isinstance(status.get("transport_stdout_path"), str)
                else status_path_value.parent / "transport.stdout"
            ),
            "stderr": observable_file(
                Path(status["transport_stderr_path"])
                if isinstance(status.get("transport_stderr_path"), str)
                else status_path_value.parent / "transport.stderr"
            ),
        })
    mismatches = [
        {"kind": item["kind"], "label": item.get("label")}
        for item in schedulers
        if item.get("state_matches_scheduler") is False
    ]
    mismatches.extend(
        {"kind": "worker", "run_id": item["run_id"], "reason": item["process"]["reason"]}
        for item in workers
        if item["status"].get("status") == "RUNNING"
        and item["process"].get("identity_match") is not True
    )
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "observed_at": utc_now(),
        "observation_only": True,
        "canonical": {
            "controller": observable_file(controller_path),
            "controller_status": (
                read_json(controller_path).get("status")
                if controller_path.is_file() else None
            ),
            "staged_state": observable_file(staged_path),
            "staged_status": (
                read_json(staged_path).get("state") if staged_path.is_file() else None
            ),
            "durable_head": observable_file(durable_head_path),
            "durable_projection": observable_file(durable_projection_path),
        },
        "schedulers": schedulers,
        "workers": workers,
        "host_bootstrap": inspect_host_bootstrap_binding(plan_dir),
        "declared_resources": declared_runtime_resources(plan_dir),
        "mismatches": mismatches,
        "shutdown": optional_json(
            plan_dir / "state" / "runtime_shutdown" / "v1" / "current.json"
        ),
    }


def command_serve_plan_dashboard(args: argparse.Namespace) -> dict[str, Any]:
    """Serve one fresh inspection surface without lifecycle authority."""
    plan_dir = Path(args.plan_dir).resolve(strict=True)
    resolved_launchctl = resolve_executable(args.launchctl_bin, label="launchctl")
    assets_dir = SCRIPT_DIR.parent / "dashboard"

    def inspect() -> dict[str, Any]:
        return command_inspect_plan_runtime(argparse.Namespace(
            plan_dir=str(plan_dir), launchctl_bin=resolved_launchctl,
        ))

    try:
        server = make_dashboard_server(
            host=args.host,
            port=args.port,
            plan_dir=plan_dir,
            assets_dir=assets_dir,
            snapshot_provider=inspect,
        )
    except (DashboardError, OSError, ValueError) as exc:
        raise ContractError(str(exc)) from exc
    host, port = server.server_address[:2]
    started = {
        "ok": True,
        "observation_only": True,
        "plan_id": plan_identity(plan_dir),
        "url": f"http://{host}:{port}/",
    }
    print(json.dumps(started, sort_keys=True), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {**started, "stopped": True}


def runtime_shutdown_root(plan_dir: Path) -> Path:
    return plan_dir / "state" / "runtime_shutdown" / "v1"


def write_shutdown_journal(path: Path, journal: dict[str, Any]) -> None:
    journal["updated_at"] = utc_now()
    atomic_write_json(path, journal)


def shutdown_worker(
    plan_dir: Path, run_id: str, stop_receipt: dict[str, Any],
    *, term_grace_seconds: float,
) -> dict[str, Any]:
    status = read_json(worker_status_path(plan_dir, run_id))
    if status.get("status") in {"COMPLETED", "FAILED", "CANCELLED"}:
        return {"run_id": run_id, "outcome": "already_terminal", "status": status["status"]}
    signal_result = signal_bound_worker_process(
        status, term_grace_seconds=term_grace_seconds,
    )
    terminal = update_worker_status(plan_dir, run_id, "CANCELLED", {
        "completed_at": utc_now(),
        "authority_record_id": stop_receipt["record_id"],
        "cancelled_by": "plan_shutdown",
        "process_termination": signal_result,
    })
    return {
        "run_id": run_id,
        "outcome": signal_result["outcome"],
        "status": terminal["status"],
        "process_termination": signal_result,
    }


def command_shutdown_plan(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    authorization_path = Path(args.authorization).resolve()
    authorization = validate_applied_action_receipt(
        plan_dir, authorization_path, "stop",
    )
    if not 0.1 <= args.term_grace_seconds <= 60:
        raise ContractError("term_grace_seconds must be between 0.1 and 60")
    resolved_launchctl = resolve_executable(args.launchctl_bin, label="launchctl")
    root = runtime_shutdown_root(plan_dir)
    journal_path = root / "shutdown-journal.json"
    current_path = root / "current.json"
    receipt_path = root / "shutdown-receipt.json"
    lock_path = root / ".shutdown.lock"
    root.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if receipt_path.is_file():
            receipt = read_json(receipt_path)
            if receipt.get("stop_record_id") != authorization["record_id"]:
                raise ContractError("shutdown receipt belongs to another stop authority")
            return {"ok": True, "idempotent": True, **receipt}
        journal = optional_json(journal_path)
        if journal is None:
            journal = {
                "schema_version": SCHEMA_VERSION,
                "phase": "PREPARED",
                "plan_id": plan_identity(plan_dir),
                "stop_record_id": authorization["record_id"],
                "stop_receipt_path": str(authorization_path),
                "stop_receipt_sha256": sha256_file(authorization_path),
                "steps": {},
                "worker_targets": [],
                "prepared_at": utc_now(),
            }
            write_shutdown_journal(journal_path, journal)
        elif (
            journal.get("stop_record_id") != authorization["record_id"]
            or journal.get("stop_receipt_sha256") != sha256_file(authorization_path)
        ):
            raise ContractError("prepared shutdown authority changed")

        steps = journal.setdefault("steps", {})
        l0_current = runtime_assurance_root(plan_dir) / "current.json"
        if "l0" not in steps:
            steps["l0"] = (
                command_unregister_runtime_assurance(argparse.Namespace(
                    plan_dir=str(plan_dir), authorization=str(authorization_path),
                )) if l0_current.is_file() else {"ok": True, "absent": True}
            )
            write_shutdown_journal(journal_path, journal)
            if args.simulate_crash_after == "l0":
                raise ContractError("simulated crash after shutdown l0")

        if "l1" not in steps:
            l1_results: list[dict[str, Any]] = []
            schedules_root = durable_root(plan_dir) / "schedules"
            for current in sorted(schedules_root.glob("*/current.json")) \
                    if schedules_root.is_dir() else []:
                schedule_id = current.parent.name
                l1_results.append(command_unregister_durable_trigger(argparse.Namespace(
                    plan_dir=str(plan_dir), schedule_id=schedule_id,
                    authorization=str(authorization_path),
                    launchctl_bin=resolved_launchctl,
                )))
            steps["l1"] = {"ok": True, "schedules": l1_results}
            write_shutdown_journal(journal_path, journal)
            if args.simulate_crash_after == "l1":
                raise ContractError("simulated crash after shutdown l1")

        retry_current = frontier_retry_trigger_root(plan_dir) / "current.json"
        if "frontier_retry" not in steps:
            steps["frontier_retry"] = (
                command_unregister_frontier_retry_trigger(argparse.Namespace(
                    plan_dir=str(plan_dir), authorization=str(authorization_path),
                )) if retry_current.is_file() else {"ok": True, "absent": True}
            )
            write_shutdown_journal(journal_path, journal)
            if args.simulate_crash_after == "frontier_retry":
                raise ContractError("simulated crash after shutdown frontier retry")

        workers_root = plan_dir / "state" / "worker_runs"
        targets = {
            status_path.parent.name
            for status_path in workers_root.glob("*/status.json")
        } if workers_root.is_dir() else set()
        journal["worker_targets"] = sorted(
            set(journal.get("worker_targets", [])) | targets
        )
        worker_results = steps.setdefault("workers", {})
        for run_id in journal["worker_targets"]:
            if run_id in worker_results:
                continue
            worker_results[run_id] = shutdown_worker(
                plan_dir, run_id, authorization,
                term_grace_seconds=args.term_grace_seconds,
            )
            write_shutdown_journal(journal_path, journal)
            if args.simulate_crash_after == "worker":
                raise ContractError("simulated crash after shutdown worker")

        snapshot = command_inspect_plan_runtime(argparse.Namespace(
            plan_dir=str(plan_dir), launchctl_bin=resolved_launchctl,
        ))
        residuals: list[dict[str, Any]] = []
        for scheduler in snapshot["schedulers"]:
            if scheduler.get("loaded") is True:
                residuals.append({
                    "kind": "scheduler_loaded", "label": scheduler.get("label"),
                })
        residual_outcomes = {
            "identity_mismatch", "identity_changed_after_sigterm",
            "identity_unavailable", "still_running",
        }
        for run_id, result in worker_results.items():
            if result.get("outcome") in residual_outcomes:
                residuals.append({
                    "kind": "worker_process", "run_id": run_id,
                    "reason": result["outcome"],
                })
        for resource in snapshot["declared_resources"]:
            observation = resource.get("process_observation")
            if isinstance(observation, dict):
                residuals.append({
                    "kind": "declared_local_process",
                    "pid": resource.get("pid"),
                    "reason": "cleanup_resource_authority_required",
                })
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": plan_identity(plan_dir),
            "shutdown_id": "shutdown_" + hashlib.sha256(
                authorization["record_id"].encode()
            ).hexdigest(),
            "stop_record_id": authorization["record_id"],
            "stop_receipt_path": str(authorization_path),
            "stop_receipt_sha256": sha256_file(authorization_path),
            "journal_path": str(journal_path),
            "journal_sha256_before_commit": sha256_file(journal_path),
            "steps": steps,
            "residuals": residuals,
            "artifacts_deleted": False,
            "cleanup_resource_authority": False,
            "status": "SHUTDOWN" if not residuals else "SHUTDOWN_WITH_RESIDUALS",
            "completed_at": utc_now(),
        }
        atomic_write_json(receipt_path, receipt, immutable=True)
        journal.update({
            "phase": "COMMITTED",
            "shutdown_receipt_path": str(receipt_path),
            "shutdown_receipt_sha256": sha256_file(receipt_path),
            "committed_at": receipt["completed_at"],
        })
        write_shutdown_journal(journal_path, journal)
        atomic_write_json(current_path, {
            "schema_version": SCHEMA_VERSION,
            "plan_id": receipt["plan_id"],
            "status": receipt["status"],
            "shutdown_id": receipt["shutdown_id"],
            "shutdown_receipt_path": str(receipt_path),
            "shutdown_receipt_sha256": sha256_file(receipt_path),
            "updated_at": receipt["completed_at"],
        })
    return {"ok": True, "shutdown_receipt": str(receipt_path), **receipt}


def durable_tick_root(plan_dir: Path, schedule_id: str, tick_id: str) -> Path:
    if not DURABLE_TICK_ID_RE.fullmatch(tick_id):
        raise ContractError("invalid durable tick_id")
    return durable_schedule_root(plan_dir, schedule_id) / "ticks" / tick_id


def claim_tick_locked(
    plan_dir: Path,
    schedule_id: str,
    tick_id: str,
    observed_at: datetime,
    lease_seconds: int,
) -> dict[str, Any]:
    tick_root = durable_tick_root(plan_dir, schedule_id, tick_id)
    current_path = tick_root / "current.json"
    current = read_json(current_path) if current_path.exists() else None
    if current and current.get("status") == "APPLIED":
        return {"ok": True, "already_applied": True, "claim": current}
    if current and current.get("status") == "CLAIMED":
        expiry = parse_utc(current["lease_expires_at"])
        if observed_at < expiry:
            return {"ok": True, "already_claimed": True, "claim": current}
        generation = current["generation"] + 1
    else:
        generation = 1
    contract_pointer = read_json(durable_schedule_root(plan_dir, schedule_id) / "current.json")
    if contract_pointer.get("active") is not True:
        raise ContractError("durable schedule is not active")
    claim_basis = {
        "plan_id": plan_identity(plan_dir),
        "schedule_id": schedule_id,
        "tick_id": tick_id,
        "generation": generation,
        "claimed_at": observed_at.isoformat().replace("+00:00", "Z"),
    }
    claim_id = f"claim_{sha256_json(claim_basis)}"
    receipt = {
        "schema_version": SCHEMA_VERSION,
        **claim_basis,
        "claim_id": claim_id,
        "lease_expires_at": (
            observed_at + timedelta(seconds=lease_seconds)
        ).isoformat().replace("+00:00", "Z"),
        "schedule_contract_sha256": contract_pointer["schedule_contract_sha256"],
        "status": "CLAIMED",
    }
    receipt_path = tick_root / "claims" / f"{claim_id}.json"
    atomic_write_json(receipt_path, receipt, immutable=True)
    atomic_write_json(current_path, {**receipt, "claim_receipt_path": str(receipt_path)})
    append_jsonl(durable_schedule_root(plan_dir, schedule_id) / "tick-events.jsonl", {
        "schema_version": SCHEMA_VERSION,
        "event": "tick_claimed",
        **receipt,
    })
    return {"ok": True, "claim_receipt": str(receipt_path), "claim": receipt}


def command_claim_durable_tick(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    observed_at = parse_utc(args.observed_at) if args.observed_at else datetime.now(timezone.utc)
    if not 1 <= args.lease_seconds <= 86400:
        raise ContractError("lease_seconds must be between 1 and 86400")
    with durable_loop_lock(plan_dir):
        return claim_tick_locked(
            plan_dir, args.schedule_id, args.tick_id, observed_at, args.lease_seconds,
        )


def command_reconcile_durable_tick(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    observed_at = parse_utc(args.observed_at) if args.observed_at else datetime.now(timezone.utc)
    tick_root = durable_tick_root(plan_dir, args.schedule_id, args.tick_id)
    with durable_loop_lock(plan_dir):
        current = read_json(tick_root / "current.json")
        if current.get("status") == "APPLIED":
            outcome = "superseded"
            resulting = current["generation"]
            applied_claim_id = current["claim_id"]
        elif observed_at < parse_utc(current["lease_expires_at"]):
            outcome = "pending"
            resulting = current["generation"]
            applied_claim_id = None
        else:
            schedule = read_json(Path(
                read_json(durable_schedule_root(plan_dir, args.schedule_id) / "current.json")[
                    "schedule_contract_path"
                ]
            ))
            claimed = claim_tick_locked(
                plan_dir, args.schedule_id, args.tick_id, observed_at, schedule["lease_seconds"],
            )
            outcome = "advanced"
            resulting = claimed["claim"]["generation"]
            applied_claim_id = None
            current = claimed["claim"]
        body = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": plan_identity(plan_dir),
            "schedule_id": args.schedule_id,
            "tick_id": args.tick_id,
            "observed_generation": max(1, resulting - 1) if outcome == "advanced" else resulting,
            "outcome": outcome,
            "resulting_generation": resulting,
            "applied_claim_id": applied_claim_id,
            "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        }
        result = {**body, "evidence_sha256": sha256_json({"claim": current, **body})}
        target = tick_root / "reconciliations" / f"{sha256_json(result)}.json"
        atomic_write_json(target, result, immutable=True)
    return {"ok": True, "reconciliation_result": str(target), **result}


def mark_tick_applied(
    plan_dir: Path,
    schedule_id: str,
    tick_id: str,
    claim_id: str,
    result: dict[str, Any],
    applied_at: datetime,
) -> dict[str, Any]:
    tick_root = durable_tick_root(plan_dir, schedule_id, tick_id)
    current_path = tick_root / "current.json"
    current = read_json(current_path)
    if current.get("status") == "APPLIED":
        if current.get("claim_id") != claim_id:
            raise ContractError("durable tick was applied by another claim")
        return current
    if current.get("claim_id") != claim_id or current.get("status") != "CLAIMED":
        raise ContractError("durable tick claim is no longer current")
    applied = {
        **current,
        "status": "APPLIED",
        "applied_at": applied_at.isoformat().replace("+00:00", "Z"),
        "result_sha256": sha256_json(result),
    }
    atomic_write_json(current_path, applied)
    append_jsonl(durable_schedule_root(plan_dir, schedule_id) / "tick-events.jsonl", {
        "schema_version": SCHEMA_VERSION,
        "event": "tick_applied",
        **applied,
    })
    return applied


def command_run_durable_tick(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    require_controller_not_stopped(plan_dir)
    require_durable_autonomy_eligibility(plan_dir)
    observed_at = parse_utc(args.observed_at) if args.observed_at else datetime.now(timezone.utc)
    schedule_root = durable_schedule_root(plan_dir, args.schedule_id)
    with durable_loop_lock(plan_dir):
        pointer = read_json(schedule_root / "current.json")
        if pointer.get("active") is not True:
            raise ContractError("durable schedule is inactive")
        contract = read_json(Path(pointer["schedule_contract_path"]))
        runtime = read_json(schedule_root / "runtime.json")
        due_at = parse_utc(runtime["next_due_at"])
        if observed_at < due_at:
            return {"ok": True, "due": False, "next_due_at": runtime["next_due_at"]}
        tick_id = f"tick_{sha256_json({'schedule_id': args.schedule_id, 'due_at': runtime['next_due_at']})}"
        claim_result = claim_tick_locked(
            plan_dir, args.schedule_id, tick_id, observed_at, contract["lease_seconds"],
        )
        if claim_result.get("already_claimed"):
            return {"ok": True, "due": True, **claim_result}
        if claim_result.get("already_applied"):
            jitter = 0
            if contract["jitter_seconds"]:
                jitter = int(hashlib.sha256(tick_id.encode()).hexdigest(), 16) % (
                    contract["jitter_seconds"] + 1
                )
            next_due = due_at + timedelta(seconds=contract["interval_seconds"] + jitter)
            runtime.update({
                "last_tick_at": claim_result["claim"]["applied_at"],
                "last_tick_id": tick_id,
                "next_due_at": next_due.isoformat().replace("+00:00", "Z"),
                "updated_at": observed_at.isoformat().replace("+00:00", "Z"),
            })
            atomic_write_json(schedule_root / "runtime.json", runtime)
            return {
                "ok": True,
                "due": True,
                "reconciled_applied_tick": True,
                "next_due_at": runtime["next_due_at"],
                **claim_result,
            }
        claim = claim_result["claim"]
    frontier_recovery = recover_one_due_frontier_retry(plan_dir)
    advanced = command_advance_durable_plan(argparse.Namespace(plan_dir=str(plan_dir)))
    advanced["frontier_quota_recovery"] = frontier_recovery
    with durable_loop_lock(plan_dir):
        mark_tick_applied(
            plan_dir, args.schedule_id, tick_id, claim["claim_id"], advanced, observed_at,
        )
        if getattr(args, "simulate_crash_after_tick_apply", False):
            raise ContractError("simulated crash after durable tick apply")
        jitter = 0
        if contract["jitter_seconds"]:
            jitter = int(hashlib.sha256(tick_id.encode()).hexdigest(), 16) % (
                contract["jitter_seconds"] + 1
            )
        next_due = due_at + timedelta(seconds=contract["interval_seconds"] + jitter)
        runtime.update({
            "last_tick_at": observed_at.isoformat().replace("+00:00", "Z"),
            "last_tick_id": tick_id,
            "next_due_at": next_due.isoformat().replace("+00:00", "Z"),
            "updated_at": observed_at.isoformat().replace("+00:00", "Z"),
        })
        atomic_write_json(schedule_root / "runtime.json", runtime)
    return {
        "ok": True,
        "due": True,
        "tick_id": tick_id,
        "claim_id": claim["claim_id"],
        "next_due_at": runtime["next_due_at"],
        "advance": advanced,
    }


def command_guardian_observe(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    if not 1 <= args.stale_seconds <= 86400:
        raise ContractError("stale_seconds must be between 1 and 86400")
    observation_path = Path(args.observation).resolve()
    observation = read_json(observation_path)
    validate_schema(observation, read_json(GUARDIAN_OBSERVATION_SCHEMA))
    if observation.get("plan_id") != plan_identity(plan_dir):
        raise ContractError("guardian observation belongs to another plan")
    observed_at = parse_utc(observation["observed_at"])
    proposals: list[dict[str, Any]] = []
    if observed_at > parse_utc(observation["schedule"]["next_due_at"]):
        proposals.append({
            "action": "reconcile_tick",
            "schedule_id": observation["schedule"]["schedule_id"],
            "authority": "controller_validation_required",
        })
    for worker in observation["workers"]:
        if worker["status"] != "RUNNING":
            continue
        if (observed_at - parse_utc(worker["updated_at"])).total_seconds() > args.stale_seconds:
            proposals.append({
                "action": "record_runtime_stall",
                "worker_run_id": worker["run_id"],
                "authority": "deterministic_controller_policy",
            })
    body = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": observation["plan_id"],
        "observation_sha256": sha256_file(observation_path),
        "observed_at": observation["observed_at"],
        "proposals": proposals,
        "research_content_access": False,
        "lifecycle_authority": False,
        "policy": {"stale_seconds": args.stale_seconds},
    }
    proposal_id = f"guardian_{sha256_json(body)}"
    record = {**body, "proposal_id": proposal_id}
    target = durable_root(plan_dir) / "guardian" / "proposals" / f"{proposal_id}.json"
    atomic_write_json(target, record, immutable=True)
    return {"ok": True, "proposal_path": str(target), **record}


def command_apply_guardian_proposal(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    proposal_path = Path(args.proposal).resolve()
    root = (durable_root(plan_dir) / "guardian" / "proposals").resolve()
    try:
        proposal_path.relative_to(root)
    except ValueError as exc:
        raise ContractError("guardian proposal is outside canonical state") from exc
    proposal = read_json(proposal_path)
    body = {key: value for key, value in proposal.items() if key != "proposal_id"}
    if proposal.get("proposal_id") != f"guardian_{sha256_json(body)}":
        raise ContractError("guardian proposal identity mismatch")
    if proposal_path != root / f"{proposal['proposal_id']}.json":
        raise ContractError("guardian proposal path mismatch")
    if not 0 <= args.action_index < len(proposal.get("proposals", [])):
        raise ContractError("guardian proposal action index is out of range")
    action = proposal["proposals"][args.action_index]
    application_path = (
        durable_root(plan_dir) / "guardian" / "applied"
        / f"{proposal['proposal_id']}.{args.action_index}.json"
    )
    if application_path.exists():
        return {"ok": True, "idempotent": True, **read_json(application_path)}
    if action.get("action") == "record_runtime_stall":
        run_id = action.get("worker_run_id")
        status = read_json(worker_status_path(plan_dir, run_id))
        observed_at = parse_utc(proposal["observed_at"])
        updated_at = parse_utc(status.get("updated_at") or status.get("started_at"))
        if (
            status.get("status") != "RUNNING"
            or (observed_at - updated_at).total_seconds() <= proposal["policy"]["stale_seconds"]
        ):
            raise ContractError("guardian runtime-stall proposal is no longer valid")
        result = command_record_failure(argparse.Namespace(
            plan_dir=str(plan_dir),
            failure_class="runtime_stall",
            fingerprint=f"guardian:{proposal['proposal_id']}:{run_id}",
            source="guardian-controller-policy",
        ))
    elif action.get("action") == "reconcile_tick":
        result = command_run_durable_tick(argparse.Namespace(
            plan_dir=str(plan_dir),
            schedule_id=action.get("schedule_id"),
            observed_at=proposal["observed_at"],
            simulate_crash_after_tick_apply=False,
        ))
    else:
        raise ContractError("guardian proposal action is not registered")
    application = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "proposal_id": proposal["proposal_id"],
        "action_index": args.action_index,
        "action": action["action"],
        "result": result,
        "controller_policy": "guardian-recovery-v1",
        "applied_at": utc_now(),
    }
    atomic_write_json(application_path, application, immutable=True)
    return {"ok": True, "application_receipt": str(application_path), **application}


def command_guardian_validate_lifecycle(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    if args.action not in {"pause", "resume", "stop"}:
        raise ContractError("guardian lifecycle action is not allowed")
    receipt = validate_applied_action_receipt(
        plan_dir, Path(args.authorization).resolve(), args.action,
    )
    event = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_identity(plan_dir),
        "action": args.action,
        "record_id": receipt["record_id"],
        "record_sha256": receipt["record_sha256"],
        "guardian_authority": "validated_pre_authorized_only",
        "validated_at": utc_now(),
    }
    append_jsonl_once(
        durable_root(plan_dir) / "guardian" / "lifecycle-audit.jsonl",
        "record_id", receipt["record_id"], event,
    )
    return {"ok": True, "applied_by": "controller", "event": event}


def normalize_owned_path(plan_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = plan_dir / path
    path = path.resolve()
    try:
        path.relative_to(plan_dir)
    except ValueError as exc:
        raise ContractError("resource path is outside plan directory") from exc
    return path


def command_remove_resource(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    manifest = read_json(plan_dir / "resource_manifest.json")
    if manifest.get("plan_id") != plan_identity(plan_dir):
        raise ContractError("resource manifest plan mismatch")
    resources = manifest.get("resources", [])
    resource = next((item for item in resources if isinstance(item, dict) and item.get("resource_id") == args.resource_id), None)
    if resource is None:
        raise ContractError("resource_id is not in the manifest")
    if resource.get("ephemeral") is not True or resource.get("run_scoped", True) is not True:
        raise ContractError("only ephemeral run-scoped resources can be removed")
    raw_resource_path = Path(str(resource.get("path", "")))
    if not raw_resource_path.is_absolute():
        raw_resource_path = plan_dir / raw_resource_path
    if raw_resource_path.is_symlink():
        raise ContractError("resource must be an existing regular non-symlink file")
    path = normalize_owned_path(plan_dir, str(raw_resource_path))
    generation = str(resource.get("ownership_generation", resource.get("ownership_nonce", "")))
    expected_token = hashlib.sha256(f"{manifest['plan_id']}\0{path}\0{generation}".encode()).hexdigest()
    if not hmac.compare_digest(args.ownership_token, expected_token):
        raise ContractError("ownership token mismatch")
    authorization = read_json(Path(args.authorization).resolve())
    if authorization.get("action") != "cleanup_resource" or authorization.get("plan_id") != manifest["plan_id"]:
        raise ContractError("cleanup authorization is invalid")
    if authorization.get("resource_id") != args.resource_id:
        raise ContractError("cleanup authorization resource mismatch")
    authorization_path = plan_dir / "state" / "cleanup_authorizations" / f"{authorization.get('record_id', '')}.json"
    if authorization_path.resolve() != Path(args.authorization).resolve():
        raise ContractError("cleanup authorization must be a stored applied receipt")
    audit_path = plan_dir / "state" / "human_action_audit.jsonl"
    audit_entries = [
        strict_json_loads(line) for line in audit_path.read_text().splitlines() if line.strip()
    ] if audit_path.exists() else []
    audit = next((item for item in audit_entries if item.get("record_id") == authorization.get("record_id")), None)
    if audit is None or any(
        audit.get(field) != authorization.get(field)
        for field in ("plan_id", "action", "record_id", "record_sha256", "resource_id")
    ):
        raise ContractError("cleanup authorization does not match the authenticated audit")
    journal_path = plan_dir / "state" / "cleanup_journal" / f"{authorization['record_id']}.json"
    journal = read_json(journal_path) if journal_path.exists() else None
    if journal and journal.get("operation_id") != getattr(args, "operation_id", None):
        raise ContractError("cleanup recovery operation identity mismatch")
    if journal and journal.get("phase") == "COMMITTED":
        if not getattr(args, "operation_id", None):
            raise ContractError("cleanup authorization was already consumed")
        if path.exists() or path.is_symlink():
            raise ContractError("cleanup authorization was already consumed")
        if (
            journal.get("plan_id") != manifest["plan_id"]
            or journal.get("resource_id") != args.resource_id
            or journal.get("path") != str(path)
            or journal.get("authorization_sha256") != sha256_file(Path(args.authorization).resolve())
            or not isinstance(journal.get("receipt"), dict)
        ):
            raise ContractError("committed cleanup invocation mismatch")
        return {"ok": True, "idempotent": True, "recovered": True, "receipt": journal["receipt"]}
    if not path.is_file():
        if journal and journal.get("phase") == "PREPARED" and journal.get("path") == str(path):
            if journal.get("authorization_sha256") != sha256_file(Path(args.authorization).resolve()):
                raise ContractError("prepared cleanup authorization changed")
            receipt = {
                "schema_version": 1, "plan_id": manifest["plan_id"], "resource_id": args.resource_id,
                "path": str(path), "ownership_generation": generation,
                "content_sha256": journal["content_sha256"], "resource_identity": journal["resource_identity"],
                "authorization_record_id": authorization["record_id"], "removed_at": utc_now(),
            }
            append_jsonl_once(
                plan_dir / "state" / "cleanup_receipts.jsonl",
                "authorization_record_id", authorization["record_id"], receipt,
            )
            journal.update({"phase": "COMMITTED", "committed_at": utc_now(), "receipt": receipt})
            atomic_write_json(journal_path, journal)
            return {"ok": True, "recovered": True, "receipt": receipt}
        raise ContractError("resource must be an existing regular non-symlink file")
    details = authorization.get("details", {})
    stat = path.stat()
    current_identity = f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}"
    if (
        details.get("resource_path") != str(path)
        or details.get("ownership_generation") != generation
        or details.get("ownership_token") != expected_token
        or details.get("content_sha256") != sha256_file(path)
        or details.get("resource_identity") != current_identity
    ):
        raise ContractError("cleanup authorization does not bind the current resource generation")
    if journal is None:
        journal = {
            "schema_version": 1, "phase": "PREPARED", "plan_id": manifest["plan_id"],
            "resource_id": args.resource_id, "path": str(path), "resource_identity": current_identity,
            "content_sha256": sha256_file(path), "ownership_generation": generation,
            "authorization_record_id": authorization["record_id"],
            "authorization_sha256": sha256_file(Path(args.authorization).resolve()),
            "operation_id": getattr(args, "operation_id", None),
            "prepared_at": utc_now(),
        }
        atomic_write_json(journal_path, journal)
    elif any(journal.get(key) != value for key, value in {
        "plan_id": manifest["plan_id"], "resource_id": args.resource_id, "path": str(path),
        "resource_identity": current_identity, "content_sha256": sha256_file(path),
        "ownership_generation": generation, "authorization_record_id": authorization["record_id"],
    }.items()):
        raise ContractError("prepared cleanup no longer matches the current resource generation")
    path.unlink()
    if getattr(args, "simulate_crash_after", None) == "unlink":
        raise ContractError("simulated crash after resource unlink")
    receipt = {
        "schema_version": 1, "plan_id": manifest["plan_id"], "resource_id": args.resource_id,
        "path": str(path), "ownership_generation": generation,
        "content_sha256": journal["content_sha256"], "resource_identity": journal["resource_identity"],
        "authorization_record_id": authorization["record_id"], "removed_at": utc_now(),
    }
    append_jsonl(plan_dir / "state" / "cleanup_receipts.jsonl", receipt)
    journal.update({"phase": "COMMITTED", "committed_at": utc_now(), "receipt": receipt})
    atomic_write_json(journal_path, journal)
    return {"ok": True, "receipt": receipt}


def frontier_root(plan_dir: Path) -> Path:
    return plan_dir / "state" / "frontier"


def empty_frontier_budget_image() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "reserved_calls": 0,
        "reserved_input_tokens": 0,
        "reserved_output_tokens": 0,
        "request_ids": [],
    }


def effective_frontier_limits(
    policy: dict[str, Any], ledger: dict[str, Any],
) -> dict[str, int]:
    base = policy["frontier_escalation"]
    additions = ledger.get("authorized_capacity", {})
    values = {
        "max_calls": base["max_calls"] + require_non_negative_int(
            additions.get("calls", 0), "authorized_capacity.calls",
        ),
        "max_input_tokens": base["max_input_tokens"]
        + require_non_negative_int(
            additions.get("input_tokens", 0),
            "authorized_capacity.input_tokens",
        ),
        "max_output_tokens": base["max_output_tokens"]
        + require_non_negative_int(
            additions.get("output_tokens", 0),
            "authorized_capacity.output_tokens",
        ),
    }
    return values


def request_dir(plan_dir: Path, request_id: str) -> Path:
    if not REQUEST_ID_RE.fullmatch(request_id):
        raise ContractError("invalid request_id")
    return frontier_root(plan_dir) / "requests" / request_id


def status_path(plan_dir: Path, request_id: str) -> Path:
    return request_dir(plan_dir, request_id) / "status.json"


def transition(plan_dir: Path, request_id: str, state: str, **extra: Any) -> dict[str, Any]:
    if state not in STATES:
        raise ContractError(f"unknown frontier state: {state}")
    path = status_path(plan_dir, request_id)
    previous = read_json(path) if path.exists() else {}
    value = {**previous, "schema_version": SCHEMA_VERSION, "request_id": request_id, "state": state, "updated_at": utc_now(), **extra}
    atomic_write_json(path, value)
    append_jsonl(frontier_root(plan_dir) / "events.jsonl", {"ts": utc_now(), "request_id": request_id, "state": state, **extra})
    return value


@contextmanager
def budget_lock(plan_dir: Path) -> Iterator[None]:
    root = frontier_root(plan_dir)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".budget.lock"
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def reserve_budget(plan_dir: Path, request: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    root = frontier_root(plan_dir)
    ledger_path = root / "budget.json"
    requested = request["budget_reservation"]
    with budget_lock(plan_dir):
        ledger = (
            read_json(ledger_path) if ledger_path.exists()
            else empty_frontier_budget_image()
        )
        if request["request_id"] in ledger["request_ids"]:
            return ledger
        limits = effective_frontier_limits(policy, ledger)
        next_calls = ledger["reserved_calls"] + require_non_negative_int(requested["call"], "budget_reservation.call")
        next_input = ledger["reserved_input_tokens"] + require_non_negative_int(requested["max_input_tokens"], "budget_reservation.max_input_tokens")
        next_output = ledger["reserved_output_tokens"] + require_non_negative_int(requested["max_output_tokens"], "budget_reservation.max_output_tokens")
        if next_calls > limits["max_calls"] or next_input > limits["max_input_tokens"] or next_output > limits["max_output_tokens"]:
            raise ContractError("frontier budget exhausted")
        ledger.update({
            "reserved_calls": next_calls,
            "reserved_input_tokens": next_input,
            "reserved_output_tokens": next_output,
            "request_ids": [*ledger["request_ids"], request["request_id"]],
            "updated_at": utc_now(),
        })
        atomic_write_json(ledger_path, ledger)
        return ledger


def _staged_release_journal_path(
    plan_dir: Path, dispatch_id: str, generation: int,
) -> Path:
    return (
        staged_root(plan_dir) / "capacity-release-journals"
        / f"{dispatch_id}.{generation}.json"
    )


def _staged_release_roll_image(
    path: Path,
    images: dict[str, Any],
    label: str,
    *,
    released_absent: bool = False,
) -> None:
    current = read_json(path) if path.exists() else None
    current_sha = sha256_json(current)
    if current_sha == images["reserved_sha256"]:
        if released_absent:
            path.unlink()
        else:
            atomic_write_json(path, images["released"])
    elif current_sha != images["released_sha256"]:
        raise ContractError(f"staged release {label} image is irreconcilable")


def _finish_staged_release_locked(
    plan_dir: Path, journal_path: Path, journal: dict[str, Any],
) -> dict[str, Any]:
    """Roll one proven-unstarted combined reservation to RELEASED."""
    dispatch_id = journal["dispatch_id"]
    global_path = frontier_root(plan_dir) / "budget.json"
    capacity_path = staged_root(plan_dir) / "capacity-ledger.json"
    usage_path = Path(journal["usage_path"])
    marker_path = (
        staged_root(plan_dir) / "dispatch-reservations"
        / f"{dispatch_id}.json"
    )
    combined_path = (
        staged_root(plan_dir) / "capacity-journals"
        / f"{dispatch_id}.json"
    )
    boundaries = (
        ("global", global_path, False, "GLOBAL"),
        ("usage", usage_path, False, "USAGE"),
        ("staged", capacity_path, False, "CAPACITY"),
        ("marker", marker_path, True, "MARKER"),
        ("combined", combined_path, False, "COMBINED"),
    )
    # Validate every frozen projection before changing any of them.  A late
    # conflict must not partially reopen capacity or remove the marker.
    for label, path, _, _ in boundaries:
        current = read_json(path) if path.exists() else None
        if sha256_json(current) not in {
            journal[label]["reserved_sha256"],
            journal[label]["released_sha256"],
        }:
            raise ContractError(
                f"staged release {label} image is irreconcilable"
            )
    for label, path, released_absent, fault_name in boundaries:
        _staged_release_roll_image(
            path, journal[label], label, released_absent=released_absent,
        )
        if os.environ.get(
            f"HARNESS_FAULT_AFTER_STAGED_RELEASE_{fault_name}"
        ) == "1":
            os._exit(89)
    _staged_ensure_audit_once_locked(
        plan_dir,
        "model_dispatch_released_unstarted",
        {
            "dispatch_id": dispatch_id,
            "reservation_generation": journal["reservation_generation"],
        },
        {
            "send_claim": journal["send_claim"],
            "checkpoint": journal["checkpoint"],
            "reason": "transport_not_started",
        },
    )
    journal["phase"] = "RELEASED"
    journal["released_at"] = journal.get("released_at", utc_now())
    atomic_write_json(journal_path, journal)
    return journal


def reserve_frontier_and_staged_budget(
    plan_dir: Path, request: dict[str, Any], policy: dict[str, Any],
) -> dict[str, Any]:
    """Commit global and staged call capacity under one recoverable transaction."""
    if not staged_is_active(plan_dir):
        return reserve_budget(plan_dir, request, policy)
    checkpoint = (
        request["checkpoint"]
        if request["checkpoint"] in {
            "CP-01", "CP-02", "CP-03", "CP-04", "STAGE-REVIEW",
        }
        else None
    )
    retry_lineage = request.get("retry_lineage")
    is_checkpoint_retry = retry_lineage is not None
    dispatch_id = request["request_id"]
    staged_reservation = (
        staged_root(plan_dir) / "dispatch-reservations" / f"{dispatch_id}.json"
    )
    journal_path = (
        staged_root(plan_dir) / "capacity-journals" / f"{dispatch_id}.json"
    )
    with staged_transaction_lock(plan_dir):
        with budget_lock(plan_dir):
            global_path = frontier_root(plan_dir) / "budget.json"
            capacity_path = staged_root(plan_dir) / "capacity-ledger.json"
            state = staged_load_state(plan_dir)
            usage_path = (
                staged_stage_dir(plan_dir, state["active_stage_id"])
                / "usage-ledger.json"
            )
            requested = request["budget_reservation"]
            previous_release: dict[str, Any] | None = None
            if journal_path.exists():
                journal = read_json(journal_path)
                if (
                    journal.get("dispatch_id") != dispatch_id
                    or journal.get("checkpoint") != checkpoint
                    or not all(
                        name in journal
                        for name in ("global", "staged", "usage", "marker_after")
                    )
                ):
                    raise ContractError(
                        "combined capacity journal correlation mismatch"
                    )
                generation = require_non_negative_int(
                    journal.get("reservation_generation", 1),
                    "reservation_generation",
                )
                if generation < 1:
                    raise ContractError("reservation_generation must be positive")
                release_path = _staged_release_journal_path(
                    plan_dir, dispatch_id, generation,
                )
                if release_path.exists():
                    release_journal = read_json(release_path)
                    if release_journal.get("phase") == "PREPARED":
                        _finish_staged_release_locked(
                            plan_dir, release_path, release_journal,
                        )
                        journal = read_json(journal_path)
                if journal.get("phase") == "RELEASED":
                    if (
                        not release_path.exists()
                        or read_json(release_path).get("phase") != "RELEASED"
                    ):
                        raise ContractError(
                            "released combined capacity lacks its release journal"
                        )
                    previous_release = journal
            ledger = (
                read_json(global_path) if global_path.exists()
                else empty_frontier_budget_image()
            )
            if journal_path.exists() and previous_release is None:
                journal = read_json(journal_path)
                if (
                    journal.get("dispatch_id") != dispatch_id
                    or journal.get("checkpoint") != checkpoint
                    or not all(
                        name in journal
                        for name in ("global", "staged", "usage", "marker_after")
                    )
                ):
                    raise ContractError("combined capacity journal correlation mismatch")
            else:
                if dispatch_id in ledger["request_ids"] or staged_reservation.exists():
                    raise ContractError(
                        "combined capacity state exists without its recovery journal"
                    )
                staged_require_preflight(plan_dir)
                limits = effective_frontier_limits(policy, ledger)
                global_after = dict(ledger)
                global_after.update({
                    "reserved_calls": ledger["reserved_calls"] + requested["call"],
                    "reserved_input_tokens": (
                        ledger["reserved_input_tokens"]
                        + requested["max_input_tokens"]
                    ),
                    "reserved_output_tokens": (
                        ledger["reserved_output_tokens"]
                        + requested["max_output_tokens"]
                    ),
                    "request_ids": [*ledger["request_ids"], dispatch_id],
                    "updated_at": utc_now(),
                })
                if (
                    global_after["reserved_calls"] > limits["max_calls"]
                    or global_after["reserved_input_tokens"]
                    > limits["max_input_tokens"]
                    or global_after["reserved_output_tokens"]
                    > limits["max_output_tokens"]
                ):
                    raise ContractError("frontier budget exhausted")
                capacity = read_json(capacity_path)
                staged_validate_capacity(capacity)
                if capacity.get("schema_version") == 2 and checkpoint is None:
                    raise ContractError(
                        "capacity v2 rejects an unclassified frontier dispatch"
                    )
                # v2 routes terminal review to its own non-fungible slot.  A
                # legacy v1 plan retains its historical generic-call replay.
                legacy_checkpoint = (
                    None
                    if capacity.get("schema_version") == 1
                    and checkpoint in {"CP-03", "STAGE-REVIEW"}
                    else checkpoint
                )
                if is_checkpoint_retry:
                    retry = capacity["retry_budget"]
                    if retry["remaining_attempts"] < 1:
                        raise ContractError("frontier retry budget exhausted")
                    if retry["per_attempt_call_limit"] < requested["call"]:
                        raise ContractError("frontier retry call limit exceeded")
                    capacity_after = json.loads(json.dumps(capacity))
                    capacity_after["retry_budget"]["remaining_attempts"] -= 1
                    staged_validate_capacity(capacity_after)
                else:
                    capacity_after = staged_capacity_reserve_image(
                        capacity, legacy_checkpoint,
                    )
                usage = read_json(usage_path)
                usage_after = json.loads(json.dumps(usage))
                usage_id = f"frontier:{dispatch_id}"
                if usage_id in usage["reservation_ids"]:
                    raise ContractError("stage usage exists without combined journal")
                controller_path = plan_dir / "state" / "controller.json"
                if (
                    controller_path.exists()
                    and read_json(controller_path).get("status")
                    in {"paused", "stopped"}
                ):
                    raise ContractError(
                        "stage dispatch blocked by canonical human lifecycle state"
                    )
                elapsed = (
                    datetime.now(timezone.utc) - parse_utc(usage["started_at"])
                ).total_seconds()
                if usage.get("stop_reason") is not None or (
                    state["state"] == "PAUSED"
                    and request.get("checkpoint") != "STAGE-REVIEW"
                ):
                    raise ContractError(
                        "stage is stopped pending canonical human reauthorization"
                    )
                if elapsed > usage["limits"]["time_seconds"]:
                    usage["stop_reason"] = "deadline"
                    atomic_write_json(usage_path, usage)
                    state["state"] = "PAUSED"
                    atomic_write_json(staged_state_path(plan_dir), state)
                    raise ContractError("stage time budget exhausted")
                if (
                    usage["used"]["review_tokens"]
                    + requested["max_output_tokens"]
                    > usage["limits"]["review_tokens"]
                ):
                    usage["stop_reason"] = "review_tokens_exhausted"
                    atomic_write_json(usage_path, usage)
                    state["state"] = "PAUSED"
                    atomic_write_json(staged_state_path(plan_dir), state)
                    raise ContractError("stage review_tokens budget exhausted")
                usage_after["used"]["review_tokens"] += requested["max_output_tokens"]
                usage_after["reservation_ids"].append(usage_id)
                usage_after["updated_at"] = utc_now()
                marker_after = {
                    "schema_version": 1,
                    "dispatch_id": dispatch_id,
                    "checkpoint": checkpoint,
                    "logical_request_id": (
                        retry_lineage["logical_request_id"]
                        if is_checkpoint_retry else dispatch_id
                    ),
                    "retry_attempt": (
                        retry_lineage["retry_attempt"]
                        if is_checkpoint_retry else 0
                    ),
                    **staged_capacity_projection(capacity_after),
                    "reserved_at": utc_now(),
                }
                journal = {
                    "schema_version": 1, "phase": "PREPARED",
                    "dispatch_id": dispatch_id, "checkpoint": checkpoint,
                    "logical_request_id": (
                        retry_lineage["logical_request_id"]
                        if is_checkpoint_retry else dispatch_id
                    ),
                    "retry_attempt": (
                        retry_lineage["retry_attempt"]
                        if is_checkpoint_retry else 0
                    ),
                    "reservation_generation": (
                        previous_release.get("reservation_generation", 1) + 1
                        if previous_release is not None else 1
                    ),
                    "prior_release_sha256": (
                        sha256_json(previous_release)
                        if previous_release is not None else None
                    ),
                    "usage_path": str(usage_path),
                    "global": {
                        "before_exists": global_path.exists(),
                        "before": ledger, "before_sha256": sha256_json(ledger),
                        "after": global_after,
                        "after_sha256": sha256_json(global_after),
                    },
                    "staged": {
                        "before_exists": capacity_path.exists(),
                        "before": capacity,
                        "before_sha256": sha256_json(capacity),
                        "after": capacity_after,
                        "after_sha256": sha256_json(capacity_after),
                    },
                    "usage": {
                        "before_exists": usage_path.exists(),
                        "before": usage, "before_sha256": sha256_json(usage),
                        "after": usage_after,
                        "after_sha256": sha256_json(usage_after),
                    },
                    "marker_after": marker_after,
                    "marker_after_sha256": sha256_json(marker_after),
                    "prepared_at": utc_now(),
                }
                atomic_write_json(journal_path, journal)

            def roll_forward(path: Path, images: dict[str, Any], label: str) -> None:
                if not path.exists():
                    if images.get("before_exists") is not False:
                        raise ContractError(
                            f"combined capacity {label} image is missing"
                        )
                    current = images["before"]
                else:
                    current = read_json(path)
                current_sha = sha256_json(current)
                if current_sha == images["before_sha256"]:
                    atomic_write_json(path, images["after"])
                elif current_sha != images["after_sha256"]:
                    raise ContractError(
                        f"combined capacity {label} image is irreconcilable"
                    )

            roll_forward(global_path, journal["global"], "global")
            if os.environ.get("HARNESS_FAULT_AFTER_COMBINED_GLOBAL") == "1":
                raise ContractError("simulated crash after combined global reservation")
            roll_forward(usage_path, journal["usage"], "usage")
            roll_forward(capacity_path, journal["staged"], "staged")
            if os.environ.get(
                "HARNESS_FAULT_AFTER_COMBINED_STAGED_CAPACITY"
            ) == "1":
                os._exit(86)
            if staged_reservation.exists():
                if read_json(staged_reservation) != journal["marker_after"]:
                    raise ContractError(
                        "combined capacity reservation marker is irreconcilable"
                    )
            else:
                atomic_write_json(
                    staged_reservation, journal["marker_after"], immutable=True,
                )
            audit_path = staged_root(plan_dir) / "audit.jsonl"
            audit_has_reservation = audit_path.exists() and any(
                strict_json_loads(line).get("event") == "model_dispatch_reserved"
                and strict_json_loads(line).get("dispatch_id") == dispatch_id
                and strict_json_loads(line).get(
                    "reservation_generation", 1,
                ) == journal["reservation_generation"]
                for line in audit_path.read_text().splitlines()
                if line.strip()
            )
            if not audit_has_reservation:
                _staged_append_audit_locked(plan_dir, "model_dispatch_reserved", {
                    "dispatch_id": dispatch_id,
                    "reservation_generation": journal[
                        "reservation_generation"
                    ],
                    "stage_id": state["active_stage_id"],
                    "checkpoint": checkpoint,
                    **staged_capacity_projection(journal["staged"]["after"]),
                })
            _staged_reconcile_audit_revision_locked(plan_dir)
            journal.update({
                "phase": "COMMITTED",
                "global_after_sha256": sha256_json(journal["global"]["after"]),
                "staged_after_sha256": sha256_json(journal["staged"]["after"]),
                "committed_at": utc_now(),
            })
            atomic_write_json(journal_path, journal)
            return read_json(global_path)


def release_unstarted_frontier_budget(
    plan_dir: Path,
    request: dict[str, Any],
    send_claim: str,
    error: OSError,
) -> dict[str, Any]:
    """Recover only a reservation proven not to have started a subprocess."""
    root = frontier_root(plan_dir)
    ledger_path = root / "budget.json"
    run_dir = request_dir(plan_dir, request["request_id"])
    recovery_dir = run_dir / "budget-releases"
    intent_path = recovery_dir / f"{send_claim}.intent.json"
    receipt_path = recovery_dir / f"{send_claim}.json"
    requested = request["budget_reservation"]
    intent = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request["request_id"],
        "reason": "transport_not_started",
        "send_claim": send_claim,
        "reservation": requested,
    }
    combined_path = (
        staged_root(plan_dir) / "capacity-journals"
        / f"{request['request_id']}.json"
    )
    if staged_is_active(plan_dir) and combined_path.exists():
        with staged_transaction_lock(plan_dir):
            with budget_lock(plan_dir):
                if intent_path.exists():
                    if read_json(intent_path) != intent:
                        raise ContractError(
                            "budget release intent correlation mismatch"
                        )
                else:
                    atomic_write_json(intent_path, intent, immutable=True)
                combined = read_json(combined_path)
                generation = require_non_negative_int(
                    combined.get("reservation_generation", 1),
                    "reservation_generation",
                )
                if generation < 1:
                    raise ContractError("reservation_generation must be positive")
                journal_path = _staged_release_journal_path(
                    plan_dir, request["request_id"], generation,
                )
                if journal_path.exists():
                    journal = read_json(journal_path)
                    if (
                        journal.get("dispatch_id") != request["request_id"]
                        or journal.get("send_claim") != send_claim
                        or journal.get("reservation_generation") != generation
                    ):
                        raise ContractError(
                            "staged release journal correlation mismatch"
                        )
                else:
                    if combined.get("phase") != "COMMITTED":
                        raise ContractError(
                            "staged release requires a committed reservation"
                        )
                    global_path = root / "budget.json"
                    capacity_path = staged_root(plan_dir) / "capacity-ledger.json"
                    usage_path = Path(
                        combined.get(
                            "usage_path",
                            str(
                                staged_stage_dir(
                                    plan_dir,
                                    staged_load_state(plan_dir)[
                                        "active_stage_id"
                                    ],
                                ) / "usage-ledger.json"
                            ),
                        )
                    )
                    marker_path = (
                        staged_root(plan_dir) / "dispatch-reservations"
                        / f"{request['request_id']}.json"
                    )
                    global_reserved = read_json(global_path)
                    capacity_reserved = read_json(capacity_path)
                    usage_reserved = read_json(usage_path)
                    marker_reserved = (
                        read_json(marker_path) if marker_path.exists() else None
                    )
                    usage_id = f"frontier:{request['request_id']}"
                    checkpoint = combined.get("checkpoint")
                    if (
                        request["request_id"]
                        not in global_reserved.get("request_ids", [])
                        or usage_id
                        not in usage_reserved.get("reservation_ids", [])
                        or marker_reserved != combined.get("marker_after")
                    ):
                        raise ContractError(
                            "staged release reserved projection mismatch"
                        )
                    global_released = json.loads(json.dumps(global_reserved))
                    global_released["reserved_calls"] -= requested["call"]
                    global_released["reserved_input_tokens"] -= requested[
                        "max_input_tokens"
                    ]
                    global_released["reserved_output_tokens"] -= requested[
                        "max_output_tokens"
                    ]
                    global_released["request_ids"] = [
                        item for item in global_released["request_ids"]
                        if item != request["request_id"]
                    ]
                    if any(
                        global_released[field] < 0
                        for field in (
                            "reserved_calls",
                            "reserved_input_tokens",
                            "reserved_output_tokens",
                        )
                    ):
                        raise ContractError(
                            "staged release would make global budget negative"
                        )
                    global_released["updated_at"] = utc_now()
                    legacy_checkpoint = (
                        None
                        if capacity_reserved.get("schema_version") == 1
                        and checkpoint in {"CP-03", "STAGE-REVIEW"}
                        else checkpoint
                    )
                    if require_non_negative_int(
                        combined.get("retry_attempt", 0), "retry_attempt",
                    ) > 0:
                        capacity_released = json.loads(
                            json.dumps(capacity_reserved)
                        )
                        capacity_released["retry_budget"][
                            "remaining_attempts"
                        ] += 1
                        staged_validate_capacity(capacity_released)
                    else:
                        capacity_released = staged_capacity_release_image(
                            capacity_reserved, legacy_checkpoint,
                        )
                    usage_released = json.loads(json.dumps(usage_reserved))
                    usage_released["used"]["review_tokens"] -= requested[
                        "max_output_tokens"
                    ]
                    usage_released["reservation_ids"] = [
                        item for item in usage_released["reservation_ids"]
                        if item != usage_id
                    ]
                    if usage_released["used"]["review_tokens"] < 0:
                        raise ContractError(
                            "staged release would make usage negative"
                        )
                    usage_released["updated_at"] = utc_now()
                    combined_released = json.loads(json.dumps(combined))
                    combined_released.update({
                        "phase": "RELEASED",
                        "release_send_claim": send_claim,
                        "released_at": utc_now(),
                    })

                    def release_images(
                        reserved: Any, released: Any,
                    ) -> dict[str, Any]:
                        return {
                            "reserved": reserved,
                            "reserved_sha256": sha256_json(reserved),
                            "released": released,
                            "released_sha256": sha256_json(released),
                        }

                    journal = {
                        "schema_version": 1,
                        "phase": "PREPARED",
                        "dispatch_id": request["request_id"],
                        "checkpoint": checkpoint,
                        "reservation_generation": generation,
                        "send_claim": send_claim,
                        "reason": "transport_not_started",
                        "usage_path": str(usage_path),
                        "global": release_images(
                            global_reserved, global_released,
                        ),
                        "staged": release_images(
                            capacity_reserved, capacity_released,
                        ),
                        "usage": release_images(
                            usage_reserved, usage_released,
                        ),
                        "marker": release_images(marker_reserved, None),
                        "combined": release_images(
                            combined, combined_released,
                        ),
                        "prepared_at": utc_now(),
                    }
                    atomic_write_json(journal_path, journal)
                    if os.environ.get(
                        "HARNESS_FAULT_AFTER_STAGED_RELEASE_PREPARED"
                    ) == "1":
                        os._exit(89)
                journal = _finish_staged_release_locked(
                    plan_dir, journal_path, journal,
                )
                receipt = {
                    **intent,
                    "error_class": type(error).__name__,
                    "reservation_generation": generation,
                    "release_journal_path": str(journal_path),
                    "release_journal_sha256": sha256_file(journal_path),
                    "ledger_before_sha256": journal["global"][
                        "reserved_sha256"
                    ],
                    "ledger_after_sha256": journal["global"][
                        "released_sha256"
                    ],
                    "released_at": journal["released_at"],
                }
                if receipt_path.exists():
                    prior = read_json(receipt_path)
                    if any(
                        prior.get(key) != receipt.get(key) for key in intent
                    ):
                        raise ContractError(
                            "budget release receipt correlation mismatch"
                        )
                    return prior
                atomic_write_json(receipt_path, receipt, immutable=True)
                return receipt
    with budget_lock(plan_dir):
        if intent_path.exists():
            if read_json(intent_path) != intent:
                raise ContractError("budget release intent correlation mismatch")
        else:
            atomic_write_json(intent_path, intent, immutable=True)
        ledger = read_json(ledger_path)
        before_sha256 = sha256_json(ledger)
        if request["request_id"] in ledger["request_ids"]:
            ledger["reserved_calls"] -= requested["call"]
            ledger["reserved_input_tokens"] -= requested["max_input_tokens"]
            ledger["reserved_output_tokens"] -= requested["max_output_tokens"]
            ledger["request_ids"] = [
                value for value in ledger["request_ids"]
                if value != request["request_id"]
            ]
            if any(
                ledger[field] < 0
                for field in (
                    "reserved_calls",
                    "reserved_input_tokens",
                    "reserved_output_tokens",
                )
            ):
                raise ContractError("budget release would make the ledger negative")
            ledger["updated_at"] = utc_now()
            atomic_write_json(ledger_path, ledger)
        elif not receipt_path.exists():
            # A durable intent plus an absent request ID is the crash-recovery
            # shape after the ledger update and before the receipt write.
            ledger = read_json(ledger_path)
        receipt = {
            **intent,
            "error_class": type(error).__name__,
            "ledger_before_sha256": before_sha256,
            "ledger_after_sha256": sha256_json(ledger),
            "released_at": utc_now(),
        }
        if receipt_path.exists():
            prior = read_json(receipt_path)
            if any(prior.get(key) != receipt.get(key) for key in intent):
                raise ContractError("budget release receipt correlation mismatch")
            return prior
        atomic_write_json(receipt_path, receipt, immutable=True)
        return receipt


def frontier_budget_is_reserved(plan_dir: Path, request_id: str) -> bool:
    ledger_path = frontier_root(plan_dir) / "budget.json"
    with budget_lock(plan_dir):
        if not ledger_path.exists():
            return False
        ledger = read_json(ledger_path)
        return request_id in ledger.get("request_ids", [])


def release_frontier_prelaunch_reservation(
    plan_dir: Path,
    request: dict[str, Any],
    failure: str,
) -> dict[str, Any] | None:
    """Release a durable reservation only while delivery is provably unstarted."""
    if not frontier_budget_is_reserved(plan_dir, request["request_id"]):
        return None
    claim_digest = hashlib.sha256(
        f"{request['request_id']}:{failure}".encode()
    ).hexdigest()[:32]
    return release_unstarted_frontier_budget(
        plan_dir,
        request,
        f"prelaunch-{claim_digest}",
        OSError(failure),
    )


def exact_worker_artifact_output_schema(
    declarations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compile declarations into the only accepted Worker proposal shape."""
    item_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["artifact_id", "path", "content", "sha256"],
        "properties": {
            "artifact_id": {
                "enum": [item["artifact_id"] for item in declarations],
            },
            "path": {"enum": [item["path"] for item in declarations]},
            "content": {"type": "string"},
            "sha256": {"const": "controller-compute"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["artifacts"],
        "properties": {
            "artifacts": {
                "type": "array", "items": item_schema,
                "minItems": len(declarations), "maxItems": len(declarations),
            },
        },
    }


def validate_stage_review_continuation_materials(
    plan_dir: Path,
    state: dict[str, Any],
    by_role: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Validate the exact Stage 2 draft before it enters the strong review."""
    if set(by_role) != STAGE_REVIEW_CONTINUATION_EVIDENCE_PROFILE:
        raise ContractError("STAGE-REVIEW continuation evidence is incomplete")
    paths = {role: Path(item["path"]).resolve() for role, item in by_role.items()}
    for role, path in paths.items():
        try:
            path.relative_to(plan_dir)
        except ValueError as exc:
            raise ContractError(
                f"STAGE-REVIEW {role} must be plan-owned"
            ) from exc
        validate_immutable_binding(path, by_role[role]["sha256"], role)
    envelope_path = paths["next_stage_envelope"]
    envelope = read_json(envelope_path)
    source_stage_id = state["active_stage_id"]
    source_decision = read_json(
        staged_stage_dir(plan_dir, source_stage_id) / "decision.json"
    )
    initial = validate_applied_action_receipt(
        plan_dir, Path(state["owner_authorization_path"]),
        state["owner_authorization_action"],
    )
    bounded = initial.get("details", {}).get("bounded_continuation_authority")
    if (
        not isinstance(bounded, dict)
        or bounded.get("max_automatic_crossings") != 1
        or bounded.get("silence_is_approval") is not False
        or bounded.get("allowed_stage_ids") != [envelope.get("stage_id")]
        or envelope.get("source_cycle_id") != source_stage_id
    ):
        raise ContractError(
            "next-stage draft is outside bounded initial continuation authority"
        )
    staged_validate_envelope(
        envelope, state["contract_version"],
        source_decision["resulting_incumbent_sha256"], first=False,
        plan_dir=plan_dir, require_manifest=True,
    )
    staged_validate_profile_envelope_compatibility(
        read_json(staged_root(plan_dir) / "evaluation-profile.json"), envelope,
    )
    raw_preflight = read_json(paths["next_stage_preflight_inputs"])
    required_preflight = {
        "verdict_truth_table", "statistical_design",
        "training_evaluation_matrix", "conditional_state_machine",
        "critical_path",
    }
    if envelope["stage_kind"] == "research" and envelope[
        "stage_budget_and_stop"
    ]["evaluation_calls"] == 0:
        required_preflight.add("source_manifest")
    if set(raw_preflight) != required_preflight:
        raise ContractError("next-stage preflight draft has an invalid closed shape")
    task = read_json(paths["next_stage_task_contract"])
    if (
        task.get("schema_version") != SCHEMA_VERSION
        or not isinstance(task.get("task_id"), str)
        or not task["task_id"]
        or not isinstance(task.get("instruction"), str)
        or not task["instruction"]
        or task.get("allowed_write_paths") != []
        or task.get("completion_check")
        != {"type": "output_schema", "assertion": "valid"}
    ):
        raise ContractError("next-stage task contract has an invalid closed shape")
    inputs = verify_manifest_items(task.get("inputs", []), base_dir=plan_dir)
    declarations = [
        normalize_declared_output(plan_dir, item)
        for item in task.get("artifact_outputs", [])
    ]
    allowed_tools = task.get("allowed_tools")
    if (
        not isinstance(allowed_tools, list)
        or any(not isinstance(value, str) for value in allowed_tools)
        or set(allowed_tools) - READ_ONLY_CLAUDE_TOOLS
    ):
        raise ContractError("next-stage task tools exceed the read-only Worker route")
    entry_policy_path = codex_host_entry_root(plan_dir) / "worker-session-policy.json"
    if entry_policy_path.is_file():
        entry_policy = read_json(entry_policy_path)
        if not set(allowed_tools).issubset(
            set(entry_policy["allowed_tool_ceiling"])
        ):
            raise ContractError(
                "next-stage task tools exceed the frozen session ceiling"
            )
    if task.get("output_schema") != exact_worker_artifact_output_schema(declarations):
        raise ContractError(
            "next-stage output schema must bind artifact IDs, paths, count, "
            "and literal controller-compute; Runtime binds declaration order"
        )
    if [item["path"] for item in inputs] != [
        item["path"] for item in task.get("inputs", [])
    ]:
        raise ContractError("next-stage task input order changed")
    return by_role


def command_create_request(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    policy = load_policy(plan_dir)
    if args.attempt < 1:
        raise ContractError("attempt must be at least 1")
    require_non_negative_int(args.max_input_tokens, "max_input_tokens")
    require_non_negative_int(args.max_output_tokens, "max_output_tokens")
    registry = CHECKPOINTS.get(args.checkpoint)
    if registry is None:
        raise ContractError(f"unregistered checkpoint: {args.checkpoint}")
    subtype = args.checkpoint_subtype
    if subtype not in registry["subtypes"]:
        raise ContractError(f"invalid subtype for {args.checkpoint}: {subtype}")
    expected_transition = DEPENDENT_TRANSITIONS.get((args.checkpoint, subtype))
    if (
        expected_transition is None
        or args.decision_required != expected_transition[0]
    ):
        raise ContractError(
            "decision_required does not match the registered checkpoint transition"
        )
    if args.checkpoint == "CP-03" and not pivot_eligibility(plan_dir)["eligible"]:
        raise ContractError("CP-03 requires distinct scientific pivot eligibility")
    if not 1 <= args.deadline_seconds <= 86400:
        raise ContractError("deadline_seconds must be between 1 and 86400")
    staged_review_state: dict[str, Any] | None = None
    if args.checkpoint == "STAGE-REVIEW":
        if not staged_is_active(plan_dir):
            raise ContractError(
                "STAGE-REVIEW requires active staged research and a canonical "
                "terminal stage report"
            )
        staged_review_state = staged_load_state(plan_dir)
        if staged_review_state["state"] == "CONTRACTED":
            raise ContractError(
                "STAGE-REVIEW is terminal-only; the current stage is CONTRACTED. "
                "Create CP-01 and apply approve_execution first"
            )
        if staged_review_state["state"] not in {"RECORDED", "PAUSED"}:
            raise ContractError(
                "STAGE-REVIEW requires a recorded terminal Gate decision and "
                "canonical stage report"
            )
        canonical_report = (
            staged_stage_dir(plan_dir, staged_review_state["active_stage_id"])
            / "stage-report.json"
        )
        if (
            canonical_report.is_symlink()
            or not canonical_report.is_file()
            or canonical_report.stat().st_mode & 0o777 != 0o444
        ):
            raise ContractError(
                "STAGE-REVIEW requires the canonical immutable stage-report.json"
            )
    request_id = args.request_id or f"far_{uuid.uuid4().hex}"
    target_dir = request_dir(plan_dir, request_id)
    manifest_items = []
    for raw in args.artifact:
        path_text, separator, purpose = raw.partition("::")
        path = Path(path_text)
        if not path.is_absolute():
            path = plan_dir / path
        manifest_items.append({"path": str(path.resolve()), "purpose": purpose if separator else "checkpoint evidence"})
    manifest = verify_manifest_items(manifest_items, base_dir=plan_dir)
    staged_cp01 = args.checkpoint == "CP-01" and staged_is_active(plan_dir)
    required_roles = (
        STAGED_CP01_EVIDENCE_PROFILE
        if staged_cp01
        else CHECKPOINT_EVIDENCE_PROFILES[(args.checkpoint, subtype)]
    )
    roles = [item["purpose"] for item in manifest]
    if len(roles) != len(set(roles)):
        raise ContractError("frontier checkpoint evidence roles must be unique")
    accepted_role_sets = [required_roles]
    if args.checkpoint == "STAGE-REVIEW":
        accepted_role_sets.append(
            required_roles | STAGE_REVIEW_CONTINUATION_EVIDENCE_PROFILE
        )
    if set(roles) not in accepted_role_sets:
        raise ContractError(
            "frontier checkpoint evidence profile mismatch; "
            f"accepted={sorted(sorted(value) for value in accepted_role_sets)}, "
            f"actual={sorted(set(roles))}"
        )
    if args.checkpoint == "CP-01" and not staged_cp01:
        requirements_item = next(
            item for item in manifest
            if item["purpose"] == "figure_requirements"
        )
        validate_frozen_figure_requirements(
            plan_dir,
            Path(requirements_item["path"]),
            args.plan_id,
        )
    if staged_cp01:
        state = staged_load_state(plan_dir)
        stage_dir = staged_stage_dir(plan_dir, state["active_stage_id"])
        expected_paths = {
            "optimization_contract": (
                staged_root(plan_dir) / "contracts"
                / f"{state['contract_version']}.json"
            ),
            "first_stage_envelope": stage_dir / "envelope.json",
            "current_stage_preflight": stage_dir / "preflight.json",
            "checkpoint_capacity": (
                staged_root(plan_dir) / "checkpoint-capacity.json"
            ),
        }
        for item in manifest:
            expected_path = expected_paths[item["purpose"]].resolve()
            if Path(item["path"]).resolve() != expected_path:
                raise ContractError(
                    f"staged CP-01 {item['purpose']} is not the canonical artifact"
                )
        if state["active_stage_envelope_sha256"] != sha256_file(
            expected_paths["first_stage_envelope"]
        ):
            raise ContractError("staged CP-01 first-stage envelope drifted")
        if state["contract_sha256"] != sha256_file(
            expected_paths["optimization_contract"]
        ):
            raise ContractError("staged CP-01 optimization contract drifted")
        envelope = read_json(expected_paths["first_stage_envelope"])
        contract = read_json(expected_paths["optimization_contract"])
        staged_validate_envelope(
            envelope,
            contract["contract_version"],
            state["current_incumbent_sha256"],
            first=envelope["source_cycle_id"] is None,
            plan_dir=plan_dir,
            require_manifest=True,
        )
        review_materials = verify_manifest_items(
            [
                {
                    "path": item["path"],
                    "sha256": item["sha256"],
                    "purpose": (
                        f"{STAGED_CP01_REVIEW_ROLE_PREFIX}{item['purpose']}"
                    ),
                }
                for item in envelope["review_material_manifest"]
            ],
            base_dir=plan_dir,
        )
        manifest.extend(review_materials)
        if (
            codex_host_activation_root(plan_dir) / "activation-receipt.json"
        ).is_file():
            manifest.extend(staged_cp01_execution_dependencies(plan_dir, manifest))
    if args.checkpoint == "STAGE-REVIEW":
        assert staged_review_state is not None
        stage_dir = staged_stage_dir(
            plan_dir, staged_review_state["active_stage_id"],
        )
        terminal_paths = staged_terminal_review_evidence_paths(
            plan_dir, staged_review_state["active_stage_id"],
        )
        expected_paths = {
            "optimization_contract": (
                staged_root(plan_dir) / "contracts"
                / f"{staged_review_state['contract_version']}.json"
            ),
            "stage_envelope": stage_dir / "envelope.json",
            "stage_report": stage_dir / "stage-report.json",
            **terminal_paths,
        }
        for item in manifest:
            if item["purpose"] in STAGE_REVIEW_CONTINUATION_EVIDENCE_PROFILE:
                continue
            expected_path = expected_paths[item["purpose"]].resolve()
            if Path(item["path"]).resolve() != expected_path:
                raise ContractError(
                    f"STAGE-REVIEW {item['purpose']} must be canonical; "
                    "use CP-01 approve_execution for an initial stage"
                )
        if STAGE_REVIEW_CONTINUATION_EVIDENCE_PROFILE <= set(roles):
            continuation_items = {
                item["purpose"]: item for item in manifest
                if item["purpose"] in STAGE_REVIEW_CONTINUATION_EVIDENCE_PROFILE
            }
            validate_stage_review_continuation_materials(
                plan_dir, staged_review_state, continuation_items,
            )
    if args.checkpoint == "CP-02":
        promotion_item = next(item for item in manifest if item["purpose"] == "promotion_receipt")
        promotion_path = Path(promotion_item["path"])
        promotion = read_json(promotion_path)
        run_id = promotion.get("worker_run_id", "")
        if promotion_path != worker_run_dir(plan_dir, run_id) / "promotion-receipt.json":
            raise ContractError("CP-02 promotion receipt is not canonical for its worker run")
        promotion_journal = read_json(promotion_path.parent / "promotion-journal.json")
        if (
            promotion_journal.get("phase") != "COMMITTED"
            or promotion_journal.get("receipt_sha256") != sha256_file(promotion_path)
        ):
            raise ContractError("CP-02 requires a COMMITTED worker promotion receipt")
    request = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "plan_id": args.plan_id,
        "checkpoint": args.checkpoint,
        "checkpoint_subtype": subtype,
        "attempt": args.attempt,
        "objective": args.objective,
        "decision_required": args.decision_required,
        "context_manifest": manifest,
        "evidence_profile_version": 3 if staged_cp01 else 1,
        "constraints": args.constraint,
        "budget_reservation": {"call": 1, "max_input_tokens": args.max_input_tokens, "max_output_tokens": args.max_output_tokens},
        "created_at": utc_now(),
        "deadline_at": (
            datetime.now(timezone.utc).replace(microsecond=0)
            + timedelta(seconds=args.deadline_seconds)
        ).isoformat().replace("+00:00", "Z"),
    }
    retry_of_request = getattr(args, "retry_of_request", None)
    if retry_of_request is not None:
        source_path, source = load_request(plan_dir, retry_of_request)
        source_status = read_json(status_path(plan_dir, retry_of_request))
        logical_request_id = source.get("retry_lineage", {}).get(
            "logical_request_id", retry_of_request,
        )
        expected_attempt = source.get("retry_lineage", {}).get(
            "retry_attempt", source["attempt"] - 1,
        ) + 1
        if (
            source_status.get("state") != "PAUSED"
            or source_status.get("failure") not in {
                "transport_failed", "frontier_surface_violation",
                "response_invalid", "provider_quota",
            }
        ):
            raise ContractError(
                "frontier retry requires a recoverable PAUSED source request"
            )
        if args.attempt != source["attempt"] + 1 or args.attempt != expected_attempt + 1:
            raise ContractError("frontier retry attempt sequence changed")
        if any(
            request.get(field) != source.get(field)
            for field in (
                "plan_id", "checkpoint", "checkpoint_subtype", "objective",
                "decision_required", "context_manifest", "constraints",
            )
        ):
            raise ContractError("frontier retry changed the logical checkpoint")
        request["retry_lineage"] = {
            "logical_request_id": logical_request_id,
            "parent_request_id": retry_of_request,
            "parent_request_sha256": sha256_file(source_path),
            "retry_attempt": source.get("retry_lineage", {}).get(
                "retry_attempt", 0,
            ) + 1,
            "failure_class": source_status["failure"],
            "retry_token_limit": read_json(
                staged_root(plan_dir) / "capacity-ledger.json"
            )["retry_budget"]["per_attempt_token_limit"],
        }
    if (
        args.checkpoint == "CP-01"
        and isinstance(policy.get("top_level_plan_audit"), dict)
    ):
        request["review_contract"] = {
            "schema_version": SCHEMA_VERSION,
            "kind": (
                "staged-contract-stage-review-v2"
                if staged_cp01 else "top-level-plan-review-v1"
            ),
            "declared_author_model_family": policy[
                "top_level_plan_audit"
            ]["declared_author_model_family"],
            "reviewer_profile": {
                "kind": "top_level_plan_audit",
                "model": policy["top_level_plan_audit"]["reviewer_model"],
                "reasoning_effort": policy[
                    "top_level_plan_audit"
                ]["reasoning_effort"],
            },
            "model_policy_sha256": sha256_file(policy_path(plan_dir)),
            "evidence_roles": sorted(
                item["purpose"] for item in manifest
            ),
            "dependent_transition": "approve_execution",
        }
        validate_top_level_plan_review_contract(request)
    context_capsule_arg = getattr(args, "context_capsule", None)
    if context_capsule_arg:
        capsule, _, _, _ = validate_context_capsule(
            plan_dir, Path(context_capsule_arg).resolve(),
        )
        if manifest != capsule["input_manifest"]:
            raise ContractError(
                "frontier context manifest is not the exact frozen context capsule manifest"
            )
        request["durable_context"] = {
            "capsule_path": str(Path(context_capsule_arg).resolve()),
            "capsule_id": capsule["capsule_id"],
            "capsule_sha256": capsule["capsule_sha256"],
            "state_revision": capsule["state_revision"],
            "task_id": capsule["task_id"],
        }
    if args.checkpoint == "CP-03":
        eligibility = pivot_eligibility(plan_dir)
        request["pivot_epoch"] = eligibility["pivot_epoch"]
        request["pivot_cursor"] = eligibility["pivot_cursor"]
        request["pivot_event_ids"] = eligibility["eligible_event_ids"]
    if not request["plan_id"] or not request["objective"] or not request["decision_required"]:
        raise ContractError("plan_id, objective, and decision_required are required")
    manifest_path = plan_dir / "resource_manifest.json"
    if manifest_path.exists() and request["plan_id"] != plan_identity(plan_dir):
        raise ContractError("frontier request plan_id does not match resource manifest")
    if target_dir.exists():
        existing_path = target_dir / "request.json"
        existing = read_json(existing_path)
        request["created_at"] = existing.get("created_at")
        request["deadline_at"] = existing.get("deadline_at")
        if sha256_json(request) != sha256_json(existing):
            raise ContractError("frontier request_id collision: canonical request bytes differ")
        return {
            "ok": True, "idempotent": True, "request_id": request_id,
            "request_path": str(existing_path), "request_sha256": sha256_file(existing_path),
            "request_canonical_sha256": sha256_json(existing), "checkpoint": existing["checkpoint"],
        }
    target_dir.mkdir(parents=True, exist_ok=False)
    request_path = target_dir / "request.json"
    atomic_write_json(request_path, request, immutable=True)
    request_hash = sha256_file(request_path)
    transition(
        plan_dir, request_id, "CREATED", checkpoint=args.checkpoint,
        request_sha256=request_hash,
        context_manifest_sha256=sha256_json(request["context_manifest"]),
        deadline_at=request["deadline_at"],
        budget_reservation=request["budget_reservation"],
        model_policy_sha256=sha256_file(policy_path(plan_dir)),
    )
    return {
        "ok": True, "request_id": request_id, "request_path": str(request_path),
        "request_sha256": request_hash, "request_canonical_sha256": sha256_json(request),
    }


def validate_request_durable_context(
    plan_dir: Path, request: dict[str, Any], *, require_current: bool,
) -> dict[str, Any] | None:
    binding = request.get("durable_context")
    if binding is None:
        return None
    if not isinstance(binding, dict) or set(binding) != {
        "capsule_path", "capsule_id", "capsule_sha256", "state_revision", "task_id",
    }:
        raise ContractError("frontier durable context binding has an invalid closed shape")
    capsule_path = Path(binding["capsule_path"])
    if require_current:
        capsule, _, _, _ = validate_context_capsule(plan_dir, capsule_path)
    else:
        expected_root = (durable_root(plan_dir) / "capsules").resolve()
        try:
            capsule_path.resolve().relative_to(expected_root)
        except ValueError as exc:
            raise ContractError(
                "frontier context capsule is outside canonical durable state"
            ) from exc
        capsule = read_json(capsule_path)
        validate_schema(capsule, read_json(CONTEXT_CAPSULE_SCHEMA))
        if capsule_path.resolve() != context_capsule_path(
            plan_dir, capsule["capsule_id"],
        ).resolve():
            raise ContractError("frontier context capsule path/identity mismatch")
        body = {key: value for key, value in capsule.items() if key != "capsule_sha256"}
        if capsule.get("capsule_sha256") != sha256_json(body):
            raise ContractError("frontier context capsule hash changed")
    if capsule.get("plan_id") != request.get("plan_id"):
        raise ContractError("frontier context capsule belongs to another plan")
    checks = {
        "capsule_id": capsule["capsule_id"],
        "capsule_sha256": capsule["capsule_sha256"],
        "state_revision": capsule["state_revision"],
        "task_id": capsule["task_id"],
    }
    if any(binding.get(field) != expected for field, expected in checks.items()):
        raise ContractError("frontier request was rebound to another durable context")
    return capsule


def command_create_durable_request(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    capsule, _, _, _ = validate_context_capsule(
        plan_dir, Path(args.context_capsule).resolve(),
    )
    key = (args.checkpoint, args.checkpoint_subtype)
    required_roles = (
        STAGED_CP01_EVIDENCE_PROFILE
        if key == ("CP-01", None) and staged_is_active(plan_dir)
        else CHECKPOINT_EVIDENCE_PROFILES.get(key)
    )
    if required_roles is None:
        raise ContractError("checkpoint/subtype is not registered")
    manifest = capsule["input_manifest"]
    roles = [item["purpose"] for item in manifest]
    if len(roles) != len(set(roles)) or set(roles) != required_roles:
        raise ContractError(
            f"durable capsule evidence profile mismatch; missing={sorted(required_roles - set(roles))}, "
            f"extra={sorted(set(roles) - required_roles)}"
        )
    forwarded = argparse.Namespace(
        plan_dir=str(plan_dir),
        plan_id=capsule["plan_id"],
        checkpoint=args.checkpoint,
        checkpoint_subtype=args.checkpoint_subtype,
        attempt=args.attempt,
        objective=args.objective,
        decision_required=args.decision_required,
        artifact=[f"{item['path']}::{item['purpose']}" for item in manifest],
        constraint=args.constraint,
        max_input_tokens=args.max_input_tokens,
        max_output_tokens=args.max_output_tokens,
        request_id=args.request_id,
        deadline_seconds=args.deadline_seconds,
        context_capsule=str(Path(args.context_capsule).resolve()),
    )
    return command_create_request(forwarded)


def frontier_logical_request_id(request: dict[str, Any]) -> str:
    lineage = request.get("retry_lineage")
    if lineage is None:
        return request["request_id"]
    if (
        not isinstance(lineage, dict)
        or set(lineage) != {
            "logical_request_id", "parent_request_id",
            "parent_request_sha256", "retry_attempt", "failure_class",
            "retry_token_limit",
        }
        or not REQUEST_ID_RE.fullmatch(lineage.get("logical_request_id", ""))
        or not REQUEST_ID_RE.fullmatch(lineage.get("parent_request_id", ""))
        or not SHA256_RE.fullmatch(lineage.get("parent_request_sha256", ""))
        or not isinstance(lineage.get("retry_attempt"), int)
        or lineage["retry_attempt"] < 1
        or not isinstance(lineage.get("retry_token_limit"), int)
        or lineage["retry_token_limit"] < 0
    ):
        raise ContractError("frontier retry lineage has an invalid closed shape")
    return lineage["logical_request_id"]


def command_retry_frontier_request(args: argparse.Namespace) -> dict[str, Any]:
    """Create a new, bounded attempt without reopening a named checkpoint slot."""
    plan_dir = Path(args.plan_dir).resolve()
    source_path, source = load_request(plan_dir, args.source_request_id)
    source_status = read_json(status_path(plan_dir, args.source_request_id))
    logical_request_id = frontier_logical_request_id(source)
    requests_root = frontier_root(plan_dir) / "requests"
    descendants: list[dict[str, Any]] = []
    for candidate in requests_root.glob("far_*/request.json"):
        value = read_json(candidate)
        if frontier_logical_request_id(value) == logical_request_id:
            descendants.append(value)
    if any(
        read_json(status_path(plan_dir, item["request_id"])).get("state") == "APPLIED"
        for item in descendants
    ):
        raise ContractError("logical frontier checkpoint is already applied")
    target_path = request_dir(plan_dir, args.request_id) / "request.json"
    if target_path.is_file():
        existing = read_json(target_path)
        lineage = existing.get("retry_lineage", {})
        if (
            lineage.get("parent_request_id") != args.source_request_id
            or lineage.get("logical_request_id") != logical_request_id
        ):
            raise ContractError("frontier retry request_id collision")
        return {
            "ok": True, "idempotent": True,
            "request_id": existing["request_id"],
            "request_path": str(target_path),
            "request_sha256": sha256_file(target_path),
            "logical_request_id": logical_request_id,
            "parent_request_id": args.source_request_id,
            "retry_attempt": lineage["retry_attempt"],
            "source_request_sha256": sha256_file(source_path),
        }
    if source_status.get("state") != "PAUSED" or source_status.get("failure") not in {
        "transport_failed", "frontier_surface_violation", "response_invalid",
        "provider_quota",
    }:
        raise ContractError(
            "frontier retry requires a recoverable PAUSED transport/response failure"
        )
    retry_not_before = source_status.get("retry_not_before")
    if (
        source_status.get("failure") == "provider_quota"
        and retry_not_before is not None
        and datetime.now(timezone.utc) < parse_utc(retry_not_before)
    ):
        raise ContractError(
            f"provider quota retry is not due before {retry_not_before}"
        )
    latest = max(descendants, key=lambda item: item["attempt"])
    if latest["request_id"] != args.source_request_id:
        raise ContractError("frontier retry must extend the latest logical attempt")
    capacity = read_json(staged_root(plan_dir) / "capacity-ledger.json")
    staged_validate_capacity(capacity)
    retry_budget = capacity["retry_budget"]
    if retry_budget["remaining_attempts"] < 1:
        raise ContractError("frontier retry budget exhausted")
    forwarded = argparse.Namespace(
        plan_dir=str(plan_dir),
        plan_id=source["plan_id"],
        checkpoint=source["checkpoint"],
        checkpoint_subtype=source.get("checkpoint_subtype"),
        attempt=source["attempt"] + 1,
        objective=source["objective"],
        decision_required=source["decision_required"],
        artifact=[
            f"{item['path']}::{item['purpose']}"
            for item in source["context_manifest"]
            if not item["purpose"].startswith(STAGED_CP01_REVIEW_ROLE_PREFIX)
        ],
        constraint=list(source["constraints"]),
        max_input_tokens=source["budget_reservation"]["max_input_tokens"],
        max_output_tokens=source["budget_reservation"]["max_output_tokens"],
        request_id=args.request_id,
        deadline_seconds=args.deadline_seconds,
        context_capsule=(source.get("durable_context") or {}).get("capsule_path"),
        retry_of_request=args.source_request_id,
    )
    created = command_create_request(forwarded)
    return {
        **created,
        "logical_request_id": logical_request_id,
        "parent_request_id": args.source_request_id,
        "retry_attempt": source.get("retry_lineage", {}).get("retry_attempt", 0) + 1,
        "source_request_sha256": sha256_file(source_path),
    }


def recover_one_due_frontier_retry(
    plan_dir: Path, *, codex_bin: str | None = None, timeout: int = 1800,
) -> dict[str, Any]:
    """Let the authorized L1 work tick resume at most one due quota attempt."""
    requests_root = frontier_root(plan_dir) / "requests"
    now = datetime.now(timezone.utc)
    requests = [
        read_json(path) for path in requests_root.glob("far_*/request.json")
    ]
    groups: dict[str, list[dict[str, Any]]] = {}
    for request in requests:
        groups.setdefault(frontier_logical_request_id(request), []).append(request)
    candidates: list[tuple[datetime, dict[str, Any], bool]] = []
    for siblings in groups.values():
        latest = max(siblings, key=lambda item: item["attempt"])
        status = read_json(status_path(plan_dir, latest["request_id"]))
        retry_at = status.get("retry_not_before")
        if (
            status.get("state") == "PAUSED"
            and status.get("failure") == "provider_quota"
            and isinstance(retry_at, str)
            and parse_utc(retry_at) <= now
        ):
            candidates.append((parse_utc(retry_at), latest, True))
            continue
        lineage = latest.get("retry_lineage")
        if status.get("state") == "CREATED" and isinstance(lineage, dict):
            parent_status = read_json(status_path(
                plan_dir, lineage["parent_request_id"],
            ))
            parent_due = parent_status.get("retry_not_before")
            if (
                parent_status.get("failure") == "provider_quota"
                and isinstance(parent_due, str)
                and parse_utc(parent_due) <= now
            ):
                candidates.append((parse_utc(parent_due), latest, False))
    if not candidates:
        return {"attempted": False}
    _, source, create_child = min(candidates, key=lambda item: item[0])
    if create_child:
        retry_id = "far_retry_" + hashlib.sha256(
            f"{source['request_id']}:{source['attempt'] + 1}".encode()
        ).hexdigest()[:24]
        command_retry_frontier_request(argparse.Namespace(
            plan_dir=str(plan_dir), source_request_id=source["request_id"],
            request_id=retry_id, deadline_seconds=1800,
        ))
    else:
        retry_id = source["request_id"]
    command_send_request(argparse.Namespace(
        plan_dir=str(plan_dir), request_id=retry_id,
        codex_bin=codex_bin or os.environ.get("CODEX_BIN", "codex"),
        timeout=timeout,
    ))
    command_validate_response(argparse.Namespace(
        plan_dir=str(plan_dir), request_id=retry_id,
    ))
    request = load_request(plan_dir, retry_id)[1]
    current = read_json(status_path(plan_dir, retry_id))
    response = read_json(Path(current["validated_response_path"]))
    expected = DEPENDENT_TRANSITIONS[
        (request["checkpoint"], request.get("checkpoint_subtype"))
    ]
    if response["recommendation"] not in expected[1]:
        return {
            "attempted": True, "request_id": retry_id,
            "state": "VALIDATED", "advisory_blocked": True,
        }
    applied = command_apply_response(argparse.Namespace(
        plan_dir=str(plan_dir), request_id=retry_id,
        controller_note="automatic due provider-quota retry",
        dependent_transition=expected[0],
    ))
    return {
        "attempted": True, "request_id": retry_id,
        "state": applied["state"], "advisory_blocked": False,
    }


def command_recover_due_frontier_retry(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    result = recover_one_due_frontier_retry(
        plan_dir, codex_bin=args.codex_bin, timeout=args.timeout,
    )
    return {"ok": True, **result}


def load_request(
    plan_dir: Path, request_id: str, *, verify_live_manifest: bool = True,
) -> tuple[Path, dict[str, Any]]:
    path = request_dir(plan_dir, request_id) / "request.json"
    request = read_json(path)
    if request.get("request_id") != request_id:
        raise ContractError("request correlation mismatch")
    if request.get("checkpoint") not in CHECKPOINTS:
        raise ContractError("request checkpoint is not registered")
    if verify_live_manifest:
        verify_manifest_items(request.get("context_manifest"), base_dir=plan_dir)
    return path, request


def extract_usage(jsonl: str) -> dict[str, int]:
    best = {"input_tokens": 0, "output_tokens": 0}
    for line in jsonl.splitlines():
        try:
            event = strict_json_loads(line)
        except ContractError:
            continue
        stack = [event]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                input_value = value.get("input_tokens", value.get("inputTokens"))
                output_value = value.get("output_tokens", value.get("outputTokens"))
                if isinstance(input_value, int):
                    best["input_tokens"] = max(best["input_tokens"], input_value)
                if isinstance(output_value, int):
                    best["output_tokens"] = max(best["output_tokens"], output_value)
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
    return best


def estimate_frontier_input_tokens(request_path: Path, request: dict[str, Any]) -> int:
    """Conservatively estimate input size before spending frontier budget."""
    byte_count = request_path.stat().st_size
    for item in request["context_manifest"]:
        byte_count += Path(item["path"]).stat().st_size
    return (byte_count + 2) // 3


@contextmanager
def request_send_lock(plan_dir: Path, request_id: str) -> Iterator[None]:
    lock_path = request_dir(plan_dir, request_id) / ".send.lock"
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def validate_frontier_response_integrity(
    plan_dir: Path, request_id: str, current: dict[str, Any], response_path: Path,
    *, allow_unreconciled_overrun: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    request_path, request = load_request(plan_dir, request_id)
    validate_request_durable_context(
        plan_dir, request, require_current=current.get("state") != "APPLIED",
    )
    response = read_json(response_path)
    validate_schema(response, read_json(RESPONSE_SCHEMA))
    registry = CHECKPOINTS[request["checkpoint"]]
    checks = {
        "request_id": request_id, "plan_id": request["plan_id"],
        "checkpoint": request["checkpoint"], "checkpoint_subtype": request["checkpoint_subtype"],
        "request_sha256": sha256_file(request_path),
        "context_manifest_sha256": sha256_json(request["context_manifest"]),
        "response_kind": registry["kind"],
    }
    for field, expected in checks.items():
        if response.get(field) != expected:
            raise ContractError(f"response {field} mismatch")
    if current.get("request_sha256") != checks["request_sha256"]:
        raise ContractError("immutable request hash changed")
    if current.get("context_manifest_sha256") != checks["context_manifest_sha256"]:
        raise ContractError("immutable context manifest hash changed")
    if response["recommendation"] not in registry["recommendations"]:
        raise ContractError("recommendation is invalid for checkpoint")
    if response["status"] != "completed":
        raise ContractError("frontier response must have status=completed")
    critical_findings = any(
        item.get("severity") == "critical" for item in response["findings"]
    )
    if response["recommendation"] == "accept" and (
        response["blockers"] or critical_findings
    ):
        raise FrontierSemanticResponseError(
            "accept recommendation is inconsistent with unresolved blockers "
            "or critical findings"
        )
    evidence_authority = {item["path"] for item in request["context_manifest"]} | {
        item["sha256"] for item in request["context_manifest"]
    }
    for finding in response["findings"]:
        if not finding["evidence"] or any(item not in evidence_authority for item in finding["evidence"]):
            raise ContractError("frontier findings must cite frozen evidence paths or hashes")
    reservation = request["budget_reservation"]
    retry_lineage = request.get("retry_lineage")
    if (
        retry_lineage is not None
        and response["usage"]["output_tokens"]
        > retry_lineage["retry_token_limit"]
    ):
        raise ContractError("frontier retry actual output token limit exceeded")
    if (
        response["usage"]["input_tokens"] > reservation["max_input_tokens"]
        or response["usage"]["output_tokens"] > reservation["max_output_tokens"]
    ) and not allow_unreconciled_overrun:
        validate_frontier_overrun_receipt(
            plan_dir, request_id, request, request_path, response, response_path,
        )
    verify_manifest_items(request["context_manifest"], base_dir=plan_dir)
    return response, request, request_path


def frontier_overrun_receipt_path(plan_dir: Path, request_id: str) -> Path:
    return request_dir(plan_dir, request_id) / "budget-overrun-receipt.json"


def frontier_overrun_journal_path(plan_dir: Path, request_id: str) -> Path:
    return request_dir(plan_dir, request_id) / "budget-overrun-journal.json"


def frontier_overrun_projection(
    request: dict[str, Any], response: dict[str, Any],
) -> dict[str, Any]:
    reservation = request["budget_reservation"]
    actual = response["usage"]
    return {
        "reservation": dict(reservation),
        "actual_usage": dict(actual),
        "delta": {
            "input_tokens": max(
                0, actual["input_tokens"] - reservation["max_input_tokens"],
            ),
            "output_tokens": max(
                0, actual["output_tokens"] - reservation["max_output_tokens"],
            ),
        },
    }


def validate_frontier_overrun_receipt(
    plan_dir: Path, request_id: str, request: dict[str, Any],
    request_path: Path, response: dict[str, Any], response_path: Path,
) -> dict[str, Any]:
    receipt_path = frontier_overrun_receipt_path(plan_dir, request_id)
    if not receipt_path.is_file():
        raise FrontierBudgetOverrunError(
            "controller-observed token use exceeds the request reservation "
            "without a committed plan-budget reconciliation"
        )
    receipt = read_json(receipt_path)
    projection = frontier_overrun_projection(request, response)
    expected = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": request["plan_id"],
        "request_id": request_id,
        "request_sha256": sha256_file(request_path),
        "response_sha256": sha256_file(response_path),
        **projection,
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ContractError("frontier budget-overrun receipt correlation mismatch")
    if not any(projection["delta"].values()):
        raise ContractError("frontier budget-overrun receipt has no overrun")
    journal_path = frontier_overrun_journal_path(plan_dir, request_id)
    journal = read_json(journal_path)
    if (
        journal.get("phase") != "COMMITTED"
        or journal.get("request_id") != request_id
        or journal.get("receipt_sha256") != sha256_file(receipt_path)
    ):
        raise ContractError("frontier budget-overrun journal is not committed")
    global_ledger = read_json(frontier_root(plan_dir) / "budget.json")
    global_after = receipt["global_after"]
    if (
        request_id not in global_ledger.get("request_ids", [])
        or any(
            global_ledger.get(field, -1) < global_after[field]
            for field in (
                "reserved_calls", "reserved_input_tokens",
                "reserved_output_tokens",
            )
        )
    ):
        raise ContractError("frontier reconciled global budget was reduced")
    usage_after = receipt.get("stage_usage_after")
    if usage_after is not None:
        usage_path = Path(receipt["stage_usage_path"])
        usage = read_json(usage_path)
        if (
            f"frontier:{request_id}" not in usage.get("reservation_ids", [])
            or usage.get("used", {}).get("review_tokens", -1)
            < usage_after["used"]["review_tokens"]
        ):
            raise ContractError("frontier reconciled stage usage was reduced")
    return receipt


def reconcile_frontier_budget_overrun(
    plan_dir: Path, request_id: str, request: dict[str, Any],
    request_path: Path, response: dict[str, Any], response_path: Path,
) -> dict[str, Any]:
    """Charge a response overrun only when every enclosing hard limit can pay it."""
    projection = frontier_overrun_projection(request, response)
    delta = projection["delta"]
    if not any(delta.values()):
        raise ContractError("frontier response does not require budget reconciliation")
    policy = load_policy(plan_dir)
    journal_path = frontier_overrun_journal_path(plan_dir, request_id)
    receipt_path = frontier_overrun_receipt_path(plan_dir, request_id)

    def reconcile_locked() -> dict[str, Any]:
        global_path = frontier_root(plan_dir) / "budget.json"
        if journal_path.exists():
            journal = read_json(journal_path)
            if journal.get("phase") == "COMMITTED":
                return validate_frontier_overrun_receipt(
                    plan_dir, request_id, request, request_path,
                    response, response_path,
                )
            expected_identity = {
                "request_id": request_id,
                "request_sha256": sha256_file(request_path),
                "response_sha256": sha256_file(response_path),
                "projection": projection,
            }
            if any(
                journal.get(key) != value
                for key, value in expected_identity.items()
            ):
                raise ContractError("frontier budget-overrun journal conflict")
            global_after = journal["global_after"]
            usage_path = (
                Path(journal["stage_usage_path"])
                if journal.get("stage_usage_path") else None
            )
            usage_after = journal.get("stage_usage_after")
        else:
            global_before = read_json(global_path)
            limits = effective_frontier_limits(policy, global_before)
            global_after = json.loads(json.dumps(global_before))
            global_after["reserved_input_tokens"] += delta["input_tokens"]
            global_after["reserved_output_tokens"] += delta["output_tokens"]
            global_after["updated_at"] = utc_now()
            if (
                global_after["reserved_input_tokens"] > limits["max_input_tokens"]
                or global_after["reserved_output_tokens"] > limits["max_output_tokens"]
            ):
                raise FrontierBudgetOverrunError(
                    "controller-observed token use exceeds the authorized plan budget"
                )
            usage_path: Path | None = None
            usage_before: dict[str, Any] | None = None
            usage_after: dict[str, Any] | None = None
            if staged_is_active(plan_dir):
                state = staged_load_state(plan_dir)
                usage_path = (
                    staged_stage_dir(plan_dir, state["active_stage_id"])
                    / "usage-ledger.json"
                )
                usage_before = read_json(usage_path)
                if f"frontier:{request_id}" not in usage_before["reservation_ids"]:
                    raise ContractError("frontier stage reservation is missing")
                usage_after = json.loads(json.dumps(usage_before))
                usage_after["used"]["review_tokens"] += delta["output_tokens"]
                usage_after["updated_at"] = utc_now()
                if (
                    usage_after["used"]["review_tokens"]
                    > usage_after["limits"]["review_tokens"]
                ):
                    raise FrontierBudgetOverrunError(
                        "controller-observed token use exceeds the authorized stage budget"
                    )
            journal = {
                "schema_version": SCHEMA_VERSION,
                "phase": "PREPARED",
                "request_id": request_id,
                "request_sha256": sha256_file(request_path),
                "response_sha256": sha256_file(response_path),
                "projection": projection,
                "global_before": global_before,
                "global_after": global_after,
                "stage_usage_path": str(usage_path) if usage_path else None,
                "stage_usage_before": usage_before,
                "stage_usage_after": usage_after,
                "prepared_at": utc_now(),
                "reconciled_at": utc_now(),
            }
            atomic_write_json(journal_path, journal)
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": request["plan_id"],
            "request_id": request_id,
            "request_sha256": sha256_file(request_path),
            "response_sha256": sha256_file(response_path),
            **projection,
            "global_after": global_after,
            "stage_usage_path": str(usage_path) if usage_path else None,
            "stage_usage_after": usage_after,
            "reconciled_at": journal["reconciled_at"],
        }
        current_global = read_json(global_path)
        if current_global == journal["global_before"]:
            atomic_write_json(global_path, journal["global_after"])
        elif current_global != journal["global_after"]:
            raise ContractError("frontier budget-overrun global image conflict")
        if usage_path is not None:
            current_usage = read_json(usage_path)
            if current_usage == journal["stage_usage_before"]:
                atomic_write_json(usage_path, journal["stage_usage_after"])
            elif current_usage != journal["stage_usage_after"]:
                raise ContractError("frontier budget-overrun stage image conflict")
        if receipt_path.exists():
            if read_json(receipt_path) != receipt:
                raise ContractError("frontier budget-overrun receipt conflict")
        else:
            atomic_write_json(receipt_path, receipt, immutable=True)
        journal.update({
            "phase": "COMMITTED",
            "receipt_sha256": sha256_file(receipt_path),
            "committed_at": utc_now(),
        })
        atomic_write_json(journal_path, journal)
        return receipt

    if staged_is_active(plan_dir):
        with staged_transaction_lock(plan_dir):
            with budget_lock(plan_dir):
                return reconcile_locked()
    with budget_lock(plan_dir):
        return reconcile_locked()


def reconcile_frontier_locked(plan_dir: Path, request_id: str) -> dict[str, Any]:
    run_dir = request_dir(plan_dir, request_id)
    current = read_json(status_path(plan_dir, request_id))
    _, request = load_request(plan_dir, request_id)
    if current["state"] in {"RECEIVED", "VALIDATED", "APPLIED"}:
        return {"ok": True, "idempotent": True, **current}
    raw_response = run_dir / "response.raw.json"
    events_path = run_dir / "transport.events.jsonl"
    if not raw_response.is_file():
        paused = transition(plan_dir, request_id, "PAUSED", failure="transport_outcome_uncertain")
        return {"ok": False, **paused}
    try:
        response = read_json(raw_response)
        usage = extract_usage(events_path.read_text() if events_path.exists() else "")
        if usage["input_tokens"] == 0 and usage["output_tokens"] == 0:
            usage = {
                "input_tokens": request["budget_reservation"]["max_input_tokens"],
                "output_tokens": request["budget_reservation"]["max_output_tokens"],
            }
            usage_accounting = {
                "authority": "conservative_reservation_fallback",
                "raw_transport_usage": {
                    "input_tokens": 0, "output_tokens": 0,
                },
                "charged_usage": usage,
            }
        else:
            usage_accounting = {
                "authority": "controller_observed_transport",
                "charged_usage": usage,
            }
        response["model_id"] = current["model_id"]
        response["usage"] = usage
        response.setdefault("completed_at", utc_now())
        response_path = run_dir / "response.json"
        if response_path.exists():
            if read_json(response_path) != response:
                raise ContractError("canonical response differs from durable raw response")
        else:
            atomic_write_json(response_path, response, immutable=True)
        received = transition(
            plan_dir, request_id, "RECEIVED", response_path=str(response_path),
            response_sha256=sha256_file(response_path),
            usage_accounting=usage_accounting,
        )
        return {"ok": True, **received}
    except ContractError as exc:
        transition(plan_dir, request_id, "INVALID", validation_error=str(exc))
        paused = transition(plan_dir, request_id, "PAUSED", failure="malformed_durable_response", validation_error=str(exc))
        raise ContractError(str(exc)) from None


def resolve_executable(command: str, *, label: str = "Codex") -> str:
    candidate = Path(command)
    if os.sep in command or (os.altsep and os.altsep in command):
        resolved = candidate.expanduser().resolve()
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise ContractError(
                f"{label} executable is unavailable or not executable: {resolved}"
            )
        return str(resolved)
    found = shutil.which(command)
    if not found:
        raise ContractError(f"{label} executable is unavailable on PATH: {command}")
    resolved = Path(found).resolve()
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ContractError(
            f"{label} executable is unavailable or not executable: {resolved}"
        )
    return str(resolved)


def validate_frontier_output_schema() -> str:
    schema = read_json(RESPONSE_SCHEMA)
    validate_supported_schema(schema)

    def require_typed_literals(node: Any, path: str = "$") -> None:
        if not isinstance(node, dict):
            return
        if ("const" in node or "enum" in node) and "type" not in node:
            raise ContractError(
                f"frontier response schema is not strict-compatible: {path} "
                "uses const/enum without an explicit type"
            )
        for key, child in node.get("properties", {}).items():
            require_typed_literals(child, f"{path}.properties.{key}")
        if "items" in node:
            require_typed_literals(node["items"], f"{path}.items")

    require_typed_literals(schema)
    return sha256_file(RESPONSE_SCHEMA)


def frontier_transport_args(policy: dict[str, Any]) -> list[str]:
    transport = policy.get("frontier_transport", "codex-default")
    if transport == "codex-default":
        return []
    return [
        "-c", 'model_provider="chatgpt_http"',
        "-c", 'model_providers.chatgpt_http.name="ChatGPT HTTP"',
        "-c", 'model_providers.chatgpt_http.base_url="https://chatgpt.com/backend-api/codex"',
        "-c", 'model_providers.chatgpt_http.wire_api="responses"',
        "-c", "model_providers.chatgpt_http.requires_openai_auth=true",
        "-c", "model_providers.chatgpt_http.supports_websockets=false",
    ]


def frontier_surface_reduction_args() -> list[str]:
    return [
        "-c", "include_collaboration_mode_instructions=false",
        "-c", (
            'developer_instructions="Act as the sole bounded frontier reviewer. '
            'Do not delegate, spawn, message, resume, interrupt, or wait for any '
            'other agent. Inspect the immutable manifest yourself and return the '
            'required final JSON in this turn."'
        ),
        "--disable", "plugins",
        "--disable", "apps",
        "--disable", "multi_agent",
        "--disable", "multi_agent_v2",
        "--disable", "goals",
        "-c", 'web_search="disabled"',
        "-c", "tools.view_image=false",
    ]


def validate_frontier_transport_events(events_path: Path) -> None:
    """Reject a transport that escaped the single-reviewer surface."""
    if not events_path.exists():
        raise ContractError("frontier transport event log is missing")
    for line_number, raw_line in enumerate(
        events_path.read_text(errors="replace").splitlines(), start=1,
    ):
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") == "collab_tool_call":
            raise ContractError(
                "frontier transport violated the single-reviewer boundary at "
                f"event line {line_number}: collaboration tool "
                f"{item.get('tool', '<unknown>')}"
            )


def frontier_review_profile(
    policy: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, str]:
    review_contract = validate_top_level_plan_review_contract(request)
    if review_contract is not None:
        return review_contract["reviewer_profile"]
    plan_audit = policy.get("top_level_plan_audit")
    if request.get("checkpoint") == "STAGE-REVIEW":
        if not isinstance(plan_audit, dict):
            raise ContractError("terminal stage review requires strongest frozen policy")
        return {
            "kind": "terminal_stage_report_review",
            "model": plan_audit["reviewer_model"],
            "reasoning_effort": plan_audit["reasoning_effort"],
        }
    if request.get("checkpoint") == "CP-01" and isinstance(plan_audit, dict):
        return {
            "kind": "top_level_plan_audit",
            "model": plan_audit["reviewer_model"],
            "reasoning_effort": plan_audit["reasoning_effort"],
        }
    return {
        "kind": "sparse_frontier_checkpoint",
        "model": policy["frontier_model"],
        "reasoning_effort": policy.get(
            "frontier_reasoning_effort", "xhigh",
        ),
    }


def frontier_usage_floor(
    policy: dict[str, Any], review_profile: dict[str, str],
) -> dict[str, Any] | None:
    if policy.get("frontier_transport", "codex-default") != "chatgpt-https":
        return None
    profile = policy.get("frontier_usage_profile", CHATGPT_USAGE_FLOOR)
    if profile != CHATGPT_USAGE_FLOOR:
        raise ContractError("frontier usage floor/profile changed")
    return {**profile, "review_profile_kind": review_profile["kind"]}


def preflight_frontier_transport(
    plan_dir: Path,
    request_id: str,
    codex_bin: str,
    policy: dict[str, Any],
    review_profile: dict[str, str],
) -> dict[str, Any]:
    resolved_bin = resolve_executable(codex_bin)
    schema_sha256 = validate_frontier_output_schema()
    transport = policy.get("frontier_transport", "codex-default")
    normalized_model = review_profile["model"].lower().replace("-", "")
    if transport == "chatgpt-https" and "minimax" in normalized_model:
        raise ContractError(
            "frontier preflight rejected MiniMax on the ChatGPT HTTPS transport; "
            "pin a Codex-supported frontier model"
        )
    try:
        auth = subprocess.run(
            [resolved_bin, "login", "status"],
            cwd=plan_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(f"Codex login preflight failed: {exc}") from exc
    if auth.returncode != 0:
        detail = (auth.stderr or auth.stdout).strip()
        raise ContractError(
            "Codex login preflight failed"
            + (f": {detail[:500]}" if detail else f" with exit {auth.returncode}")
        )
    auth_summary = f"{auth.stdout}\n{auth.stderr}".lower()
    if transport == "chatgpt-https" and "chatgpt" not in auth_summary:
        raise ContractError(
            "Codex login preflight did not confirm a ChatGPT session required "
            "by chatgpt-https"
        )
    config_probe_command = [
        resolved_bin,
        *frontier_transport_args(policy),
        *frontier_surface_reduction_args(),
        "features",
        "list",
    ]
    try:
        config_probe = subprocess.run(
            config_probe_command,
            cwd=plan_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(
            f"Codex isolated-surface config preflight failed: {exc}"
        ) from exc
    if config_probe.returncode != 0:
        detail = (config_probe.stderr or config_probe.stdout).strip()
        raise ContractError(
            "Codex isolated-surface config preflight failed"
            + (f": {detail[:500]}" if detail else "")
        )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "codex_bin": resolved_bin,
        "frontier_model": review_profile["model"],
        "reasoning_effort": review_profile["reasoning_effort"],
        "review_profile_kind": review_profile["kind"],
        "frontier_transport": transport,
        "response_schema_sha256": schema_sha256,
        "auth_check": (
            "chatgpt-session-passed"
            if transport == "chatgpt-https"
            else "codex-login-passed"
        ),
        "isolated_surface_config_check": "passed",
        "checked_at": utc_now(),
    }
    receipt_path = request_dir(plan_dir, request_id) / "preflight.json"
    if receipt_path.exists():
        prior = read_json(receipt_path)
        stable_fields = {
            key for key in receipt
            if key != "checked_at"
        }
        if any(prior.get(key) != receipt.get(key) for key in stable_fields):
            raise ContractError("frontier preflight receipt correlation mismatch")
        return prior
    atomic_write_json(receipt_path, receipt, immutable=True)
    return receipt


def build_frontier_command(
    codex_bin: str,
    plan_dir: Path,
    raw_response: Path,
    policy: dict[str, Any],
    review_profile: dict[str, str],
) -> list[str]:
    return [
        codex_bin,
        "exec",
        "-m",
        review_profile["model"],
        "-c",
        f"model_reasoning_effort={review_profile['reasoning_effort']}",
        *frontier_transport_args(policy),
        *frontier_surface_reduction_args(),
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "--cd",
        str(plan_dir),
        "--output-schema",
        str(RESPONSE_SCHEMA),
        "--output-last-message",
        str(raw_response),
        "--json",
        "-",
    ]


def classify_frontier_transport_failure(
    stderr_text: str, events_text: str,
) -> dict[str, Any]:
    """Turn provider-limit prose into typed, scheduler-actionable state."""
    text = f"{stderr_text}\n{events_text}".lower()
    quota_markers = (
        "usage limit", "quota", "rate limit", "rate_limit",
        "too many requests", "hour limit", "capacity exhausted",
        "resource_exhausted",
    )
    if not any(marker in text for marker in quota_markers):
        return {"failure": "transport_failed"}
    duration = re.search(
        r"(?:retry|reset|available|try again)[^\n]{0,80}?"
        r"(\d+)\s*(seconds?|minutes?|hours?)",
        text,
    )
    result: dict[str, Any] = {
        "failure": "provider_quota",
        "provider_failure_class": "quota_or_usage_window",
    }
    if duration:
        value = int(duration.group(1))
        unit = duration.group(2)
        multiplier = 3600 if unit.startswith("hour") else (
            60 if unit.startswith("minute") else 1
        )
        result["retry_not_before"] = (
            datetime.now(timezone.utc).replace(microsecond=0)
            + timedelta(seconds=value * multiplier)
        ).isoformat().replace("+00:00", "Z")
    else:
        absolute = re.search(
            r"try again at ([a-z]{3} \d{1,2}(?:st|nd|rd|th), "
            r"\d{4} \d{1,2}:\d{2} [ap]m)",
            text,
        )
        if absolute:
            normalized = re.sub(
                r"(\d{1,2})(?:st|nd|rd|th)", r"\1", absolute.group(1),
            )
            local_zone = datetime.now().astimezone().tzinfo
            parsed = datetime.strptime(
                normalized.title(), "%b %d, %Y %I:%M %p",
            ).replace(tzinfo=local_zone)
            result["retry_not_before"] = parsed.astimezone(
                timezone.utc
            ).isoformat().replace("+00:00", "Z")
    return result


def command_classify_paused_frontier_failure(
    args: argparse.Namespace,
) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    current = read_json(status_path(plan_dir, args.request_id))
    if current.get("state") != "PAUSED":
        raise ContractError("frontier failure classification requires PAUSED state")
    if current.get("failure") == "provider_quota":
        return {"ok": True, "idempotent": True, **current}
    if current.get("failure") != "transport_failed":
        raise ContractError("paused frontier failure is not transport_failed")
    run_dir = request_dir(plan_dir, args.request_id)
    classified = classify_frontier_transport_failure(
        (run_dir / "transport.stderr").read_text(errors="replace"),
        (run_dir / "transport.events.jsonl").read_text(errors="replace"),
    )
    if classified["failure"] == "transport_failed":
        return {"ok": True, "classified": False, **current}
    updated = transition(
        plan_dir, args.request_id, "PAUSED",
        previous_failure=current["failure"], **classified,
    )
    return {"ok": True, "classified": True, **updated}


def update_transport_launch(
    plan_dir: Path,
    request_id: str,
    send_claim: str,
    phase: str,
    **extra: Any,
) -> dict[str, Any]:
    path = (
        request_dir(plan_dir, request_id)
        / "transport-launches"
        / f"{send_claim}.json"
    )
    prior = read_json(path) if path.exists() else {}
    value = {
        **prior,
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "send_claim": send_claim,
        "phase": phase,
        "updated_at": utc_now(),
        **extra,
    }
    atomic_write_json(path, value)
    return value


def terminate_transport_process_group(
    proc: subprocess.Popen[str],
    grace_seconds: float = 1.0,
) -> None:
    if os.name != "posix":
        proc.terminate()
        try:
            proc.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return
    process_group = proc.pid
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        proc.wait()
        return
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        proc.poll()
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    try:
        os.killpg(process_group, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def recover_public_unstarted_release(
    plan_dir: Path, request_id: str, current: dict[str, Any],
) -> dict[str, Any] | None:
    """Complete canonical non-start release before generic reconciliation."""
    send_claim = current.get("send_claim")
    if not isinstance(send_claim, str):
        return None
    run_dir = request_dir(plan_dir, request_id)
    intent_path = run_dir / "budget-releases" / f"{send_claim}.intent.json"
    if not intent_path.exists():
        return None
    combined_path = (
        staged_root(plan_dir) / "capacity-journals" / f"{request_id}.json"
    )
    if not staged_is_active(plan_dir) or not combined_path.exists():
        return None
    _, request = load_request(plan_dir, request_id)
    expected_intent = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "reason": "transport_not_started",
        "send_claim": send_claim,
        "reservation": request["budget_reservation"],
    }
    if read_json(intent_path) != expected_intent:
        raise ContractError("public unstarted release intent identity conflict")
    combined = read_json(combined_path)
    generation = require_non_negative_int(
        combined.get("reservation_generation", 1),
        "reservation_generation",
    )
    if generation < 1:
        raise ContractError("reservation_generation must be positive")
    release_path = _staged_release_journal_path(
        plan_dir, request_id, generation,
    )
    if not release_path.exists():
        raise ContractError(
            "public unstarted release intent lacks its generation journal"
        )
    release = read_json(release_path)
    if (
        release.get("phase") not in {"PREPARED", "RELEASED"}
        or release.get("dispatch_id") != request_id
        or release.get("reservation_generation") != generation
        or release.get("send_claim") != send_claim
        or release.get("reason") != "transport_not_started"
    ):
        raise ContractError("public unstarted release journal identity conflict")
    launch_path = run_dir / "transport-launches" / f"{send_claim}.json"
    launch = read_json(launch_path)
    if (
        launch.get("request_id") != request_id
        or launch.get("send_claim") != send_claim
        or launch.get("phase") not in {"CALLING", "NOT_STARTED"}
        or "pid" in launch
    ):
        raise ContractError(
            "public unstarted release lacks canonical non-start proof"
        )
    recovery = release_unstarted_frontier_budget(
        plan_dir,
        request,
        send_claim,
        OSError("recovered canonical transport_not_started release"),
    )
    update_transport_launch(
        plan_dir, request_id, send_claim, "NOT_STARTED",
        budget_recovery=recovery,
    )
    return transition(
        plan_dir,
        request_id,
        "CREATED",
        failure="transport_not_started",
        budget_recovery=recovery,
    )


def command_send_request(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    with request_send_lock(plan_dir, args.request_id):
        current = read_json(status_path(plan_dir, args.request_id))
        if current["state"] in {"RECEIVED", "VALIDATED", "APPLIED"}:
            return {"ok": True, "idempotent": True, **current}
        if current["state"] in {"SENT", "WAITING"}:
            recovered = recover_public_unstarted_release(
                plan_dir, args.request_id, current,
            )
            if recovered is None:
                return reconcile_frontier_locked(plan_dir, args.request_id)
            current = recovered
        if current["state"] == "PAUSED":
            raise ContractError("paused frontier requests are never redelivered; reconcile or create a new attempt")
        if current["state"] not in {"CREATED", "BUDGET_RESERVED"}:
            raise ContractError(f"cannot send request from state {current['state']}")
        if not 1 <= args.timeout <= 86400:
            raise ContractError("frontier transport timeout must be between 1 and 86400 seconds")
        reservation_present = frontier_budget_is_reserved(
            plan_dir, args.request_id,
        )
        try:
            policy = load_policy(plan_dir)
            request_path, request = load_request(plan_dir, args.request_id)
            validate_request_durable_context(
                plan_dir, request,
                require_current=current.get("state") != "APPLIED",
            )
        except ContractError as exc:
            recovery = None
            if reservation_present:
                recovery_request = {
                    "request_id": args.request_id,
                    "budget_reservation": current.get("budget_reservation"),
                }
                if not isinstance(
                    recovery_request["budget_reservation"], dict
                ):
                    transition(
                        plan_dir, args.request_id, "PAUSED",
                        failure="prelaunch_validation_failed_unrecoverable_budget",
                        validation_error=str(exc),
                    )
                    raise ContractError(
                        "prelaunch validation failed after reservation and the "
                        "durable reservation receipt is unavailable"
                    ) from exc
                recovery = release_frontier_prelaunch_reservation(
                    plan_dir,
                    recovery_request,
                    "prelaunch_validation_failed_before_transport",
                )
                transition(
                    plan_dir, args.request_id, "PAUSED",
                    failure="prelaunch_validation_failed",
                    validation_error=str(exc),
                    budget_recovery=recovery,
                )
            atomic_write_json(
                request_dir(plan_dir, args.request_id)
                / "prelaunch-validation-failure.json",
                {
                    "schema_version": SCHEMA_VERSION,
                    "request_id": args.request_id,
                    "failure": "prelaunch_validation_failed",
                    "error": str(exc),
                    "budget_reserved": reservation_present,
                    "budget_released": recovery is not None,
                    "budget_recovery": recovery,
                    "checked_at": utc_now(),
                },
            )
            raise
        deadline = parse_utc(request["deadline_at"])
        now = datetime.now(timezone.utc)
        if deadline <= now:
            recovery = release_frontier_prelaunch_reservation(
                plan_dir, request, "deadline_expired_before_transport",
            )
            transition(
                plan_dir, args.request_id, "EXPIRED",
                failure="deadline_expired", budget_recovery=recovery,
            )
            transition(
                plan_dir, args.request_id, "PAUSED",
                failure="deadline_expired", budget_recovery=recovery,
            )
            raise ContractError("frontier request deadline expired")
        if current.get("model_policy_sha256") != sha256_file(policy_path(plan_dir)):
            recovery = release_frontier_prelaunch_reservation(
                plan_dir, request, "model_policy_hash_changed_before_transport",
            )
            transition(
                plan_dir, args.request_id, "PAUSED",
                failure="model_policy_hash_changed", budget_recovery=recovery,
            )
            raise ContractError("frozen model policy hash changed")
        estimated_input_tokens = estimate_frontier_input_tokens(request_path, request)
        if estimated_input_tokens > request["budget_reservation"]["max_input_tokens"]:
            recovery = release_frontier_prelaunch_reservation(
                plan_dir, request, "context_exceeds_input_reservation_before_transport",
            )
            transition(
                plan_dir, args.request_id, "PAUSED",
                failure="context_exceeds_input_reservation",
                budget_recovery=recovery,
            )
            raise ContractError("estimated input exceeds reservation")
        review_profile = frontier_review_profile(policy, request)
        usage_floor = frontier_usage_floor(policy, review_profile)
        if usage_floor is not None and (
            request["budget_reservation"]["max_input_tokens"]
            < usage_floor["min_input_tokens"]
            or request["budget_reservation"]["max_output_tokens"]
            < usage_floor["min_output_tokens"]
        ):
            recovery = release_frontier_prelaunch_reservation(
                plan_dir, request,
                "reservation_below_chatgpt_usage_floor_before_transport",
            )
            transition(
                plan_dir, args.request_id, "PAUSED",
                failure="reservation_below_chatgpt_usage_floor",
                usage_floor=usage_floor,
                budget_recovery=recovery,
            )
            raise ContractError(
                "frontier reservation is below the frozen ChatGPT usage "
                f"floor/profile {usage_floor['profile_id']}: input >= "
                f"{usage_floor['min_input_tokens']}, output >= "
                f"{usage_floor['min_output_tokens']}"
            )
        try:
            preflight = preflight_frontier_transport(
                plan_dir, args.request_id, args.codex_bin, policy,
                review_profile,
            )
        except ContractError as exc:
            recovery = release_frontier_prelaunch_reservation(
                plan_dir, request, "frontier_preflight_failed_before_transport",
            )
            atomic_write_json(
                request_dir(plan_dir, args.request_id) / "preflight-failure.json",
                {
                    "schema_version": SCHEMA_VERSION,
                    "request_id": args.request_id,
                    "failure": "frontier_preflight_failed",
                    "error": str(exc),
                    "budget_reserved": reservation_present,
                    "budget_released": recovery is not None,
                    "budget_recovery": recovery,
                    "checked_at": utc_now(),
                },
            )
            if recovery is not None:
                transition(
                    plan_dir,
                    args.request_id,
                    "PAUSED",
                    failure="frontier_preflight_failed",
                    budget_recovery=recovery,
                )
            raise
        remaining_seconds = (deadline - datetime.now(timezone.utc)).total_seconds()
        if remaining_seconds <= 0:
            recovery = release_frontier_prelaunch_reservation(
                plan_dir, request, "deadline_expired_during_preflight",
            )
            transition(
                plan_dir, args.request_id, "EXPIRED",
                failure="deadline_expired", budget_recovery=recovery,
            )
            transition(
                plan_dir, args.request_id, "PAUSED",
                failure="deadline_expired", budget_recovery=recovery,
            )
            raise ContractError("frontier request deadline expired during preflight")
        effective_timeout = min(float(args.timeout), remaining_seconds)
        ledger = reserve_frontier_and_staged_budget(
            plan_dir, request, policy,
        )
        if os.environ.get("HARNESS_FAULT_AFTER_FRONTIER_LEDGER") == "1":
            raise ContractError("simulated crash after frontier ledger reservation")
        claim = uuid.uuid4().hex
        transition(
            plan_dir,
            args.request_id,
            "BUDGET_RESERVED",
            budget_snapshot=ledger,
            estimated_input_tokens=estimated_input_tokens,
            preflight=preflight,
        )
        update_transport_launch(
            plan_dir, args.request_id, claim, "PREPARED",
            budget_snapshot_sha256=sha256_json(ledger),
        )
        if os.environ.get("HARNESS_FAULT_AFTER_FRONTIER_RESERVATION") == "1":
            raise ContractError("simulated crash after frontier reservation")
        run_dir = request_dir(plan_dir, args.request_id)
        raw_response = run_dir / "response.raw.json"
        registry = CHECKPOINTS[request["checkpoint"]]
        allowed_recommendations = sorted(registry["recommendations"])
        prompt = (
            "You are the sparse frontier advisor for a research Harness. Read the immutable request below, "
            "audit only the bounded evidence it names, and return exactly the required JSON schema.\n"
            + (
                "This is the mandatory independent CP-01 review of the exact "
                "top-level execution plan declared as MiniMax M3 output inside Claude "
                "Code. Review architecture, task ordering, evaluator readiness, "
                "risk budget, figure requirements, missing dependencies, and "
                "whether execution should remain blocked. Do not defer this "
                "review to a later checkpoint.\n"
                if request["checkpoint"] == "CP-01"
                else ""
            )
            + "Copy these controller-computed response bindings exactly; do not recalculate them:\n"
            f"- request_sha256: {sha256_file(request_path)}\n"
            f"- context_manifest_sha256: {sha256_json(request['context_manifest'])}\n"
            f"- response_kind: {registry['kind']}\n"
            f"- recommendation: one of {json.dumps(allowed_recommendations)}\n"
            "Every findings[].evidence item must be exactly one full path or one SHA-256 value "
            "from context_manifest; use an empty findings array when no finding is needed. "
            "Do not add labels, prefixes, excerpts, or path/hash combinations to evidence items. "
            "A successful audit uses status=completed and blockers=[]; model_id and usage are "
            "transport-authoritative and will be overwritten by the controller.\n\n"
            + request_path.read_text()
        )
        cmd = build_frontier_command(
            preflight["codex_bin"], plan_dir, raw_response, policy,
            review_profile,
        )
        events_path = run_dir / "transport.events.jsonl"
        stderr_path = run_dir / "transport.stderr"
        transport_started = False
        try:
            with events_path.open("w") as events, stderr_path.open("w") as stderr:
                update_transport_launch(
                    plan_dir, args.request_id, claim, "CALLING",
                )
                transition(
                    plan_dir,
                    args.request_id,
                    "SENT",
                    model_id=review_profile["model"],
                    reviewer_profile=review_profile,
                    send_claim=claim,
                )
                transition(
                    plan_dir,
                    args.request_id,
                    "WAITING",
                    transport=policy.get("frontier_transport", "codex-default"),
                    send_claim=claim,
                )
                proc = subprocess.Popen(
                    cmd,
                    cwd=plan_dir,
                    stdin=subprocess.PIPE,
                    stdout=events,
                    stderr=stderr,
                    text=True,
                    start_new_session=True,
                )
                transport_started = True
                update_transport_launch(
                    plan_dir, args.request_id, claim, "STARTED", pid=proc.pid,
                )
                try:
                    proc.communicate(input=prompt, timeout=effective_timeout)
                except subprocess.TimeoutExpired:
                    try:
                        update_transport_launch(
                            plan_dir, args.request_id, claim, "OUTCOME_UNCERTAIN",
                            failure="timeout",
                        )
                    finally:
                        terminate_transport_process_group(proc)
                    raise
                finally:
                    events.flush()
                    stderr.flush()
                    os.fsync(events.fileno())
                    os.fsync(stderr.fileno())
        except OSError as exc:
            if not transport_started:
                recovery = release_unstarted_frontier_budget(
                    plan_dir, request, claim, exc,
                )
                update_transport_launch(
                    plan_dir,
                    args.request_id,
                    claim,
                    "NOT_STARTED",
                    budget_recovery=recovery,
                )
                transition(
                    plan_dir,
                    args.request_id,
                    "CREATED",
                    failure="transport_not_started",
                    budget_recovery=recovery,
                )
                raise ContractError(f"Codex transport did not start: {exc}") from exc
            terminate_transport_process_group(proc)
            transition(plan_dir, args.request_id, "PAUSED", failure="transport_outcome_uncertain")
            raise ContractError(f"Codex transport outcome is uncertain: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            transition(plan_dir, args.request_id, "PAUSED", failure="transport_outcome_uncertain")
            raise ContractError(f"Codex transport outcome is uncertain: {exc}") from exc
        if proc.returncode != 0:
            failure = classify_frontier_transport_failure(
                stderr_path.read_text(errors="replace"),
                events_path.read_text(errors="replace"),
            )
            update_transport_launch(
                plan_dir,
                args.request_id,
                claim,
                "FAILED",
                exit_code=proc.returncode,
                **failure,
            )
            transition(
                plan_dir, args.request_id, "PAUSED",
                exit_code=proc.returncode, **failure,
            )
            raise ContractError(f"Codex transport failed with exit {proc.returncode}")
        try:
            validate_frontier_transport_events(events_path)
        except ContractError as exc:
            update_transport_launch(
                plan_dir,
                args.request_id,
                claim,
                "FAILED",
                exit_code=proc.returncode,
                failure="frontier_surface_violation",
            )
            transition(
                plan_dir,
                args.request_id,
                "PAUSED",
                failure="frontier_surface_violation",
                validation_error=str(exc),
            )
            raise
        update_transport_launch(
            plan_dir, args.request_id, claim, "COMPLETED", exit_code=0,
        )
        return reconcile_frontier_locked(plan_dir, args.request_id)


def command_reconcile_request(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    with request_send_lock(plan_dir, args.request_id):
        current = read_json(status_path(plan_dir, args.request_id))
        allowed = {"SENT", "WAITING", "RECEIVED", "VALIDATED", "APPLIED"}
        if (
            current["state"] == "PAUSED"
            and current.get("failure") == "transport_outcome_uncertain"
        ):
            allowed.add("PAUSED")
        if current["state"] not in allowed:
            raise ContractError(f"cannot reconcile frontier request from state {current['state']}")
        return reconcile_frontier_locked(plan_dir, args.request_id)


def command_validate_response(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    request_path, request = load_request(plan_dir, args.request_id)
    current = read_json(status_path(plan_dir, args.request_id))
    if current["state"] in {"VALIDATED", "APPLIED"}:
        return {"ok": True, "idempotent": True, **current}
    recoverable_overrun = (
        current["state"] == "PAUSED"
        and current.get("failure") == "response_budget_overrun"
    )
    if current["state"] != "RECEIVED" and not recoverable_overrun:
        raise ContractError(f"cannot validate response from state {current['state']}")
    response_path = request_dir(plan_dir, args.request_id) / "response.json"

    def pause_validation_failure(exc: ContractError) -> None:
        if isinstance(exc, FrontierBudgetOverrunError):
            failure = "response_budget_overrun"
        elif isinstance(exc, FrontierSemanticResponseError):
            failure = "response_semantic_inconsistency"
        else:
            failure = "response_invalid"
        transition(plan_dir, args.request_id, "INVALID", validation_error=str(exc))
        transition(
            plan_dir, args.request_id, "PAUSED", failure=failure,
            validation_error=str(exc),
        )

    try:
        response, _, _ = validate_frontier_response_integrity(
            plan_dir, args.request_id, current, response_path,
            allow_unreconciled_overrun=True,
        )
    except ContractError as exc:
        pause_validation_failure(exc)
        raise
    if parse_utc(response["completed_at"]) > parse_utc(request["deadline_at"]):
        transition(
            plan_dir, args.request_id, "EXPIRED",
            failure="response_after_deadline",
        )
        transition(
            plan_dir, args.request_id, "PAUSED",
            failure="response_after_deadline",
        )
        raise ContractError("frontier response arrived after the frozen deadline")
    try:
        projection = frontier_overrun_projection(request, response)
        if any(projection["delta"].values()):
            reconcile_frontier_budget_overrun(
                plan_dir, args.request_id, request, request_path,
                response, response_path,
            )
        validate_frontier_response_integrity(
            plan_dir, args.request_id, current, response_path,
        )
    except ContractError as exc:
        pause_validation_failure(exc)
        raise
    transition(
        plan_dir, args.request_id, "VALIDATED", validated_response_path=str(response_path),
        validated_response_sha256=sha256_file(response_path),
        validated_request_sha256=sha256_file(request_path),
        validated_context_manifest_sha256=sha256_json(request["context_manifest"]),
        budget_overrun_receipt=(
            str(frontier_overrun_receipt_path(plan_dir, args.request_id))
            if frontier_overrun_receipt_path(plan_dir, args.request_id).is_file()
            else None
        ),
        failure=None, validation_error=None, advisory_only=True,
    )
    return {"ok": True, "request_id": args.request_id, "state": "VALIDATED", "response_path": str(response_path)}


def command_apply_response(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    request_path, request = load_request(plan_dir, args.request_id)
    current = read_json(status_path(plan_dir, args.request_id))
    if current["state"] == "APPLIED":
        event = current.get("applied_event", {})
        if event.get("transition") != args.dependent_transition:
            raise ContractError("request was applied to a different dependent transition")
        if staged_is_active(plan_dir) and request["checkpoint"] == "CP-01":
            staged_authorize_first_stage(
                plan_dir, args.request_id,
                transition_receipt_path(
                    plan_dir, args.dependent_transition, args.request_id,
                ),
            )
        return {"ok": True, "idempotent": True, **current}
    if current["state"] != "VALIDATED":
        raise ContractError(f"cannot apply advisory response from state {current['state']}")
    registry_key = (request["checkpoint"], request.get("checkpoint_subtype"))
    expected = DEPENDENT_TRANSITIONS.get(registry_key)
    if expected is None or args.dependent_transition != expected[0]:
        raise ContractError("dependent transition does not match checkpoint registry")
    response_path = Path(current["validated_response_path"])
    response, request, request_path = validate_frontier_response_integrity(
        plan_dir, args.request_id, current, response_path,
    )
    policy = load_policy(plan_dir)
    review_contract = validate_top_level_plan_review_contract(request)
    expected_profile = frontier_review_profile(policy, request)
    if (
        review_contract is not None
        and review_contract["model_policy_sha256"] != sha256_file(
            policy_path(plan_dir)
        )
    ):
        raise ContractError("frontier review contract model policy hash changed")
    if response.get("model_id") != expected_profile["model"]:
        raise ContractError("frontier response model does not match frozen review profile")
    profile_is_required = (
        review_contract is not None
        or current.get("reviewer_profile") is not None
    )
    if profile_is_required and current.get("reviewer_profile") != expected_profile:
        raise ContractError("frontier status review profile does not match frozen policy")
    if current.get("validated_response_sha256") != sha256_file(response_path):
        raise ContractError("validated response hash changed before apply")
    if current.get("validated_request_sha256") != sha256_file(request_path):
        raise ContractError("validated request hash changed before apply")
    if current.get("validated_context_manifest_sha256") != sha256_json(request["context_manifest"]):
        raise ContractError("validated context hash changed before apply")
    if response["recommendation"] not in expected[1]:
        raise ContractError("frontier recommendation leaves dependent transition blocked")
    event = {
        "schema_version": SCHEMA_VERSION,
        "ts": utc_now(),
        "event": "frontier_advice_applied",
        "request_id": args.request_id,
        "plan_id": request["plan_id"],
        "checkpoint": request["checkpoint"],
        "checkpoint_subtype": request.get("checkpoint_subtype"),
        "transition": args.dependent_transition,
        "request_sha256": sha256_file(request_path),
        "response_sha256": sha256_file(response_path),
        "context_manifest_sha256": sha256_json(request["context_manifest"]),
        "response_path": current["validated_response_path"],
        "reviewer_profile": expected_profile,
        "model_policy_sha256": sha256_file(policy_path(plan_dir)),
        "advisory_only": True,
        "lifecycle_mutation": False,
        "controller_note": args.controller_note,
    }
    target = transition_receipt_path(plan_dir, args.dependent_transition, args.request_id)
    lock_path = frontier_root(plan_dir) / ".transition.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current = read_json(status_path(plan_dir, args.request_id))
        validate_frontier_response_integrity(plan_dir, args.request_id, current, response_path)
        if (
            profile_is_required
            and current.get("reviewer_profile") != expected_profile
        ):
            raise ContractError(
                "frontier status review profile changed while applying"
            )
        if current.get("validated_response_sha256") != sha256_file(response_path):
            raise ContractError("validated response hash changed while applying")
        logical_request_id = frontier_logical_request_id(request)
        for sibling_path in (
            frontier_root(plan_dir) / "requests"
        ).glob("far_*/request.json"):
            sibling = read_json(sibling_path)
            if (
                sibling["request_id"] != args.request_id
                and frontier_logical_request_id(sibling) == logical_request_id
                and read_json(status_path(
                    plan_dir, sibling["request_id"],
                )).get("state") == "APPLIED"
            ):
                raise ContractError(
                    "logical frontier checkpoint was already applied by another attempt"
                )
        if target.exists():
            prior = read_json(target)
            transition(plan_dir, args.request_id, "APPLIED", applied_event=prior)
            if staged_is_active(plan_dir) and request["checkpoint"] == "CP-01":
                staged_authorize_first_stage(plan_dir, args.request_id, target)
            return {"ok": True, "idempotent": True, "request_id": args.request_id, "state": "APPLIED", "event": prior}
        atomic_write_json(target, event, immutable=True)
        append_jsonl(plan_dir / "state" / "controller_transitions.jsonl", event)
        transition(plan_dir, args.request_id, "APPLIED", applied_event=event)
    if staged_is_active(plan_dir) and request["checkpoint"] == "CP-01":
        staged_authorize_first_stage(plan_dir, args.request_id, target)
    return {"ok": True, "request_id": args.request_id, "state": "APPLIED", "event": event}


def command_commit_durable_frontier_result(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    with durable_result_commit_lock(plan_dir, f"frontier:{args.request_id}"):
        return commit_durable_frontier_result_locked(args, plan_dir)


def commit_durable_frontier_result_locked(
    args: argparse.Namespace, plan_dir: Path,
) -> dict[str, Any]:
    target = durable_root(plan_dir) / "frontier_commits" / f"{args.request_id}.json"
    if target.exists():
        return {"ok": True, "idempotent": True, **read_json(target)}
    request_path, request = load_request(plan_dir, args.request_id)
    capsule = validate_request_durable_context(
        plan_dir, request, require_current=True,
    )
    if capsule is None:
        if request.get("checkpoint") == "STAGE-REVIEW":
            raise ContractError(
                "STAGE-REVIEW is persisted with record-strong-stage-review; "
                "commit-durable-frontier-result is only for requests prebound "
                "to a durable context capsule"
            )
        raise ContractError("frontier request is not bound to a durable context capsule")
    current = read_json(status_path(plan_dir, args.request_id))
    if current.get("state") != "APPLIED":
        raise ContractError("durable frontier commit requires an APPLIED controller transition")
    registry_key = (request["checkpoint"], request.get("checkpoint_subtype"))
    expected = DEPENDENT_TRANSITIONS.get(registry_key)
    if expected is None:
        raise ContractError("frontier request has no registered dependent transition")
    applied_event = current.get("applied_event")
    if (
        not isinstance(applied_event, dict)
        or applied_event.get("transition") != expected[0]
        or applied_event.get("request_id") != args.request_id
        or applied_event.get("request_sha256") != sha256_file(request_path)
        or applied_event.get("lifecycle_mutation") is not False
        or applied_event.get("advisory_only") is not True
    ):
        raise ContractError("frontier APPLIED state is not bound to the registered controller transition")
    transition_path = transition_receipt_path(
        plan_dir, expected[0], args.request_id,
    )
    if not transition_path.is_file() or read_json(transition_path) != applied_event:
        raise ContractError("canonical frontier transition receipt is missing or changed")
    result_path = (
        durable_root(plan_dir) / "controller_results"
        / f"frontier-{args.request_id}.json"
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "capsule_id": capsule["capsule_id"],
        "task_id": capsule["task_id"],
        "evidence": [{
            "path": str(transition_path),
            "sha256": sha256_file(transition_path),
        }],
    }
    if result_path.exists():
        if read_json(result_path) != result:
            raise ContractError("durable frontier controller-result identity collision")
    else:
        atomic_write_json(result_path, result, immutable=True)
    run_dir = request_dir(plan_dir, args.request_id)
    journal_path = run_dir / "durable-commit-journal.json"
    journal = read_json(journal_path) if journal_path.exists() else None
    if journal is None:
        journal = {
            "schema_version": SCHEMA_VERSION,
            "phase": "PREPARED",
            "request_id": args.request_id,
            "capsule_id": capsule["capsule_id"],
            "transition": expected[0],
            "transition_receipt_sha256": sha256_file(transition_path),
            "controller_result_path": str(result_path),
            "controller_result_sha256": sha256_file(result_path),
            "prepared_at": utc_now(),
        }
        atomic_write_json(journal_path, journal)
    elif any(
        journal.get(field) != value for field, value in (
            ("request_id", args.request_id),
            ("capsule_id", capsule["capsule_id"]),
            ("transition", expected[0]),
            ("transition_receipt_sha256", sha256_file(transition_path)),
            ("controller_result_sha256", sha256_file(result_path)),
        )
    ):
        raise ContractError("durable frontier commit journal correlation mismatch")
    applied: dict[str, Any] | None = None
    evidence_root = durable_root(plan_dir) / "evidence"
    if evidence_root.exists():
        for evidence_path in evidence_root.glob("evidence_*.json"):
            evidence = read_json(evidence_path)
            if (
                evidence.get("capsule_id") == capsule["capsule_id"]
                and evidence.get("result_path") == str(result_path)
                and evidence.get("result_sha256") == sha256_file(result_path)
            ):
                applied = {
                    "ok": True,
                    "recovered": True,
                    "evidence_record": str(evidence_path),
                    "evidence_id": evidence["evidence_id"],
                    "projection": read_json(durable_root(plan_dir) / "projection.json"),
                }
                break
    if applied is None:
        applied = command_apply_work_unit_result(argparse.Namespace(
            plan_dir=str(plan_dir),
            capsule=request["durable_context"]["capsule_path"],
            result=str(result_path),
        ))
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": request["plan_id"],
        "request_id": args.request_id,
        "capsule_id": capsule["capsule_id"],
        "capsule_sha256": capsule["capsule_sha256"],
        "transition": expected[0],
        "transition_receipt_path": str(transition_path),
        "transition_receipt_sha256": sha256_file(transition_path),
        "evidence_id": applied["evidence_id"],
        "evidence_record": applied["evidence_record"],
        "state_revision": applied["projection"]["state_revision"],
        "committed_at": utc_now(),
    }
    atomic_write_json(target, receipt, immutable=True)
    journal.update({
        "phase": "COMMITTED",
        "commit_receipt_path": str(target),
        "commit_receipt_sha256": sha256_file(target),
        "committed_at": receipt["committed_at"],
    })
    atomic_write_json(journal_path, journal)
    return {"ok": True, "commit_receipt": str(target), **receipt}


def command_status(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    return read_json(status_path(plan_dir, args.request_id))


def command_assert_transition(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    receipt = check_transition_receipt(
        plan_dir, args.plan_id, args.transition, getattr(args, "request_id", None),
    )
    current = read_json(status_path(plan_dir, receipt["request_id"]))
    response_path = request_dir(plan_dir, receipt["request_id"]) / "response.json"
    validate_frontier_response_integrity(plan_dir, receipt["request_id"], current, response_path)
    if receipt.get("response_sha256") != sha256_file(response_path):
        raise ContractError("transition response hash changed")
    return {"ok": True, "receipt": receipt}


def command_expire_request(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    with request_send_lock(plan_dir, args.request_id):
        current = read_json(status_path(plan_dir, args.request_id))
        if current["state"] in {"EXPIRED", "PAUSED"} and current.get("failure") == "deadline_expired":
            return {"ok": True, "idempotent": True, **current}
        if current["state"] not in {"CREATED", "BUDGET_RESERVED", "SENT", "WAITING"}:
            raise ContractError(f"cannot expire request from state {current['state']}")
        now = parse_utc(args.now)
        if now <= parse_utc(current["deadline_at"]):
            raise ContractError("request deadline has not passed")
        recovery = None
        if (
            current["state"] in {"CREATED", "BUDGET_RESERVED"}
            and frontier_budget_is_reserved(plan_dir, args.request_id)
        ):
            recovery_request = {
                "request_id": args.request_id,
                "budget_reservation": current.get("budget_reservation"),
            }
            if not isinstance(recovery_request["budget_reservation"], dict):
                raise ContractError(
                    "durable reservation receipt is unavailable for prelaunch expiry"
                )
            recovery = release_frontier_prelaunch_reservation(
                plan_dir, recovery_request, "deadline_expired_before_transport",
            )
        transition(
            plan_dir, args.request_id, "EXPIRED",
            expired_at=args.now, failure="deadline_expired",
            budget_recovery=recovery,
        )
        paused = transition(
            plan_dir, args.request_id, "PAUSED",
            expired_at=args.now, failure="deadline_expired",
            budget_recovery=recovery,
        )
        return {"ok": True, **paused}


def staged_root(plan_dir: Path) -> Path:
    return plan_dir / "state" / "staged_research" / "v1"


def staged_state_path(plan_dir: Path) -> Path:
    return staged_root(plan_dir) / "state.json"


def staged_is_active(plan_dir: Path) -> bool:
    return staged_state_path(plan_dir).is_file()


def staged_projection_payload(
    plan_dir: Path, state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the legacy progress view solely from canonical staged artifacts."""
    root = staged_root(plan_dir)
    state_path = staged_state_path(plan_dir)
    state = state or read_json(state_path)
    audit_path = root / "audit.jsonl"
    audit_sha256 = sha256_file(audit_path) if audit_path.exists() else hashlib.sha256(b"").hexdigest()
    audit_records = [
        strict_json_loads(line) for line in audit_path.read_text().splitlines()
        if line.strip()
    ] if audit_path.exists() else []
    capacity_path = root / "capacity-ledger.json"
    capacity = read_json(capacity_path) if capacity_path.exists() else None
    stage_dir = staged_stage_dir(plan_dir, state["active_stage_id"])
    usage_path = stage_dir / "usage-ledger.json"
    usage = read_json(usage_path) if usage_path.exists() else {}
    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in (
        "envelope.json", "preflight.json", "candidate.json", "decision.json",
        "stage-report.json", "strong-review.json", "next-stage.json",
    ):
        path = stage_dir / name
        artifacts[name.removesuffix(".json").replace("-", "_")] = (
            {"path": str(path), "sha256": sha256_file(path)}
            if path.is_file() else None
        )
    return {
        "schema_version": 1,
        "projection_version": "staged-research-progress/v1",
        "authority": "state/staged_research/v1",
        "authoritative": False,
        "plan_id": state["plan_id"],
        "status": state["state"],
        "active_stage_id": state["active_stage_id"],
        "contract_version": state["contract_version"],
        "current_incumbent_sha256": state["current_incumbent_sha256"],
        "next_stage_compiled": state["next_stage_compiled"],
        "canonical": {
            "audit_revision": state["audit_revision"],
            "state_path": str(state_path),
            "state_sha256": sha256_file(state_path),
            "audit_path": str(audit_path),
            "audit_sha256": audit_sha256,
            "capacity_path": str(capacity_path),
            "capacity_sha256": (
                sha256_file(capacity_path) if capacity_path.exists() else None
            ),
        },
        "capacity": staged_capacity_projection(capacity) if capacity else None,
        "pause_or_stop_reason": usage.get("stop_reason"),
        "recent_audit": [
            {
                "audit_revision": record["audit_revision"],
                "event": record["event"],
                "recorded_at": record["recorded_at"],
            }
            for record in audit_records[-5:]
        ],
        "artifacts": artifacts,
    }


def staged_dossier_bytes(projection: dict[str, Any]) -> bytes:
    """Render a byte-stable, one-page human view of the staged controller."""
    canonical = projection["canonical"]
    capacity = projection.get("capacity") or {}
    artifact_lines = []
    for name, binding in sorted(projection["artifacts"].items()):
        artifact_lines.append(
            f"- {name}: {binding['sha256']} ({binding['path']})"
            if binding else f"- {name}: pending"
        )
    capacity_lines = [
        f"- worker dispatches remaining: {capacity.get('worker_dispatch_remaining', 'n/a')}",
        f"- stage review remaining: {capacity.get('stage_review_remaining', 'n/a')}",
        f"- named checkpoints remaining: {capacity.get('checkpoint_remaining', 'n/a')}",
    ]
    audit_lines = [
        f"- r{item['audit_revision']} {item['event']} — {item['recorded_at']}"
        for item in projection["recent_audit"]
    ] or ["- none"]
    text = "\n".join([
        "# Research dossier", "",
        "> Generated projection only. It cannot authorize controller transitions.", "",
        f"- plan: {projection['plan_id']}",
        f"- state: {projection['status']}",
        f"- active stage: {projection['active_stage_id']}",
        f"- contract: {projection['contract_version']}",
        f"- incumbent: {projection['current_incumbent_sha256']}",
        f"- pause/stop reason: {projection.get('pause_or_stop_reason') or 'none'}",
        f"- canonical audit revision: {canonical['audit_revision']}",
        f"- canonical state sha256: {canonical['state_sha256']}",
        f"- canonical audit sha256: {canonical['audit_sha256']}", "",
        "## Capacity", "", *capacity_lines, "", "## Current-stage artifacts", "",
        *artifact_lines, "", "## Recent canonical events", "", *audit_lines, "",
    ])
    return text.encode("utf-8")


def staged_refresh_projections(
    plan_dir: Path, state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Overwrite derived views; their prior bytes are deliberately not inputs."""
    projection = staged_projection_payload(plan_dir, state)
    progress_path = plan_dir / "state" / "progress.json"
    dossier_path = plan_dir / "state" / "research-dossier.md"
    atomic_write_json(progress_path, projection)
    atomic_write_bytes(dossier_path, staged_dossier_bytes(projection))
    return {
        "progress_path": str(progress_path),
        "progress_sha256": sha256_file(progress_path),
        "dossier_path": str(dossier_path),
        "dossier_sha256": sha256_file(dossier_path),
        "audit_revision": projection["canonical"]["audit_revision"],
    }


def command_rebuild_staged_projections(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    with staged_transaction_lock(plan_dir):
        state, _ = _staged_reconcile_audit_revision_locked(plan_dir)
        # Full canonical validation occurs before emitting a view.
        state = staged_load_state(plan_dir)
        result = staged_refresh_projections(plan_dir, state)
    return {"ok": True, **result}


def staged_require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ContractError(f"{field} must be a lowercase sha256")
    return value


def staged_require_id(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value)
    ):
        raise ContractError(f"{field} must be an immutable identifier")
    return value


def staged_copy_immutable(source: Path, target: Path) -> dict[str, Any]:
    value = read_json(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if canonical_json(read_json(target)) != canonical_json(value):
            raise ContractError(f"immutable staged artifact collision: {target}")
    else:
        # Authorization receipts bind the exact source bytes.  Re-serializing a
        # valid JSON document here changes its sha256 whenever key order or
        # whitespace differs, which used to make a freshly initialized stage
        # fail its own lineage check.  Preserve the authorized bytes exactly.
        atomic_write_bytes(target, source.read_bytes(), immutable=True)
    return value


def staged_repair_legacy_canonical_copies(
    plan_dir: Path,
    contract_path: Path,
    envelope_path: Path,
    evaluation_path: Path,
    capacity_path: Path,
    authorization_path: Path,
) -> bool:
    """Repair the v0.16.1 canonical-copy lineage defect without resetting state.

    The repair is deliberately narrow: the signed source and staged contract
    must be JSON-semantically identical, the current staged bytes must still
    match controller state, and the applied authorization must bind the exact
    supplied source bytes plus the already-active first-stage envelope.
    """
    state_path = staged_state_path(plan_dir)
    if not state_path.is_file():
        return False
    state = read_json(state_path)
    root = staged_root(plan_dir)
    targets = (
        (
            contract_path,
            root / "contracts" / f"{state['contract_version']}.json",
            "contract_sha256",
        ),
        (
            envelope_path,
            staged_stage_dir(plan_dir, state["active_stage_id"]) / "envelope.json",
            "active_stage_envelope_sha256",
        ),
        (evaluation_path, root / "evaluation-profile.json", "evaluation_profile_sha256"),
        (capacity_path, root / "checkpoint-capacity.json", "checkpoint_capacity_sha256"),
    )
    if any(not target.is_file() for _, target, _ in targets):
        return False
    changes: list[tuple[Path, Path, str, str]] = []
    for source, target, field in targets:
        source_sha = sha256_file(source)
        target_sha = sha256_file(target)
        state_sha = state.get(field)
        if source_sha == target_sha == state_sha:
            continue
        if canonical_json(read_json(source)) != canonical_json(read_json(target)):
            return False
        canonical_copy_sha = atomic_json_sha256(read_json(source))
        if not (
            (target_sha == state_sha == canonical_copy_sha)
            or (target_sha == source_sha and state_sha == canonical_copy_sha)
        ):
            return False
        changes.append((source, target, field, source_sha))
    audit_path = root / "audit.jsonl"
    initialized_hashes = {
        record.get("contract_sha256")
        for record in (
            strict_json_loads(line)
            for line in audit_path.read_text().splitlines()
            if line.strip()
        )
        if record.get("event") == "staged_research_initialized"
        and record.get("contract_version") == state["contract_version"]
    } if audit_path.exists() else set()
    legacy_audit_mismatch = bool(initialized_hashes) and (
        sha256_file(contract_path) not in initialized_hashes
    )
    if not changes and not legacy_audit_mismatch:
        return False
    if authorization_path != Path(state["owner_authorization_path"]).resolve():
        return False
    authorization = validate_applied_action_receipt(
        plan_dir, authorization_path, "authorize_contract",
    )
    contract = read_json(contract_path)
    details = authorization.get("details", {})
    expected = {
        "contract_version": state["contract_version"],
        "contract_sha256": sha256_file(contract_path),
        "stage_id": state["active_stage_id"],
        "stage_envelope_sha256": sha256_file(envelope_path),
    }
    if (
        authorization.get("record_id") != contract["authorization_receipt_id"]
        or any(details.get(key) != value for key, value in expected.items())
    ):
        return False
    if changes:
        for source, target, field, source_sha in changes:
            if sha256_file(target) != source_sha:
                atomic_write_bytes(target, source.read_bytes(), immutable=True)
            state[field] = source_sha
        atomic_write_json(state_path, state)
    return True


def _staged_reconcile_audit_revision_locked(
    plan_dir: Path,
) -> tuple[dict[str, Any], Path]:
    state_path = staged_state_path(plan_dir)
    state = read_json(state_path)
    audit_path = staged_root(plan_dir) / "audit.jsonl"
    prior_records = [
        strict_json_loads(line)
        for line in audit_path.read_text().splitlines()
        if line.strip()
    ] if audit_path.exists() else []
    revisions = [item.get("audit_revision") for item in prior_records]
    if revisions != list(range(1, len(revisions) + 1)):
        raise ContractError("staged audit revisions are not contiguous")
    if len(revisions) == state["audit_revision"] + 1:
        # Recover a process exit after append and before the state revision write.
        state["audit_revision"] = len(revisions)
        atomic_write_json(state_path, state)
    elif len(revisions) != state["audit_revision"]:
        raise ContractError("staged audit revision disagrees with controller state")
    return state, audit_path


def _staged_append_audit_locked(
    plan_dir: Path, event: str, details: dict[str, Any],
) -> dict[str, Any]:
    state, audit_path = _staged_reconcile_audit_revision_locked(plan_dir)
    state_path = staged_state_path(plan_dir)
    revision = state["audit_revision"] + 1
    record = {
        "schema_version": 1,
        "audit_revision": revision,
        "event": event,
        "recorded_at": utc_now(),
        **details,
    }
    append_jsonl(audit_path, record)
    state["audit_revision"] = revision
    atomic_write_json(state_path, state)
    staged_refresh_projections(plan_dir, state)
    return record


def _staged_ensure_audit_once_locked(
    plan_dir: Path,
    event: str,
    identity: dict[str, Any],
    details: dict[str, Any],
) -> dict[str, Any]:
    """Complete one correlated audit effect without duplicating it on replay."""
    _, audit_path = _staged_reconcile_audit_revision_locked(plan_dir)
    records = [
        strict_json_loads(line)
        for line in audit_path.read_text().splitlines()
        if line.strip()
    ] if audit_path.exists() else []
    matches = [
        record for record in records
        if record.get("event") == event
        and all(record.get(key) == value for key, value in identity.items())
    ]
    if len(matches) > 1:
        raise ContractError(f"duplicate staged audit identity for {event}")
    if matches:
        expected = {**identity, **details}
        if any(matches[0].get(key) != value for key, value in expected.items()):
            raise ContractError(f"staged audit identity conflict for {event}")
        return matches[0]
    return _staged_append_audit_locked(
        plan_dir, event, {**identity, **details},
    )


def _staged_fault_after_artifact(operation: str) -> None:
    """Deterministic process-exit boundary for artifact-first recovery tests."""
    if os.environ.get("HARNESS_FAULT_AFTER_STAGED_ARTIFACT") == operation:
        os._exit(88)


def staged_append_audit(
    plan_dir: Path, event: str, details: dict[str, Any],
) -> dict[str, Any]:
    with staged_transaction_lock(plan_dir):
        return _staged_append_audit_locked(plan_dir, event, details)


def staged_ensure_audit_once(
    plan_dir: Path, event: str, identity: dict[str, Any], details: dict[str, Any],
) -> dict[str, Any]:
    with staged_transaction_lock(plan_dir):
        return _staged_ensure_audit_once_locked(
            plan_dir, event, identity, details,
        )


def staged_load_state(plan_dir: Path) -> dict[str, Any]:
    state = read_json(staged_state_path(plan_dir))
    validate_schema(state, read_json(STAGED_RESEARCH_SCHEMA))
    root = staged_root(plan_dir)
    contract_path = root / "contracts" / f"{state['contract_version']}.json"
    envelope_path = (
        root / "stages" / state["active_stage_id"] / "envelope.json"
    )
    evaluation_path = root / "evaluation-profile.json"
    capacity_path = root / "checkpoint-capacity.json"
    checks = (
        (contract_path, state["contract_sha256"], "optimization contract"),
        (
            envelope_path, state["active_stage_envelope_sha256"],
            "active stage envelope",
        ),
        (
            evaluation_path, state["evaluation_profile_sha256"],
            "evaluation profile",
        ),
        (
            capacity_path, state["checkpoint_capacity_sha256"],
            "checkpoint capacity",
        ),
    )
    for path, expected, label in checks:
        if not path.is_file() or sha256_file(path) != expected:
            raise ContractError(f"{label} hash changed")
    authorization_path = Path(state["owner_authorization_path"])
    if (
        not authorization_path.is_file()
        or sha256_file(authorization_path) != state["owner_authorization_sha256"]
    ):
        raise ContractError("owner authorization receipt changed")
    owner_authorization = validate_applied_action_receipt(
        plan_dir, authorization_path, state["owner_authorization_action"],
    )
    stage_authorization_path = Path(state["active_stage_authorization_path"])
    if (
        not stage_authorization_path.is_file()
        or sha256_file(stage_authorization_path)
        != state["active_stage_authorization_sha256"]
    ):
        raise ContractError("active stage authorization receipt changed")
    if state["active_stage_authorization_action"] == "derived_continuation":
        stage_authorization = validate_staged_continuation_receipt(
            plan_dir, stage_authorization_path,
        )
    else:
        stage_authorization = validate_applied_action_receipt(
            plan_dir, stage_authorization_path,
            state["active_stage_authorization_action"],
        )
    contract = read_json(contract_path)
    envelope = read_json(envelope_path)
    evaluation = read_json(evaluation_path)
    staged_validate_envelope(
        envelope, state["contract_version"],
        envelope.get("incumbent_sha256"),
        first=envelope.get("source_cycle_id") is None,
        plan_dir=plan_dir, require_manifest=False,
    )
    staged_validate_evaluation_profile(evaluation)
    staged_validate_profile_envelope_compatibility(
        evaluation, envelope, strict=False,
    )
    authorization_checks = {
        "contract_version": state["contract_version"],
        "contract_sha256": state["contract_sha256"],
        "stage_id": state["active_stage_id"],
        "stage_envelope_sha256": state["active_stage_envelope_sha256"],
    }
    if (
        owner_authorization.get("record_id") != contract["authorization_receipt_id"]
        or any(
            stage_authorization.get("details", {}).get(key) != value
            for key, value in authorization_checks.items()
        )
        or envelope["contract_version"] != state["contract_version"]
    ):
        raise ContractError("owner authorization lineage no longer matches staged state")
    # progress.json and the dossier are caches.  Rebuilding them here ensures a
    # hand edit can never become an input to a canonical transition.
    staged_refresh_projections(plan_dir, state)
    return state


def validate_staged_continuation_receipt(
    plan_dir: Path, receipt_path: Path,
) -> dict[str, Any]:
    root = staged_root(plan_dir)
    receipt = read_json(receipt_path)
    continuation_id = receipt.get("continuation_id")
    canonical = root / "continuation-receipts" / f"{continuation_id}.json"
    required = {
        "schema_version", "continuation_id", "authority",
        "crossing_index", "max_automatic_crossings", "source_stage_id",
        "next_stage_id", "initial_authorization_path",
        "initial_authorization_sha256", "initial_authorization_record_id",
        "source_decision_sha256", "stage_report_sha256", "strong_review_sha256",
        "next_stage_envelope_sha256", "details", "derived_at",
    }
    if (
        receipt_path.resolve() != canonical.resolve()
        or set(receipt) != required
        or receipt.get("schema_version") != 1
        or receipt.get("authority") != "bounded_initial_human_authorization"
        or receipt.get("crossing_index") != 1
        or receipt.get("max_automatic_crossings") != 1
    ):
        raise ContractError("derived continuation receipt has an invalid closed shape")
    initial_path = Path(receipt["initial_authorization_path"])
    if (
        not initial_path.is_file()
        or sha256_file(initial_path) != receipt["initial_authorization_sha256"]
    ):
        raise ContractError("initial continuation authority changed")
    initial = validate_applied_action_receipt(
        plan_dir, initial_path, "authorize_contract",
    )
    bounded = initial.get("details", {}).get("bounded_continuation_authority")
    if (
        initial.get("record_id") != receipt["initial_authorization_record_id"]
        or not isinstance(bounded, dict)
        or bounded.get("max_automatic_crossings") != 1
        or bounded.get("allowed_stage_ids") != [receipt["next_stage_id"]]
        or bounded.get("silence_is_approval") is not False
    ):
        raise ContractError("initial authorization does not cover this continuation")
    source_dir = staged_stage_dir(plan_dir, receipt["source_stage_id"])
    next_envelope = staged_stage_dir(
        plan_dir, receipt["next_stage_id"],
    ) / "envelope.json"
    bindings = (
        (source_dir / "decision.json", "source_decision_sha256"),
        (source_dir / "stage-report.json", "stage_report_sha256"),
        (source_dir / "strong-review.json", "strong_review_sha256"),
        (next_envelope, "next_stage_envelope_sha256"),
    )
    if any(not path.is_file() or sha256_file(path) != receipt[field] for path, field in bindings):
        raise ContractError("derived continuation evidence binding changed")
    details = receipt["details"]
    if not isinstance(details, dict) or any(
        details.get(key) != value for key, value in {
            "contract_version": read_json(next_envelope)["contract_version"],
            "stage_id": receipt["next_stage_id"],
            "stage_envelope_sha256": receipt["next_stage_envelope_sha256"],
        }.items()
    ):
        raise ContractError("derived continuation stage binding changed")
    staged_validate_accepted_strong_review(
        plan_dir, receipt["source_stage_id"],
        read_json(next_envelope)["contract_version"],
    )
    return receipt


def staged_continuation_capsule_path(
    plan_dir: Path, capsule_id: str,
) -> Path:
    if not re.fullmatch(r"capsule_[a-f0-9]{64}", capsule_id):
        raise ContractError("invalid staged continuation capsule identity")
    return (
        staged_root(plan_dir) / "continuation-capsules" / f"{capsule_id}.json"
    )


def make_staged_continuation_capsule(
    plan_dir: Path,
    continuation_path: Path,
    task_contract_path: Path,
    preflight_path: Path,
) -> tuple[dict[str, Any], Path]:
    """Freeze the exact context for a persistent Worker after one stage crossing."""
    receipt = validate_staged_continuation_receipt(
        plan_dir, continuation_path.resolve(),
    )
    state = staged_load_state(plan_dir)
    if (
        state["active_stage_id"] != receipt["next_stage_id"]
        or state["state"] not in {"STAGE_AUTHORIZED", "DEVELOPING"}
        or state["active_stage_authorization_action"] != "derived_continuation"
        or Path(state["active_stage_authorization_path"]).resolve()
        != continuation_path.resolve()
    ):
        raise ContractError(
            "staged continuation capsule requires the authorized next stage"
        )
    contract_path = task_contract_path.resolve()
    preflight_path = preflight_path.resolve()
    contract = read_json(contract_path)
    task_id = staged_require_id(contract.get("task_id"), "task_id")
    input_manifest = verify_manifest_items(
        contract.get("inputs", []), base_dir=plan_dir,
    )
    stage_envelope_path = (
        staged_stage_dir(plan_dir, receipt["next_stage_id"]) / "envelope.json"
    )
    identity = {
        "plan_id": plan_identity(plan_dir),
        "task_id": task_id,
        "continuation_id": receipt["continuation_id"],
        "continuation_receipt_sha256": sha256_file(continuation_path),
        "task_contract_sha256": sha256_file(contract_path),
        "input_manifest_sha256": sha256_json(input_manifest),
        "stage_envelope_sha256": sha256_file(stage_envelope_path),
        "preflight_sha256": sha256_file(preflight_path),
    }
    capsule_id = f"capsule_{sha256_json(identity)}"
    target = staged_continuation_capsule_path(plan_dir, capsule_id)
    if target.exists():
        capsule, _ = validate_staged_continuation_capsule(plan_dir, target)
        return capsule, target
    if state["state"] != "STAGE_AUTHORIZED":
        raise ContractError(
            "missing staged continuation capsule after Worker dispatch"
        )
    source_stage_dir = staged_stage_dir(plan_dir, receipt["source_stage_id"])
    body = {
        "schema_version": SCHEMA_VERSION,
        "capsule_kind": "staged_continuation",
        "capsule_id": capsule_id,
        "plan_id": plan_identity(plan_dir),
        "task_id": task_id,
        "state_revision": state["audit_revision"],
        "task_contract": {
            "path": str(contract_path),
            "sha256": sha256_file(contract_path),
        },
        "input_manifest": input_manifest,
        "input_manifest_sha256": sha256_json(input_manifest),
        "continuation_receipt": {
            "path": str(continuation_path.resolve()),
            "sha256": sha256_file(continuation_path),
            "continuation_id": receipt["continuation_id"],
        },
        "stage_envelope": {
            "path": str(stage_envelope_path),
            "sha256": sha256_file(stage_envelope_path),
        },
        "preflight": {
            "path": str(preflight_path),
            "sha256": sha256_file(preflight_path),
        },
        "prior_direction_refs": [{
            "path": str(source_stage_dir / "strong-review.json"),
            "sha256": sha256_file(source_stage_dir / "strong-review.json"),
        }],
        "evidence_refs": [{
            "path": str(source_stage_dir / name),
            "sha256": sha256_file(source_stage_dir / name),
        } for name in ("decision.json", "stage-report.json")],
        "created_at": utc_now(),
    }
    capsule = {**body, "capsule_sha256": sha256_json(body)}
    atomic_write_json(target, capsule, immutable=True)
    return capsule, target


def validate_staged_continuation_capsule(
    plan_dir: Path, capsule_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    capsule_path = capsule_path.resolve()
    root = (staged_root(plan_dir) / "continuation-capsules").resolve()
    try:
        capsule_path.relative_to(root)
    except ValueError as exc:
        raise ContractError(
            "staged continuation capsule is outside canonical state"
        ) from exc
    capsule = read_json(capsule_path)
    required = {
        "schema_version", "capsule_kind", "capsule_id", "plan_id",
        "task_id", "state_revision", "task_contract", "input_manifest",
        "input_manifest_sha256", "continuation_receipt", "stage_envelope",
        "preflight", "prior_direction_refs", "evidence_refs", "created_at",
        "capsule_sha256",
    }
    if (
        set(capsule) != required
        or capsule.get("schema_version") != SCHEMA_VERSION
        or capsule.get("capsule_kind") != "staged_continuation"
        or capsule_path
        != staged_continuation_capsule_path(
            plan_dir, capsule.get("capsule_id", ""),
        ).resolve()
        or capsule_path.stat().st_mode & 0o777 != 0o444
    ):
        raise ContractError("staged continuation capsule has an invalid closed shape")
    body = {key: value for key, value in capsule.items() if key != "capsule_sha256"}
    if capsule["capsule_sha256"] != sha256_json(body):
        raise ContractError("staged continuation capsule hash mismatch")
    if capsule["plan_id"] != plan_identity(plan_dir):
        raise ContractError("staged continuation capsule belongs to another plan")
    continuation = capsule["continuation_receipt"]
    if not isinstance(continuation, dict) or set(continuation) != {
        "path", "sha256", "continuation_id",
    }:
        raise ContractError("staged continuation receipt binding is malformed")
    continuation_path = Path(continuation["path"])
    if (
        not continuation_path.is_file()
        or sha256_file(continuation_path) != continuation["sha256"]
    ):
        raise ContractError("staged continuation receipt binding changed")
    receipt = validate_staged_continuation_receipt(plan_dir, continuation_path)
    if receipt["continuation_id"] != continuation["continuation_id"]:
        raise ContractError("staged continuation receipt identity changed")
    state = staged_load_state(plan_dir)
    if (
        state["active_stage_id"] != receipt["next_stage_id"]
        or state["state"] not in {"STAGE_AUTHORIZED", "DEVELOPING", "RECORDED"}
        or state["active_stage_authorization_action"] != "derived_continuation"
        or Path(state["active_stage_authorization_path"]).resolve()
        != continuation_path.resolve()
    ):
        raise ContractError("staged continuation capsule is not current")
    task = capsule["task_contract"]
    if not isinstance(task, dict) or set(task) != {"path", "sha256"}:
        raise ContractError("staged continuation task binding is malformed")
    task_path = Path(task["path"])
    if not task_path.is_file() or sha256_file(task_path) != task["sha256"]:
        raise ContractError("staged continuation task contract changed")
    contract = read_json(task_path)
    if contract.get("task_id") != capsule["task_id"]:
        raise ContractError("staged continuation task identity changed")
    manifest = verify_manifest_items(contract.get("inputs", []), base_dir=plan_dir)
    if (
        manifest != capsule["input_manifest"]
        or sha256_json(manifest) != capsule["input_manifest_sha256"]
    ):
        raise ContractError("staged continuation input manifest changed")
    bindings = (
        (capsule["stage_envelope"], "stage envelope"),
        (capsule["preflight"], "preflight"),
    )
    for binding, label in bindings:
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
            raise ContractError(f"staged continuation {label} binding is malformed")
        path = Path(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise ContractError(f"staged continuation {label} changed")
    if capsule["stage_envelope"]["sha256"] != receipt["next_stage_envelope_sha256"]:
        raise ContractError("staged continuation envelope authority changed")
    for refs, label in (
        (capsule["prior_direction_refs"], "prior direction"),
        (capsule["evidence_refs"], "evidence"),
    ):
        if not isinstance(refs, list) or not refs:
            raise ContractError(f"staged continuation {label} refs are missing")
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
                raise ContractError(f"staged continuation {label} ref is malformed")
            path = Path(ref["path"])
            if not path.is_file() or sha256_file(path) != ref["sha256"]:
                raise ContractError(f"staged continuation {label} ref changed")
    return capsule, {"task_contract": task}


def validate_worker_context_capsule(
    plan_dir: Path, capsule_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate either an initial durable capsule or a bounded stage-crossing capsule."""
    resolved = capsule_path.resolve()
    staged_capsule_root = (
        staged_root(plan_dir) / "continuation-capsules"
    ).resolve()
    try:
        resolved.relative_to(staged_capsule_root)
    except ValueError:
        capsule, _, _, task = validate_context_capsule(plan_dir, resolved)
        return capsule, task
    return validate_staged_continuation_capsule(plan_dir, resolved)


def staged_derive_continuation_receipt(
    plan_dir: Path, next_envelope_path: Path,
) -> Path:
    """Materialize one auditable authority already granted by the owner."""
    state = staged_load_state(plan_dir)
    source_stage_id = state["active_stage_id"]
    envelope = read_json(next_envelope_path)
    next_stage_id = staged_require_id(envelope.get("stage_id"), "next stage id")
    initial_path = Path(state["owner_authorization_path"])
    initial = validate_applied_action_receipt(
        plan_dir, initial_path, "authorize_contract",
    )
    bounded = initial.get("details", {}).get("bounded_continuation_authority")
    if (
        not isinstance(bounded, dict)
        or bounded.get("allowed_stage_ids") != [next_stage_id]
        or bounded.get("max_automatic_crossings") != 1
        or bounded.get("silence_is_approval") is not False
    ):
        raise ContractError(
            "initial signed authorization lacks the requested bounded continuation"
        )
    receipt_dir = staged_root(plan_dir) / "continuation-receipts"
    prior = sorted(receipt_dir.glob("*.json"))
    continuation_id = f"continuation_{source_stage_id}_{next_stage_id}"
    target = receipt_dir / f"{continuation_id}.json"
    if prior and target not in prior:
        raise ContractError("bounded continuation authority is already exhausted")
    source_dir = staged_stage_dir(plan_dir, source_stage_id)
    decision_path = source_dir / "decision.json"
    report_path = source_dir / "stage-report.json"
    review_path = source_dir / "strong-review.json"
    decision = read_json(decision_path)
    strong_review = staged_validate_accepted_strong_review(
        plan_dir, source_stage_id, state["contract_version"],
    )
    reviewed = strong_review.get("continuation_review")
    reviewed_envelope = (
        reviewed.get("next_stage_envelope")
        if isinstance(reviewed, dict) else None
    )
    if (
        not isinstance(reviewed_envelope, dict)
        or Path(reviewed_envelope.get("path", "")).resolve()
        != next_envelope_path.resolve()
        or reviewed_envelope.get("sha256") != sha256_file(next_envelope_path)
    ):
        raise ContractError(
            "bounded continuation requires the accepted strong review to bind "
            "the exact next-stage envelope"
        )
    if (
        decision.get("decision") not in STAGED_TERMINAL_DECISIONS
    ):
        raise ContractError("bounded continuation requires a terminal decision")
    stable = {
        "schema_version": 1,
        "continuation_id": continuation_id,
        "authority": "bounded_initial_human_authorization",
        "crossing_index": 1,
        "max_automatic_crossings": 1,
        "source_stage_id": source_stage_id,
        "next_stage_id": next_stage_id,
        "initial_authorization_path": str(initial_path),
        "initial_authorization_sha256": sha256_file(initial_path),
        "initial_authorization_record_id": initial["record_id"],
        "source_decision_sha256": sha256_file(decision_path),
        "stage_report_sha256": sha256_file(report_path),
        "strong_review_sha256": sha256_file(review_path),
        "next_stage_envelope_sha256": sha256_file(next_envelope_path),
        "details": {
            "contract_version": state["contract_version"],
            "contract_sha256": state["contract_sha256"],
            "stage_id": next_stage_id,
            "stage_envelope_sha256": sha256_file(next_envelope_path),
        },
    }
    if target.exists():
        receipt = read_json(target)
        if {key: receipt.get(key) for key in stable} != stable:
            raise ContractError("derived continuation receipt collision")
    else:
        receipt = {**stable, "derived_at": utc_now()}
        atomic_write_json(target, receipt, immutable=True)
        _staged_fault_after_artifact("continuation_receipt")
    validate_staged_continuation_receipt_source(plan_dir, target, next_envelope_path)
    _staged_ensure_audit_once_locked(
        plan_dir, "bounded_continuation_derived",
        {"continuation_id": continuation_id},
        {
            "source_stage_id": source_stage_id,
            "next_stage_id": next_stage_id,
            "initial_authorization_record_id": initial["record_id"],
            "silence_is_approval": False,
        },
    )
    return target


def validate_staged_continuation_receipt_source(
    plan_dir: Path, receipt_path: Path, next_envelope_path: Path,
) -> dict[str, Any]:
    """Validate a derived receipt before its envelope has become canonical."""
    receipt = read_json(receipt_path)
    required = {
        "schema_version", "continuation_id", "authority", "crossing_index",
        "max_automatic_crossings", "source_stage_id", "next_stage_id",
        "initial_authorization_path", "initial_authorization_sha256",
        "initial_authorization_record_id", "source_decision_sha256",
        "stage_report_sha256", "strong_review_sha256",
        "next_stage_envelope_sha256", "details", "derived_at",
    }
    canonical = (
        staged_root(plan_dir) / "continuation-receipts"
        / f"{receipt.get('continuation_id')}.json"
    )
    if (
        receipt_path.resolve() != canonical.resolve()
        or set(receipt) != required
        or receipt.get("schema_version") != 1
        or receipt.get("crossing_index") != 1
        or receipt.get("max_automatic_crossings") != 1
    ):
        raise ContractError("derived continuation source has an invalid closed shape")
    initial_path = Path(receipt.get("initial_authorization_path", ""))
    if (
        not initial_path.is_file()
        or sha256_file(initial_path) != receipt["initial_authorization_sha256"]
    ):
        raise ContractError("initial continuation authority changed")
    initial = validate_applied_action_receipt(
        plan_dir, initial_path, "authorize_contract",
    )
    bounded = initial.get("details", {}).get("bounded_continuation_authority")
    envelope = read_json(next_envelope_path)
    source_dir = staged_stage_dir(plan_dir, receipt.get("source_stage_id", ""))
    source_bindings = (
        (source_dir / "decision.json", "source_decision_sha256"),
        (source_dir / "stage-report.json", "stage_report_sha256"),
        (source_dir / "strong-review.json", "strong_review_sha256"),
    )
    details = receipt.get("details")
    if (
        receipt.get("authority") != "bounded_initial_human_authorization"
        or initial.get("record_id") != receipt.get("initial_authorization_record_id")
        or receipt.get("next_stage_envelope_sha256") != sha256_file(next_envelope_path)
        or envelope.get("stage_id") != receipt.get("next_stage_id")
        or envelope.get("source_cycle_id") != receipt.get("source_stage_id")
        or any(
            not path.is_file() or sha256_file(path) != receipt.get(field)
            for path, field in source_bindings
        )
        or not isinstance(bounded, dict)
        or bounded.get("allowed_stage_ids") != [receipt.get("next_stage_id")]
        or bounded.get("max_automatic_crossings") != 1
        or bounded.get("silence_is_approval") is not False
        or not isinstance(details, dict)
        or details.get("stage_id") != receipt.get("next_stage_id")
        or details.get("stage_envelope_sha256")
        != receipt.get("next_stage_envelope_sha256")
        or details.get("contract_version") != envelope.get("contract_version")
    ):
        raise ContractError("derived continuation source binding mismatch")
    staged_validate_accepted_strong_review(
        plan_dir, receipt["source_stage_id"], envelope["contract_version"],
    )
    return receipt


def staged_stage_dir(plan_dir: Path, stage_id: str) -> Path:
    return staged_root(plan_dir) / "stages" / stage_id


def staged_initialize_usage_ledger(
    plan_dir: Path, envelope: dict[str, Any],
) -> None:
    target = staged_stage_dir(plan_dir, envelope["stage_id"]) / "usage-ledger.json"
    value = staged_usage_ledger_image(envelope)
    if target.exists():
        if read_json(target) != value:
            raise ContractError("stage usage ledger initialization collision")
    else:
        atomic_write_json(target, value)


def staged_usage_ledger_image(envelope: dict[str, Any]) -> dict[str, Any]:
    budget = envelope["stage_budget_and_stop"]
    limit_keys = [
        "time_seconds", "tool_calls", "worker_tokens", "review_tokens",
        "retry_attempts", "evaluation_calls",
    ]
    if "worker_dispatches" in budget:
        limit_keys.append("worker_dispatches")
    return {
        "schema_version": 1,
        "stage_id": envelope["stage_id"],
        "budget_profile_id": budget["profile_id"],
        "budget_sha256": envelope["stage_budget_sha256"],
        "started_at": utc_now(),
        "limits": {key: budget[key] for key in limit_keys},
        "used": {
            "tool_calls": 0, "worker_tokens": 0, "review_tokens": 0,
            "retry_attempts": 0, "evaluation_calls": 0,
            **({"worker_dispatches": 0} if "worker_dispatches" in budget else {}),
        },
        "reservation_ids": [],
        "stop_reason": None,
    }


def staged_consume_stage_budget(
    plan_dir: Path, reservation_id: str, usage: dict[str, int],
) -> dict[str, Any]:
    with staged_transaction_lock(plan_dir):
        return _staged_consume_stage_budget_locked(
            plan_dir, reservation_id, usage,
        )


def _staged_consume_stage_budget_locked(
    plan_dir: Path, reservation_id: str, usage: dict[str, int],
) -> dict[str, Any]:
    state = staged_load_state(plan_dir)
    controller_path = plan_dir / "state" / "controller.json"
    if controller_path.exists() and read_json(controller_path).get("status") in {
        "paused", "stopped",
    }:
        raise ContractError("stage dispatch blocked by canonical human lifecycle state")
    ledger_path = (
        staged_stage_dir(plan_dir, state["active_stage_id"])
        / "usage-ledger.json"
    )
    ledger = read_json(ledger_path)
    if reservation_id in ledger["reservation_ids"]:
        return ledger
    if ledger.get("stop_reason") is not None or state["state"] == "PAUSED":
        raise ContractError("stage is stopped pending canonical human reauthorization")
    elapsed = (
        datetime.now(timezone.utc) - parse_utc(ledger["started_at"])
    ).total_seconds()
    if elapsed > ledger["limits"]["time_seconds"]:
        ledger["stop_reason"] = "deadline"
        atomic_write_json(ledger_path, ledger)
        state["state"] = "PAUSED"
        atomic_write_json(staged_state_path(plan_dir), state)
        raise ContractError("stage time budget exhausted")
    for field, amount in usage.items():
        require_non_negative_int(amount, f"stage usage {field}")
        if field not in ledger["used"]:
            raise ContractError(f"unknown stage budget dimension: {field}")
        if ledger["used"][field] + amount > ledger["limits"][field]:
            ledger["stop_reason"] = f"{field}_exhausted"
            atomic_write_json(ledger_path, ledger)
            state["state"] = "PAUSED"
            atomic_write_json(staged_state_path(plan_dir), state)
            raise ContractError(f"stage {field} budget exhausted")
    for field, amount in usage.items():
        ledger["used"][field] += amount
    ledger["reservation_ids"].append(reservation_id)
    ledger["updated_at"] = utc_now()
    atomic_write_json(ledger_path, ledger)
    return ledger


@contextmanager
def staged_transaction_lock(plan_dir: Path) -> Iterator[None]:
    lock_path = plan_dir / "state" / ".staged-research.transaction.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def staged_authorize_first_stage(
    plan_dir: Path, request_id: str, transition_path: Path,
) -> None:
    with staged_transaction_lock(plan_dir):
        _staged_authorize_first_stage_locked(
            plan_dir, request_id, transition_path,
        )


def _staged_authorize_first_stage_locked(
    plan_dir: Path, request_id: str, transition_path: Path,
) -> None:
    if not transition_path.is_file():
        raise ContractError("staged CP-01 transition receipt is missing")
    state = staged_load_state(plan_dir)
    if state["state"] == "CONTRACTED":
        usage_path = (
            staged_stage_dir(plan_dir, state["active_stage_id"])
            / "usage-ledger.json"
        )
        usage = read_json(usage_path)
        if not any(
            item.startswith("worker:")
            for item in usage.get("reservation_ids", [])
        ):
            # The scientific stage clock begins when CP-01 authorizes
            # development, not while the plan is waiting for frontier review.
            usage["started_at"] = utc_now()
            usage["updated_at"] = usage["started_at"]
            atomic_write_json(usage_path, usage)
        state["state"] = "STAGE_AUTHORIZED"
        atomic_write_json(staged_state_path(plan_dir), state)
        _staged_fault_after_artifact("first_stage_authorize")
    _staged_ensure_audit_once_locked(
        plan_dir,
        "first_stage_authorized",
        {"stage_id": state["active_stage_id"]},
        {
            "cp01_request_id": request_id,
            "cp01_transition_receipt_sha256": sha256_file(transition_path),
            "review_advisory_only": True,
            "controller_authoritative": True,
        },
    )


def staged_validate_contract(contract: dict[str, Any]) -> None:
    required = {
        "schema_version", "contract_version", "owner_identity_sha256",
        "authorization_receipt_id", "objective",
        "development_evidence_profile_sha256", "acceptance_evaluator_sha256",
        "development_validator_sha256", "admissibility_policy_sha256",
        "adoption_policy_sha256", "scope_policy_sha256",
        "permission_policy_sha256", "evaluation_policy_sha256",
        "resource_policy_sha256", "authority_policy_sha256",
        "per_cycle_budget_sha256", "frontier_checkpoint_budget_sha256",
        "stop_and_reauthorization_policy_sha256",
        "external_transfer_profile_sha256",
    }
    missing = sorted(required - set(contract))
    if missing:
        raise ContractError(f"optimization contract is incomplete: {missing}")
    extra = sorted(set(contract) - required)
    if extra:
        raise ContractError(f"optimization contract has forbidden fields: {extra}")
    if contract.get("schema_version") != 1:
        raise ContractError("optimization contract schema_version must be 1")
    staged_require_id(contract["contract_version"], "contract_version")
    staged_require_id(
        contract["authorization_receipt_id"], "authorization_receipt_id",
    )
    for field in required - {
        "schema_version", "contract_version", "authorization_receipt_id",
        "objective",
    }:
        staged_require_sha256(contract[field], field)
    objective = contract["objective"]
    if not isinstance(objective, dict) or set(objective) != {"id", "statement_sha256"}:
        raise ContractError("optimization contract objective must have id and statement_sha256")
    staged_require_id(objective["id"], "objective.id")
    staged_require_sha256(objective["statement_sha256"], "objective.statement_sha256")
    if (
        contract["development_validator_sha256"]
        == contract["acceptance_evaluator_sha256"]
    ):
        raise ContractError("development validator and acceptance evaluator must be distinct")


def staged_validate_evaluation_profile(profile: dict[str, Any]) -> None:
    common = {
        "schema_version", "profile_id",
        "private_split_policy_sha256", "holdout_refresh_policy_sha256",
        "transfer_audit_schedule_sha256", "external_suite_identity_sha256",
    }
    inactive = common | {"applicable", "reason"}
    if profile.get("applicable") is False:
        missing = sorted(inactive - set(profile))
        if missing:
            raise ContractError(f"evaluation profile is incomplete: {missing}")
        extra = sorted(set(profile) - inactive)
        if extra:
            raise ContractError(f"evaluation profile has forbidden fields: {extra}")
        if (
            profile.get("schema_version") != 1
            or profile.get("reason") != "observation_only_no_logical_gate"
        ):
            raise ContractError("inactive evaluation profile reason is invalid")
        staged_require_id(profile["profile_id"], "evaluation_profile.profile_id")
        for field in common - {"schema_version", "profile_id"}:
            staged_require_sha256(profile[field], f"evaluation_profile.{field}")
        return
    required = common | {
        "logical_gate_query_limit_per_candidate",
        "gate_metric", "gate_operator", "gate_threshold",
        "gate_escalation_margin",
    }
    missing = sorted(required - set(profile))
    if missing:
        raise ContractError(f"evaluation profile is incomplete: {missing}")
    extra = sorted(set(profile) - required)
    if extra:
        raise ContractError(f"evaluation profile has forbidden fields: {extra}")
    if (
        profile.get("schema_version") != 1
        or profile.get("logical_gate_query_limit_per_candidate") != 1
    ):
        raise ContractError("evaluation profile must permit exactly one Gate query")
    staged_require_id(profile["profile_id"], "evaluation_profile.profile_id")
    for field in common - {
        "schema_version", "profile_id",
    }:
        staged_require_sha256(profile[field], f"evaluation_profile.{field}")
    if (
        not isinstance(profile["gate_metric"], str)
        or not profile["gate_metric"]
        or profile["gate_operator"] not in {"ge", "le"}
    ):
        raise ContractError("evaluation Gate metric/operator is invalid")
    require_finite_number(profile["gate_threshold"], "gate_threshold")
    margin = require_finite_number(
        profile["gate_escalation_margin"], "gate_escalation_margin",
    )
    if margin < 0:
        raise ContractError("gate_escalation_margin must be non-negative")


def staged_validate_profile_envelope_compatibility(
    profile: dict[str, Any], envelope: dict[str, Any], *, strict: bool = True,
) -> None:
    """Bind Gate authority to the exact semantics of one executable stage.

    An inactive evaluation profile is valid only for a research stage that has
    no logical Gate calls.  Every other executable stage needs the active Gate
    fields.  This check is deliberately bidirectional so neither an inactive
    profile can leak into evaluative work nor an active profile can make an
    observation-only stage appear Gate-authorized.
    """
    budget = envelope.get("stage_budget_and_stop")
    observation_only = (
        envelope.get("stage_kind") == "research"
        and isinstance(budget, dict)
        and budget.get("evaluation_calls") == 0
    )
    inactive = profile.get("applicable") is False
    if inactive and not observation_only:
        raise ContractError(
            "evaluation profile/stage envelope incompatibility: "
            "active evaluation profile required"
        )
    if strict and observation_only and not inactive:
        expected = "inactive" if observation_only else "active"
        raise ContractError(
            "evaluation profile/stage envelope incompatibility: "
            f"{expected} evaluation profile required"
        )


def staged_validate_capacity(capacity: dict[str, Any]) -> None:
    if capacity.get("schema_version") == 2:
        required = {
            "schema_version", "worker_dispatch_capacity",
            "stage_review_capacity", "checkpoint_capacity", "retry_budget",
        }
        allowed = required | {"capacity_authorization_ids"}
        if not required.issubset(capacity) or set(capacity) - allowed:
            raise ContractError("capacity v2 has an invalid closed shape")
        worker = capacity.get("worker_dispatch_capacity")
        if not isinstance(worker, dict) or set(worker) != {
            "authorized_calls", "spent_calls", "remaining_calls",
        }:
            raise ContractError("worker_dispatch_capacity has an invalid closed shape")
        authorized = require_non_negative_int(
            worker.get("authorized_calls"), "worker_dispatch_capacity.authorized_calls",
        )
        spent = require_non_negative_int(
            worker.get("spent_calls"), "worker_dispatch_capacity.spent_calls",
        )
        remaining = require_non_negative_int(
            worker.get("remaining_calls"), "worker_dispatch_capacity.remaining_calls",
        )
        if spent + remaining != authorized:
            raise ContractError("worker dispatch capacity does not reconcile")
        checkpoints = capacity.get("checkpoint_capacity")
        mandatory_checkpoints = {"CP-01", "CP-02", "CP-04"}
        if (
            not isinstance(checkpoints, dict)
            or not mandatory_checkpoints.issubset(checkpoints)
            or set(checkpoints) - (mandatory_checkpoints | {"CP-03"})
        ):
            raise ContractError(
                "capacity v2 must name CP-01, CP-02, CP-04 and may name CP-03"
            )
        review = capacity.get("stage_review_capacity")
        if not isinstance(review, dict) or set(review) != {
            "authorized_calls", "spent_calls", "remaining_calls", "transferable",
        }:
            raise ContractError("stage_review_capacity has an invalid closed shape")
        review_authorized = require_non_negative_int(
            review.get("authorized_calls"), "stage_review_capacity.authorized_calls",
        )
        review_spent = require_non_negative_int(
            review.get("spent_calls"), "stage_review_capacity.spent_calls",
        )
        review_remaining = require_non_negative_int(
            review.get("remaining_calls"), "stage_review_capacity.remaining_calls",
        )
        if (
            review.get("transferable") is not False
            or review_spent + review_remaining != review_authorized
        ):
            raise ContractError("stage review capacity does not reconcile")
        slots = checkpoints
        slot_ids: list[str] = []
        for checkpoint, slot in slots.items():
            if not isinstance(slot, dict) or set(slot) != {
                "slot_id", "reserved", "spent", "transferable",
            }:
                raise ContractError(f"{checkpoint} capacity must be an object")
            if (
                slot.get("reserved") != 1
                or slot.get("spent") not in {0, 1}
                or slot.get("transferable") is not False
            ):
                raise ContractError(f"{checkpoint} capacity must be non-fungible")
            slot_ids.append(staged_require_id(slot.get("slot_id"), f"{checkpoint}.slot_id"))
        if len(slot_ids) != len(set(slot_ids)):
            raise ContractError("capacity v2 slot identities must be distinct")
        _staged_validate_retry_and_authorizations(capacity)
        return
    required = {
        "schema_version", "checkpoint_capacity", "retry_budget",
        "remaining_calls", "mandatory_future_calls",
    }
    allowed = required | {
        "capacity_authorization_ids", "authorized_additions",
    }
    if (
        not required.issubset(capacity)
        or set(capacity) - allowed
        or capacity.get("schema_version") != 1
    ):
        raise ContractError("checkpoint capacity has an invalid closed shape")
    checkpoints = capacity.get("checkpoint_capacity")
    if not isinstance(checkpoints, dict) or set(checkpoints) != {
        "CP-01", "CP-02", "CP-04",
    }:
        raise ContractError("checkpoint capacity must reserve CP-01, CP-02, and CP-04")
    slot_ids: list[str] = []
    for checkpoint, slot in checkpoints.items():
        if not isinstance(slot, dict) or set(slot) != {
            "slot_id", "reserved", "spent", "transferable",
        }:
            raise ContractError(f"{checkpoint} capacity must be an object")
        if (
            slot.get("reserved") != 1
            or slot.get("spent") not in {0, 1}
            or slot.get("transferable") is not False
        ):
            raise ContractError(f"{checkpoint} capacity must be one non-fungible slot")
        slot_ids.append(staged_require_id(slot.get("slot_id"), f"{checkpoint}.slot_id"))
    if len(set(slot_ids)) != 3:
        raise ContractError("checkpoint slot identities must be distinct")
    retry = capacity.get("retry_budget")
    if not isinstance(retry, dict) or set(retry) != {
        "remaining_attempts", "per_attempt_call_limit",
        "per_attempt_token_limit",
    }:
        raise ContractError("independent retry_budget is required")
    for field in (
        "remaining_attempts", "per_attempt_call_limit",
        "per_attempt_token_limit",
    ):
        require_non_negative_int(retry.get(field), f"retry_budget.{field}")
    remaining = require_non_negative_int(
        capacity.get("remaining_calls"), "remaining_calls",
    )
    mandatory = require_non_negative_int(
        capacity.get("mandatory_future_calls"), "mandatory_future_calls",
    )
    unspent = sum(1 for slot in checkpoints.values() if slot["spent"] == 0)
    if mandatory != unspent:
        raise ContractError("mandatory_future_calls must equal unspent named slots")
    if remaining < mandatory:
        raise ContractError("remaining_calls < mandatory_future_calls")
    authorization_ids = capacity.get("capacity_authorization_ids", [])
    if (
        not isinstance(authorization_ids, list)
        or len(authorization_ids) != len(set(authorization_ids))
        or any(not isinstance(item, str) or not item.startswith("har_")
               for item in authorization_ids)
    ):
        raise ContractError("capacity authorization IDs are invalid")
    additions = capacity.get("authorized_additions", {"calls": 0})
    if (
        not isinstance(additions, dict)
        or set(additions) != {"calls"}
        or require_non_negative_int(
            additions.get("calls"), "authorized_additions.calls",
        ) < 0
    ):
        raise ContractError("authorized staged capacity additions are invalid")


def _staged_validate_retry_and_authorizations(capacity: dict[str, Any]) -> None:
    retry = capacity.get("retry_budget")
    if not isinstance(retry, dict) or set(retry) != {
        "remaining_attempts", "per_attempt_call_limit", "per_attempt_token_limit",
    }:
        raise ContractError("independent retry_budget is required")
    for field in (
        "remaining_attempts", "per_attempt_call_limit", "per_attempt_token_limit",
    ):
        require_non_negative_int(retry.get(field), f"retry_budget.{field}")
    authorization_ids = capacity.get("capacity_authorization_ids", [])
    if (
        not isinstance(authorization_ids, list)
        or len(authorization_ids) != len(set(authorization_ids))
        or any(not isinstance(item, str) or not item.startswith("har_")
               for item in authorization_ids)
    ):
        raise ContractError("capacity authorization IDs are invalid")


def staged_capacity_projection(capacity: dict[str, Any]) -> dict[str, Any]:
    """Return version-neutral counters for views, markers, and audit records."""
    if capacity.get("schema_version") == 2:
        checkpoints = capacity["checkpoint_capacity"]
        return {
            "schema_version": 2,
            "worker_dispatch_remaining": capacity[
                "worker_dispatch_capacity"
            ]["remaining_calls"],
            "stage_review_remaining": capacity[
                "stage_review_capacity"
            ]["remaining_calls"],
            "checkpoint_remaining": sum(
                1 - slot["spent"] for slot in checkpoints.values()
            ),
        }
    return {
        "schema_version": 1,
        "worker_dispatch_remaining": (
            capacity["remaining_calls"] - capacity["mandatory_future_calls"]
        ),
        # Legacy v1 did not isolate terminal review capacity.
        "stage_review_remaining": None,
        "checkpoint_remaining": capacity["mandatory_future_calls"],
        "remaining_calls": capacity["remaining_calls"],
        "mandatory_future_calls": capacity["mandatory_future_calls"],
    }


def staged_capacity_reserve_image(
    capacity: dict[str, Any], checkpoint: str | None,
) -> dict[str, Any]:
    """Debit exactly one dispatch class and return a validated new image."""
    staged_validate_capacity(capacity)
    after = json.loads(json.dumps(capacity))
    if capacity.get("schema_version") == 2:
        if checkpoint is None:
            worker = after["worker_dispatch_capacity"]
            if worker["remaining_calls"] == 0:
                raise ContractError("worker dispatch capacity is exhausted")
            worker["remaining_calls"] -= 1
            worker["spent_calls"] += 1
        elif checkpoint == "STAGE-REVIEW":
            review = after["stage_review_capacity"]
            if review["remaining_calls"] == 0:
                raise ContractError("non-fungible STAGE-REVIEW capacity is unavailable")
            review["remaining_calls"] -= 1
            review["spent_calls"] += 1
        else:
            slot = after["checkpoint_capacity"].get(checkpoint)
            if slot is None or slot["spent"] != 0:
                raise ContractError(f"non-fungible {checkpoint} capacity is unavailable")
            slot["spent"] = 1
    else:
        if checkpoint is None:
            if after["remaining_calls"] - 1 < after["mandatory_future_calls"]:
                raise ContractError(
                    "dispatch blocked: remaining_calls would fall below mandatory_future_calls"
                )
        else:
            slot = after["checkpoint_capacity"].get(checkpoint)
            if slot is None or slot["spent"] != 0:
                raise ContractError(f"non-fungible {checkpoint} capacity is unavailable")
        after["remaining_calls"] -= 1
        if checkpoint is not None:
            after["checkpoint_capacity"][checkpoint]["spent"] = 1
            after["mandatory_future_calls"] -= 1
    staged_validate_capacity(after)
    return after


def staged_capacity_release_image(
    capacity: dict[str, Any], checkpoint: str | None,
) -> dict[str, Any]:
    """Reverse only a proven-unstarted reservation in its original class."""
    staged_validate_capacity(capacity)
    after = json.loads(json.dumps(capacity))
    if capacity.get("schema_version") == 2:
        if checkpoint is None:
            worker = after["worker_dispatch_capacity"]
            if worker["spent_calls"] <= 0:
                raise ContractError("worker capacity is not reserved")
            worker["spent_calls"] -= 1
            worker["remaining_calls"] += 1
        elif checkpoint == "STAGE-REVIEW":
            review = after["stage_review_capacity"]
            if review["spent_calls"] <= 0:
                raise ContractError("STAGE-REVIEW capacity is not reserved")
            review["spent_calls"] -= 1
            review["remaining_calls"] += 1
        else:
            slot = after["checkpoint_capacity"].get(checkpoint)
            if slot is None or slot["spent"] != 1:
                raise ContractError(f"{checkpoint} capacity is not reserved")
            slot["spent"] = 0
    else:
        after["remaining_calls"] += 1
        if checkpoint is not None:
            slot = after["checkpoint_capacity"].get(checkpoint)
            if slot is None or slot["spent"] != 1:
                raise ContractError(f"{checkpoint} capacity is not reserved")
            slot["spent"] = 0
            after["mandatory_future_calls"] += 1
    staged_validate_capacity(after)
    return after


def staged_validate_envelope(
    envelope: dict[str, Any], contract_version: str,
    incumbent_sha256: str, *, first: bool,
    plan_dir: Path | None = None,
    require_manifest: bool = False,
) -> None:
    required = {
        "schema_version", "stage_id", "contract_version", "source_cycle_id",
        "incumbent_sha256", "stage_objective_sha256",
        "authorized_evidence_refs", "allowed_intervention_sha256",
        "entry_criteria_sha256", "exit_criteria_sha256",
        "stage_budget_sha256", "required_report_schema_sha256",
        "stage_budget_and_stop", "stage_kind",
    }
    allowed = required | {
        "figure_requirements_sha256", "review_material_manifest",
    }
    missing = sorted(required - set(envelope))
    if missing:
        raise ContractError(f"stage envelope is incomplete: {missing}")
    extra = sorted(set(envelope) - allowed)
    if extra:
        raise ContractError(f"stage envelope has forbidden fields: {extra}")
    if envelope.get("schema_version") != 1:
        raise ContractError("stage envelope schema_version must be 1")
    if any(key in envelope for key in ("future_stages", "executable_stages", "depends_on")):
        raise ContractError("stage envelope must not contain a speculative executable DAG")
    staged_require_id(envelope["stage_id"], "stage_id")
    if envelope["contract_version"] != contract_version:
        raise ContractError("stage envelope contract_version mismatch")
    if envelope["incumbent_sha256"] != incumbent_sha256:
        raise ContractError("stage envelope incumbent mismatch")
    if first and envelope["source_cycle_id"] is not None:
        raise ContractError("first stage source_cycle_id must be null")
    if not first:
        staged_require_id(envelope["source_cycle_id"], "source_cycle_id")
    if not isinstance(envelope["authorized_evidence_refs"], list):
        raise ContractError("authorized_evidence_refs must be a list")
    if (
        len(envelope["authorized_evidence_refs"])
        != len(set(envelope["authorized_evidence_refs"]))
    ):
        raise ContractError("authorized_evidence_refs must be unique")
    for item in envelope["authorized_evidence_refs"]:
        staged_require_id(item, "authorized_evidence_ref")
    materials = envelope.get("review_material_manifest", [])
    required_material_hashes = {
        "stage_objective": envelope["stage_objective_sha256"],
        "allowed_intervention": envelope["allowed_intervention_sha256"],
        "entry_criteria": envelope["entry_criteria_sha256"],
        "exit_criteria": envelope["exit_criteria_sha256"],
        "stage_budget": envelope["stage_budget_sha256"],
        "required_report_schema": envelope["required_report_schema_sha256"],
        "stop_policy": (
            envelope.get("stage_budget_and_stop", {}).get("stop_policy_sha256")
            if isinstance(envelope.get("stage_budget_and_stop"), dict)
            else None
        ),
    }
    if envelope.get("stage_kind") == "figure_production":
        required_material_hashes["figure_requirements"] = envelope.get(
            "figure_requirements_sha256"
        )
    allowed_material_purposes = (
        set(required_material_hashes)
        | STAGED_CP01_REVIEW_MATERIAL_PURPOSES
        | STAGED_REPORT_VALIDATOR_MATERIAL_PURPOSES
        | STAGED_CP01_OPTIONAL_REVIEW_MATERIAL_PURPOSES
    )
    if require_manifest and not materials:
        raise ContractError(
            "new stage envelope requires review_material_manifest"
        )
    if not isinstance(materials, list):
        raise ContractError("review_material_manifest must be a list")
    material_ids: list[str] = []
    material_paths: list[str] = []
    material_purposes: list[str] = []
    for material in materials:
        if not isinstance(material, dict) or set(material) != {
            "id", "path", "sha256", "purpose",
        }:
            raise ContractError(
                "review material must bind id, path, sha256, and purpose"
            )
        material_ids.append(staged_require_id(material["id"], "review material id"))
        staged_require_sha256(material["sha256"], "review material sha256")
        if not isinstance(material["purpose"], str) or not material["purpose"].strip():
            raise ContractError("review material purpose is required")
        material_purposes.append(material["purpose"])
        expected_digest = required_material_hashes.get(material["purpose"])
        if material["purpose"] not in allowed_material_purposes:
            raise ContractError(
                f"review material purpose is not authorized: {material['purpose']}"
            )
        if expected_digest is not None and material["sha256"] != expected_digest:
            raise ContractError(
                f"review material digest does not bind {material['purpose']}"
            )
        raw_path = Path(material["path"])
        if plan_dir is not None:
            if (
                raw_path.is_absolute()
                or str(raw_path) != material["path"]
                or any(part in {"", ".", ".."} for part in raw_path.parts)
            ):
                raise ContractError(
                    "review material path must be canonical and plan-relative"
                )
            candidate = plan_dir
            for part in raw_path.parts:
                candidate = candidate / part
                if candidate.is_symlink():
                    raise ContractError(
                        "review material path must not traverse a symlink"
                    )
            if candidate.is_symlink():
                raise ContractError("review material path must not be a symlink")
            path = normalize_owned_path(plan_dir, str(candidate))
            if not path.is_file():
                raise ContractError("review material must be an existing file")
            if path.stat().st_mode & 0o777 != 0o444:
                raise ContractError("review material must be immutable mode 0444")
            if sha256_file(path) != material["sha256"]:
                raise ContractError("review material content hash mismatch")
            material_paths.append(str(path))
        else:
            material_paths.append(material["path"])
    if len(material_ids) != len(set(material_ids)):
        raise ContractError("review material IDs must be unique")
    if len(material_paths) != len(set(material_paths)):
        raise ContractError("review material paths must be unique")
    if len(material_purposes) != len(set(material_purposes)):
        raise ContractError("review material purposes must be unique")
    required_purposes = set(required_material_hashes)
    if require_manifest:
        required_purposes |= STAGED_REPORT_VALIDATOR_MATERIAL_PURPOSES
    if first and require_manifest:
        required_purposes |= STAGED_CP01_REVIEW_MATERIAL_PURPOSES
    if materials and (
        not required_purposes.issubset(set(material_purposes))
        or not set(material_purposes).issubset(allowed_material_purposes)
    ):
        raise ContractError(
            "review material purpose set does not close the stage audit boundary"
        )
    for field in (
        "incumbent_sha256", "stage_objective_sha256",
        "allowed_intervention_sha256", "entry_criteria_sha256",
        "exit_criteria_sha256", "stage_budget_sha256",
        "required_report_schema_sha256",
    ):
        staged_require_sha256(envelope[field], field)
    budget = envelope["stage_budget_and_stop"]
    budget_fields = {
        "profile_id", "time_seconds", "tool_calls", "worker_tokens",
        "review_tokens", "retry_attempts", "evaluation_calls",
        "stop_policy_sha256",
    }
    if (
        not isinstance(budget, dict)
        or set(budget) not in {frozenset(budget_fields), frozenset(budget_fields | {"worker_dispatches"})}
    ):
        raise ContractError("stage budget/stop behavior is incomplete")
    staged_require_id(budget["profile_id"], "stage_budget_and_stop.profile_id")
    for field in set(budget) - {"profile_id", "stop_policy_sha256"}:
        require_non_negative_int(budget[field], f"stage_budget_and_stop.{field}")
    staged_require_sha256(
        budget["stop_policy_sha256"], "stage_budget_and_stop.stop_policy_sha256",
    )
    if envelope["stage_kind"] not in {"research", "figure_production", "release"}:
        raise ContractError("stage_kind is invalid")
    if envelope["stage_kind"] == "figure_production":
        staged_require_sha256(
            envelope.get("figure_requirements_sha256"),
            "figure_requirements_sha256",
        )
    elif "figure_requirements_sha256" in envelope:
        raise ContractError(
            "only a figure-production stage may bind figure requirements"
        )


def command_prepare_staged_research(args: argparse.Namespace) -> dict[str, Any]:
    """Validate the complete bootstrap closure before owner authorization.

    This command publishes no staged runtime state and uses no signing key.  It
    freezes the exact file-byte hashes that create-human-action and
    init-staged-research must reuse, preventing post-signature lint/hash loops.
    """
    plan_dir = Path(args.plan_dir).resolve()
    if staged_state_path(plan_dir).exists():
        raise ContractError(
            "staged initialization preparation requires a fresh plan"
        )
    staged_require_id(args.plan_id, "plan_id")
    if args.plan_id != plan_identity(plan_dir):
        raise ContractError(
            "prepared plan_id does not match resource_manifest.json"
        )
    record_id = staged_require_id(args.record_id, "record_id")
    prepared_operation_id = staged_require_id(
        args.prepared_operation_id, "prepared_operation_id",
    )
    contract_path = Path(args.contract).resolve()
    envelope_path = Path(args.stage_envelope).resolve()
    evaluation_path = Path(args.evaluation_profile).resolve()
    capacity_path = Path(args.checkpoint_capacity).resolve()
    contract = read_json(contract_path)
    envelope = read_json(envelope_path)
    evaluation = read_json(evaluation_path)
    capacity = read_json(capacity_path)
    staged_validate_contract(contract)
    staged_validate_evaluation_profile(evaluation)
    staged_validate_capacity(capacity)
    incumbent_sha256 = staged_require_sha256(
        args.incumbent_sha256, "incumbent_sha256",
    )
    staged_validate_envelope(
        envelope,
        contract["contract_version"],
        incumbent_sha256,
        first=True,
        plan_dir=plan_dir,
        require_manifest=True,
    )
    staged_validate_profile_envelope_compatibility(
        evaluation, envelope, strict=True,
    )
    if contract["authorization_receipt_id"] != record_id:
        raise ContractError(
            "optimization contract authorization receipt ID does not match "
            "the prepared record ID"
        )
    continuation_stage_id = getattr(args, "continuation_stage_id", None)
    if continuation_stage_id:
        continuation_stage_id = staged_require_id(
            continuation_stage_id, "continuation_stage_id",
        )
        if continuation_stage_id == envelope["stage_id"]:
            raise ContractError(
                "continuation stage must differ from the first stage"
            )
    proposal = {
        "schema_version": 1,
        "status": "AWAITING_HUMAN_AUTHORIZATION",
        "prepared_operation_id": prepared_operation_id,
        "proposal_kind": "authorize_contract",
        "plan_id": args.plan_id,
        "record_id": record_id,
        "contract_version": contract["contract_version"],
        "contract_path": str(contract_path),
        "contract_sha256": sha256_file(contract_path),
        "stage_id": envelope["stage_id"],
        "stage_envelope_path": str(envelope_path),
        "stage_envelope_sha256": sha256_file(envelope_path),
        "evaluation_profile_path": str(evaluation_path),
        "evaluation_profile_sha256": sha256_file(evaluation_path),
        "checkpoint_capacity_path": str(capacity_path),
        "checkpoint_capacity_sha256": sha256_file(capacity_path),
        "incumbent_sha256": incumbent_sha256,
        "continuation_stage_id": continuation_stage_id,
        "continuation_stage_limit": 1 if continuation_stage_id else 0,
    }
    proposal_path = (
        plan_dir / "control" / "human_authorization_required.json"
    )
    if proposal_path.exists() and read_json(proposal_path) != proposal:
        bound_records = list(
            (plan_dir / "control" / "human_actions" / "pending").glob("*.json")
        ) + list(
            (plan_dir / "state" / "human_actions" / "applied").glob("*.json")
        )
        if bound_records:
            raise ContractError(
                "authorization proposal is already bound; create a fresh plan"
            )
    atomic_write_json(proposal_path, proposal)
    return {
        "ok": True,
        "authorization_proposal_path": str(proposal_path),
        "authorization_proposal_sha256": sha256_file(proposal_path),
        "prepared_operation_id": prepared_operation_id,
        "record_id": record_id,
        "contract_version": contract["contract_version"],
        "contract_sha256": proposal["contract_sha256"],
        "stage_id": envelope["stage_id"],
        "stage_envelope_sha256": proposal["stage_envelope_sha256"],
        "evaluation_profile_sha256": proposal["evaluation_profile_sha256"],
        "checkpoint_capacity_sha256": proposal[
            "checkpoint_capacity_sha256"
        ],
        "incumbent_sha256": incumbent_sha256,
        "continuation_stage_id": continuation_stage_id,
        "continuation_stage_limit": proposal["continuation_stage_limit"],
    }


def command_init_staged_research(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    state_path = staged_state_path(plan_dir)
    contract_path = Path(args.contract).resolve()
    envelope_path = Path(args.stage_envelope).resolve()
    evaluation_path = Path(args.evaluation_profile).resolve()
    capacity_path = Path(args.checkpoint_capacity).resolve()
    contract = read_json(contract_path)
    envelope = read_json(envelope_path)
    evaluation = read_json(evaluation_path)
    capacity = read_json(capacity_path)
    staged_validate_contract(contract)
    staged_validate_evaluation_profile(evaluation)
    staged_validate_capacity(capacity)
    staged_require_sha256(args.incumbent_sha256, "incumbent_sha256")
    staged_validate_envelope(
        envelope, contract["contract_version"], args.incumbent_sha256,
        first=True, plan_dir=plan_dir,
        require_manifest=not state_path.exists(),
    )
    staged_validate_profile_envelope_compatibility(
        evaluation, envelope, strict=not state_path.exists(),
    )
    if state_path.exists():
        repaired_legacy_copy = staged_repair_legacy_canonical_copies(
            plan_dir,
            contract_path,
            envelope_path,
            evaluation_path,
            capacity_path,
            Path(args.authorization_receipt).resolve(),
        )
        state = staged_load_state(plan_dir)
        expected = {
            "contract_sha256": sha256_file(contract_path),
            "active_stage_envelope_sha256": sha256_file(envelope_path),
            "evaluation_profile_sha256": sha256_file(evaluation_path),
            "checkpoint_capacity_sha256": sha256_file(capacity_path),
        }
        if any(state.get(key) != value for key, value in expected.items()):
            raise ContractError("staged research initialization collision")
        supplied_authorization = Path(args.authorization_receipt).resolve()
        if supplied_authorization != Path(state["owner_authorization_path"]).resolve():
            raise ContractError("staged research owner authorization path changed")
        if repaired_legacy_copy:
            _staged_ensure_audit_once_locked(
                plan_dir,
                "staged_json_canonicalization_repaired",
                {"contract_sha256": state["contract_sha256"]},
                {
                    "contract_version": state["contract_version"],
                    "repair_scope": "byte_preserving_contract_copy",
                    "semantic_content_changed": False,
                },
            )
        else:
            _staged_ensure_audit_once_locked(
                plan_dir,
                "staged_research_initialized",
                {"contract_version": contract["contract_version"]},
                {
                    "contract_sha256": state["contract_sha256"],
                    "stage_id": envelope["stage_id"],
                    "stage_envelope_sha256": state[
                        "active_stage_envelope_sha256"
                    ],
                    "evaluation_profile_sha256": state[
                        "evaluation_profile_sha256"
                    ],
                    "checkpoint_capacity_sha256": state[
                        "checkpoint_capacity_sha256"
                    ],
                    "executable_stage_count": 1,
                    "controller_authoritative": True,
                },
            )
        return {"ok": True, "idempotent": True, **state}
    authorization_path = Path(args.authorization_receipt).resolve()
    authorization = validate_applied_action_receipt(
        plan_dir, authorization_path, "authorize_contract",
    )
    expected_authorization = {
        "contract_version": contract["contract_version"],
        "contract_sha256": sha256_file(contract_path),
        "stage_id": envelope["stage_id"],
        "stage_envelope_sha256": sha256_file(envelope_path),
    }
    if authorization.get("record_id") != contract["authorization_receipt_id"]:
        raise ContractError("optimization contract authorization receipt ID mismatch")
    details = authorization.get("details", {})
    if any(details.get(key) != value for key, value in expected_authorization.items()):
        raise ContractError("owner authorization does not bind contract and first stage")
    proposal_path_value = details.get("authorization_proposal_path")
    proposal_sha256 = details.get("authorization_proposal_sha256")
    if proposal_path_value is not None or proposal_sha256 is not None:
        proposal_path = Path(str(proposal_path_value)).resolve()
        canonical_proposal = (
            plan_dir / "control" / "human_authorization_required.json"
        ).resolve()
        if (
            proposal_path != canonical_proposal
            or not proposal_path.is_file()
            or sha256_file(proposal_path) != proposal_sha256
        ):
            raise ContractError("owner authorization proposal binding changed")
        proposal = read_json(proposal_path)
        proposal_expected = {
            "status": "AWAITING_HUMAN_AUTHORIZATION",
            "proposal_kind": "authorize_contract",
            "plan_id": args.plan_id,
            "record_id": authorization.get("record_id"),
            "contract_version": contract["contract_version"],
            "contract_path": str(contract_path),
            "contract_sha256": sha256_file(contract_path),
            "stage_id": envelope["stage_id"],
            "stage_envelope_path": str(envelope_path),
            "stage_envelope_sha256": sha256_file(envelope_path),
            "evaluation_profile_path": str(evaluation_path),
            "evaluation_profile_sha256": sha256_file(evaluation_path),
            "checkpoint_capacity_path": str(capacity_path),
            "checkpoint_capacity_sha256": sha256_file(capacity_path),
            "incumbent_sha256": args.incumbent_sha256,
        }
        if any(
            proposal.get(field) != value
            for field, value in proposal_expected.items()
        ):
            raise ContractError(
                "owner authorization proposal does not bind bootstrap closure"
            )
    root = staged_root(plan_dir)
    root.mkdir(parents=True, exist_ok=True)
    contract_target = root / "contracts" / f"{contract['contract_version']}.json"
    stage_dir = staged_stage_dir(plan_dir, envelope["stage_id"])
    contract_was_absent = not contract_target.exists()
    staged_copy_immutable(contract_path, contract_target)
    if contract_was_absent:
        _staged_fault_after_artifact("init")
    staged_copy_immutable(evaluation_path, root / "evaluation-profile.json")
    staged_copy_immutable(capacity_path, root / "checkpoint-capacity.json")
    staged_copy_immutable(capacity_path, root / "capacity-ledger.json")
    staged_copy_immutable(envelope_path, stage_dir / "envelope.json")
    staged_initialize_usage_ledger(plan_dir, envelope)
    state = {
        "schema_version": 1,
        "governance_version": STAGED_GOVERNANCE_VERSION,
        "plan_id": args.plan_id,
        "contract_version": contract["contract_version"],
        "contract_sha256": sha256_file(contract_target),
        "evaluation_profile_sha256": sha256_file(root / "evaluation-profile.json"),
        "checkpoint_capacity_sha256": sha256_file(root / "checkpoint-capacity.json"),
        "owner_authorization_sha256": sha256_file(authorization_path),
        "owner_authorization_path": str(authorization_path),
        "owner_authorization_action": "authorize_contract",
        "active_stage_authorization_path": str(authorization_path),
        "active_stage_authorization_sha256": sha256_file(authorization_path),
        "active_stage_authorization_action": "authorize_contract",
        "active_stage_id": envelope["stage_id"],
        "active_stage_envelope_sha256": sha256_file(stage_dir / "envelope.json"),
        "current_incumbent_sha256": args.incumbent_sha256,
        "state": "CONTRACTED",
        "audit_revision": 0,
        "next_stage_compiled": False,
    }
    validate_schema(state, read_json(STAGED_RESEARCH_SCHEMA))
    atomic_write_json(state_path, state)
    event = _staged_ensure_audit_once_locked(
        plan_dir,
        "staged_research_initialized",
        {"contract_version": contract["contract_version"]},
        {
            "contract_sha256": state["contract_sha256"],
            "stage_id": envelope["stage_id"],
            "stage_envelope_sha256": state["active_stage_envelope_sha256"],
            "evaluation_profile_sha256": state["evaluation_profile_sha256"],
            "checkpoint_capacity_sha256": state["checkpoint_capacity_sha256"],
            "executable_stage_count": 1,
            "controller_authoritative": True,
        },
    )
    return {
        "ok": True, **read_json(state_path), "executable_stage_count": 1,
        "event": event,
    }


def command_revise_unstarted_stage(args: argparse.Namespace) -> dict[str, Any]:
    """Replace only an unstarted first stage through fresh owner authorization.

    This is a forward-only correction path for deterministic draft defects.  It
    preserves the superseded contract/stage, refuses any stage that has passed
    preflight or reserved capacity, and never refunds a frontier call.
    """
    plan_dir = Path(args.plan_dir).resolve()
    with staged_transaction_lock(plan_dir):
        state = staged_load_state(plan_dir)
        current_stage_dir = staged_stage_dir(plan_dir, state["active_stage_id"])
        if state["state"] != "CONTRACTED" or (current_stage_dir / "preflight.json").exists():
            raise ContractError(
                "unstarted-stage revision requires CONTRACTED state before preflight"
            )
        root = staged_root(plan_dir)
        capacity = read_json(root / "capacity-ledger.json")
        baseline_capacity = read_json(root / "checkpoint-capacity.json")
        if capacity != baseline_capacity:
            raise ContractError("unstarted-stage revision refuses consumed capacity")
        frontier_budget = frontier_root(plan_dir) / "budget.json"
        if frontier_budget.exists():
            ledger = read_json(frontier_budget)
            if ledger.get("request_ids") or any(
                ledger.get(field, 0) != 0
                for field in (
                    "reserved_calls", "reserved_input_tokens",
                    "reserved_output_tokens",
                )
            ):
                raise ContractError(
                    "unstarted-stage revision refuses frontier reservations"
                )

        contract_path = Path(args.contract).resolve()
        envelope_path = Path(args.stage_envelope).resolve()
        evaluation_path = Path(args.evaluation_profile).resolve()
        capacity_path = Path(args.checkpoint_capacity).resolve()
        authorization_path = Path(args.authorization_receipt).resolve()
        contract = read_json(contract_path)
        envelope = read_json(envelope_path)
        evaluation = read_json(evaluation_path)
        incoming_capacity = read_json(capacity_path)
        staged_validate_contract(contract)
        staged_validate_evaluation_profile(evaluation)
        staged_validate_capacity(incoming_capacity)
        if contract["contract_version"] == state["contract_version"]:
            raise ContractError("revised first stage requires a new contract_version")
        if envelope.get("stage_id") == state["active_stage_id"]:
            raise ContractError("revised first stage requires a new stage_id")
        staged_validate_envelope(
            envelope,
            contract["contract_version"],
            state["current_incumbent_sha256"],
            first=True,
            plan_dir=plan_dir,
            require_manifest=True,
        )
        staged_validate_profile_envelope_compatibility(evaluation, envelope)
        authorization = validate_applied_action_receipt(
            plan_dir, authorization_path, "authorize_contract",
        )
        expected_authorization = {
            "contract_version": contract["contract_version"],
            "contract_sha256": sha256_file(contract_path),
            "stage_id": envelope["stage_id"],
            "stage_envelope_sha256": sha256_file(envelope_path),
        }
        if (
            authorization.get("record_id")
            != contract["authorization_receipt_id"]
            or any(
                authorization.get("details", {}).get(key) != value
                for key, value in expected_authorization.items()
            )
        ):
            raise ContractError(
                "owner authorization does not bind revised contract and first stage"
            )

        contract_target = (
            root / "contracts" / f"{contract['contract_version']}.json"
        )
        stage_dir = staged_stage_dir(plan_dir, envelope["stage_id"])
        prior_evaluation_path = root / "evaluation-profile.json"
        prior_capacity_path = root / "checkpoint-capacity.json"
        staged_copy_immutable(
            prior_evaluation_path,
            root / "evaluation-profiles" / f"{state['contract_version']}.json",
        )
        staged_copy_immutable(
            prior_capacity_path,
            root / "checkpoint-capacities" / f"{state['contract_version']}.json",
        )
        staged_copy_immutable(contract_path, contract_target)
        staged_copy_immutable(envelope_path, stage_dir / "envelope.json")
        atomic_write_bytes(
            prior_evaluation_path, evaluation_path.read_bytes(), immutable=True,
        )
        atomic_write_bytes(
            prior_capacity_path, capacity_path.read_bytes(), immutable=True,
        )
        atomic_write_bytes(
            root / "capacity-ledger.json", capacity_path.read_bytes(),
        )
        staged_initialize_usage_ledger(plan_dir, envelope)
        prior = {
            "contract_version": state["contract_version"],
            "contract_sha256": state["contract_sha256"],
            "stage_id": state["active_stage_id"],
            "stage_envelope_sha256": state["active_stage_envelope_sha256"],
            "evaluation_profile_sha256": state["evaluation_profile_sha256"],
            "checkpoint_capacity_sha256": state["checkpoint_capacity_sha256"],
        }
        state.update({
            "contract_version": contract["contract_version"],
            "contract_sha256": sha256_file(contract_target),
            "owner_authorization_path": str(authorization_path),
            "owner_authorization_sha256": sha256_file(authorization_path),
            "owner_authorization_action": "authorize_contract",
            "active_stage_authorization_path": str(authorization_path),
            "active_stage_authorization_sha256": sha256_file(authorization_path),
            "active_stage_authorization_action": "authorize_contract",
            "active_stage_id": envelope["stage_id"],
            "active_stage_envelope_sha256": sha256_file(stage_dir / "envelope.json"),
            "evaluation_profile_sha256": sha256_file(prior_evaluation_path),
            "checkpoint_capacity_sha256": sha256_file(prior_capacity_path),
            "next_stage_compiled": False,
        })
        validate_schema(state, read_json(STAGED_RESEARCH_SCHEMA))
        atomic_write_json(staged_state_path(plan_dir), state)
        _staged_ensure_audit_once_locked(
            plan_dir,
            "unstarted_stage_revised",
            {"contract_version": state["contract_version"]},
            {
                **{f"prior_{key}": value for key, value in prior.items()},
                "contract_sha256": state["contract_sha256"],
                "stage_id": state["active_stage_id"],
                "stage_envelope_sha256": state["active_stage_envelope_sha256"],
                "authorization_receipt_sha256": state[
                    "active_stage_authorization_sha256"
                ],
                "frontier_calls_spent": 0,
            },
        )
        return {"ok": True, **read_json(staged_state_path(plan_dir))}


def staged_preflight_payload(
    plan_dir: Path, raw_path: Path,
) -> dict[str, Any]:
    state = staged_load_state(plan_dir)
    try:
        raw_path.resolve().relative_to(plan_dir)
    except ValueError as exc:
        raise ContractError("preflight raw inputs must be inside the plan") from exc
    if not raw_path.is_file() or raw_path.is_symlink():
        raise ContractError("preflight raw inputs must be a canonical regular artifact")
    raw = read_json(raw_path)
    forbidden_labels = {"pass", "fail", "not_applicable"}
    if any(
        isinstance(value, str) and value.lower() in forbidden_labels
        for value in _walk_json_values(raw)
    ):
        raise ContractError("preflight accepts raw evidence, not caller verdict labels")
    envelope = read_json(
        staged_stage_dir(plan_dir, state["active_stage_id"]) / "envelope.json",
    )
    budget = envelope["stage_budget_and_stop"]
    observation_only = (
        envelope["stage_kind"] == "research"
        and budget["evaluation_calls"] == 0
    )
    required = {
        "verdict_truth_table", "statistical_design",
        "training_evaluation_matrix", "conditional_state_machine",
        "critical_path",
    }
    if observation_only:
        required.add("source_manifest")
    if set(raw) != required:
        raise ContractError("preflight raw inputs have an invalid closed shape")
    capacity_path = staged_root(plan_dir) / "capacity-ledger.json"
    capacity = read_json(capacity_path)
    staged_validate_capacity(capacity)
    verified_source_manifest: list[dict[str, Any]] = []
    evaluator_conformance: dict[str, Any] | None = None
    report_validator_conformance: dict[str, Any] | None = None
    if observation_only:
        implementation_materials = [
            item for item in envelope.get("review_material_manifest", [])
            if item.get("purpose") == "evaluator_implementation"
        ]
        if len(implementation_materials) != 1:
            raise ContractError(
                "observation-only preflight requires one frozen evaluator "
                "implementation review material"
            )
        implementation_material = implementation_materials[0]
        implementation_path = normalize_owned_path(
            plan_dir, str(plan_dir / implementation_material["path"]),
        )
        shipped_implementation_path = SCRIPT_DIR / "source_inventory_validator.py"
        if (
            implementation_path.is_symlink()
            or not implementation_path.is_file()
            or implementation_material["sha256"]
            != sha256_file(implementation_path)
            or sha256_file(implementation_path)
            != sha256_file(shipped_implementation_path)
        ):
            raise ContractError(
                "frozen source inventory evaluator does not match Runtime enforcement"
            )
        try:
            suite = run_source_inventory_conformance_suite()
        except SourceInventoryValidationError as exc:
            raise ContractError(
                f"source inventory evaluator conformance failed: {exc}"
            ) from exc
        evaluator_conformance = {
            "implementation_path": str(implementation_path),
            "implementation_sha256": sha256_file(implementation_path),
            "runtime_implementation_path": str(shipped_implementation_path),
            "runtime_implementation_sha256": sha256_file(
                shipped_implementation_path
            ),
            "runtime_byte_identity_verified": True,
            **suite,
        }
        report_materials = {
            item.get("purpose"): item
            for item in envelope.get("review_material_manifest", [])
            if item.get("purpose") in {
                "stage_report_validator_implementation",
                "stage_report_validator_conformance",
            }
        }
        if set(report_materials) != {
            "stage_report_validator_implementation",
            "stage_report_validator_conformance",
        }:
            raise ContractError(
                "observation-only preflight requires one frozen stage-report "
                "validator implementation and conformance receipt"
            )
        report_implementation_path = normalize_owned_path(
            plan_dir,
            str(plan_dir / report_materials[
                "stage_report_validator_implementation"
            ]["path"]),
        )
        report_conformance_path = normalize_owned_path(
            plan_dir,
            str(plan_dir / report_materials[
                "stage_report_validator_conformance"
            ]["path"]),
        )
        shipped_report_path = SCRIPT_DIR / "stage_report_validator.py"
        report_suite = run_stage_report_conformance_suite()
        if (
            report_implementation_path.is_symlink()
            or report_conformance_path.is_symlink()
            or not report_implementation_path.is_file()
            or not report_conformance_path.is_file()
            or report_materials[
                "stage_report_validator_implementation"
            ]["sha256"] != sha256_file(report_implementation_path)
            or report_materials[
                "stage_report_validator_conformance"
            ]["sha256"] != sha256_file(report_conformance_path)
            or sha256_file(report_implementation_path)
            != sha256_file(shipped_report_path)
            or read_json(report_conformance_path) != report_suite
        ):
            raise ContractError(
                "frozen stage-report validator does not match Runtime enforcement"
            )
        report_validator_conformance = {
            "implementation_path": str(report_implementation_path),
            "implementation_sha256": sha256_file(report_implementation_path),
            "runtime_implementation_path": str(shipped_report_path),
            "runtime_implementation_sha256": sha256_file(shipped_report_path),
            "runtime_byte_identity_verified": True,
            "conformance_path": str(report_conformance_path),
            "conformance_sha256": sha256_file(report_conformance_path),
            **report_suite,
        }
        source_manifest = raw["source_manifest"]
        if not isinstance(source_manifest, list) or not source_manifest:
            raise ContractError(
                "observation-only preflight requires a non-empty source manifest"
            )
        seen_paths: set[str] = set()
        for index, item in enumerate(source_manifest):
            if not isinstance(item, dict) or set(item) != {
                "path", "sha256", "symbol", "line_start",
            }:
                raise ContractError(
                    f"source_manifest[{index}] must bind path, sha256, symbol, "
                    "and line_start"
                )
            raw_source = item.get("path")
            expected_sha = item.get("sha256")
            symbol = item.get("symbol")
            line_start = item.get("line_start")
            if not isinstance(raw_source, str) or not Path(raw_source).is_absolute():
                raise ContractError("source manifest paths must be absolute")
            staged_require_sha256(expected_sha, "source_manifest.sha256")
            source_path = Path(raw_source)
            if (
                source_path.is_symlink()
                or not source_path.is_file()
                or not os.access(source_path, os.R_OK)
                or sha256_file(source_path) != expected_sha
            ):
                raise ContractError(
                    f"source manifest identity is unavailable or changed: {raw_source}"
                )
            canonical_source = str(source_path.resolve())
            if canonical_source != raw_source or canonical_source in seen_paths:
                raise ContractError("source manifest paths must be canonical and unique")
            source_bytes = source_path.read_bytes()
            try:
                source_text = source_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ContractError(
                    f"source manifest must be UTF-8 text: {raw_source}"
                ) from exc
            lines = source_text.splitlines()
            if (
                not isinstance(symbol, str)
                or SYMBOL_RE.fullmatch(symbol) is None
                or isinstance(line_start, bool)
                or not isinstance(line_start, int)
                or not 1 <= line_start <= len(lines)
                or not symbol_occurs_on_line(symbol, lines[line_start - 1])
            ):
                raise ContractError(
                    f"source_manifest[{index}] symbol/line_start is not exact"
                )
            seen_paths.add(canonical_source)
            verified_source_manifest.append({
                "path": canonical_source, "sha256": expected_sha,
                "symbol": symbol, "line_start": line_start,
                "size_bytes": source_path.stat().st_size,
                "line_count": len(lines),
            })
    truth = raw["verdict_truth_table"]
    expected_truth = {
        "accept": {
            "resulting_incumbent": "candidate", "advancement": "record",
        },
        "reject": {
            "resulting_incumbent": "incumbent", "advancement": "record",
        },
        "escalate": {
            "resulting_incumbent": "incumbent", "advancement": "paused",
        },
    }
    if observation_only:
        if (
            not isinstance(truth, dict)
            or set(truth) != {"applicable", "rationale"}
            or truth.get("applicable") is not False
            or not isinstance(truth.get("rationale"), str)
            or not truth["rationale"].strip()
        ):
            raise ContractError(
                "observation-only preflight must declare why no Gate verdict applies"
            )
        truth_result = "not_applicable"
    elif truth != expected_truth:
        raise ContractError("preflight verdict truth table is invalid")
    else:
        truth_result = "pass"
    statistical = raw["statistical_design"]
    if not isinstance(statistical, dict) or not isinstance(
        statistical.get("applicable"), bool,
    ):
        raise ContractError("statistical design applicability is invalid")
    expected_statistical_keys = (
        {
            "applicable", "planned_sample_size", "minimum_sample_size",
            "planned_power", "minimum_power",
        }
        if statistical["applicable"]
        else {"applicable", "rationale"}
    )
    if set(statistical) != expected_statistical_keys:
        raise ContractError("statistical design has an invalid closed shape")
    statistical_result = "not_applicable"
    if statistical["applicable"]:
        planned = require_non_negative_int(
            statistical.get("planned_sample_size"),
            "statistical_design.planned_sample_size",
        )
        minimum = require_non_negative_int(
            statistical.get("minimum_sample_size"),
            "statistical_design.minimum_sample_size",
        )
        power = require_finite_number(
            statistical.get("planned_power"), "statistical_design.planned_power",
        )
        minimum_power = require_finite_number(
            statistical.get("minimum_power"), "statistical_design.minimum_power",
        )
        if minimum < 1 or planned < minimum or not 0 < minimum_power <= power <= 1:
            raise ContractError("statistical design is infeasible")
        statistical_result = "pass"
    elif not isinstance(statistical.get("rationale"), str) or not statistical["rationale"].strip():
        raise ContractError("statistical not-applicable rationale is required")
    matrix = raw["training_evaluation_matrix"]
    if not isinstance(matrix, dict) or not isinstance(matrix.get("applicable"), bool):
        raise ContractError("training/evaluation applicability is invalid")
    expected_matrix_keys = (
        {"applicable", "training_ids", "evaluation_ids"}
        if matrix["applicable"]
        else {"applicable", "rationale"}
    )
    if set(matrix) != expected_matrix_keys:
        raise ContractError("training/evaluation matrix has an invalid closed shape")
    matrix_result = "not_applicable"
    if matrix["applicable"]:
        training = matrix.get("training_ids")
        evaluation = matrix.get("evaluation_ids")
        if (
            not isinstance(training, list) or not training
            or not isinstance(evaluation, list) or not evaluation
            or len(training) != len(set(training))
            or len(evaluation) != len(set(evaluation))
            or set(training) & set(evaluation)
        ):
            raise ContractError("training/evaluation sets overlap or are invalid")
        matrix_result = "pass"
    elif not isinstance(matrix.get("rationale"), str) or not matrix["rationale"].strip():
        raise ContractError("training/evaluation not-applicable rationale is required")
    machine = raw["conditional_state_machine"]
    transitions = machine.get("transitions") if isinstance(machine, dict) else None
    if (
        not isinstance(machine, dict)
        or set(machine) != {"initial", "transitions"}
        or machine.get("initial") != "CONTRACTED"
        or not isinstance(transitions, list)
    ):
        raise ContractError("conditional state machine is invalid")
    graph: dict[str, set[str]] = {}
    transition_ids: set[str] = set()
    for item in transitions:
        if not isinstance(item, dict) or set(item) != {"id", "from", "event", "to"}:
            raise ContractError("conditional transition has an invalid closed shape")
        staged_require_id(item["id"], "transition.id")
        if item["id"] in transition_ids:
            raise ContractError("conditional transition IDs must be unique")
        transition_ids.add(item["id"])
        graph.setdefault(item["from"], set()).add(item["to"])
    reachable = {"CONTRACTED"}
    while True:
        expanded = reachable | {
            target
            for source in reachable
            for target in graph.get(source, set())
        }
        if expanded == reachable:
            break
        reachable = expanded
    required_states = (
        {"STAGE_AUTHORIZED", "DEVELOPING", "RECORDED", "COMPLETE", "PAUSED"}
        if observation_only
        else {
            "STAGE_AUTHORIZED", "CANDIDATE_FROZEN", "GATE_QUERIED",
            "RECORDED", "PAUSED",
        }
    )
    if not required_states <= reachable:
        raise ContractError("conditional state machine has an unreachable state")
    critical = raw["critical_path"]
    ordered = critical.get("ordered_transition_ids") if isinstance(critical, dict) else None
    cp_bindings = critical.get("checkpoint_after_transition") if isinstance(critical, dict) else None
    if (
        not isinstance(critical, dict)
        or set(critical) != {
            "ordered_transition_ids", "checkpoint_after_transition",
        }
        or not isinstance(ordered, list) or not ordered
        or len(ordered) != len(set(ordered))
        or any(item not in transition_ids for item in ordered)
        or not isinstance(cp_bindings, dict)
        or (
            set(cp_bindings) != {"CP-01"}
            if observation_only else (
                not {"CP-01", "CP-02", "CP-04"}.issubset(cp_bindings)
                or set(cp_bindings) - {"CP-01", "CP-02", "CP-03", "CP-04"}
            )
        )
        or any(value not in ordered for value in cp_bindings.values())
    ):
        raise ContractError("current-stage critical path is broken")
    all_unspent = [
        name for name, slot in capacity["checkpoint_capacity"].items()
        if slot["spent"] == 0
    ]
    mandatory = (
        ["CP-01"] if observation_only and "CP-01" in all_unspent
        else (
            [] if observation_only else [
                item for item in all_unspent
                if item != "CP-03" or item in cp_bindings
            ]
        )
    )
    unreachable = next((item for item in mandatory if item not in cp_bindings), None)
    zero_budget = next(
        (
            field for field in (
                "time_seconds", "tool_calls", "worker_tokens",
                "review_tokens",
            )
            if budget[field] < 1
        ),
        None,
    )
    if zero_budget:
        raise ContractError(f"stage budget is not dispatchable: {zero_budget}=0")
    if observation_only:
        required_read_calls = len(verified_source_manifest)
        estimated_source_tokens = (
            sum(item["size_bytes"] for item in verified_source_manifest) + 2
        ) // 3
        required_worker_tokens = estimated_source_tokens + 8000
        if (
            budget["tool_calls"] < required_read_calls
            or budget["worker_tokens"] < required_worker_tokens
        ):
            raise ContractError(
                "observation-only stage budget cannot cover the frozen source manifest"
            )
    if unreachable is not None:
        raise ContractError(f"critical path cannot reach {unreachable}")
    capacity_view = staged_capacity_projection(capacity)
    if capacity.get("schema_version") == 2:
        stage_worker_limit = budget.get("worker_dispatches")
        if (
            isinstance(stage_worker_limit, bool)
            or not isinstance(stage_worker_limit, int)
            or stage_worker_limit < 1
        ):
            raise ContractError(
                "capacity v2 requires stage_budget_and_stop.worker_dispatches >= 1"
            )
        owner = validate_applied_action_receipt(
            plan_dir, Path(state["owner_authorization_path"]),
            state["owner_authorization_action"],
        )
        bounded = owner.get("details", {}).get("bounded_continuation_authority")
        continuation_kickoff = (
            1
            if envelope.get("source_cycle_id") is None
            and isinstance(bounded, dict)
            and bounded.get("max_automatic_crossings") == 1
            else 0
        )
        required_worker_calls = stage_worker_limit + continuation_kickoff
        if capacity_view["worker_dispatch_remaining"] < required_worker_calls:
            raise ContractError(
                "worker dispatch capacity cannot cover the stage quota and "
                "bounded continuation kickoff"
            )
        if capacity_view["stage_review_remaining"] < 1:
            raise ContractError("terminal STAGE-REVIEW capacity is unavailable")
    elif capacity["remaining_calls"] < capacity["mandatory_future_calls"]:
        raise ContractError("remaining_calls < mandatory_future_calls")
    calculators = {
        "verdict_truth_table": "controller-truth-table/v1",
        "statistical_feasibility": "controller-statistical-feasibility/v1",
        "training_evaluation_matrix": "controller-train-eval-isolation/v1",
        "conditional_state_machine": "controller-state-reachability/v1",
        "budget_arithmetic": "controller-capacity-arithmetic/v1",
        "current_stage_critical_path": "controller-critical-path/v1",
    }
    if observation_only:
        calculators["source_manifest_identity"] = (
            "controller-source-manifest/v1"
        )
        calculators["source_inventory_evaluator_conformance"] = (
            evaluator_conformance["validator_version"]
        )
        calculators["stage_report_validator_conformance"] = (
            report_validator_conformance["validator_version"]
        )
    return {
        "schema_version": 1,
        "preflight_id": f"preflight_{state['active_stage_id']}",
        "stage_id": state["active_stage_id"],
        "input_path": str(raw_path),
        "input_manifest_sha256": sha256_file(raw_path),
        "validator_versions_sha256": sha256_json(calculators),
        "calculator_versions": calculators,
        "validators": {
            "verdict_truth_table": truth_result,
            "statistical_feasibility": statistical_result,
            "training_evaluation_matrix": matrix_result,
            "conditional_state_machine": "pass",
            "budget_arithmetic": "pass",
            "current_stage_critical_path": "pass",
            **({"source_manifest_identity": "pass"} if observation_only else {}),
            **({
                "source_inventory_evaluator_conformance": "pass",
                "stage_report_validator_conformance": "pass",
            } if observation_only else {}),
        },
        "critical_path": {
            "ordered_transition_ids": ordered,
            "mandatory_checkpoint_ids": mandatory,
            **({
                "deferred_checkpoint_ids": [
                    item for item in all_unspent if item not in mandatory
                ],
            } if observation_only else {}),
            "checkpoint_after_transition": cp_bindings,
            "unreachable_transition_id": None,
        },
        **({
            "verified_source_manifest": verified_source_manifest,
            "verified_source_manifest_sha256": sha256_json(
                verified_source_manifest
            ),
            "source_budget_proof": {
                "required_read_calls": required_read_calls,
                "estimated_source_tokens": estimated_source_tokens,
                "required_worker_tokens": required_worker_tokens,
                "authorized_tool_calls": budget["tool_calls"],
                "authorized_worker_tokens": budget["worker_tokens"],
            },
            "evaluator_conformance": evaluator_conformance,
            "stage_report_validator_conformance": (
                report_validator_conformance
            ),
        } if observation_only else {}),
        "failure": {"type": None, "evidence_sha256": None},
    }


def _walk_json_values(value: Any) -> Iterator[Any]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_json_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json_values(item)
    else:
        yield value


def command_preflight_staged_research(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    raw_path = Path(args.preflight_inputs).resolve()
    payload = staged_preflight_payload(plan_dir, raw_path)
    state = staged_load_state(plan_dir)
    target = staged_stage_dir(
        plan_dir, state["active_stage_id"],
    ) / "preflight.json"
    if target.exists() and read_json(target) != payload:
        raise ContractError("current-stage preflight changed")
    if not target.exists():
        atomic_write_json(target, payload, immutable=True)
        _staged_fault_after_artifact("preflight")
    _staged_ensure_audit_once_locked(
        plan_dir,
        "stage_preflight_passed",
        {"stage_id": state["active_stage_id"]},
        {
            "preflight_sha256": sha256_file(target),
            "critical_path": payload["critical_path"],
        },
    )
    return {"ok": True, "preflight_path": str(target), "preflight_sha256": sha256_file(target)}


def staged_require_preflight(plan_dir: Path) -> dict[str, Any]:
    state = staged_load_state(plan_dir)
    path = staged_stage_dir(plan_dir, state["active_stage_id"]) / "preflight.json"
    preflight = read_json(path)
    if preflight.get("failure", {}).get("type") is not None:
        raise ContractError("current-stage preflight is not passing")
    if preflight.get("stage_id") != state["active_stage_id"]:
        raise ContractError("current-stage preflight identity mismatch")
    input_path = Path(preflight.get("input_path", "")).resolve()
    if (
        not input_path.is_file()
        or sha256_file(input_path) != preflight.get("input_manifest_sha256")
    ):
        raise ContractError("current-stage preflight raw evidence changed")
    # Do not rebuild the complete preflight after CP-01. Its critical-path and
    # capacity image intentionally change when the non-fungible CP-01 slot is
    # spent. Revalidate only immutable scientific inputs and executable
    # evaluator identity here; the applied CP-01 receipt separately binds the
    # exact frozen preflight bytes used for authorization.
    verified_sources = preflight.get("verified_source_manifest")
    if verified_sources is not None:
        if not isinstance(verified_sources, list) or not verified_sources:
            raise ContractError("current-stage preflight source manifest is invalid")
        current_sources = []
        for item in verified_sources:
            if not isinstance(item, dict) or set(item) != {
                "path", "sha256", "symbol", "line_start",
                "size_bytes", "line_count",
            }:
                raise ContractError(
                    "current-stage preflight source identity is malformed"
                )
            source_path = Path(item["path"])
            if (
                source_path.is_symlink()
                or not source_path.is_file()
                or str(source_path.resolve()) != item["path"]
                or sha256_file(source_path) != item["sha256"]
            ):
                raise ContractError(
                    "current-stage preflight source evidence changed"
                )
            try:
                source_text = source_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise ContractError(
                    "current-stage preflight source is no longer UTF-8 text"
                ) from exc
            lines = source_text.splitlines()
            if (
                not isinstance(item["symbol"], str)
                or SYMBOL_RE.fullmatch(item["symbol"]) is None
                or isinstance(item["line_start"], bool)
                or not isinstance(item["line_start"], int)
                or not 1 <= item["line_start"] <= len(lines)
                or not symbol_occurs_on_line(
                    item["symbol"], lines[item["line_start"] - 1]
                )
            ):
                raise ContractError(
                    "current-stage preflight source selection changed"
                )
            current_sources.append({
                "path": item["path"],
                "sha256": item["sha256"],
                "symbol": item["symbol"],
                "line_start": item["line_start"],
                "size_bytes": source_path.stat().st_size,
                "line_count": len(lines),
            })
        if (
            current_sources != verified_sources
            or sha256_json(current_sources)
            != preflight.get("verified_source_manifest_sha256")
        ):
            raise ContractError("current-stage preflight source evidence changed")
    evaluator = preflight.get("evaluator_conformance")
    if evaluator is not None:
        implementation_path = Path(evaluator.get("implementation_path", ""))
        shipped_path = SCRIPT_DIR / "source_inventory_validator.py"
        if (
            implementation_path.is_symlink()
            or not implementation_path.is_file()
            or sha256_file(implementation_path)
            != evaluator.get("implementation_sha256")
            or sha256_file(implementation_path) != sha256_file(shipped_path)
            or evaluator.get("runtime_implementation_path") != str(shipped_path)
            or evaluator.get("runtime_implementation_sha256")
            != sha256_file(shipped_path)
            or evaluator.get("runtime_byte_identity_verified") is not True
        ):
            raise ContractError(
                "current-stage preflight evaluator implementation changed"
            )
        try:
            current_suite = run_source_inventory_conformance_suite()
        except SourceInventoryValidationError as exc:
            raise ContractError(
                f"current-stage preflight evaluator conformance failed: {exc}"
            ) from exc
        recorded_suite = {
            key: evaluator.get(key) for key in (
                "validator_id", "validator_version", "case_count", "cases",
                "status",
            )
        }
        if current_suite != recorded_suite:
            raise ContractError(
                "current-stage preflight evaluator conformance changed"
            )
    report_evaluator = preflight.get("stage_report_validator_conformance")
    if report_evaluator is not None:
        implementation_path = Path(
            report_evaluator.get("implementation_path", "")
        )
        conformance_path = Path(
            report_evaluator.get("conformance_path", "")
        )
        shipped_path = SCRIPT_DIR / "stage_report_validator.py"
        current_suite = run_stage_report_conformance_suite()
        recorded_suite = {
            key: report_evaluator.get(key) for key in (
                "validator_id", "validator_version", "case_count", "cases",
                "status",
            )
        }
        if (
            implementation_path.is_symlink()
            or conformance_path.is_symlink()
            or not implementation_path.is_file()
            or not conformance_path.is_file()
            or sha256_file(implementation_path)
            != report_evaluator.get("implementation_sha256")
            or sha256_file(implementation_path) != sha256_file(shipped_path)
            or report_evaluator.get("runtime_implementation_path")
            != str(shipped_path)
            or report_evaluator.get("runtime_implementation_sha256")
            != sha256_file(shipped_path)
            or report_evaluator.get("runtime_byte_identity_verified") is not True
            or sha256_file(conformance_path)
            != report_evaluator.get("conformance_sha256")
            or read_json(conformance_path) != current_suite
            or recorded_suite != current_suite
        ):
            raise ContractError(
                "current-stage preflight stage-report validator changed"
            )
    return preflight


def staged_reserve_dispatch(
    plan_dir: Path, *, checkpoint: str | None = None, dispatch_id: str,
) -> None:
    with staged_transaction_lock(plan_dir):
        _staged_reserve_dispatch_locked(
            plan_dir, checkpoint=checkpoint, dispatch_id=dispatch_id,
        )


def staged_reserve_worker_dispatch_and_budget(
    plan_dir: Path, *, dispatch_id: str, usage: dict[str, int],
) -> None:
    """Precheck and reserve both worker ledgers under one controller lock."""
    with staged_transaction_lock(plan_dir):
        _staged_precheck_dispatch_locked(
            plan_dir, checkpoint=None, dispatch_id=dispatch_id,
        )
        state = staged_load_state(plan_dir)
        stage_usage = read_json(
            staged_stage_dir(plan_dir, state["active_stage_id"]) / "usage-ledger.json"
        )
        charged_usage = dict(usage)
        if "worker_dispatches" in stage_usage.get("limits", {}):
            charged_usage["worker_dispatches"] = 1
        _staged_consume_stage_budget_locked(
            plan_dir, f"worker:{dispatch_id}", charged_usage,
        )
        _staged_reserve_dispatch_locked(
            plan_dir, checkpoint=None, dispatch_id=dispatch_id,
        )


def _staged_precheck_dispatch_locked(
    plan_dir: Path, *, checkpoint: str | None, dispatch_id: str,
) -> None:
    if not staged_is_active(plan_dir):
        return
    root = staged_root(plan_dir)
    reservation_path = root / "dispatch-reservations" / f"{dispatch_id}.json"
    journal_path = root / "dispatch-journals" / f"{dispatch_id}.json"
    if journal_path.exists():
        journal = read_json(journal_path)
        if (
            journal.get("dispatch_id") != dispatch_id
            or journal.get("checkpoint") != checkpoint
        ):
            raise ContractError("staged dispatch journal identity collision")
        return
    if reservation_path.exists():
        raise ContractError(
            "staged dispatch marker exists without its recovery journal"
        )
    staged_require_preflight(plan_dir)
    state = staged_load_state(plan_dir)
    if checkpoint is None and state["state"] not in {
        "STAGE_AUTHORIZED", "DEVELOPING",
    }:
        raise ContractError("worker dispatch requires controller-authorized stage")
    capacity = read_json(root / "capacity-ledger.json")
    staged_validate_capacity(capacity)
    if checkpoint is None and capacity.get("schema_version") == 2:
        usage = read_json(
            staged_stage_dir(plan_dir, state["active_stage_id"]) / "usage-ledger.json"
        )
        limit = usage.get("limits", {}).get("worker_dispatches")
        used = usage.get("used", {}).get("worker_dispatches")
        already_charged = f"worker:{dispatch_id}" in usage.get(
            "reservation_ids", []
        )
        if (
            isinstance(limit, bool) or not isinstance(limit, int)
            or isinstance(used, bool) or not isinstance(used, int)
            or (used >= limit and not already_charged)
        ):
            raise ContractError("stage worker_dispatches capacity is exhausted")
    staged_capacity_reserve_image(capacity, checkpoint)


def _staged_reserve_dispatch_locked(
    plan_dir: Path, *, checkpoint: str | None = None, dispatch_id: str,
) -> None:
    _staged_precheck_dispatch_locked(
        plan_dir, checkpoint=checkpoint, dispatch_id=dispatch_id,
    )
    if not staged_is_active(plan_dir):
        return
    root = staged_root(plan_dir)
    reservation_path = (
        root / "dispatch-reservations" / f"{dispatch_id}.json"
    )
    journal_path = root / "dispatch-journals" / f"{dispatch_id}.json"
    capacity_path = root / "capacity-ledger.json"
    if journal_path.exists():
        journal = read_json(journal_path)
        if (
            journal.get("dispatch_id") != dispatch_id
            or journal.get("checkpoint") != checkpoint
        ):
            raise ContractError("staged dispatch journal identity collision")
    else:
        if reservation_path.exists():
            raise ContractError(
                "staged dispatch marker exists without its recovery journal"
            )
        staged_require_preflight(plan_dir)
        state = staged_load_state(plan_dir)
        allowed_dispatch_states = {"STAGE_AUTHORIZED", "DEVELOPING"}
        if checkpoint is None and state["state"] not in allowed_dispatch_states:
            raise ContractError(
                "worker dispatch requires controller-authorized stage"
            )
        capacity = read_json(capacity_path)
        staged_validate_capacity(capacity)
        capacity_after = staged_capacity_reserve_image(capacity, checkpoint)
        capacity_projection = staged_capacity_projection(capacity_after)
        marker = {
            "schema_version": 1,
            "dispatch_id": dispatch_id,
            "checkpoint": checkpoint,
            **capacity_projection,
            "reserved_at": utc_now(),
        }
        journal = {
            "schema_version": 1,
            "phase": "PREPARED",
            "dispatch_id": dispatch_id,
            "checkpoint": checkpoint,
            "stage_id": state["active_stage_id"],
            "capacity_before": capacity,
            "capacity_before_sha256": sha256_json(capacity),
            "capacity_after": capacity_after,
            "capacity_after_sha256": sha256_json(capacity_after),
            "marker_after": marker,
            "marker_after_sha256": sha256_json(marker),
            "state_before": state["state"],
            "state_after": (
                "DEVELOPING" if checkpoint is None else state["state"]
            ),
            "prepared_at": utc_now(),
        }
        atomic_write_json(journal_path, journal)
    current_capacity = read_json(capacity_path)
    current_sha = sha256_json(current_capacity)
    if current_sha == journal["capacity_before_sha256"]:
        atomic_write_json(capacity_path, journal["capacity_after"])
        _staged_fault_after_artifact("dispatch_reservation")
    elif current_sha != journal["capacity_after_sha256"]:
        raise ContractError("staged dispatch capacity is irreconcilable")
    if reservation_path.exists():
        if read_json(reservation_path) != journal["marker_after"]:
            raise ContractError("staged dispatch marker is irreconcilable")
    else:
        atomic_write_json(
            reservation_path, journal["marker_after"], immutable=True,
        )
    state = staged_load_state(plan_dir)
    if state["state"] == journal["state_before"]:
        state["state"] = journal["state_after"]
        atomic_write_json(staged_state_path(plan_dir), state)
    elif state["state"] != journal["state_after"]:
        raise ContractError("staged dispatch state is irreconcilable")
    _staged_ensure_audit_once_locked(
        plan_dir,
        "model_dispatch_reserved",
        {"dispatch_id": dispatch_id},
        {
            "stage_id": journal["stage_id"],
            "checkpoint": checkpoint,
            **staged_capacity_projection(journal["capacity_after"]),
        },
    )
    journal["phase"] = "COMMITTED"
    journal["committed_at"] = journal.get("committed_at", utc_now())
    atomic_write_json(journal_path, journal)


def command_record_role_visible_state(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    state = staged_load_state(plan_dir)
    target = staged_root(plan_dir) / "role-visible" / f"{args.call_id}.json"
    source_audit_revision = (
        read_json(target).get("audit_revision")
        if target.exists()
        else state["audit_revision"]
    )
    source_refs: list[str]
    if args.call_kind == "worker":
        run_dir = worker_run_dir(plan_dir, args.call_id)
        status_path_value = run_dir / "status.json"
        status = read_json(status_path_value)
        contract_path = Path(status.get("contract_path", ""))
        result_path = Path(status.get("result_path", ""))
        if (
            status.get("status") != "COMPLETED"
            or status.get("worker_model") != load_policy(plan_dir)["worker_model"]
            or not contract_path.is_file()
            or sha256_file(contract_path) != status.get("contract_sha256")
            or not result_path.is_file()
            or sha256_file(result_path) != status.get("result_sha256")
        ):
            raise ContractError("worker role-visible state lacks a canonical completed call")
        role = "worker"
        manifest_value = {
            "call_kind": "worker", "run_id": args.call_id,
            "contract_sha256": status["contract_sha256"],
            "result_sha256": status["result_sha256"],
            "model_policy_sha256": status["model_policy_sha256"],
            "context_capsule_sha256": status.get("context_capsule_sha256"),
        }
        source_paths = [status_path_value, contract_path, result_path]
    else:
        request_path_value, request = load_request(
            plan_dir, args.call_id, verify_live_manifest=True,
        )
        status_path_value = status_path(plan_dir, args.call_id)
        status = read_json(status_path_value)
        if status.get("state") not in {"RECEIVED", "VALIDATED", "APPLIED"}:
            raise ContractError("reviewer role-visible state requires a received frontier call")
        response_path = request_dir(plan_dir, args.call_id) / "response.json"
        validate_frontier_response_integrity(
            plan_dir, args.call_id, status, response_path,
        )
        if any(
            item["purpose"].startswith("external_transfer")
            for item in request["context_manifest"]
        ):
            raise ContractError("external transfer suite cannot enter reviewer-visible state")
        role = "reviewer"
        manifest_value = {
            "call_kind": "frontier", "request_id": args.call_id,
            "request_sha256": sha256_file(request_path_value),
            "response_sha256": sha256_file(response_path),
            "context_manifest_sha256": sha256_json(request["context_manifest"]),
            "model_policy_sha256": status["model_policy_sha256"],
        }
        source_paths = [
            request_path_value, status_path_value, response_path,
            *(Path(item["path"]) for item in request["context_manifest"]),
        ]
    for path in source_paths:
        try:
            path.resolve().relative_to(plan_dir)
        except ValueError as exc:
            raise ContractError("role-visible source reference escapes the plan") from exc
        if not path.is_file():
            raise ContractError("role-visible source reference is unresolved")
    manifest_sha = sha256_json(manifest_value)
    context_events = [{
        "event_id": f"full_context_{args.call_id}",
        "type": "full_context",
        "input_manifest_sha256": manifest_sha,
        "output_manifest_sha256": manifest_sha,
    }]
    visible = {
        "schema_version": 1,
        "call_id": args.call_id,
        "role": role,
        "audit_revision": source_audit_revision,
        "context_policy_version": "canonical-runtime-context-v1",
        "visible_message_manifest_sha256": manifest_sha,
        "context_events": context_events,
        "context_event_manifest_sha256": sha256_json(context_events),
        "source_artifact_refs": [
            str(path.resolve().relative_to(plan_dir)) for path in source_paths
        ],
        "source_artifact_sha256": {
            str(path.resolve().relative_to(plan_dir)): sha256_file(path)
            for path in source_paths
        },
        "canonical_call_manifest": manifest_value,
    }
    external_identity = read_json(
        staged_root(plan_dir) / "evaluation-profile.json",
    )["external_suite_identity_sha256"]
    if external_identity in canonical_json(visible).decode("utf-8"):
        raise ContractError("external transfer suite leaked into role-visible state")
    if target.exists():
        if read_json(target) != visible:
            raise ContractError("canonical role-visible call record changed")
    else:
        atomic_write_json(target, visible, immutable=True)
        _staged_fault_after_artifact("role_visible")
    _staged_ensure_audit_once_locked(
        plan_dir,
        "role_visible_state_recorded",
        {"call_id": visible["call_id"]},
        {
        "role": visible["role"],
        "role_visible_state_sha256": sha256_file(target),
        "source_audit_revision": visible["audit_revision"],
        },
    )
    return {"ok": True, "path": str(target), "sha256": sha256_file(target)}


def command_freeze_stage_candidate(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    state = staged_load_state(plan_dir)
    staged_require_preflight(plan_dir)
    if state["state"] not in {
        "STAGE_AUTHORIZED", "DEVELOPING", "CANDIDATE_FROZEN",
    }:
        raise ContractError("candidate freeze requires a controller-authorized stage")
    try:
        require_staged_transition(
            "freeze_candidate", state["state"], "CANDIDATE_FROZEN",
        )
    except WorkerArtifactLifecycleError as exc:
        raise ContractError(str(exc)) from exc
    stage_dir = staged_stage_dir(plan_dir, state["active_stage_id"])
    target = stage_dir / "candidate.json"
    candidate_path = Path(args.candidate).resolve()
    try:
        candidate_path.relative_to(plan_dir)
    except ValueError as exc:
        raise ContractError("stage candidate must be inside the plan directory") from exc
    if not candidate_path.is_file() or candidate_path.is_symlink():
        raise ContractError("stage candidate must be a regular artifact")
    candidate_sha = sha256_file(candidate_path)
    promotion_path = Path(args.promotion_receipt).resolve()
    promotion = read_json(promotion_path)
    run_id = promotion.get("worker_run_id", "")
    run_dir = worker_run_dir(plan_dir, run_id)
    if promotion_path != run_dir / "promotion-receipt.json":
        raise ContractError("candidate requires a canonical worker promotion receipt")
    promotion_binding = staged_canonical_file(
        promotion_path, run_dir / "promotion-receipt.json",
        "candidate promotion receipt", immutable=True,
    )
    journal_path = run_dir / "promotion-journal.json"
    status_path = run_dir / "status.json"
    journal_binding = staged_canonical_file(
        journal_path, journal_path, "candidate promotion journal",
        immutable=True,
    )
    status_binding = staged_canonical_file(
        status_path, status_path, "candidate worker status", immutable=True,
    )
    promotion_journal = read_json(journal_path)
    status = read_json(status_path)
    validate_committed_promotion_journal(
        promotion_journal, status, run_dir, promotion_binding["sha256"],
        promotion.get("artifacts", []),
    )
    worker_contract_path = Path(status.get("contract_path", "")).resolve()
    worker_result_path = Path(status.get("result_path", "")).resolve()
    policy_path = plan_dir / "state" / "model_policy.json"
    if (
        promotion_journal.get("phase") != "COMMITTED"
        or promotion_journal.get("receipt_sha256") != sha256_file(promotion_path)
        or status.get("status") != "COMPLETED"
        or status.get("worker_model") != load_policy(plan_dir)["worker_model"]
        or not worker_contract_path.is_file()
        or sha256_file(worker_contract_path) != status.get("contract_sha256")
        or not worker_result_path.is_file()
        or sha256_file(worker_result_path) != status.get("result_sha256")
        or status.get("model_policy_sha256") != sha256_file(policy_path)
        or promotion.get("contract_sha256") != status.get("contract_sha256")
        or promotion.get("result_sha256") != status.get("result_sha256")
        or not any(
            Path(item["path"]).resolve() == candidate_path
            and item["sha256"] == candidate_sha
            for item in promotion.get("artifacts", [])
        )
    ):
        raise ContractError("candidate promotion is not a committed MiniMax artifact")
    frozen_candidate_path = stage_dir / "candidate-artifact"
    if frozen_candidate_path.exists():
        if sha256_file(frozen_candidate_path) != candidate_sha:
            raise ContractError("one stage may freeze only one candidate")
    else:
        atomic_write_bytes(
            frozen_candidate_path, candidate_path.read_bytes(), immutable=True,
        )
    record = {
        "schema_version": 1,
        "stage_cycle_id": state["active_stage_id"],
        "incumbent_sha256": state["current_incumbent_sha256"],
        "candidate_sha256": candidate_sha,
        "candidate_path": str(frozen_candidate_path),
        "maturity": "full_experiment",
        "development_evidence_refs": [f"promotion:{run_id}"],
        "promotion_receipt_path": str(promotion_path),
        "promotion_receipt_sha256": promotion_binding["sha256"],
        "completed_worker_status_path": str(status_path),
        "completed_worker_status_sha256": status_binding["sha256"],
        "promotion_journal_path": str(journal_path),
        "promotion_journal_sha256": journal_binding["sha256"],
        "frozen_at": utc_now(),
    }
    if target.exists():
        staged_canonical_file(
            target, target, "candidate record", immutable=True,
        )
        prior = read_json(target)
        if set(prior) != STAGED_CANDIDATE_FIELDS:
            raise ContractError("canonical candidate record changed")
        comparable = {k: v for k, v in prior.items() if k != "frozen_at"}
        if comparable != {k: v for k, v in record.items() if k != "frozen_at"}:
            raise ContractError("one stage may freeze only one candidate")
        record = prior
    else:
        atomic_write_json(target, record, immutable=True)
        _staged_fault_after_artifact("candidate")
    maturity_path = stage_dir / "evidence-maturity.json"
    if maturity_path.exists():
        maturity = read_json(maturity_path)
        staged_validate_evidence_maturity(maturity, candidate_sha)
        if maturity["current_maturity"] != "full_experiment":
            raise ContractError("candidate maturity identity conflict")
    else:
        transitions = []
        for maturity_name, authority in (
            ("idea", "candidate_pool"),
            ("screened", f"promotion:{run_id}"),
            ("full_experiment", f"promotion:{run_id}"),
        ):
            transitions.append({
                "maturity": maturity_name, "authority": authority,
                "recorded_at": record["frozen_at"],
            })
        atomic_write_json(maturity_path, {
            "schema_version": 1,
            "evidence_id": f"evidence_{state['active_stage_id']}",
            "candidate_sha256": candidate_sha,
            "current_maturity": "full_experiment",
            "transitions": transitions,
        }, immutable=True)
    state["state"] = "CANDIDATE_FROZEN"
    atomic_write_json(staged_state_path(plan_dir), state)
    _staged_ensure_audit_once_locked(
        plan_dir,
        "stage_candidate_frozen",
        {"stage_id": state["active_stage_id"]},
        {
        "candidate_sha256": candidate_sha,
        "incumbent_sha256": state["current_incumbent_sha256"],
        },
    )
    return {"ok": True, **record}


def command_complete_observation_stage(args: argparse.Namespace) -> dict[str, Any]:
    """Deterministically terminate an observation-only research stage.

    Observation-only stages intentionally have no logical acceptance Gate. The
    Controller therefore validates the frozen MiniMax artifact with the exact
    Runtime-shipped source-inventory validator, records a typed non-Gate
    decision, and moves the stage to RECORDED so it can receive a fresh strong
    stage review. This command never manufactures reusable Gate evidence.
    """
    plan_dir = Path(args.plan_dir).resolve()
    state = staged_load_state(plan_dir)
    stage_dir = staged_stage_dir(plan_dir, state["active_stage_id"])
    envelope = read_json(stage_dir / "envelope.json")
    preflight_path = stage_dir / "preflight.json"
    preflight = read_json(preflight_path)
    budget = envelope["stage_budget_and_stop"]
    try:
        require_staged_transition(
            "complete_observation", state["state"], "RECORDED",
        )
    except WorkerArtifactLifecycleError as exc:
        raise ContractError(str(exc)) from exc
    if not (
        envelope.get("stage_kind") == "research"
        and budget.get("evaluation_calls") == 0
        and preflight.get("validators", {}).get("verdict_truth_table")
        == "not_applicable"
    ):
        raise ContractError(
            "observation completion requires an observation-only research stage"
        )
    if state["state"] not in {"CANDIDATE_FROZEN", "RECORDED"}:
        raise ContractError(
            "observation completion requires one frozen promoted Worker artifact"
        )

    candidate_path = stage_dir / "candidate.json"
    candidate = read_json(candidate_path)
    candidate_chain = staged_resolve_candidate_chain(
        plan_dir, stage_dir, candidate,
    )
    implementation = [
        item for item in envelope.get("review_material_manifest", [])
        if item.get("purpose") == "evaluator_implementation"
    ]
    if len(implementation) != 1:
        raise ContractError(
            "observation completion requires one frozen evaluator implementation"
        )
    implementation_path = normalize_owned_path(
        plan_dir, str(plan_dir / implementation[0]["path"]),
    )
    shipped_path = SCRIPT_DIR / "source_inventory_validator.py"
    implementation_sha = sha256_file(implementation_path)
    contract = read_json(
        staged_root(plan_dir) / "contracts"
        / f"{state['contract_version']}.json",
    )
    if (
        implementation_path.is_symlink()
        or implementation_path.stat().st_mode & 0o777 != 0o444
        or implementation[0].get("sha256") != implementation_sha
        or implementation_sha != sha256_file(shipped_path)
        or implementation_sha != contract["development_validator_sha256"]
    ):
        raise ContractError(
            "observation completion validator is not the frozen Runtime implementation"
        )

    source_manifest = preflight.get("verified_source_manifest")
    if not isinstance(source_manifest, list) or not source_manifest:
        raise ContractError("observation completion lacks a frozen source manifest")
    frozen_candidate = Path(candidate["candidate_path"])
    try:
        validate_source_inventory(
            frozen_candidate.read_text(encoding="utf-8"), source_manifest,
        )
    except (OSError, UnicodeError, SourceInventoryValidationError) as exc:
        raise ContractError(f"source inventory validator rejected candidate: {exc}") from exc

    validation = {
        "schema_version": 1,
        "validation_kind": "observation_source_inventory",
        "stage_cycle_id": state["active_stage_id"],
        "candidate_sha256": candidate["candidate_sha256"],
        "source_manifest_sha256": sha256_json(source_manifest),
        "development_validator_path": str(implementation_path),
        "development_validator_sha256": implementation_sha,
        "result": "pass",
        "controller_authoritative": True,
    }
    validation_path = stage_dir / "observation-validation.json"
    if validation_path.exists():
        if read_json(validation_path) != validation:
            raise ContractError("observation validation receipt collision")
    else:
        atomic_write_json(validation_path, validation, immutable=True)
        _staged_fault_after_artifact("observation_validation")

    stable_decision = {
        "schema_version": 1,
        "stage_cycle_id": state["active_stage_id"],
        "decision_kind": "observation_validation",
        "decision": "accept",
        "prior_incumbent_sha256": candidate["incumbent_sha256"],
        "candidate_sha256": candidate["candidate_sha256"],
        "resulting_incumbent_sha256": candidate["candidate_sha256"],
        "advancement_blocked": False,
        "development_validator_receipt_path": str(validation_path),
        "development_validator_receipt_sha256": sha256_file(validation_path),
        "controller_authoritative": True,
    }
    decision_path = stage_dir / "decision.json"
    if decision_path.exists():
        decision = read_json(decision_path)
        if {
            key: decision.get(key) for key in stable_decision
        } != stable_decision:
            raise ContractError("observation decision collision")
    else:
        decision = {**stable_decision, "decided_at": utc_now()}
        atomic_write_json(decision_path, decision, immutable=True)
        _staged_fault_after_artifact("observation_decision")

    state["current_incumbent_sha256"] = candidate["candidate_sha256"]
    state["state"] = "RECORDED"
    atomic_write_json(staged_state_path(plan_dir), state)
    _staged_ensure_audit_once_locked(
        plan_dir,
        "observation_stage_completed",
        {"stage_id": state["active_stage_id"]},
        {
            "candidate_sha256": candidate["candidate_sha256"],
            "worker_run_id": candidate_chain["worker_run_id"],
            "development_validator_receipt_sha256": sha256_file(validation_path),
            "logical_gate_applied": False,
            "controller_authoritative": True,
        },
    )
    return {
        "ok": True,
        "stage_id": state["active_stage_id"],
        "state": state["state"],
        "candidate_sha256": candidate["candidate_sha256"],
        "decision_path": str(decision_path),
        "decision_sha256": sha256_file(decision_path),
        "validation_receipt_path": str(validation_path),
        "validation_receipt_sha256": sha256_file(validation_path),
    }


def staged_terminal_review_evidence_paths(
    plan_dir: Path, stage_id: str,
) -> dict[str, Path]:
    """Resolve and validate the canonical evidence a terminal reviewer must see."""
    stage_dir = staged_stage_dir(plan_dir, stage_id)
    candidate_path = stage_dir / "candidate.json"
    decision_path = stage_dir / "decision.json"
    staged_canonical_file(
        candidate_path, candidate_path, "stage candidate", immutable=True,
    )
    staged_canonical_file(
        decision_path, decision_path, "stage decision", immutable=True,
    )
    candidate = read_json(candidate_path)
    staged_resolve_candidate_chain(plan_dir, stage_dir, candidate)
    decision = read_json(decision_path)
    if (
        decision.get("stage_cycle_id") != stage_id
        or decision.get("controller_authoritative") is not True
    ):
        raise ContractError("terminal stage decision is not Controller-authoritative")
    if decision.get("decision_kind") == "observation_validation":
        terminal_path = stage_dir / "observation-validation.json"
        staged_canonical_file(
            terminal_path, terminal_path,
            "observation validation receipt", immutable=True,
        )
        receipt = read_json(terminal_path)
        envelope = read_json(stage_dir / "envelope.json")
        preflight = read_json(stage_dir / "preflight.json")
        contract = read_json(
            staged_root(plan_dir) / "contracts"
            / f"{envelope['contract_version']}.json"
        )
        implementations = [
            item for item in envelope.get("review_material_manifest", [])
            if item.get("purpose") == "evaluator_implementation"
        ]
        if len(implementations) != 1:
            raise ContractError(
                "canonical observation decision lacks one evaluator implementation"
            )
        implementation_path = normalize_owned_path(
            plan_dir, str(plan_dir / implementations[0]["path"]),
        )
        expected_receipt = {
            "schema_version": 1,
            "validation_kind": "observation_source_inventory",
            "stage_cycle_id": stage_id,
            "candidate_sha256": candidate["candidate_sha256"],
            "source_manifest_sha256": sha256_json(
                preflight["verified_source_manifest"]
            ),
            "development_validator_path": str(implementation_path),
            "development_validator_sha256": sha256_file(implementation_path),
            "result": "pass",
            "controller_authoritative": True,
        }
        expected_decision = {
            "schema_version": 1,
            "stage_cycle_id": stage_id,
            "decision_kind": "observation_validation",
            "decision": "accept",
            "prior_incumbent_sha256": candidate["incumbent_sha256"],
            "candidate_sha256": candidate["candidate_sha256"],
            "resulting_incumbent_sha256": candidate["candidate_sha256"],
            "advancement_blocked": False,
            "development_validator_receipt_path": str(terminal_path),
            "development_validator_receipt_sha256": sha256_file(terminal_path),
            "controller_authoritative": True,
        }
        if (
            receipt != expected_receipt
            or set(decision) != set(expected_decision) | {"decided_at"}
            or any(decision.get(key) != value for key, value in expected_decision.items())
            or not isinstance(decision.get("decided_at"), str)
            or not decision["decided_at"]
            or implementations[0].get("sha256") != sha256_file(implementation_path)
            or contract.get("development_validator_sha256")
            != sha256_file(implementation_path)
        ):
            raise ContractError("canonical observation validation binding changed")
    else:
        terminal_path = Path(
            decision.get("evaluator_execution_receipt_path", "")
        )
        run = load_evaluator_run(plan_dir, terminal_path)
        envelope = read_json(stage_dir / "envelope.json")
        profile = read_json(staged_root(plan_dir) / "evaluation-profile.json")
        staged_validate_profile_envelope_compatibility(
            profile, envelope, strict=False,
        )
        audit_path = staged_root(plan_dir) / "audit.jsonl"
        audit = [
            strict_json_loads(line)
            for line in audit_path.read_text().splitlines() if line.strip()
        ] if audit_path.exists() else []
        value = require_finite_number(run.get("value"), "Gate evaluator value")
        threshold = profile["gate_threshold"]
        margin = profile["gate_escalation_margin"]
        if abs(value - threshold) <= margin:
            expected_decision = "escalate"
        elif profile["gate_operator"] == "ge":
            expected_decision = "accept" if value >= threshold else "reject"
        else:
            expected_decision = "accept" if value <= threshold else "reject"
        expected_resulting = (
            candidate["candidate_sha256"]
            if expected_decision == "accept"
            else candidate["incumbent_sha256"]
        )
        if (
            decision.get("evaluator_execution_receipt_sha256")
            != sha256_file(terminal_path)
            or run.get("candidate_sha256") != decision.get("candidate_sha256")
            or decision.get("decision") != expected_decision
            or decision.get("prior_incumbent_sha256")
            != candidate["incumbent_sha256"]
            or decision.get("resulting_incumbent_sha256") != expected_resulting
            or decision.get("advancement_blocked")
            is not (expected_decision == "escalate")
        ):
            raise ContractError("canonical Gate execution binding changed")
        staged_validate_terminal_gate_replay(
            plan_dir,
            {
                "contract_version": envelope["contract_version"],
                "audit_revision": len(audit),
                "current_incumbent_sha256": expected_resulting,
                "state": (
                    "PAUSED"
                    if expected_decision == "escalate" else "RECORDED"
                ),
            },
            stage_dir,
            stage_dir / "gate-query.json",
            read_json(stage_dir / "gate-query.json"),
            profile, run, decision,
        )
    return {
        "stage_candidate": candidate_path,
        "stage_decision": decision_path,
        "terminal_validation_receipt": terminal_path,
    }


def staged_expected_report_validator_receipts(
    plan_dir: Path, stage_id: str,
) -> list[dict[str, str]]:
    paths = staged_terminal_review_evidence_paths(plan_dir, stage_id)
    decision = read_json(paths["stage_decision"])
    return [{
        "kind": (
            "observation_validation"
            if decision.get("decision_kind") == "observation_validation"
            else "acceptance_evaluator_execution"
        ),
        "path": str(paths["terminal_validation_receipt"]),
        "sha256": sha256_file(paths["terminal_validation_receipt"]),
    }]


def command_create_logical_gate_query(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    state = staged_load_state(plan_dir)
    stage_dir = staged_stage_dir(plan_dir, state["active_stage_id"])
    envelope = read_json(stage_dir / "envelope.json")
    profile = read_json(staged_root(plan_dir) / "evaluation-profile.json")
    staged_validate_profile_envelope_compatibility(
        profile, envelope, strict=False,
    )
    if (
        profile.get("applicable") is False
        or envelope.get("stage_kind") == "research"
        and envelope.get("stage_budget_and_stop", {}).get("evaluation_calls") == 0
    ):
        raise ContractError(
            "inactive evaluation profile forbids a logical Gate query"
        )
    candidate = read_json(stage_dir / "candidate.json")
    if args.candidate_sha256 != candidate["candidate_sha256"]:
        raise ContractError("logical Gate query candidate mismatch")
    contract = read_json(
        staged_root(plan_dir) / "contracts" / f"{state['contract_version']}.json",
    )
    if args.evaluator_sha256 != contract["acceptance_evaluator_sha256"]:
        raise ContractError("logical Gate query evaluator mismatch")
    if args.requesting_role != "controller":
        raise ContractError("Development must not query the isolated acceptance Gate")
    query = {
        "schema_version": 1,
        "logical_gate_query_id": staged_require_id(
            args.logical_gate_query_id, "logical_gate_query_id",
        ),
        "stage_cycle_id": state["active_stage_id"],
        "candidate_sha256": candidate["candidate_sha256"],
        "evaluator_sha256": args.evaluator_sha256,
        "idempotency_key": sha256_json({
            "stage_cycle_id": state["active_stage_id"],
            "candidate_sha256": candidate["candidate_sha256"],
            "evaluator_sha256": args.evaluator_sha256,
        }),
        "transport_attempts": [],
        "applied_gate_receipt_id": None,
    }
    path = stage_dir / "gate-query.json"
    if path.exists():
        if read_json(path) != query:
            raise ContractError("candidate already has a logical Gate query")
    else:
        atomic_write_json(path, query)
        _staged_fault_after_artifact("gate_query")
    if state["state"] not in {"CANDIDATE_FROZEN", "GATE_QUERIED"}:
        raise ContractError("logical Gate query state is irreconcilable")
    state["state"] = "GATE_QUERIED"
    atomic_write_json(staged_state_path(plan_dir), state)
    _staged_ensure_audit_once_locked(
        plan_dir,
        "logical_gate_query_created",
        {"logical_gate_query_id": query["logical_gate_query_id"]},
        {
        "stage_id": state["active_stage_id"],
        "candidate_sha256": query["candidate_sha256"],
        },
    )
    return {"ok": True, **query}


def staged_validate_evidence_maturity(
    maturity: dict[str, Any], candidate_sha256: str,
) -> None:
    required = {
        "schema_version", "evidence_id", "candidate_sha256",
        "current_maturity", "transitions",
    }
    if (
        set(maturity) != required
        or maturity["schema_version"] != 1
        or maturity["candidate_sha256"] != candidate_sha256
        or not isinstance(maturity["transitions"], list)
        or not maturity["transitions"]
    ):
        raise ContractError("evidence maturity record is not canonical")
    actual = [item.get("maturity") for item in maturity["transitions"]]
    expected = list(EVIDENCE_MATURITY_ORDER[:len(actual)])
    if (
        actual != expected
        or len(actual) > len(EVIDENCE_MATURITY_ORDER)
        or maturity["current_maturity"] != actual[-1]
        or any(
            set(item) - {"maturity", "authority", "recorded_at", "cp04_request_id"}
            or not isinstance(item.get("authority"), str)
            or not item["authority"]
            for item in maturity["transitions"]
        )
    ):
        raise ContractError("evidence maturity transition sequence is invalid")


def staged_final_gate_attempt_journal(
    journal: dict[str, Any], attempt: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "phase": "COMMITTED",
        "logical_gate_query_id": journal["logical_gate_query_id"],
        "attempt": attempt,
        "capacity_before_sha256": journal["capacity_before_sha256"],
        "capacity_after": journal["capacity_after"],
        "capacity_after_sha256": journal["capacity_after_sha256"],
    }


def staged_validate_committed_gate_attempt_journal(
    journal: dict[str, Any], query: dict[str, Any],
    attempt: dict[str, Any], capacity: dict[str, Any] | None = None,
) -> None:
    fields = {
        "schema_version", "phase", "logical_gate_query_id", "attempt",
        "capacity_before_sha256", "capacity_after", "capacity_after_sha256",
    }
    before = json.loads(json.dumps(journal.get("capacity_after", {})))
    try:
        before["retry_budget"]["remaining_attempts"] += 1
    except (KeyError, TypeError):
        raise ContractError("committed Gate attempt capacity shape changed") from None
    expected_reservation = "gate_retry_" + hashlib.sha256(
        f"{query['logical_gate_query_id']}:{attempt['transport_attempt_id']}".encode()
    ).hexdigest()[:24]
    if (
        set(journal) != fields
        or journal.get("schema_version") != 1
        or journal.get("phase") != "COMMITTED"
        or journal.get("logical_gate_query_id") != query.get("logical_gate_query_id")
        or journal.get("attempt") != attempt
        or journal.get("capacity_after_sha256")
        != sha256_json(journal.get("capacity_after"))
        or (capacity is not None and journal.get("capacity_after") != capacity)
        or journal.get("capacity_before_sha256") != sha256_json(before)
        or attempt.get("budget_reservation_id") != expected_reservation
    ):
        raise ContractError("committed Gate attempt journal changed")


def command_record_gate_transport_attempt(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    execution_path = Path(args.execution_receipt).resolve()
    with staged_transaction_lock(plan_dir):
        state = staged_load_state(plan_dir)
        stage_dir = staged_stage_dir(plan_dir, state["active_stage_id"])
        query_path = stage_dir / "gate-query.json"
        query = read_json(query_path)
        if args.logical_gate_query_id != query["logical_gate_query_id"]:
            raise ContractError("transport attempt changed the logical Gate query")
        run = load_evaluator_run(plan_dir, execution_path)
        candidate = read_json(stage_dir / "candidate.json")
        if (
            run.get("purpose") != "candidate"
            or run.get("candidate_sha256") != candidate["candidate_sha256"]
            or run.get("evaluator_sha256") != query["evaluator_sha256"]
        ):
            raise ContractError("Gate transport lacks a bound isolated evaluator execution")
        journal_path = (
            stage_dir / "gate-attempt-journals"
            / f"{args.transport_attempt_id}.json"
        )
        journal = read_json(journal_path) if journal_path.exists() else None
        query_attempt = next((
            item for item in query["transport_attempts"]
            if item["transport_attempt_id"] == args.transport_attempt_id
        ), None)
        capacity_path = staged_root(plan_dir) / "capacity-ledger.json"
        capacity = read_json(capacity_path)
        execution_sha256 = sha256_file(execution_path)
        if journal is not None:
            attempt = journal.get("attempt")
            if (
                not isinstance(attempt, dict)
                or attempt.get("transport_attempt_id") != args.transport_attempt_id
                or attempt.get("execution_receipt_path") != str(execution_path)
                or attempt.get("execution_receipt_sha256") != execution_sha256
                or attempt.get("evaluator_run_id") != run["run_id"]
                or attempt.get("idempotency_key") != query["idempotency_key"]
            ):
                raise ContractError("transport attempt identity collision")
            if journal.get("phase") == "COMMITTED":
                if query_attempt != attempt:
                    raise ContractError("committed Gate attempt query changed")
                staged_canonical_file(
                    journal_path, journal_path, "Gate attempt journal",
                    immutable=True,
                )
                staged_validate_committed_gate_attempt_journal(
                    journal, query, attempt, capacity,
                )
                audit_path = staged_root(plan_dir) / "audit.jsonl"
                audit = [
                    strict_json_loads(line)
                    for line in audit_path.read_text().splitlines() if line.strip()
                ] if audit_path.exists() else []
                staged_exact_audit(
                    audit, "gate_transport_attempt_recorded",
                    {"logical_gate_query_id": query["logical_gate_query_id"], **attempt},
                )
                if query["applied_gate_receipt_id"] is not None:
                    decision = read_json(stage_dir / "decision.json")
                    profile = read_json(
                        staged_root(plan_dir) / "evaluation-profile.json",
                    )
                    staged_validate_terminal_gate_replay(
                        plan_dir, state, stage_dir, query_path, query,
                        profile, run, decision,
                    )
                return {"ok": True, "idempotent": True, **attempt}
            prepared_fields = {
                "schema_version", "phase", "logical_gate_query_id", "attempt",
                "capacity_before_sha256", "capacity_after", "capacity_after_sha256",
            }
            if (
                set(journal) != prepared_fields
                or journal.get("schema_version") != 1
                or journal.get("phase") != "PREPARED"
                or query["applied_gate_receipt_id"] is not None
            ):
                raise ContractError("Gate attempt journal is not recoverable")
            current_sha = sha256_json(capacity)
            if current_sha == journal["capacity_before_sha256"]:
                atomic_write_json(capacity_path, journal["capacity_after"])
                capacity = journal["capacity_after"]
            elif current_sha != journal["capacity_after_sha256"]:
                raise ContractError("Gate attempt capacity cannot be reconciled")
            if query_attempt is None:
                query["transport_attempts"].append(attempt)
                atomic_write_json(query_path, query)
            elif query_attempt != attempt:
                raise ContractError("prepared Gate attempt query changed")
            _staged_ensure_audit_once_locked(
                plan_dir, "gate_transport_attempt_recorded",
                {"transport_attempt_id": attempt["transport_attempt_id"]},
                {"logical_gate_query_id": query["logical_gate_query_id"], **{
                    key: value for key, value in attempt.items()
                    if key != "transport_attempt_id"
                }},
            )
            final_journal = staged_final_gate_attempt_journal(journal, attempt)
            staged_validate_committed_gate_attempt_journal(
                final_journal, query, attempt, capacity,
            )
            atomic_write_json(journal_path, final_journal, immutable=True)
            return {"ok": True, "idempotent": True, "recovered": True, **attempt}
        if query_attempt is not None:
            raise ContractError("Gate attempt journal is missing")
        if query["applied_gate_receipt_id"] is not None:
            raise ContractError("logical Gate decision is already terminal")
        capacity_before_sha256 = sha256_json(capacity)
        retry = capacity["retry_budget"]
        if retry["remaining_attempts"] < 1 or retry["per_attempt_call_limit"] < 1:
            raise ContractError("independent Gate transport retry budget exhausted")
        retry["remaining_attempts"] -= 1
        _staged_consume_stage_budget_locked(
            plan_dir, f"gate-attempt:{args.transport_attempt_id}",
            {"retry_attempts": 1, "evaluation_calls": 1},
        )
        attempt = {
            "transport_attempt_id": staged_require_id(
                args.transport_attempt_id, "transport_attempt_id",
            ),
            "idempotency_key": query["idempotency_key"],
            "budget_reservation_id": "gate_retry_" + hashlib.sha256(
                f"{query['logical_gate_query_id']}:{args.transport_attempt_id}".encode()
            ).hexdigest()[:24],
            "status": "received",
            "execution_receipt_path": str(execution_path),
            "execution_receipt_sha256": execution_sha256,
            "evaluator_run_id": run["run_id"],
        }
        journal = {
            "schema_version": 1, "phase": "PREPARED",
            "logical_gate_query_id": query["logical_gate_query_id"],
            "attempt": attempt,
            "capacity_before_sha256": capacity_before_sha256,
            "capacity_after": capacity,
            "capacity_after_sha256": sha256_json(capacity),
        }
        atomic_write_json(journal_path, journal)
        if getattr(args, "simulate_crash_after_prepare", False):
            raise ContractError("simulated Gate attempt crash after PREPARED")
        query["transport_attempts"].append(attempt)
        atomic_write_json(query_path, query)
        atomic_write_json(capacity_path, capacity)
        _staged_ensure_audit_once_locked(
            plan_dir, "gate_transport_attempt_recorded",
            {"transport_attempt_id": attempt["transport_attempt_id"]},
            {"logical_gate_query_id": query["logical_gate_query_id"], **{
                key: value for key, value in attempt.items()
                if key != "transport_attempt_id"
            }},
        )
        final_journal = staged_final_gate_attempt_journal(journal, attempt)
        staged_validate_committed_gate_attempt_journal(
            final_journal, query, attempt, capacity,
        )
        atomic_write_json(journal_path, final_journal, immutable=True)
        return {"ok": True, **attempt}


def command_apply_logical_gate_decision(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    execution_path = Path(args.execution_receipt).resolve()
    with staged_transaction_lock(plan_dir):
        return _apply_logical_gate_decision_locked(args, plan_dir, execution_path)


def _apply_logical_gate_decision_locked(
    args: argparse.Namespace, plan_dir: Path, execution_path: Path,
) -> dict[str, Any]:
    state = staged_load_state(plan_dir)
    stage_dir = staged_stage_dir(plan_dir, state["active_stage_id"])
    query_path = stage_dir / "gate-query.json"
    query = read_json(query_path)
    if args.logical_gate_query_id != query["logical_gate_query_id"]:
        raise ContractError("Gate receipt logical query mismatch")
    run = load_evaluator_run(plan_dir, execution_path)
    matching_attempt = next(
        (
            item for item in query["transport_attempts"]
            if item.get("execution_receipt_sha256") == sha256_file(execution_path)
            and item.get("status") == "received"
        ),
        None,
    )
    if matching_attempt is None:
        raise ContractError("Gate decision lacks a canonical received evaluator execution")
    profile = read_json(staged_root(plan_dir) / "evaluation-profile.json")
    if run["metric"] != profile["gate_metric"]:
        raise ContractError("Gate execution metric differs from frozen evaluation profile")
    value = require_finite_number(run["value"], "Gate evaluator value")
    threshold = profile["gate_threshold"]
    margin = profile["gate_escalation_margin"]
    if abs(value - threshold) <= margin:
        decision_value = "escalate"
    elif profile["gate_operator"] == "ge":
        decision_value = "accept" if value >= threshold else "reject"
    else:
        decision_value = "accept" if value <= threshold else "reject"
    gate_receipt_id = run["run_id"]
    decision_path = stage_dir / "decision.json"
    journal_path = stage_dir / "gate-decision-journal.json"
    existing_journal = read_json(journal_path) if journal_path.exists() else None
    if existing_journal is not None:
        prior = existing_journal.get("decision")
        if (
            not isinstance(prior, dict)
            or prior.get("gate_receipt_id") != gate_receipt_id
            or prior.get("decision") != decision_value
            or prior.get("logical_gate_query_id")
            != query["logical_gate_query_id"]
        ):
            raise ContractError("Gate decision journal identity changed")
        if decision_path.exists():
            staged_canonical_file(
                decision_path, decision_path, "Gate decision", immutable=True,
            )
            if read_json(decision_path) != prior:
                raise ContractError("Gate decision bytes changed during recovery")
        elif existing_journal.get("phase") == "PREPARED":
            atomic_write_json(decision_path, prior, immutable=True)
        else:
            raise ContractError("committed Gate decision is missing")
        return _finish_gate_decision_transaction(
            plan_dir, state, stage_dir, query_path, query, profile,
            run, prior, recovered=True,
        )
    if query["applied_gate_receipt_id"] is not None or decision_path.exists():
        prior = read_json(decision_path)
        if (
            prior.get("gate_receipt_id") == gate_receipt_id
            and prior.get("decision") == decision_value
        ):
            return _finish_gate_decision_transaction(
                plan_dir, state, stage_dir, query_path, query, profile,
                run, prior, recovered=True,
            )
        raise ContractError("one candidate may receive only one logical Gate decision")
    resulting = (
        query["candidate_sha256"]
        if decision_value == "accept"
        else state["current_incumbent_sha256"]
    )
    decision = {
        "schema_version": 1,
        "stage_cycle_id": state["active_stage_id"],
        "logical_gate_query_id": query["logical_gate_query_id"],
        "gate_receipt_id": gate_receipt_id,
        "decision": decision_value,
        "prior_incumbent_sha256": state["current_incumbent_sha256"],
        "candidate_sha256": query["candidate_sha256"],
        "resulting_incumbent_sha256": resulting,
        "advancement_blocked": decision_value == "escalate",
        "evaluator_execution_receipt_path": str(execution_path),
        "evaluator_execution_receipt_sha256": sha256_file(execution_path),
        "controller_authoritative": True,
        "decided_at": utc_now(),
    }
    maturity_path = stage_dir / "evidence-maturity.json"
    maturity = read_json(maturity_path)
    staged_validate_evidence_maturity(maturity, query["candidate_sha256"])
    if maturity.get("current_maturity") != "full_experiment":
        raise ContractError("Gate decision requires full_experiment evidence maturity")
    atomic_write_json(journal_path, {
        "schema_version": 1, "phase": "PREPARED", "decision": decision,
        "initial_logical_gate_query_sha256": sha256_file(query_path),
    })
    if getattr(args, "simulate_crash_after_prepare", False):
        raise ContractError("simulated Gate decision crash after PREPARED")
    atomic_write_json(decision_path, decision, immutable=True)
    return _finish_gate_decision_transaction(
        plan_dir, state, stage_dir, query_path, query, profile,
        run, decision, recovered=False,
    )


def _finish_gate_decision_transaction(
    plan_dir: Path,
    state: dict[str, Any],
    stage_dir: Path,
    query_path: Path,
    query: dict[str, Any],
    profile: dict[str, Any],
    run: dict[str, Any],
    decision: dict[str, Any],
    *,
    recovered: bool,
) -> dict[str, Any]:
    """Roll a prepared logical-Gate decision forward exactly once."""
    gate_receipt_id = decision["gate_receipt_id"]
    decision_value = decision["decision"]
    resulting = decision["resulting_incumbent_sha256"]
    decision_path = stage_dir / "decision.json"
    journal_path = stage_dir / "gate-decision-journal.json"
    journal = read_json(journal_path)
    if journal.get("phase") == "COMMITTED":
        evidence = staged_validate_terminal_gate_replay(
            plan_dir, state, stage_dir, query_path, query,
            profile, run, decision,
        )
        return {
            "ok": True, "idempotent": True,
            **decision, "evidence": evidence,
        }
    initial_query = json.loads(json.dumps(query))
    initial_query["applied_gate_receipt_id"] = None
    prepared_fields = {
        "schema_version", "phase", "decision",
        "initial_logical_gate_query_sha256",
    }
    if (
        set(journal) != prepared_fields
        or journal.get("schema_version") != 1
        or journal.get("phase") != "PREPARED"
        or journal.get("decision") != decision
        or journal.get("initial_logical_gate_query_sha256")
        != atomic_json_sha256(initial_query)
    ):
        raise ContractError("prepared Gate decision journal changed")
    decision_binding = staged_canonical_file(
        decision_path, decision_path, "Gate decision", immutable=True,
    )
    if read_json(decision_path) != decision:
        raise ContractError("Gate decision bytes changed during recovery")
    maturity_path = stage_dir / "evidence-maturity.json"
    maturity = read_json(maturity_path)
    staged_validate_evidence_maturity(maturity, decision["candidate_sha256"])
    query["applied_gate_receipt_id"] = gate_receipt_id
    atomic_write_json(query_path, query, immutable=True)
    query_binding = staged_canonical_file(
        query_path, query_path, "terminal logical Gate query", immutable=True,
    )
    if decision_value == "accept":
        authority = f"evaluator_run:{run['run_id']}"
        if maturity["current_maturity"] == "full_experiment":
            maturity["transitions"].append({
                "maturity": "gate_accepted",
                "authority": authority,
                "recorded_at": decision["decided_at"],
            })
        elif (
            maturity["current_maturity"] != "gate_accepted"
            or not any(
                item.get("maturity") == "gate_accepted"
                and item.get("authority") == authority
                for item in maturity["transitions"]
            )
        ):
            raise ContractError("Gate maturity transaction cannot be reconciled")
        maturity["current_maturity"] = "gate_accepted"
        atomic_write_json(maturity_path, maturity, immutable=True)
    candidate_path = stage_dir / "candidate.json"
    candidate = read_json(candidate_path)
    candidate_chain = staged_resolve_candidate_chain(
        plan_dir, stage_dir, candidate,
    )
    matching_attempts = [
        item for item in query["transport_attempts"]
        if item.get("execution_receipt_sha256")
        == decision["evaluator_execution_receipt_sha256"]
        and item.get("evaluator_run_id") == run["run_id"]
        and item.get("status") == "received"
    ]
    if len(matching_attempts) != 1:
        raise ContractError("Gate decision lacks one received transport attempt")
    attempt = matching_attempts[0]
    attempt_journal_path = (
        stage_dir / "gate-attempt-journals"
        / f"{attempt['transport_attempt_id']}.json"
    )
    attempt_journal_binding = staged_canonical_file(
        attempt_journal_path, attempt_journal_path,
        "Gate attempt journal", immutable=True,
    )
    staged_validate_committed_gate_attempt_journal(
        read_json(attempt_journal_path), query, attempt,
        read_json(staged_root(plan_dir) / "capacity-ledger.json"),
    )
    final_journal = staged_final_gate_decision_journal(
        stage_dir, query, decision, decision_binding, query_binding,
    )
    journal_binding = {
        "path": str(journal_path),
        "sha256": atomic_json_sha256(final_journal),
    }
    anchors = staged_gate_anchor_values(
        candidate_chain["candidate_record"], query_binding,
        attempt_journal_binding, journal_binding,
    )
    evidence = {
        "schema_version": 1,
        "evidence_id": f"evidence_{state['active_stage_id']}",
        "stage_cycle_id": state["active_stage_id"],
        "decision": decision_value,
        "maturity": maturity["current_maturity"],
        "environment_version": profile["profile_id"],
        "evaluator_version": run["evaluator_sha256"],
        "applicability": ["same frozen evaluation profile and environment"],
        "confidence": "high",
        "validation_status": "validated",
        "provenance_sha256": decision[
            "evaluator_execution_receipt_sha256"
        ],
        "active_for_retrieval": (
            decision_value == "accept"
        ),
        **anchors,
    }
    evidence_receipt_path = stage_dir / "evidence-receipt.json"
    if evidence_receipt_path.exists():
        if read_json(evidence_receipt_path) != evidence:
            raise ContractError("Gate evidence receipt cannot be reconciled")
    else:
        atomic_write_json(evidence_receipt_path, evidence, immutable=True)
    _staged_fault_after_artifact("gate_evidence_receipt")
    ledger_path = staged_root(plan_dir) / "evidence-ledger.jsonl"
    ledger = [
        strict_json_loads(line)
        for line in ledger_path.read_text().splitlines() if line.strip()
    ] if ledger_path.exists() else []
    matches = [
        record for record in ledger
        if record.get("evidence_id") == evidence["evidence_id"]
        and record.get("maturity") == evidence["maturity"]
    ]
    if len(matches) > 1 or matches and matches[0] != evidence:
        raise ContractError("Gate evidence ledger cannot be reconciled")
    if not matches:
        append_jsonl(ledger_path, evidence)
    _staged_fault_after_artifact("gate_evidence_ledger")
    state["current_incumbent_sha256"] = resulting
    state["state"] = "PAUSED" if decision_value == "escalate" else "RECORDED"
    atomic_write_json(staged_state_path(plan_dir), state)
    _staged_fault_after_artifact("gate_decision_state")
    _staged_ensure_audit_once_locked(
        plan_dir, "logical_gate_decision_applied",
        {"gate_receipt_id": gate_receipt_id},
        {
            **{key: value for key, value in decision.items()
               if key != "gate_receipt_id"},
            "evidence_id": evidence["evidence_id"],
        },
    )
    _staged_fault_after_artifact("gate_decision_audit")
    atomic_write_json(journal_path, final_journal, immutable=True)
    return {
        "ok": True, "idempotent": recovered,
        **decision, "evidence": evidence,
    }


def staged_final_gate_decision_journal(
    stage_dir: Path, query: dict[str, Any], decision: dict[str, Any],
    decision_binding: dict[str, str], query_binding: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "phase": "COMMITTED",
        "logical_gate_query_id": query["logical_gate_query_id"],
        "decision": decision,
        "decision_path": str(stage_dir / "decision.json"),
        "decision_sha256": decision_binding["sha256"],
        "logical_gate_query_path": str(stage_dir / "gate-query.json"),
        "logical_gate_query_sha256": query_binding["sha256"],
    }


def staged_gate_anchor_values(
    candidate_binding: dict[str, str], query_binding: dict[str, str],
    attempt_journal_binding: dict[str, str],
    decision_journal_binding: dict[str, str],
) -> dict[str, str]:
    return {
        "candidate_record_path": candidate_binding["path"],
        "candidate_record_sha256": candidate_binding["sha256"],
        "logical_gate_query_path": query_binding["path"],
        "logical_gate_query_sha256": query_binding["sha256"],
        "received_attempt_journal_path": attempt_journal_binding["path"],
        "received_attempt_journal_sha256": attempt_journal_binding["sha256"],
        "gate_decision_journal_path": decision_journal_binding["path"],
        "gate_decision_journal_sha256": decision_journal_binding["sha256"],
    }


def staged_validate_gate_anchor_files(
    stage_dir: Path, receipt: dict[str, Any],
) -> None:
    expected = {
        "candidate_record": stage_dir / "candidate.json",
        "logical_gate_query": stage_dir / "gate-query.json",
        "gate_decision_journal": stage_dir / "gate-decision-journal.json",
    }
    attempt_path = Path(receipt.get("received_attempt_journal_path", ""))
    if attempt_path.parent != stage_dir / "gate-attempt-journals":
        raise ContractError("received Gate attempt journal path changed")
    expected["received_attempt_journal"] = attempt_path
    for prefix, path in expected.items():
        binding = staged_canonical_file(
            Path(receipt.get(f"{prefix}_path", "")), path,
            f"{prefix} anchor", immutable=True,
        )
        if receipt.get(f"{prefix}_sha256") != binding["sha256"]:
            raise ContractError(f"{prefix} anchor hash changed")


def staged_validate_frozen_report_validator(
    plan_dir: Path, envelope: dict[str, Any],
) -> None:
    """Require the CP-01-frozen report validator used for terminal authority."""
    materials = {
        item.get("purpose"): item
        for item in envelope.get("review_material_manifest", [])
        if item.get("purpose") in {
            "stage_report_validator_implementation",
            "stage_report_validator_conformance",
        }
    }
    if set(materials) != {
        "stage_report_validator_implementation",
        "stage_report_validator_conformance",
    }:
        raise ContractError(
            "stage report requires a CP-01-frozen validator and conformance receipt"
        )
    implementation_path = normalize_owned_path(
        plan_dir, str(plan_dir / materials[
            "stage_report_validator_implementation"
        ]["path"]),
    )
    conformance_path = normalize_owned_path(
        plan_dir, str(plan_dir / materials[
            "stage_report_validator_conformance"
        ]["path"]),
    )
    shipped_path = SCRIPT_DIR / "stage_report_validator.py"
    if (
        implementation_path.is_symlink()
        or conformance_path.is_symlink()
        or implementation_path.stat().st_mode & 0o777 != 0o444
        or conformance_path.stat().st_mode & 0o777 != 0o444
        or sha256_file(implementation_path)
        != materials["stage_report_validator_implementation"]["sha256"]
        or sha256_file(conformance_path)
        != materials["stage_report_validator_conformance"]["sha256"]
        or sha256_file(implementation_path) != sha256_file(shipped_path)
        or read_json(conformance_path) != run_stage_report_conformance_suite()
    ):
        raise ContractError(
            "frozen stage report validator differs from Runtime authority"
        )


def command_record_stage_report(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    state = staged_load_state(plan_dir)
    if state["state"] not in {"RECORDED", "PAUSED"}:
        raise ContractError("terminal stage report requires a recorded Gate decision")
    source = Path(args.stage_report).resolve()
    report = read_json(source)
    run_dir = worker_run_dir(plan_dir, args.worker_run_id)
    status_path_value = run_dir / "status.json"
    status = read_json(status_path_value)
    promotion_path = run_dir / "promotion-receipt.json"
    promotion = read_json(promotion_path)
    promotion_journal = read_json(run_dir / "promotion-journal.json")
    if (
        status.get("status") != "COMPLETED"
        or status.get("worker_model") != load_policy(plan_dir)["worker_model"]
        or promotion.get("worker_run_id") != args.worker_run_id
        or promotion_journal.get("phase") != "COMMITTED"
        or promotion_journal.get("receipt_sha256") != sha256_file(promotion_path)
        or not any(
            Path(item["path"]).resolve() == source
            and item["sha256"] == sha256_file(source)
            for item in promotion.get("artifacts", [])
        )
    ):
        raise ContractError("stage report lacks a canonical COMMITTED MiniMax promotion")
    stage_dir = staged_stage_dir(plan_dir, state["active_stage_id"])
    envelope = read_json(stage_dir / "envelope.json")
    staged_validate_frozen_report_validator(plan_dir, envelope)
    candidate = read_json(stage_dir / "candidate.json")
    try:
        validate_stage_report(
            report,
            stage_cycle_id=state["active_stage_id"],
            worker_model=status["worker_model"],
            candidate_sha256=candidate["candidate_sha256"],
            authorized_evidence_refs=envelope["authorized_evidence_refs"],
            expected_validator_receipts=(
                staged_expected_report_validator_receipts(
                    plan_dir, state["active_stage_id"],
                )
            ),
        )
    except StageReportValidationError as exc:
        raise ContractError(f"stage report validator rejected source: {exc}") from exc
    worker = report["worker_identity"]
    if (
        not isinstance(worker, dict)
        or worker.get("model") != status["worker_model"]
        or not worker.get("agent")
        or not worker.get("provider")
    ):
        raise ContractError("terminal stage report must be produced by MiniMax-M3")
    visible_path = staged_root(plan_dir) / "role-visible" / f"{args.worker_run_id}.json"
    if (
        not visible_path.is_file()
        or read_json(visible_path).get("role") != "worker"
        or read_json(visible_path).get("call_id") != args.worker_run_id
    ):
        raise ContractError("stage report lacks its exact worker-visible state")
    visible_sha = sha256_file(visible_path)
    if report.get("role_visible_state_sha256") not in {None, visible_sha}:
        raise ContractError("stage report declares a different worker-visible state")
    if report["candidate_sha256"] != candidate["candidate_sha256"]:
        raise ContractError("stage report candidate mismatch")
    # The Worker cannot know the hash of the role-visible record that is
    # created only after its call completes. Preserve every scientific field
    # byte-for-value and let the Controller add only that provenance binding.
    canonical_report = {**report, "role_visible_state_sha256": visible_sha}
    target = staged_stage_dir(plan_dir, state["active_stage_id"]) / "stage-report.json"
    target_was_absent = not target.exists()
    if target.exists():
        if read_json(target) != canonical_report:
            raise ContractError("canonical stage report changed")
    else:
        atomic_write_json(target, canonical_report, immutable=True)
    if target_was_absent:
        _staged_fault_after_artifact("stage_report")
    _staged_ensure_audit_once_locked(
        plan_dir,
        "minimax_terminal_stage_report_recorded",
        {"stage_report_id": report["stage_report_id"]},
        {
        "stage_id": state["active_stage_id"],
        "stage_report_sha256": sha256_file(target),
        "worker_run_id": args.worker_run_id,
        "worker_status_sha256": sha256_file(status_path_value),
        "promotion_receipt_sha256": sha256_file(promotion_path),
        },
    )
    return {"ok": True, "path": str(target), "sha256": sha256_file(target)}


def command_record_strong_stage_review(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    state = staged_load_state(plan_dir)
    stage_dir = staged_stage_dir(plan_dir, state["active_stage_id"])
    report_path = stage_dir / "stage-report.json"
    report = read_json(report_path)
    request_path_value, request = load_request(plan_dir, args.request_id)
    status = read_json(status_path(plan_dir, args.request_id))
    response_path = request_dir(plan_dir, args.request_id) / "response.json"
    response, _, _ = validate_frontier_response_integrity(
        plan_dir, args.request_id, status, response_path,
    )
    if request.get("checkpoint") != "STAGE-REVIEW" or status.get("state") != "APPLIED":
        raise ContractError("strong stage review requires an APPLIED canonical frontier review")
    transition_path = transition_receipt_path(
        plan_dir, "record_stage_review", args.request_id,
    )
    if not transition_path.is_file():
        raise ContractError("strong stage review controller transition is missing")
    required_paths = {
        "optimization_contract": (
            staged_root(plan_dir) / "contracts"
            / f"{state['contract_version']}.json"
        ),
        "stage_envelope": stage_dir / "envelope.json",
        "stage_report": report_path,
        **staged_terminal_review_evidence_paths(
            plan_dir, state["active_stage_id"],
        ),
    }
    by_role = {item["purpose"]: item for item in request["context_manifest"]}
    continuation_roles = set(by_role) & STAGE_REVIEW_CONTINUATION_EVIDENCE_PROFILE
    accepted_roles = set(required_paths) | continuation_roles
    if (
        continuation_roles not in (
            set(), STAGE_REVIEW_CONTINUATION_EVIDENCE_PROFILE,
        )
        or set(by_role) != accepted_roles
        or any(
        Path(by_role[role]["path"]).resolve() != path.resolve()
        or by_role[role]["sha256"] != sha256_file(path)
        for role, path in required_paths.items()
        )
    ):
        raise ContractError("strong stage review request does not bind canonical stage evidence")
    continuation_review = None
    if continuation_roles:
        continuation_review = {
            role: {
                "path": by_role[role]["path"],
                "sha256": by_role[role]["sha256"],
            }
            for role in sorted(continuation_roles)
        }
        validate_stage_review_continuation_materials(
            plan_dir, state,
            {role: by_role[role] for role in continuation_roles},
        )
    policy = load_policy(plan_dir)
    expected_model = policy["top_level_plan_audit"]["reviewer_model"]
    expected_effort = policy["top_level_plan_audit"]["reasoning_effort"]
    reviewer_profile = status.get("reviewer_profile")
    if (
        not isinstance(reviewer_profile, dict)
        or reviewer_profile.get("model") != expected_model
        or reviewer_profile.get("reasoning_effort") != expected_effort
        or response.get("model_id") != expected_model
        or status.get("model_policy_sha256") != sha256_file(policy_path(plan_dir))
    ):
        raise ContractError("frontier stage review is not strongest-policy bound")
    visible_path = (
        staged_root(plan_dir) / "role-visible" / f"{args.request_id}.json"
    )
    visible = read_json(visible_path)
    if visible.get("role") != "reviewer" or visible.get("call_id") != args.request_id:
        raise ContractError("strong review lacks canonical reviewer-visible state")
    review = {
        "schema_version": 1,
        "review_receipt_id": f"review_{args.request_id}",
        "review_kind": "terminal_stage_report",
        "contract_version": state["contract_version"],
        "stage_cycle_id": state["active_stage_id"],
        "stage_report_sha256": sha256_file(report_path),
        "stage_envelope_sha256": state["active_stage_envelope_sha256"],
        "reviewer": {
            "agent": "codex-frontier",
            "model": expected_model,
            "reasoning_effort": expected_effort,
            "policy_sha256": sha256_file(policy_path(plan_dir)),
        },
        "role_visible_state_sha256": sha256_file(visible_path),
        "recommendation": response["recommendation"],
        "findings_sha256": sha256_json(response["findings"]),
        "continuation_review": continuation_review,
        "frontier_request_id": args.request_id,
        "frontier_request_sha256": sha256_file(request_path_value),
        "frontier_response_sha256": sha256_file(response_path),
        "frontier_transition_sha256": sha256_file(transition_path),
    }
    required = {
        "schema_version", "review_receipt_id", "review_kind",
        "contract_version", "stage_cycle_id", "stage_report_sha256",
        "stage_envelope_sha256", "reviewer", "role_visible_state_sha256",
        "recommendation", "findings_sha256", "continuation_review",
    }
    if not required <= set(review):
        raise ContractError("strong-review receipt is incomplete")
    if (
        review["schema_version"] != 1
        or review["review_kind"] != "terminal_stage_report"
        or review["contract_version"] != state["contract_version"]
        or review["stage_cycle_id"] != state["active_stage_id"]
        or review["stage_report_sha256"] != sha256_file(report_path)
        or review["stage_envelope_sha256"] != state["active_stage_envelope_sha256"]
    ):
        raise ContractError("strong-review receipt binding mismatch")
    if review["recommendation"] not in {"accept", "revise", "block"}:
        raise ContractError("strong-review recommendation is invalid")
    target = stage_dir / "strong-review.json"
    if target.exists() and read_json(target) != review:
        raise ContractError("strong stage review receipt collision")
    if not target.exists():
        atomic_write_json(target, review, immutable=True)
        _staged_fault_after_artifact("strong_review")
    _staged_ensure_audit_once_locked(
        plan_dir,
        "strong_stage_review_recorded",
        {"review_receipt_id": review["review_receipt_id"]},
        {
        "stage_id": state["active_stage_id"],
        "stage_report_id": report["stage_report_id"],
        "recommendation": review["recommendation"],
        "advisory_only": True,
        "controller_authoritative": True,
        },
    )
    return {"ok": True, "path": str(target), "sha256": sha256_file(target)}


def staged_validate_accepted_strong_review(
    plan_dir: Path, stage_id: str, contract_version: str,
) -> dict[str, Any]:
    """Validate the strongest-model review as a hard continuation veto."""
    stage_dir = staged_stage_dir(plan_dir, stage_id)
    report_path = stage_dir / "stage-report.json"
    envelope_path = stage_dir / "envelope.json"
    review_path = stage_dir / "strong-review.json"
    staged_canonical_file(
        review_path, review_path, "strong stage review", immutable=True,
    )
    review = read_json(review_path)
    required_fields = {
        "schema_version", "review_receipt_id", "review_kind",
        "contract_version", "stage_cycle_id", "stage_report_sha256",
        "stage_envelope_sha256", "reviewer", "role_visible_state_sha256",
        "recommendation", "findings_sha256", "frontier_request_id",
        "frontier_request_sha256", "frontier_response_sha256",
        "frontier_transition_sha256",
    }
    policy = load_policy(plan_dir)
    policy_sha = sha256_file(policy_path(plan_dir))
    expected_model = policy["top_level_plan_audit"]["reviewer_model"]
    expected_effort = policy["top_level_plan_audit"]["reasoning_effort"]
    expected_reviewer = {
        "agent": "codex-frontier", "model": expected_model,
        "reasoning_effort": expected_effort, "policy_sha256": policy_sha,
    }
    if (
        set(review) not in (
            required_fields, required_fields | {"continuation_review"},
        )
        or review.get("schema_version") != 1
        or review.get("review_kind") != "terminal_stage_report"
        or review.get("contract_version") != contract_version
        or review.get("stage_cycle_id") != stage_id
        or review.get("stage_report_sha256") != sha256_file(report_path)
        or review.get("stage_envelope_sha256") != sha256_file(envelope_path)
        or review.get("reviewer") != expected_reviewer
        or review.get("recommendation") != "accept"
    ):
        raise ContractError(
            "automatic continuation requires an accepted canonical strongest review"
        )
    request_id = review["frontier_request_id"]
    request_path_value, request = load_request(plan_dir, request_id)
    response_path = request_dir(plan_dir, request_id) / "response.json"
    status = read_json(status_path(plan_dir, request_id))
    response, _, _ = validate_frontier_response_integrity(
        plan_dir, request_id, status, response_path,
    )
    transition_path = transition_receipt_path(
        plan_dir, "record_stage_review", request_id,
    )
    visible_path = staged_root(plan_dir) / "role-visible" / f"{request_id}.json"
    expected_paths = {
        "optimization_contract": (
            staged_root(plan_dir) / "contracts" / f"{contract_version}.json"
        ),
        "stage_envelope": envelope_path,
        "stage_report": report_path,
        **staged_terminal_review_evidence_paths(plan_dir, stage_id),
    }
    by_role = {item["purpose"]: item for item in request["context_manifest"]}
    continuation_roles = set(by_role) & STAGE_REVIEW_CONTINUATION_EVIDENCE_PROFILE
    expected_roles = set(expected_paths) | continuation_roles
    expected_continuation = (
        {
            role: {
                "path": by_role[role]["path"],
                "sha256": by_role[role]["sha256"],
            }
            for role in sorted(continuation_roles)
        }
        if continuation_roles else None
    )
    reviewer_profile = status.get("reviewer_profile")
    if (
        request.get("checkpoint") != "STAGE-REVIEW"
        or request.get("decision_required") != "record_stage_review"
        or continuation_roles not in (
            set(), STAGE_REVIEW_CONTINUATION_EVIDENCE_PROFILE,
        )
        or set(by_role) != expected_roles
        or any(
            Path(by_role[role]["path"]).resolve() != path.resolve()
            or by_role[role]["sha256"] != sha256_file(path)
            for role, path in expected_paths.items()
        )
        or status.get("state") != "APPLIED"
        or reviewer_profile != {
            "kind": "terminal_stage_report_review",
            "model": expected_model,
            "reasoning_effort": expected_effort,
        }
        or status.get("model_policy_sha256") != policy_sha
        or response.get("model_id") != expected_model
        or response.get("recommendation") != "accept"
        or review.get("continuation_review") != expected_continuation
        or review.get("findings_sha256") != sha256_json(response["findings"])
        or review.get("frontier_request_sha256") != sha256_file(request_path_value)
        or review.get("frontier_response_sha256") != sha256_file(response_path)
        or not transition_path.is_file()
        or review.get("frontier_transition_sha256") != sha256_file(transition_path)
        or not visible_path.is_file()
        or review.get("role_visible_state_sha256") != sha256_file(visible_path)
    ):
        raise ContractError("accepted strongest review authority binding changed")
    return review


def staged_canonical_file(
    path: Path, canonical: Path, label: str, *, immutable: bool = False,
) -> dict[str, Any]:
    if (
        path != canonical
        or path.is_symlink()
        or not path.is_file()
        or (immutable and path.stat().st_mode & 0o777 != 0o444)
    ):
        raise ContractError(f"canonical {label} path or mode changed")
    return {"path": str(path), "sha256": sha256_file(path)}


def staged_exact_audit(
    audit: list[dict[str, Any]], event: str, payload: dict[str, Any],
) -> dict[str, Any]:
    metadata = {"schema_version", "audit_revision", "event", "recorded_at"}
    matches = [
        record for record in audit
        if set(record) == metadata | set(payload)
        and record.get("schema_version") == 1
        and record.get("event") == event
        and all(record.get(key) == value for key, value in payload.items())
    ]
    if len(matches) != 1:
        raise ContractError(f"compile evidence lacks one exact {event} audit")
    return matches[0]


def staged_resolve_candidate_chain(
    plan_dir: Path, stage_dir: Path, candidate: dict[str, Any],
) -> dict[str, Any]:
    candidate_path = stage_dir / "candidate.json"
    candidate_binding = staged_canonical_file(
        candidate_path, candidate_path, "candidate record", immutable=True,
    )
    if (
        set(candidate) != STAGED_CANDIDATE_FIELDS
        or candidate.get("schema_version") != 1
        or candidate.get("stage_cycle_id") != stage_dir.name
        or candidate.get("maturity") != "full_experiment"
    ):
        raise ContractError("canonical candidate record changed")
    frozen_path = stage_dir / "candidate-artifact"
    frozen_binding = staged_canonical_file(
        Path(candidate["candidate_path"]), frozen_path,
        "frozen candidate", immutable=True,
    )
    if frozen_binding["sha256"] != candidate["candidate_sha256"]:
        raise ContractError("frozen candidate bytes changed")
    promotion_path = Path(candidate["promotion_receipt_path"])
    promotion = read_json(promotion_path)
    run_id = promotion.get("worker_run_id", "")
    run_dir = worker_run_dir(plan_dir, run_id)
    promotion_binding = staged_canonical_file(
        promotion_path, run_dir / "promotion-receipt.json",
        "candidate promotion receipt", immutable=True,
    )
    status_path = run_dir / "status.json"
    journal_path = run_dir / "promotion-journal.json"
    status_binding = staged_canonical_file(
        status_path, status_path, "candidate worker status", immutable=True,
    )
    journal_binding = staged_canonical_file(
        journal_path, journal_path, "candidate promotion journal",
        immutable=True,
    )
    status = read_json(status_path)
    journal = read_json(journal_path)
    validate_committed_promotion_journal(
        journal, status, run_dir, promotion_binding["sha256"],
        promotion.get("artifacts", []),
    )
    contract_path = Path(status.get("contract_path", ""))
    result_path = Path(status.get("result_path", ""))
    contract_binding = staged_canonical_file(
        contract_path, contract_path, "candidate worker contract",
    )
    result_binding = staged_canonical_file(
        result_path, result_path, "candidate worker result",
    )
    policy_path = plan_dir / "state" / "model_policy.json"
    artifacts = [
        item for item in promotion.get("artifacts", [])
        if item.get("artifact_id") == "candidate"
        and item.get("sha256") == candidate["candidate_sha256"]
    ]
    promoted_source_binding = None
    if len(artifacts) == 1:
        promoted_source = Path(artifacts[0].get("path", ""))
        promoted_source_binding = staged_canonical_file(
            promoted_source, promoted_source, "promoted candidate source",
        )
    if (
        candidate["promotion_receipt_sha256"] != promotion_binding["sha256"]
        or candidate["completed_worker_status_path"] != str(status_path)
        or candidate["completed_worker_status_sha256"] != status_binding["sha256"]
        or candidate["promotion_journal_path"] != str(journal_path)
        or candidate["promotion_journal_sha256"] != journal_binding["sha256"]
        or candidate["development_evidence_refs"] != [f"promotion:{run_id}"]
        or status.get("run_id") != run_id
        or status.get("status") != "COMPLETED"
        or status.get("worker_model") != load_policy(plan_dir)["worker_model"]
        or status.get("contract_sha256") != contract_binding["sha256"]
        or status.get("result_sha256") != result_binding["sha256"]
        or status.get("model_policy_sha256") != sha256_file(policy_path)
        or promotion.get("plan_id") != plan_identity(plan_dir)
        or promotion.get("contract_sha256") != status.get("contract_sha256")
        or promotion.get("result_sha256") != status.get("result_sha256")
        or len(artifacts) != 1
        or promoted_source_binding["sha256"] != candidate["candidate_sha256"]
        or journal.get("phase") != "COMMITTED"
        or journal.get("worker_run_id") != run_id
        or journal.get("receipt_sha256") != promotion_binding["sha256"]
    ):
        raise ContractError("canonical candidate promotion chain changed")
    return {
        "candidate_record": candidate_binding,
        "frozen_candidate": frozen_binding,
        "worker_status": status_binding,
        "worker_contract": contract_binding,
        "worker_result": result_binding,
        "promotion_receipt": promotion_binding,
        "promotion_journal": journal_binding,
        "promoted_candidate_source": promoted_source_binding,
        "worker_run_id": run_id,
        "frozen_at": candidate["frozen_at"],
    }


def staged_resolve_gate_chain(
    plan_dir: Path,
    stage_dir: Path,
    evidence_id: str,
    candidate: dict[str, Any],
    decision: dict[str, Any],
    contract: dict[str, Any],
    audit: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    decision_path = stage_dir / "decision.json"
    decision_binding = staged_canonical_file(
        decision_path, decision_path, "Gate decision", immutable=True,
    )
    decision_fields = {
        "schema_version", "stage_cycle_id", "logical_gate_query_id",
        "gate_receipt_id", "decision", "prior_incumbent_sha256",
        "candidate_sha256", "resulting_incumbent_sha256",
        "advancement_blocked", "evaluator_execution_receipt_path",
        "evaluator_execution_receipt_sha256", "controller_authoritative",
        "decided_at",
    }
    if (
        set(decision) != decision_fields
        or decision.get("schema_version") != 1
        or decision.get("controller_authoritative") is not True
        or decision.get("stage_cycle_id") != stage_dir.name
        or decision.get("candidate_sha256") != candidate["candidate_sha256"]
    ):
        raise ContractError("canonical Gate decision changed")
    execution_path = Path(decision["evaluator_execution_receipt_path"])
    run = load_evaluator_run(plan_dir, execution_path)
    if (
        sha256_file(execution_path)
        != decision["evaluator_execution_receipt_sha256"]
        or run.get("run_id") != decision["gate_receipt_id"]
        or run.get("purpose") != "candidate"
        or run.get("candidate_path") != candidate["candidate_path"]
        or run.get("candidate_sha256") != candidate["candidate_sha256"]
        or run.get("evaluator_sha256")
        != contract["acceptance_evaluator_sha256"]
    ):
        raise ContractError("canonical evaluator execution lineage changed")
    query_path = stage_dir / "gate-query.json"
    query_binding = staged_canonical_file(
        query_path, query_path, "logical Gate query", immutable=True,
    )
    query = read_json(query_path)
    query_fields = {
        "schema_version", "logical_gate_query_id", "stage_cycle_id",
        "candidate_sha256", "evaluator_sha256", "idempotency_key",
        "transport_attempts", "applied_gate_receipt_id",
    }
    if (
        set(query) != query_fields
        or query.get("schema_version") != 1
        or query.get("logical_gate_query_id")
        != decision["logical_gate_query_id"]
        or query.get("stage_cycle_id") != stage_dir.name
        or query.get("candidate_sha256") != candidate["candidate_sha256"]
        or query.get("evaluator_sha256")
        != contract["acceptance_evaluator_sha256"]
        or query.get("applied_gate_receipt_id") != run["run_id"]
        or not isinstance(query.get("transport_attempts"), list)
    ):
        raise ContractError("canonical logical Gate query changed")
    attempts = [
        item for item in query["transport_attempts"]
        if item.get("status") == "received"
        and item.get("execution_receipt_path") == str(execution_path)
        and item.get("execution_receipt_sha256")
        == decision["evaluator_execution_receipt_sha256"]
        and item.get("evaluator_run_id") == run["run_id"]
        and item.get("idempotency_key") == query["idempotency_key"]
    ]
    if len(attempts) != 1:
        raise ContractError("Gate evidence lacks one canonical received attempt")
    attempt = attempts[0]
    attempt_fields = {
        "transport_attempt_id", "idempotency_key", "budget_reservation_id",
        "status", "execution_receipt_path", "execution_receipt_sha256",
        "evaluator_run_id",
    }
    if set(attempt) != attempt_fields:
        raise ContractError("canonical Gate transport attempt changed")
    attempt_journal_path = (
        stage_dir / "gate-attempt-journals"
        / f"{attempt['transport_attempt_id']}.json"
    )
    attempt_journal_binding = staged_canonical_file(
        attempt_journal_path, attempt_journal_path, "Gate attempt journal",
        immutable=True,
    )
    attempt_journal = read_json(attempt_journal_path)
    staged_validate_committed_gate_attempt_journal(
        attempt_journal, query, attempt,
    )
    decision_journal_path = stage_dir / "gate-decision-journal.json"
    decision_journal_binding = staged_canonical_file(
        decision_journal_path, decision_journal_path,
        "Gate decision journal", immutable=True,
    )
    decision_journal = read_json(decision_journal_path)
    expected_decision_journal = staged_final_gate_decision_journal(
        stage_dir, query, decision, decision_binding, query_binding,
    )
    if decision_journal != expected_decision_journal:
        raise ContractError("canonical Gate decision journal changed")
    attempt_audit = staged_exact_audit(
        audit, "gate_transport_attempt_recorded",
        {"logical_gate_query_id": query["logical_gate_query_id"], **attempt},
    )
    terminal_audit = staged_exact_audit(
        audit, "logical_gate_decision_applied",
        {**decision, "evidence_id": evidence_id},
    )
    execution = {
        "receipt": {"path": str(execution_path), "sha256": sha256_file(execution_path)},
        "run_id": run["run_id"], "plan_id": run["plan_id"],
        "evaluator": {"path": run["evaluator_path"], "sha256": run["evaluator_sha256"]},
        "evidence": {"path": run["evidence_path"], "sha256": run["evidence_sha256"]},
        "candidate": {"path": run["candidate_path"], "sha256": run["candidate_sha256"]},
    }
    gate = {
        "query": query_binding,
        "attempt_journal": attempt_journal_binding,
        "attempt_audit_revision": attempt_audit["audit_revision"],
        "attempt_audit_sha256": sha256_json(attempt_audit),
        "decision": decision_binding,
        "decision_journal": decision_journal_binding,
        "terminal_audit_revision": terminal_audit["audit_revision"],
        "terminal_audit_sha256": sha256_json(terminal_audit),
    }
    return gate, execution, run


def staged_validate_terminal_gate_replay(
    plan_dir: Path, state: dict[str, Any], stage_dir: Path,
    query_path: Path, query: dict[str, Any], profile: dict[str, Any],
    run: dict[str, Any], decision: dict[str, Any],
) -> dict[str, Any]:
    """Validate an already terminal Gate transaction without repairing it."""
    root = staged_root(plan_dir)
    audit_path = root / "audit.jsonl"
    audit = [
        strict_json_loads(line)
        for line in audit_path.read_text().splitlines() if line.strip()
    ] if audit_path.exists() else []
    revisions = [record.get("audit_revision") for record in audit]
    if (
        revisions != list(range(1, len(revisions) + 1))
        or state.get("audit_revision") != len(revisions)
    ):
        raise ContractError("terminal Gate audit projection changed")
    candidate = read_json(stage_dir / "candidate.json")
    candidate_chain = staged_resolve_candidate_chain(
        plan_dir, stage_dir, candidate,
    )
    contract = read_json(
        root / "contracts" / f"{state['contract_version']}.json",
    )
    evidence_id = f"evidence_{stage_dir.name}"
    gate_chain, _, resolved_run = staged_resolve_gate_chain(
        plan_dir, stage_dir, evidence_id, candidate, decision,
        contract, audit,
    )
    if resolved_run != run:
        raise ContractError("terminal Gate evaluator execution changed")
    anchors = staged_gate_anchor_values(
        candidate_chain["candidate_record"], gate_chain["query"],
        gate_chain["attempt_journal"], gate_chain["decision_journal"],
    )
    maturity_path = stage_dir / "evidence-maturity.json"
    maturity = read_json(maturity_path)
    staged_validate_evidence_maturity(maturity, decision["candidate_sha256"])
    gate_maturity = (
        "gate_accepted" if decision["decision"] == "accept"
        else "full_experiment"
    )
    if (
        query.get("applied_gate_receipt_id") != decision["gate_receipt_id"]
        or query_path.stat().st_mode & 0o777 != 0o444
        or state.get("current_incumbent_sha256")
        != decision["resulting_incumbent_sha256"]
        or state.get("state")
        != ("PAUSED" if decision["decision"] == "escalate" else "RECORDED")
        or (decision["decision"] == "accept"
            and maturity["current_maturity"] not in {"gate_accepted", "released"})
        or (decision["decision"] != "accept"
            and maturity["current_maturity"] != "full_experiment")
    ):
        raise ContractError("terminal Gate state projection changed")
    evidence = {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "stage_cycle_id": stage_dir.name,
        "decision": decision["decision"],
        "maturity": gate_maturity,
        "environment_version": profile["profile_id"],
        "evaluator_version": run["evaluator_sha256"],
        "applicability": ["same frozen evaluation profile and environment"],
        "confidence": "high",
        "validation_status": "validated",
        "provenance_sha256": decision[
            "evaluator_execution_receipt_sha256"
        ],
        "active_for_retrieval": decision["decision"] == "accept",
        **anchors,
    }
    receipt_path = stage_dir / "evidence-receipt.json"
    staged_canonical_file(
        receipt_path, receipt_path, "terminal Gate evidence receipt",
        immutable=True,
    )
    receipt = read_json(receipt_path)
    if set(receipt) != STAGED_EVIDENCE_RECEIPT_FIELDS or receipt != evidence:
        raise ContractError("terminal Gate evidence receipt changed")
    ledger_path = root / "evidence-ledger.jsonl"
    ledger = [
        strict_json_loads(line)
        for line in ledger_path.read_text().splitlines() if line.strip()
    ] if ledger_path.exists() else []
    if len([record for record in ledger if record == evidence]) != 1:
        raise ContractError("terminal Gate evidence ledger changed")
    return evidence


def staged_resolve_compile_evidence(
    plan_dir: Path,
    envelope: dict[str, Any],
    cli_evidence: list[str],
    authorization: dict[str, Any],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolve caller IDs to current canonical Controller evidence."""
    explicit_ids = list(dict.fromkeys(cli_evidence))
    if explicit_ids != envelope["authorized_evidence_refs"]:
        raise ContractError(
            "compile evidence IDs must exactly match envelope order"
        )
    root = staged_root(plan_dir)
    ledger_path = root / "evidence-ledger.jsonl"
    audit_path = root / "audit.jsonl"
    ledger = [
        strict_json_loads(line)
        for line in ledger_path.read_text().splitlines() if line.strip()
    ] if ledger_path.exists() else []
    audit = [
        strict_json_loads(line)
        for line in audit_path.read_text().splitlines() if line.strip()
    ] if audit_path.exists() else []
    profile = read_json(root / "evaluation-profile.json")
    contract = read_json(
        root / "contracts" / f"{state['contract_version']}.json"
    )
    external_identity = profile["external_suite_identity_sha256"]
    bindings: list[dict[str, Any]] = []
    for evidence_id in explicit_ids:
        receipt_candidates = [
            path for path in sorted((root / "stages").glob("*/evidence-receipt.json"))
            if read_json(path).get("evidence_id") == evidence_id
        ] + [
            path for path in sorted(
                (root / "stages").glob("*/released-evidence-receipt.json")
            )
            if read_json(path).get("evidence_id") == evidence_id
        ]
        stage_ids = {path.parent.name for path in receipt_candidates}
        if not receipt_candidates:
            raise ContractError(
                f"compile evidence is not canonical: {evidence_id}"
            )
        if len(stage_ids) != 1:
            raise ContractError(
                f"compile evidence is duplicated across stages: {evidence_id}"
            )
        stage_id = next(iter(stage_ids))
        stage_dir = staged_stage_dir(plan_dir, stage_id)
        candidate_path = stage_dir / "candidate.json"
        decision_path = stage_dir / "decision.json"
        candidate = read_json(candidate_path)
        decision = read_json(decision_path)
        maturity_path = stage_dir / "evidence-maturity.json"
        maturity_binding = staged_canonical_file(
            maturity_path, maturity_path, "evidence maturity", immutable=True,
        )
        maturity = read_json(maturity_path)
        staged_validate_evidence_maturity(
            maturity, candidate["candidate_sha256"],
        )
        if (
            evidence_id != f"evidence_{stage_id}"
            or maturity.get("evidence_id") != evidence_id
            or decision.get("stage_cycle_id") != stage_id
            or decision.get("candidate_sha256")
            != candidate["candidate_sha256"]
        ):
            raise ContractError("compile evidence stage binding changed")
        source_envelope_path = stage_dir / "envelope.json"
        source_envelope_binding = staged_canonical_file(
            source_envelope_path, source_envelope_path,
            "source stage envelope", immutable=True,
        )
        source_envelope = read_json(source_envelope_path)
        if source_envelope.get("contract_version") != state["contract_version"]:
            raise ContractError("compile evidence contract lineage is stale")
        candidate_chain = staged_resolve_candidate_chain(
            plan_dir, stage_dir, candidate,
        )
        gate_chain, execution_chain, execution = staged_resolve_gate_chain(
            plan_dir, stage_dir, evidence_id, candidate, decision,
            contract, audit,
        )
        expected_gate_anchors = staged_gate_anchor_values(
            candidate_chain["candidate_record"], gate_chain["query"],
            gate_chain["attempt_journal"], gate_chain["decision_journal"],
        )
        expected_initial = [
            {"maturity": name, "authority": authority,
             "recorded_at": candidate["frozen_at"]}
            for name, authority in (
                ("idea", "candidate_pool"),
                ("screened", f"promotion:{candidate_chain['worker_run_id']}"),
                ("full_experiment", f"promotion:{candidate_chain['worker_run_id']}"),
            )
        ]
        if maturity["transitions"][:3] != expected_initial:
            raise ContractError("canonical candidate maturity authority changed")
        expected_transitions = list(expected_initial)
        if decision["decision"] == "accept":
            expected_transitions.append({
                "maturity": "gate_accepted",
                "authority": f"evaluator_run:{execution['run_id']}",
                "recorded_at": decision["decided_at"],
            })
        current_maturity = maturity["current_maturity"]
        release_chain: dict[str, Any] | None = None
        if current_maturity == "released":
            receipt_path = stage_dir / "released-evidence-receipt.json"
            classification = "released_reusable"
            expected_applicability = ["released under current contract lineage"]
            released_transition = maturity["transitions"][-1]
            authority = released_transition.get("authority", "")
            record_id = authority.removeprefix("human:")
            release_authorization_path = (
                plan_dir / "state" / "human_actions" / "applied"
                / f"{record_id}.json"
            )
            release_authorization_binding = staged_canonical_file(
                release_authorization_path, release_authorization_path,
                "release authorization receipt", immutable=True,
            )
            release_authorization = validate_applied_action_receipt(
                plan_dir, release_authorization_path, "release_evidence",
            )
            cp04_request_id = released_transition.get("cp04_request_id")
            cp04 = check_transition_receipt(
                plan_dir, plan_identity(plan_dir), "start_writing",
                cp04_request_id,
            )
            cp04_path = transition_receipt_path(
                plan_dir, "start_writing", cp04["request_id"],
            )
            cp04_binding = staged_canonical_file(
                cp04_path, cp04_path, "CP-04 transition receipt",
                immutable=True,
            )
            expected_transitions.append({
                "maturity": "released", "authority": f"human:{record_id}",
                "cp04_request_id": cp04["request_id"],
                "recorded_at": release_authorization["applied_at"],
            })
            if (
                release_authorization.get("details", {}).get("evidence_id")
                != evidence_id
                or release_authorization.get("details", {}).get("binding_sha256")
                != candidate["candidate_sha256"]
            ):
                raise ContractError("canonical evidence release authority changed")
        else:
            receipt_path = stage_dir / "evidence-receipt.json"
            classification = (
                "gate_accepted_reusable"
                if decision.get("decision") == "accept"
                else "negative_context"
            )
            expected_applicability = [
                "same frozen evaluation profile and environment"
            ]
        if maturity["transitions"] != expected_transitions:
            raise ContractError("canonical evidence maturity history changed")
        if receipt_path not in receipt_candidates:
            raise ContractError("compile evidence maturity receipt is missing")
        receipt_binding = staged_canonical_file(
            receipt_path, receipt_path, "evidence receipt", immutable=True,
        )
        receipt = read_json(receipt_path)
        if (
            set(receipt) != STAGED_EVIDENCE_RECEIPT_FIELDS
            or receipt.get("schema_version") != 1
            or receipt.get("stage_cycle_id") != stage_id
            or receipt.get("evidence_id") != evidence_id
            or receipt.get("decision") != decision.get("decision")
            or receipt.get("maturity") != current_maturity
            or receipt.get("validation_status") != "validated"
            or receipt.get("applicability") != expected_applicability
            or receipt.get("environment_version") != profile["profile_id"]
            or receipt.get("evaluator_version")
            != contract["acceptance_evaluator_sha256"]
            or receipt.get("confidence") != "high"
            or any(
                receipt.get(key) != value
                for key, value in expected_gate_anchors.items()
            )
        ):
            raise ContractError("compile evidence receipt is ineligible or stale")
        if classification in {"gate_accepted_reusable", "released_reusable"}:
            if (
                decision.get("decision") != "accept"
                or current_maturity not in {"gate_accepted", "released"}
                or receipt.get("active_for_retrieval") is not True
            ):
                raise ContractError("compile reusable evidence authority changed")
        else:
            authorization_details = authorization.get("details", {})
            if (
                decision.get("decision") not in {"reject", "escalate"}
                or current_maturity != "full_experiment"
                or receipt.get("active_for_retrieval") is not False
                or authorization_details.get("evidence_id") != evidence_id
                or authorization_details.get("reason") != "negative_context"
            ):
                raise ContractError(
                    "negative evidence requires explicit owner context authority"
                )
        expected_provenance = (
            sha256_file(maturity_path)
            if current_maturity == "released"
            else decision["evaluator_execution_receipt_sha256"]
        )
        if receipt.get("provenance_sha256") != expected_provenance:
            raise ContractError("compile evidence provenance changed")
        ledger_matches = [record for record in ledger if record == receipt]
        if len(ledger_matches) != 1:
            raise ContractError("compile evidence lacks one exact ledger record")
        gate_receipt_path = stage_dir / "evidence-receipt.json"
        gate_receipt_binding = staged_canonical_file(
            gate_receipt_path, gate_receipt_path,
            "terminal Gate evidence receipt", immutable=True,
        )
        gate_receipt = read_json(gate_receipt_path)
        gate_ledger_matches = [record for record in ledger if record == gate_receipt]
        if (
            len(gate_ledger_matches) != 1
            or set(gate_receipt) != STAGED_EVIDENCE_RECEIPT_FIELDS
            or gate_receipt.get("schema_version") != 1
            or gate_receipt.get("evidence_id") != evidence_id
            or gate_receipt.get("stage_cycle_id") != stage_id
            or gate_receipt.get("decision") != decision["decision"]
            or gate_receipt.get("maturity")
            != ("gate_accepted" if decision["decision"] == "accept" else "full_experiment")
            or gate_receipt.get("provenance_sha256")
            != decision["evaluator_execution_receipt_sha256"]
            or gate_receipt.get("validation_status") != "validated"
            or gate_receipt.get("environment_version") != profile["profile_id"]
            or gate_receipt.get("evaluator_version")
            != contract["acceptance_evaluator_sha256"]
            or gate_receipt.get("applicability")
            != ["same frozen evaluation profile and environment"]
            or gate_receipt.get("confidence") != "high"
            or gate_receipt.get("active_for_retrieval")
            is not (decision["decision"] == "accept")
            or any(
                gate_receipt.get(key) != value
                for key, value in expected_gate_anchors.items()
            )
        ):
            raise ContractError("canonical terminal Gate ledger changed")
        audit_binding = {
            "revision": gate_chain["terminal_audit_revision"],
            "sha256": gate_chain["terminal_audit_sha256"],
        }
        if current_maturity == "released":
            release_audit = staged_exact_audit(
                audit, "staged_evidence_released", {
                    "evidence_id": evidence_id, "stage_id": stage_id,
                    "released_evidence_receipt_sha256": receipt_binding["sha256"],
                },
            )
            release_chain = {
                "authorization": {
                    **release_authorization_binding,
                },
                "cp04_receipt": cp04_binding,
                "receipt": receipt_binding,
                "ledger_record_sha256": sha256_json(ledger_matches[0]),
                "audit_revision": release_audit["audit_revision"],
                "audit_sha256": sha256_json(release_audit),
            }
        if external_identity in canonical_json({
            "receipt": receipt, "gate_receipt": gate_receipt,
            "ledger": ledger_matches[0], "gate_chain": gate_chain,
        }).decode("utf-8"):
            raise ContractError("external transfer evidence is not compilable")
        bindings.append({
            "evidence_id": evidence_id,
            "stage_id": stage_id,
            "receipt_path": receipt_binding["path"],
            "receipt_sha256": receipt_binding["sha256"],
            "ledger_record_sha256": sha256_json(ledger_matches[0]),
            "audit_revision": audit_binding["revision"],
            "audit_record_sha256": audit_binding["sha256"],
            "classification": classification,
            "decision": decision["decision"],
            "maturity": current_maturity,
            "validation_status": receipt["validation_status"],
            "applicability": receipt["applicability"],
            "environment_version": receipt["environment_version"],
            "evaluator_version": receipt["evaluator_version"],
            "contract_version": state["contract_version"],
            "contract_sha256": state["contract_sha256"],
            "evaluation_profile_sha256": state["evaluation_profile_sha256"],
            "provenance_sha256": expected_provenance,
            "source_envelope": source_envelope_binding,
            "candidate_chain": candidate_chain,
            "execution_chain": execution_chain,
            "gate_chain": gate_chain,
            "maturity_record": maturity_binding,
            "terminal_gate_receipt": gate_receipt_binding,
            "terminal_gate_ledger_record_sha256": sha256_json(
                gate_ledger_matches[0]
            ),
            "release_chain": release_chain,
        })
    return bindings


def staged_compile_operation_identity(
    args: argparse.Namespace,
    incoming_source: Path,
    evidence_bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Freeze every authority-bearing compile input with ordered-set semantics."""
    ordered_evidence = list(dict.fromkeys(args.authorized_evidence))
    figure_raw = getattr(args, "figure_requirements", None)
    figure_path = Path(figure_raw).resolve() if figure_raw else None
    figure_identity = {
        "present": figure_path is not None,
        "path": str(figure_path) if figure_path is not None else None,
        "sha256": sha256_file(figure_path) if figure_path is not None else None,
    }
    authorization_path = Path(args.authorization_receipt).resolve()
    return {
        "schema_version": 1,
        "stage_envelope_path": str(incoming_source),
        "stage_envelope_sha256": sha256_file(incoming_source),
        "authorization_receipt_path": str(authorization_path),
        "authorization_receipt_sha256": sha256_file(authorization_path),
        # First-occurrence order is semantic; duplicates are not authority.
        "authorized_evidence_ordered_set": ordered_evidence,
        "canonical_evidence_bindings": evidence_bindings,
        "figure_requirements": figure_identity,
    }


def command_compile_next_stage(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    incoming_source = Path(args.stage_envelope).resolve()
    incoming_envelope = read_json(incoming_source)
    state = staged_load_state(plan_dir)
    source_cycle_id = staged_require_id(
        incoming_envelope.get("source_cycle_id"), "source_cycle_id",
    )
    source_decision = read_json(
        staged_stage_dir(plan_dir, source_cycle_id) / "decision.json"
    )
    strong_review = staged_validate_accepted_strong_review(
        plan_dir, source_cycle_id, state["contract_version"],
    )
    staged_validate_envelope(
        incoming_envelope,
        state["contract_version"],
        source_decision["resulting_incumbent_sha256"],
        first=False, plan_dir=plan_dir, require_manifest=True,
    )
    staged_validate_profile_envelope_compatibility(
        read_json(staged_root(plan_dir) / "evaluation-profile.json"),
        incoming_envelope,
    )
    authorization_path = Path(args.authorization_receipt).resolve()
    if authorization_path.parent == (
        staged_root(plan_dir) / "continuation-receipts"
    ).resolve():
        reviewed_envelope = (
            strong_review.get("continuation_review", {}).get(
                "next_stage_envelope"
            )
            if isinstance(strong_review.get("continuation_review"), dict)
            else None
        )
        if (
            not isinstance(reviewed_envelope, dict)
            or Path(reviewed_envelope.get("path", "")).resolve()
            != incoming_source
            or reviewed_envelope.get("sha256") != sha256_file(incoming_source)
        ):
            raise ContractError(
                "automatic next-stage compilation requires the exact accepted "
                "continuation draft"
            )
        authorization = validate_staged_continuation_receipt_source(
            plan_dir, authorization_path, incoming_source,
        )
        authorization_action = "derived_continuation"
    else:
        authorization = validate_applied_action_receipt(
            plan_dir, authorization_path, "reauthorize_stage",
        )
        authorization_action = "reauthorize_stage"
    authorization_checks = {
        "contract_version": state["contract_version"],
        "contract_sha256": state["contract_sha256"],
        "stage_id": incoming_envelope["stage_id"],
        "stage_envelope_sha256": sha256_file(incoming_source),
    }
    if any(
        authorization.get("details", {}).get(key) != value
        for key, value in authorization_checks.items()
    ):
        raise ContractError("next-stage owner authorization binding mismatch")
    evidence_bindings = staged_resolve_compile_evidence(
        plan_dir,
        incoming_envelope,
        args.authorized_evidence,
        authorization,
        state,
    )
    operation_identity = staged_compile_operation_identity(
        args, incoming_source, evidence_bindings,
    )
    operation_identity_sha256 = sha256_json(operation_identity)
    journal_dir = staged_root(plan_dir) / "compile-journals"
    prepared = [
        path for path in sorted(journal_dir.glob("*.json"))
        if read_json(path).get("phase") == "PREPARED"
    ]
    if prepared:
        if len(prepared) != 1:
            raise ContractError("multiple prepared next-stage compilations")
        journal = read_json(prepared[0])
        if (
            journal.get("operation_identity") != operation_identity
            or journal.get("operation_identity_sha256")
            != operation_identity_sha256
        ):
            raise ContractError("prepared next-stage compilation identity conflict")
        return _finish_next_stage_compile_locked(
            plan_dir, prepared[0], journal,
        )
    prior_cycle = incoming_envelope.get("source_cycle_id")
    prior_journal_path = journal_dir / f"{prior_cycle}.json"
    if (
        isinstance(prior_cycle, str)
        and prior_journal_path.exists()
        and read_json(prior_journal_path).get("phase") == "COMMITTED"
    ):
        raise ContractError(
            "next-stage compilation identity conflict: source cycle is committed"
        )
    if state["state"] not in {"RECORDED", "PAUSED"}:
        raise ContractError("next-stage compilation requires a terminal cycle")
    if state["next_stage_compiled"]:
        raise ContractError("at most one next-stage envelope may be compiled")
    stage_dir = staged_stage_dir(plan_dir, state["active_stage_id"])
    decision = read_json(stage_dir / "decision.json")
    report_path = stage_dir / "stage-report.json"
    review_path = stage_dir / "strong-review.json"
    report = read_json(report_path)
    review = read_json(review_path)
    if (
        review["stage_report_sha256"] != sha256_file(report_path)
        or review["stage_cycle_id"] != state["active_stage_id"]
    ):
        raise ContractError("fresh report-bound strong review is required")
    source = incoming_source
    envelope = incoming_envelope
    staged_validate_envelope(
        envelope, state["contract_version"],
        decision["resulting_incumbent_sha256"], first=False,
        plan_dir=plan_dir, require_manifest=True,
    )
    if envelope["source_cycle_id"] != state["active_stage_id"]:
        raise ContractError("next stage must cite the preceding terminal cycle")
    if set(envelope["authorized_evidence_refs"]) - set(args.authorized_evidence):
        raise ContractError("next stage includes unauthorized evidence")
    if envelope["stage_kind"] == "figure_production":
        if not args.figure_requirements:
            raise ContractError("figure-production stage must freeze exact figure requirements")
        requirements_path = Path(args.figure_requirements).resolve()
        validate_frozen_figure_requirements(
            plan_dir, requirements_path, plan_identity(plan_dir),
        )
        if sha256_file(requirements_path) != envelope["figure_requirements_sha256"]:
            raise ContractError("figure-production inventory binding mismatch")
    else:
        if args.figure_requirements:
            raise ContractError(
                "only figure-production compilation accepts figure requirements"
            )
        requirements_path = None
    prior_stage = state["active_stage_id"]
    target_dir = staged_stage_dir(plan_dir, envelope["stage_id"])
    state_transition = {
        "active_stage_id": envelope["stage_id"],
        "active_stage_envelope_sha256": sha256_file(source),
        "state": "CONTRACTED",
        "next_stage_compiled": False,
        "active_stage_authorization_path": str(authorization_path),
        "active_stage_authorization_sha256": sha256_file(authorization_path),
        "active_stage_authorization_action": authorization_action,
    }
    marker = stage_dir / "next-stage.json"
    marker_value = {
        "schema_version": 1,
        "source_cycle_id": prior_stage,
        "next_stage_id": envelope["stage_id"],
        "next_stage_envelope_sha256": sha256_file(source),
        "stage_report_sha256": sha256_file(report_path),
        "strong_review_sha256": sha256_file(review_path),
        "controller_authoritative": True,
    }
    usage_after = staged_usage_ledger_image(envelope)
    journal = {
        "schema_version": 1, "phase": "PREPARED",
        "source_cycle_id": prior_stage,
        "next_stage_id": envelope["stage_id"],
        "stage_envelope_path": str(source),
        "stage_envelope_sha256": sha256_file(source),
        "authorization_receipt_path": str(authorization_path),
        "authorization_receipt_sha256": sha256_file(authorization_path),
        "operation_identity": operation_identity,
        "operation_identity_sha256": operation_identity_sha256,
        "figure_requirements_path": (
            str(requirements_path) if requirements_path is not None else None
        ),
        "figure_requirements_sha256": (
            sha256_file(requirements_path)
            if requirements_path is not None else None
        ),
        "usage_after": usage_after,
        "usage_after_sha256": sha256_json(usage_after),
        "state_before_sha256": sha256_json(state),
        "source_state": state["state"],
        "state_transition": state_transition,
        "marker_after": marker_value,
        "marker_after_sha256": sha256_json(marker_value),
        "prepared_at": utc_now(),
    }
    journal_path = journal_dir / f"{prior_stage}.json"
    atomic_write_json(journal_path, journal)
    return _finish_next_stage_compile_locked(plan_dir, journal_path, journal)


def _finish_next_stage_compile_locked(
    plan_dir: Path, journal_path: Path, journal: dict[str, Any],
) -> dict[str, Any]:
    if (
        not isinstance(journal.get("operation_identity"), dict)
        or sha256_json(journal["operation_identity"])
        != journal.get("operation_identity_sha256")
    ):
        raise ContractError("prepared next-stage operation identity changed")
    source = Path(journal["stage_envelope_path"])
    authorization_path = Path(journal["authorization_receipt_path"])
    if (
        sha256_file(source) != journal["stage_envelope_sha256"]
        or sha256_file(authorization_path)
        != journal["authorization_receipt_sha256"]
    ):
        raise ContractError("prepared next-stage compilation source changed")
    source_stage_dir = staged_stage_dir(plan_dir, journal["source_cycle_id"])
    target_dir = staged_stage_dir(plan_dir, journal["next_stage_id"])
    requirements_raw = journal.get("figure_requirements_path")
    if requirements_raw is not None:
        requirements_path = Path(requirements_raw)
        if sha256_file(requirements_path) != journal["figure_requirements_sha256"]:
            raise ContractError("prepared figure requirements changed")
        staged_copy_immutable(
            requirements_path, target_dir / "figure-requirements.json",
        )
    staged_copy_immutable(source, target_dir / "envelope.json")
    if os.environ.get("HARNESS_FAULT_AFTER_COMPILE_ENVELOPE") == "1":
        os._exit(87)
    usage_path = target_dir / "usage-ledger.json"
    if usage_path.exists():
        if sha256_json(read_json(usage_path)) != journal["usage_after_sha256"]:
            raise ContractError("prepared next-stage usage image is irreconcilable")
    else:
        atomic_write_json(usage_path, journal["usage_after"])
    marker_path = source_stage_dir / "next-stage.json"
    if marker_path.exists():
        if read_json(marker_path) != journal["marker_after"]:
            raise ContractError("prepared next-stage marker is irreconcilable")
    else:
        atomic_write_json(marker_path, journal["marker_after"], immutable=True)
    state = staged_load_state(plan_dir)
    transition = journal["state_transition"]
    if (
        state["active_stage_id"] == journal["source_cycle_id"]
        and state["state"] == journal["source_state"]
    ):
        state.update(transition)
        atomic_write_json(staged_state_path(plan_dir), state)
    elif any(state.get(key) != value for key, value in transition.items()):
        raise ContractError("prepared next-stage state is irreconcilable")
    audit_path = staged_root(plan_dir) / "audit.jsonl"
    audit_has_compile = audit_path.exists() and any(
        strict_json_loads(line).get("event") == "next_stage_compiled"
        and strict_json_loads(line).get("source_cycle_id")
        == journal["source_cycle_id"]
        and strict_json_loads(line).get("next_stage_id")
        == journal["next_stage_id"]
        for line in audit_path.read_text().splitlines()
        if line.strip()
    )
    if not audit_has_compile:
        _staged_append_audit_locked(
            plan_dir, "next_stage_compiled", journal["marker_after"],
        )
    _staged_reconcile_audit_revision_locked(plan_dir)
    journal.update({"phase": "COMMITTED", "committed_at": utc_now()})
    atomic_write_json(journal_path, journal)
    return {"ok": True, **journal["marker_after"]}


def _staged_advance_fault(phase: str) -> None:
    if os.environ.get("HARNESS_FAULT_AFTER_STAGED_ADVANCE_PHASE") == phase:
        os._exit(89)


def command_advance_staged_research(args: argparse.Namespace) -> dict[str, Any]:
    """Cross one pre-authorized stage boundary and start exactly one Worker."""
    plan_dir = Path(args.plan_dir).resolve()
    capacity = read_json(staged_root(plan_dir) / "capacity-ledger.json")
    staged_validate_capacity(capacity)
    if capacity.get("schema_version") != 2:
        raise ContractError(
            "automatic staged continuation requires separated capacity v2"
        )
    envelope_path = Path(args.stage_envelope).resolve()
    preflight_path = Path(args.preflight_inputs).resolve()
    task_contract_path = Path(args.task_contract).resolve()
    envelope = read_json(envelope_path)
    source_stage_id = staged_require_id(
        envelope.get("source_cycle_id"), "source_cycle_id",
    )
    next_stage_id = staged_require_id(envelope.get("stage_id"), "stage_id")
    identity = {
        "source_stage_id": source_stage_id,
        "next_stage_id": next_stage_id,
        "stage_envelope_path": str(envelope_path),
        "stage_envelope_sha256": sha256_file(envelope_path),
        "preflight_inputs_path": str(preflight_path),
        "preflight_inputs_sha256": sha256_file(preflight_path),
        "task_contract_path": str(task_contract_path),
        "task_contract_sha256": sha256_file(task_contract_path),
        "authorized_evidence": list(args.authorized_evidence),
        "figure_requirements": (
            str(Path(args.figure_requirements).resolve())
            if args.figure_requirements else None
        ),
    }
    journal_path = (
        staged_root(plan_dir) / "advance-journals" / f"{source_stage_id}.json"
    )
    if journal_path.exists():
        journal = read_json(journal_path)
        if journal.get("identity") != identity:
            raise ContractError("staged advance operation identity conflict")
    else:
        state = staged_load_state(plan_dir)
        if state["active_stage_id"] != source_stage_id or state["state"] != "RECORDED":
            raise ContractError("staged advance requires the active terminal source stage")
        source_dir = staged_stage_dir(plan_dir, source_stage_id)
        decision = read_json(source_dir / "decision.json")
        report_path = source_dir / "stage-report.json"
        review_path = source_dir / "strong-review.json"
        review = read_json(review_path)
        strong_review = staged_validate_accepted_strong_review(
            plan_dir, source_stage_id, state["contract_version"],
        )
        reviewed = strong_review.get("continuation_review")
        expected_review_bindings = {
            "next_stage_envelope": {
                "path": str(envelope_path), "sha256": sha256_file(envelope_path),
            },
            "next_stage_preflight_inputs": {
                "path": str(preflight_path), "sha256": sha256_file(preflight_path),
            },
            "next_stage_task_contract": {
                "path": str(task_contract_path),
                "sha256": sha256_file(task_contract_path),
            },
        }
        if reviewed != expected_review_bindings:
            raise ContractError(
                "staged advance inputs are not the exact accepted continuation draft"
            )
        if (
            decision.get("decision") not in STAGED_TERMINAL_DECISIONS
            or not report_path.is_file()
            or review.get("stage_cycle_id") != source_stage_id
            or review.get("stage_report_sha256") != sha256_file(report_path)
        ):
            raise ContractError(
                "staged advance requires terminal decision, report, and strong review"
            )
        continuation_path = staged_derive_continuation_receipt(
            plan_dir, envelope_path,
        )
        journal = {
            "schema_version": 1,
            "phase": "CONTINUATION_AUTHORIZED",
            "identity": identity,
            "identity_sha256": sha256_json(identity),
            "continuation_receipt_path": str(continuation_path),
            "continuation_receipt_sha256": sha256_file(continuation_path),
            "worker_operation_id": "op_" + hashlib.sha256(
                canonical_json(identity)
            ).hexdigest(),
            "prepared_at": utc_now(),
        }
        atomic_write_json(journal_path, journal)
        _staged_advance_fault("continuation")

    phases = {
        "CONTINUATION_AUTHORIZED": 1,
        "COMPILED": 2,
        "PREFLIGHTED": 3,
        "STAGE_AUTHORIZED": 4,
        "WORKER_STARTED": 5,
    }
    if journal.get("phase") not in phases:
        raise ContractError("staged advance journal phase is invalid")
    continuation_path = Path(journal["continuation_receipt_path"])
    if sha256_file(continuation_path) != journal["continuation_receipt_sha256"]:
        raise ContractError("staged advance continuation receipt changed")

    if phases[journal["phase"]] < phases["COMPILED"]:
        current_state = staged_load_state(plan_dir)["state"]
        try:
            require_staged_transition(
                "compile_continuation", current_state, "CONTRACTED",
            )
        except WorkerArtifactLifecycleError as exc:
            raise ContractError(str(exc)) from exc
        compile_result = command_compile_next_stage(argparse.Namespace(
            plan_dir=str(plan_dir),
            stage_envelope=str(envelope_path),
            authorized_evidence=list(args.authorized_evidence),
            figure_requirements=args.figure_requirements,
            authorization_receipt=str(continuation_path),
        ))
        journal.update({"phase": "COMPILED", "compile_result": compile_result})
        atomic_write_json(journal_path, journal)
        _staged_advance_fault("compile")

    if phases[journal["phase"]] < phases["PREFLIGHTED"]:
        preflight_result = command_preflight_staged_research(argparse.Namespace(
            plan_dir=str(plan_dir), preflight_inputs=str(preflight_path),
        ))
        journal.update({"phase": "PREFLIGHTED", "preflight_result": preflight_result})
        atomic_write_json(journal_path, journal)
        _staged_advance_fault("preflight")

    if phases[journal["phase"]] < phases["STAGE_AUTHORIZED"]:
        with staged_transaction_lock(plan_dir):
            state = staged_load_state(plan_dir)
            receipt = validate_staged_continuation_receipt(
                plan_dir, continuation_path,
            )
            if (
                state["active_stage_id"] != next_stage_id
                or state["state"] != "CONTRACTED"
                or receipt["next_stage_id"] != next_stage_id
            ):
                raise ContractError("compiled continuation is not authorizable")
            try:
                require_staged_transition(
                    "authorize_continuation", state["state"], "STAGE_AUTHORIZED",
                )
            except WorkerArtifactLifecycleError as exc:
                raise ContractError(str(exc)) from exc
            staged_require_preflight(plan_dir)
            state["state"] = "STAGE_AUTHORIZED"
            atomic_write_json(staged_state_path(plan_dir), state)
            _staged_ensure_audit_once_locked(
                plan_dir, "continuation_stage_authorized",
                {"continuation_id": receipt["continuation_id"]},
                {
                    "source_stage_id": source_stage_id,
                    "stage_id": next_stage_id,
                    "initial_authorization_record_id": receipt[
                        "initial_authorization_record_id"
                    ],
                },
            )
        journal["phase"] = "STAGE_AUTHORIZED"
        atomic_write_json(journal_path, journal)
        _staged_advance_fault("authorize")

    if phases[journal["phase"]] < phases["WORKER_STARTED"]:
        try:
            require_staged_transition(
                "start_continuation_worker",
                staged_load_state(plan_dir)["state"],
                "DEVELOPING",
            )
        except WorkerArtifactLifecycleError as exc:
            raise ContractError(str(exc)) from exc
        context_capsule, context_capsule_path = make_staged_continuation_capsule(
            plan_dir,
            continuation_path,
            task_contract_path,
            preflight_path,
        )
        prior_capsule = journal.get("context_capsule")
        capsule_binding = {
            "path": str(context_capsule_path),
            "sha256": sha256_file(context_capsule_path),
            "capsule_id": context_capsule["capsule_id"],
            "capsule_sha256": context_capsule["capsule_sha256"],
        }
        if prior_capsule is not None and prior_capsule != capsule_binding:
            raise ContractError("staged continuation capsule binding changed")
        journal["context_capsule"] = capsule_binding
        atomic_write_json(journal_path, journal)
        worker_result = command_dispatch_worker(argparse.Namespace(
            plan_dir=str(plan_dir),
            task_contract=str(task_contract_path),
            claude_bin=args.claude_bin,
            timeout=args.timeout,
            writing_gate_receipt=None,
            context_capsule=str(context_capsule_path),
            operation_id=journal["worker_operation_id"],
        ))
        # The Worker handler has committed its deterministic run and capacity
        # reservation, while the enclosing crossing journal has not.  Replay
        # must observe that exact run rather than dispatch another one.
        _staged_advance_fault("dispatch")
        state = staged_load_state(plan_dir)
        if state["active_stage_id"] != next_stage_id or state["state"] != "DEVELOPING":
            raise ContractError("second-stage Worker did not enter DEVELOPING")
        journal.update({
            "phase": "WORKER_STARTED",
            "worker_run_id": worker_result.get("worker_run_id", worker_result.get("run_id")),
            "worker_result": worker_result,
            "committed_at": utc_now(),
        })
        atomic_write_json(journal_path, journal)
        staged_ensure_audit_once(
            plan_dir, "bounded_stage_crossing_completed",
            {"continuation_id": read_json(continuation_path)["continuation_id"]},
            {
                "source_stage_id": source_stage_id,
                "stage_id": next_stage_id,
                "worker_run_id": worker_result.get(
                    "worker_run_id", worker_result.get("run_id")
                ),
            },
        )

    journal = read_json(journal_path)
    state = staged_load_state(plan_dir)
    return {
        "ok": True,
        "source_stage_id": source_stage_id,
        "stage_id": next_stage_id,
        "state": state["state"],
        "worker_run_id": journal["worker_run_id"],
        "continuation_receipt_path": str(continuation_path),
        "idempotent": journal.get("phase") == "WORKER_STARTED",
    }


def command_record_human_stage_input(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    state = staged_load_state(plan_dir)
    if args.kind == "feedback" and not args.stage_report_id:
        raise ContractError("human feedback must bind a named staged report")
    if args.kind == "feedback":
        report_path = (
            staged_stage_dir(plan_dir, state["active_stage_id"])
            / "stage-report.json"
        )
        report = read_json(report_path)
        if report.get("stage_report_id") != args.stage_report_id:
            raise ContractError("human feedback stage report ID is unresolved")
    stable_record = {
        "schema_version": 1,
        "input_id": staged_require_id(args.input_id, "input_id"),
        "kind": args.kind,
        "stage_id": state["active_stage_id"],
        "stage_report_id": args.stage_report_id,
        "content_sha256": staged_require_sha256(args.content_sha256, "content_sha256"),
        "status": "candidate_pool",
        "authorization_created": False,
    }
    path = staged_root(plan_dir) / "human-inputs.jsonl"
    records = [
        strict_json_loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ] if path.exists() else []
    prior = [item for item in records if item.get("input_id") == args.input_id]
    if len(prior) > 1:
        raise ContractError("duplicate human stage input identity")
    if prior:
        record = prior[0]
        if {
            key: record.get(key) for key in stable_record
        } != stable_record:
            raise ContractError("human stage input identity collision")
    else:
        record = {**stable_record, "recorded_at": utc_now()}
        append_jsonl(path, record)
        _staged_fault_after_artifact("human_input")
    _staged_ensure_audit_once_locked(
        plan_dir,
        "human_stage_input_recorded",
        {"input_id": record["input_id"]},
        {
            **{key: value for key, value in record.items() if key != "input_id"},
            "silence_is_approval": False,
        },
    )
    return {"ok": True, **record}


def command_release_staged_evidence(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    with staged_transaction_lock(plan_dir):
        state = staged_load_state(plan_dir)
        stage_dir = staged_stage_dir(plan_dir, state["active_stage_id"])
        maturity_path = stage_dir / "evidence-maturity.json"
        maturity = read_json(maturity_path)
        staged_validate_evidence_maturity(
            maturity, read_json(stage_dir / "candidate.json")["candidate_sha256"],
        )
        receipt = validate_applied_action_receipt(
            plan_dir, Path(args.authorization_receipt).resolve(),
            "release_evidence",
        )
        if (
            receipt.get("details", {}).get("evidence_id") != maturity["evidence_id"]
            or receipt.get("details", {}).get("binding_sha256")
            != maturity["candidate_sha256"]
        ):
            raise ContractError("release authorization evidence binding mismatch")
        cp04 = check_transition_receipt(
            plan_dir, plan_identity(plan_dir), "start_writing",
            args.cp04_request_id,
        )
        release_transition = {
            "maturity": "released",
            "authority": f"human:{receipt['record_id']}",
            "cp04_request_id": cp04["request_id"],
        }
        if maturity.get("current_maturity") == "gate_accepted":
            maturity["transitions"].append({
                **release_transition, "recorded_at": receipt["applied_at"],
            })
            maturity["current_maturity"] = "released"
            atomic_write_json(maturity_path, maturity, immutable=True)
            _staged_fault_after_artifact("evidence_release")
        elif maturity.get("current_maturity") == "released":
            last = maturity["transitions"][-1]
            if any(last.get(key) != value for key, value in release_transition.items()):
                raise ContractError("released evidence operation identity conflict")
        else:
            raise ContractError("released evidence must advance from gate_accepted")
        gate_receipt_path = stage_dir / "evidence-receipt.json"
        staged_canonical_file(
            gate_receipt_path, gate_receipt_path,
            "terminal Gate evidence receipt", immutable=True,
        )
        gate_receipt = read_json(gate_receipt_path)
        if set(gate_receipt) != STAGED_EVIDENCE_RECEIPT_FIELDS:
            raise ContractError("terminal Gate evidence receipt shape changed")
        staged_validate_gate_anchor_files(stage_dir, gate_receipt)
        entry = {
            "schema_version": 1,
            "evidence_id": maturity["evidence_id"],
            "stage_cycle_id": state["active_stage_id"],
            "decision": "accept",
            "maturity": "released",
            "environment_version": read_json(
                staged_root(plan_dir) / "evaluation-profile.json"
            )["profile_id"],
            "evaluator_version": read_json(
                staged_root(plan_dir) / "contracts"
                / f"{state['contract_version']}.json"
            )["acceptance_evaluator_sha256"],
            "applicability": ["released under current contract lineage"],
            "confidence": "high", "validation_status": "validated",
            "provenance_sha256": sha256_file(maturity_path),
            "active_for_retrieval": True,
            **{key: gate_receipt[key] for key in STAGED_GATE_ANCHOR_FIELDS},
        }
        released_receipt_path = stage_dir / "released-evidence-receipt.json"
        if released_receipt_path.exists():
            if read_json(released_receipt_path) != entry:
                raise ContractError("released evidence receipt collision")
        else:
            atomic_write_json(released_receipt_path, entry, immutable=True)
        ledger_path = staged_root(plan_dir) / "evidence-ledger.jsonl"
        ledger_records = [
            strict_json_loads(line)
            for line in ledger_path.read_text().splitlines()
            if line.strip()
        ] if ledger_path.exists() else []
        matching = [
            item for item in ledger_records
            if item.get("evidence_id") == entry["evidence_id"]
            and item.get("maturity") == "released"
        ]
        if len(matching) > 1 or matching and matching[0] != entry:
            raise ContractError("released evidence ledger identity conflict")
        if not matching:
            append_jsonl(ledger_path, entry)
        _staged_ensure_audit_once_locked(
            plan_dir,
            "staged_evidence_released",
            {"evidence_id": entry["evidence_id"]},
            {
            "stage_id": state["active_stage_id"],
            "released_evidence_receipt_sha256": sha256_file(
                released_receipt_path
            ),
            },
        )
        return {"ok": True, "evidence": entry}


def command_retrieve_staged_evidence(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    state = staged_load_state(plan_dir)
    path = staged_root(plan_dir) / "evidence-ledger.jsonl"
    records = [
        strict_json_loads(line) for line in path.read_text().splitlines()
        if line.strip()
    ] if path.exists() else []
    latest: dict[str, dict[str, Any]] = {}
    for receipt_path in sorted(
        (staged_root(plan_dir) / "stages").glob("*/evidence-receipt.json")
    ):
        record = read_json(receipt_path)
        stage_dir = receipt_path.parent
        decision = read_json(stage_dir / "decision.json")
        if (
            set(record) != STAGED_EVIDENCE_RECEIPT_FIELDS
            or
            record.get("stage_cycle_id") != stage_dir.name
            or record.get("evidence_id") != f"evidence_{stage_dir.name}"
            or record.get("provenance_sha256")
            != decision.get("evaluator_execution_receipt_sha256")
        ):
            raise ContractError("canonical Gate evidence receipt binding changed")
        staged_validate_gate_anchor_files(stage_dir, record)
        latest[record["evidence_id"]] = record
    for receipt_path in sorted(
        (staged_root(plan_dir) / "stages").glob(
            "*/released-evidence-receipt.json"
        )
    ):
        record = read_json(receipt_path)
        stage_dir = receipt_path.parent
        maturity_path = stage_dir / "evidence-maturity.json"
        maturity = read_json(maturity_path)
        staged_validate_evidence_maturity(
            maturity, read_json(stage_dir / "candidate.json")["candidate_sha256"],
        )
        if (
            set(record) != STAGED_EVIDENCE_RECEIPT_FIELDS
            or
            maturity["current_maturity"] != "released"
            or record.get("stage_cycle_id") != stage_dir.name
            or record.get("evidence_id") != maturity["evidence_id"]
            or record.get("provenance_sha256") != sha256_file(maturity_path)
        ):
            raise ContractError("canonical released evidence receipt binding changed")
        staged_validate_gate_anchor_files(stage_dir, record)
        latest[record["evidence_id"]] = record
    active = [
        record for record in latest.values()
        if record.get("active_for_retrieval") is True
        and record.get("validation_status") == "validated"
        and record.get("maturity") in {"gate_accepted", "released"}
        and record.get("applicability")
    ]
    external_identity = read_json(
        staged_root(plan_dir) / "evaluation-profile.json",
    )["external_suite_identity_sha256"]
    rendered = canonical_json(active).decode()
    if external_identity in rendered:
        raise ContractError("external transfer suite leaked into reusable evidence")
    return {
        "ok": True, "contract_version": state["contract_version"],
        "active_evidence": active, "audit_record_count": len(records),
    }


def replay_role_visible_state(
    plan_dir: Path, call_id: str,
) -> dict[str, Any]:
    path = staged_root(plan_dir) / "role-visible" / f"{call_id}.json"
    visible = read_json(path)
    validate_schema(visible, read_json(ROLE_VISIBLE_STATE_SCHEMA))
    events = visible["context_events"]
    if visible["context_event_manifest_sha256"] != sha256_json(events):
        raise ContractError("role-visible context event manifest changed")
    for previous, current in zip(events, events[1:]):
        if previous["output_manifest_sha256"] != current["input_manifest_sha256"]:
            raise ContractError("role-visible transformations do not replay in order")
    if (
        not events
        or events[-1]["output_manifest_sha256"]
        != visible["visible_message_manifest_sha256"]
    ):
        raise ContractError("role-visible replay final manifest mismatch")
    if set(visible["source_artifact_sha256"]) != set(
        visible["source_artifact_refs"]
    ):
        raise ContractError("role-visible source hash manifest is incomplete")
    for raw in visible["source_artifact_refs"]:
        source = (plan_dir / raw).resolve()
        try:
            source.relative_to(plan_dir)
        except ValueError as exc:
            raise ContractError("role-visible source reference escapes the plan") from exc
        if not source.is_file():
            raise ContractError("role-visible source reference no longer resolves")
        if sha256_file(source) != visible["source_artifact_sha256"][raw]:
            raise ContractError("role-visible source artifact changed after rendering")
    manifest = visible["canonical_call_manifest"]
    if manifest.get("call_kind") == "worker":
        run_id = manifest.get("run_id")
        if run_id != call_id:
            raise ContractError("role-visible worker call identity changed")
        status = read_json(worker_run_dir(plan_dir, run_id) / "status.json")
        expected_manifest = {
            "call_kind": "worker", "run_id": run_id,
            "contract_sha256": status["contract_sha256"],
            "result_sha256": status["result_sha256"],
            "model_policy_sha256": status["model_policy_sha256"],
            "context_capsule_sha256": status.get("context_capsule_sha256"),
        }
    elif manifest.get("call_kind") == "frontier":
        request_path_value, request = load_request(
            plan_dir, call_id, verify_live_manifest=True,
        )
        current_status = read_json(status_path(plan_dir, call_id))
        response_path = request_dir(plan_dir, call_id) / "response.json"
        validate_frontier_response_integrity(
            plan_dir, call_id, current_status, response_path,
        )
        expected_manifest = {
            "call_kind": "frontier", "request_id": call_id,
            "request_sha256": sha256_file(request_path_value),
            "response_sha256": sha256_file(response_path),
            "context_manifest_sha256": sha256_json(request["context_manifest"]),
            "model_policy_sha256": current_status["model_policy_sha256"],
        }
    else:
        raise ContractError("role-visible canonical call kind is invalid")
    if (
        manifest != expected_manifest
        or sha256_json(manifest) != visible["visible_message_manifest_sha256"]
    ):
        raise ContractError("role-visible canonical call manifest does not replay")
    if visible["audit_revision"] > staged_load_state(plan_dir)["audit_revision"]:
        raise ContractError("role-visible audit revision is unresolved")
    return visible


def command_replay_role_visible_state(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    visible = replay_role_visible_state(plan_dir, args.call_id)
    return {
        "ok": True, "call_id": args.call_id,
        "visible_message_manifest_sha256": visible[
            "visible_message_manifest_sha256"
        ],
        "audit_revision": visible["audit_revision"],
        "claim_scope": "state-faithful role-visible reconstruction only",
    }


def command_classify_staged_failure(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    visible = replay_role_visible_state(plan_dir, args.call_id)
    evidence_path = Path(args.evidence_artifact).resolve()
    final_path = Path(args.final_output).resolve()
    for path in (evidence_path, final_path):
        try:
            path.relative_to(plan_dir)
        except ValueError as exc:
            raise ContractError("failure-classification artifact escapes the plan") from exc
        if not path.is_file():
            raise ContractError("failure-classification artifact is unresolved")
    evidence_sha = sha256_file(evidence_path)
    relative = str(evidence_path.relative_to(plan_dir))
    audit_path = staged_root(plan_dir) / "audit.jsonl"
    audit_text = audit_path.read_text() if audit_path.exists() else ""
    audit_present = evidence_sha in audit_text or relative in audit_text
    visible_present = relative in visible["source_artifact_refs"]
    final_bytes = final_path.read_bytes()
    final_present = (
        sha256_file(final_path) == evidence_sha
        or evidence_sha.encode() in final_bytes
        or evidence_path.read_bytes() in final_bytes
    )
    if audit_present and not visible_present:
        classification = "context_rendering"
    elif visible_present and not final_present:
        classification = "finalization_or_constraint"
    else:
        classification = "indeterminate"
    receipt = {
        "schema_version": 1, "call_id": args.call_id,
        "classification": classification,
        "audit_evidence_present": audit_present,
        "role_visible_evidence_present": visible_present,
        "final_output_evidence_present": final_present,
        "evidence_sha256": evidence_sha,
        "bounded_attribution": True,
        "complete_causal_attribution": False,
    }
    append_jsonl(
        staged_root(plan_dir) / "failure-classifications.jsonl", receipt,
    )
    return {"ok": True, **receipt}


def command_pause_staged_research(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    with staged_transaction_lock(plan_dir):
        state = staged_load_state(plan_dir)
        ledger_path = (
            staged_stage_dir(plan_dir, state["active_stage_id"])
            / "usage-ledger.json"
        )
        ledger = read_json(ledger_path)
        if ledger.get("stop_reason") is None:
            ledger["stop_reason"] = args.reason
            ledger["stopped_at"] = utc_now()
            atomic_write_json(ledger_path, ledger)
            _staged_fault_after_artifact("pause")
        elif ledger.get("stop_reason") != args.reason:
            raise ContractError("stage pause operation identity conflict")
        state["state"] = "PAUSED"
        atomic_write_json(staged_state_path(plan_dir), state)
        _staged_ensure_audit_once_locked(
            plan_dir,
            "stage_stop_condition_applied",
            {"stage_id": state["active_stage_id"], "reason": args.reason},
            {"controller_authoritative": True},
        )
        return {"ok": True, "stage_id": state["active_stage_id"], "reason": args.reason}


def command_reauthorize_staged_research(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    with staged_transaction_lock(plan_dir):
        state = staged_load_state(plan_dir)
        receipt_path = Path(args.authorization_receipt).resolve()
        receipt = validate_applied_action_receipt(
            plan_dir, receipt_path, "reauthorize_stage",
        )
        expected = {
            "contract_version": state["contract_version"],
            "contract_sha256": state["contract_sha256"],
            "stage_id": state["active_stage_id"],
            "stage_envelope_sha256": state["active_stage_envelope_sha256"],
        }
        if any(receipt.get("details", {}).get(k) != v for k, v in expected.items()):
            raise ContractError("stage reauthorization binding mismatch")
        controller_path = plan_dir / "state" / "controller.json"
        if controller_path.exists() and read_json(controller_path).get("status") == "stopped":
            if not args.resume_receipt:
                raise ContractError("human-stopped stage also requires canonical resume")
            validate_applied_action_receipt(
                plan_dir, Path(args.resume_receipt).resolve(), "resume",
            )
        ledger_path = (
            staged_stage_dir(plan_dir, state["active_stage_id"])
            / "usage-ledger.json"
        )
        ledger = read_json(ledger_path)
        prior_record_id = ledger.get("reauthorization_record_id")
        if prior_record_id not in {None, receipt["record_id"]}:
            raise ContractError("stage reauthorization operation identity conflict")
        if prior_record_id is None:
            ledger["stop_reason"] = None
            ledger["reauthorization_record_id"] = receipt["record_id"]
            ledger["reauthorized_at"] = utc_now()
            atomic_write_json(ledger_path, ledger)
            _staged_fault_after_artifact("reauthorize")
        state["state"] = "STAGE_AUTHORIZED"
        state["active_stage_authorization_path"] = str(receipt_path)
        state["active_stage_authorization_sha256"] = sha256_file(receipt_path)
        state["active_stage_authorization_action"] = "reauthorize_stage"
        atomic_write_json(staged_state_path(plan_dir), state)
        _staged_ensure_audit_once_locked(
            plan_dir,
            "stage_reauthorized",
            {"record_id": receipt["record_id"]},
            {"stage_id": state["active_stage_id"]},
        )
        return {"ok": True, "stage_id": state["active_stage_id"]}


def command_record_evaluator_rebaseline(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    state = staged_load_state(plan_dir)
    contract_path = Path(args.contract).resolve()
    contract = read_json(contract_path)
    staged_validate_contract(contract)
    if contract["contract_version"] == state["contract_version"]:
        raise ContractError("evaluator/adoption changes require a new contract version")
    authorization_path = Path(args.authorization_receipt).resolve()
    authorization = validate_applied_action_receipt(
        plan_dir, authorization_path, "authorize_rebaseline",
    )
    if (
        authorization.get("record_id") != contract["authorization_receipt_id"]
        or authorization.get("details", {}).get("contract_version")
        != contract["contract_version"]
        or authorization.get("details", {}).get("contract_sha256")
        != sha256_file(contract_path)
    ):
        raise ContractError("rebaseline owner authorization contract binding mismatch")
    run_path = Path(args.execution_receipt).resolve()
    run = load_evaluator_run(plan_dir, run_path)
    if (
        run.get("purpose") != "calibration"
        or run.get("evaluator_sha256") != contract["acceptance_evaluator_sha256"]
    ):
        raise ContractError("rebaseline requires canonical calibration of new evaluator")
    stable_receipt = {
        "schema_version": 1,
        "rebaseline_id": f"rebaseline_{contract['contract_version']}",
        "prior_contract_version": state["contract_version"],
        "contract_version": contract["contract_version"],
        "contract_sha256": sha256_file(contract_path),
        "evaluator_sha256": run["evaluator_sha256"],
        "adoption_policy_sha256": contract["adoption_policy_sha256"],
        "execution_receipt_path": str(run_path),
        "execution_receipt_sha256": sha256_file(run_path),
        "authorization_receipt_path": str(authorization_path),
        "authorization_receipt_sha256": sha256_file(authorization_path),
    }
    target = (
        staged_root(plan_dir) / "rebaseline-receipts"
        / f"{stable_receipt['rebaseline_id']}.json"
    )
    if target.exists():
        receipt = read_json(target)
        if {
            key: receipt.get(key) for key in stable_receipt
        } != stable_receipt:
            raise ContractError("rebaseline receipt collision")
    else:
        receipt = {**stable_receipt, "recorded_at": utc_now()}
        atomic_write_json(target, receipt, immutable=True)
        _staged_fault_after_artifact("rebaseline")
    _staged_ensure_audit_once_locked(
        plan_dir,
        "evaluator_rebaseline_recorded",
        {"rebaseline_id": receipt["rebaseline_id"]},
        {
            "prior_contract_version": receipt["prior_contract_version"],
            "contract_version": receipt["contract_version"],
            "contract_sha256": receipt["contract_sha256"],
            "evaluator_sha256": receipt["evaluator_sha256"],
            "authorization_receipt_sha256": receipt[
                "authorization_receipt_sha256"
            ],
        },
    )
    return {"ok": True, "receipt_path": str(target), **receipt}


def command_amend_staged_contract(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    with staged_transaction_lock(plan_dir):
        incoming_contract_path = Path(args.contract).resolve()
        incoming_contract = read_json(incoming_contract_path)
        staged_validate_contract(incoming_contract)
        amendment_journal_path = (
            staged_root(plan_dir) / "amendment-journals"
            / f"{incoming_contract['contract_version']}.json"
        )
        if amendment_journal_path.exists():
            amendment_journal = read_json(amendment_journal_path)
            source_checks = {
                "contract_sha256": sha256_file(incoming_contract_path),
                "evaluation_profile_sha256": sha256_file(
                    Path(args.evaluation_profile).resolve()
                ),
                "stage_envelope_sha256": sha256_file(
                    Path(args.stage_envelope).resolve()
                ),
                "rebaseline_receipt_sha256": sha256_file(
                    Path(args.rebaseline_receipt).resolve()
                ),
            }
            if (
                amendment_journal.get("contract_version")
                != incoming_contract["contract_version"]
                or any(
                    amendment_journal.get(key) != value
                    for key, value in source_checks.items()
                )
            ):
                raise ContractError("contract amendment journal identity conflict")
            raw_state = read_json(staged_state_path(plan_dir))
            if (
                raw_state.get("contract_version")
                != incoming_contract["contract_version"]
            ):
                evaluation_target = (
                    staged_root(plan_dir) / "evaluation-profile.json"
                )
                current_evaluation = read_json(evaluation_target)
                current_sha = sha256_json(current_evaluation)
                if current_sha == amendment_journal[
                    "evaluation_after_sha256"
                ]:
                    atomic_write_json(
                        evaluation_target,
                        amendment_journal["evaluation_before"],
                    )
                elif current_sha != amendment_journal[
                    "evaluation_before_sha256"
                ]:
                    raise ContractError(
                        "prepared contract amendment evaluation is "
                        "irreconcilable"
                    )
        state = staged_load_state(plan_dir)
        contract_path = Path(args.contract).resolve()
        contract = read_json(contract_path)
        staged_validate_contract(contract)
        rebaseline_path = Path(args.rebaseline_receipt).resolve()
        rebaseline = read_json(rebaseline_path)
        canonical_rebaseline = (
            staged_root(plan_dir) / "rebaseline-receipts"
            / f"rebaseline_{contract['contract_version']}.json"
        )
        if (
            rebaseline_path != canonical_rebaseline
            or rebaseline.get("contract_sha256") != sha256_file(contract_path)
        ):
            raise ContractError("contract amendment lacks canonical rebaseline")
        if state["contract_version"] == contract["contract_version"]:
            root = staged_root(plan_dir)
            evaluation_path = Path(args.evaluation_profile).resolve()
            envelope_path = Path(args.stage_envelope).resolve()
            envelope = read_json(envelope_path)
            expected = {
                "contract_sha256": sha256_file(contract_path),
                "evaluation_profile_sha256": sha256_file(evaluation_path),
                "active_stage_id": envelope["stage_id"],
                "active_stage_envelope_sha256": sha256_file(envelope_path),
            }
            if (
                any(state.get(key) != value for key, value in expected.items())
                or sha256_file(
                    root / "contracts" / f"{contract['contract_version']}.json"
                ) != expected["contract_sha256"]
            ):
                raise ContractError("committed contract amendment identity conflict")
            _staged_ensure_audit_once_locked(
                plan_dir,
                "contract_lineage_amended",
                {"contract_version": contract["contract_version"]},
                {
                    "prior_contract_version": rebaseline[
                        "prior_contract_version"
                    ],
                    "rebaseline_receipt_sha256": sha256_file(rebaseline_path),
                },
            )
            if amendment_journal_path.exists():
                amendment_journal = read_json(amendment_journal_path)
                amendment_journal["phase"] = "COMMITTED"
                amendment_journal["committed_at"] = amendment_journal.get(
                    "committed_at", utc_now(),
                )
                atomic_write_json(
                    amendment_journal_path, amendment_journal,
                )
            return {
                "ok": True, "idempotent": True,
                "contract_version": contract["contract_version"],
            }
        if state["state"] not in {"RECORDED", "PAUSED"}:
            raise ContractError("contract amendment requires a terminal recorded stage")
        old_contract = read_json(
            staged_root(plan_dir) / "contracts"
            / f"{state['contract_version']}.json"
        )
        changed_policy = any(
            old_contract[field] != contract[field]
            for field in ("acceptance_evaluator_sha256", "adoption_policy_sha256")
        )
        if changed_policy and not canonical_rebaseline.is_file():
            raise ContractError("evaluator/adoption drift requires rebaseline")
        evaluation_path = Path(args.evaluation_profile).resolve()
        evaluation = read_json(evaluation_path)
        staged_validate_evaluation_profile(evaluation)
        envelope_path = Path(args.stage_envelope).resolve()
        envelope = read_json(envelope_path)
        staged_validate_envelope(
            envelope, contract["contract_version"],
            state["current_incumbent_sha256"], first=False,
            plan_dir=plan_dir, require_manifest=True,
        )
        staged_validate_profile_envelope_compatibility(evaluation, envelope)
        authorization_path = Path(
            rebaseline["authorization_receipt_path"]
        ).resolve()
        authorization = validate_applied_action_receipt(
            plan_dir, authorization_path, "authorize_rebaseline",
        )
        if authorization["record_id"] != contract["authorization_receipt_id"]:
            raise ContractError("new contract owner authorization ID mismatch")
        root = staged_root(plan_dir)
        if amendment_journal_path.exists():
            amendment_journal = read_json(amendment_journal_path)
        else:
            evaluation_target = root / "evaluation-profile.json"
            evaluation_before = read_json(evaluation_target)
            amendment_journal = {
                "schema_version": 1,
                "phase": "PREPARED",
                "contract_version": contract["contract_version"],
                "prior_contract_version": state["contract_version"],
                "contract_sha256": sha256_file(contract_path),
                "evaluation_profile_sha256": sha256_file(evaluation_path),
                "stage_envelope_sha256": sha256_file(envelope_path),
                "rebaseline_receipt_sha256": sha256_file(rebaseline_path),
                "evaluation_before": evaluation_before,
                "evaluation_before_sha256": sha256_json(evaluation_before),
                "evaluation_after_sha256": sha256_json(evaluation),
                "prepared_at": utc_now(),
            }
            atomic_write_json(amendment_journal_path, amendment_journal)
        contract_target = (
            root / "contracts" / f"{contract['contract_version']}.json"
        )
        contract_was_absent = not contract_target.exists()
        staged_copy_immutable(
            contract_path, contract_target,
        )
        if contract_was_absent:
            _staged_fault_after_artifact("amend")
        atomic_write_json(root / "evaluation-profile.json", evaluation)
        if os.environ.get("HARNESS_FAULT_AFTER_AMEND_EVALUATION") == "1":
            os._exit(90)
        target_dir = staged_stage_dir(plan_dir, envelope["stage_id"])
        staged_copy_immutable(envelope_path, target_dir / "envelope.json")
        usage_path = target_dir / "usage-ledger.json"
        if usage_path.exists():
            usage = read_json(usage_path)
            expected_usage = staged_usage_ledger_image(envelope)
            expected_usage["started_at"] = usage.get("started_at")
            if usage != expected_usage:
                raise ContractError("stage usage ledger initialization collision")
        else:
            staged_initialize_usage_ledger(plan_dir, envelope)
        state.update({
            "contract_version": contract["contract_version"],
            "contract_sha256": sha256_file(
                root / "contracts" / f"{contract['contract_version']}.json"
            ),
            "evaluation_profile_sha256": sha256_file(
                root / "evaluation-profile.json"
            ),
            "active_stage_id": envelope["stage_id"],
            "active_stage_envelope_sha256": sha256_file(
                target_dir / "envelope.json"
            ),
            "owner_authorization_path": str(authorization_path),
            "owner_authorization_sha256": sha256_file(authorization_path),
            "owner_authorization_action": "authorize_rebaseline",
            "active_stage_authorization_path": str(authorization_path),
            "active_stage_authorization_sha256": sha256_file(authorization_path),
            "active_stage_authorization_action": "authorize_rebaseline",
            "state": "CONTRACTED", "next_stage_compiled": False,
        })
        atomic_write_json(staged_state_path(plan_dir), state)
        _staged_ensure_audit_once_locked(
            plan_dir,
            "contract_lineage_amended",
            {"contract_version": contract["contract_version"]},
            {
                "prior_contract_version": old_contract["contract_version"],
                "rebaseline_receipt_sha256": sha256_file(rebaseline_path),
            },
        )
        amendment_journal["phase"] = "COMMITTED"
        amendment_journal["committed_at"] = amendment_journal.get(
            "committed_at", utc_now(),
        )
        atomic_write_json(amendment_journal_path, amendment_journal)
        return {"ok": True, "contract_version": contract["contract_version"]}


def staged_locked_command(handler: Any) -> Any:
    """Serialize one public staged mutator; handlers must use _locked helpers."""
    def locked(args: argparse.Namespace) -> dict[str, Any]:
        with staged_transaction_lock(Path(args.plan_dir).resolve()):
            return handler(args)
    return locked


command_prepare_staged_research = staged_locked_command(
    command_prepare_staged_research
)
command_init_staged_research = staged_locked_command(
    command_init_staged_research
)
command_preflight_staged_research = staged_locked_command(
    command_preflight_staged_research
)
command_record_role_visible_state = staged_locked_command(
    command_record_role_visible_state
)
command_freeze_stage_candidate = staged_locked_command(
    command_freeze_stage_candidate
)
command_complete_observation_stage = staged_locked_command(
    command_complete_observation_stage
)
command_create_logical_gate_query = staged_locked_command(
    command_create_logical_gate_query
)
command_record_stage_report = staged_locked_command(command_record_stage_report)
command_record_strong_stage_review = staged_locked_command(
    command_record_strong_stage_review
)
command_compile_next_stage = staged_locked_command(command_compile_next_stage)
command_record_human_stage_input = staged_locked_command(
    command_record_human_stage_input
)
command_classify_staged_failure = staged_locked_command(
    command_classify_staged_failure
)
command_record_evaluator_rebaseline = staged_locked_command(
    command_record_evaluator_rebaseline
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    codex_prepare = sub.add_parser(
        "prepare-codex-host-plan",
        help="validate a closed brief and atomically prepare an installed Codex Host plan",
    )
    codex_prepare.add_argument("--brief", required=True)
    codex_prepare.add_argument("--plan-dir", required=True)
    codex_prepare.add_argument("--claude-bin", default=os.environ.get("CLAUDE_BIN", "claude"))
    codex_prepare.add_argument("--worker-model", default="MiniMax-M3")
    codex_prepare.add_argument("--frontier-model", default=PLAN_AUDIT_MODEL)
    codex_prepare.add_argument(
        "--frontier-reasoning-effort",
        default=PLAN_AUDIT_REASONING_EFFORT,
        choices=["low", "medium", "high", "xhigh", "max", "ultra"],
    )
    codex_prepare.set_defaults(handler=command_prepare_codex_host_plan)

    codex_activate = sub.add_parser(
        "activate-codex-host-plan",
        help="bind one authenticated first stage to a prepared Codex Host plan",
    )
    codex_activate.add_argument("--plan-dir", required=True)
    codex_activate.add_argument("--prepared-receipt", required=True)
    codex_activate.add_argument("--authorization-receipt", required=True)
    codex_activate.add_argument("--contract", required=True)
    codex_activate.add_argument("--stage-envelope", required=True)
    codex_activate.add_argument("--evaluation-profile", required=True)
    codex_activate.add_argument("--checkpoint-capacity", required=True)
    codex_activate.add_argument("--preflight-inputs", required=True)
    codex_activate.add_argument("--graph", required=True)
    codex_activate.add_argument("--incumbent-sha256", required=True)
    codex_activate.set_defaults(handler=command_activate_codex_host_plan)

    staged_prepare = sub.add_parser(
        "prepare-staged-research",
        help="validate bootstrap closure and prepare exact authorization hashes",
    )
    staged_prepare.add_argument("--plan-dir", required=True)
    staged_prepare.add_argument("--plan-id", required=True)
    staged_prepare.add_argument("--contract", required=True)
    staged_prepare.add_argument("--stage-envelope", required=True)
    staged_prepare.add_argument("--evaluation-profile", required=True)
    staged_prepare.add_argument("--checkpoint-capacity", required=True)
    staged_prepare.add_argument("--incumbent-sha256", required=True)
    staged_prepare.add_argument("--record-id", required=True)
    staged_prepare.add_argument("--prepared-operation-id", required=True)
    staged_prepare.add_argument("--continuation-stage-id")
    staged_prepare.set_defaults(handler=command_prepare_staged_research)

    staged_init = sub.add_parser(
        "init-staged-research",
        help="freeze a v1 optimization contract and exactly one first stage",
    )
    staged_init.add_argument("--plan-dir", required=True)
    staged_init.add_argument("--plan-id", required=True)
    staged_init.add_argument("--contract", required=True)
    staged_init.add_argument("--stage-envelope", required=True)
    staged_init.add_argument("--evaluation-profile", required=True)
    staged_init.add_argument("--checkpoint-capacity", required=True)
    staged_init.add_argument("--authorization-receipt", required=True)
    staged_init.add_argument("--incumbent-sha256", required=True)
    staged_init.set_defaults(handler=command_init_staged_research)

    revise_unstarted = sub.add_parser(
        "revise-unstarted-stage",
        help="replace a contracted first stage before preflight or capacity use",
    )
    revise_unstarted.add_argument("--plan-dir", required=True)
    revise_unstarted.add_argument("--contract", required=True)
    revise_unstarted.add_argument("--stage-envelope", required=True)
    revise_unstarted.add_argument("--evaluation-profile", required=True)
    revise_unstarted.add_argument("--checkpoint-capacity", required=True)
    revise_unstarted.add_argument("--authorization-receipt", required=True)
    revise_unstarted.set_defaults(handler=command_revise_unstarted_stage)

    staged_preflight = sub.add_parser(
        "preflight-staged-research",
        help="run deterministic current-stage feasibility and capacity checks",
    )
    staged_preflight.add_argument("--plan-dir", required=True)
    staged_preflight.add_argument("--preflight-inputs", required=True)
    staged_preflight.set_defaults(handler=command_preflight_staged_research)

    rebuild_staged = sub.add_parser(
        "rebuild-staged-projections",
        help="rebuild legacy progress and the human dossier from canonical staged state",
    )
    rebuild_staged.add_argument("--plan-dir", required=True)
    rebuild_staged.set_defaults(handler=command_rebuild_staged_projections)

    visible_state = sub.add_parser(
        "record-role-visible-state",
        help="persist exact rendered role state separately from audit history",
    )
    visible_state.add_argument("--plan-dir", required=True)
    visible_state.add_argument(
        "--call-kind", required=True, choices=["worker", "frontier"],
    )
    visible_state.add_argument("--call-id", required=True)
    visible_state.set_defaults(handler=command_record_role_visible_state)

    staged_candidate = sub.add_parser(
        "freeze-stage-candidate",
        help="immutably freeze the active stage's one bounded candidate",
    )
    staged_candidate.add_argument("--plan-dir", required=True)
    staged_candidate.add_argument("--candidate", required=True)
    staged_candidate.add_argument("--promotion-receipt", required=True)
    staged_candidate.set_defaults(handler=command_freeze_stage_candidate)

    logical_gate = sub.add_parser(
        "create-logical-gate-query",
        help="create the candidate's one isolated acceptance-Gate query",
    )
    logical_gate.add_argument("--plan-dir", required=True)
    logical_gate.add_argument("--logical-gate-query-id", required=True)
    logical_gate.add_argument("--candidate-sha256", required=True)
    logical_gate.add_argument("--evaluator-sha256", required=True)
    logical_gate.add_argument(
        "--requesting-role", default="controller",
        choices=["controller", "development"],
    )
    logical_gate.set_defaults(handler=command_create_logical_gate_query)

    gate_attempt = sub.add_parser(
        "record-gate-transport-attempt",
        help="append an independently budgeted retry for one logical Gate query",
    )
    gate_attempt.add_argument("--plan-dir", required=True)
    gate_attempt.add_argument("--logical-gate-query-id", required=True)
    gate_attempt.add_argument("--transport-attempt-id", required=True)
    gate_attempt.add_argument("--execution-receipt", required=True)
    gate_attempt.add_argument("--simulate-crash-after-prepare", action="store_true")
    gate_attempt.set_defaults(handler=command_record_gate_transport_attempt)

    gate_decision = sub.add_parser(
        "apply-logical-gate-decision",
        help="apply exactly one controller-owned accept/reject/escalate transition",
    )
    gate_decision.add_argument("--plan-dir", required=True)
    gate_decision.add_argument("--logical-gate-query-id", required=True)
    gate_decision.add_argument("--execution-receipt", required=True)
    gate_decision.add_argument("--simulate-crash-after-prepare", action="store_true")
    gate_decision.set_defaults(handler=command_apply_logical_gate_decision)

    observation_complete = sub.add_parser(
        "complete-observation-stage",
        help=(
            "validate and record one observation-only stage without a logical Gate"
        ),
    )
    observation_complete.add_argument("--plan-dir", required=True)
    observation_complete.set_defaults(
        handler=command_complete_observation_stage,
    )

    stage_report = sub.add_parser(
        "record-stage-report",
        help="persist a terminal MiniMax-M3 report for the active stage",
    )
    stage_report.add_argument("--plan-dir", required=True)
    stage_report.add_argument("--stage-report", required=True)
    stage_report.add_argument("--worker-run-id", required=True)
    stage_report.set_defaults(handler=command_record_stage_report)

    strong_review = sub.add_parser(
        "record-strong-stage-review",
        help="persist a fresh report-bound strongest-policy non-M3 review",
    )
    strong_review.add_argument("--plan-dir", required=True)
    strong_review.add_argument("--request-id", required=True)
    strong_review.set_defaults(handler=command_record_strong_stage_review)

    compile_stage = sub.add_parser(
        "compile-next-stage",
        help="controller-compile at most one next envelope from recorded evidence",
    )
    compile_stage.add_argument("--plan-dir", required=True)
    compile_stage.add_argument("--stage-envelope", required=True)
    compile_stage.add_argument(
        "--authorized-evidence", action="append", default=[],
    )
    compile_stage.add_argument("--figure-requirements")
    compile_stage.add_argument("--authorization-receipt", required=True)
    compile_stage.set_defaults(handler=command_compile_next_stage)

    advance_stage = sub.add_parser(
        "advance-staged-research",
        help="cross one initially authorized stage boundary and start its first Worker",
    )
    advance_stage.add_argument("--plan-dir", required=True)
    advance_stage.add_argument("--stage-envelope", required=True)
    advance_stage.add_argument("--preflight-inputs", required=True)
    advance_stage.add_argument("--task-contract", required=True)
    advance_stage.add_argument(
        "--authorized-evidence", action="append", default=[],
    )
    advance_stage.add_argument("--figure-requirements")
    advance_stage.add_argument(
        "--claude-bin", default=os.environ.get("CLAUDE_BIN", "claude"),
    )
    advance_stage.add_argument("--timeout", type=int, default=1800)
    advance_stage.set_defaults(handler=command_advance_staged_research)

    human_stage = sub.add_parser(
        "record-human-stage-input",
        help="record proposals or report-bound feedback without synthesizing authority",
    )
    human_stage.add_argument("--plan-dir", required=True)
    human_stage.add_argument("--input-id", required=True)
    human_stage.add_argument(
        "--kind", required=True, choices=["proposal", "feedback"],
    )
    human_stage.add_argument("--stage-report-id")
    human_stage.add_argument("--content-sha256", required=True)
    human_stage.set_defaults(handler=command_record_human_stage_input)

    release_evidence = sub.add_parser("release-staged-evidence")
    release_evidence.add_argument("--plan-dir", required=True)
    release_evidence.add_argument("--authorization-receipt", required=True)
    release_evidence.add_argument("--cp04-request-id", required=True)
    release_evidence.set_defaults(handler=command_release_staged_evidence)

    retrieve_evidence = sub.add_parser("retrieve-staged-evidence")
    retrieve_evidence.add_argument("--plan-dir", required=True)
    retrieve_evidence.set_defaults(handler=command_retrieve_staged_evidence)

    replay_visible = sub.add_parser("replay-role-visible-state")
    replay_visible.add_argument("--plan-dir", required=True)
    replay_visible.add_argument("--call-id", required=True)
    replay_visible.set_defaults(handler=command_replay_role_visible_state)

    classify_failure = sub.add_parser("classify-staged-failure")
    classify_failure.add_argument("--plan-dir", required=True)
    classify_failure.add_argument("--call-id", required=True)
    classify_failure.add_argument("--evidence-artifact", required=True)
    classify_failure.add_argument("--final-output", required=True)
    classify_failure.set_defaults(handler=command_classify_staged_failure)

    staged_pause = sub.add_parser("pause-staged-research")
    staged_pause.add_argument("--plan-dir", required=True)
    staged_pause.add_argument(
        "--reason", required=True,
        choices=["plateau", "repeated_rejection", "risk", "deadline", "human_stop"],
    )
    staged_pause.set_defaults(handler=command_pause_staged_research)

    staged_reauthorize = sub.add_parser("reauthorize-staged-research")
    staged_reauthorize.add_argument("--plan-dir", required=True)
    staged_reauthorize.add_argument("--authorization-receipt", required=True)
    staged_reauthorize.add_argument("--resume-receipt")
    staged_reauthorize.set_defaults(handler=command_reauthorize_staged_research)

    rebaseline = sub.add_parser("record-evaluator-rebaseline")
    rebaseline.add_argument("--plan-dir", required=True)
    rebaseline.add_argument("--contract", required=True)
    rebaseline.add_argument("--execution-receipt", required=True)
    rebaseline.add_argument("--authorization-receipt", required=True)
    rebaseline.set_defaults(handler=command_record_evaluator_rebaseline)

    amend_contract = sub.add_parser("amend-staged-contract")
    amend_contract.add_argument("--plan-dir", required=True)
    amend_contract.add_argument("--contract", required=True)
    amend_contract.add_argument("--evaluation-profile", required=True)
    amend_contract.add_argument("--stage-envelope", required=True)
    amend_contract.add_argument("--rebaseline-receipt", required=True)
    amend_contract.set_defaults(handler=command_amend_staged_contract)

    init = sub.add_parser("init-policy", help="freeze Claude/MiniMax and Codex budgets for a plan")
    init.add_argument("--plan-dir", required=True)
    init.add_argument("--worker-model", required=True)
    init.add_argument("--worker-max-budget-usd", type=float, required=True)
    init.add_argument("--frontier-model", required=True)
    init.add_argument(
        "--frontier-reasoning-effort",
        default="xhigh",
        choices=["low", "medium", "high", "xhigh", "max", "ultra"],
    )
    init.add_argument(
        "--plan-audit-model",
        default=PLAN_AUDIT_MODEL,
        choices=[PLAN_AUDIT_MODEL],
        help="strongest verified Codex model for mandatory CP-01 top-level plan review",
    )
    init.add_argument(
        "--plan-audit-reasoning-effort",
        default=PLAN_AUDIT_REASONING_EFFORT,
        choices=[PLAN_AUDIT_REASONING_EFFORT],
        help="highest verified reasoning effort for mandatory CP-01 review",
    )
    init.add_argument(
        "--frontier-transport",
        default="chatgpt-https",
        choices=sorted(FRONTIER_TRANSPORTS),
        help="use verified HTTPS-only ChatGPT transport or the local Codex default",
    )
    init.add_argument("--max-frontier-calls", type=int, required=True)
    init.add_argument("--max-frontier-input-tokens", type=int, required=True)
    init.add_argument("--max-frontier-output-tokens", type=int, required=True)
    init.add_argument("--scientific-pivot-threshold", type=int, default=2)
    init.set_defaults(handler=command_init_policy)

    worker = sub.add_parser("dispatch-worker", help="run a bounded MiniMax M3 task through Claude Code")
    worker.add_argument("--plan-dir", required=True)
    worker.add_argument("--task-contract", required=True)
    worker.add_argument("--claude-bin", default=os.environ.get("CLAUDE_BIN", "claude"))
    worker.add_argument("--timeout", type=int, default=1800)
    worker.add_argument("--writing-gate-receipt")
    worker.add_argument("--context-capsule")
    worker.add_argument(
        "--stateless-worker-session", action="store_true",
        help=(
            "explicit compatibility mode; default binds this plan to one "
            "persistent Claude Code session"
        ),
    )
    worker.set_defaults(handler=command_dispatch_worker)

    recover_worker_budget = sub.add_parser(
        "reconcile-orphan-worker-budget",
        help="refund a provably unstarted legacy worker budget reservation",
    )
    recover_worker_budget.add_argument("--plan-dir", required=True)
    recover_worker_budget.add_argument("--worker-run-id", required=True)
    recover_worker_budget.add_argument("--task-contract", required=True)
    recover_worker_budget.set_defaults(
        handler=command_reconcile_orphan_worker_budget,
    )

    recover_denied_input = sub.add_parser(
        "reconcile-denied-input-worker-budget",
        help="release scientific capacity after every frozen input read was denied",
    )
    recover_denied_input.add_argument("--plan-dir", required=True)
    recover_denied_input.add_argument("--worker-run-id", required=True)
    recover_denied_input.add_argument("--task-contract", required=True)
    recover_denied_input.set_defaults(
        handler=command_reconcile_denied_input_worker_budget,
    )

    recover_content_contract = sub.add_parser(
        "reconcile-undisclosed-content-contract-budget",
        help="release a work unit made impossible by an undisclosed closed schema",
    )
    recover_content_contract.add_argument("--plan-dir", required=True)
    recover_content_contract.add_argument("--worker-run-id", required=True)
    recover_content_contract.add_argument("--task-contract", required=True)
    recover_content_contract.set_defaults(
        handler=command_reconcile_undisclosed_content_contract_budget,
    )

    normalize_legacy_inventory = sub.add_parser(
        "normalize-legacy-source-inventory",
        help="compile a bounded pre-disclosure alias shape through validator v2",
    )
    normalize_legacy_inventory.add_argument("--plan-dir", required=True)
    normalize_legacy_inventory.add_argument("--worker-run-id", required=True)
    normalize_legacy_inventory.add_argument("--task-contract", required=True)
    normalize_legacy_inventory.set_defaults(
        handler=command_normalize_legacy_source_inventory,
    )

    promote = sub.add_parser("promote-worker-artifacts")
    promote.add_argument("--plan-dir", required=True)
    promote.add_argument("--worker-run-id", required=True)
    promote.add_argument("--simulate-crash-after", type=int, choices=range(1, 101))
    promote.set_defaults(handler=command_promote_worker_artifacts)

    commit_worker = sub.add_parser("commit-durable-worker-result")
    commit_worker.add_argument("--plan-dir", required=True)
    commit_worker.add_argument("--worker-run-id", required=True)
    commit_worker.set_defaults(handler=command_commit_durable_worker_result)

    inspect = sub.add_parser("inspect-worker")
    inspect.add_argument("--plan-dir", required=True)
    inspect.add_argument("--worker-run-id", required=True)
    inspect.set_defaults(handler=command_inspect_worker)

    inspect_plan = sub.add_parser(
        "inspect-plan-runtime",
        help="correlate canonical, scheduler, Worker, process, and log status without mutation",
    )
    inspect_plan.add_argument("--plan-dir", required=True)
    inspect_plan.add_argument(
        "--launchctl-bin", default=os.environ.get("LAUNCHCTL_BIN", "launchctl"),
    )
    inspect_plan.set_defaults(handler=command_inspect_plan_runtime)

    dashboard = sub.add_parser(
        "serve-plan-dashboard",
        help="serve one loopback-only read-only plan dashboard",
    )
    dashboard.add_argument("--plan-dir", required=True)
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument(
        "--launchctl-bin", default=os.environ.get("LAUNCHCTL_BIN", "launchctl"),
    )
    dashboard.set_defaults(handler=command_serve_plan_dashboard)

    wait = sub.add_parser("wait-worker")
    wait.add_argument("--plan-dir", required=True)
    wait.add_argument("--worker-run-id", required=True)
    wait.add_argument("--deadline-seconds", type=int, required=True)
    wait.set_defaults(handler=command_wait_worker)

    message = sub.add_parser("send-worker-message")
    message.add_argument("--plan-dir", required=True)
    message.add_argument("--worker-run-id", required=True)
    message.add_argument("--message", required=True)
    message.set_defaults(handler=command_send_worker_message)

    human = sub.add_parser("create-human-action")
    human.add_argument("--plan-dir", required=True)
    human.add_argument("--plan-id", required=True)
    human.add_argument("--action", required=True, choices=sorted(HUMAN_ACTIONS))
    human.add_argument("--key-file", required=True)
    human.add_argument("--expires-in", type=int, required=True)
    human.add_argument("--reason")
    human.add_argument("--record-id")
    human.add_argument("--actor")
    human.add_argument("--worker-run-id")
    human.add_argument("--resource-id")
    human.add_argument("--binding-sha256")
    human.add_argument("--contract-version")
    human.add_argument("--stage-id")
    human.add_argument("--contract-sha256")
    human.add_argument("--stage-envelope-sha256")
    human.add_argument("--evidence-id")
    human.add_argument("--candidate")
    human.add_argument("--verdict")
    human.add_argument("--tier", choices=["arxiv", "conference", "journal-q1"])
    human.add_argument("--negative-result", action="store_true")
    human.add_argument("--learning-proposal")
    human.add_argument("--add-frontier-calls", type=int)
    human.add_argument("--add-frontier-input-tokens", type=int)
    human.add_argument("--add-frontier-output-tokens", type=int)
    human.add_argument("--authorization-proposal")
    human.add_argument("--prepared-operation-id")
    human.add_argument("--continuation-stage-id", action="append", default=[])
    human.add_argument("--continuation-stage-limit", type=int)
    human.set_defaults(handler=command_create_human_action)

    apply_human = sub.add_parser("apply-human-action")
    apply_human.add_argument("--plan-dir", required=True)
    apply_human.add_argument("--record", required=True)
    apply_human.add_argument("--key-file", required=True)
    apply_human.add_argument("--worker-run-id")
    apply_human.add_argument("--expected-action")
    apply_human.add_argument("--simulate-crash-after", choices=["prepared", "replay", "mutation", "audit"])
    apply_human.set_defaults(handler=command_apply_human_action)

    cancel = sub.add_parser("cancel-worker")
    cancel.add_argument("--plan-dir", required=True)
    cancel.add_argument("--record", required=True)
    cancel.add_argument("--key-file", required=True)
    cancel.add_argument("--worker-run-id", required=True)
    cancel.add_argument("--simulate-crash-after", choices=["prepared", "replay", "mutation", "audit"])
    cancel.set_defaults(handler=command_apply_human_action, expected_action="cancel_worker")

    validate_action = sub.add_parser("validate-action-receipt")
    validate_action.add_argument("--plan-dir", required=True)
    validate_action.add_argument("--receipt", required=True)
    validate_action.add_argument("--action", required=True, choices=sorted(HUMAN_ACTIONS))
    validate_action.set_defaults(handler=command_validate_action_receipt)

    evaluator_run = sub.add_parser("run-evaluator")
    evaluator_run.add_argument("--plan-dir", required=True)
    evaluator_run.add_argument("--evaluator", required=True)
    evaluator_run.add_argument("--evidence", required=True)
    evaluator_run.add_argument("--candidate", required=True)
    evaluator_run.add_argument("--purpose", required=True, choices=["calibration", "candidate"])
    evaluator_run.add_argument("--timeout", type=int, default=1800)
    evaluator_run.set_defaults(handler=command_run_evaluator)

    freeze = sub.add_parser("freeze-evaluator")
    freeze.add_argument("--plan-dir", required=True)
    freeze.add_argument("--execution-receipt", required=True)
    freeze.set_defaults(handler=command_freeze_evaluator)

    verdict = sub.add_parser("record-evaluator-verdict")
    verdict.add_argument("--plan-dir", required=True)
    verdict.add_argument("--execution-receipt", required=True)
    verdict.add_argument("--candidate-id", required=True)
    verdict.set_defaults(handler=command_record_evaluator_verdict)

    scientific_acceptance = sub.add_parser("check-scientific-acceptance")
    scientific_acceptance.add_argument("--plan-dir", required=True)
    scientific_acceptance.add_argument("--verdict", required=True)
    scientific_acceptance.set_defaults(handler=command_check_scientific_acceptance)

    figure_gate = sub.add_parser("check-figure-gate")
    figure_gate.add_argument("--plan-dir", required=True)
    figure_gate.add_argument("--inventory", required=True)
    figure_gate.add_argument("--requirements", required=True)
    figure_gate.set_defaults(handler=command_check_figure_gate)

    writing = sub.add_parser("check-writing-gate")
    writing.add_argument("--plan-dir", required=True)
    writing.add_argument("--tier", required=True, choices=["arxiv", "conference", "journal-q1"])
    writing.add_argument("--verdict")
    writing.add_argument("--waiver")
    writing.add_argument("--figure-gate-receipt", required=True)
    writing.set_defaults(handler=command_check_writing_gate)

    failure = sub.add_parser("record-failure")
    failure.add_argument("--plan-dir", required=True)
    failure.add_argument(
        "--class", dest="failure_class", required=True,
        choices=sorted(FAILURE_CLASSES - INTEGRITY_FAILURE_CLASSES),
    )
    failure.add_argument("--fingerprint")
    failure.add_argument("--direction")
    failure.add_argument("--verdict")
    failure.add_argument("--source", required=True)
    failure.set_defaults(handler=command_record_failure)

    integrity = sub.add_parser("check-research-integrity")
    integrity.add_argument("--plan-dir", required=True)
    integrity.set_defaults(handler=command_check_research_integrity)

    memory = sub.add_parser("promote-episode-memory")
    memory.add_argument("--plan-dir", required=True)
    memory.add_argument("--episode-manifest", required=True)
    memory.add_argument("--diagnosis", required=True)
    memory.add_argument("--replay", required=True)
    memory.add_argument("--validation", required=True)
    memory.add_argument("--audit", required=True)
    memory.add_argument("--auditor-identity", required=True)
    memory.set_defaults(handler=command_promote_episode_memory)

    learning = sub.add_parser("promote-learning-proposal")
    learning.add_argument("--plan-dir", required=True)
    learning.add_argument("--memory-receipt", required=True)
    learning.add_argument("--proposal", required=True)
    learning.add_argument(
        "--target-kind", required=True, choices=sorted(LEARNING_TARGET_KINDS),
    )
    learning.add_argument("--replay", required=True)
    learning.add_argument("--validation", required=True)
    learning.add_argument("--audit", required=True)
    learning.add_argument("--auditor-identity", required=True)
    learning.add_argument("--authorization")
    learning.set_defaults(handler=command_promote_learning_proposal)

    acceptance_start = sub.add_parser("start-acceptance-profile")
    acceptance_start.add_argument("--plan-dir", required=True)
    acceptance_start.add_argument("--profile", required=True)
    acceptance_start.set_defaults(handler=command_start_acceptance_profile)

    acceptance_complete = sub.add_parser("complete-acceptance-profile")
    acceptance_complete.add_argument("--plan-dir", required=True)
    acceptance_complete.add_argument("--profile-id", required=True)
    acceptance_complete.add_argument(
        "--fault-evidence", action="append", default=[], required=True,
    )
    acceptance_complete.add_argument(
        "--session-observation", action="append", default=[], required=True,
    )
    acceptance_complete.set_defaults(handler=command_complete_acceptance_profile)

    acceptance_claim = sub.add_parser("validate-acceptance-claim")
    acceptance_claim.add_argument("--plan-dir", required=True)
    acceptance_claim.add_argument("--profile-id", required=True)
    acceptance_claim.add_argument(
        "--claim-kind", required=True, choices=sorted(ACCEPTANCE_CLAIM_KINDS),
    )
    acceptance_claim.add_argument(
        "--claimed-duration-seconds", type=int, required=True,
    )
    acceptance_claim.set_defaults(handler=command_validate_acceptance_claim)

    pivot = sub.add_parser("pivot-eligibility")
    pivot.add_argument("--plan-dir", required=True)
    pivot.set_defaults(handler=command_pivot_eligibility)

    apply_pivot = sub.add_parser("apply-structural-pivot")
    apply_pivot.add_argument("--plan-dir", required=True)
    apply_pivot.add_argument("--proposal", required=True)
    apply_pivot.set_defaults(handler=command_apply_structural_pivot)

    dispute = sub.add_parser("resolve-acceptance-dispute")
    dispute.add_argument("--plan-dir", required=True)
    dispute.add_argument("--resolution", required=True)
    dispute.set_defaults(handler=command_resolve_acceptance_dispute)

    schedule = sub.add_parser("schedule-patrol")
    schedule.add_argument("--plan-dir", required=True)
    schedule.add_argument("--interval-seconds", type=int, required=True)
    schedule.set_defaults(handler=command_schedule_patrol)

    patrol = sub.add_parser("run-patrol")
    patrol.add_argument("--plan-dir", required=True)
    patrol.add_argument("--stale-seconds", type=int, required=True)
    patrol.set_defaults(handler=command_run_patrol)

    evaluator_admit = sub.add_parser("admit-evaluator")
    evaluator_admit.add_argument("--plan-dir", required=True)
    evaluator_admit.add_argument("--contract", required=True)
    evaluator_admit.add_argument("--evaluator", required=True)
    evaluator_admit.add_argument("--authority-identity", required=True)
    evaluator_admit.add_argument("--input-manifest", required=True)
    evaluator_admit.add_argument("--validation-identity", required=True)
    evaluator_admit.add_argument("--replay-identity", required=True)
    evaluator_admit.add_argument("--regression-suite", required=True)
    evaluator_admit.add_argument("--allowed-search-space", required=True)
    evaluator_admit.add_argument("--complexity-identity")
    evaluator_admit.set_defaults(handler=command_admit_evaluator)

    evaluator_eligibility = sub.add_parser("check-autonomy-eligibility")
    evaluator_eligibility.add_argument("--plan-dir", required=True)
    evaluator_eligibility.set_defaults(handler=command_check_autonomy_eligibility)

    durable_init = sub.add_parser("init-durable-plan")
    durable_init.add_argument("--plan-dir", required=True)
    durable_init.add_argument("--graph", required=True)
    durable_init.set_defaults(handler=command_init_durable_plan)

    durable_advance = sub.add_parser("advance-durable-plan")
    durable_advance.add_argument("--plan-dir", required=True)
    durable_advance.set_defaults(handler=command_advance_durable_plan)

    durable_apply = sub.add_parser("apply-work-unit-result")
    durable_apply.add_argument("--plan-dir", required=True)
    durable_apply.add_argument("--capsule", required=True)
    durable_apply.add_argument("--result", required=True)
    durable_apply.set_defaults(handler=command_apply_work_unit_result)

    durable_rebuild = sub.add_parser("rebuild-durable-projection")
    durable_rebuild.add_argument("--plan-dir", required=True)
    durable_rebuild.set_defaults(handler=command_rebuild_durable_projection)

    trigger_register = sub.add_parser("register-durable-trigger")
    trigger_register.add_argument("--plan-dir", required=True)
    trigger_register.add_argument("--schedule-id", default="research_loop")
    trigger_register.add_argument("--interval-seconds", type=int, required=True)
    trigger_register.add_argument("--jitter-seconds", type=int, default=0)
    trigger_register.add_argument("--session-budget-seconds", type=int, required=True)
    trigger_register.add_argument("--human-escalation-after-seconds", type=int, required=True)
    trigger_register.add_argument("--lease-seconds", type=int, default=300)
    trigger_register.add_argument("--first-due-at")
    trigger_register.add_argument(
        "--launchctl-bin", default=os.environ.get("LAUNCHCTL_BIN", "launchctl"),
    )
    trigger_register.add_argument("--simulate-crash-after-bootstrap", action="store_true")
    trigger_register.set_defaults(handler=command_register_durable_trigger)

    trigger_unregister = sub.add_parser("unregister-durable-trigger")
    trigger_unregister.add_argument("--plan-dir", required=True)
    trigger_unregister.add_argument("--schedule-id", default="research_loop")
    trigger_unregister.add_argument("--authorization", required=True)
    trigger_unregister.add_argument(
        "--launchctl-bin", default=os.environ.get("LAUNCHCTL_BIN", "launchctl"),
    )
    trigger_unregister.set_defaults(handler=command_unregister_durable_trigger)

    frontier_trigger = sub.add_parser("register-frontier-retry-trigger")
    frontier_trigger.add_argument("--plan-dir", required=True)
    frontier_trigger.add_argument("--interval-seconds", type=int, default=1800)
    frontier_trigger.add_argument("--timeout", type=int, default=1800)
    frontier_trigger.add_argument(
        "--codex-bin", default=os.environ.get("CODEX_BIN", "codex"),
    )
    frontier_trigger.add_argument(
        "--launchctl-bin", default=os.environ.get("LAUNCHCTL_BIN", "launchctl"),
    )
    frontier_trigger.set_defaults(handler=command_register_frontier_retry_trigger)

    frontier_trigger_remove = sub.add_parser(
        "unregister-frontier-retry-trigger",
    )
    frontier_trigger_remove.add_argument("--plan-dir", required=True)
    frontier_trigger_remove.add_argument("--authorization", required=True)
    frontier_trigger_remove.set_defaults(
        handler=command_unregister_frontier_retry_trigger,
    )

    assurance_activate = sub.add_parser("activate-runtime-assurance")
    assurance_activate.add_argument("--plan-dir", required=True)
    assurance_activate.add_argument("--schedule-id", default="research_loop")
    assurance_activate.add_argument(
        "--health-interval-seconds", type=int, default=1800,
    )
    assurance_activate.add_argument(
        "--worker-stale-seconds", type=int, default=7200,
    )
    assurance_activate.add_argument(
        "--frontier-stale-seconds", type=int, default=7200,
    )
    assurance_activate.add_argument(
        "--heartbeat-stale-seconds", type=int, default=3600,
    )
    assurance_activate.add_argument(
        "--launchctl-bin", default=os.environ.get("LAUNCHCTL_BIN", "launchctl"),
    )
    assurance_activate.set_defaults(handler=command_activate_runtime_assurance)

    host_bootstrap = sub.add_parser(
        "bootstrap-host-runtime",
        help="transactionally compose and exercise Codex-host L0/L1/L2 assurance",
    )
    host_bootstrap.add_argument("--plan-dir", required=True)
    host_bootstrap.add_argument("--graph", required=True)
    host_bootstrap.add_argument("--schedule-id", default="research_loop")
    host_bootstrap.add_argument("--interval-seconds", type=int, default=300)
    host_bootstrap.add_argument("--jitter-seconds", type=int, default=30)
    host_bootstrap.add_argument("--session-budget-seconds", type=int, default=1800)
    host_bootstrap.add_argument(
        "--human-escalation-after-seconds", type=int, default=900,
    )
    host_bootstrap.add_argument("--lease-seconds", type=int, default=300)
    host_bootstrap.add_argument(
        "--health-interval-seconds", type=int, default=1800,
    )
    host_bootstrap.add_argument("--worker-stale-seconds", type=int, default=7200)
    host_bootstrap.add_argument("--frontier-stale-seconds", type=int, default=7200)
    host_bootstrap.add_argument("--heartbeat-stale-seconds", type=int, default=3600)
    host_bootstrap.add_argument("--dashboard-port", type=int, default=8765)
    host_bootstrap.add_argument(
        "--launchctl-bin", default=os.environ.get("LAUNCHCTL_BIN", "launchctl"),
    )
    host_bootstrap.add_argument(
        "--simulate-crash-after",
        choices=["l1_registered", "assurance_activated", "l1_probe", "l1_bootout"],
    )
    host_bootstrap.set_defaults(handler=command_bootstrap_host_runtime)

    assurance_tick = sub.add_parser("run-runtime-assurance-tick")
    assurance_tick.add_argument("--plan-dir", required=True)
    assurance_tick.set_defaults(handler=command_run_runtime_assurance_tick)

    assurance_unregister = sub.add_parser("unregister-runtime-assurance")
    assurance_unregister.add_argument("--plan-dir", required=True)
    assurance_unregister.add_argument("--authorization", required=True)
    assurance_unregister.set_defaults(handler=command_unregister_runtime_assurance)

    shutdown = sub.add_parser(
        "shutdown-plan",
        help="deactivate target schedulers and bound Workers under an applied stop receipt",
    )
    shutdown.add_argument("--plan-dir", required=True)
    shutdown.add_argument("--authorization", required=True)
    shutdown.add_argument("--term-grace-seconds", type=float, default=5.0)
    shutdown.add_argument(
        "--launchctl-bin", default=os.environ.get("LAUNCHCTL_BIN", "launchctl"),
    )
    shutdown.add_argument(
        "--simulate-crash-after",
        choices=["l0", "l1", "frontier_retry", "worker"],
    )
    shutdown.set_defaults(handler=command_shutdown_plan)

    worker_heartbeat = sub.add_parser("record-worker-heartbeat")
    worker_heartbeat.add_argument("--plan-dir", required=True)
    worker_heartbeat.add_argument("--worker-run-id", required=True)
    worker_heartbeat.add_argument(
        "--source", default="claude_post_tool_hook",
    )
    worker_heartbeat.set_defaults(handler=command_record_worker_heartbeat)

    tick_claim = sub.add_parser("claim-durable-tick")
    tick_claim.add_argument("--plan-dir", required=True)
    tick_claim.add_argument("--schedule-id", default="research_loop")
    tick_claim.add_argument("--tick-id", required=True)
    tick_claim.add_argument("--observed-at")
    tick_claim.add_argument("--lease-seconds", type=int, default=300)
    tick_claim.set_defaults(handler=command_claim_durable_tick)

    tick_reconcile = sub.add_parser("reconcile-durable-tick")
    tick_reconcile.add_argument("--plan-dir", required=True)
    tick_reconcile.add_argument("--schedule-id", default="research_loop")
    tick_reconcile.add_argument("--tick-id", required=True)
    tick_reconcile.add_argument("--observed-at")
    tick_reconcile.set_defaults(handler=command_reconcile_durable_tick)

    tick_run = sub.add_parser("run-durable-tick")
    tick_run.add_argument("--plan-dir", required=True)
    tick_run.add_argument("--schedule-id", default="research_loop")
    tick_run.add_argument("--observed-at")
    tick_run.add_argument("--simulate-crash-after-tick-apply", action="store_true")
    tick_run.set_defaults(handler=command_run_durable_tick)

    guardian = sub.add_parser("guardian-observe")
    guardian.add_argument("--plan-dir", required=True)
    guardian.add_argument("--observation", required=True)
    guardian.add_argument("--stale-seconds", type=int, required=True)
    guardian.set_defaults(handler=command_guardian_observe)

    guardian_apply = sub.add_parser("apply-guardian-proposal")
    guardian_apply.add_argument("--plan-dir", required=True)
    guardian_apply.add_argument("--proposal", required=True)
    guardian_apply.add_argument("--action-index", type=int, required=True)
    guardian_apply.set_defaults(handler=command_apply_guardian_proposal)

    guardian_lifecycle = sub.add_parser("guardian-validate-lifecycle")
    guardian_lifecycle.add_argument("--plan-dir", required=True)
    guardian_lifecycle.add_argument("--action", required=True, choices=["pause", "resume", "stop"])
    guardian_lifecycle.add_argument("--authorization", required=True)
    guardian_lifecycle.set_defaults(handler=command_guardian_validate_lifecycle)

    remove = sub.add_parser("remove-resource")
    remove.add_argument("--plan-dir", required=True)
    remove.add_argument("--resource-id", required=True)
    remove.add_argument("--ownership-token", required=True)
    remove.add_argument("--authorization", required=True)
    remove.add_argument("--simulate-crash-after", choices=["unlink"])
    remove.set_defaults(handler=command_remove_resource)

    create = sub.add_parser("create-frontier-request", help="create an immutable checkpoint request")
    create.add_argument("--plan-dir", required=True)
    create.add_argument("--plan-id", required=True)
    create.add_argument("--checkpoint", required=True)
    create.add_argument("--checkpoint-subtype")
    create.add_argument("--attempt", type=int, default=1)
    create.add_argument("--objective", required=True)
    create.add_argument("--decision-required", required=True)
    create.add_argument("--artifact", action="append", default=[], help="PATH[::PURPOSE]; repeatable")
    create.add_argument("--constraint", action="append", default=[])
    create.add_argument("--max-input-tokens", type=int, required=True)
    create.add_argument("--max-output-tokens", type=int, required=True)
    create.add_argument("--request-id")
    create.add_argument("--deadline-seconds", type=int, default=1800)
    create.add_argument("--context-capsule")
    create.set_defaults(handler=command_create_request)

    retry_frontier = sub.add_parser(
        "retry-frontier-request",
        help="create a new bounded attempt for a failed logical checkpoint",
    )
    retry_frontier.add_argument("--plan-dir", required=True)
    retry_frontier.add_argument("--source-request-id", required=True)
    retry_frontier.add_argument("--request-id", required=True)
    retry_frontier.add_argument("--deadline-seconds", type=int, default=1800)
    retry_frontier.set_defaults(handler=command_retry_frontier_request)

    recover_frontier = sub.add_parser(
        "recover-due-frontier-retry",
        help="run at most one due provider-quota retry under work-loop authority",
    )
    recover_frontier.add_argument("--plan-dir", required=True)
    recover_frontier.add_argument(
        "--codex-bin", default=os.environ.get("CODEX_BIN", "codex"),
    )
    recover_frontier.add_argument("--timeout", type=int, default=1800)
    recover_frontier.set_defaults(handler=command_recover_due_frontier_retry)

    classify_frontier = sub.add_parser(
        "classify-paused-frontier-failure",
        help="type a legacy PAUSED transport failure from its frozen logs",
    )
    classify_frontier.add_argument("--plan-dir", required=True)
    classify_frontier.add_argument("--request-id", required=True)
    classify_frontier.set_defaults(handler=command_classify_paused_frontier_failure)

    create_durable = sub.add_parser(
        "create-durable-frontier-request",
        help="derive an immutable checkpoint request from the current durable capsule",
    )
    create_durable.add_argument("--plan-dir", required=True)
    create_durable.add_argument("--context-capsule", required=True)
    create_durable.add_argument("--checkpoint", required=True)
    create_durable.add_argument("--checkpoint-subtype")
    create_durable.add_argument("--attempt", type=int, default=1)
    create_durable.add_argument("--objective", required=True)
    create_durable.add_argument("--decision-required", required=True)
    create_durable.add_argument("--constraint", action="append", default=[])
    create_durable.add_argument("--max-input-tokens", type=int, required=True)
    create_durable.add_argument("--max-output-tokens", type=int, required=True)
    create_durable.add_argument("--request-id")
    create_durable.add_argument("--deadline-seconds", type=int, default=1800)
    create_durable.set_defaults(handler=command_create_durable_request)

    send = sub.add_parser("send-frontier-request", help="reserve budget and call Codex")
    send.add_argument("--plan-dir", required=True)
    send.add_argument("--request-id", required=True)
    send.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    send.add_argument("--timeout", type=int, default=1800)
    send.set_defaults(handler=command_send_request)

    reconcile = sub.add_parser("reconcile-frontier-request")
    reconcile.add_argument("--plan-dir", required=True)
    reconcile.add_argument("--request-id", required=True)
    reconcile.set_defaults(handler=command_reconcile_request)

    validate = sub.add_parser("validate-frontier-response", help="validate correlation, schema, hashes, and budget")
    validate.add_argument("--plan-dir", required=True)
    validate.add_argument("--request-id", required=True)
    validate.set_defaults(handler=command_validate_response)

    apply = sub.add_parser("apply-frontier-response", help="record idempotent controller consumption of advice")
    apply.add_argument("--plan-dir", required=True)
    apply.add_argument("--request-id", required=True)
    apply.add_argument("--controller-note", required=True)
    apply.add_argument("--dependent-transition", required=True)
    apply.set_defaults(handler=command_apply_response)

    commit_frontier = sub.add_parser("commit-durable-frontier-result")
    commit_frontier.add_argument("--plan-dir", required=True)
    commit_frontier.add_argument("--request-id", required=True)
    commit_frontier.set_defaults(handler=command_commit_durable_frontier_result)

    status = sub.add_parser("frontier-status", help="read durable checkpoint state")
    status.add_argument("--plan-dir", required=True)
    status.add_argument("--request-id", required=True)
    status.set_defaults(handler=command_status)

    expire = sub.add_parser("expire-frontier-request")
    expire.add_argument("--plan-dir", required=True)
    expire.add_argument("--request-id", required=True)
    expire.add_argument("--now", required=True)
    expire.set_defaults(handler=command_expire_request)

    assertion = sub.add_parser("assert-transition")
    assertion.add_argument("--plan-dir", required=True)
    assertion.add_argument("--plan-id", required=True)
    assertion.add_argument("--transition", required=True)
    assertion.add_argument("--request-id")
    assertion.set_defaults(handler=command_assert_transition)
    for command_parser in sub.choices.values():
        command_parser.add_argument(
            "--operation-id",
            help="stable caller operation identity for exact-once subprocess reconciliation",
        )
    return parser


def operation_effect_path(plan_dir: Path, operation_id: str) -> Path:
    return plan_dir / "state" / "runtime_operations" / "effects" / f"{operation_id}.json"


def read_operation_effect(
    plan_dir: Path, operation_id: str, request_sha256: str,
) -> dict[str, Any] | None:
    path = operation_effect_path(plan_dir, operation_id)
    if not path.exists():
        return None
    effect = read_json(path)
    if (
        effect.get("operation_id") != operation_id
        or effect.get("request_sha256") != request_sha256
        or not isinstance(effect.get("result"), dict)
    ):
        raise ContractError("operation effect receipt correlation mismatch")
    return effect["result"]


def write_operation_effect(
    plan_dir: Path, operation_id: str, request_sha256: str,
    command: str, result: dict[str, Any],
) -> None:
    path = operation_effect_path(plan_dir, operation_id)
    effect = {
        "schema_version": 1,
        "operation_id": operation_id,
        "request_sha256": request_sha256,
        "command": command,
        "result": result,
        "effect_committed_at": utc_now(),
    }
    if path.exists():
        prior = read_json(path)
        if prior.get("request_sha256") != request_sha256 or prior.get("result") != result:
            raise ContractError("operation effect receipt collision")
        return
    atomic_write_json(path, effect, immutable=True)


def reconcile_ambiguous_prepared_operation(
    args: argparse.Namespace, plan_dir: Path, operation_id: str,
) -> dict[str, Any]:
    """Reconcile external delivery or re-enter an exact local durable operation."""
    if args.command == "dispatch-worker":
        run_id = "cwr_" + operation_id[3:35]
        run_dir = worker_run_dir(plan_dir, run_id, must_exist=False)
        if not run_dir.exists():
            return {**args.handler(args), "operation_reconciled": True}
        if run_dir.is_dir() and (run_dir / "status.json").is_file():
            status = read_json(run_dir / "status.json")
            if status.get("status") in TERMINAL_WORKER_STATES:
                reconcile_worker_session_turn(
                    plan_dir, run_id, status["status"], status.get("failure"),
                )
                return {**status, "operation_reconciled": True}
            process_reconciliation = signal_bound_worker_process(
                status, term_grace_seconds=1.0,
            )
            if process_reconciliation.get("outcome") not in {
                "terminated", "already_absent",
            }:
                update_worker_status(plan_dir, run_id, status["status"], {
                    "failure": "transport_outcome_unresolved",
                    "reconciliation_required": True,
                    "process_reconciliation": process_reconciliation,
                })
                record_worker_session_failure(
                    plan_dir, "delivery_uncertain", {
                        "worker_run_id": run_id,
                        "reconciliation_required": True,
                        "process_reconciliation": process_reconciliation,
                    },
                )
                raise ContractError(
                    "delivery_uncertain: Worker process termination is unproven; "
                    "session remains BUSY and no terminal receipt was committed"
                )
            status = update_worker_status(plan_dir, run_id, "PAUSED", {
                "failure": "transport_outcome_uncertain",
                "reconciliation_required": True,
                "process_reconciliation": process_reconciliation,
            })
            reconcile_worker_session_turn(
                plan_dir, run_id, "PAUSED", "transport_outcome_uncertain",
            )
        raise ContractError("worker operation is ambiguous and PAUSED; explicit reconciliation is required")
    if args.command == "send-frontier-request":
        current = read_json(status_path(plan_dir, args.request_id))
        if (
            current["state"] == "PAUSED"
            and current.get("failure") != "transport_outcome_uncertain"
        ):
            raise ContractError(
                "paused frontier requests are never redelivered; "
                "reconcile or create a new attempt"
            )
        ledger_path = frontier_root(plan_dir) / "budget.json"
        ledger = read_json(ledger_path) if ledger_path.exists() else {"request_ids": []}
        if (
            current["state"] == "CREATED"
            and args.request_id in ledger.get("request_ids", [])
        ):
            transition(
                plan_dir,
                args.request_id,
                "BUDGET_RESERVED",
                budget_snapshot=ledger,
                recovered_from="ledger_before_status_transition",
            )
            return {**args.handler(args), "operation_reconciled": True}
        if current["state"] == "BUDGET_RESERVED":
            return {**args.handler(args), "operation_reconciled": True}
        send_claim = current.get("send_claim")
        release_intent = (
            request_dir(plan_dir, args.request_id)
            / "budget-releases"
            / f"{send_claim}.intent.json"
        )
        if (
            current["state"] in {"SENT", "WAITING"}
            and isinstance(send_claim, str)
            and release_intent.exists()
        ):
            _, request = load_request(plan_dir, args.request_id)
            recovery = release_unstarted_frontier_budget(
                plan_dir,
                request,
                send_claim,
                OSError("recovered transport_not_started release"),
            )
            transition(
                plan_dir,
                args.request_id,
                "CREATED",
                failure="transport_not_started",
                budget_recovery=recovery,
            )
            return {**args.handler(args), "operation_reconciled": True}
        if (
            current["state"] == "CREATED"
            and args.request_id not in ledger.get("request_ids", [])
        ):
            return {**args.handler(args), "operation_reconciled": True}
        with request_send_lock(plan_dir, args.request_id):
            reconciled = reconcile_frontier_locked(plan_dir, args.request_id)
        if not reconciled.get("ok"):
            raise ContractError("frontier delivery is PAUSED; explicit reconciliation is required")
        return {**reconciled, "operation_reconciled": True}
    # The PREPARED journal and request hash freeze the exact invocation. Local
    # handlers are required to be idempotent or own a durable recovery journal,
    # so re-entry lets that command-specific authority converge after a crash.
    return {**args.handler(args), "operation_reconciled": True}


def main() -> int:
    args = build_parser().parse_args()
    try:
        operation_id = getattr(args, "operation_id", None)
        if args.command == "prepare-codex-host-plan" and operation_id:
            raise ContractError(
                "prepare-codex-host-plan rejects operation journaling before plan publication"
            )
        if args.command in {"inspect-plan-runtime", "serve-plan-dashboard"} and operation_id:
            raise ContractError(
                f"{args.command} is observation-only and rejects operation journaling"
            )
        if operation_id:
            if not OPERATION_ID_RE.fullmatch(operation_id):
                raise ContractError("operation_id must be op_ followed by 64 lowercase hex characters")
            plan_dir = Path(args.plan_dir).resolve()
            request = {
                key: value for key, value in vars(args).items()
                if key not in {"handler", "operation_id"} and value is not None
            }
            request_sha256 = sha256_json(request)
            journal_path = plan_dir / "state" / "runtime_operations" / f"{operation_id}.json"
            lock_path = plan_dir / "state" / "runtime_operations" / f".{operation_id}.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                journal = read_json(journal_path) if journal_path.exists() else None
                if journal:
                    if journal.get("request_sha256") != request_sha256:
                        raise ContractError("operation_id collision: canonical command request differs")
                    if journal.get("phase") == "COMMITTED":
                        result = {**journal["result"], "operation_reconciled": True}
                    else:
                        effect_result = read_operation_effect(
                            plan_dir, operation_id, request_sha256,
                        )
                        result = (
                            {**effect_result, "operation_reconciled": True}
                            if effect_result is not None
                            else reconcile_ambiguous_prepared_operation(args, plan_dir, operation_id)
                        )
                else:
                    atomic_write_json(journal_path, {
                        "schema_version": 1, "operation_id": operation_id, "phase": "PREPARED",
                        "request": request, "request_sha256": request_sha256, "prepared_at": utc_now(),
                    })
                    result = args.handler(args)
                    if os.environ.get("HARNESS_FAULT_AFTER_HANDLER") == args.command:
                        raise ContractError(f"simulated crash after {args.command} handler effects")
                    write_operation_effect(
                        plan_dir, operation_id, request_sha256, args.command, result,
                    )
                if not journal or journal.get("phase") != "COMMITTED":
                    if read_operation_effect(plan_dir, operation_id, request_sha256) is None:
                        write_operation_effect(
                            plan_dir, operation_id, request_sha256, args.command, result,
                        )
                    atomic_write_json(journal_path, {
                        "schema_version": 1, "operation_id": operation_id, "phase": "COMMITTED",
                        "request": request, "request_sha256": request_sha256,
                        "result": result, "committed_at": utc_now(),
                    })
        else:
            result = args.handler(args)
    except ContractError as exc:
        if getattr(args, "command", None) == "bootstrap-host-runtime":
            try:
                record_host_bootstrap_failure(
                    Path(args.plan_dir).resolve(), str(exc),
                )
            except (ContractError, OSError, ValueError):
                pass
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 20 if args.command == "check-writing-gate" else 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
