#!/usr/bin/env python3
"""MVP-0 P5 evidence-bound Recompile Loop.

P5 turns one terminal P4 PIVOT/RECOMPILE decision into a closed failure
analysis and recompile request.  It can either select an already-frozen next
experiment or compile Research IR version N+1 into the existing P1 human review
workflow.  It never approves an IR, dispatches a Worker, or runs autonomously.
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
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from . import evidence_gate as gate
    from . import experiment_ledger as ledger
    from . import research_compiler as compiler
    from . import worker_adapter as worker
except ImportError:  # pragma: no cover - direct script execution
    import evidence_gate as gate  # type: ignore[no-redef]
    import experiment_ledger as ledger  # type: ignore[no-redef]
    import research_compiler as compiler  # type: ignore[no-redef]
    import worker_adapter as worker  # type: ignore[no-redef]


MVP_ROOT = Path(__file__).resolve().parent
ANALYSIS_SCHEMA_PATH = MVP_ROOT / "schemas" / "failure-analysis.schema.json"
REQUEST_SCHEMA_PATH = MVP_ROOT / "schemas" / "recompile-request.schema.json"
RECOMPILE_PROMPT_PATH = MVP_ROOT / "prompts" / "codex-recompile-analyst.md"
STORE_VERSION = "recompile-store/v1"
ANALYSIS_VERSION = "failure-analysis/v1"
REQUEST_VERSION = "recompile-request/v1"
ANALYSIS_RECORD_VERSION = "failure-analysis-record/v1"
REQUEST_RECORD_VERSION = "recompile-request-record/v1"
PROPOSAL_VERSION = "recompile-proposal/v1"
PROPOSAL_RECORD_VERSION = "recompile-proposal-record/v1"
FREEZE_VERSION = "recompile-freeze/v1"
DELEGATED_FREEZE_VERSION = "recompile-freeze/v2"
FREEZE_RECORD_VERSION = "recompile-freeze-record/v1"

IDENTITY_ROOTS = {"/schema_version", "/ir_id", "/version", "/parent_ir_sha256"}
SCIENTIFIC_ROOTS = {
    "/source",
    "/problem_statement",
    "/central_claim",
    "/falsification_conditions",
    "/related_work_gap",
    "/baseline_contract",
    "/metric_contract",
    "/evaluator_spec",
    "/allowed_search_space",
    "/forbidden_changes",
    "/experiment_plan",
    "/budget",
    "/stop_rules",
}
CODEX_IDENTITY_RE = re.compile(r"^codex/[a-zA-Z0-9][a-zA-Z0-9._/-]*$")


class RecompileError(RuntimeError):
    """A fail-closed P5 lineage, evidence, or versioning error."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return worker._canonical_bytes(value)  # noqa: SLF001
    except worker.AdapterError as exc:
        raise RecompileError(str(exc)) from exc


def _sha256_bytes(value: bytes) -> str:
    return worker._sha256_bytes(value)  # noqa: SLF001


def _sha256_file(path: Path) -> str:
    return worker._sha256_file(path)  # noqa: SLF001


def _load_json(path: Path) -> Any:
    try:
        return worker._load_json(path)  # noqa: SLF001
    except worker.AdapterError as exc:
        raise RecompileError(str(exc)) from exc


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RecompileError(f"invalid bound timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise RecompileError(f"bound timestamp lacks a timezone: {value!r}")
    return parsed


def _atomic_write(path: Path, payload: bytes, *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and (path.exists() or path.is_symlink()):
        raise RecompileError(f"immutable artifact already exists: {path}")
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


def _publish_json(path: Path, value: Any) -> None:
    payload = _canonical_bytes(value)
    if path.exists() or path.is_symlink():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_mode & 0o777 != 0o444
            or path.read_bytes() != payload
        ):
            raise RecompileError(f"content-addressed artifact collided or drifted: {path}")
        return
    _atomic_write(path, payload, immutable=True)


def _immutable_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o777 != 0o444:
        raise RecompileError(f"{label} is missing, mutable, or a symlink: {path}")
    value = _load_json(path)
    if not isinstance(value, dict):
        raise RecompileError(f"{label} must be a JSON object")
    return value, _sha256_file(path)


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise RecompileError(
            f"{label} fields differ: missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _validate(value: Any, schema_path: Path, label: str) -> dict[str, Any]:
    try:
        worker._validate_against_schema(value, schema_path, label)  # noqa: SLF001
    except worker.AdapterError as exc:
        raise RecompileError(str(exc)) from exc
    if not isinstance(value, dict):
        raise RecompileError(f"{label} must be a JSON object")
    return value


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@contextmanager
def _store_lease(store_dir: Path):
    lock_path = store_dir.resolve() / ".recompile.lock"
    lock_path.touch(exist_ok=True)
    handle = lock_path.open("r+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _gate_snapshot(gate_store: Path) -> tuple[list[dict[str, Any]], str]:
    records: list[dict[str, Any]] = []
    for record, _record_path in gate._records(gate_store):  # noqa: SLF001
        decision_path = Path(record["decision_path"])
        decision, digest = _immutable_json(decision_path, "P4 decision")
        if digest != record["decision_sha256"]:
            raise RecompileError("P4 decision record digest differs")
        records.append({
            "decision": decision,
            "record": record,
        })
    records.sort(key=lambda item: item["decision"]["experiment_receipt"]["sequence"])
    return records, _sha256_bytes(_canonical_bytes(records))


def initialize_store(*, gate_store: Path, store_dir: Path) -> dict[str, Any]:
    """Freeze one complete P4 prefix as the only parent of this P5 store."""

    gate_store = gate_store.resolve()
    try:
        gate.verify_store(store_dir=gate_store)
        gate_manifest, ledger_manifest, ir = gate._store_manifest(gate_store)  # noqa: SLF001
        _ledger_manifest, adapter_manifest, _session = ledger._ledger_manifest(  # noqa: SLF001
            Path(gate_manifest["ledger_dir"])
        )
    except (gate.GateError, ledger.LedgerError, worker.AdapterError) as exc:
        raise RecompileError(f"P4 replay failed: {exc}") from exc
    records, snapshot_digest = _gate_snapshot(gate_store)
    if not records:
        raise RecompileError("P5 requires at least one P4 decision")
    latest = records[-1]["decision"]
    if latest["decision"] not in {"PIVOT", "RECOMPILE"}:
        raise RecompileError("P5 starts only from the latest PIVOT or RECOMPILE decision")

    compiler_store = Path(adapter_manifest["compiler_store"]).resolve()
    freeze_path = Path(adapter_manifest["freeze_receipt_path"]).resolve()
    try:
        verified = compiler.verify_freeze(
            receipt_path=freeze_path,
            store=compiler_store,
            check_paths=False,
        )
    except compiler.CompilerError as exc:
        raise RecompileError(f"parent P1 freeze replay failed: {exc}") from exc
    if (
        verified["freeze_receipt_sha256"] != adapter_manifest["freeze_receipt_sha256"]
        or verified["research_ir_sha256"] != gate_manifest["research_ir_sha256"]
    ):
        raise RecompileError("P5 parent freeze differs from the P2–P4 lineage")

    store_dir = store_dir.resolve()
    if store_dir.exists() or store_dir.is_symlink():
        raise RecompileError("store_dir already exists")
    protected = (
        gate_store,
        Path(gate_manifest["ledger_dir"]).resolve(),
        Path(ledger_manifest["adapter_dir"]).resolve(),
        Path(adapter_manifest["source_repo"]).resolve(),
        Path(adapter_manifest["worktree_root"]).resolve(),
        compiler_store,
    )
    if any(_inside(store_dir, root) or _inside(root, store_dir) for root in protected):
        raise RecompileError("store_dir overlaps a bound P1–P4 path")

    store_dir.parent.mkdir(parents=True, exist_ok=True)
    store_dir.mkdir()
    try:
        manifest = {
            "analysis_schema_sha256": _sha256_file(ANALYSIS_SCHEMA_PATH),
            "compiler_prompt_sha256": _sha256_file(compiler.COMPILER_PROMPT_PATH),
            "compiler_store": str(compiler_store),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            ),
            "gate_decision_count": len(records),
            "gate_id": gate_manifest["gate_id"],
            "gate_manifest_path": str(gate_store / "gate-manifest.json"),
            "gate_manifest_sha256": _sha256_file(gate_store / "gate-manifest.json"),
            "gate_records_sha256": snapshot_digest,
            "gate_store": str(gate_store),
            "latest_gate_decision_sha256": records[-1]["record"]["decision_sha256"],
            "p5_id": "mvp0-recompile-" + uuid.uuid4().hex[:16],
            "parent_freeze_receipt_path": str(freeze_path),
            "parent_freeze_receipt_sha256": adapter_manifest["freeze_receipt_sha256"],
            "parent_ir_id": ir["ir_id"],
            "parent_ir_sha256": gate_manifest["research_ir_sha256"],
            "parent_ir_version": ir["version"],
            "recompile_prompt_sha256": _sha256_file(RECOMPILE_PROMPT_PATH),
            "request_schema_sha256": _sha256_file(REQUEST_SCHEMA_PATH),
            "research_ir_schema_sha256": _sha256_file(compiler.SCHEMA_PATH),
            "schema_version": STORE_VERSION,
            "semantic_validator_sha256": compiler.semantic_validator_sha256(),
        }
        _publish_json(store_dir / "recompile-manifest.json", manifest)
        for relative in (
            "analyses/sha256",
            "analysis-records/by-decision",
            "requests/sha256",
            "request-records/by-decision",
            "proposals/sha256",
            "proposal-records/by-request",
            "freezes/sha256",
            "freeze-records/by-proposal",
        ):
            (store_dir / relative).mkdir(parents=True)
    except Exception:
        shutil.rmtree(store_dir)
        raise
    return {
        "latest_gate_decision_sha256": manifest["latest_gate_decision_sha256"],
        "p5_id": manifest["p5_id"],
        "parent_ir_sha256": manifest["parent_ir_sha256"],
        "parent_ir_version": manifest["parent_ir_version"],
        "store_dir": str(store_dir),
    }


def _manifest(store_dir: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    manifest, _digest = _immutable_json(
        store_dir / "recompile-manifest.json", "P5 manifest"
    )
    _exact_keys(manifest, {
        "analysis_schema_sha256",
        "compiler_prompt_sha256",
        "compiler_store",
        "created_at",
        "gate_decision_count",
        "gate_id",
        "gate_manifest_path",
        "gate_manifest_sha256",
        "gate_records_sha256",
        "gate_store",
        "latest_gate_decision_sha256",
        "p5_id",
        "parent_freeze_receipt_path",
        "parent_freeze_receipt_sha256",
        "parent_ir_id",
        "parent_ir_sha256",
        "parent_ir_version",
        "recompile_prompt_sha256",
        "request_schema_sha256",
        "research_ir_schema_sha256",
        "schema_version",
        "semantic_validator_sha256",
    }, "P5 manifest")
    if manifest["schema_version"] != STORE_VERSION:
        raise RecompileError("P5 store version is unsupported")
    local_hashes = {
        "analysis_schema_sha256": _sha256_file(ANALYSIS_SCHEMA_PATH),
        "compiler_prompt_sha256": _sha256_file(compiler.COMPILER_PROMPT_PATH),
        "recompile_prompt_sha256": _sha256_file(RECOMPILE_PROMPT_PATH),
        "request_schema_sha256": _sha256_file(REQUEST_SCHEMA_PATH),
        "research_ir_schema_sha256": _sha256_file(compiler.SCHEMA_PATH),
        "semantic_validator_sha256": compiler.semantic_validator_sha256(),
    }
    if any(manifest[key] != value for key, value in local_hashes.items()):
        raise RecompileError("P5 compiler, prompt, or schema drifted after initialization")

    gate_store = Path(manifest["gate_store"]).resolve()
    if (
        Path(manifest["gate_manifest_path"]).resolve() != gate_store / "gate-manifest.json"
        or _sha256_file(gate_store / "gate-manifest.json") != manifest["gate_manifest_sha256"]
    ):
        raise RecompileError("P5 Gate manifest binding changed")
    try:
        gate.verify_store(store_dir=gate_store)
        gate_manifest, _ledger_manifest, ir = gate._store_manifest(gate_store)  # noqa: SLF001
    except (gate.GateError, ledger.LedgerError, worker.AdapterError) as exc:
        raise RecompileError(f"bound P4 replay failed: {exc}") from exc
    records, _current_snapshot = _gate_snapshot(gate_store)
    frozen_count = manifest["gate_decision_count"]
    if not isinstance(frozen_count, int) or isinstance(frozen_count, bool) or frozen_count < 1:
        raise RecompileError("P5 Gate decision count is invalid")
    if len(records) < frozen_count:
        raise RecompileError("P4 history was truncated below the P5 snapshot")
    frozen_records = records[:frozen_count]
    snapshot = _sha256_bytes(_canonical_bytes(frozen_records))
    if (
        gate_manifest["gate_id"] != manifest["gate_id"]
        or snapshot != manifest["gate_records_sha256"]
        or frozen_records[-1]["record"]["decision_sha256"]
        != manifest["latest_gate_decision_sha256"]
        or gate_manifest["research_ir_sha256"] != manifest["parent_ir_sha256"]
        or ir["ir_id"] != manifest["parent_ir_id"]
        or ir["version"] != manifest["parent_ir_version"]
    ):
        raise RecompileError("P5 frozen P4 prefix or parent IR changed")
    try:
        verified = compiler.verify_freeze(
            receipt_path=Path(manifest["parent_freeze_receipt_path"]),
            store=Path(manifest["compiler_store"]),
            check_paths=False,
        )
    except compiler.CompilerError as exc:
        raise RecompileError(f"bound parent freeze replay failed: {exc}") from exc
    if (
        verified["freeze_receipt_sha256"] != manifest["parent_freeze_receipt_sha256"]
        or verified["research_ir_sha256"] != manifest["parent_ir_sha256"]
    ):
        raise RecompileError("P5 parent freeze binding changed")
    return manifest, ir, frozen_records


def _latest_decision(
    manifest: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    latest = records[-1]
    record = latest["record"]
    decision = latest["decision"]
    if record["decision_sha256"] != manifest["latest_gate_decision_sha256"]:
        raise RecompileError("P5 latest decision binding changed")
    if decision["decision"] not in {"PIVOT", "RECOMPILE"}:
        raise RecompileError("P5 latest decision is not eligible")
    return decision, record


def _decision_prefix(
    manifest: Mapping[str, Any], decision: Mapping[str, Any]
) -> list[dict[str, Any]]:
    gate_store = Path(manifest["gate_store"])
    gate_manifest, _ledger_manifest, _ir = gate._store_manifest(gate_store)  # noqa: SLF001
    _receipt, _path, prefix = gate._receipt(  # noqa: SLF001
        store_manifest=gate_manifest,
        digest=decision["experiment_receipt"]["sha256"],
    )
    return prefix


def _known_evidence(prefix: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], str]:
    known: dict[tuple[str, str], str] = {}
    for entry in prefix:
        receipt_known = gate._known_receipt_artifacts(entry["receipt"])  # noqa: SLF001
        for identity, blob_path in receipt_known.items():
            prior = known.get(identity)
            if prior is not None and prior != blob_path:
                raise RecompileError("P3 prefix maps one evidence identity to multiple blobs")
            known[identity] = blob_path
    return known


def _validate_analysis(
    *,
    value: Any,
    manifest: Mapping[str, Any],
    decision: Mapping[str, Any],
    decision_record: Mapping[str, Any],
) -> dict[str, Any]:
    analysis = _validate(value, ANALYSIS_SCHEMA_PATH, "Failure analysis")
    if analysis["schema_version"] != ANALYSIS_VERSION:
        raise RecompileError("Failure analysis version is unsupported")
    if (
        analysis["research_ir_sha256"] != manifest["parent_ir_sha256"]
        or analysis["evidence_gate_decision_sha256"] != decision_record["decision_sha256"]
        or analysis["experiment_receipt_sha256"]
        != decision["experiment_receipt"]["sha256"]
        or analysis["gate_decision"] != decision["decision"]
        or analysis["gate_reason_codes"] != decision["reason_codes"]
    ):
        raise RecompileError("Failure analysis differs from the frozen P4 decision")
    if _parse_time(analysis["analyzed_at"]) < _parse_time(decision["decided_at"]):
        raise RecompileError("Failure analysis predates its P4 decision")

    prefix = _decision_prefix(manifest, decision)
    expected_receipts = [entry["receipt_sha256"] for entry in prefix]
    attempts = analysis["attempted_directions"]
    actual_receipts = [item["experiment_receipt_sha256"] for item in attempts]
    if actual_receipts != expected_receipts:
        raise RecompileError("Failure analysis must cover the exact ordered P3 prefix")
    evidence_by_digest = {item["sha256"]: item for item in analysis["evidence"]}
    if len(evidence_by_digest) != len(analysis["evidence"]):
        raise RecompileError("Failure analysis duplicates an evidence digest")
    known = _known_evidence(prefix)
    gate_manifest, _ledger_manifest, _ir = gate._store_manifest(  # noqa: SLF001
        Path(manifest["gate_store"])
    )
    ledger_dir = Path(gate_manifest["ledger_dir"])
    for item in analysis["evidence"]:
        if known.get((item["path"], item["sha256"])) != item["blob_path"]:
            raise RecompileError("Failure analysis cites evidence outside the P3 prefix")
        try:
            ledger._verify_blob(  # noqa: SLF001
                ledger_dir, item["blob_path"], item["sha256"]
            )
        except ledger.LedgerError as exc:
            raise RecompileError(f"Failure analysis evidence replay failed: {exc}") from exc

    cited: set[str] = set()
    for attempt, entry in zip(attempts, prefix, strict=True):
        receipt = entry["receipt"]
        if (
            attempt["experiment_id"] != receipt["experiment"]["id"]
            or attempt["outcome"] != receipt["execution"]["status"]
        ):
            raise RecompileError("Failure analysis attempt identity differs from P3")
        allowed = {sha for _path, sha in gate._known_receipt_artifacts(receipt)}  # noqa: SLF001
        if any(digest not in allowed for digest in attempt["evidence_sha256s"]):
            raise RecompileError("Failure analysis attempt cites another receipt's evidence")
        cited.update(attempt["evidence_sha256s"])
    if cited != set(evidence_by_digest):
        raise RecompileError("Failure analysis evidence must equal the union cited by attempts")
    return analysis


def _record_map(
    root: Path, label: str, expected_keys: set[str], key_field: str
) -> list[dict[str, Any]]:
    if root.is_symlink() or not root.is_dir():
        raise RecompileError(f"{label} directory is missing or a symlink")
    values: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()):
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix != ".json"
            or not ledger.SHA256_RE.fullmatch(path.stem)
        ):
            raise RecompileError(f"invalid {label} record: {path}")
        value, _digest = _immutable_json(path, label)
        _exact_keys(value, expected_keys, label)
        if value.get(key_field) != path.stem:
            raise RecompileError(f"{label} filename differs from {key_field}")
        values.append(value)
    return values


def _analysis_records(store_dir: Path) -> list[dict[str, Any]]:
    return _record_map(
        store_dir / "analysis-records" / "by-decision",
        "Failure analysis mapping",
        {
            "analysis_path",
            "analysis_sha256",
            "decision_sha256",
            "schema_version",
        },
        "decision_sha256",
    )


def _request_records(store_dir: Path) -> list[dict[str, Any]]:
    return _record_map(
        store_dir / "request-records" / "by-decision",
        "Recompile request mapping",
        {
            "analysis_sha256",
            "decision_sha256",
            "request_path",
            "request_sha256",
            "schema_version",
        },
        "decision_sha256",
    )


def _proposal_records(store_dir: Path) -> list[dict[str, Any]]:
    return _record_map(
        store_dir / "proposal-records" / "by-request",
        "Recompile proposal mapping",
        {
            "proposal_path",
            "proposal_sha256",
            "request_sha256",
            "schema_version",
        },
        "request_sha256",
    )


def _freeze_records(store_dir: Path) -> list[dict[str, Any]]:
    return _record_map(
        store_dir / "freeze-records" / "by-proposal",
        "Recompile freeze mapping",
        {
            "freeze_path",
            "freeze_sha256",
            "proposal_sha256",
            "schema_version",
        },
        "proposal_sha256",
    )


def _object_digests(root: Path) -> set[str]:
    if root.is_symlink() or not root.is_dir():
        raise RecompileError(f"P5 object directory is missing or a symlink: {root}")
    result: set[str] = set()
    for path in root.iterdir():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix != ".json"
            or not ledger.SHA256_RE.fullmatch(path.stem)
            or path.stat().st_mode & 0o777 != 0o444
        ):
            raise RecompileError(f"invalid P5 object-store entry: {path}")
        result.add(path.stem)
    return result


def _allow_recovery(actual: set[str], indexed: set[str], current: str, label: str) -> None:
    if actual not in (indexed, indexed | {current}):
        raise RecompileError(f"{label} contains an unrelated unindexed object")


def _publish_analysis_unlocked(*, store_dir: Path, analysis_path: Path) -> dict[str, Any]:
    """Publish the single strong-model analysis for the frozen latest P4 decision."""

    store_dir = store_dir.resolve()
    manifest, _ir, records = _manifest(store_dir)
    _verify_store(store_dir=store_dir, strict_inventory=False)
    decision, decision_record = _latest_decision(manifest, records)
    analysis = _validate_analysis(
        value=_load_json(analysis_path),
        manifest=manifest,
        decision=decision,
        decision_record=decision_record,
    )
    digest = _sha256_bytes(_canonical_bytes(analysis))
    object_path = store_dir / "analyses" / "sha256" / f"{digest}.json"
    record_path = (
        store_dir
        / "analysis-records"
        / "by-decision"
        / f"{decision_record['decision_sha256']}.json"
    )
    if record_path.exists() or record_path.is_symlink():
        record, _record_digest = _immutable_json(record_path, "Failure analysis mapping")
        if record.get("analysis_sha256") != digest:
            raise RecompileError("latest P4 decision already binds a different analysis")
        verify_store(store_dir=store_dir)
        return {
            "already_published": True,
            "analysis_path": record["analysis_path"],
            "analysis_sha256": digest,
            "decision_sha256": decision_record["decision_sha256"],
            "stage": "ANALYZED",
        }
    indexed = {item["analysis_sha256"] for item in _analysis_records(store_dir)}
    _allow_recovery(
        _object_digests(store_dir / "analyses" / "sha256"), indexed, digest, "Analysis store"
    )
    _publish_json(object_path, analysis)
    _publish_json(record_path, {
        "analysis_path": str(object_path),
        "analysis_sha256": digest,
        "decision_sha256": decision_record["decision_sha256"],
        "schema_version": ANALYSIS_RECORD_VERSION,
    })
    verify_store(store_dir=store_dir)
    return {
        "already_published": False,
        "analysis_path": str(object_path),
        "analysis_sha256": digest,
        "decision_sha256": decision_record["decision_sha256"],
        "stage": "ANALYZED",
    }


def _load_analysis_for_decision(
    store_dir: Path, decision_sha256: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    matches = [
        item for item in _analysis_records(store_dir) if item["decision_sha256"] == decision_sha256
    ]
    if len(matches) != 1:
        raise RecompileError("latest P4 decision does not have exactly one failure analysis")
    record = matches[0]
    analysis, digest = _immutable_json(Path(record["analysis_path"]), "Failure analysis")
    if digest != record["analysis_sha256"]:
        raise RecompileError("Failure analysis mapping digest differs")
    return analysis, record


def _validate_request(
    *,
    value: Any,
    analysis: Mapping[str, Any],
    analysis_digest: str,
    manifest: Mapping[str, Any],
    ir: Mapping[str, Any],
    decision: Mapping[str, Any],
    decision_record: Mapping[str, Any],
) -> dict[str, Any]:
    request = _validate(value, REQUEST_SCHEMA_PATH, "Recompile request")
    if request["schema_version"] != REQUEST_VERSION:
        raise RecompileError("Recompile request version is unsupported")
    if (
        request["failure_analysis_sha256"] != analysis_digest
        or request["evidence_gate_decision_sha256"] != decision_record["decision_sha256"]
        or request["parent_freeze_receipt_sha256"]
        != manifest["parent_freeze_receipt_sha256"]
        or request["current_ir"]
        != {
            "ir_id": manifest["parent_ir_id"],
            "sha256": manifest["parent_ir_sha256"],
            "version": manifest["parent_ir_version"],
        }
        or request["problem"] != analysis["problem"]
        or request["attempted_receipt_sha256s"]
        != [item["experiment_receipt_sha256"] for item in analysis["attempted_directions"]]
        or request["evidence_sha256s"]
        != [item["sha256"] for item in analysis["evidence"]]
        or request["new_questions"] != analysis["new_questions"]
    ):
        raise RecompileError("Recompile request omits or changes its analysis/P1–P4 lineage")
    if _parse_time(request["requested_at"]) < _parse_time(analysis["analyzed_at"]):
        raise RecompileError("Recompile request predates its failure analysis")

    change_paths = [item["path"] for item in request["requested_changes"]]
    retained = request["retained_constraints"]
    if len(change_paths) != len(set(change_paths)):
        raise RecompileError("Recompile request duplicates a requested change path")
    if any(path not in SCIENTIFIC_ROOTS for path in change_paths):
        raise RecompileError("Recompile request changes an identity or unknown IR root")
    if any(path not in SCIENTIFIC_ROOTS for path in retained):
        raise RecompileError("Recompile request retains an identity or unknown IR root")
    if set(change_paths) & set(retained):
        raise RecompileError("A contract root cannot be both changed and retained")

    if request["disposition"] == "CONTINUE_CURRENT_IR":
        if decision["decision"] != "PIVOT":
            raise RecompileError("Only a PIVOT decision may continue the current IR")
        if change_paths or request["continuation_experiment_id"] is None:
            raise RecompileError("Continuation requires no IR changes and one experiment ID")
        prefix = _decision_prefix(manifest, decision)
        attempted = {entry["receipt"]["experiment"]["id"] for entry in prefix}
        completed = {
            entry["receipt"]["experiment"]["id"]
            for entry in prefix
            if entry["receipt"]["execution"]["status"] == "COMPLETED"
        }
        experiments = {item["id"]: item for item in ir["experiment_plan"]}
        selected = experiments.get(request["continuation_experiment_id"])
        if selected is None or selected["id"] in attempted:
            raise RecompileError("Continuation experiment is unknown or already attempted")
        required: set[str] = set()
        pending = list(selected["depends_on"])
        while pending:
            dependency = pending.pop()
            if dependency in required:
                continue
            required.add(dependency)
            pending.extend(experiments[dependency]["depends_on"])
        if not required.issubset(completed):
            raise RecompileError("Continuation experiment transitive dependencies are not completed")
    else:
        if not change_paths or request["continuation_experiment_id"] is not None:
            raise RecompileError("IR recompilation requires change roots and no continuation ID")
    return request


def _publish_request_unlocked(*, store_dir: Path, request_path: Path) -> dict[str, Any]:
    """Publish one decision-bound continuation or IR-recompile request."""

    store_dir = store_dir.resolve()
    manifest, ir, records = _manifest(store_dir)
    _verify_store(store_dir=store_dir, strict_inventory=False)
    decision, decision_record = _latest_decision(manifest, records)
    analysis, analysis_record = _load_analysis_for_decision(
        store_dir, decision_record["decision_sha256"]
    )
    request = _validate_request(
        value=_load_json(request_path),
        analysis=analysis,
        analysis_digest=analysis_record["analysis_sha256"],
        manifest=manifest,
        ir=ir,
        decision=decision,
        decision_record=decision_record,
    )
    digest = _sha256_bytes(_canonical_bytes(request))
    object_path = store_dir / "requests" / "sha256" / f"{digest}.json"
    record_path = (
        store_dir
        / "request-records"
        / "by-decision"
        / f"{decision_record['decision_sha256']}.json"
    )
    if record_path.exists() or record_path.is_symlink():
        record, _record_digest = _immutable_json(record_path, "Recompile request mapping")
        if record.get("request_sha256") != digest:
            raise RecompileError("latest P4 decision already binds a different request")
        verify_store(store_dir=store_dir)
        return {
            "already_published": True,
            "disposition": request["disposition"],
            "request_path": record["request_path"],
            "request_sha256": digest,
            "stage": request["disposition"],
        }
    indexed = {item["request_sha256"] for item in _request_records(store_dir)}
    _allow_recovery(
        _object_digests(store_dir / "requests" / "sha256"), indexed, digest, "Request store"
    )
    _publish_json(object_path, request)
    _publish_json(record_path, {
        "analysis_sha256": analysis_record["analysis_sha256"],
        "decision_sha256": decision_record["decision_sha256"],
        "request_path": str(object_path),
        "request_sha256": digest,
        "schema_version": REQUEST_RECORD_VERSION,
    })
    verify_store(store_dir=store_dir)
    return {
        "already_published": False,
        "continuation_experiment_id": request["continuation_experiment_id"],
        "disposition": request["disposition"],
        "request_path": str(object_path),
        "request_sha256": digest,
        "stage": request["disposition"],
    }


def _load_request(store_dir: Path, digest: str) -> tuple[dict[str, Any], dict[str, Any]]:
    matches = [item for item in _request_records(store_dir) if item["request_sha256"] == digest]
    if len(matches) != 1:
        raise RecompileError("request digest is not indexed exactly once")
    record = matches[0]
    request, actual = _immutable_json(Path(record["request_path"]), "Recompile request")
    if actual != digest:
        raise RecompileError("Recompile request mapping digest differs")
    return request, record


def _changed_roots(parent: Mapping[str, Any], child: Mapping[str, Any]) -> set[str]:
    return {
        f"/{key}"
        for key in parent
        if key not in {"version", "parent_ir_sha256"} and parent[key] != child[key]
    }


def _validate_candidate(
    *, parent: Mapping[str, Any], candidate: Any, request: Mapping[str, Any], manifest: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(candidate, dict):
        raise RecompileError("candidate Research IR must be a JSON object")
    try:
        compiler._assert_valid_ir(candidate, check_paths=True)  # noqa: SLF001
    except compiler.CompilerError as exc:
        raise RecompileError(f"candidate Research IR is invalid: {exc}") from exc
    if (
        candidate["ir_id"] != parent["ir_id"]
        or candidate["version"] != parent["version"] + 1
        or candidate["parent_ir_sha256"] != manifest["parent_ir_sha256"]
        or candidate["schema_version"] != parent["schema_version"]
        or candidate["source"]["source_task_id"] != parent["source"]["source_task_id"]
        or candidate["source"]["workspace_root"] != parent["source"]["workspace_root"]
        or candidate["source"]["code_root"] != parent["source"]["code_root"]
    ):
        raise RecompileError("candidate Research IR version or project identity is invalid")
    changed = _changed_roots(parent, candidate)
    requested = {item["path"] for item in request["requested_changes"]}
    if changed != requested:
        raise RecompileError(
            f"candidate changed roots differ from request: changed={sorted(changed)}, "
            f"requested={sorted(requested)}"
        )
    for pointer in request["retained_constraints"]:
        key = pointer[1:]
        if candidate[key] != parent[key]:
            raise RecompileError(f"candidate changed retained constraint {pointer}")
    return candidate, sorted(changed)


def _compile_candidate_unlocked(
    *, store_dir: Path, request_sha256: str, candidate_ir: Path, author: str
) -> dict[str, Any]:
    """Compile IR N+1 into P1 and stop at AWAITING_HUMAN_CRITIQUE."""

    if not ledger.SHA256_RE.fullmatch(request_sha256):
        raise RecompileError("request_sha256 must be lowercase SHA-256")
    if CODEX_IDENTITY_RE.fullmatch(author) is None:
        raise RecompileError("P5 compiler author must use the codex/<identity> namespace")
    store_dir = store_dir.resolve()
    manifest, parent, _records = _manifest(store_dir)
    _verify_store(store_dir=store_dir, strict_inventory=False)
    request, _request_record = _load_request(store_dir, request_sha256)
    if request["disposition"] != "RECOMPILE_IR":
        raise RecompileError("CONTINUE_CURRENT_IR does not compile a new Research IR")
    candidate, changed = _validate_candidate(
        parent=parent,
        candidate=_load_json(candidate_ir),
        request=request,
        manifest=manifest,
    )
    candidate_digest = _sha256_bytes(_canonical_bytes(candidate))
    existing_path = store_dir / "proposal-records" / "by-request" / f"{request_sha256}.json"
    if existing_path.exists() or existing_path.is_symlink():
        mapping, _mapping_digest = _immutable_json(existing_path, "Recompile proposal mapping")
        proposal, _proposal_digest = _immutable_json(
            Path(mapping["proposal_path"]), "Recompile proposal"
        )
        if proposal.get("child_ir_sha256") != candidate_digest or proposal.get("author") != author:
            raise RecompileError("request already binds a different candidate or author")
        verify_store(store_dir=store_dir)
        return {
            "already_compiled": True,
            "compiler_proposal_path": proposal["compiler_proposal_path"],
            "compiler_proposal_sha256": proposal["compiler_proposal_sha256"],
            "proposal_path": mapping["proposal_path"],
            "proposal_sha256": mapping["proposal_sha256"],
            "research_ir_path": proposal["child_ir_path"],
            "research_ir_sha256": proposal["child_ir_sha256"],
            "stage": "AWAITING_HUMAN_CRITIQUE",
        }

    compiler_result = compiler.propose(
        ir_path=candidate_ir,
        store=Path(manifest["compiler_store"]),
        author=author,
        recorded_at=request["requested_at"],
    )
    proposal = {
        "author": author,
        "changed_roots": changed,
        "child_ir_path": compiler_result["research_ir_path"],
        "child_ir_sha256": compiler_result["research_ir_sha256"],
        "child_ir_version": candidate["version"],
        "compiled_at": request["requested_at"],
        "compiler_proposal_path": compiler_result["proposal_path"],
        "compiler_proposal_sha256": compiler_result["proposal_sha256"],
        "parent_freeze_receipt_sha256": manifest["parent_freeze_receipt_sha256"],
        "parent_ir_sha256": manifest["parent_ir_sha256"],
        "request_sha256": request_sha256,
        "schema_version": PROPOSAL_VERSION,
    }
    digest = _sha256_bytes(_canonical_bytes(proposal))
    object_path = store_dir / "proposals" / "sha256" / f"{digest}.json"
    indexed = {item["proposal_sha256"] for item in _proposal_records(store_dir)}
    _allow_recovery(
        _object_digests(store_dir / "proposals" / "sha256"), indexed, digest, "Proposal store"
    )
    _publish_json(object_path, proposal)
    _publish_json(existing_path, {
        "proposal_path": str(object_path),
        "proposal_sha256": digest,
        "request_sha256": request_sha256,
        "schema_version": PROPOSAL_RECORD_VERSION,
    })
    verify_store(store_dir=store_dir)
    return {
        "already_compiled": False,
        "compiler_proposal_path": proposal["compiler_proposal_path"],
        "compiler_proposal_sha256": proposal["compiler_proposal_sha256"],
        "proposal_path": str(object_path),
        "proposal_sha256": digest,
        "research_ir_path": proposal["child_ir_path"],
        "research_ir_sha256": proposal["child_ir_sha256"],
        "stage": "AWAITING_HUMAN_CRITIQUE",
    }


def _validate_proposal(
    *, store_dir: Path, value: Mapping[str, Any], manifest: Mapping[str, Any], parent: Mapping[str, Any]
) -> dict[str, Any]:
    _exact_keys(value, {
        "author",
        "changed_roots",
        "child_ir_path",
        "child_ir_sha256",
        "child_ir_version",
        "compiled_at",
        "compiler_proposal_path",
        "compiler_proposal_sha256",
        "parent_freeze_receipt_sha256",
        "parent_ir_sha256",
        "request_sha256",
        "schema_version",
    }, "Recompile proposal")
    if (
        value["schema_version"] != PROPOSAL_VERSION
        or CODEX_IDENTITY_RE.fullmatch(value["author"]) is None
    ):
        raise RecompileError("Recompile proposal identity is invalid")
    request, _record = _load_request(store_dir, value["request_sha256"])
    if request["disposition"] != "RECOMPILE_IR":
        raise RecompileError("Recompile proposal descends from a continuation request")
    child, child_digest = _immutable_json(Path(value["child_ir_path"]), "child Research IR")
    expected_child_path = (
        Path(manifest["compiler_store"]) / "objects" / "sha256" / f"{child_digest}.json"
    )
    if (
        child_digest != value["child_ir_sha256"]
        or Path(value["child_ir_path"]).resolve() != expected_child_path.resolve()
    ):
        raise RecompileError("child Research IR is not content addressed")
    child, changed = _validate_candidate(
        parent=parent, candidate=child, request=request, manifest=manifest
    )
    compiler_proposal, compiler_digest = compiler._load_addressed(  # noqa: SLF001
        Path(value["compiler_proposal_path"]), expected_kind="research-ir-proposal/v1"
    )
    compiler._validate_proposal_record(compiler_proposal)  # noqa: SLF001
    expected_compiler_proposal_path = (
        Path(manifest["compiler_store"])
        / "objects"
        / "sha256"
        / f"{compiler_digest}.json"
    )
    if (
        compiler_digest != value["compiler_proposal_sha256"]
        or Path(value["compiler_proposal_path"]).resolve()
        != expected_compiler_proposal_path.resolve()
        or compiler_proposal["research_ir_sha256"] != child_digest
        or value["changed_roots"] != changed
        or value["child_ir_version"] != child["version"]
        or value["compiled_at"] != request["requested_at"]
        or value["parent_ir_sha256"] != manifest["parent_ir_sha256"]
        or value["parent_freeze_receipt_sha256"]
        != manifest["parent_freeze_receipt_sha256"]
    ):
        raise RecompileError("Recompile proposal lineage differs from P1 or request")
    return dict(value)


def _bind_freeze_unlocked(
    *, store_dir: Path, proposal_sha256: str, freeze_receipt: Path, engineering_test: bool = False
) -> dict[str, Any]:
    """Bind a later P1 freeze to the P5 request without starting P2."""

    if not ledger.SHA256_RE.fullmatch(proposal_sha256):
        raise RecompileError("proposal_sha256 must be lowercase SHA-256")
    store_dir = store_dir.resolve()
    manifest, parent, _records = _manifest(store_dir)
    _verify_store(store_dir=store_dir, strict_inventory=False)
    matches = [
        item for item in _proposal_records(store_dir) if item["proposal_sha256"] == proposal_sha256
    ]
    if len(matches) != 1:
        raise RecompileError("proposal digest is not indexed exactly once")
    proposal, actual = _immutable_json(Path(matches[0]["proposal_path"]), "Recompile proposal")
    if actual != proposal_sha256:
        raise RecompileError("Recompile proposal mapping digest differs")
    proposal = _validate_proposal(
        store_dir=store_dir, value=proposal, manifest=manifest, parent=parent
    )
    try:
        verified = compiler.verify_freeze(
            receipt_path=freeze_receipt,
            store=Path(manifest["compiler_store"]),
            check_paths=False,
        )
        receipt, freeze_digest = compiler._load_addressed(  # noqa: SLF001
            freeze_receipt, expected_kind=None
        )
        compiler._validate_receipt(receipt)  # noqa: SLF001
    except compiler.CompilerError as exc:
        raise RecompileError(f"child P1 freeze replay failed: {exc}") from exc
    if receipt["approval_scope"] not in {
        "OWNER_REVIEWED",
        "DELEGATED_ENGINEERING_REVIEW",
    } and not (
        engineering_test and receipt["approval_scope"] == "ENGINEERING_ACCEPTANCE"
    ):
        raise RecompileError(
            "live P5 requires an OWNER_REVIEWED or DELEGATED_ENGINEERING_REVIEW child freeze"
        )
    request, _request_record = _load_request(store_dir, proposal["request_sha256"])
    final_ir, final_ir_digest = compiler._load_addressed(  # noqa: SLF001
        Path(manifest["compiler_store"])
        / "objects"
        / "sha256"
        / f"{receipt['research_ir_sha256']}.json",
        expected_kind=None,
    )
    final_ir, _changed = _validate_candidate(
        parent=parent,
        candidate=final_ir,
        request=request,
        manifest=manifest,
    )
    if (
        verified["freeze_receipt_sha256"] != freeze_digest
        or receipt["proposal_sha256"] != proposal["compiler_proposal_sha256"]
        or receipt["research_ir_sha256"] != final_ir_digest
        or receipt["ir_id"] != manifest["parent_ir_id"]
        or receipt["ir_version"] != manifest["parent_ir_version"] + 1
    ):
        raise RecompileError("child freeze does not descend from the P5/P1 proposal")
    value = {
        "approval_scope": receipt["approval_scope"],
        "bound_at": receipt["approved_at"],
        "child_freeze_receipt_path": str(freeze_receipt.resolve()),
        "child_freeze_receipt_sha256": freeze_digest,
        "child_ir_sha256": final_ir_digest,
        "child_ir_version": final_ir["version"],
        "parent_freeze_receipt_sha256": manifest["parent_freeze_receipt_sha256"],
        "parent_ir_sha256": manifest["parent_ir_sha256"],
        "proposal_sha256": proposal_sha256,
        "request_sha256": proposal["request_sha256"],
        "schema_version": (
            DELEGATED_FREEZE_VERSION
            if receipt["approval_scope"] == "DELEGATED_ENGINEERING_REVIEW"
            else FREEZE_VERSION
        ),
    }
    if receipt["approval_scope"] == "DELEGATED_ENGINEERING_REVIEW":
        value["delegated_review_path"] = receipt["delegated_review_path"]
        value["delegated_review_sha256"] = receipt["delegated_review_sha256"]
    digest = _sha256_bytes(_canonical_bytes(value))
    object_path = store_dir / "freezes" / "sha256" / f"{digest}.json"
    mapping_path = (
        store_dir / "freeze-records" / "by-proposal" / f"{proposal_sha256}.json"
    )
    if mapping_path.exists() or mapping_path.is_symlink():
        mapping, _mapping_digest = _immutable_json(mapping_path, "Recompile freeze mapping")
        if mapping.get("freeze_sha256") != digest:
            raise RecompileError("proposal already binds a different child freeze")
        verify_store(store_dir=store_dir)
        return {
            "already_bound": True,
            "child_ir_sha256": value["child_ir_sha256"],
            "child_ir_version": value["child_ir_version"],
            "freeze_path": mapping["freeze_path"],
            "freeze_sha256": digest,
            "stage": "FROZEN",
        }
    indexed = {item["freeze_sha256"] for item in _freeze_records(store_dir)}
    _allow_recovery(
        _object_digests(store_dir / "freezes" / "sha256"), indexed, digest, "Freeze store"
    )
    _publish_json(object_path, value)
    _publish_json(mapping_path, {
        "freeze_path": str(object_path),
        "freeze_sha256": digest,
        "proposal_sha256": proposal_sha256,
        "schema_version": FREEZE_RECORD_VERSION,
    })
    verify_store(store_dir=store_dir)
    return {
        "already_bound": False,
        "child_ir_sha256": value["child_ir_sha256"],
        "child_ir_version": value["child_ir_version"],
        "freeze_path": str(object_path),
        "freeze_sha256": digest,
        "stage": "FROZEN",
    }


def _verify_store(*, store_dir: Path, strict_inventory: bool) -> dict[str, Any]:
    manifest, parent, gate_records = _manifest(store_dir)
    decision, decision_record = _latest_decision(manifest, gate_records)
    analyses = _analysis_records(store_dir)
    requests = _request_records(store_dir)
    proposals = _proposal_records(store_dir)
    freezes = _freeze_records(store_dir)
    if len(analyses) > 1 or len(requests) > 1 or len(proposals) > 1 or len(freezes) > 1:
        raise RecompileError("MVP-0 P5 permits one linear lineage only")

    expected_analyses: set[str] = set()
    expected_requests: set[str] = set()
    expected_proposals: set[str] = set()
    expected_freezes: set[str] = set()
    analysis: dict[str, Any] | None = None
    analysis_digest: str | None = None
    if analyses:
        mapping = analyses[0]
        if (
            mapping["schema_version"] != ANALYSIS_RECORD_VERSION
            or mapping["decision_sha256"] != decision_record["decision_sha256"]
        ):
            raise RecompileError("Failure analysis mapping identity is invalid")
        analysis, analysis_digest = _immutable_json(
            Path(mapping["analysis_path"]), "Failure analysis"
        )
        if analysis_digest != mapping["analysis_sha256"]:
            raise RecompileError("Failure analysis is not content addressed")
        _validate_analysis(
            value=analysis,
            manifest=manifest,
            decision=decision,
            decision_record=decision_record,
        )
        expected_analyses.add(analysis_digest)

    request: dict[str, Any] | None = None
    request_digest: str | None = None
    if requests:
        if analysis is None or analysis_digest is None:
            raise RecompileError("Recompile request exists without failure analysis")
        mapping = requests[0]
        if (
            mapping["schema_version"] != REQUEST_RECORD_VERSION
            or mapping["decision_sha256"] != decision_record["decision_sha256"]
            or mapping["analysis_sha256"] != analysis_digest
        ):
            raise RecompileError("Recompile request mapping identity is invalid")
        request, request_digest = _immutable_json(
            Path(mapping["request_path"]), "Recompile request"
        )
        if request_digest != mapping["request_sha256"]:
            raise RecompileError("Recompile request is not content addressed")
        _validate_request(
            value=request,
            analysis=analysis,
            analysis_digest=analysis_digest,
            manifest=manifest,
            ir=parent,
            decision=decision,
            decision_record=decision_record,
        )
        expected_requests.add(request_digest)

    proposal: dict[str, Any] | None = None
    proposal_digest: str | None = None
    if proposals:
        if request is None or request_digest is None:
            raise RecompileError("Recompile proposal exists without a request")
        mapping = proposals[0]
        if (
            mapping["schema_version"] != PROPOSAL_RECORD_VERSION
            or mapping["request_sha256"] != request_digest
        ):
            raise RecompileError("Recompile proposal mapping identity is invalid")
        proposal, proposal_digest = _immutable_json(
            Path(mapping["proposal_path"]), "Recompile proposal"
        )
        if proposal_digest != mapping["proposal_sha256"]:
            raise RecompileError("Recompile proposal is not content addressed")
        proposal = _validate_proposal(
            store_dir=store_dir, value=proposal, manifest=manifest, parent=parent
        )
        expected_proposals.add(proposal_digest)

    if freezes:
        if proposal is None or proposal_digest is None:
            raise RecompileError("Recompile freeze exists without a proposal")
        mapping = freezes[0]
        if (
            mapping["schema_version"] != FREEZE_RECORD_VERSION
            or mapping["proposal_sha256"] != proposal_digest
        ):
            raise RecompileError("Recompile freeze mapping identity is invalid")
        value, digest = _immutable_json(Path(mapping["freeze_path"]), "Recompile freeze")
        if digest != mapping["freeze_sha256"]:
            raise RecompileError("Recompile freeze is not content addressed")
        expected_freeze_keys = {
            "approval_scope",
            "bound_at",
            "child_freeze_receipt_path",
            "child_freeze_receipt_sha256",
            "child_ir_sha256",
            "child_ir_version",
            "parent_freeze_receipt_sha256",
            "parent_ir_sha256",
            "proposal_sha256",
            "request_sha256",
            "schema_version",
        }
        if value.get("schema_version") == DELEGATED_FREEZE_VERSION:
            expected_freeze_keys |= {
                "delegated_review_path",
                "delegated_review_sha256",
            }
        _exact_keys(value, expected_freeze_keys, "Recompile freeze")
        try:
            verified = compiler.verify_freeze(
                receipt_path=Path(value["child_freeze_receipt_path"]),
                store=Path(manifest["compiler_store"]),
                check_paths=False,
            )
            receipt, receipt_digest = compiler._load_addressed(  # noqa: SLF001
                Path(value["child_freeze_receipt_path"]), expected_kind=None
            )
            compiler._validate_receipt(receipt)  # noqa: SLF001
        except compiler.CompilerError as exc:
            raise RecompileError(f"child freeze replay failed: {exc}") from exc
        request, _request_record = _load_request(store_dir, proposal["request_sha256"])
        final_ir, final_ir_digest = compiler._load_addressed(  # noqa: SLF001
            Path(manifest["compiler_store"])
            / "objects"
            / "sha256"
            / f"{receipt['research_ir_sha256']}.json",
            expected_kind=None,
        )
        _validate_candidate(
            parent=parent,
            candidate=final_ir,
            request=request,
            manifest=manifest,
        )
        if (
            value["schema_version"]
            not in {FREEZE_VERSION, DELEGATED_FREEZE_VERSION}
            or value["proposal_sha256"] != proposal_digest
            or value["request_sha256"] != proposal["request_sha256"]
            or value["parent_ir_sha256"] != manifest["parent_ir_sha256"]
            or value["parent_freeze_receipt_sha256"]
            != manifest["parent_freeze_receipt_sha256"]
            or value["child_ir_sha256"] != final_ir_digest
            or value["child_ir_version"] != final_ir["version"]
            or value["approval_scope"] != receipt["approval_scope"]
            or value["bound_at"] != receipt["approved_at"]
            or receipt_digest != value["child_freeze_receipt_sha256"]
            or receipt["proposal_sha256"] != proposal["compiler_proposal_sha256"]
            or verified["freeze_receipt_sha256"] != value["child_freeze_receipt_sha256"]
            or verified["research_ir_sha256"] != value["child_ir_sha256"]
        ):
            raise RecompileError("Recompile freeze lineage differs")
        if receipt["approval_scope"] == "DELEGATED_ENGINEERING_REVIEW":
            if (
                value["schema_version"] != DELEGATED_FREEZE_VERSION
                or value["delegated_review_path"] != receipt["delegated_review_path"]
                or value["delegated_review_sha256"]
                != receipt["delegated_review_sha256"]
            ):
                raise RecompileError("delegated review binding differs in P5 freeze")
        elif value["schema_version"] != FREEZE_VERSION:
            raise RecompileError("non-delegated P5 freeze uses the delegated schema")
        expected_freezes.add(digest)

    if strict_inventory:
        inventories = (
            ("analyses", expected_analyses),
            ("requests", expected_requests),
            ("proposals", expected_proposals),
            ("freezes", expected_freezes),
        )
        for name, expected in inventories:
            if _object_digests(store_dir / name / "sha256") != expected:
                raise RecompileError(f"P5 {name} inventory differs from mappings")
    stage = "READY_FOR_ANALYSIS"
    if analysis is not None:
        stage = "ANALYZED"
    if request is not None:
        stage = request["disposition"]
    if proposal is not None:
        stage = "AWAITING_HUMAN_CRITIQUE"
    if freezes:
        stage = "FROZEN"
    return {
        "analysis_count": len(analyses),
        "freeze_count": len(freezes),
        "p5_id": manifest["p5_id"],
        "proposal_count": len(proposals),
        "request_count": len(requests),
        "stage": stage,
        "store_dir": str(store_dir),
        "verified": True,
    }


def verify_store(*, store_dir: Path) -> dict[str, Any]:
    """Replay the complete linear P5 lineage and exact object inventories."""

    return _verify_store(store_dir=store_dir.resolve(), strict_inventory=True)


def publish_analysis(*, store_dir: Path, analysis_path: Path) -> dict[str, Any]:
    with _store_lease(store_dir):
        return _publish_analysis_unlocked(store_dir=store_dir, analysis_path=analysis_path)


def publish_request(*, store_dir: Path, request_path: Path) -> dict[str, Any]:
    with _store_lease(store_dir):
        return _publish_request_unlocked(store_dir=store_dir, request_path=request_path)


def compile_candidate(
    *, store_dir: Path, request_sha256: str, candidate_ir: Path, author: str
) -> dict[str, Any]:
    with _store_lease(store_dir):
        return _compile_candidate_unlocked(
            store_dir=store_dir,
            request_sha256=request_sha256,
            candidate_ir=candidate_ir,
            author=author,
        )


def bind_freeze(
    *, store_dir: Path, proposal_sha256: str, freeze_receipt: Path, engineering_test: bool = False
) -> dict[str, Any]:
    with _store_lease(store_dir):
        return _bind_freeze_unlocked(
            store_dir=store_dir,
            proposal_sha256=proposal_sha256,
            freeze_receipt=freeze_receipt,
            engineering_test=engineering_test,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MVP-0 P5 Recompile Loop")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="freeze a complete eligible P4 prefix")
    init.add_argument("--gate-store", type=Path, required=True)
    init.add_argument("--store-dir", type=Path, required=True)
    analyze = sub.add_parser("analyze", help="publish one evidence-bound failure analysis")
    analyze.add_argument("--store-dir", type=Path, required=True)
    analyze.add_argument("--analysis", type=Path, required=True)
    request = sub.add_parser("request", help="publish one continuation/recompile request")
    request.add_argument("--store-dir", type=Path, required=True)
    request.add_argument("--request", type=Path, required=True)
    compile_parser = sub.add_parser("compile", help="compile IR N+1 into P1 review")
    compile_parser.add_argument("--store-dir", type=Path, required=True)
    compile_parser.add_argument("--request-sha256", required=True)
    compile_parser.add_argument("--candidate-ir", type=Path, required=True)
    compile_parser.add_argument("--author", required=True)
    bind = sub.add_parser("bind-freeze", help="bind a later P1 freeze to P5")
    bind.add_argument("--store-dir", type=Path, required=True)
    bind.add_argument("--proposal-sha256", required=True)
    bind.add_argument("--freeze-receipt", type=Path, required=True)
    bind.add_argument("--engineering-test", action="store_true")
    verify = sub.add_parser("verify", help="replay P5 lineage")
    verify.add_argument("--store-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            result = initialize_store(gate_store=args.gate_store, store_dir=args.store_dir)
        elif args.command == "analyze":
            result = publish_analysis(store_dir=args.store_dir, analysis_path=args.analysis)
        elif args.command == "request":
            result = publish_request(store_dir=args.store_dir, request_path=args.request)
        elif args.command == "compile":
            result = compile_candidate(
                store_dir=args.store_dir,
                request_sha256=args.request_sha256,
                candidate_ir=args.candidate_ir,
                author=args.author,
            )
        elif args.command == "bind-freeze":
            result = bind_freeze(
                store_dir=args.store_dir,
                proposal_sha256=args.proposal_sha256,
                freeze_receipt=args.freeze_receipt,
                engineering_test=args.engineering_test,
            )
        else:
            result = verify_store(store_dir=args.store_dir)
    except (
        RecompileError,
        gate.GateError,
        ledger.LedgerError,
        worker.AdapterError,
        compiler.CompilerError,
        OSError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
