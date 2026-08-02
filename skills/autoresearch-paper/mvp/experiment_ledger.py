#!/usr/bin/env python3
"""Content-addressed Experiment Receipt ledger for MVP-0 P3.

P3 reconstructs one scientific provenance record from each terminal P2 turn.
It does not evaluate metrics, choose KEEP/PIVOT/STOP/RECOMPILE, retry Workers,
or mutate the research worktree.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from . import worker_adapter as worker
except ImportError:  # pragma: no cover - direct script execution
    import worker_adapter as worker  # type: ignore[no-redef]


MVP_ROOT = Path(__file__).resolve().parent
RECEIPT_SCHEMA_PATH = MVP_ROOT / "schemas" / "experiment-receipt.schema.json"
LEDGER_VERSION = "experiment-ledger/v1"
RECEIPT_VERSION = "experiment-receipt/v1"
INDEX_VERSION = "experiment-ledger-index/v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class LedgerError(RuntimeError):
    """A fail-closed P3 ledger or provenance error."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise LedgerError(f"value is not canonical JSON: {exc}") from exc
    return (rendered + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return worker._sha256_bytes(value)  # noqa: SLF001


def _sha256_file(path: Path) -> str:
    return worker._sha256_file(path)  # noqa: SLF001


def _load_json(path: Path) -> Any:
    try:
        return worker._load_json(path)  # noqa: SLF001
    except worker.AdapterError as exc:
        raise LedgerError(str(exc)) from exc


def _atomic_write(path: Path, payload: bytes, *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and (path.exists() or path.is_symlink()):
        raise LedgerError(f"immutable artifact already exists: {path}")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
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


def _publish_immutable_json(path: Path, value: Any) -> None:
    """Publish once, while accepting an exact object left by an interrupted append."""

    payload = _canonical_bytes(value)
    if path.exists() or path.is_symlink():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_mode & 0o777 != 0o444
            or path.read_bytes() != payload
        ):
            raise LedgerError(f"content-addressed object collided or became mutable: {path}")
        return
    _atomic_write(path, payload, immutable=True)


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise LedgerError(
            f"{label} fields differ: missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _immutable_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o777 != 0o444:
        raise LedgerError(f"{label} is missing, mutable, or a symlink: {path}")
    value = _load_json(path)
    if not isinstance(value, dict):
        raise LedgerError(f"{label} must be a JSON object")
    return value, _sha256_file(path)


def _validate_receipt(value: Any) -> dict[str, Any]:
    try:
        worker._validate_against_schema(  # noqa: SLF001
            value,
            RECEIPT_SCHEMA_PATH,
            "Experiment receipt",
        )
    except worker.AdapterError as exc:
        raise LedgerError(str(exc)) from exc
    if not isinstance(value, dict):
        raise LedgerError("Experiment receipt must be an object")
    return value


def initialize_ledger(*, adapter_dir: Path, ledger_dir: Path) -> dict[str, Any]:
    """Bind a new P3 ledger to exactly one immutable P2 Adapter."""

    adapter_dir = adapter_dir.resolve()
    try:
        adapter_manifest = worker._adapter_manifest(adapter_dir)  # noqa: SLF001
        worker._session_state(adapter_dir, adapter_manifest)  # noqa: SLF001
    except worker.AdapterError as exc:
        raise LedgerError(f"P2 Adapter replay failed: {exc}") from exc
    ledger_dir = ledger_dir.resolve()
    if ledger_dir.exists() or ledger_dir.is_symlink():
        raise LedgerError("ledger_dir already exists")
    protected_roots = (
        Path(adapter_manifest["source_repo"]).resolve(),
        Path(adapter_manifest["worktree_root"]).resolve(),
        adapter_dir,
    )
    if any(_inside(ledger_dir, root) or _inside(root, ledger_dir) for root in protected_roots):
        raise LedgerError("ledger_dir must not overlap the source repo, worktree, or Adapter")
    ledger_dir.parent.mkdir(parents=True, exist_ok=True)
    ledger_dir.mkdir()
    try:
        ledger_id = "mvp0-ledger-" + uuid.uuid4().hex[:16]
        manifest = {
            "adapter_dir": str(adapter_dir),
            "adapter_id": adapter_manifest["adapter_id"],
            "adapter_manifest_path": str(adapter_dir / "adapter-manifest.json"),
            "adapter_manifest_sha256": _sha256_file(adapter_dir / "adapter-manifest.json"),
            "created_at": _now(),
            "freeze_receipt_sha256": adapter_manifest["freeze_receipt_sha256"],
            "ledger_id": ledger_id,
            "research_ir_sha256": adapter_manifest["research_ir_sha256"],
            "receipt_schema_sha256": _sha256_file(RECEIPT_SCHEMA_PATH),
            "schema_version": LEDGER_VERSION,
        }
        _write_json(ledger_dir / "ledger-manifest.json", manifest, immutable=True)
        _atomic_write(ledger_dir / "experiment-receipts.jsonl", b"")
        (ledger_dir / "objects" / "sha256").mkdir(parents=True)
        (ledger_dir / "blobs" / "sha256").mkdir(parents=True)
    except Exception:
        shutil.rmtree(ledger_dir)
        raise
    return {
        "ledger_dir": str(ledger_dir),
        "ledger_id": ledger_id,
        "record_count": 0,
        "research_ir_sha256": manifest["research_ir_sha256"],
    }


def _ledger_manifest(
    ledger_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest, _ = _immutable_json(ledger_dir / "ledger-manifest.json", "ledger manifest")
    _exact_keys(manifest, {
        "adapter_dir",
        "adapter_id",
        "adapter_manifest_path",
        "adapter_manifest_sha256",
        "created_at",
        "freeze_receipt_sha256",
        "ledger_id",
        "research_ir_sha256",
        "receipt_schema_sha256",
        "schema_version",
    }, "ledger manifest")
    if manifest["schema_version"] != LEDGER_VERSION:
        raise LedgerError("ledger manifest version is unsupported")
    if _sha256_file(RECEIPT_SCHEMA_PATH) != manifest["receipt_schema_sha256"]:
        raise LedgerError("Experiment receipt schema drifted")
    adapter_dir = Path(manifest["adapter_dir"]).resolve()
    try:
        adapter_manifest = worker._adapter_manifest(adapter_dir)  # noqa: SLF001
        session = worker._session_state(adapter_dir, adapter_manifest)  # noqa: SLF001
    except worker.AdapterError as exc:
        raise LedgerError(f"P2 Adapter replay failed: {exc}") from exc
    if (
        Path(manifest["adapter_manifest_path"]).resolve() != adapter_dir / "adapter-manifest.json"
        or _sha256_file(adapter_dir / "adapter-manifest.json") != manifest["adapter_manifest_sha256"]
        or adapter_manifest["adapter_id"] != manifest["adapter_id"]
        or adapter_manifest["research_ir_sha256"] != manifest["research_ir_sha256"]
        or adapter_manifest["freeze_receipt_sha256"] != manifest["freeze_receipt_sha256"]
    ):
        raise LedgerError("ledger binding differs from the P2 Adapter")
    return manifest, adapter_manifest, session


def _blob_path(ledger_dir: Path, digest: str) -> Path:
    if not SHA256_RE.fullmatch(digest):
        raise LedgerError("blob digest is not lowercase SHA-256")
    return ledger_dir / "blobs" / "sha256" / digest


def _archive_blob(ledger_dir: Path, source: Path, digest: str, label: str) -> str:
    if source.is_symlink() or not source.is_file():
        raise LedgerError(f"{label} is missing, non-regular, or a symlink: {source}")
    if _sha256_file(source) != digest:
        raise LedgerError(f"{label} hash differs from bound provenance: {source}")
    target = _blob_path(ledger_dir, digest)
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file() or target.stat().st_mode & 0o777 != 0o444:
            raise LedgerError(f"archived blob is mutable or a symlink: {target}")
        if _sha256_file(target) != digest:
            raise LedgerError(f"archived blob hash drifted: {target}")
    else:
        _atomic_write(target, source.read_bytes(), immutable=True)
    return str(target)


def _verify_blob(ledger_dir: Path, path_value: str, digest: str) -> None:
    expected = _blob_path(ledger_dir, digest).resolve()
    actual = Path(path_value).resolve()
    if actual != expected:
        raise LedgerError("receipt blob path is not the content-addressed ledger path")
    if actual.is_symlink() or not actual.is_file() or actual.stat().st_mode & 0o777 != 0o444:
        raise LedgerError(f"receipt blob is missing, mutable, or a symlink: {actual}")
    if _sha256_file(actual) != digest:
        raise LedgerError(f"receipt blob hash drifted: {actual}")


def _load_index(ledger_dir: Path) -> list[dict[str, Any]]:
    path = ledger_dir / "experiment-receipts.jsonl"
    if path.is_symlink() or not path.is_file():
        raise LedgerError("experiment receipt log is missing or a symlink")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise LedgerError(f"cannot read experiment receipt log: {exc}") from exc
    entries: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            raise LedgerError(f"experiment receipt log has blank line {line_number}")
        try:
            entry = json.loads(line, parse_constant=worker._reject_constant)  # noqa: SLF001
        except (ValueError, json.JSONDecodeError) as exc:
            raise LedgerError(f"invalid JSONL index line {line_number}: {exc}") from exc
        if not isinstance(entry, dict):
            raise LedgerError(f"JSONL index line {line_number} must be an object")
        _exact_keys(
            entry,
            {"schema_version", "sequence", "receipt_sha256", "receipt"},
            "index entry",
        )
        if (
            entry["schema_version"] != INDEX_VERSION
            or entry["sequence"] != line_number
            or not isinstance(entry["receipt_sha256"], str)
            or not SHA256_RE.fullmatch(entry["receipt_sha256"])
        ):
            raise LedgerError(f"JSONL index line {line_number} has invalid identity")
        receipt = _validate_receipt(entry["receipt"])
        if (
            receipt["sequence"] != line_number
            or _sha256_bytes(_canonical_bytes(receipt)) != entry["receipt_sha256"]
        ):
            raise LedgerError(f"JSONL index line {line_number} receipt digest differs")
        entries.append(entry)
    return entries


def _receipt_object_digests(ledger_dir: Path) -> set[str]:
    root = ledger_dir / "objects" / "sha256"
    if root.is_symlink() or not root.is_dir():
        raise LedgerError("Experiment Receipt object store is missing or a symlink")
    digests: set[str] = set()
    for path in root.iterdir():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix != ".json"
            or not SHA256_RE.fullmatch(path.stem)
            or path.stat().st_mode & 0o777 != 0o444
        ):
            raise LedgerError(f"invalid Experiment Receipt object-store entry: {path}")
        digests.add(path.stem)
    return digests


def _turn_receipt(
    *, adapter_dir: Path, path: Path
) -> tuple[dict[str, Any], str]:
    resolved = path.resolve()
    if resolved.parent != (adapter_dir / "turns").resolve():
        raise LedgerError("Worker turn receipt must be an exact Adapter turns artifact")
    return _immutable_json(resolved, "Worker turn receipt")


def _bound_file(path_value: Any, digest: Any, label: str) -> tuple[dict[str, Any], Path]:
    if not isinstance(path_value, str) or not isinstance(digest, str):
        raise LedgerError(f"{label} path/hash binding is missing")
    path = Path(path_value).resolve()
    value, actual = _immutable_json(path, label)
    if actual != digest:
        raise LedgerError(f"{label} hash binding changed")
    return value, path


def _input_archive(
    turn: Mapping[str, Any],
    contract: Mapping[str, Any],
    run_dir: Path,
) -> dict[str, dict[str, Any]]:
    archive, archive_path = _bound_file(
        turn.get("input_archive_path"),
        turn.get("input_archive_sha256"),
        "P2 input archive",
    )
    if archive_path != run_dir / "input-archive.json":
        raise LedgerError("P2 input archive is outside the exact turn run directory")
    _exact_keys(archive, {"artifacts"}, "P2 input archive")
    if not isinstance(archive["artifacts"], list):
        raise LedgerError("P2 input archive artifacts must be an array")
    by_path: dict[str, dict[str, Any]] = {}
    for item in archive["artifacts"]:
        if not isinstance(item, dict):
            raise LedgerError("P2 input archive item must be an object")
        _exact_keys(item, {"blob_path", "path", "purpose", "sha256"}, "P2 input archive item")
        if item["path"] in by_path:
            raise LedgerError("P2 input archive has duplicate paths")
        by_path[item["path"]] = item
    expected = {item["path"]: item for item in contract["input_artifacts"]}
    if set(by_path) != set(expected):
        raise LedgerError("P2 input archive inventory differs from the task contract")
    for path, item in by_path.items():
        source = expected[path]
        if item["sha256"] != source["sha256"] or item["purpose"] != source["purpose"]:
            raise LedgerError("P2 input archive identity differs from the task contract")
        blob = Path(item["blob_path"]).resolve()
        if blob != run_dir / "input-blobs" / "sha256" / item["sha256"]:
            raise LedgerError("P2 input archive blob is outside its run directory")
        if blob.is_symlink() or not blob.is_file() or blob.stat().st_mode & 0o777 != 0o444:
            raise LedgerError("P2 input archive blob is mutable or unavailable")
        if _sha256_file(blob) != item["sha256"]:
            raise LedgerError("P2 input archive blob hash drifted")
    return by_path


def _build_receipt(
    *,
    ledger_dir: Path,
    ledger_manifest: Mapping[str, Any],
    adapter_manifest: Mapping[str, Any],
    turn_path: Path,
    turn: Mapping[str, Any],
    turn_digest: str,
    sequence: int,
    previous_digest: str | None,
) -> dict[str, Any]:
    adapter_dir = Path(ledger_manifest["adapter_dir"]).resolve()
    if turn.get("schema_version") != worker.RECEIPT_VERSION:
        raise LedgerError("Worker turn receipt version is not P3-compatible")
    if (
        turn.get("adapter_id") != adapter_manifest["adapter_id"]
        or turn.get("research_ir_sha256") != adapter_manifest["research_ir_sha256"]
        or turn.get("freeze_receipt_sha256") != adapter_manifest["freeze_receipt_sha256"]
        or turn.get("session_id") != adapter_manifest["session_id"]
        or turn.get("turn_index") != sequence
    ):
        raise LedgerError("Worker turn receipt identity differs from the bound Adapter or sequence")
    run_dir = Path(turn.get("run_dir", "")).resolve()
    expected_run_dir = (
        adapter_dir
        / "runs"
        / f"{sequence:06d}-{turn.get('task_id')}"
    ).resolve()
    if run_dir != expected_run_dir:
        raise LedgerError("Worker turn receipt run_dir differs from its Adapter sequence")

    contract_path = adapter_dir / "contracts" / "sha256" / f"{turn.get('task_contract_sha256')}.json"
    contract, contract_digest = _immutable_json(contract_path, "Worker task contract")
    if contract_digest != turn.get("task_contract_sha256"):
        raise LedgerError("Worker task contract digest differs from the turn receipt")
    try:
        ir = worker._load_ir_from_manifest(adapter_manifest)  # noqa: SLF001
        worker.validate_task_contract(contract, adapter_manifest, ir)
    except worker.AdapterError as exc:
        raise LedgerError(f"Worker task replay failed: {exc}") from exc
    if contract["task_id"] != turn.get("task_id"):
        raise LedgerError("Worker task_id differs from the turn receipt")
    experiment = next(
        (item for item in ir["experiment_plan"] if item["id"] == contract["experiment_id"]),
        None,
    )
    if experiment is None:
        raise LedgerError("frozen experiment disappeared")

    change_manifest, change_path = _bound_file(
        turn.get("change_manifest_path"),
        turn.get("change_manifest_sha256"),
        "P2 change manifest",
    )
    expected_change_name = (
        "change-manifest.json"
        if turn.get("outcome") in {"COMPLETED", "BLOCKED"}
        else "rejected-change-manifest.json"
    )
    if change_path != run_dir / expected_change_name:
        raise LedgerError("P2 change manifest is outside the exact turn run directory")
    if (
        change_manifest.get("base_commit") != adapter_manifest["base_commit"]
        or change_manifest.get("task_id") != contract["task_id"]
        or change_manifest.get("task_contract_sha256") != contract_digest
        or change_manifest.get("turn_index") != sequence
    ):
        raise LedgerError("P2 change manifest lineage differs")

    result: dict[str, Any] | None = None
    result_path: Path | None = None
    result_digest: str | None = None
    if turn.get("result_path") is not None or turn.get("result_sha256") is not None:
        result, result_path = _bound_file(
            turn.get("result_path"),
            turn.get("result_sha256"),
            "P2 Worker result",
        )
        if result_path != run_dir / "result.json":
            raise LedgerError("P2 Worker result is outside the exact turn run directory")
        result_digest = turn["result_sha256"]
        try:
            worker._validate_against_schema(  # noqa: SLF001
                result,
                worker.RESULT_SCHEMA_PATH,
                "Worker result",
            )
        except worker.AdapterError as exc:
            raise LedgerError(str(exc)) from exc
        if result.get("task_id") != contract["task_id"] or result.get("status") != turn.get("outcome"):
            raise LedgerError("P2 Worker result differs from the turn receipt")
    elif turn.get("outcome") in {"COMPLETED", "BLOCKED"}:
        raise LedgerError("successful or blocked P2 turn is missing its Worker result")

    if result is not None:
        changed = sorted([
            {
                "change_type": item.get("change_type"),
                "path": item.get("path"),
                "sha256": item.get("sha256"),
            }
            for item in change_manifest.get("changes", [])
        ], key=lambda item: item["path"])
        reported = sorted([
            {
                "change_type": item["change_type"],
                "path": item["path"],
                "sha256": item["sha256"],
            }
            for item in result["artifacts"]
        ], key=lambda item: item["path"])
        if changed != reported:
            raise LedgerError("P2 change manifest differs from the Worker result artifacts")

    commands = [] if result is None else result["commands_run"]
    planned_reported = any(
        item["argv"] == contract["command_argv"] and item["exit_code"] == 0
        for item in commands
    )
    if turn.get("outcome") == "COMPLETED" and not planned_reported:
        raise LedgerError("COMPLETED experiment does not report a successful frozen command")
    if turn.get("outcome") in {"COMPLETED", "BLOCKED"} and not turn.get("worker_model_verified"):
        raise LedgerError("delivered experiment lacks verified Worker model identity")

    inputs = _input_archive(turn, contract, run_dir)
    archived_inputs: list[dict[str, Any]] = []
    for item in contract["input_artifacts"]:
        p2_blob = Path(inputs[item["path"]]["blob_path"])
        archived_inputs.append({
            **item,
            "blob_path": _archive_blob(
                ledger_dir,
                p2_blob,
                item["sha256"],
                f"input artifact {item['path']}",
            ),
        })
    input_blobs = {item["path"]: item["blob_path"] for item in archived_inputs}

    context = contract["experiment_context"]
    archived_data = [
        {**item, "blob_path": input_blobs[item["path"]]}
        for item in context["data_artifacts"]
    ]
    archived_environment = [
        {**item, "blob_path": input_blobs[item["path"]]}
        for item in context["environment"]["artifacts"]
    ]

    artifacts: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    worktree = Path(adapter_manifest["worktree_root"]).resolve()
    if result is not None:
        for item in result["artifacts"]:
            source = worktree / item["path"]
            artifacts.append({
                **item,
                "blob_path": _archive_blob(
                    ledger_dir,
                    source,
                    item["sha256"],
                    f"Worker output {item['path']}",
                ),
            })
        known_blobs = {
            (item["path"], item["sha256"]): item["blob_path"]
            for item in (*archived_inputs, *artifacts)
        }
        for observation in result["observations"]:
            evidence: list[dict[str, str]] = []
            for item in observation["evidence"]:
                blob_path = known_blobs.get((item["path"], item["sha256"]))
                if blob_path is None:
                    blob_path = _archive_blob(
                        ledger_dir,
                        worktree / item["path"],
                        item["sha256"],
                        f"observation evidence {item['path']}",
                    )
                evidence.append({**item, "blob_path": blob_path})
            observations.append({"statement": observation["statement"], "evidence": evidence})

    try:
        worktree_head = worker._git_text(worktree, "rev-parse", "HEAD")  # noqa: SLF001
    except worker.AdapterError:
        worktree_head = None
    if turn.get("outcome") in {"COMPLETED", "BLOCKED"} and worktree_head != adapter_manifest["base_commit"]:
        raise LedgerError("successful or blocked experiment worktree HEAD drifted")

    usage = turn.get("usage")
    if not isinstance(usage, dict):
        raise LedgerError("Worker turn usage observation is missing")
    receipt = {
        "artifacts": artifacts,
        "execution": {
            "completed_at": turn["completed_at"],
            "failure_type": (
                "WORKER_BLOCKED"
                if turn.get("outcome") == "BLOCKED"
                else turn.get("failure")
            ),
            "planned_command_reported": planned_reported,
            "reported_commands": commands,
            "started_at": turn["started_at"],
            "status": turn["outcome"],
            "summary": None if result is None else result["summary"],
        },
        "experiment": {
            "expected_observation": experiment["expected_observation"],
            "hypothesis": experiment["hypothesis"],
            "id": experiment["id"],
            "stage": experiment["stage"],
        },
        "ledger_id": ledger_manifest["ledger_id"],
        "observations": observations,
        "previous_receipt_sha256": previous_digest,
        "provenance": {
            "adapter_id": adapter_manifest["adapter_id"],
            "adapter_manifest_sha256": ledger_manifest["adapter_manifest_sha256"],
            "change_manifest_path": str(change_path),
            "change_manifest_sha256": turn["change_manifest_sha256"],
            "data_artifacts": archived_data,
            "environment": {
                "artifacts": archived_environment,
                "description": context["environment"]["description"],
            },
            "freeze_receipt_sha256": adapter_manifest["freeze_receipt_sha256"],
            "input_artifacts": archived_inputs,
            "session_id": adapter_manifest["session_id"],
            "source_commit": adapter_manifest["base_commit"],
            "worker_model_argument": turn["worker_model_argument"],
            "worker_model_verified": turn["worker_model_verified"],
            "worker_result_path": None if result_path is None else str(result_path),
            "worker_result_sha256": result_digest,
            "worker_turn_receipt_path": str(turn_path),
            "worker_turn_receipt_sha256": turn_digest,
            "worktree_head": worktree_head,
            "worktree_root": str(worktree),
        },
        # A deterministic source timestamp makes publication recoverable when
        # the immutable object reaches disk but the JSONL append is interrupted.
        "recorded_at": turn["completed_at"],
        "research_ir": {
            "ir_id": ir["ir_id"],
            "sha256": adapter_manifest["research_ir_sha256"],
            "version": ir["version"],
        },
        "schema_version": RECEIPT_VERSION,
        "sequence": sequence,
        "task": {
            "command_argv": contract["command_argv"],
            "config": context["config"],
            "contract_path": str(contract_path),
            "contract_sha256": contract_digest,
            "id": contract["task_id"],
            "objective": contract["objective"],
            "seeds": context["seeds"],
        },
        "usage": {
            **usage,
            "complete": turn["usage_complete"],
        },
    }
    return _validate_receipt(receipt)


def _verify_receipt_object(
    *,
    ledger_dir: Path,
    ledger_manifest: Mapping[str, Any],
    adapter_manifest: Mapping[str, Any],
    entry: Mapping[str, Any],
    previous_digest: str | None,
) -> dict[str, Any]:
    digest = entry["receipt_sha256"]
    path = ledger_dir / "objects" / "sha256" / f"{digest}.json"
    receipt, actual = _immutable_json(path, "Experiment receipt object")
    if actual != digest:
        raise LedgerError("Experiment receipt object is not content addressed")
    _validate_receipt(receipt)
    if entry["receipt"] != receipt:
        raise LedgerError("JSONL Experiment Receipt differs from its immutable object")
    if (
        receipt["ledger_id"] != ledger_manifest["ledger_id"]
        or receipt["sequence"] != entry["sequence"]
        or receipt["previous_receipt_sha256"] != previous_digest
        or receipt["research_ir"]["sha256"] != ledger_manifest["research_ir_sha256"]
        or receipt["provenance"]["adapter_id"] != adapter_manifest["adapter_id"]
        or receipt["provenance"]["adapter_manifest_sha256"] != ledger_manifest["adapter_manifest_sha256"]
    ):
        raise LedgerError("Experiment receipt hash chain or Adapter identity changed")
    turn, turn_digest = _turn_receipt(
        adapter_dir=Path(ledger_manifest["adapter_dir"]),
        path=Path(receipt["provenance"]["worker_turn_receipt_path"]),
    )
    if (
        turn_digest != receipt["provenance"]["worker_turn_receipt_sha256"]
        or turn.get("turn_index") != receipt["sequence"]
        or turn.get("task_id") != receipt["task"]["id"]
        or turn.get("task_contract_sha256") != receipt["task"]["contract_sha256"]
        or turn.get("outcome") != receipt["execution"]["status"]
        or turn.get("completed_at") != receipt["recorded_at"]
    ):
        raise LedgerError("Experiment receipt no longer replays its P2 turn")
    provenance = receipt["provenance"]
    if (
        provenance["freeze_receipt_sha256"] != adapter_manifest["freeze_receipt_sha256"]
        or provenance["session_id"] != adapter_manifest["session_id"]
        or provenance["source_commit"] != adapter_manifest["base_commit"]
        or provenance["worktree_root"] != adapter_manifest["worktree_root"]
        or provenance["worker_model_argument"] != turn.get("worker_model_argument")
        or provenance["worker_model_verified"] != turn.get("worker_model_verified")
        or provenance["change_manifest_sha256"] != turn.get("change_manifest_sha256")
        or provenance["worker_result_sha256"] != turn.get("result_sha256")
    ):
        raise LedgerError("Experiment receipt provenance differs from the P2 turn")

    contract, contract_path = _bound_file(
        receipt["task"]["contract_path"],
        receipt["task"]["contract_sha256"],
        "recorded Worker task contract",
    )
    expected_contract_path = (
        Path(ledger_manifest["adapter_dir"])
        / "contracts"
        / "sha256"
        / f"{receipt['task']['contract_sha256']}.json"
    ).resolve()
    if contract_path != expected_contract_path:
        raise LedgerError("recorded Worker task contract is outside the Adapter store")
    try:
        ir = worker._load_ir_from_manifest(adapter_manifest)  # noqa: SLF001
        worker.validate_task_contract(contract, adapter_manifest, ir)
    except worker.AdapterError as exc:
        raise LedgerError(f"recorded Worker task replay failed: {exc}") from exc
    experiment = next(
        (item for item in ir["experiment_plan"] if item["id"] == contract["experiment_id"]),
        None,
    )
    context = contract["experiment_context"]
    if (
        experiment is None
        or receipt["research_ir"] != {
            "ir_id": ir["ir_id"],
            "sha256": adapter_manifest["research_ir_sha256"],
            "version": ir["version"],
        }
        or receipt["experiment"] != {
            "expected_observation": experiment["expected_observation"],
            "hypothesis": experiment["hypothesis"],
            "id": experiment["id"],
            "stage": experiment["stage"],
        }
        or receipt["task"]["id"] != contract["task_id"]
        or receipt["task"]["objective"] != contract["objective"]
        or receipt["task"]["command_argv"] != contract["command_argv"]
        or receipt["task"]["config"] != context["config"]
        or receipt["task"]["seeds"] != context["seeds"]
    ):
        raise LedgerError("Experiment receipt scientific/task fields differ from frozen inputs")

    change, change_path = _bound_file(
        provenance["change_manifest_path"],
        provenance["change_manifest_sha256"],
        "recorded P2 change manifest",
    )
    run_dir = Path(turn["run_dir"]).resolve()
    expected_change = (
        run_dir / "change-manifest.json"
        if turn["outcome"] in {"COMPLETED", "BLOCKED"}
        else run_dir / "rejected-change-manifest.json"
    )
    if (
        change_path != expected_change
        or change.get("base_commit") != adapter_manifest["base_commit"]
        or change.get("task_contract_sha256") != receipt["task"]["contract_sha256"]
        or change.get("task_id") != receipt["task"]["id"]
        or change.get("turn_index") != receipt["sequence"]
    ):
        raise LedgerError("recorded P2 change manifest lineage differs")

    result: dict[str, Any] | None = None
    if provenance["worker_result_path"] is not None:
        result, result_path = _bound_file(
            provenance["worker_result_path"],
            provenance["worker_result_sha256"],
            "recorded P2 Worker result",
        )
        if result_path != run_dir / "result.json":
            raise LedgerError("recorded P2 Worker result is outside its run directory")
        try:
            worker._validate_against_schema(  # noqa: SLF001
                result,
                worker.RESULT_SCHEMA_PATH,
                "Worker result",
            )
        except worker.AdapterError as exc:
            raise LedgerError(str(exc)) from exc
    elif provenance["worker_result_sha256"] is not None:
        raise LedgerError("recorded P2 Worker result path/hash nullability differs")

    if result is not None:
        changed = sorted([
            {
                "change_type": item.get("change_type"),
                "path": item.get("path"),
                "sha256": item.get("sha256"),
            }
            for item in change.get("changes", [])
        ], key=lambda item: item["path"])
        reported = sorted([
            {
                "change_type": item["change_type"],
                "path": item["path"],
                "sha256": item["sha256"],
            }
            for item in result["artifacts"]
        ], key=lambda item: item["path"])
        if changed != reported:
            raise LedgerError("recorded change manifest differs from result artifacts")

    expected_commands = [] if result is None else result["commands_run"]
    expected_summary = None if result is None else result["summary"]
    expected_planned = any(
        item["argv"] == contract["command_argv"] and item["exit_code"] == 0
        for item in expected_commands
    )
    expected_failure = (
        "WORKER_BLOCKED" if turn["outcome"] == "BLOCKED" else turn.get("failure")
    )
    if receipt["execution"] != {
        "completed_at": turn["completed_at"],
        "failure_type": expected_failure,
        "planned_command_reported": expected_planned,
        "reported_commands": expected_commands,
        "started_at": turn["started_at"],
        "status": turn["outcome"],
        "summary": expected_summary,
    }:
        raise LedgerError("Experiment receipt execution fields differ from the P2 turn")

    input_archive = _input_archive(turn, contract, run_dir)
    expected_inputs = [
        {
            **item,
            "blob_path": str(_blob_path(ledger_dir, item["sha256"])),
        }
        for item in contract["input_artifacts"]
    ]
    if provenance["input_artifacts"] != expected_inputs:
        raise LedgerError("Experiment receipt input provenance differs from the P2 archive")
    expected_by_path = {item["path"]: item["blob_path"] for item in expected_inputs}
    if provenance["data_artifacts"] != [
        {**item, "blob_path": expected_by_path[item["path"]]}
        for item in context["data_artifacts"]
    ] or provenance["environment"] != {
        "description": context["environment"]["description"],
        "artifacts": [
            {**item, "blob_path": expected_by_path[item["path"]]}
            for item in context["environment"]["artifacts"]
        ],
    }:
        raise LedgerError("Experiment receipt data/environment provenance differs")

    expected_artifacts = [] if result is None else [
        {**item, "blob_path": str(_blob_path(ledger_dir, item["sha256"]))}
        for item in result["artifacts"]
    ]
    expected_blob_by_identity = {
        (item["path"], item["sha256"]): item["blob_path"]
        for item in (*expected_inputs, *expected_artifacts)
    }
    expected_observations = [] if result is None else [
        {
            "statement": observation["statement"],
            "evidence": [
                {
                    **item,
                    "blob_path": expected_blob_by_identity.get(
                        (item["path"], item["sha256"]),
                        str(_blob_path(ledger_dir, item["sha256"])),
                    ),
                }
                for item in observation["evidence"]
            ],
        }
        for observation in result["observations"]
    ]
    if receipt["artifacts"] != expected_artifacts or receipt["observations"] != expected_observations:
        raise LedgerError("Experiment receipt artifacts/observations differ from the Worker result")
    if receipt["usage"] != {**turn["usage"], "complete": turn["usage_complete"]}:
        raise LedgerError("Experiment receipt usage differs from the P2 turn")

    for item in receipt["provenance"]["input_artifacts"]:
        _verify_blob(ledger_dir, item["blob_path"], item["sha256"])
    for item in receipt["provenance"]["data_artifacts"]:
        _verify_blob(ledger_dir, item["blob_path"], item["sha256"])
    for item in receipt["provenance"]["environment"]["artifacts"]:
        _verify_blob(ledger_dir, item["blob_path"], item["sha256"])
    for item in receipt["artifacts"]:
        _verify_blob(ledger_dir, item["blob_path"], item["sha256"])
    for observation in receipt["observations"]:
        for item in observation["evidence"]:
            _verify_blob(ledger_dir, item["blob_path"], item["sha256"])
    return receipt


def _verify_ledger(
    *,
    ledger_dir: Path,
    require_complete: bool,
    check_object_inventory: bool,
) -> dict[str, Any]:
    """Replay indexed lineage, optionally requiring every P2 turn and no orphans."""

    ledger_dir = ledger_dir.resolve()
    manifest, adapter_manifest, session = _ledger_manifest(ledger_dir)
    entries = _load_index(ledger_dir)
    previous: str | None = None
    receipts: list[dict[str, Any]] = []
    for entry in entries:
        receipts.append(_verify_receipt_object(
            ledger_dir=ledger_dir,
            ledger_manifest=manifest,
            adapter_manifest=adapter_manifest,
            entry=entry,
            previous_digest=previous,
        ))
        previous = entry["receipt_sha256"]
    if len(entries) > session["turn_count"]:
        raise LedgerError("Experiment Receipt ledger is ahead of the bound P2 session")
    if require_complete and len(entries) != session["turn_count"]:
        raise LedgerError(
            "Experiment Receipt ledger does not cover all terminal P2 turns: "
            f"recorded={len(entries)}, terminal_turns={session['turn_count']}"
        )
    if check_object_inventory:
        expected_objects = {entry["receipt_sha256"] for entry in entries}
        if _receipt_object_digests(ledger_dir) != expected_objects:
            raise LedgerError("Experiment Receipt object inventory differs from the JSONL index")
    return {
        "head_receipt_sha256": previous,
        "ledger_dir": str(ledger_dir),
        "ledger_id": manifest["ledger_id"],
        "record_count": len(receipts),
        "research_ir_sha256": manifest["research_ir_sha256"],
        "verified": True,
    }


def verify_ledger(*, ledger_dir: Path) -> dict[str, Any]:
    """Replay the complete P2 turn set, JSONL chain, objects, and evidence blobs."""

    return _verify_ledger(
        ledger_dir=ledger_dir,
        require_complete=True,
        check_object_inventory=True,
    )


def _append_index(path: Path, entry: Mapping[str, Any]) -> None:
    payload = _canonical_bytes(entry)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
    try:
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise LedgerError("short append to Experiment Receipt JSONL")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def record_turn(*, ledger_dir: Path, turn_receipt: Path) -> dict[str, Any]:
    """Append exactly the next P2 turn, or return its existing idempotent record."""

    ledger_dir = ledger_dir.resolve()
    lock_path = ledger_dir / ".ledger.lock"
    lock_path.touch(exist_ok=True)
    lock = lock_path.open("r+")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        manifest, adapter_manifest, _session = _ledger_manifest(ledger_dir)
        verified = _verify_ledger(
            ledger_dir=ledger_dir,
            require_complete=False,
            check_object_inventory=False,
        )
        entries = _load_index(ledger_dir)
        turn, turn_digest = _turn_receipt(
            adapter_dir=Path(manifest["adapter_dir"]),
            path=turn_receipt,
        )
        indexed_objects = {entry["receipt_sha256"] for entry in entries}
        actual_objects = _receipt_object_digests(ledger_dir)
        for entry in entries:
            receipt_path = ledger_dir / "objects" / "sha256" / f"{entry['receipt_sha256']}.json"
            existing = _load_json(receipt_path)
            if existing.get("provenance", {}).get("worker_turn_receipt_sha256") == turn_digest:
                if actual_objects != indexed_objects:
                    raise LedgerError(
                        "Experiment Receipt object inventory contains an unrelated unindexed object"
                    )
                return {
                    "already_recorded": True,
                    "ledger_id": manifest["ledger_id"],
                    "receipt_path": str(receipt_path),
                    "receipt_sha256": entry["receipt_sha256"],
                    "sequence": entry["sequence"],
                }
        sequence = len(entries) + 1
        if turn.get("turn_index") != sequence:
            raise LedgerError(
                f"P3 requires the next unskipped P2 turn: expected {sequence}, "
                f"received {turn.get('turn_index')}"
            )
        receipt = _build_receipt(
            ledger_dir=ledger_dir,
            ledger_manifest=manifest,
            adapter_manifest=adapter_manifest,
            turn_path=turn_receipt.resolve(),
            turn=turn,
            turn_digest=turn_digest,
            sequence=sequence,
            previous_digest=verified["head_receipt_sha256"],
        )
        digest = _sha256_bytes(_canonical_bytes(receipt))
        object_path = ledger_dir / "objects" / "sha256" / f"{digest}.json"
        if actual_objects not in (indexed_objects, indexed_objects | {digest}):
            raise LedgerError(
                "Experiment Receipt object inventory contains an unrelated unindexed object"
            )
        _publish_immutable_json(object_path, receipt)
        _append_index(ledger_dir / "experiment-receipts.jsonl", {
            "receipt": receipt,
            "receipt_sha256": digest,
            "schema_version": INDEX_VERSION,
            "sequence": sequence,
        })
        _verify_ledger(
            ledger_dir=ledger_dir,
            require_complete=False,
            check_object_inventory=True,
        )
        return {
            "already_recorded": False,
            "ledger_id": manifest["ledger_id"],
            "outcome": receipt["execution"]["status"],
            "receipt_path": str(object_path),
            "receipt_sha256": digest,
            "sequence": sequence,
        }
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def inspect_ledger(*, ledger_dir: Path) -> dict[str, Any]:
    return verify_ledger(ledger_dir=ledger_dir)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MVP-0 P3 Experiment Receipt ledger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="bind a new ledger to one P2 Adapter")
    init.add_argument("--adapter-dir", type=Path, required=True)
    init.add_argument("--ledger-dir", type=Path, required=True)

    record = subparsers.add_parser("record", help="append exactly the next P2 turn")
    record.add_argument("--ledger-dir", type=Path, required=True)
    record.add_argument("--turn-receipt", type=Path, required=True)

    for name in ("verify", "inspect"):
        command = subparsers.add_parser(name, help=f"{name} the complete ledger")
        command.add_argument("--ledger-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            result = initialize_ledger(adapter_dir=args.adapter_dir, ledger_dir=args.ledger_dir)
        elif args.command == "record":
            result = record_turn(ledger_dir=args.ledger_dir, turn_receipt=args.turn_receipt)
        elif args.command == "verify":
            result = verify_ledger(ledger_dir=args.ledger_dir)
        else:
            result = inspect_ledger(ledger_dir=args.ledger_dir)
    except (LedgerError, worker.AdapterError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
