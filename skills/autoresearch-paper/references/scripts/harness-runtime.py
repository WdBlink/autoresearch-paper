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
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1
CHECKPOINTS = {
    "CP-01": {"kind": "plan_audit", "subtypes": {None}, "recommendations": {"accept", "revise", "block"}},
    "CP-02": {"kind": "evaluator_audit", "subtypes": {None}, "recommendations": {"accept", "revise", "block"}},
    "CP-03": {"kind": "pivot_advice", "subtypes": {None}, "recommendations": {"pivot", "repair", "escalate_human", "block"}},
    "CP-04": {
        "kind": "evidence_audit",
        "subtypes": {"acceptance_dispute", "prewriting_final_evidence"},
        "recommendations": {"accept", "repair", "escalate_human", "block"},
    },
}
DEPENDENT_TRANSITIONS = {
    ("CP-01", None): ("approve_execution", {"accept"}),
    ("CP-02", None): ("freeze_evaluator", {"accept"}),
    ("CP-03", None): ("authorize_structural_pivot", {"pivot", "repair"}),
    ("CP-04", "acceptance_dispute"): ("resolve_acceptance_dispute", {"accept"}),
    ("CP-04", "prewriting_final_evidence"): ("start_writing", {"accept"}),
}
HUMAN_ACTIONS = {
    "pause", "resume", "stop", "cancel_worker", "waive_acceptance",
    "override_acceptance", "cleanup_resource",
}
FAILURE_CLASSES = {
    "runtime_stall", "implementation_failure", "scientific_no_improvement",
    "duplicate_direction", "verifier_rejection",
}
TERMINAL_WORKER_STATES = {"COMPLETED", "FAILED", "PAUSED", "CANCELLED"}
READ_ONLY_CLAUDE_TOOLS = {"Read", "Glob", "Grep", "WebSearch", "WebFetch"}
REQUEST_ID_RE = re.compile(r"^far_[A-Za-z0-9_-]+$")
WORKER_ID_RE = re.compile(r"^cwr_[a-f0-9]{32}$")
STATES = {
    "CREATED", "BUDGET_RESERVED", "SENT", "WAITING", "RECEIVED",
    "VALIDATED", "APPLIED", "EXPIRED", "INVALID", "PAUSED",
}
SCRIPT_DIR = Path(__file__).resolve().parent
RESPONSE_SCHEMA = SCRIPT_DIR.parent / "frontier-response.schema.json"
HUMAN_ACTION_SCHEMA = SCRIPT_DIR.parent / "human-action.schema.json"
EVALUATOR_VERDICT_SCHEMA = SCRIPT_DIR.parent / "evaluator-verdict.schema.json"
CHECKPOINT_EVIDENCE_PROFILES = {
    ("CP-01", None): {
        "normalized_brief", "execution_plan", "risk_budget",
    },
    ("CP-02", None): {
        "evaluator", "evidence_manifest", "metric_contract", "baselines",
        "seeds_splits", "leakage_controls", "calibration_candidate",
    },
    ("CP-03", None): {
        "failure_state", "direction_registry", "pivot_proposal", "evaluator_verdict",
    },
    ("CP-04", "acceptance_dispute"): {
        "evaluator_contract", "evaluator_verdict", "dispute_record", "candidate",
    },
    ("CP-04", "prewriting_final_evidence"): {
        "candidate", "claim_evidence_map", "evaluator_contract", "evaluator_verdict",
        "raw_result_manifest", "baselines", "uncertainty_robustness",
    },
}
DIRECTION_FIELDS = {
    "algorithm_family", "data_representation", "objective", "evaluator",
    "baseline_framing", "lineage", "candidate_sha256",
}


class ContractError(RuntimeError):
    """A runtime or data contract was violated."""


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
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ContractError(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def atomic_write_json(path: Path, value: dict[str, Any], *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    with temporary.open("w") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    if immutable:
        path.chmod(0o444)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")
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
    escalation = policy.get("frontier_escalation")
    if not isinstance(escalation, dict) or escalation.get("enabled") is not True:
        raise ContractError("frontier_escalation must be enabled and frozen")
    for field in ("max_calls", "max_input_tokens", "max_output_tokens"):
        require_non_negative_int(escalation.get(field), f"frontier_escalation.{field}")
    worker_budget = policy.get("worker_max_budget_usd")
    if not isinstance(worker_budget, (int, float)) or isinstance(worker_budget, bool) or worker_budget <= 0:
        raise ContractError("worker_max_budget_usd must be positive")
    return policy


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


def validate_schema(instance: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Validate the JSON-Schema subset used by bundled contracts."""
    if "const" in schema and instance != schema["const"]:
        raise ContractError(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise ContractError(f"{path} is not in the allowed enum")
    expected_type = schema.get("type")
    type_ok = {
        "object": isinstance(instance, dict),
        "array": isinstance(instance, list),
        "string": isinstance(instance, str),
        "integer": isinstance(instance, int) and not isinstance(instance, bool),
        "number": isinstance(instance, (int, float)) and not isinstance(instance, bool),
        "boolean": isinstance(instance, bool),
        "null": instance is None,
    }.get(expected_type, True)
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
        if "minimum" in schema and instance < schema["minimum"]:
            raise ContractError(f"{path} is below minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            raise ContractError(f"{path} is above maximum")


def validate_supported_schema(schema: Any, path: str = "$") -> None:
    """Reject schema features the bundled deterministic validator cannot enforce."""
    if not isinstance(schema, dict):
        raise ContractError(f"{path} schema must be an object")
    supported = {
        "$schema", "title", "description", "type", "properties", "required",
        "additionalProperties", "items", "enum", "const", "minLength",
        "pattern", "minimum", "maximum", "maxLength",
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
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
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
        record = json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
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
            if line.strip() and json.loads(line).get(key) == value:
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
    entries = [json.loads(line) for line in audit.read_text().splitlines() if line.strip()] if audit.exists() else []
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
    if args.action in {"waive_acceptance", "override_acceptance"}:
        if not args.candidate or not args.tier:
            raise ContractError("waiver actions require --candidate and --tier")
        candidate = Path(args.candidate).resolve()
        contract_path = plan_dir / "state" / "evaluator_contract.json"
        details.update({
            "candidate_path": str(candidate),
            "candidate_sha256": sha256_file(candidate),
            "evaluator_contract_sha256": sha256_file(contract_path),
            "tier": args.tier,
            "scope": "negative_result" if args.negative_result else "acceptance_override",
        })
        if args.negative_result and args.tier != "arxiv":
            raise ContractError("negative-result waiver is arxiv-only")
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
        if current_state in {"COMPLETED", "FAILED"} and desired != current_state:
            raise ContractError(f"worker terminal status is monotonic: {current_state}")
        current.update(updates)
        current["status"] = desired
        current["updated_at"] = utc_now()
        atomic_write_json(path, current)
        return current


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
            if journal.get("phase") == "COMMITTED":
                raise ContractError("human action record was already applied")
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
            if action in {"waive_acceptance", "override_acceptance"}:
                required = {"candidate_path", "candidate_sha256", "evaluator_contract_sha256", "tier", "scope", "reason"}
                if not required.issubset(details):
                    raise ContractError(f"waiver details missing: {sorted(required - set(details))}")
                if sha256_file(Path(details["candidate_path"])) != details["candidate_sha256"]:
                    raise ContractError("waiver candidate hash mismatch")
                if sha256_file(plan_dir / "state" / "evaluator_contract.json") != details["evaluator_contract_sha256"]:
                    raise ContractError("waiver evaluator contract hash mismatch")
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
            update_worker_status(plan_dir, run_id, "CANCELLED", {
                "completed_at": receipt["applied_at"], "authority_record_id": record["record_id"],
            })
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
        return {"ok": True, "recovered": was_recovery, "receipt": receipt}


def require_transition_evidence(
    plan_dir: Path, transition_name: str, role_paths: dict[str, Path],
) -> dict[str, Any]:
    receipt = check_transition_receipt(plan_dir, plan_identity(plan_dir), transition_name)
    _, request = load_request(plan_dir, receipt["request_id"])
    by_role = {item["purpose"]: item for item in request["context_manifest"]}
    for role, path in role_paths.items():
        item = by_role.get(role)
        if item is None or Path(item["path"]).resolve() != path.resolve() or item["sha256"] != sha256_file(path):
            raise ContractError(f"{transition_name} evidence does not bind role {role}")
    return receipt


def command_run_evaluator(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    evaluator = Path(args.evaluator).resolve()
    evidence = Path(args.evidence).resolve()
    candidate = Path(args.candidate).resolve()
    require_transition_evidence(plan_dir, "freeze_evaluator", {
        "evaluator": evaluator, "evidence_manifest": evidence,
    })
    if not 1 <= args.timeout <= 86400:
        raise ContractError("evaluator timeout must be between 1 and 86400")
    command = [sys.executable, str(evaluator), "--evidence", str(evidence), "--candidate", str(candidate)]
    try:
        proc = subprocess.run(command, cwd=plan_dir, capture_output=True, text=True, timeout=args.timeout)
    except subprocess.TimeoutExpired as exc:
        raise ContractError("frozen evaluator timed out") from exc
    if proc.returncode != 0:
        raise ContractError(f"frozen evaluator failed with exit {proc.returncode}: {proc.stderr[:300]}")
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError("frozen evaluator output is not JSON") from exc
    if not isinstance(result, dict) or set(result) != {"metric", "value"}:
        raise ContractError("frozen evaluator must output exactly metric and value")
    if not isinstance(result["metric"], str) or not result["metric"]:
        raise ContractError("evaluator metric must be a non-empty string")
    if isinstance(result["value"], bool) or not isinstance(result["value"], (int, float)):
        raise ContractError("evaluator value must be numeric")
    run_id = f"evr_{uuid.uuid4().hex}"
    receipt = {
        "schema_version": 1, "run_id": run_id, "purpose": args.purpose,
        "plan_id": plan_identity(plan_dir), "evaluator_path": str(evaluator),
        "evaluator_sha256": sha256_file(evaluator), "evidence_path": str(evidence),
        "evidence_sha256": sha256_file(evidence), "candidate_path": str(candidate),
        "candidate_sha256": sha256_file(candidate), "metric": result["metric"],
        "value": result["value"], "stdout_sha256": hashlib.sha256(proc.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(proc.stderr.encode()).hexdigest(),
        "exit_code": proc.returncode, "python": sys.executable, "completed_at": utc_now(),
    }
    target = plan_dir / "state" / "evaluator_runs" / f"{run_id}.json"
    atomic_write_json(target, receipt, immutable=True)
    return {"ok": True, "execution_receipt": str(target), **receipt}


def load_evaluator_run(plan_dir: Path, path: Path) -> dict[str, Any]:
    run = read_json(path)
    canonical = plan_dir / "state" / "evaluator_runs" / f"{run.get('run_id', '')}.json"
    if path.resolve() != canonical.resolve() or run.get("plan_id") != plan_identity(plan_dir):
        raise ContractError("evaluator execution receipt is not canonical for this plan")
    for field in ("evaluator", "evidence", "candidate"):
        artifact = Path(run[f"{field}_path"])
        if sha256_file(artifact) != run[f"{field}_sha256"]:
            raise ContractError(f"evaluator execution {field} hash changed")
    if run.get("exit_code") != 0:
        raise ContractError("evaluator execution did not complete successfully")
    return run


def command_freeze_evaluator(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    target = plan_dir / "state" / "evaluator_contract.json"
    if target.exists():
        raise ContractError("evaluator contract is already frozen")
    run = load_evaluator_run(plan_dir, Path(args.execution_receipt).resolve())
    if run.get("purpose") != "calibration":
        raise ContractError("evaluator freeze requires a calibration execution receipt")
    evaluator = Path(run["evaluator_path"])
    evidence = Path(run["evidence_path"])
    require_transition_evidence(plan_dir, "freeze_evaluator", {
        "evaluator": evaluator, "evidence_manifest": evidence,
        "calibration_candidate": Path(run["candidate_path"]),
    })
    if args.operator not in {"gte", "lte"}:
        raise ContractError("operator must be gte or lte")
    contract = {
        "schema_version": 1,
        "evaluator_sha256": sha256_file(evaluator),
        "evidence_sha256": sha256_file(evidence),
        "evaluator_path": str(evaluator),
        "evidence_path": str(evidence),
        "metric": run["metric"],
        "operator": args.operator,
        "threshold": args.threshold,
        "calibration_execution_sha256": sha256_file(Path(args.execution_receipt).resolve()),
        "calibration_value": run["value"],
        "frozen_at": utc_now(),
    }
    contract["contract_sha256"] = sha256_json(contract)
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
    run_path = Path(args.execution_receipt).resolve()
    run = load_evaluator_run(plan_dir, run_path)
    if run.get("purpose") != "candidate":
        raise ContractError("candidate verdict requires a candidate evaluator execution")
    for field in ("evaluator_sha256", "evidence_sha256", "metric"):
        if run[field] != contract[field]:
            raise ContractError(f"evaluator execution {field} mismatch")
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
        raise ContractError("candidate verdict is already recorded")
    atomic_write_json(target, verdict, immutable=True)
    append_jsonl(plan_dir / "state" / "evaluator_audit.jsonl", {
        "ts": utc_now(), "candidate_id": verdict["candidate_id"], "verdict_sha256": sha256_file(target),
        "execution_receipt_sha256": verdict["execution_receipt_sha256"],
    })
    return {"ok": True, "verdict_path": str(target), "verdict_sha256": sha256_file(target)}


def transition_receipt_path(plan_dir: Path, transition_name: str) -> Path:
    return plan_dir / "state" / "frontier" / "transitions" / f"{transition_name}.json"


def check_transition_receipt(plan_dir: Path, plan_id: str, name: str) -> dict[str, Any]:
    receipt = read_json(transition_receipt_path(plan_dir, name))
    if receipt.get("plan_id") != plan_id or receipt.get("transition") != name:
        raise ContractError("dependent transition receipt correlation mismatch")
    request_path, request = load_request(plan_dir, receipt["request_id"])
    response_path = request_dir(plan_dir, receipt["request_id"]) / "response.json"
    if receipt.get("request_sha256") != sha256_file(request_path):
        raise ContractError("dependent transition request hash changed")
    if receipt.get("response_sha256") != sha256_file(response_path):
        raise ContractError("dependent transition response hash changed")
    context_hash = sha256_json(request["context_manifest"])
    if receipt.get("context_manifest_sha256") != context_hash:
        raise ContractError("dependent transition context hash changed")
    verify_manifest_items(request["context_manifest"], base_dir=plan_dir)
    return receipt


def command_check_writing_gate(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    if bool(args.verdict) == bool(args.waiver):
        raise ContractError("writing gate requires exactly one of --verdict or --waiver")
    transition_receipt = check_transition_receipt(plan_dir, plan_identity(plan_dir), "start_writing")
    source: str
    authority_path: Path
    if args.verdict:
        verdict_path = Path(args.verdict).resolve()
        verdict = read_json(verdict_path)
        stored = plan_dir / "state" / "evaluator_verdicts" / f"{verdict.get('candidate_id', '')}.json"
        if stored.resolve() != verdict_path or verdict.get("verdict") != "PASS":
            raise ContractError("writing gate requires a stored validated PASS verdict")
        contract = read_json(plan_dir / "state" / "evaluator_contract.json")
        contract_body = {key: value for key, value in contract.items() if key != "contract_sha256"}
        if contract.get("contract_sha256") != sha256_json(contract_body):
            raise ContractError("frozen evaluator contract hash changed")
        if verdict.get("contract_sha256") != contract["contract_sha256"]:
            raise ContractError("verdict evaluator contract mismatch")
        if verdict.get("metric") != contract["metric"] or verdict.get("threshold") != contract["threshold"]:
            raise ContractError("verdict metric or threshold changed")
        passed = verdict.get("value") >= contract["threshold"] if contract["operator"] == "gte" else verdict.get("value") <= contract["threshold"]
        if not passed:
            raise ContractError("stored PASS no longer satisfies the frozen threshold")
        if sha256_file(Path(verdict["candidate_path"])) != verdict["candidate_sha256"]:
            raise ContractError("candidate artifact hash changed")
        if sha256_file(Path(contract["evaluator_path"])) != verdict["evaluator_sha256"]:
            raise ContractError("evaluator hash changed")
        if sha256_file(Path(contract["evidence_path"])) != verdict["evidence_sha256"]:
            raise ContractError("evidence hash changed")
        require_transition_evidence(plan_dir, "start_writing", {
            "candidate": Path(verdict["candidate_path"]),
            "evaluator_verdict": verdict_path,
            "evaluator_contract": plan_dir / "state" / "evaluator_contract.json",
        })
        source, authority_path = "validated_verdict", verdict_path
    else:
        waiver_path = Path(args.waiver).resolve()
        waiver = validate_applied_action_receipt(plan_dir, waiver_path, "waive_acceptance")
        details = waiver["details"]
        if details.get("tier") != args.tier:
            raise ContractError("waiver tier does not match writing tier")
        candidate = Path(details["candidate_path"])
        contract_path = plan_dir / "state" / "evaluator_contract.json"
        if sha256_file(candidate) != details.get("candidate_sha256"):
            raise ContractError("waiver candidate hash changed")
        if sha256_file(contract_path) != details.get("evaluator_contract_sha256"):
            raise ContractError("waiver evaluator contract hash changed")
        negative = details.get("scope") == "negative_result"
        if negative and args.tier != "arxiv":
            raise ContractError("negative-result waiver is arxiv-only")
        source, authority_path = "applied_waiver_receipt", Path(waiver["receipt_path"])
    audit = {
        "schema_version": 1, "plan_id": plan_identity(plan_dir), "tier": args.tier,
        "source": source, "authority_path": str(authority_path),
        "authority_sha256": sha256_file(authority_path),
        "start_writing_receipt_sha256": sha256_file(transition_receipt_path(plan_dir, "start_writing")),
        "checked_at": utc_now(),
    }
    audit["decision_sha256"] = sha256_json({key: value for key, value in audit.items() if key != "checked_at"})
    append_jsonl_once(plan_dir / "state" / "writing_gate_audit.jsonl", "decision_sha256", audit["decision_sha256"], audit)
    return {"ok": True, "tier": args.tier, "source": source, "audit": audit,
            "transition_request_id": transition_receipt["request_id"]}


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
        "seen": [],
        "scientific_pivot_threshold": threshold,
    }


def command_record_failure(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    if args.failure_class not in FAILURE_CLASSES:
        raise ContractError("unsupported failure class")
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
        fingerprint = sha256_json(direction)
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
        key = f"{args.failure_class}:{fingerprint}"
        if key in state.get("seen", []):
            return {"ok": True, "idempotent": True, "failure_class": args.failure_class, "state": state}
        state.setdefault("seen", []).append(key)
        count_key = f"{args.failure_class}_count"
        state[count_key] = int(state.get(count_key, 0)) + 1
        if args.failure_class == "scientific_no_improvement":
            state.setdefault("distinct_scientific_fingerprints", []).append(fingerprint)
            state.setdefault("direction_registry", {})[fingerprint] = {
                "descriptor": direction, "verdict_path": str(verdict_path),
                "verdict_sha256": sha256_file(verdict_path), "recorded_at": utc_now(),
            }
        state["updated_at"] = utc_now()
        atomic_write_json(target, state)
        append_jsonl(plan_dir / "state" / "failure_events.jsonl", {
            "ts": utc_now(), "class": args.failure_class, "fingerprint": fingerprint,
            "source": args.source, "direction": direction,
        })
    return {"ok": True, "idempotent": False, "failure_class": args.failure_class, "state": state}


def pivot_eligibility(plan_dir: Path) -> dict[str, Any]:
    target = plan_dir / "state" / "failure_state.json"
    state = read_json(target) if target.exists() else failure_state_default(plan_dir)
    expected_threshold = failure_state_default(plan_dir)["scientific_pivot_threshold"]
    if state.get("scientific_pivot_threshold") != expected_threshold:
        raise ContractError("scientific pivot threshold changed from the frozen policy")
    distinct = len(set(state.get("distinct_scientific_fingerprints", [])))
    threshold = expected_threshold
    return {"eligible": distinct >= threshold, "distinct_scientific_failures": distinct, "threshold": threshold}


def command_pivot_eligibility(args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, **pivot_eligibility(Path(args.plan_dir).resolve())}


def command_apply_structural_pivot(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    if not pivot_eligibility(plan_dir)["eligible"]:
        raise ContractError("structural pivot threshold is not satisfied")
    proposal_path = Path(args.proposal).resolve()
    proposal = read_json(proposal_path)
    require_transition_evidence(plan_dir, "authorize_structural_pivot", {"pivot_proposal": proposal_path})
    direction = proposal.get("direction")
    if not isinstance(direction, dict) or set(direction) != DIRECTION_FIELDS:
        raise ContractError("pivot proposal requires a complete direction descriptor")
    normalized = {
        key: " ".join(value.strip().lower().split()) if isinstance(value, str) else value
        for key, value in sorted(direction.items())
    }
    if not all(isinstance(value, str) and value for value in normalized.values()):
        raise ContractError("pivot direction fields must be non-empty strings")
    direction_hash = sha256_json(normalized)
    failure_state = read_json(plan_dir / "state" / "failure_state.json")
    if direction_hash in failure_state.get("direction_registry", {}):
        raise ContractError("pivot direction duplicates a failed scientific direction")
    receipt = {
        "schema_version": 1, "plan_id": plan_identity(plan_dir), "direction": normalized,
        "direction_sha256": direction_hash, "proposal_path": str(proposal_path),
        "proposal_sha256": sha256_file(proposal_path),
        "frontier_receipt_sha256": sha256_file(transition_receipt_path(plan_dir, "authorize_structural_pivot")),
        "applied_at": utc_now(),
    }
    target = plan_dir / "state" / "structural_pivots" / f"pivot_{direction_hash[:24]}.json"
    if target.exists():
        raise ContractError("structural pivot was already applied")
    atomic_write_json(target, receipt, immutable=True)
    append_jsonl(plan_dir / "state" / "structural_pivot_audit.jsonl", receipt)
    return {"ok": True, "pivot_receipt": str(target), **receipt}


def command_resolve_acceptance_dispute(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    resolution_path = Path(args.resolution).resolve()
    resolution = read_json(resolution_path)
    require_transition_evidence(plan_dir, "resolve_acceptance_dispute", {"dispute_record": resolution_path})
    if set(resolution) != {"candidate_id", "resolution", "rationale"}:
        raise ContractError("dispute resolution requires exactly candidate_id, resolution, rationale")
    if resolution["resolution"] not in {"accept", "reject", "rerun"}:
        raise ContractError("invalid dispute resolution")
    receipt = {
        "schema_version": 1, "plan_id": plan_identity(plan_dir), **resolution,
        "resolution_path": str(resolution_path), "resolution_sha256": sha256_file(resolution_path),
        "frontier_receipt_sha256": sha256_file(transition_receipt_path(plan_dir, "resolve_acceptance_dispute")),
        "resolved_at": utc_now(),
    }
    target = plan_dir / "state" / "acceptance_disputes" / f"{resolution['candidate_id']}.json"
    if target.exists():
        raise ContractError("acceptance dispute was already resolved")
    atomic_write_json(target, receipt, immutable=True)
    return {"ok": True, "resolution_receipt": str(target), **receipt}


def command_init_policy(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    target = policy_path(plan_dir)
    if target.exists():
        raise ContractError(f"frozen model policy already exists: {target}")
    require_non_negative_int(args.max_frontier_calls, "max_frontier_calls")
    require_non_negative_int(args.max_frontier_input_tokens, "max_frontier_input_tokens")
    require_non_negative_int(args.max_frontier_output_tokens, "max_frontier_output_tokens")
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
    if args.worker_max_budget_usd <= 0:
        raise ContractError("worker_max_budget_usd must be positive")
    atomic_write_json(target, policy, immutable=True)
    load_policy(plan_dir)
    return {"ok": True, "policy_path": str(target)}


def normalize_declared_output(plan_dir: Path, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {"artifact_id", "path", "content_field", "max_bytes"}:
        raise ContractError("artifact_outputs entries require exactly artifact_id, path, content_field, max_bytes")
    if not all(isinstance(raw.get(key), str) and raw[key] for key in ("artifact_id", "path", "content_field")):
        raise ContractError("artifact output identifiers and paths must be non-empty strings")
    if isinstance(raw.get("max_bytes"), bool) or not isinstance(raw.get("max_bytes"), int) or not 1 <= raw["max_bytes"] <= 100_000_000:
        raise ContractError("artifact output max_bytes must be in 1..100000000")
    path = normalize_owned_path(plan_dir, raw["path"])
    cursor = path.parent
    while cursor != plan_dir.parent:
        if cursor.is_symlink():
            raise ContractError("artifact output path contains a symlink parent")
        if cursor == plan_dir:
            break
        cursor = cursor.parent
    return {**raw, "path": str(path)}


def validate_worker_artifact_proposals(
    result: dict[str, Any], declarations: list[dict[str, Any]],
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
        if len(encoded) > declaration["max_bytes"]:
            raise ContractError("worker artifact exceeds declared max_bytes")
        digest = hashlib.sha256(encoded).hexdigest()
        if proposal.get("sha256") != digest:
            raise ContractError("worker artifact content hash mismatch")
        checked.append(proposal)
    return checked


def command_dispatch_worker(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
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
    inputs = verify_manifest_items(contract.get("inputs", []), base_dir=plan_dir)
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
    run_id = f"cwr_{uuid.uuid4().hex}"
    (plan_dir / "state" / "worker_runs").mkdir(parents=True, exist_ok=True)
    run_dir = worker_run_dir(plan_dir, run_id, must_exist=False)
    run_dir.mkdir(parents=True, exist_ok=False)
    prompt = json.dumps({
        "role": "bounded research worker",
        "authority": "artifact producer only; do not change plan lifecycle state",
        "task_id": task_id,
        "instruction": instruction,
        "inputs": inputs,
        "artifact_outputs": declarations,
        "artifact_contract": "return proposals only; the controller validates and promotes them",
    }, indent=2)
    cmd = [
        args.claude_bin, "-p", "--model", policy["worker_model"],
        "--output-format", "json", "--json-schema", json.dumps(output_schema),
        "--max-budget-usd", str(policy["worker_max_budget_usd"]),
        "--permission-mode", "dontAsk", "--tools", ",".join(allowed_tools),
        "--no-session-persistence",
    ]
    started = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "task_id": task_id,
        "status": "RUNNING",
        "worker_model": policy["worker_model"],
        "contract_path": str(contract_path),
        "contract_sha256": sha256_file(contract_path),
        "model_policy_sha256": sha256_file(policy_path(plan_dir)),
        "started_at": utc_now(),
    }
    atomic_write_json(run_dir / "status.json", started)
    try:
        proc = subprocess.run(
            cmd, input=prompt, cwd=plan_dir, capture_output=True, text=True,
            timeout=args.timeout,
        )
    except FileNotFoundError as exc:
        update_worker_status(plan_dir, run_id, "FAILED", {"failure": "claude_not_found", "completed_at": utc_now()})
        raise ContractError(f"Claude Code executable not found: {args.claude_bin}") from exc
    except subprocess.TimeoutExpired as exc:
        update_worker_status(plan_dir, run_id, "PAUSED", {"failure": "worker_timeout", "completed_at": utc_now()})
        raise ContractError(f"Claude worker timed out after {args.timeout}s") from exc
    (run_dir / "transport.stdout").write_text(proc.stdout)
    (run_dir / "transport.stderr").write_text(proc.stderr)
    if proc.returncode != 0:
        update_worker_status(plan_dir, run_id, "FAILED", {"exit_code": proc.returncode, "completed_at": utc_now()})
        raise ContractError(f"Claude worker failed with exit {proc.returncode}: {proc.stderr[:300]}")
    try:
        result = extract_structured_claude_output(proc.stdout)
        validate_schema(result, output_schema)
        if not isinstance(result, dict):
            raise ContractError("worker structured output must be an object")
        validate_worker_artifact_proposals(result, declarations)
        result_path = run_dir / "result.json"
        atomic_write_json(result_path, {"result": result, "artifact_outputs": declarations})
        completed = update_worker_status(plan_dir, run_id, "COMPLETED", {
            "completed_at": utc_now(), "result_path": str(result_path),
            "result_sha256": sha256_file(result_path),
        })
        if completed.get("status") == "CANCELLED":
            return {**completed, "ignored_result_path": str(result_path)}
        return completed
    except ContractError:
        update_worker_status(plan_dir, run_id, "FAILED", {"failure": "invalid_worker_output", "completed_at": utc_now()})
        raise


def command_promote_worker_artifacts(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    transition_receipt = check_transition_receipt(plan_dir, plan_identity(plan_dir), "approve_execution")
    status = read_json(worker_status_path(plan_dir, args.worker_run_id))
    if status.get("status") != "COMPLETED":
        raise ContractError("only COMPLETED worker runs can be promoted")
    contract_path = Path(status["contract_path"])
    result_path = Path(status["result_path"])
    if sha256_file(contract_path) != status["contract_sha256"] or sha256_file(result_path) != status["result_sha256"]:
        raise ContractError("worker contract or result hash changed")
    contract = read_json(contract_path)
    declarations = [normalize_declared_output(plan_dir, item) for item in contract["artifact_outputs"]]
    envelope = read_json(result_path)
    proposals = validate_worker_artifact_proposals(envelope["result"], declarations)
    promoted: list[dict[str, Any]] = []
    for proposal in proposals:
        target = Path(proposal["path"])
        if target.exists():
            raise ContractError(f"artifact promotion refuses overwrite: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
        temporary.write_text(proposal["content"])
        os.replace(temporary, target)
        if sha256_file(target) != proposal["sha256"]:
            raise ContractError("promoted artifact hash mismatch")
        promoted.append({"artifact_id": proposal["artifact_id"], "path": str(target), "sha256": proposal["sha256"]})
    receipt = {
        "schema_version": 1, "plan_id": plan_identity(plan_dir), "worker_run_id": args.worker_run_id,
        "contract_sha256": status["contract_sha256"], "result_sha256": status["result_sha256"],
        "approve_execution_receipt_sha256": sha256_file(transition_receipt_path(plan_dir, "approve_execution")),
        "artifacts": promoted, "promoted_at": utc_now(),
    }
    target = worker_run_dir(plan_dir, args.worker_run_id) / "promotion-receipt.json"
    atomic_write_json(target, receipt, immutable=True)
    return {"ok": True, "promotion_receipt": str(target), **receipt}


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
    receipt = {
        "schema_version": 1, "worker_run_id": args.worker_run_id,
        "message": args.message, "authority": "advisory_only", "ts": utc_now(),
    }
    append_jsonl(worker_status_path(plan_dir, args.worker_run_id).parent / "messages.jsonl", receipt)
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
    if not path.is_file():
        raise ContractError("resource must be an existing regular non-symlink file")
    expected_token = hashlib.sha256(
        f"{manifest['plan_id']}\0{path}\0{resource.get('ownership_nonce', '')}".encode()
    ).hexdigest()
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
        json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()
    ] if audit_path.exists() else []
    audit = next((item for item in audit_entries if item.get("record_id") == authorization.get("record_id")), None)
    if audit is None or any(
        audit.get(field) != authorization.get(field)
        for field in ("plan_id", "action", "record_id", "record_sha256", "resource_id")
    ):
        raise ContractError("cleanup authorization does not match the authenticated audit")
    path.unlink()
    receipt = {
        "schema_version": 1, "plan_id": manifest["plan_id"], "resource_id": args.resource_id,
        "path": str(path), "authorization_record_id": authorization["record_id"], "removed_at": utc_now(),
    }
    append_jsonl(plan_dir / "state" / "cleanup_receipts.jsonl", receipt)
    return {"ok": True, "receipt": receipt}


def frontier_root(plan_dir: Path) -> Path:
    return plan_dir / "state" / "frontier"


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
        ledger = read_json(ledger_path) if ledger_path.exists() else {
            "schema_version": SCHEMA_VERSION,
            "reserved_calls": 0,
            "reserved_input_tokens": 0,
            "reserved_output_tokens": 0,
            "request_ids": [],
        }
        if request["request_id"] in ledger["request_ids"]:
            return ledger
        limits = policy["frontier_escalation"]
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


def command_create_request(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    load_policy(plan_dir)
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
    if args.checkpoint == "CP-03" and not pivot_eligibility(plan_dir)["eligible"]:
        raise ContractError("CP-03 requires distinct scientific pivot eligibility")
    if not 1 <= args.deadline_seconds <= 86400:
        raise ContractError("deadline_seconds must be between 1 and 86400")
    request_id = args.request_id or f"far_{uuid.uuid4().hex}"
    target_dir = request_dir(plan_dir, request_id)
    if target_dir.exists():
        existing = read_json(target_dir / "request.json")
        return {"ok": True, "idempotent": True, "request_id": request_id, "request_path": str(target_dir / "request.json"), "request_sha256": sha256_file(target_dir / "request.json"), "checkpoint": existing["checkpoint"]}
    manifest_items = []
    for raw in args.artifact:
        path_text, separator, purpose = raw.partition("::")
        path = Path(path_text)
        if not path.is_absolute():
            path = plan_dir / path
        manifest_items.append({"path": str(path.resolve()), "purpose": purpose if separator else "checkpoint evidence"})
    manifest = verify_manifest_items(manifest_items, base_dir=plan_dir)
    required_roles = CHECKPOINT_EVIDENCE_PROFILES[(args.checkpoint, subtype)]
    roles = [item["purpose"] for item in manifest]
    if len(roles) != len(set(roles)):
        raise ContractError("frontier checkpoint evidence roles must be unique")
    if set(roles) != required_roles:
        raise ContractError(
            f"frontier checkpoint evidence profile mismatch; missing={sorted(required_roles - set(roles))}, "
            f"extra={sorted(set(roles) - required_roles)}"
        )
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
        "evidence_profile_version": 1,
        "constraints": args.constraint,
        "budget_reservation": {"call": 1, "max_input_tokens": args.max_input_tokens, "max_output_tokens": args.max_output_tokens},
        "created_at": utc_now(),
        "deadline_at": (
            datetime.now(timezone.utc).replace(microsecond=0)
            + timedelta(seconds=args.deadline_seconds)
        ).isoformat().replace("+00:00", "Z"),
    }
    if not request["plan_id"] or not request["objective"] or not request["decision_required"]:
        raise ContractError("plan_id, objective, and decision_required are required")
    manifest_path = plan_dir / "resource_manifest.json"
    if manifest_path.exists() and request["plan_id"] != plan_identity(plan_dir):
        raise ContractError("frontier request plan_id does not match resource manifest")
    target_dir.mkdir(parents=True, exist_ok=False)
    request_path = target_dir / "request.json"
    atomic_write_json(request_path, request, immutable=True)
    request_hash = sha256_file(request_path)
    transition(
        plan_dir, request_id, "CREATED", checkpoint=args.checkpoint,
        request_sha256=request_hash,
        context_manifest_sha256=sha256_json(request["context_manifest"]),
        deadline_at=request["deadline_at"],
        model_policy_sha256=sha256_file(policy_path(plan_dir)),
    )
    return {"ok": True, "request_id": request_id, "request_path": str(request_path), "request_sha256": request_hash}


def load_request(plan_dir: Path, request_id: str) -> tuple[Path, dict[str, Any]]:
    path = request_dir(plan_dir, request_id) / "request.json"
    request = read_json(path)
    if request.get("request_id") != request_id:
        raise ContractError("request correlation mismatch")
    if request.get("checkpoint") not in CHECKPOINTS:
        raise ContractError("request checkpoint is not registered")
    verify_manifest_items(request.get("context_manifest"), base_dir=plan_dir)
    return path, request


def extract_usage(jsonl: str) -> dict[str, int]:
    best = {"input_tokens": 0, "output_tokens": 0}
    for line in jsonl.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
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
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    request_path, request = load_request(plan_dir, request_id)
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
    if response["blockers"]:
        raise ContractError("frontier response has unresolved blockers")
    if any(item.get("severity") == "critical" for item in response["findings"]):
        raise ContractError("frontier response has unresolved critical findings")
    evidence_authority = {item["path"] for item in request["context_manifest"]} | {
        item["sha256"] for item in request["context_manifest"]
    }
    for finding in response["findings"]:
        if not finding["evidence"] or any(item not in evidence_authority for item in finding["evidence"]):
            raise ContractError("frontier findings must cite frozen evidence paths or hashes")
    reservation = request["budget_reservation"]
    if response["usage"]["input_tokens"] > reservation["max_input_tokens"] or response["usage"]["output_tokens"] > reservation["max_output_tokens"]:
        raise ContractError("observed token use exceeds the request reservation")
    verify_manifest_items(request["context_manifest"], base_dir=plan_dir)
    return response, request, request_path


def reconcile_frontier_locked(plan_dir: Path, request_id: str) -> dict[str, Any]:
    run_dir = request_dir(plan_dir, request_id)
    current = read_json(status_path(plan_dir, request_id))
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
            raise ContractError("transport usage is unavailable")
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
        )
        return {"ok": True, **received}
    except ContractError as exc:
        transition(plan_dir, request_id, "INVALID", validation_error=str(exc))
        paused = transition(plan_dir, request_id, "PAUSED", failure="malformed_durable_response", validation_error=str(exc))
        raise ContractError(str(exc)) from None


def command_send_request(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    with request_send_lock(plan_dir, args.request_id):
        policy = load_policy(plan_dir)
        request_path, request = load_request(plan_dir, args.request_id)
        current = read_json(status_path(plan_dir, args.request_id))
        if current["state"] in {"RECEIVED", "VALIDATED", "APPLIED"}:
            return {"ok": True, "idempotent": True, **current}
        if current["state"] in {"SENT", "WAITING"}:
            return reconcile_frontier_locked(plan_dir, args.request_id)
        if current["state"] == "PAUSED":
            raise ContractError("paused frontier requests are never redelivered; reconcile or create a new attempt")
        if current["state"] not in {"CREATED", "BUDGET_RESERVED"}:
            raise ContractError(f"cannot send request from state {current['state']}")
        if parse_utc(request["deadline_at"]) <= datetime.now(timezone.utc):
            transition(plan_dir, args.request_id, "EXPIRED", failure="deadline_expired")
            transition(plan_dir, args.request_id, "PAUSED", failure="deadline_expired")
            raise ContractError("frontier request deadline expired")
        if current.get("model_policy_sha256") != sha256_file(policy_path(plan_dir)):
            transition(plan_dir, args.request_id, "PAUSED", failure="model_policy_hash_changed")
            raise ContractError("frozen model policy hash changed")
        estimated_input_tokens = estimate_frontier_input_tokens(request_path, request)
        if estimated_input_tokens > request["budget_reservation"]["max_input_tokens"]:
            transition(plan_dir, args.request_id, "PAUSED", failure="context_exceeds_input_reservation")
            raise ContractError("estimated input exceeds reservation")
        ledger = reserve_budget(plan_dir, request, policy)
        claim = uuid.uuid4().hex
        transition(plan_dir, args.request_id, "BUDGET_RESERVED", budget_snapshot=ledger, estimated_input_tokens=estimated_input_tokens)
        transition(plan_dir, args.request_id, "SENT", model_id=policy["frontier_model"], send_claim=claim)
        transition(plan_dir, args.request_id, "WAITING", transport="codex-cli", send_claim=claim)
        run_dir = request_dir(plan_dir, args.request_id)
        raw_response = run_dir / "response.raw.json"
        prompt = (
            "You are the sparse frontier advisor for a research Harness. Read the immutable request below, "
            "audit only the bounded evidence it names, and return exactly the required JSON schema.\n\n"
            + request_path.read_text()
        )
        cmd = [args.codex_bin, "exec", "-m", policy["frontier_model"], "-c",
               f"model_reasoning_effort={policy.get('frontier_reasoning_effort', 'xhigh')}",
               "--sandbox", "read-only", "--cd", str(plan_dir), "--output-schema", str(RESPONSE_SCHEMA),
               "--output-last-message", str(raw_response), "--json", "-"]
        try:
            proc = subprocess.run(cmd, input=prompt, cwd=plan_dir, capture_output=True, text=True, timeout=args.timeout)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            transition(plan_dir, args.request_id, "PAUSED", failure="transport_outcome_uncertain")
            raise ContractError(f"Codex transport outcome is uncertain: {exc}") from exc
        (run_dir / "transport.events.jsonl").write_text(proc.stdout)
        (run_dir / "transport.stderr").write_text(proc.stderr)
        if proc.returncode != 0:
            transition(plan_dir, args.request_id, "PAUSED", failure="transport_failed", exit_code=proc.returncode)
            raise ContractError(f"Codex transport failed with exit {proc.returncode}")
        return reconcile_frontier_locked(plan_dir, args.request_id)


def command_reconcile_request(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    with request_send_lock(plan_dir, args.request_id):
        current = read_json(status_path(plan_dir, args.request_id))
        if current["state"] not in {"SENT", "WAITING", "RECEIVED", "VALIDATED", "APPLIED"}:
            raise ContractError(f"cannot reconcile frontier request from state {current['state']}")
        return reconcile_frontier_locked(plan_dir, args.request_id)


def command_validate_response(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    request_path, request = load_request(plan_dir, args.request_id)
    current = read_json(status_path(plan_dir, args.request_id))
    if current["state"] in {"VALIDATED", "APPLIED"}:
        return {"ok": True, "idempotent": True, **current}
    if current["state"] != "RECEIVED":
        raise ContractError(f"cannot validate response from state {current['state']}")
    if parse_utc(request["deadline_at"]) <= datetime.now(timezone.utc):
        transition(plan_dir, args.request_id, "EXPIRED", failure="response_after_deadline")
        transition(plan_dir, args.request_id, "PAUSED", failure="response_after_deadline")
        raise ContractError("frontier response arrived after the frozen deadline")
    response_path = request_dir(plan_dir, args.request_id) / "response.json"
    try:
        validate_frontier_response_integrity(plan_dir, args.request_id, current, response_path)
    except ContractError as exc:
        transition(plan_dir, args.request_id, "INVALID", validation_error=str(exc))
        transition(plan_dir, args.request_id, "PAUSED", failure="response_invalid", validation_error=str(exc))
        raise
    transition(
        plan_dir, args.request_id, "VALIDATED", validated_response_path=str(response_path),
        validated_response_sha256=sha256_file(response_path),
        validated_request_sha256=sha256_file(request_path),
        validated_context_manifest_sha256=sha256_json(request["context_manifest"]), advisory_only=True,
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
        "advisory_only": True,
        "lifecycle_mutation": False,
        "controller_note": args.controller_note,
    }
    target = transition_receipt_path(plan_dir, args.dependent_transition)
    lock_path = frontier_root(plan_dir) / ".transition.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current = read_json(status_path(plan_dir, args.request_id))
        validate_frontier_response_integrity(plan_dir, args.request_id, current, response_path)
        if current.get("validated_response_sha256") != sha256_file(response_path):
            raise ContractError("validated response hash changed while applying")
        if target.exists():
            prior = read_json(target)
            if prior.get("request_id") != args.request_id:
                raise ContractError("dependent transition was already applied by another request")
            transition(plan_dir, args.request_id, "APPLIED", applied_event=prior)
            return {"ok": True, "idempotent": True, "request_id": args.request_id, "state": "APPLIED", "event": prior}
        atomic_write_json(target, event, immutable=True)
        append_jsonl(plan_dir / "state" / "controller_transitions.jsonl", event)
        transition(plan_dir, args.request_id, "APPLIED", applied_event=event)
    return {"ok": True, "request_id": args.request_id, "state": "APPLIED", "event": event}


def command_status(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    return read_json(status_path(plan_dir, args.request_id))


def command_assert_transition(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    receipt = check_transition_receipt(plan_dir, args.plan_id, args.transition)
    current = read_json(status_path(plan_dir, receipt["request_id"]))
    response_path = request_dir(plan_dir, receipt["request_id"]) / "response.json"
    validate_frontier_response_integrity(plan_dir, receipt["request_id"], current, response_path)
    if receipt.get("response_sha256") != sha256_file(response_path):
        raise ContractError("transition response hash changed")
    return {"ok": True, "receipt": receipt}


def command_expire_request(args: argparse.Namespace) -> dict[str, Any]:
    plan_dir = Path(args.plan_dir).resolve()
    _, request = load_request(plan_dir, args.request_id)
    now = parse_utc(args.now)
    current = read_json(status_path(plan_dir, args.request_id))
    if current["state"] in {"EXPIRED", "PAUSED"} and current.get("failure") == "deadline_expired":
        return {"ok": True, "idempotent": True, **current}
    if current["state"] not in {"CREATED", "BUDGET_RESERVED", "SENT", "WAITING"}:
        raise ContractError(f"cannot expire request from state {current['state']}")
    if now <= parse_utc(request["deadline_at"]):
        raise ContractError("request deadline has not passed")
    transition(plan_dir, args.request_id, "EXPIRED", expired_at=args.now, failure="deadline_expired")
    paused = transition(plan_dir, args.request_id, "PAUSED", expired_at=args.now, failure="deadline_expired")
    return {"ok": True, **paused}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-policy", help="freeze Claude/MiniMax and Codex budgets for a plan")
    init.add_argument("--plan-dir", required=True)
    init.add_argument("--worker-model", required=True)
    init.add_argument("--worker-max-budget-usd", type=float, required=True)
    init.add_argument("--frontier-model", required=True)
    init.add_argument("--frontier-reasoning-effort", default="xhigh", choices=["low", "medium", "high", "xhigh", "max"])
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
    worker.set_defaults(handler=command_dispatch_worker)

    promote = sub.add_parser("promote-worker-artifacts")
    promote.add_argument("--plan-dir", required=True)
    promote.add_argument("--worker-run-id", required=True)
    promote.set_defaults(handler=command_promote_worker_artifacts)

    inspect = sub.add_parser("inspect-worker")
    inspect.add_argument("--plan-dir", required=True)
    inspect.add_argument("--worker-run-id", required=True)
    inspect.set_defaults(handler=command_inspect_worker)

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
    human.add_argument("--candidate")
    human.add_argument("--tier", choices=["arxiv", "conference", "journal-q1"])
    human.add_argument("--negative-result", action="store_true")
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
    freeze.add_argument("--operator", required=True, choices=["gte", "lte"])
    freeze.add_argument("--threshold", type=float, required=True)
    freeze.set_defaults(handler=command_freeze_evaluator)

    verdict = sub.add_parser("record-evaluator-verdict")
    verdict.add_argument("--plan-dir", required=True)
    verdict.add_argument("--execution-receipt", required=True)
    verdict.add_argument("--candidate-id", required=True)
    verdict.set_defaults(handler=command_record_evaluator_verdict)

    writing = sub.add_parser("check-writing-gate")
    writing.add_argument("--plan-dir", required=True)
    writing.add_argument("--tier", required=True, choices=["arxiv", "conference", "journal-q1"])
    writing.add_argument("--verdict")
    writing.add_argument("--waiver")
    writing.set_defaults(handler=command_check_writing_gate)

    failure = sub.add_parser("record-failure")
    failure.add_argument("--plan-dir", required=True)
    failure.add_argument("--class", dest="failure_class", required=True, choices=sorted(FAILURE_CLASSES))
    failure.add_argument("--fingerprint")
    failure.add_argument("--direction")
    failure.add_argument("--verdict")
    failure.add_argument("--source", required=True)
    failure.set_defaults(handler=command_record_failure)

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

    remove = sub.add_parser("remove-resource")
    remove.add_argument("--plan-dir", required=True)
    remove.add_argument("--resource-id", required=True)
    remove.add_argument("--ownership-token", required=True)
    remove.add_argument("--authorization", required=True)
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
    create.set_defaults(handler=command_create_request)

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
    assertion.set_defaults(handler=command_assert_transition)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = args.handler(args)
    except ContractError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 20 if args.command == "check-writing-gate" else 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
