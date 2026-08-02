#!/usr/bin/env python3
"""Complete P6 L0/L1/L2 runtime assurance for the isolated MVP-0 loop.

This module owns runtime metadata only.  It never reads Research IR content,
judges scientific evidence, or invokes a model.  The Codex heartbeat remains
the model-bearing L1; this module makes its registration independently
observable and recoverable and binds it to Worker liveness evidence.
"""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
import signal
import subprocess
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
L1_STABLE_FIELDS = (
    "version",
    "id",
    "kind",
    "name",
    "rrule",
    "target_thread_id",
    "created_at",
)


class AssuranceError(RuntimeError):
    """A fail-closed runtime-assurance contract error."""


def _l1_registration_matches(
    expected: bytes,
    observed: bytes,
    *,
    lifecycle_state: str,
) -> bool:
    """Accept only Codex App's documented persistence normalization.

    The App owns ``updated_at`` and removes one terminal newline from prompt
    values when it rewrites an automation.  Those representation changes must
    not invalidate an otherwise exact activation.  Every stable routing field,
    the complete prompt content, and the lifecycle status remain fail-closed.
    """

    try:
        expected_value = automation.parse_thread_automation(expected)
        observed_value = automation.parse_thread_automation(observed)
    except automation.AutomationError:
        return False
    if any(
        observed_value[field] != expected_value[field]
        for field in L1_STABLE_FIELDS
    ):
        return False
    if observed_value["prompt"].rstrip() != expected_value["prompt"].rstrip():
        return False
    required_status = "ACTIVE" if lifecycle_state == "ACTIVE" else "PAUSED"
    if observed_value["status"] != required_status:
        return False
    return observed_value["updated_at"] >= expected_value["created_at"]


class ProcessInspector(Protocol):
    def identity(self, pid: int) -> str | None: ...

    def terminate(self, pid: int) -> None: ...

    def kill(self, pid: int) -> None: ...


class LocalProcessInspector:
    """Inspect and signal the exact process-group leader launched by P2."""

    def identity(self, pid: int) -> str | None:
        try:
            proc = subprocess.run(
                ["/bin/ps", "-o", "lstart=,command=", "-p", str(pid)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            raise AssuranceError(f"cannot inspect Worker process identity: {exc}") from exc
        rendered = proc.stdout.strip()
        if proc.returncode != 0 or not rendered:
            return None
        return _sha256_bytes(_canonical_bytes({"pid": pid, "ps_identity": rendered}))

    @staticmethod
    def _signal_group(pid: int, signum: int) -> None:
        try:
            os.killpg(pid, signum)
        except ProcessLookupError:
            return
        except PermissionError as exc:
            raise AssuranceError(f"cannot signal Worker process group {pid}: {exc}") from exc

    def terminate(self, pid: int) -> None:
        self._signal_group(pid, signal.SIGTERM)

    def kill(self, pid: int) -> None:
        self._signal_group(pid, signal.SIGKILL)


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


def _l1_latest_path(store_dir: Path) -> Path:
    return store_dir / "assurance" / "l1-latest.json"


def _tick_lease_status(store_dir: Path) -> str:
    path = store_dir / "leases" / "tick.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "HELD"
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        return "FREE"
    finally:
        handle.close()


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


def record_l1_heartbeat(
    *,
    store_dir: Path,
    controller_id: str,
    target_thread_id: str,
    observed_at: str,
    source: str = "SCHEDULED_CODEX_TASK",
) -> dict[str, Any]:
    """Publish proof that the exact L1 task returned to its bound controller."""

    store_dir = store_dir.resolve()
    _parse_time(observed_at)
    if source not in {"ACTIVATION_PROBE", "SCHEDULED_CODEX_TASK", "MANUAL_BOUND_TICK"}:
        raise AssuranceError("L1 heartbeat source is invalid")
    contract = _load_contract(store_dir)
    lifecycle = _load_lifecycle(store_dir)
    if controller_id != contract["controller_id"]:
        raise AssuranceError("L1 heartbeat controller mismatch")
    if target_thread_id != contract["l1"]["target_thread_id"]:
        raise AssuranceError("L1 heartbeat target thread mismatch")
    if source != "ACTIVATION_PROBE" and lifecycle["state"] != "ACTIVE":
        raise AssuranceError(f"L1 heartbeat refused in lifecycle {lifecycle['state']}")
    lock_path = store_dir / "assurance" / "l1-heartbeat.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open("a+")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        latest_path = _l1_latest_path(store_dir)
        latest = _read_json(latest_path) if latest_path.is_file() else None
        sequence = 1 if not isinstance(latest, dict) else int(latest["sequence"]) + 1
        predecessor = None if not isinstance(latest, dict) else latest["heartbeat_sha256"]
        heartbeat = {
            "controller_id": controller_id,
            "model_dispatches": 0 if source == "ACTIVATION_PROBE" else 1,
            "observed_at": observed_at,
            "predecessor_sha256": predecessor,
            "schema_version": "mvp0-l1-heartbeat/v1",
            "sequence": sequence,
            "source": source,
            "target_thread_id": target_thread_id,
        }
        payload = _canonical_bytes(heartbeat)
        digest = _sha256_bytes(payload)
        object_path = store_dir / "assurance" / "l1-heartbeats" / f"{digest}.json"
        already = _write_immutable_idempotent(object_path, payload)
        if not already:
            _append_jsonl(
                store_dir / "assurance" / "l1-heartbeats.jsonl",
                {"heartbeat_path": str(object_path), "sequence": sequence, "sha256": digest},
            )
        _write_json(
            latest_path,
            {
                "heartbeat_path": str(object_path),
                "heartbeat_sha256": digest,
                "observed_at": observed_at,
                "sequence": sequence,
                "source": source,
            },
        )
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    return {
        "already_applied": already,
        "heartbeat_path": str(object_path),
        "heartbeat_sha256": digest,
        "sequence": sequence,
        "source": source,
    }


def _publish_l0_observation(store_dir: Path, observation: dict[str, Any]) -> dict[str, Any]:
    fingerprint_value = {
        key: value
        for key, value in observation.items()
        if key not in {
            "observed_at",
            "deduplicated",
            "observation_sha256",
            "l1_heartbeat_age_seconds",
            "l2_heartbeat_age_seconds",
        }
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
    object_path = store_dir / "assurance" / "l0-objects" / f"{object_digest}.json"
    _write_immutable_idempotent(object_path, _canonical_bytes(payload))
    _append_jsonl(index_path, {"observation_path": str(object_path), "sha256": object_digest})
    returned = {**payload, "observation_sha256": object_digest}
    _write_json(latest_path, {"fingerprint": fingerprint, "observation": returned})
    return returned


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
    simulate_crash_after: str | None = None,
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
        verified_existing = verify_activation(store_dir=store_dir, scheduler=scheduler, now=now)
        journal_path = store_dir / "runtime" / "bootstrap-journal.json"
        if journal_path.is_file():
            journal = _read_json(journal_path)
            if isinstance(journal, dict) and journal.get("phase") != "COMMITTED":
                _write_json(
                    journal_path,
                    {
                        "activation_receipt_sha256": verified_existing["activation_receipt_sha256"],
                        "controller_id": verified_existing["controller_id"],
                        "phase": "COMMITTED",
                        "prepared_at": journal.get("prepared_at", now),
                        "schema_version": "mvp0-runtime-bootstrap-journal/v1",
                    },
                )
        return verified_existing
    partial_contract: dict[str, Any] | None = None
    if _contract_path(store_dir).is_file():
        partial = _load_contract(store_dir)
        partial_contract = partial
        expected_partial = {
            "controller_id": controller_id,
            "target_thread_id": target_thread_id,
            "l0_interval_seconds": l0_interval_seconds,
            "l1_interval_seconds": l1_interval_seconds,
            "l2_interval_seconds": l2_interval_seconds,
            "heartbeat_stale_seconds": heartbeat_stale_seconds,
        }
        observed_partial = {
            "controller_id": partial.get("controller_id"),
            "target_thread_id": partial.get("l1", {}).get("target_thread_id"),
            "l0_interval_seconds": partial.get("l0", {}).get("interval_seconds"),
            "l1_interval_seconds": partial.get("l1", {}).get("interval_seconds"),
            "l2_interval_seconds": partial.get("l2", {}).get("heartbeat_interval_seconds"),
            "heartbeat_stale_seconds": partial.get("heartbeat_stale_seconds"),
        }
        if observed_partial != expected_partial:
            raise AssuranceError("partial bootstrap contract differs from requested activation")
        partial_backup = Path(partial["l1"]["backup_path"])
        if not partial_backup.is_file() or partial_backup.is_symlink():
            raise AssuranceError("partial bootstrap L1 backup is missing or unsafe")
        expected_partial_bytes = partial_backup.read_bytes()
        if _sha256_bytes(expected_partial_bytes) != partial["l1"]["expected_sha256"]:
            raise AssuranceError("partial bootstrap L1 backup drifted")
        if not l1_automation_path.exists():
            _atomic_write(l1_automation_path, expected_partial_bytes)
        elif l1_automation_path.is_symlink() or l1_automation_path.read_bytes() != expected_partial_bytes:
            raise AssuranceError("partial bootstrap L1 registration drifted")
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
    generation_created_at = (
        partial_contract["created_at"] if partial_contract is not None else now
    )
    runtime_contract = {
        "controller_id": controller_id,
        "created_at": generation_created_at,
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
            "stale_seconds": max(l1_interval_seconds * 2, heartbeat_stale_seconds),
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
        "created_at": generation_created_at,
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
    bootstrap_journal_path = store_dir / "runtime" / "bootstrap-journal.json"
    _write_json(
        bootstrap_journal_path,
        {
            "controller_id": controller_id,
            "phase": "PREPARED",
            "prepared_at": now,
            "schema_version": "mvp0-runtime-bootstrap-journal/v1",
        },
    )
    _write_immutable_idempotent(backup_path, l1_bytes)
    _write_immutable_idempotent(plist_evidence_path, plist_bytes)
    _atomic_write(installed_plist_path, plist_bytes)
    _write_immutable_idempotent(heartbeat_contract_path, _canonical_bytes(heartbeat_contract))
    _write_immutable_idempotent(_contract_path(store_dir), _canonical_bytes(runtime_contract))
    _write_immutable_idempotent(
        store_dir / "runtime" / "resource-manifest.json",
        _canonical_bytes(resource_manifest),
    )
    _write_json(
        _lifecycle_path(store_dir),
        {"controller_id": controller_id, "state": "ACTIVE", "updated_at": now},
    )
    if not scheduler.is_loaded(l0_label):
        scheduler.load(l0_label, installed_plist_path)
    if not scheduler.is_loaded(l0_label):
        raise AssuranceError("L0 service did not become loaded")
    _write_json(
        bootstrap_journal_path,
        {
            "controller_id": controller_id,
            "phase": "L0_LOADED",
            "prepared_at": now,
            "schema_version": "mvp0-runtime-bootstrap-journal/v1",
        },
    )

    l1_heartbeat_probe = record_l1_heartbeat(
        store_dir=store_dir,
        controller_id=controller_id,
        target_thread_id=target_thread_id,
        observed_at=now,
        source="ACTIVATION_PROBE",
    )
    l1_probe = {
        "due": False,
        "heartbeat_sha256": l1_heartbeat_probe["heartbeat_sha256"],
        "model_dispatches": 0,
        "observed_at": now,
        "registration_sha256": l1_digest,
    }
    l1_automation_path.unlink()
    _write_json(
        bootstrap_journal_path,
        {
            "controller_id": controller_id,
            "phase": "L1_REMOVED",
            "prepared_at": now,
            "schema_version": "mvp0-runtime-bootstrap-journal/v1",
        },
    )
    if simulate_crash_after == "L1_REMOVED":
        raise AssuranceError("simulated bootstrap crash after L1_REMOVED")
    l0_probe_result = run_l0_health_tick(store_dir=store_dir, scheduler=scheduler, now=now)
    if l0_probe_result.get("action") != "RESTORED_L1" or l1_automation_path.read_bytes() != l1_bytes:
        raise AssuranceError("L0 failed the exact L1 restoration probe")
    l0_probe = {
        "l1_restored": True,
        "l1_was_removed": True,
        "model_dispatches": l0_probe_result["model_dispatches"],
        "observation_sha256": l0_probe_result["observation_sha256"],
    }
    l2_probe_store = store_dir / "runtime" / "bootstrap-probes" / "l2"
    (l2_probe_store / "assurance").mkdir(parents=True, exist_ok=True)
    (l2_probe_store / "runtime").mkdir(parents=True, exist_ok=True)
    _write_immutable_idempotent(
        _contract_path(l2_probe_store), _canonical_bytes(runtime_contract)
    )
    _write_json(
        _lifecycle_path(l2_probe_store),
        {"controller_id": controller_id, "state": "ACTIVE", "updated_at": now},
    )
    probe_binding = bind_worker(
        store_dir=l2_probe_store,
        adapter_id=f"{controller_id}-activation-probe",
        turn_id="activation-probe",
        session_id="00000000-0000-4000-8000-000000000000",
        worker_model="activation-probe/no-model",
        task_contract_sha256=_sha256_bytes(controller_id.encode("utf-8")),
        process_id=1,
        process_identity="activation-probe/no-process",
        now=now,
    )
    probe_heartbeat = record_worker_heartbeat(
        store_dir=l2_probe_store,
        worker_binding_path=Path(probe_binding["worker_binding_path"]),
        sequence=1,
        session_id="00000000-0000-4000-8000-000000000000",
        process_id=1,
        process_identity="activation-probe/no-process",
        task_contract_sha256=_sha256_bytes(controller_id.encode("utf-8")),
        observed_at=now,
    )
    l2_probe = {
        "binding_sha256": probe_binding["binding_sha256"],
        "contract_sha256": _sha256_file(heartbeat_contract_path),
        "contract_verified": True,
        "heartbeat_path": probe_heartbeat["heartbeat_path"],
        "heartbeat_sha256": probe_heartbeat["heartbeat_sha256"],
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
    _write_json(
        bootstrap_journal_path,
        {
            "activation_receipt_sha256": _sha256_file(_activation_path(store_dir)),
            "controller_id": controller_id,
            "phase": "COMMITTED",
            "prepared_at": now,
            "schema_version": "mvp0-runtime-bootstrap-journal/v1",
        },
    )
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
        "controller_lease": _tick_lease_status(store_dir),
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
    if not _l1_registration_matches(
        expected, observed, lifecycle_state=lifecycle["state"]
    ):
        return _publish_l0_observation(
            store_dir,
            {**base, "action": "RECOVERY_PROPOSED", "reason": "L1_DRIFT"},
        )

    l1_latest_path = _l1_latest_path(store_dir)
    if not l1_latest_path.is_file():
        return _publish_l0_observation(
            store_dir,
            {**base, "action": "RECOVERY_PROPOSED", "reason": "L1_HEARTBEAT_MISSING"},
        )
    l1_latest = _read_json(l1_latest_path)
    if not isinstance(l1_latest, dict):
        raise AssuranceError("latest L1 heartbeat pointer is invalid")
    l1_age = max(
        0.0,
        (_parse_time(now) - _parse_time(l1_latest["observed_at"])).total_seconds(),
    )
    base["l1_heartbeat_age_seconds"] = int(l1_age)
    base["l1_heartbeat_sha256"] = l1_latest.get("heartbeat_sha256")
    if l1_age >= l1["stale_seconds"]:
        return _publish_l0_observation(
            store_dir,
            {**base, "action": "RECOVERY_PROPOSED", "reason": "L1_HEARTBEAT_STALE"},
        )

    pointer_path = store_dir / "assurance" / "current-worker.json"
    if pointer_path.is_file():
        pointer = _read_json(pointer_path)
        if not isinstance(pointer, dict) or not _valid_sha(pointer.get("binding_sha256")):
            raise AssuranceError("current Worker pointer is invalid")
        if pointer.get("state") != "TERMINAL":
            heartbeat = _latest_heartbeat(store_dir, pointer["binding_sha256"])
            if heartbeat is None:
                return _publish_l0_observation(
                    store_dir,
                    {**base, "action": "RECOVERY_PROPOSED", "reason": "L2_HEARTBEAT_MISSING"},
                )
            l2_age = max(
                0.0,
                (_parse_time(now) - _parse_time(heartbeat["observed_at"])).total_seconds(),
            )
            base["l2_heartbeat_age_seconds"] = int(l2_age)
            base["l2_heartbeat_sha256"] = _sha256_bytes(_canonical_bytes(heartbeat))
            if l2_age >= contract["heartbeat_stale_seconds"]:
                return _publish_l0_observation(
                    store_dir,
                    {**base, "action": "RECOVERY_PROPOSED", "reason": "L2_HEARTBEAT_STALE"},
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
    require_l1_fresh: bool = True,
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
    lifecycle = _load_lifecycle(store_dir)
    if lifecycle["state"] != "ACTIVE":
        raise AssuranceError(f"runtime activation is not ACTIVE: {lifecycle['state']}")
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
    expected_l1 = Path(contract["l1"]["backup_path"]).read_bytes()
    if not _l1_registration_matches(
        expected_l1, automation_path.read_bytes(), lifecycle_state=lifecycle["state"]
    ):
        raise AssuranceError("runtime activation L1 registration drifted")
    automation.validate_thread_automation(
        automation_path,
        expected_thread_id=activation["target_thread_id"],
        expected_controller_id=activation["controller_id"],
    )
    l1_latest = _read_json(_l1_latest_path(store_dir))
    if not isinstance(l1_latest, dict):
        raise AssuranceError("runtime activation L1 heartbeat pointer is invalid")
    heartbeat_path = Path(l1_latest.get("heartbeat_path", ""))
    if (
        not heartbeat_path.is_file()
        or heartbeat_path.is_symlink()
        or _sha256_file(heartbeat_path) != l1_latest.get("heartbeat_sha256")
    ):
        raise AssuranceError("runtime activation L1 heartbeat evidence drifted")
    heartbeat_age = max(
        0.0,
        (_parse_time(now) - _parse_time(l1_latest["observed_at"])).total_seconds(),
    )
    if require_l1_fresh and heartbeat_age >= contract["l1"]["stale_seconds"]:
        raise AssuranceError("runtime activation L1 heartbeat is stale")
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
    l2_probe_path = Path(activation["probes"]["l2"].get("heartbeat_path", ""))
    if (
        not l2_probe_path.is_file()
        or l2_probe_path.is_symlink()
        or _sha256_file(l2_probe_path)
        != activation["probes"]["l2"].get("heartbeat_sha256")
    ):
        raise AssuranceError("runtime activation L2 conformance heartbeat drifted")
    return {
        "activation_receipt_path": str(path),
        "activation_receipt_sha256": _sha256_file(path),
        "controller_id": activation["controller_id"],
        "status": "VERIFIED",
    }


def heartbeat_interval_seconds(*, store_dir: Path) -> int:
    """Return the frozen L2 cadence without exposing research state."""

    contract = _load_contract(store_dir.resolve())
    value = contract["l2"]["heartbeat_interval_seconds"]
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AssuranceError("runtime L2 heartbeat interval is invalid")
    return value


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


def complete_worker(
    *,
    store_dir: Path,
    worker_binding_path: Path,
    outcome: str,
    turn_receipt_path: Path,
    turn_receipt_sha256: str,
    completed_at: str,
) -> dict[str, Any]:
    """Bind one terminal P2 receipt so completed work is not reported stale."""

    store_dir = store_dir.resolve()
    _parse_time(completed_at)
    if outcome not in {"COMPLETED", "BLOCKED", "FAILED"}:
        raise AssuranceError("Worker terminal outcome is invalid")
    binding_path = worker_binding_path.resolve()
    pointer_path = store_dir / "assurance" / "current-worker.json"
    pointer = _read_json(pointer_path)
    if pointer.get("binding_path") != str(binding_path):
        raise AssuranceError("terminal Worker binding is not current")
    binding_digest = _sha256_file(binding_path)
    if pointer.get("binding_sha256") != binding_digest:
        raise AssuranceError("terminal Worker binding hash mismatch")
    receipt_path = turn_receipt_path.resolve()
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise AssuranceError("terminal Worker receipt is missing or unsafe")
    if not _valid_sha(turn_receipt_sha256) or _sha256_file(receipt_path) != turn_receipt_sha256:
        raise AssuranceError("terminal Worker receipt hash mismatch")
    completion = {
        "binding_sha256": binding_digest,
        "completed_at": completed_at,
        "controller_id": pointer["controller_id"],
        "outcome": outcome,
        "schema_version": "mvp0-runtime-worker-completion/v1",
        "turn_receipt_path": str(receipt_path),
        "turn_receipt_sha256": turn_receipt_sha256,
    }
    digest = _sha256_bytes(_canonical_bytes(completion))
    completion_path = store_dir / "assurance" / "worker-completions" / f"{digest}.json"
    already = _write_immutable_idempotent(completion_path, _canonical_bytes(completion))
    _write_json(
        pointer_path,
        {
            **pointer,
            "completion_path": str(completion_path),
            "completion_sha256": digest,
            "state": "TERMINAL",
        },
    )
    return {
        "already_applied": already,
        "completion_path": str(completion_path),
        "completion_sha256": digest,
        "state": "TERMINAL",
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
    expected_l1 = Path(l1["backup_path"]).read_bytes()
    l1_matches = (
        l1_present
        and _l1_registration_matches(
            expected_l1,
            automation_path.read_bytes(),
            lifecycle_state=lifecycle["state"],
        )
    )
    l1_latest_path = _l1_latest_path(store_dir)
    l1_latest = _read_json(l1_latest_path) if l1_latest_path.is_file() else None
    l1_age = (
        None
        if not isinstance(l1_latest, dict)
        else int(max(0.0, (observed - _parse_time(l1_latest["observed_at"])).total_seconds()))
    )
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
        if pointer.get("state") == "TERMINAL":
            completion_path = Path(pointer.get("completion_path", ""))
            if (
                not completion_path.is_file()
                or _sha256_file(completion_path) != pointer.get("completion_sha256")
            ):
                raise AssuranceError("terminal Worker completion pointer drifted")
            l2 = {
                "binding": "BOUND",
                "freshness": "TERMINAL",
                "heartbeat_age_seconds": None,
                "completion_sha256": pointer["completion_sha256"],
            }
        elif heartbeat is None:
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
            "agreement": "MATCH" if l1_matches else "MISSING" if not l1_present else "MISMATCH",
            "automation_id": l1["automation_id"],
            "heartbeat_age_seconds": l1_age,
            "heartbeat_freshness": (
                "MISSING"
                if l1_age is None
                else "FRESH"
                if l1_age < l1["stale_seconds"]
                else "STALE"
            ),
            "heartbeat_source": None if not isinstance(l1_latest, dict) else l1_latest.get("source"),
            "path": str(automation_path),
        },
        "l2": l2,
        "lifecycle": lifecycle["state"],
        "observed_at": now,
        "schema_version": SNAPSHOT_VERSION,
        "scientific_state_mutations": 0,
        "supervisor_lease": _tick_lease_status(store_dir),
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
    verify_activation(
        store_dir=store_dir,
        scheduler=scheduler,
        now=now,
        require_l1_fresh=False,
    )
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
    record_l1_heartbeat(
        store_dir=store_dir,
        controller_id=contract["controller_id"],
        target_thread_id=contract["l1"]["target_thread_id"],
        observed_at=now,
        source="MANUAL_BOUND_TICK",
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
        if pointer.get("state") == "TERMINAL" and observed_identity is None:
            worker_results.append({"outcome": "TERMINAL_ALREADY_EXITED", "process_id": pid})
        elif observed_identity is None:
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
