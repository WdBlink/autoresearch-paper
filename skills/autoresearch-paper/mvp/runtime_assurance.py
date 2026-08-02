#!/usr/bin/env python3
"""Complete P6 L0/L1/L2 runtime assurance for the isolated MVP-0 loop.

This module owns runtime metadata only.  It never reads Research IR content,
judges scientific evidence, or invokes a model.  The Codex heartbeat remains
the model-bearing L1; this module makes its registration independently
observable and recoverable and binds it to Worker liveness evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

try:
    from . import automation_registration as automation
    from . import launchd_registration as launchd
except ImportError:  # pragma: no cover - direct script execution
    import automation_registration as automation  # type: ignore[no-redef]
    import launchd_registration as launchd  # type: ignore[no-redef]


ASSURANCE_VERSION = "mvp0-runtime-assurance/v1"
ACTIVATION_VERSION = "mvp0-runtime-activation/v1"
L0_OBSERVATION_VERSION = "mvp0-l0-observation/v1"
L2_CONTRACT_VERSION = "mvp0-l2-heartbeat-contract/v1"
L2_HEARTBEAT_VERSION = "mvp0-l2-heartbeat/v1"
WORKER_BINDING_VERSION = "mvp0-runtime-worker-binding/v1"
SNAPSHOT_VERSION = "mvp0-runtime-snapshot/v1"
SHUTDOWN_VERSION = "mvp0-runtime-shutdown/v1"
HEX64 = set("0123456789abcdef")


class AssuranceError(RuntimeError):
    """A fail-closed runtime-assurance contract error."""


class ProcessInspector(Protocol):
    def identity(self, pid: int) -> str | None: ...

    def terminate(self, pid: int) -> None: ...

    def kill(self, pid: int) -> None: ...


def _canonical_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise AssuranceError(f"value is not canonical JSON: {exc}") from exc
    return (text + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX64


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle, parse_constant=_reject_constant)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise AssuranceError(f"cannot read strict JSON from {path}: {exc}") from exc


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _atomic_write(path: Path, data: bytes, *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and (path.exists() or path.is_symlink()):
        raise AssuranceError(f"immutable runtime artifact already exists: {path}")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
        path.chmod(0o444 if immutable else 0o644)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json(path: Path, value: Any, *, immutable: bool = False) -> None:
    _atomic_write(path, _canonical_bytes(value), immutable=immutable)


def _write_immutable_idempotent(path: Path, data: bytes) -> bool:
    if path.exists() or path.is_symlink():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_mode & 0o777 != 0o444
            or path.read_bytes() != data
        ):
            raise AssuranceError(f"immutable runtime artifact collision: {path}")
        return True
    _atomic_write(path, data, immutable=True)
    return False


def _parse_time(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AssuranceError("timestamp must be an RFC3339 UTC string")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AssuranceError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise AssuranceError("timestamp must contain timezone information")
    return parsed.astimezone(timezone.utc)


def _milliseconds(value: str) -> int:
    return int(_parse_time(value).timestamp() * 1000)


def _assert_absolute_regular(path: Path, label: str, *, executable: bool = False) -> Path:
    if not path.is_absolute():
        raise AssuranceError(f"{label} path must be absolute")
    resolved = path.resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise AssuranceError(f"{label} must be an existing regular file")
    if executable and not os.access(resolved, os.X_OK):
        raise AssuranceError(f"{label} must be executable")
    return resolved


def _contract_path(store_dir: Path) -> Path:
    return store_dir / "assurance" / "runtime-contract.json"


def _activation_path(store_dir: Path) -> Path:
    return store_dir / "assurance" / "activation-receipt.json"


def _lifecycle_path(store_dir: Path) -> Path:
    return store_dir / "runtime" / "lifecycle.json"


def _load_contract(store_dir: Path) -> dict[str, Any]:
    value = _read_json(_contract_path(store_dir))
    if not isinstance(value, dict) or value.get("schema_version") != ASSURANCE_VERSION:
        raise AssuranceError("runtime assurance contract is invalid")
    return value


def _load_lifecycle(store_dir: Path) -> dict[str, Any]:
    value = _read_json(_lifecycle_path(store_dir))
    if not isinstance(value, dict) or value.get("state") not in {"ACTIVE", "PAUSED", "STOPPING", "STOPPED"}:
        raise AssuranceError("runtime lifecycle projection is invalid")
    return value


def _append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(_canonical_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o644)


def _publish_l0_observation(store_dir: Path, observation: dict[str, Any]) -> dict[str, Any]:
    fingerprint_value = {
        key: value
        for key, value in observation.items()
        if key not in {"observed_at", "deduplicated", "observation_sha256"}
    }
    fingerprint = _sha256_bytes(_canonical_bytes(fingerprint_value))
    index_path = store_dir / "assurance" / "l0-observations.jsonl"
    latest_path = store_dir / "assurance" / "l0-latest.json"
    latest = _read_json(latest_path) if latest_path.is_file() else None
    if isinstance(latest, dict) and latest.get("fingerprint") == fingerprint:
        returned = dict(latest["observation"])
        returned["deduplicated"] = True
        return returned
    payload = dict(observation)
    payload["deduplicated"] = False
    payload["fingerprint"] = fingerprint
    object_digest = _sha256_bytes(_canonical_bytes(payload))
    payload["observation_sha256"] = object_digest
    object_path = store_dir / "assurance" / "l0-objects" / f"{object_digest}.json"
    _write_immutable_idempotent(object_path, _canonical_bytes(payload))
    _append_jsonl(index_path, {"observation_path": str(object_path), "sha256": object_digest})
    _write_json(latest_path, {"fingerprint": fingerprint, "observation": payload})
    return payload


def _validate_intervals(
    *,
    l0_interval_seconds: int,
    l1_interval_seconds: int,
    l2_interval_seconds: int,
    heartbeat_stale_seconds: int,
) -> None:
    for label, value in (
        ("health interval", l0_interval_seconds),
        ("L1 interval", l1_interval_seconds),
        ("L2 interval", l2_interval_seconds),
        ("heartbeat stale threshold", heartbeat_stale_seconds),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise AssuranceError(f"{label} must be a positive integer")
    if l0_interval_seconds > 3600 or l0_interval_seconds * 2 > heartbeat_stale_seconds:
        raise AssuranceError(
            "health interval must be at most 3600 seconds and no greater than half the shortest stale threshold"
        )
    if l2_interval_seconds >= heartbeat_stale_seconds:
        raise AssuranceError("L2 interval must be below the heartbeat stale threshold")
    if l1_interval_seconds < 300 or l1_interval_seconds > 3600:
        raise AssuranceError("L1 interval must be between 300 and 3600 seconds")


def bootstrap_assurance(
    *,
    store_dir: Path,
    controller_id: str,
    target_thread_id: str,
    l1_automation_path: Path,
    l0_interval_seconds: int,
    l1_interval_seconds: int,
    l2_interval_seconds: int,
    heartbeat_stale_seconds: int,
    scheduler: launchd.Scheduler,
    launch_agents_dir: Path,
    python_executable: Path,
    now: str,
    l0_script_path: Path | None = None,
) -> dict[str, Any]:
    """Create and functionally prove one complete runtime-assurance generation."""

    store_dir = store_dir.resolve()
    l1_automation_path = l1_automation_path.resolve()
    launch_agents_dir = launch_agents_dir.resolve()
    _parse_time(now)
    _validate_intervals(
        l0_interval_seconds=l0_interval_seconds,
        l1_interval_seconds=l1_interval_seconds,
        l2_interval_seconds=l2_interval_seconds,
        heartbeat_stale_seconds=heartbeat_stale_seconds,
    )
    if _activation_path(store_dir).is_file():
        return verify_activation(store_dir=store_dir, scheduler=scheduler, now=now)
    parsed_l1 = automation.validate_thread_automation(
        l1_automation_path,
        expected_thread_id=target_thread_id,
        expected_controller_id=controller_id,
    )
    expected_interval = f"RRULE:FREQ=MINUTELY;INTERVAL={l1_interval_seconds // 60}"
    if parsed_l1["rrule"] != expected_interval:
        raise AssuranceError("L1 automation interval differs from the frozen interval")
    python_executable = _assert_absolute_regular(
        python_executable.resolve(), "Python executable", executable=True
    )
    script = (
        Path(__file__).resolve().parent / "l0_watchdog.py"
        if l0_script_path is None
        else l0_script_path.resolve()
    )
    script = _assert_absolute_regular(script, "L0 watchdog script")
    l1_bytes = l1_automation_path.read_bytes()
    l1_digest = _sha256_bytes(l1_bytes)
    l1_command_digest = launchd.command_sha256(["codex-thread-heartbeat", parsed_l1["prompt"]])
    l0_label = launchd.label_for_controller(controller_id)
    logs = store_dir / "runtime" / "logs"
    stdout_path = logs / "l0.stdout.log"
    stderr_path = logs / "l0.stderr.log"
    l0_argv = [
        str(python_executable),
        str(script),
        "--store-dir",
        str(store_dir),
        "--once",
    ]
    l0_command_digest = launchd.command_sha256(l0_argv)
    if l0_command_digest == l1_command_digest or l0_label == parsed_l1["id"]:
        raise AssuranceError("L0 and L1 identities must be distinct")
    plist_bytes = launchd.render_l0_plist(
        label=l0_label,
        program_arguments=l0_argv,
        interval_seconds=l0_interval_seconds,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )

    assurance_dir = store_dir / "assurance"
    backup_path = assurance_dir / "l1-automation.toml"
    plist_evidence_path = assurance_dir / f"{l0_label}.plist"
    installed_plist_path = launch_agents_dir / f"{l0_label}.plist"
    heartbeat_contract_path = assurance_dir / "l2-heartbeat-contract.json"
    runtime_contract = {
        "controller_id": controller_id,
        "created_at": now,
        "heartbeat_stale_seconds": heartbeat_stale_seconds,
        "l0": {
            "command_argv": l0_argv,
            "command_sha256": l0_command_digest,
            "interval_seconds": l0_interval_seconds,
            "plist_path": str(installed_plist_path),
            "scheduler_label": l0_label,
            "stderr_path": str(stderr_path),
            "stdout_path": str(stdout_path),
        },
        "l1": {
            "automation_id": parsed_l1["id"],
            "automation_path": str(l1_automation_path),
            "backup_path": str(backup_path),
            "command_sha256": l1_command_digest,
            "expected_sha256": l1_digest,
            "interval_seconds": l1_interval_seconds,
            "target_thread_id": target_thread_id,
        },
        "l2": {
            "contract_path": str(heartbeat_contract_path),
            "heartbeat_interval_seconds": l2_interval_seconds,
            "heartbeat_stale_seconds": heartbeat_stale_seconds,
        },
        "schema_version": ASSURANCE_VERSION,
    }
    heartbeat_contract = {
        "callback": "mvp.runtime_assurance.record_worker_heartbeat",
        "controller_id": controller_id,
        "created_at": now,
        "heartbeat_interval_seconds": l2_interval_seconds,
        "heartbeat_stale_seconds": heartbeat_stale_seconds,
        "model_dispatches": 0,
        "schema_version": L2_CONTRACT_VERSION,
    }
    resource_manifest = {
        "controller_id": controller_id,
        "owned_resources": [
            {"kind": "launchd", "layer": "L0", "identity": l0_label},
            {"kind": "codex_automation", "layer": "L1", "identity": parsed_l1["id"]},
        ],
        "schema_version": "mvp0-resource-manifest/v1",
    }

    for path in (logs, launch_agents_dir, assurance_dir, store_dir / "runtime"):
        path.mkdir(parents=True, exist_ok=True)
    stdout_path.touch(exist_ok=True)
    stderr_path.touch(exist_ok=True)
    _atomic_write(backup_path, l1_bytes, immutable=True)
    _atomic_write(plist_evidence_path, plist_bytes, immutable=True)
    _atomic_write(installed_plist_path, plist_bytes)
    _write_json(heartbeat_contract_path, heartbeat_contract, immutable=True)
    _write_json(_contract_path(store_dir), runtime_contract, immutable=True)
    _write_json(store_dir / "runtime" / "resource-manifest.json", resource_manifest, immutable=True)
    _write_json(
        _lifecycle_path(store_dir),
        {"controller_id": controller_id, "state": "ACTIVE", "updated_at": now},
    )
    scheduler.load(l0_label, installed_plist_path)
    if not scheduler.is_loaded(l0_label):
        raise AssuranceError("L0 service did not become loaded")

    l1_probe = {
        "due": False,
        "model_dispatches": 0,
        "observed_at": now,
        "registration_sha256": l1_digest,
    }
    l1_automation_path.unlink()
    l0_probe_result = run_l0_health_tick(store_dir=store_dir, scheduler=scheduler, now=now)
    if l0_probe_result.get("action") != "RESTORED_L1" or l1_automation_path.read_bytes() != l1_bytes:
        raise AssuranceError("L0 failed the exact L1 restoration probe")
    l0_probe = {
        "l1_restored": True,
        "l1_was_removed": True,
        "model_dispatches": l0_probe_result["model_dispatches"],
        "observation_sha256": l0_probe_result["observation_sha256"],
    }
    l2_probe = {
        "contract_sha256": _sha256_file(heartbeat_contract_path),
        "contract_verified": True,
        "model_dispatches": 0,
        "observed_at": now,
    }
    activation = {
        "activated_at": now,
        "controller_id": controller_id,
        "l0": {
            **runtime_contract["l0"],
            "loaded": True,
            "plist_sha256": _sha256_bytes(plist_bytes),
        },
        "l1": {
            **runtime_contract["l1"],
            "registered": True,
        },
        "l2": {
            **runtime_contract["l2"],
            "contract_sha256": _sha256_file(heartbeat_contract_path),
        },
        "probes": {"l0": l0_probe, "l1": l1_probe, "l2": l2_probe},
        "resource_manifest_path": str(store_dir / "runtime" / "resource-manifest.json"),
        "resource_manifest_sha256": _sha256_file(store_dir / "runtime" / "resource-manifest.json"),
        "schema_version": ACTIVATION_VERSION,
        "target_thread_id": target_thread_id,
    }
    _write_json(_activation_path(store_dir), activation, immutable=True)
    verified = verify_activation(store_dir=store_dir, scheduler=scheduler, now=now)
    return verified


def run_l0_health_tick(
    *,
    store_dir: Path,
    scheduler: launchd.Scheduler,
    now: str,
) -> dict[str, Any]:
    """Inspect only frozen runtime metadata and repair an exactly missing L1."""

    store_dir = store_dir.resolve()
    _parse_time(now)
    contract = _load_contract(store_dir)
    lifecycle = _load_lifecycle(store_dir)
    l0 = contract["l0"]
    l1 = contract["l1"]
    automation_path = Path(l1["automation_path"])
    backup_path = Path(l1["backup_path"])
    expected = backup_path.read_bytes()
    if _sha256_bytes(expected) != l1["expected_sha256"]:
        raise AssuranceError("L1 immutable backup hash mismatch")
    loaded = scheduler.is_loaded(l0["scheduler_label"])
    base = {
        "controller_id": contract["controller_id"],
        "l0_loaded": loaded,
        "l1_path": str(automation_path),
        "lifecycle_state": lifecycle["state"],
        "model_dispatches": 0,
        "observed_at": now,
        "schema_version": L0_OBSERVATION_VERSION,
    }
    if lifecycle["state"] != "ACTIVE":
        return _publish_l0_observation(
            store_dir,
            {**base, "action": "NOOP", "reason": f"LIFECYCLE_{lifecycle['state']}"},
        )
    if not loaded:
        return _publish_l0_observation(
            store_dir,
            {**base, "action": "RECOVERY_PROPOSED", "reason": "L0_NOT_LOADED"},
        )
    if not automation_path.exists():
        _atomic_write(automation_path, expected)
        return _publish_l0_observation(
            store_dir,
            {**base, "action": "RESTORED_L1", "reason": "L1_MISSING"},
        )
    if automation_path.is_symlink() or not automation_path.is_file():
        return _publish_l0_observation(
            store_dir,
            {**base, "action": "RECOVERY_PROPOSED", "reason": "L1_PATH_UNSAFE"},
        )
    observed = automation_path.read_bytes()
    if observed != expected:
        return _publish_l0_observation(
            store_dir,
            {**base, "action": "RECOVERY_PROPOSED", "reason": "L1_DRIFT"},
        )
    return _publish_l0_observation(
        store_dir,
        {**base, "action": "HEALTHY", "reason": None},
    )


def verify_activation(
    *,
    store_dir: Path,
    scheduler: launchd.Scheduler,
    now: str,
) -> dict[str, Any]:
    store_dir = store_dir.resolve()
    _parse_time(now)
    path = _activation_path(store_dir)
    activation = _read_json(path)
    if not isinstance(activation, dict) or activation.get("schema_version") != ACTIVATION_VERSION:
        raise AssuranceError("runtime activation receipt is invalid")
    if path.stat().st_mode & 0o777 != 0o444:
        raise AssuranceError("runtime activation receipt is mutable")
    contract = _load_contract(store_dir)
    if activation.get("controller_id") != contract.get("controller_id"):
        raise AssuranceError("runtime activation controller mismatch")
    l0 = activation["l0"]
    l1 = activation["l1"]
    l2 = activation["l2"]
    if l0["scheduler_label"] == l1["automation_id"] or l0["command_sha256"] == l1["command_sha256"]:
        raise AssuranceError("runtime activation L0/L1 identity collision")
    if not scheduler.is_loaded(l0["scheduler_label"]):
        raise AssuranceError("runtime activation L0 service is unloaded")
    automation_path = Path(l1["automation_path"])
    if not automation_path.is_file() or automation_path.is_symlink():
        raise AssuranceError("runtime activation L1 registration is missing")
    if _sha256_file(automation_path) != l1["expected_sha256"]:
        raise AssuranceError("runtime activation L1 registration drifted")
    automation.validate_thread_automation(
        automation_path,
        expected_thread_id=activation["target_thread_id"],
        expected_controller_id=activation["controller_id"],
    )
    contract_path = Path(l2["contract_path"])
    if not contract_path.is_file() or _sha256_file(contract_path) != l2["contract_sha256"]:
        raise AssuranceError("runtime activation L2 contract drifted")
    manifest_path = Path(activation["resource_manifest_path"])
    if not manifest_path.is_file() or _sha256_file(manifest_path) != activation["resource_manifest_sha256"]:
        raise AssuranceError("runtime activation resource manifest drifted")
    for layer in ("l0", "l1", "l2"):
        probe = activation["probes"].get(layer)
        if not isinstance(probe, dict) or probe.get("model_dispatches") != 0:
            raise AssuranceError(f"runtime activation {layer.upper()} probe is invalid")
    return {
        "activation_receipt_path": str(path),
        "activation_receipt_sha256": _sha256_file(path),
        "controller_id": activation["controller_id"],
        "status": "VERIFIED",
    }


def bind_worker(
    *,
    store_dir: Path,
    adapter_id: str,
    turn_id: str,
    session_id: str,
    worker_model: str,
    task_contract_sha256: str,
    process_id: int,
    process_identity: str,
    now: str,
) -> dict[str, Any]:
    store_dir = store_dir.resolve()
    _parse_time(now)
    try:
        uuid.UUID(session_id)
    except (ValueError, AttributeError) as exc:
        raise AssuranceError("Worker session_id must be a UUID") from exc
    if not _valid_sha(task_contract_sha256):
        raise AssuranceError("Worker task contract SHA-256 is invalid")
    if not isinstance(process_id, int) or isinstance(process_id, bool) or process_id <= 0:
        raise AssuranceError("Worker process_id must be positive")
    for label, value in (
        ("adapter_id", adapter_id),
        ("turn_id", turn_id),
        ("worker_model", worker_model),
        ("process_identity", process_identity),
    ):
        if not isinstance(value, str) or not value:
            raise AssuranceError(f"Worker {label} must be non-empty")
    contract = _load_contract(store_dir)
    binding = {
        "adapter_id": adapter_id,
        "bound_at": now,
        "controller_id": contract["controller_id"],
        "process_id": process_id,
        "process_identity": process_identity,
        "schema_version": WORKER_BINDING_VERSION,
        "session_id": session_id,
        "task_contract_sha256": task_contract_sha256,
        "turn_id": turn_id,
        "worker_model": worker_model,
    }
    digest = _sha256_bytes(_canonical_bytes(binding))
    binding_path = store_dir / "assurance" / "workers" / f"{digest}.json"
    _write_immutable_idempotent(binding_path, _canonical_bytes(binding))
    pointer = {
        "binding_path": str(binding_path),
        "binding_sha256": digest,
        "controller_id": contract["controller_id"],
    }
    _write_json(store_dir / "assurance" / "current-worker.json", pointer)
    return {**pointer, "worker_binding_path": str(binding_path)}


def record_worker_heartbeat(
    *,
    store_dir: Path,
    worker_binding_path: Path,
    sequence: int,
    session_id: str,
    process_id: int,
    process_identity: str,
    task_contract_sha256: str,
    observed_at: str,
) -> dict[str, Any]:
    store_dir = store_dir.resolve()
    _parse_time(observed_at)
    binding_path = worker_binding_path.resolve()
    workers_root = (store_dir / "assurance" / "workers").resolve()
    try:
        binding_path.relative_to(workers_root)
    except ValueError as exc:
        raise AssuranceError("Worker binding is outside the assurance store") from exc
    binding = _read_json(binding_path)
    if not isinstance(binding, dict) or binding.get("schema_version") != WORKER_BINDING_VERSION:
        raise AssuranceError("Worker binding is invalid")
    if binding_path.stat().st_mode & 0o777 != 0o444:
        raise AssuranceError("Worker binding is mutable")
    pointer = _read_json(store_dir / "assurance" / "current-worker.json")
    if pointer.get("binding_path") != str(binding_path) or pointer.get("binding_sha256") != _sha256_file(binding_path):
        raise AssuranceError("Worker binding is not the current active binding")
    for field, observed in (
        ("session_id", session_id),
        ("process_id", process_id),
        ("process_identity", process_identity),
        ("task_contract_sha256", task_contract_sha256),
    ):
        if binding[field] != observed:
            label = "session" if field == "session_id" else field.replace("_", " ")
            raise AssuranceError(f"Worker heartbeat {label} mismatch")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
        raise AssuranceError("Worker heartbeat sequence must be positive")
    binding_digest = _sha256_file(binding_path)
    root = store_dir / "assurance" / "l2-heartbeats" / binding_digest
    path = root / f"{sequence:08d}.json"
    predecessor_path = root / f"{sequence - 1:08d}.json" if sequence > 1 else None
    predecessor_digest = None
    if predecessor_path is not None:
        if not predecessor_path.is_file():
            raise AssuranceError("Worker heartbeat sequence is not contiguous")
        predecessor_digest = _sha256_file(predecessor_path)
    elif not path.exists() and any(root.glob("*.json")):
        raise AssuranceError("Worker heartbeat sequence cannot restart")
    heartbeat = {
        "adapter_id": binding["adapter_id"],
        "binding_sha256": binding_digest,
        "controller_id": binding["controller_id"],
        "observed_at": observed_at,
        "predecessor_sha256": predecessor_digest,
        "process_id": process_id,
        "process_identity": process_identity,
        "schema_version": L2_HEARTBEAT_VERSION,
        "sequence": sequence,
        "session_id": session_id,
        "task_contract_sha256": task_contract_sha256,
        "turn_id": binding["turn_id"],
        "worker_model": binding["worker_model"],
    }
    payload = _canonical_bytes(heartbeat)
    already = _write_immutable_idempotent(path, payload)
    if not already:
        _append_jsonl(
            store_dir / "assurance" / "l2-heartbeats.jsonl",
            {"heartbeat_path": str(path), "sha256": _sha256_bytes(payload)},
        )
    return {
        "already_applied": already,
        "heartbeat_path": str(path),
        "heartbeat_sha256": _sha256_bytes(payload),
        "sequence": sequence,
    }


def _latest_heartbeat(store_dir: Path, binding_digest: str) -> dict[str, Any] | None:
    root = store_dir / "assurance" / "l2-heartbeats" / binding_digest
    paths = sorted(root.glob("*.json")) if root.is_dir() else []
    if not paths:
        return None
    value = _read_json(paths[-1])
    if not isinstance(value, dict) or value.get("binding_sha256") != binding_digest:
        raise AssuranceError("latest Worker heartbeat is invalid")
    return value


def inspect_runtime(
    *,
    store_dir: Path,
    scheduler: launchd.Scheduler,
    processes: ProcessInspector | None,
    now: str,
) -> dict[str, Any]:
    """Return a fresh correlated snapshot without writing any state."""

    store_dir = store_dir.resolve()
    observed = _parse_time(now)
    contract = _load_contract(store_dir)
    lifecycle = _load_lifecycle(store_dir)
    l0 = contract["l0"]
    l1 = contract["l1"]
    automation_path = Path(l1["automation_path"])
    l1_present = automation_path.is_file() and not automation_path.is_symlink()
    l1_digest = _sha256_file(automation_path) if l1_present else None
    pointer_path = store_dir / "assurance" / "current-worker.json"
    l2: dict[str, Any] = {"binding": "MISSING", "freshness": "MISSING", "heartbeat_age_seconds": None}
    worker: dict[str, Any] = {"identity_agreement": "UNKNOWN", "process_id": None}
    if pointer_path.is_file():
        pointer = _read_json(pointer_path)
        binding_path = Path(pointer["binding_path"])
        binding = _read_json(binding_path)
        binding_digest = _sha256_file(binding_path)
        if binding_digest != pointer["binding_sha256"]:
            raise AssuranceError("current Worker pointer hash mismatch")
        heartbeat = _latest_heartbeat(store_dir, binding_digest)
        if heartbeat is None:
            l2 = {"binding": "BOUND", "freshness": "MISSING", "heartbeat_age_seconds": None}
        else:
            age = max(0.0, (observed - _parse_time(heartbeat["observed_at"])).total_seconds())
            freshness = "FRESH" if age < contract["heartbeat_stale_seconds"] else "STALE"
            l2 = {
                "binding": "BOUND",
                "freshness": freshness,
                "heartbeat_age_seconds": int(age),
                "heartbeat_sequence": heartbeat["sequence"],
                "heartbeat_sha256": _sha256_bytes(_canonical_bytes(heartbeat)),
            }
        actual_identity = processes.identity(binding["process_id"]) if processes is not None else None
        agreement = (
            "UNKNOWN"
            if processes is None
            else "MATCH"
            if actual_identity == binding["process_identity"]
            else "ABSENT"
            if actual_identity is None
            else "MISMATCH"
        )
        worker = {
            "adapter_id": binding["adapter_id"],
            "identity_agreement": agreement,
            "process_id": binding["process_id"],
            "session_id": binding["session_id"],
            "turn_id": binding["turn_id"],
        }
    return {
        "controller_id": contract["controller_id"],
        "l0": {
            "loaded": scheduler.is_loaded(l0["scheduler_label"]),
            "scheduler_label": l0["scheduler_label"],
        },
        "l1": {
            "agreement": "MATCH" if l1_digest == l1["expected_sha256"] else "MISSING" if l1_digest is None else "MISMATCH",
            "automation_id": l1["automation_id"],
            "path": str(automation_path),
        },
        "l2": l2,
        "lifecycle": lifecycle["state"],
        "observed_at": now,
        "schema_version": SNAPSHOT_VERSION,
        "scientific_state_mutations": 0,
        "worker": worker,
    }


def pause_runtime(
    *,
    store_dir: Path,
    scheduler: launchd.Scheduler,
    authority_id: str,
    now: str,
) -> dict[str, Any]:
    """Pause L1 research advancement while keeping L0 observation alive."""

    store_dir = store_dir.resolve()
    _parse_time(now)
    if not isinstance(authority_id, str) or not authority_id.strip():
        raise AssuranceError("pause authority_id must be non-empty")
    lifecycle = _load_lifecycle(store_dir)
    if lifecycle["state"] == "STOPPED":
        raise AssuranceError("a stopped runtime cannot be paused")
    if lifecycle["state"] == "STOPPING":
        raise AssuranceError("a stopping runtime cannot be paused")
    if lifecycle["state"] == "PAUSED":
        return {"authority_id": authority_id, "status": "PAUSED", "already_applied": True}
    verify_activation(store_dir=store_dir, scheduler=scheduler, now=now)
    contract = _load_contract(store_dir)
    l1_path = Path(contract["l1"]["automation_path"])
    paused_bytes = automation.with_status(
        l1_path.read_bytes(), status="PAUSED", updated_at_ms=_milliseconds(now)
    )
    _atomic_write(l1_path, paused_bytes)
    _write_json(
        _lifecycle_path(store_dir),
        {
            "authority_id": authority_id,
            "controller_id": contract["controller_id"],
            "state": "PAUSED",
            "updated_at": now,
        },
    )
    receipt = {
        "authority_id": authority_id,
        "controller_id": contract["controller_id"],
        "paused_at": now,
        "schema_version": "mvp0-runtime-pause/v1",
        "status": "PAUSED",
    }
    digest = _sha256_bytes(_canonical_bytes(receipt))
    path = store_dir / "runtime" / "lifecycle-receipts" / f"{digest}.json"
    _write_immutable_idempotent(path, _canonical_bytes(receipt))
    return {**receipt, "already_applied": False, "receipt_path": str(path), "receipt_sha256": digest}


def resume_runtime(
    *,
    store_dir: Path,
    scheduler: launchd.Scheduler,
    authority_id: str,
    now: str,
) -> dict[str, Any]:
    """Restore the exact frozen L1 and revalidate the full activation closure."""

    store_dir = store_dir.resolve()
    _parse_time(now)
    if not isinstance(authority_id, str) or not authority_id.strip():
        raise AssuranceError("resume authority_id must be non-empty")
    lifecycle = _load_lifecycle(store_dir)
    if lifecycle["state"] == "STOPPED":
        raise AssuranceError("a stopped activation generation cannot be resumed")
    if lifecycle["state"] == "STOPPING":
        raise AssuranceError("a stopping runtime cannot be resumed")
    contract = _load_contract(store_dir)
    l0 = contract["l0"]
    if not scheduler.is_loaded(l0["scheduler_label"]):
        plist_path = Path(l0["plist_path"])
        if not plist_path.is_file() or plist_path.is_symlink():
            raise AssuranceError("cannot resume because the exact L0 plist is missing")
        scheduler.load(l0["scheduler_label"], plist_path)
    expected = Path(contract["l1"]["backup_path"]).read_bytes()
    if _sha256_bytes(expected) != contract["l1"]["expected_sha256"]:
        raise AssuranceError("cannot resume because the immutable L1 backup drifted")
    _atomic_write(Path(contract["l1"]["automation_path"]), expected)
    _write_json(
        _lifecycle_path(store_dir),
        {
            "authority_id": authority_id,
            "controller_id": contract["controller_id"],
            "state": "ACTIVE",
            "updated_at": now,
        },
    )
    verified = verify_activation(store_dir=store_dir, scheduler=scheduler, now=now)
    receipt = {
        "activation_receipt_sha256": verified["activation_receipt_sha256"],
        "authority_id": authority_id,
        "controller_id": contract["controller_id"],
        "resumed_at": now,
        "schema_version": "mvp0-runtime-resume/v1",
        "status": "ACTIVE",
    }
    digest = _sha256_bytes(_canonical_bytes(receipt))
    path = store_dir / "runtime" / "lifecycle-receipts" / f"{digest}.json"
    _write_immutable_idempotent(path, _canonical_bytes(receipt))
    return {**receipt, "receipt_path": str(path), "receipt_sha256": digest}


def shutdown_runtime(
    *,
    store_dir: Path,
    scheduler: launchd.Scheduler,
    processes: ProcessInspector,
    authority_id: str,
    now: str,
    simulate_crash_after: str | None = None,
) -> dict[str, Any]:
    """Converge on one ordered, restart-safe shutdown receipt."""

    store_dir = store_dir.resolve()
    _parse_time(now)
    if not isinstance(authority_id, str) or not authority_id.strip():
        raise AssuranceError("shutdown authority_id must be non-empty")
    receipt_path = store_dir / "runtime" / "shutdown-receipt.json"
    if receipt_path.is_file():
        receipt = _read_json(receipt_path)
        if receipt.get("authority_id") != authority_id:
            raise AssuranceError("shutdown was already applied under different authority")
        return {**receipt, "shutdown_receipt_path": str(receipt_path), "shutdown_receipt_sha256": _sha256_file(receipt_path)}
    contract = _load_contract(store_dir)
    activation = _read_json(_activation_path(store_dir))
    journal_path = store_dir / "runtime" / "shutdown-journal.json"
    journal = _read_json(journal_path) if journal_path.is_file() else {
        "authority_id": authority_id,
        "controller_id": contract["controller_id"],
        "phase": "PREPARED",
        "prepared_at": now,
        "schema_version": "mvp0-runtime-shutdown-journal/v1",
        "steps": {},
    }
    if journal.get("authority_id") != authority_id:
        raise AssuranceError("shutdown journal authority mismatch")
    _write_json(
        _lifecycle_path(store_dir),
        {"controller_id": contract["controller_id"], "state": "STOPPING", "updated_at": now},
    )
    journal["steps"]["block_new_work"] = "DONE"
    journal["phase"] = "BLOCKED_NEW_WORK"
    _write_json(journal_path, journal)
    if simulate_crash_after == "BLOCKED_NEW_WORK":
        raise AssuranceError("simulated crash after BLOCKED_NEW_WORK")

    l0_label = activation["l0"]["scheduler_label"]
    scheduler.unload(l0_label)
    journal["steps"]["l0"] = "DISABLED"
    journal["phase"] = "L0_DISABLED"
    _write_json(journal_path, journal)
    if simulate_crash_after == "L0_DISABLED":
        raise AssuranceError("simulated crash after L0_DISABLED")

    l1_path = Path(activation["l1"]["automation_path"])
    if l1_path.is_file() and not l1_path.is_symlink():
        current = l1_path.read_bytes()
        try:
            paused = automation.with_status(current, status="PAUSED", updated_at_ms=_milliseconds(now))
        except automation.AutomationError as exc:
            raise AssuranceError(f"cannot disable L1 automation safely: {exc}") from exc
        _atomic_write(l1_path, paused)
    journal["steps"]["l1"] = "DISABLED"
    journal["phase"] = "L1_DISABLED"
    _write_json(journal_path, journal)
    if simulate_crash_after == "L1_DISABLED":
        raise AssuranceError("simulated crash after L1_DISABLED")

    residuals: list[dict[str, Any]] = []
    pointer_path = store_dir / "assurance" / "current-worker.json"
    worker_results: list[dict[str, Any]] = []
    if pointer_path.is_file():
        pointer = _read_json(pointer_path)
        binding = _read_json(Path(pointer["binding_path"]))
        pid = binding["process_id"]
        observed_identity = processes.identity(pid)
        if observed_identity is None:
            worker_results.append({"outcome": "ALREADY_EXITED", "process_id": pid})
        elif observed_identity != binding["process_identity"]:
            residual = {
                "expected_identity": binding["process_identity"],
                "observed_identity": observed_identity,
                "process_id": pid,
                "reason": "PROCESS_IDENTITY_MISMATCH",
            }
            residuals.append(residual)
            worker_results.append({"outcome": "REFUSED_IDENTITY_MISMATCH", "process_id": pid})
        else:
            processes.terminate(pid)
            if processes.identity(pid) is not None:
                processes.kill(pid)
            if processes.identity(pid) is not None:
                residuals.append({"process_id": pid, "reason": "PROCESS_SURVIVED_KILL"})
                worker_results.append({"outcome": "SURVIVED", "process_id": pid})
            else:
                worker_results.append({"outcome": "TERMINATED", "process_id": pid})
    journal["steps"]["workers"] = worker_results
    journal["phase"] = "WORKERS_STOPPED"
    _write_json(journal_path, journal)
    if simulate_crash_after == "WORKERS_STOPPED":
        raise AssuranceError("simulated crash after WORKERS_STOPPED")

    _write_json(
        _lifecycle_path(store_dir),
        {"controller_id": contract["controller_id"], "state": "STOPPED", "updated_at": now},
    )
    receipt = {
        "artifacts_deleted": False,
        "authority_id": authority_id,
        "completed_at": now,
        "controller_id": contract["controller_id"],
        "residuals": residuals,
        "schema_version": SHUTDOWN_VERSION,
        "status": "SHUTDOWN" if not residuals else "SHUTDOWN_WITH_RESIDUALS",
        "steps": journal["steps"],
    }
    _write_json(receipt_path, receipt, immutable=True)
    journal["phase"] = "COMMITTED"
    journal["shutdown_receipt_sha256"] = _sha256_file(receipt_path)
    _write_json(journal_path, journal)
    return {
        **receipt,
        "shutdown_receipt_path": str(receipt_path),
        "shutdown_receipt_sha256": _sha256_file(receipt_path),
    }
