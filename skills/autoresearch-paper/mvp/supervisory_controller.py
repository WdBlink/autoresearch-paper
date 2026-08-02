#!/usr/bin/env python3
"""P6 one-transition supervisory controller for the isolated MVP-0 loop."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from . import automation_registration as automation
    from . import delegated_review
    from . import evidence_gate as gate
    from . import experiment_ledger as ledger
    from . import recompile_loop as p5
    from . import research_compiler as compiler
    from . import runtime_assurance
    from . import worker_adapter as worker
    from .launchd_registration import LaunchctlScheduler
except ImportError:  # pragma: no cover - direct script execution
    import automation_registration as automation  # type: ignore[no-redef]
    import delegated_review  # type: ignore[no-redef]
    import evidence_gate as gate  # type: ignore[no-redef]
    import experiment_ledger as ledger  # type: ignore[no-redef]
    import recompile_loop as p5  # type: ignore[no-redef]
    import research_compiler as compiler  # type: ignore[no-redef]
    import runtime_assurance  # type: ignore[no-redef]
    import worker_adapter as worker  # type: ignore[no-redef]
    from launchd_registration import LaunchctlScheduler  # type: ignore[no-redef]


MVP_ROOT = Path(__file__).resolve().parent
HEARTBEAT_PROMPT_PATH = MVP_ROOT / "prompts" / "codex-supervisor-heartbeat.md"
MANIFEST_VERSION = "mvp0-supervisor-manifest/v1"
STATE_VERSION = "mvp0-supervisor-state/v1"
TICK_VERSION = "mvp0-supervisor-tick/v1"
REVIEW_INPUT_VERSION = "mvp0-engineering-review-input/v1"
PHASES = {
    "READY",
    "WORKER_RUNNING",
    "NEEDS_P3",
    "NEEDS_P4",
    "NEEDS_P5",
    "NEEDS_ENGINEERING_REVIEW",
    "NEEDS_CHILD_P2",
    "WAITING_HUMAN",
    "BLOCKED",
    "STOPPED",
    "COMPLETED",
}


class SupervisorError(RuntimeError):
    """A fail-closed P6 state, lineage, or authority error."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SupervisorError("timestamp must be an RFC3339 UTC string")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise SupervisorError(f"invalid timestamp: {value}") from exc


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
        raise SupervisorError(f"value is not canonical JSON: {exc}") from exc
    return (rendered + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise SupervisorError(f"cannot read strict JSON from {path}: {exc}") from exc


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _atomic_write(path: Path, data: bytes, *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and (path.exists() or path.is_symlink()):
        raise SupervisorError(f"immutable supervisor artifact already exists: {path}")
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


def _write_immutable_idempotent(path: Path, value: Any) -> bool:
    data = _canonical_bytes(value)
    if path.exists() or path.is_symlink():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_mode & 0o777 != 0o444
            or path.read_bytes() != data
        ):
            raise SupervisorError(f"immutable supervisor artifact collision: {path}")
        return True
    _atomic_write(path, data, immutable=True)
    return False


def _append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _canonical_bytes(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        if os.write(descriptor, data) != len(data):
            raise SupervisorError("short append to supervisor tick index")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _lease(store_dir: Path):
    path = store_dir / "leases" / "tick.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SupervisorError("another supervisor tick is already running") from exc
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def controller_id_for(*, target_thread_id: str, run_dir: Path) -> str:
    seed = f"{target_thread_id}\0{run_dir.resolve()}".encode("utf-8")
    return "mvp0-supervisor-" + hashlib.sha256(seed).hexdigest()[:16]


def _immutable(path: Path, label: str) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o777 != 0o444:
        raise SupervisorError(f"{label} is missing, mutable, or a symlink")
    value = _read_json(path)
    if not isinstance(value, dict):
        raise SupervisorError(f"{label} must be a JSON object")
    return value, _sha256_file(path)


def _load(store_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    store_dir = store_dir.resolve()
    manifest, _digest = _immutable(store_dir / "supervisor-manifest.json", "supervisor manifest")
    state = _read_json(store_dir / "supervisor-state.json")
    if manifest.get("schema_version") != MANIFEST_VERSION:
        raise SupervisorError("supervisor manifest version is unsupported")
    if not isinstance(state, dict) or state.get("schema_version") != STATE_VERSION:
        raise SupervisorError("supervisor state is invalid")
    if state.get("controller_id") != manifest.get("controller_id"):
        raise SupervisorError("supervisor state controller differs from its manifest")
    if state.get("phase") not in PHASES:
        raise SupervisorError("supervisor state phase is invalid")
    return manifest, state


def _turn_paths(adapter_dir: Path) -> list[Path]:
    root = adapter_dir / "turns"
    return sorted(root.glob("*.json")) if root.is_dir() else []


def _ledger_prefix(ledger_dir: Path) -> dict[str, Any]:
    try:
        return ledger._verify_ledger(  # noqa: SLF001
            ledger_dir=ledger_dir,
            require_complete=False,
            check_object_inventory=True,
        )
    except (ledger.LedgerError, worker.AdapterError) as exc:
        raise SupervisorError(f"P3 prefix replay failed: {exc}") from exc


def _gate_prefix(gate_store: Path | None) -> dict[str, Any] | None:
    if gate_store is None or not gate_store.is_dir():
        return None
    try:
        return gate._verify_store(store_dir=gate_store, strict_inventory=True)  # noqa: SLF001
    except (gate.GateError, ledger.LedgerError, worker.AdapterError) as exc:
        raise SupervisorError(f"P4 replay failed: {exc}") from exc


def _latest_gate_decision(gate_store: Path) -> dict[str, Any] | None:
    records = gate._records(gate_store)  # noqa: SLF001
    if not records:
        return None
    value, _digest = p5._immutable_json(  # noqa: SLF001
        Path(records[-1][0]["decision_path"]), "P4 decision"
    )
    return value


def _p5_proposal(p5_store: Path) -> tuple[dict[str, Any], str, Path]:
    records = p5._proposal_records(p5_store)  # noqa: SLF001
    if len(records) != 1:
        raise SupervisorError("P5 must contain exactly one proposal for engineering review")
    path = Path(records[0]["proposal_path"])
    value, digest = p5._immutable_json(path, "P5 proposal")  # noqa: SLF001
    return value, digest, path


def _phase(manifest: Mapping[str, Any], state: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    adapter_dir = Path(state["active_adapter_dir"])
    ledger_dir = Path(state["active_ledger_dir"])
    gate_store = Path(state["active_gate_store"]) if state.get("active_gate_store") else None
    p5_store = Path(state["active_p5_store"]) if state.get("active_p5_store") else None
    try:
        adapter_view = worker.inspect_adapter(adapter_dir=adapter_dir)
    except worker.AdapterError as exc:
        raise SupervisorError(f"P2 replay failed: {exc}") from exc
    if adapter_view["session_state"] == "BUSY":
        return "WORKER_RUNNING", {"action": "WAIT_FOR_WORKER"}
    ledger_view = _ledger_prefix(ledger_dir)
    if adapter_view["turn_count"] > ledger_view["record_count"]:
        return "NEEDS_P3", {
            "action": "RECORD_P3",
            "turn_receipt_path": str(_turn_paths(adapter_dir)[ledger_view["record_count"]]),
        }
    gate_view = _gate_prefix(gate_store)
    decision_count = 0 if gate_view is None else gate_view["decision_count"]
    if ledger_view["record_count"] > decision_count:
        entries = ledger._load_index(ledger_dir)  # noqa: SLF001
        receipt = entries[decision_count]["receipt"]
        _ledger_manifest, adapter_manifest, _session = ledger._ledger_manifest(  # noqa: SLF001
            ledger_dir
        )
        ir = worker._load_ir_from_manifest(adapter_manifest)  # noqa: SLF001
        return "NEEDS_P4", {
            "action": "DECIDE_P4",
            "experiment_receipt_sha256": entries[decision_count]["receipt_sha256"],
            "evaluator_report_required": (
                receipt["execution"]["status"] == "COMPLETED"
                and ir["evaluator_spec"]["status"] == "READY"
            ),
        }
    if decision_count == 0:
        return "READY", {"action": "DISPATCH_INITIAL_WORK"}
    assert gate_store is not None
    decision = _latest_gate_decision(gate_store)
    assert decision is not None
    if decision["decision"] == "STOP":
        return "STOPPED", {"action": "PAUSE", "reason": "P4_STOP"}
    if decision["decision"] == "KEEP":
        return "READY", {"action": "CREATE_CURRENT_IR_SUCCESSOR"}
    if decision["decision"] not in {"PIVOT", "RECOMPILE"}:
        raise SupervisorError("P4 produced an unsupported decision")
    if p5_store is None or not p5_store.exists():
        return "NEEDS_P5", {"action": "INITIALIZE_P5"}
    try:
        p5_view = p5.verify_store(store_dir=p5_store)
    except p5.RecompileError as exc:
        raise SupervisorError(f"P5 replay failed: {exc}") from exc
    stage = p5_view["stage"]
    if stage == "READY_FOR_ANALYSIS":
        return "NEEDS_P5", {"action": "PUBLISH_FAILURE_ANALYSIS"}
    if stage == "ANALYZED":
        return "NEEDS_P5", {"action": "PUBLISH_RECOMPILE_REQUEST"}
    if stage == "RECOMPILE_IR":
        return "NEEDS_P5", {"action": "COMPILE_SUCCESSOR_IR"}
    if stage == "CONTINUE_CURRENT_IR":
        return "NEEDS_CHILD_P2", {"action": "CREATE_CURRENT_IR_SUCCESSOR"}
    if stage == "AWAITING_HUMAN_CRITIQUE":
        proposal, proposal_digest, proposal_path = _p5_proposal(p5_store)
        p5_manifest, _p5_ir, _records = p5._manifest(p5_store)  # noqa: SLF001
        parent_path = (
            Path(p5_manifest["compiler_store"])
            / "objects"
            / "sha256"
            / f"{p5_manifest['parent_ir_sha256']}.json"
        )
        parent = _read_json(parent_path)
        child = _read_json(Path(proposal["child_ir_path"]))
        try:
            pointers, roots = delegated_review.validate_engineering_delta(parent, child)
        except delegated_review.DelegatedReviewError as exc:
            return "WAITING_HUMAN", {
                "action": "PAUSE",
                "reason": f"SCIENTIFIC_OR_UNAUTHORIZED_IR_CHANGE:{exc}",
            }
        return "NEEDS_ENGINEERING_REVIEW", {
            "action": "REVIEW_ENGINEERING_IR",
            "changed_pointers": pointers,
            "changed_roots": roots,
            "compiler_proposal_path": proposal["compiler_proposal_path"],
            "p5_proposal_path": str(proposal_path),
            "p5_proposal_sha256": proposal_digest,
            "review_input_schema_version": REVIEW_INPUT_VERSION,
        }
    if stage == "FROZEN":
        return "NEEDS_CHILD_P2", {"action": "CREATE_CHILD_P2"}
    raise SupervisorError(f"P5 stage is unsupported: {stage}")


def initialize_supervisor(
    *,
    run_dir: Path,
    target_thread_id: str,
    adapter_dir: Path,
    ledger_dir: Path,
    gate_store: Path,
    p5_store: Path,
    store_dir: Path | None = None,
    automation_root: Path = Path.home() / ".codex" / "automations",
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    store_dir = (run_dir / "supervisor" if store_dir is None else store_dir).resolve()
    if store_dir.exists() or store_dir.is_symlink():
        raise SupervisorError("supervisor store already exists")
    adapter_dir = adapter_dir.resolve()
    ledger_dir = ledger_dir.resolve()
    gate_store = gate_store.resolve()
    p5_store = p5_store.resolve()
    adapter_manifest = worker._adapter_manifest(adapter_dir)  # noqa: SLF001
    _ledger_prefix(ledger_dir)
    _gate_prefix(gate_store)
    if p5_store.exists():
        p5.verify_store(store_dir=p5_store)
    controller_id = controller_id_for(target_thread_id=target_thread_id, run_dir=run_dir)
    automation_path = automation_root.expanduser().resolve() / controller_id / "automation.toml"
    created_at = _now()
    manifest = {
        "automation_path": str(automation_path),
        "controller_id": controller_id,
        "created_at": created_at,
        "heartbeat_prompt_path": str(HEARTBEAT_PROMPT_PATH),
        "heartbeat_prompt_sha256": _sha256_file(HEARTBEAT_PROMPT_PATH),
        "initial_adapter_dir": str(adapter_dir),
        "initial_freeze_receipt_sha256": adapter_manifest["freeze_receipt_sha256"],
        "initial_gate_store": str(gate_store),
        "initial_ir_sha256": adapter_manifest["research_ir_sha256"],
        "initial_ledger_dir": str(ledger_dir),
        "initial_p5_store": str(p5_store),
        "run_dir": str(run_dir),
        "schema_version": MANIFEST_VERSION,
        "source_repo": adapter_manifest["source_repo"],
        "supervisor_store": str(store_dir),
        "target_thread_id": target_thread_id,
    }
    store_dir.mkdir(parents=True)
    try:
        for relative in ("objects/sha256", "leases", "reports", "assurance", "runtime"):
            (store_dir / relative).mkdir(parents=True, exist_ok=True)
        _write_json(store_dir / "supervisor-manifest.json", manifest, immutable=True)
        state = {
            "active_adapter_dir": str(adapter_dir),
            "active_gate_store": str(gate_store),
            "active_ledger_dir": str(ledger_dir),
            "active_p5_store": str(p5_store),
            "automation_pause_required": False,
            "blocker": None,
            "controller_id": controller_id,
            "generation": 1,
            "latest_tick_sha256": None,
            "phase": "READY",
            "schema_version": STATE_VERSION,
            "sequence": 0,
            "updated_at": created_at,
        }
        phase, _action = _phase(manifest, state)
        state["phase"] = phase
        state["automation_pause_required"] = phase in {
            "WAITING_HUMAN", "BLOCKED", "STOPPED", "COMPLETED"
        }
        _write_json(store_dir / "supervisor-state.json", state)
    except Exception:
        import shutil

        shutil.rmtree(store_dir)
        raise
    return inspect_supervisor(store_dir=store_dir)


def _action_envelope(
    manifest: Mapping[str, Any], state: Mapping[str, Any], action: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        **action,
        "controller_id": manifest["controller_id"],
        "run_dir": manifest["run_dir"],
        "target_thread_id": manifest["target_thread_id"],
        "expected_sequence": state["sequence"] + 1,
    }


def inspect_supervisor(*, store_dir: Path) -> dict[str, Any]:
    manifest, state = _load(store_dir)
    phase, action = _phase(manifest, state)
    return {
        "action": _action_envelope(manifest, state, action),
        "automation_pause_required": phase in {
            "WAITING_HUMAN", "BLOCKED", "STOPPED", "COMPLETED"
        },
        "controller_id": manifest["controller_id"],
        "phase": phase,
        "sequence": state["sequence"],
        "state_matches_durable_lineage": state["phase"] == phase,
        "store_dir": str(store_dir.resolve()),
        "target_thread_id": manifest["target_thread_id"],
    }


def _validate_review_input(value: Any) -> dict[str, Any]:
    expected = {
        "approval_note",
        "approved_at",
        "approver",
        "critique",
        "recorded_at",
        "review_summary",
        "reviewed_at",
        "reviewer",
        "revision_author",
        "revision_recorded_at",
        "revision_summary",
        "schema_version",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise SupervisorError("engineering review input fields differ from the closed contract")
    if value["schema_version"] != REVIEW_INPUT_VERSION:
        raise SupervisorError("engineering review input version is unsupported")
    critique = value["critique"]
    if not isinstance(critique, dict) or critique.get("verdict") != "ACCEPT" or critique.get("findings") != []:
        raise SupervisorError("delegated engineering critique must be an unqualified ACCEPT")
    identities = [value[key] for key in ("reviewer", "revision_author", "approver")]
    if any(not isinstance(item, str) or not item.startswith("codex/") for item in identities):
        raise SupervisorError("delegated review identities must use codex/<role>")
    for field in ("recorded_at", "revision_recorded_at", "reviewed_at", "approved_at"):
        _parse_time(value[field])
    return value


def _execute_review(
    *, manifest: Mapping[str, Any], state: Mapping[str, Any], action_input: Path
) -> dict[str, Any]:
    review_input = _validate_review_input(_read_json(action_input))
    p5_store = Path(state["active_p5_store"])
    proposal, proposal_digest, proposal_path = _p5_proposal(p5_store)
    compiler_store = Path(p5._manifest(p5_store)[0]["compiler_store"])  # noqa: SLF001
    compiler_proposal = Path(proposal["compiler_proposal_path"])
    compiler_record = _read_json(compiler_proposal)
    if review_input["reviewer"] == compiler_record["author"]:
        raise SupervisorError("delegated reviewer must differ from the compiler author")
    critique_input_path = (
        Path(manifest["supervisor_store"])
        / "review-inputs"
        / f"{proposal_digest}-critique.json"
    )
    _write_immutable_idempotent(critique_input_path, review_input["critique"])
    critique = compiler.critique(
        proposal_path=compiler_proposal,
        critique_path=critique_input_path,
        store=compiler_store,
        reviewer=review_input["reviewer"],
        recorded_at=review_input["recorded_at"],
    )
    revision = compiler.confirm_revision(
        proposal_path=compiler_proposal,
        critique_record_path=Path(critique["critique_path"]),
        store=compiler_store,
        author=review_input["revision_author"],
        summary=review_input["revision_summary"],
        recorded_at=review_input["revision_recorded_at"],
    )
    p5_manifest, _parent, _records = p5._manifest(p5_store)  # noqa: SLF001
    parent_path = (
        compiler_store
        / "objects"
        / "sha256"
        / f"{p5_manifest['parent_ir_sha256']}.json"
    )
    request_path = (
        p5_store / "requests" / "sha256" / f"{proposal['request_sha256']}.json"
    )
    review = delegated_review.publish_review(
        store_dir=p5_store / "delegated-reviews",
        parent_ir_path=parent_path,
        child_ir_path=Path(proposal["child_ir_path"]),
        request_path=request_path,
        proposal_path=proposal_path,
        compiler_author=compiler_record["author"],
        reviewer=review_input["reviewer"],
        revision_author=review_input["revision_author"],
        approver=review_input["approver"],
        verdict="ACCEPT",
        summary=review_input["review_summary"],
        reviewed_at=review_input["reviewed_at"],
    )
    frozen = compiler.freeze(
        revision_path=Path(revision["revision_path"]),
        store=compiler_store,
        approved_by=review_input["approver"],
        approval_scope="DELEGATED_ENGINEERING_REVIEW",
        approval_note=review_input["approval_note"],
        approved_at=review_input["approved_at"],
        delegated_review_receipt=Path(review["review_receipt_path"]),
    )
    bound = p5.bind_freeze(
        store_dir=p5_store,
        proposal_sha256=proposal_digest,
        freeze_receipt=Path(frozen["freeze_receipt_path"]),
    )
    return {
        "action": "REVIEW_ENGINEERING_IR",
        "child_freeze_receipt_path": frozen["freeze_receipt_path"],
        "child_ir_sha256": frozen["research_ir_sha256"],
        "delegated_review_sha256": review["review_receipt_sha256"],
        "p5_freeze_path": bound["freeze_path"],
        "p5_freeze_sha256": bound["freeze_sha256"],
    }


def _execute_child_p2(
    *,
    manifest: Mapping[str, Any],
    state: Mapping[str, Any],
    task_contract: Path,
    scheduler: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    p5_store = Path(state["active_p5_store"])
    p5.verify_store(store_dir=p5_store)
    freeze_records = p5._freeze_records(p5_store)  # noqa: SLF001
    if len(freeze_records) != 1:
        raise SupervisorError("child P2 requires exactly one P5 freeze")
    p5_freeze_path = Path(freeze_records[0]["freeze_path"])
    p5_freeze = _read_json(p5_freeze_path)
    child_freeze = Path(p5_freeze["child_freeze_receipt_path"])
    generation = int(state["generation"]) + 1
    generation_root = Path(manifest["run_dir"]) / "generations" / f"{generation:04d}"
    child_adapter = generation_root / "adapter"
    child_worktree = generation_root / "worktree"
    child_ledger = generation_root / "ledger"
    prior_turns = _turn_paths(Path(state["active_adapter_dir"]))
    if not prior_turns:
        raise SupervisorError("child P2 requires one terminal predecessor turn")
    prior_manifest = worker._adapter_manifest(Path(state["active_adapter_dir"]))  # noqa: SLF001
    if not child_adapter.exists():
        worker.initialize_adapter(
            freeze_receipt=child_freeze,
            compiler_store=Path(prior_manifest["compiler_store"]),
            source_repo=Path(manifest["source_repo"]),
            adapter_dir=child_adapter,
            worktree=child_worktree,
            claude_bin=prior_manifest["claude_executable"],
            worker_model=prior_manifest["worker_model"],
            max_budget_usd_per_turn=prior_manifest["max_budget_usd_per_turn"],
            predecessor_turn_receipt=prior_turns[-1],
            p5_store=p5_store,
            p5_freeze_binding=p5_freeze_path,
        )
    if not child_ledger.exists():
        ledger.initialize_ledger(adapter_dir=child_adapter, ledger_dir=child_ledger)
    child_manifest = worker._adapter_manifest(child_adapter)  # noqa: SLF001
    expected_child = {
        "freeze_receipt_path": str(child_freeze.resolve()),
        "freeze_receipt_sha256": _sha256_file(child_freeze),
        "p5_freeze_binding_path": str(p5_freeze_path.resolve()),
        "p5_freeze_binding_sha256": _sha256_file(p5_freeze_path),
        "p5_store": str(p5_store.resolve()),
        "predecessor_turn_receipt_path": str(prior_turns[-1].resolve()),
        "predecessor_turn_receipt_sha256": _sha256_file(prior_turns[-1]),
        "session_id": prior_manifest["session_id"],
        "source_repo": manifest["source_repo"],
        "worktree_root": str(child_worktree),
    }
    observed_child = {key: child_manifest.get(key) for key in expected_child}
    if child_manifest.get("schema_version") != worker.SUCCESSOR_ADAPTER_VERSION:
        raise SupervisorError("existing child Adapter is not a P5-bound successor")
    if observed_child != expected_child:
        raise SupervisorError("existing child Adapter differs from the exact successor lineage")
    child_view = worker.inspect_adapter(adapter_dir=child_adapter)
    if child_view["turn_count"] == 0:
        delivered = worker.dispatch_task(
            adapter_dir=child_adapter,
            task_contract=task_contract,
            unattended=True,
            runtime_store=Path(manifest["supervisor_store"]),
            scheduler=scheduler,
        )
    else:
        delivered = {
            "already_dispatched": True,
            "receipt_path": child_view["last_receipt_path"],
            "session_state": child_view["session_state"],
        }
    state_updates = {
        "active_adapter_dir": str(child_adapter),
        "active_gate_store": None,
        "active_ledger_dir": str(child_ledger),
        "active_p5_store": None,
        "generation": generation,
    }
    return {
        "action": "CREATE_CHILD_P2",
        "adapter_dir": str(child_adapter),
        "delivery": delivered,
        "ledger_dir": str(child_ledger),
        "worktree": str(child_worktree),
    }, state_updates


def _recover_tick_commit(*, store_dir: Path) -> bool:
    """Finish a tick whose immutable result was prepared before a host crash."""

    journal_path = store_dir / "runtime" / "tick-commit-journal.json"
    if not journal_path.is_file():
        return False
    journal = _read_json(journal_path)
    if not isinstance(journal, dict) or journal.get("schema_version") != "mvp0-tick-commit-journal/v1":
        raise SupervisorError("tick commit journal is invalid")
    if journal.get("phase") == "COMMITTED":
        return False
    if journal.get("phase") != "PREPARED":
        raise SupervisorError("tick commit journal phase is invalid")
    tick = journal.get("tick")
    next_state = journal.get("next_state")
    digest = journal.get("tick_sha256")
    if (
        not isinstance(tick, dict)
        or not isinstance(next_state, dict)
        or not isinstance(digest, str)
        or _sha256_bytes(_canonical_bytes(tick)) != digest
    ):
        raise SupervisorError("tick commit journal payload is inconsistent")
    current = _read_json(store_dir / "supervisor-state.json")
    if not isinstance(current, dict) or current.get("controller_id") != tick.get("controller_id"):
        raise SupervisorError("tick recovery controller differs from current state")
    target_sequence = tick.get("sequence")
    if current.get("sequence") not in {target_sequence - 1, target_sequence}:
        raise SupervisorError("tick recovery sequence is not adjacent to current state")
    tick_path = store_dir / "objects" / "sha256" / f"{digest}.json"
    _write_immutable_idempotent(tick_path, tick)
    index_path = store_dir / "ticks.jsonl"
    entries = []
    if index_path.is_file():
        entries = [json.loads(line) for line in index_path.read_text().splitlines() if line]
    same_sequence = [item for item in entries if item.get("sequence") == target_sequence]
    expected_entry = {
        "sequence": target_sequence,
        "tick_path": str(tick_path),
        "tick_sha256": digest,
    }
    if same_sequence and same_sequence != [expected_entry]:
        raise SupervisorError("tick recovery index contains a conflicting sequence")
    if not same_sequence:
        _append_jsonl(index_path, expected_entry)
    _write_json(store_dir / "supervisor-state.json", next_state)
    _write_json(journal_path, {**journal, "committed_at": _now(), "phase": "COMMITTED"})
    return True


def _commit_tick(
    *,
    store_dir: Path,
    manifest: Mapping[str, Any],
    state: Mapping[str, Any],
    observed_phase: str,
    result: Mapping[str, Any],
    state_updates: Mapping[str, Any],
    recorded_at: str,
    simulate_crash_after: str | None = None,
) -> dict[str, Any]:
    next_state = {**state, **state_updates}
    next_phase, _action = _phase(manifest, next_state)
    next_state.update({
        "automation_pause_required": next_phase in {
            "WAITING_HUMAN", "BLOCKED", "STOPPED", "COMPLETED"
        },
        "blocker": result.get("blocker"),
        "phase": next_phase,
        "sequence": int(state["sequence"]) + 1,
        "updated_at": recorded_at,
    })
    tick = {
        "action": result["action"],
        "controller_id": manifest["controller_id"],
        "next_phase": next_phase,
        "observed_phase": observed_phase,
        "predecessor_tick_sha256": state["latest_tick_sha256"],
        "recorded_at": recorded_at,
        "result": dict(result),
        "schema_version": TICK_VERSION,
        "sequence": next_state["sequence"],
        "state_projection": {
            key: next_state[key]
            for key in (
                "active_adapter_dir",
                "active_gate_store",
                "active_ledger_dir",
                "active_p5_store",
                "generation",
                "phase",
            )
        },
    }
    digest = _sha256_bytes(_canonical_bytes(tick))
    next_state["latest_tick_sha256"] = digest
    tick_path = store_dir / "objects" / "sha256" / f"{digest}.json"
    journal_path = store_dir / "runtime" / "tick-commit-journal.json"
    journal = {
        "controller_id": manifest["controller_id"],
        "next_state": next_state,
        "phase": "PREPARED",
        "prepared_at": recorded_at,
        "schema_version": "mvp0-tick-commit-journal/v1",
        "tick": tick,
        "tick_sha256": digest,
    }
    _write_json(journal_path, journal)
    if simulate_crash_after == "PREPARED":
        raise SupervisorError("simulated supervisor crash after tick commit PREPARED")
    already = _write_immutable_idempotent(tick_path, tick)
    if simulate_crash_after == "OBJECT_WRITTEN":
        raise SupervisorError("simulated supervisor crash after tick object write")
    index_path = store_dir / "ticks.jsonl"
    indexed = []
    if index_path.is_file():
        indexed = [json.loads(line) for line in index_path.read_text().splitlines() if line]
    if not any(item.get("tick_sha256") == digest for item in indexed):
        _append_jsonl(index_path, {
            "sequence": tick["sequence"],
            "tick_path": str(tick_path),
            "tick_sha256": digest,
        })
    if simulate_crash_after == "INDEX_WRITTEN":
        raise SupervisorError("simulated supervisor crash after tick index write")
    _write_json(store_dir / "supervisor-state.json", next_state)
    _write_json(journal_path, {**journal, "committed_at": recorded_at, "phase": "COMMITTED"})
    return {
        "already_applied": already,
        "next_phase": next_phase,
        "sequence": tick["sequence"],
        "tick_path": str(tick_path),
        "tick_sha256": digest,
    }


def tick(
    *,
    store_dir: Path,
    action_input: Path | None = None,
    scheduler: Any | None = None,
    recorded_at: str | None = None,
    simulate_crash_after: str | None = None,
) -> dict[str, Any]:
    store_dir = store_dir.resolve()
    timestamp = _now() if recorded_at is None else recorded_at
    _parse_time(timestamp)
    with _lease(store_dir):
        recovered = _recover_tick_commit(store_dir=store_dir)
        manifest, state = _load(store_dir)
        if recovered:
            return {
                "already_applied": True,
                "next_phase": state["phase"],
                "recovered_commit": True,
                "sequence": state["sequence"],
                "tick_sha256": state["latest_tick_sha256"],
            }
        lifecycle_path = store_dir / "runtime" / "lifecycle.json"
        if lifecycle_path.is_file():
            lifecycle = runtime_assurance._load_lifecycle(store_dir)  # noqa: SLF001
            if lifecycle["state"] != "ACTIVE":
                raise SupervisorError(
                    f"supervisor transition refused in runtime lifecycle {lifecycle['state']}"
                )
        observed_phase, action = _phase(manifest, state)
        state_updates: dict[str, Any] = {}
        if observed_phase == "NEEDS_P3":
            result = {"action": "RECORD_P3", **ledger.record_turn(
                ledger_dir=Path(state["active_ledger_dir"]),
                turn_receipt=Path(action["turn_receipt_path"]),
            )}
        elif observed_phase == "NEEDS_P4":
            if action["evaluator_report_required"] and action_input is None:
                raise SupervisorError("P4 requires one evaluator report for this completed receipt")
            if not action["evaluator_report_required"] and action_input is not None:
                raise SupervisorError("P4 forbids an evaluator report for this receipt")
            gate_store = Path(state["active_gate_store"]) if state.get("active_gate_store") else None
            if gate_store is None:
                gate_store = Path(state["active_ledger_dir"]).parent / "gate"
                gate.initialize_store(
                    ledger_dir=Path(state["active_ledger_dir"]), store_dir=gate_store
                )
                state_updates["active_gate_store"] = str(gate_store)
            result = {"action": "DECIDE_P4", **gate.decide(
                store_dir=gate_store,
                experiment_receipt_sha256=action["experiment_receipt_sha256"],
                evaluator_report=action_input,
            )}
        elif observed_phase == "NEEDS_P5":
            p5_store = Path(state["active_p5_store"]) if state.get("active_p5_store") else None
            if action["action"] == "INITIALIZE_P5":
                p5_store = Path(state["active_gate_store"]).parent / "p5-recompile"
                result = {"action": "INITIALIZE_P5", **p5.initialize_store(
                    gate_store=Path(state["active_gate_store"]), store_dir=p5_store
                )}
                state_updates["active_p5_store"] = str(p5_store)
            else:
                if p5_store is None or action_input is None:
                    raise SupervisorError(f"{action['action']} requires one action_input JSON")
                if action["action"] == "PUBLISH_FAILURE_ANALYSIS":
                    result = {"action": action["action"], **p5.publish_analysis(
                        store_dir=p5_store, analysis_path=action_input
                    )}
                elif action["action"] == "PUBLISH_RECOMPILE_REQUEST":
                    result = {"action": action["action"], **p5.publish_request(
                        store_dir=p5_store, request_path=action_input
                    )}
                elif action["action"] == "COMPILE_SUCCESSOR_IR":
                    records = p5._request_records(p5_store)  # noqa: SLF001
                    result = {"action": action["action"], **p5.compile_candidate(
                        store_dir=p5_store,
                        request_sha256=records[0]["request_sha256"],
                        candidate_ir=action_input,
                        author="codex/recompile-compiler",
                    )}
                else:
                    raise SupervisorError(f"unsupported P5 action: {action['action']}")
        elif observed_phase == "NEEDS_ENGINEERING_REVIEW":
            if action_input is None:
                raise SupervisorError("engineering review tick requires one closed review input")
            result = _execute_review(
                manifest=manifest, state=state, action_input=action_input
            )
        elif observed_phase == "NEEDS_CHILD_P2":
            if action_input is None:
                raise SupervisorError("child P2 tick requires one task contract")
            if scheduler is None:
                raise SupervisorError("child P2 unattended dispatch requires a scheduler backend")
            result, state_updates = _execute_child_p2(
                manifest=manifest,
                state=state,
                task_contract=action_input,
                scheduler=scheduler,
            )
        elif observed_phase == "READY":
            if action_input is None:
                raise SupervisorError(f"{action['action']} requires one task contract")
            if scheduler is None:
                raise SupervisorError(f"{action['action']} requires a scheduler backend")
            result = {
                "action": action["action"],
                **worker.dispatch_task(
                    adapter_dir=Path(state["active_adapter_dir"]),
                    task_contract=action_input,
                    unattended=True,
                    runtime_store=store_dir,
                    scheduler=scheduler,
                ),
            }
        elif observed_phase in {"WAITING_HUMAN", "BLOCKED", "STOPPED", "COMPLETED"}:
            raise SupervisorError(f"supervisor is terminal or paused in {observed_phase}")
        elif observed_phase == "WORKER_RUNNING":
            raise SupervisorError("Worker remains active; heartbeat tick may inspect but not transition")
        else:
            raise SupervisorError(f"no authorized transition from {observed_phase}")
        return _commit_tick(
            store_dir=store_dir,
            manifest=manifest,
            state=state,
            observed_phase=observed_phase,
            result=result,
            state_updates=state_updates,
            recorded_at=timestamp,
            simulate_crash_after=simulate_crash_after,
        )


def render_automation(*, store_dir: Path, created_at_ms: int) -> dict[str, Any]:
    manifest, _state = _load(store_dir)
    prompt = HEARTBEAT_PROMPT_PATH.read_text(encoding="utf-8").format(
        controller_id=manifest["controller_id"],
        store_dir=str(store_dir.resolve()),
        target_thread_id=manifest["target_thread_id"],
        run_dir=manifest["run_dir"],
    )
    rendered = automation.render_thread_automation(
        controller_id=manifest["controller_id"],
        name=f"AutoResearch MVP0 · {Path(manifest['run_dir']).name}",
        prompt=prompt,
        target_thread_id=manifest["target_thread_id"],
        created_at_ms=created_at_ms,
    )
    path = Path(manifest["automation_path"])
    return {"automation_path": str(path), "automation_toml": rendered}


def bootstrap_runtime(
    *,
    store_dir: Path,
    scheduler: Any,
    launch_agents_dir: Path,
    python_executable: Path,
    now: str,
    l0_interval_seconds: int = 300,
    l1_interval_seconds: int = 600,
    l2_interval_seconds: int = 60,
    heartbeat_stale_seconds: int = 900,
) -> dict[str, Any]:
    manifest, _state = _load(store_dir)
    return runtime_assurance.bootstrap_assurance(
        store_dir=store_dir.resolve(),
        controller_id=manifest["controller_id"],
        target_thread_id=manifest["target_thread_id"],
        l1_automation_path=Path(manifest["automation_path"]),
        l0_interval_seconds=l0_interval_seconds,
        l1_interval_seconds=l1_interval_seconds,
        l2_interval_seconds=l2_interval_seconds,
        heartbeat_stale_seconds=heartbeat_stale_seconds,
        scheduler=scheduler,
        launch_agents_dir=launch_agents_dir,
        python_executable=python_executable,
        now=now,
    )


def inspect_runtime(
    *, store_dir: Path, scheduler: Any, processes: Any | None, now: str
) -> dict[str, Any]:
    manifest, state = _load(store_dir)
    runtime = runtime_assurance.inspect_runtime(
        store_dir=store_dir.resolve(), scheduler=scheduler, processes=processes, now=now
    )
    phase, action = _phase(manifest, state)
    return {
        "controller": {
            "action": _action_envelope(manifest, state, action),
            "phase": phase,
            "sequence": state["sequence"],
        },
        "runtime": runtime,
    }


def pause(
    *, store_dir: Path, scheduler: Any, authority_id: str, now: str
) -> dict[str, Any]:
    return runtime_assurance.pause_runtime(
        store_dir=store_dir.resolve(), scheduler=scheduler,
        authority_id=authority_id, now=now
    )


def resume(
    *, store_dir: Path, scheduler: Any, authority_id: str, now: str
) -> dict[str, Any]:
    verify_supervisor(store_dir=store_dir)
    return runtime_assurance.resume_runtime(
        store_dir=store_dir.resolve(), scheduler=scheduler,
        authority_id=authority_id, now=now
    )


def stop(
    *, store_dir: Path, scheduler: Any, processes: Any, authority_id: str, now: str
) -> dict[str, Any]:
    return runtime_assurance.shutdown_runtime(
        store_dir=store_dir.resolve(), scheduler=scheduler, processes=processes,
        authority_id=authority_id, now=now
    )


def heartbeat(*, store_dir: Path, now: str, source: str) -> dict[str, Any]:
    manifest, _state = _load(store_dir)
    return runtime_assurance.record_l1_heartbeat(
        store_dir=store_dir.resolve(),
        controller_id=manifest["controller_id"],
        target_thread_id=manifest["target_thread_id"],
        observed_at=now,
        source=source,
    )


def verify_supervisor(*, store_dir: Path) -> dict[str, Any]:
    manifest, state = _load(store_dir)
    journal_path = store_dir.resolve() / "runtime" / "tick-commit-journal.json"
    if journal_path.is_file():
        journal = _read_json(journal_path)
        if not isinstance(journal, dict) or journal.get("phase") != "COMMITTED":
            raise SupervisorError("supervisor has an uncommitted tick journal")
    index_path = store_dir.resolve() / "ticks.jsonl"
    previous = None
    entries = []
    if index_path.is_file():
        entries = [json.loads(line) for line in index_path.read_text().splitlines() if line]
    for sequence, entry in enumerate(entries, 1):
        path = Path(entry["tick_path"])
        tick_value, digest = _immutable(path, "supervisor tick")
        if (
            entry != {"sequence": sequence, "tick_path": str(path), "tick_sha256": digest}
            or tick_value.get("schema_version") != TICK_VERSION
            or tick_value.get("sequence") != sequence
            or tick_value.get("predecessor_tick_sha256") != previous
            or path != store_dir.resolve() / "objects" / "sha256" / f"{digest}.json"
        ):
            raise SupervisorError("supervisor tick lineage is inconsistent")
        previous = digest
    if state["sequence"] != len(entries) or state["latest_tick_sha256"] != previous:
        raise SupervisorError("supervisor state differs from the tick chain")
    phase, _action = _phase(manifest, state)
    if state["phase"] != phase:
        raise SupervisorError("supervisor state differs from durable P1-P5 lineage")
    return {
        "controller_id": manifest["controller_id"],
        "phase": phase,
        "sequence": state["sequence"],
        "verified": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MVP-0 P6 supervisory controller")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--run-dir", type=Path, required=True)
    init.add_argument("--target-thread-id", required=True)
    init.add_argument("--adapter-dir", type=Path, required=True)
    init.add_argument("--ledger-dir", type=Path, required=True)
    init.add_argument("--gate-store", type=Path, required=True)
    init.add_argument("--p5-store", type=Path, required=True)
    init.add_argument("--store-dir", type=Path)
    for name in ("inspect", "verify"):
        command = sub.add_parser(name)
        command.add_argument("--store-dir", type=Path, required=True)
    run = sub.add_parser("tick")
    run.add_argument("--store-dir", type=Path, required=True)
    run.add_argument("--action-input", type=Path)
    render = sub.add_parser("render-automation")
    render.add_argument("--store-dir", type=Path, required=True)
    render.add_argument("--created-at-ms", type=int, required=True)
    bootstrap = sub.add_parser("bootstrap-assurance")
    bootstrap.add_argument("--store-dir", type=Path, required=True)
    bootstrap.add_argument("--launch-agents-dir", type=Path, required=True)
    bootstrap.add_argument("--python-executable", type=Path, required=True)
    bootstrap.add_argument("--now", required=True)
    l0 = sub.add_parser("l0-health-tick")
    l0.add_argument("--store-dir", type=Path, required=True)
    l0.add_argument("--now", required=True)
    heartbeat_command = sub.add_parser("heartbeat")
    heartbeat_command.add_argument("--store-dir", type=Path, required=True)
    heartbeat_command.add_argument("--now", required=True)
    heartbeat_command.add_argument(
        "--source",
        choices=("SCHEDULED_CODEX_TASK", "MANUAL_BOUND_TICK"),
        default="SCHEDULED_CODEX_TASK",
    )
    runtime = sub.add_parser("inspect-runtime")
    runtime.add_argument("--store-dir", type=Path, required=True)
    runtime.add_argument("--now", required=True)
    for name in ("pause", "resume", "stop"):
        command = sub.add_parser(name)
        command.add_argument("--store-dir", type=Path, required=True)
        command.add_argument("--authority-id", required=True)
        command.add_argument("--now", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            result = initialize_supervisor(
                run_dir=args.run_dir,
                target_thread_id=args.target_thread_id,
                adapter_dir=args.adapter_dir,
                ledger_dir=args.ledger_dir,
                gate_store=args.gate_store,
                p5_store=args.p5_store,
                store_dir=args.store_dir,
            )
        elif args.command == "inspect":
            result = inspect_supervisor(store_dir=args.store_dir)
        elif args.command == "verify":
            result = verify_supervisor(store_dir=args.store_dir)
        elif args.command == "render-automation":
            result = render_automation(
                store_dir=args.store_dir, created_at_ms=args.created_at_ms
            )
        elif args.command == "bootstrap-assurance":
            result = bootstrap_runtime(
                store_dir=args.store_dir,
                scheduler=LaunchctlScheduler(),
                launch_agents_dir=args.launch_agents_dir,
                python_executable=args.python_executable,
                now=args.now,
            )
        elif args.command == "l0-health-tick":
            result = runtime_assurance.run_l0_health_tick(
                store_dir=args.store_dir,
                scheduler=LaunchctlScheduler(),
                now=args.now,
            )
        elif args.command == "heartbeat":
            result = heartbeat(
                store_dir=args.store_dir, now=args.now, source=args.source
            )
        elif args.command == "inspect-runtime":
            result = inspect_runtime(
                store_dir=args.store_dir,
                scheduler=LaunchctlScheduler(),
                processes=runtime_assurance.LocalProcessInspector(),
                now=args.now,
            )
        elif args.command == "pause":
            result = pause(
                store_dir=args.store_dir, scheduler=LaunchctlScheduler(),
                authority_id=args.authority_id, now=args.now
            )
        elif args.command == "resume":
            result = resume(
                store_dir=args.store_dir, scheduler=LaunchctlScheduler(),
                authority_id=args.authority_id, now=args.now
            )
        elif args.command == "stop":
            result = stop(
                store_dir=args.store_dir,
                scheduler=LaunchctlScheduler(),
                processes=runtime_assurance.LocalProcessInspector(),
                authority_id=args.authority_id,
                now=args.now,
            )
        else:
            result = tick(
                store_dir=args.store_dir,
                action_input=args.action_input,
                scheduler=LaunchctlScheduler(),
            )
    except (
        SupervisorError,
        worker.AdapterError,
        ledger.LedgerError,
        gate.GateError,
        p5.RecompileError,
        compiler.CompilerError,
        delegated_review.DelegatedReviewError,
        runtime_assurance.AssuranceError,
        OSError,
    ) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=os.sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
