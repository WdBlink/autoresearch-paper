#!/usr/bin/env python3
"""Minimal fixed-session Claude Code/MiniMax Worker Adapter for MVP-0 P2.

The Adapter is intentionally separate from the legacy Harness.  It owns one
detached Git worktree, one exact Claude Code session UUID, closed task/result
contracts, and an immutable receipt per launched turn.  It does not schedule,
retry, review, promote, or accept scientific results.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

try:
    from . import research_compiler as compiler
    from . import runtime_assurance
    from .launchd_registration import LaunchctlScheduler
except ImportError:  # pragma: no cover - direct script execution
    import research_compiler as compiler  # type: ignore[no-redef]
    import runtime_assurance  # type: ignore[no-redef]
    from launchd_registration import LaunchctlScheduler  # type: ignore[no-redef]


MVP_ROOT = Path(__file__).resolve().parent
TASK_SCHEMA_PATH = MVP_ROOT / "schemas" / "worker-task-contract.schema.json"
RESULT_SCHEMA_PATH = MVP_ROOT / "schemas" / "worker-result.schema.json"
ADAPTER_VERSION = "worker-adapter/v2"
SUCCESSOR_ADAPTER_VERSION = "worker-adapter/v3"
SESSION_VERSION = "worker-session/v1"
RECEIPT_VERSION = "worker-identity-usage-receipt/v2"
ALLOWED_TOOLS = ("Read", "Glob", "Grep", "Write", "Edit", "Bash")
PERMISSION_MODE = "dontAsk"
GIT_OID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
MODEL_NORMALIZATION_RE = re.compile(r"[^a-z0-9]+")


class AdapterError(RuntimeError):
    """A fail-closed Worker Adapter contract error."""


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
        raise AdapterError(f"value is not canonical JSON: {exc}") from exc
    return (rendered + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle, parse_constant=_reject_constant)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise AdapterError(f"cannot read strict JSON from {path}: {exc}") from exc


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _atomic_write(path: Path, payload: bytes, *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and (path.exists() or path.is_symlink()):
        raise AdapterError(f"immutable artifact already exists: {path}")
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


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise AdapterError(
            f"{label} fields differ: missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _validate_against_schema(value: Any, schema_path: Path, label: str) -> None:
    schema = _load_json(schema_path)
    if not isinstance(schema, dict):
        raise AdapterError(f"{label} schema root must be an object")
    try:
        issues = compiler._schema_issues(value, schema, root=schema)  # noqa: SLF001
    except compiler.CompilerError as exc:
        raise AdapterError(str(exc)) from exc
    if issues:
        rendered = "; ".join(
            f"{issue.code} at {issue.path}: {issue.message}" for issue in issues
        )
        raise AdapterError(f"{label} violates its closed schema: {rendered}")


def _claude_transport_schema(value: Any) -> Any:
    """Translate the authoritative 2020-12 subset to Claude's draft-07 subset.

    Claude Code 2.1.205 asks its bundled validator to resolve any declared
    ``$schema`` URI but does not register the 2020-12 metaschema.  Keep the
    repository's 2020-12 schema authoritative for Host validation, while
    sending a declaration-free draft-07-compatible projection over the CLI.
    """

    if isinstance(value, list):
        return [_claude_transport_schema(item) for item in value]
    if isinstance(value, str):
        return value.replace("#/$defs/", "#/definitions/")
    if not isinstance(value, dict):
        return value
    projected: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"$schema", "$id"}:
            continue
        projected["definitions" if key == "$defs" else key] = _claude_transport_schema(item)
    return projected


def _result_transport_schema() -> dict[str, Any]:
    schema = _claude_transport_schema(_load_json(RESULT_SCHEMA_PATH))
    if not isinstance(schema, dict):
        raise AdapterError("Worker result transport schema root must be an object")
    rendered = _canonical_bytes(schema)
    if b"2020-12" in rendered or b"#/$defs/" in rendered or b'"$defs"' in rendered:
        raise AdapterError("Worker result transport schema is not Claude-compatible")
    return schema


def _resolve_executable(command: str) -> Path:
    if os.sep in command or (os.altsep and os.altsep in command):
        resolved = Path(command).expanduser().resolve()
    else:
        found = shutil.which(command)
        if found is None:
            raise AdapterError(f"Claude Code executable is unavailable on PATH: {command}")
        resolved = Path(found).resolve()
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise AdapterError(f"Claude Code executable is not executable: {resolved}")
    return resolved


def _run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise AdapterError(f"Git command failed ({' '.join(args)}): {message[:500]}")
    return proc


def _git_text(root: Path, *args: str) -> str:
    return _run_git(root, *args).stdout.decode("utf-8", errors="strict").strip()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _normalize_model(value: str) -> str:
    return MODEL_NORMALIZATION_RE.sub("", value.lower())


def _safe_relative_path(raw: str, label: str) -> str:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise AdapterError(f"{label} must be a non-empty repository-relative path")
    candidate = PurePosixPath(raw)
    if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
        raise AdapterError(f"{label} must not be absolute or traverse parents: {raw!r}")
    normalized = candidate.as_posix()
    if normalized.startswith(".git/") or normalized == ".git":
        raise AdapterError(f"{label} cannot target Git metadata")
    return normalized


def _glob_regex(pattern: str) -> re.Pattern[str]:
    pattern = _safe_relative_path(pattern, "path pattern")
    chunks: list[str] = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    chunks.append("(?:.*/)?")
                    index += 1
                else:
                    chunks.append(".*")
                continue
            chunks.append("[^/]*")
        elif char == "?":
            chunks.append("[^/]")
        else:
            chunks.append(re.escape(char))
        index += 1
    chunks.append("$")
    return re.compile("".join(chunks))


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(_glob_regex(pattern).fullmatch(path) is not None for pattern in patterns)


def _load_verified_ir(
    *,
    freeze_receipt: Path,
    compiler_store: Path,
    allow_engineering_fixture: bool,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    try:
        verified = compiler.verify_freeze(
            receipt_path=freeze_receipt,
            store=compiler_store,
            check_paths=True,
        )
    except compiler.CompilerError as exc:
        raise AdapterError(f"Research IR freeze replay failed: {exc}") from exc
    receipt = _load_json(freeze_receipt)
    scope = receipt.get("approval_scope") if isinstance(receipt, dict) else None
    if scope not in {"OWNER_REVIEWED", "DELEGATED_ENGINEERING_REVIEW"} and not (
        allow_engineering_fixture and scope == "ENGINEERING_ACCEPTANCE"
    ):
        raise AdapterError(
            "Worker Adapter requires an OWNER_REVIEWED or DELEGATED_ENGINEERING_REVIEW Research IR freeze; "
            "ENGINEERING_ACCEPTANCE is allowed only with --engineering-test"
        )
    ir_digest = verified["research_ir_sha256"]
    ir_path = compiler_store.resolve() / "objects" / "sha256" / f"{ir_digest}.json"
    ir = _load_json(ir_path)
    if not isinstance(ir, dict) or _sha256_bytes(_canonical_bytes(ir)) != ir_digest:
        raise AdapterError("verified Research IR object is missing or not content addressed")
    return ir, receipt, verified["freeze_receipt_sha256"], ir_digest


def _adapter_manifest(adapter_dir: Path) -> dict[str, Any]:
    path = adapter_dir / "adapter-manifest.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o777 != 0o444:
        raise AdapterError("adapter manifest is missing, mutable, or a symlink")
    value = _load_json(path)
    if not isinstance(value, dict):
        raise AdapterError("adapter manifest must be an object")
    expected = {
        "adapter_id",
        "base_commit",
        "claude_executable",
        "claude_executable_sha256",
        "compiler_store",
        "created_at",
        "freeze_approval_scope",
        "freeze_receipt_path",
        "freeze_receipt_sha256",
        "isolation_assurance",
        "max_budget_usd_per_turn",
        "permission_mode",
        "research_ir_path",
        "research_ir_sha256",
        "result_schema_sha256",
        "result_transport_schema_sha256",
        "schema_version",
        "session_id",
        "source_repo",
        "task_schema_sha256",
        "tools",
        "worker_model",
        "worktree_root",
    }
    if value.get("schema_version") == SUCCESSOR_ADAPTER_VERSION:
        expected |= {
            "p5_freeze_binding_path",
            "p5_freeze_binding_sha256",
            "p5_store",
            "predecessor_adapter_id",
            "predecessor_task_contract_sha256",
            "predecessor_turn_receipt_path",
            "predecessor_turn_receipt_sha256",
            "session_start_mode",
        }
    _exact_keys(value, expected, "adapter manifest")
    if value["schema_version"] not in {ADAPTER_VERSION, SUCCESSOR_ADAPTER_VERSION}:
        raise AdapterError("adapter manifest version is unsupported")
    try:
        if _sha256_file(Path(value["claude_executable"])) != value["claude_executable_sha256"]:
            raise AdapterError("Claude Code executable identity drifted")
        if _sha256_file(Path(value["freeze_receipt_path"])) != value["freeze_receipt_sha256"]:
            raise AdapterError("Research IR freeze receipt bytes drifted")
        if _sha256_file(TASK_SCHEMA_PATH) != value["task_schema_sha256"]:
            raise AdapterError("Worker task schema drifted")
        if _sha256_file(RESULT_SCHEMA_PATH) != value["result_schema_sha256"]:
            raise AdapterError("Worker result schema drifted")
        if _sha256_bytes(_canonical_bytes(_result_transport_schema())) != value["result_transport_schema_sha256"]:
            raise AdapterError("Worker result transport schema drifted")
    except OSError as exc:
        raise AdapterError(f"adapter identity artifact is unavailable: {exc}") from exc
    try:
        uuid.UUID(value["session_id"])
    except (TypeError, ValueError, AttributeError) as exc:
        raise AdapterError("adapter session_id is not a UUID") from exc
    if value["tools"] != list(ALLOWED_TOOLS) or value["permission_mode"] != PERMISSION_MODE:
        raise AdapterError("adapter tool or permission boundary drifted")
    if value["schema_version"] == SUCCESSOR_ADAPTER_VERSION:
        if value["session_start_mode"] != "RESUME_PREDECESSOR":
            raise AdapterError("successor adapter has an invalid session_start_mode")
        for path_field, digest_field in (
            ("predecessor_turn_receipt_path", "predecessor_turn_receipt_sha256"),
            ("p5_freeze_binding_path", "p5_freeze_binding_sha256"),
        ):
            path = Path(value[path_field])
            if not path.is_absolute() or _sha256_file(path) != value[digest_field]:
                raise AdapterError(f"successor adapter {path_field} binding drifted")
    return value


def _session_state(adapter_dir: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    path = adapter_dir / "session.json"
    value = _load_json(path)
    if not isinstance(value, dict):
        raise AdapterError("session state must be an object")
    required = {
        "adapter_manifest_sha256",
        "created_at",
        "last_receipt_path",
        "last_receipt_sha256",
        "paused_reason",
        "schema_version",
        "session_id",
        "state",
        "turn_count",
        "updated_at",
    }
    _exact_keys(value, required, "session state")
    if (
        value["schema_version"] != SESSION_VERSION
        or value["session_id"] != manifest["session_id"]
        or value["adapter_manifest_sha256"]
        != _sha256_file(adapter_dir / "adapter-manifest.json")
    ):
        raise AdapterError("session state is not bound to this adapter manifest")
    if value["state"] not in {"READY", "BUSY", "PAUSED"}:
        raise AdapterError("session state is invalid")
    if not isinstance(value["turn_count"], int) or isinstance(value["turn_count"], bool) or value["turn_count"] < 0:
        raise AdapterError("session turn_count must be a non-negative integer")
    receipts = sorted((adapter_dir / "turns").glob("*.json")) if (adapter_dir / "turns").exists() else []
    if len(receipts) != value["turn_count"]:
        raise AdapterError("immutable turn receipt chain does not match session turn_count")
    for index, receipt_path in enumerate(receipts, 1):
        if receipt_path.is_symlink() or receipt_path.stat().st_mode & 0o777 != 0o444:
            raise AdapterError("turn receipt is mutable or a symlink")
        receipt = _load_json(receipt_path)
        if (
            not isinstance(receipt, dict)
            or receipt.get("session_id") != manifest["session_id"]
            or receipt.get("turn_index") != index
            or not receipt_path.name.startswith(f"{index:06d}-")
        ):
            raise AdapterError("turn receipt chain identity changed")
    if receipts:
        if (
            value["last_receipt_path"] != str(receipts[-1])
            or value["last_receipt_sha256"] != _sha256_file(receipts[-1])
        ):
            raise AdapterError("session last receipt pointer changed")
    elif value["last_receipt_path"] is not None or value["last_receipt_sha256"] is not None:
        raise AdapterError("empty session cannot name a last receipt")
    return value


def _successor_bindings(
    *,
    predecessor_turn_receipt: Path,
    p5_store: Path,
    p5_freeze_binding: Path,
    freeze_digest: str,
    ir_digest: str,
    source_repo: Path,
    worker_model: str,
    base_commit: str,
) -> dict[str, Any]:
    """Replay the exact terminal predecessor and P5 child-freeze lineage."""

    predecessor_turn_receipt = predecessor_turn_receipt.resolve()
    if (
        predecessor_turn_receipt.is_symlink()
        or not predecessor_turn_receipt.is_file()
        or predecessor_turn_receipt.stat().st_mode & 0o777 != 0o444
    ):
        raise AdapterError("predecessor turn receipt is missing, mutable, or a symlink")
    predecessor = _load_json(predecessor_turn_receipt)
    if not isinstance(predecessor, dict) or predecessor.get("schema_version") != RECEIPT_VERSION:
        raise AdapterError("predecessor turn receipt version is unsupported")
    predecessor_adapter_dir = predecessor_turn_receipt.parent.parent
    predecessor_manifest = _adapter_manifest(predecessor_adapter_dir)
    predecessor_session = _session_state(predecessor_adapter_dir, predecessor_manifest)
    if (
        predecessor_session["last_receipt_path"] != str(predecessor_turn_receipt)
        or predecessor_session["state"] != "PAUSED"
        or predecessor.get("outcome") != "FAILED"
    ):
        raise AdapterError("successor requires the latest failed, paused predecessor turn")
    if (
        predecessor.get("adapter_id") != predecessor_manifest["adapter_id"]
        or predecessor.get("session_id") != predecessor_manifest["session_id"]
        or predecessor.get("task_contract_sha256") is None
        or predecessor_manifest["source_repo"] != str(source_repo)
        or predecessor_manifest["base_commit"] != base_commit
        or _normalize_model(predecessor_manifest["worker_model"])
        != _normalize_model(worker_model)
    ):
        raise AdapterError("predecessor Worker identity differs from the successor binding")

    p5_store = p5_store.resolve()
    p5_freeze_binding = p5_freeze_binding.resolve()
    try:
        from . import recompile_loop as p5
    except ImportError:  # pragma: no cover - direct script execution
        import recompile_loop as p5  # type: ignore[no-redef]
    try:
        verified_p5 = p5.verify_store(store_dir=p5_store)
    except p5.RecompileError as exc:
        raise AdapterError(f"successor P5 replay failed: {exc}") from exc
    if verified_p5.get("stage") != "FROZEN":
        raise AdapterError("successor P5 store is not frozen")
    if (
        p5_freeze_binding.is_symlink()
        or not p5_freeze_binding.is_file()
        or p5_freeze_binding.stat().st_mode & 0o777 != 0o444
        or p5_freeze_binding.parent != p5_store / "freezes" / "sha256"
        or p5_freeze_binding.name != f"{_sha256_file(p5_freeze_binding)}.json"
    ):
        raise AdapterError("successor P5 freeze binding is not content addressed")
    p5_binding = _load_json(p5_freeze_binding)
    if not isinstance(p5_binding, dict) or (
        p5_binding.get("child_freeze_receipt_sha256") != freeze_digest
        or p5_binding.get("child_ir_sha256") != ir_digest
        or p5_binding.get("parent_freeze_receipt_sha256")
        != predecessor_manifest["freeze_receipt_sha256"]
        or p5_binding.get("parent_ir_sha256")
        != predecessor_manifest["research_ir_sha256"]
    ):
        raise AdapterError("successor P5 freeze does not descend from the predecessor")
    return {
        "p5_freeze_binding_path": str(p5_freeze_binding),
        "p5_freeze_binding_sha256": _sha256_file(p5_freeze_binding),
        "p5_store": str(p5_store),
        "predecessor_adapter_id": predecessor_manifest["adapter_id"],
        "predecessor_task_contract_sha256": predecessor["task_contract_sha256"],
        "predecessor_turn_receipt_path": str(predecessor_turn_receipt),
        "predecessor_turn_receipt_sha256": _sha256_file(predecessor_turn_receipt),
        "session_id": predecessor_manifest["session_id"],
        "session_start_mode": "RESUME_PREDECESSOR",
    }


def initialize_adapter(
    *,
    freeze_receipt: Path,
    compiler_store: Path,
    source_repo: Path,
    adapter_dir: Path,
    worktree: Path,
    claude_bin: str,
    worker_model: str,
    max_budget_usd_per_turn: float,
    engineering_test: bool = False,
    predecessor_turn_receipt: Path | None = None,
    p5_store: Path | None = None,
    p5_freeze_binding: Path | None = None,
) -> dict[str, Any]:
    """Create exactly one detached worktree and exact persistent session binding."""

    if not isinstance(max_budget_usd_per_turn, (int, float)) or isinstance(max_budget_usd_per_turn, bool) or max_budget_usd_per_turn <= 0:
        raise AdapterError("max_budget_usd_per_turn must be positive")
    if not isinstance(worker_model, str) or not worker_model.strip():
        raise AdapterError("worker_model must be non-empty")
    if not _normalize_model(worker_model).startswith("minimax"):
        raise AdapterError("P2 Worker model must be an explicit MiniMax model")
    ir, freeze_record, freeze_digest, ir_digest = _load_verified_ir(
        freeze_receipt=freeze_receipt.resolve(),
        compiler_store=compiler_store.resolve(),
        allow_engineering_fixture=engineering_test,
    )
    source_repo = source_repo.resolve()
    if not source_repo.is_dir():
        raise AdapterError("source_repo must be an existing directory")
    git_root = Path(_git_text(source_repo, "rev-parse", "--show-toplevel")).resolve()
    if git_root != source_repo:
        raise AdapterError("P2 requires source_repo to be the Git repository root")
    code_root = Path(ir.get("source", {}).get("code_root", "")).resolve()
    if code_root != source_repo:
        raise AdapterError("source_repo must equal frozen Research IR source.code_root")
    if _git_text(source_repo, "status", "--porcelain=v1", "--untracked-files=all"):
        raise AdapterError("source_repo must be clean before creating the research worktree")
    if _git_text(source_repo, "submodule", "status"):
        raise AdapterError("P2 does not support repositories with submodules")
    base_commit = _git_text(source_repo, "rev-parse", "HEAD")
    if not GIT_OID_RE.fullmatch(base_commit):
        raise AdapterError("source_repo HEAD is not a full commit hash")

    adapter_dir = adapter_dir.resolve()
    worktree = worktree.resolve()
    if adapter_dir.exists() or adapter_dir.is_symlink():
        raise AdapterError("adapter_dir already exists; automatic rebinding is forbidden")
    if worktree.exists() or worktree.is_symlink():
        raise AdapterError("worktree already exists")
    if _inside(adapter_dir, source_repo) or _inside(worktree, source_repo):
        raise AdapterError("adapter_dir and worktree must be outside source_repo")
    if _inside(adapter_dir, worktree) or _inside(worktree, adapter_dir):
        raise AdapterError("adapter_dir and worktree must not overlap")
    adapter_dir.parent.mkdir(parents=True, exist_ok=True)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    claude = _resolve_executable(claude_bin)
    successor_inputs = (
        predecessor_turn_receipt,
        p5_store,
        p5_freeze_binding,
    )
    if any(item is not None for item in successor_inputs) and not all(
        item is not None for item in successor_inputs
    ):
        raise AdapterError(
            "successor initialization requires predecessor turn, P5 store, and P5 freeze binding together"
        )
    successor: dict[str, Any] | None = None
    if predecessor_turn_receipt is not None:
        assert p5_store is not None and p5_freeze_binding is not None
        successor = _successor_bindings(
            predecessor_turn_receipt=predecessor_turn_receipt,
            p5_store=p5_store,
            p5_freeze_binding=p5_freeze_binding,
            freeze_digest=freeze_digest,
            ir_digest=ir_digest,
            source_repo=source_repo,
            worker_model=worker_model.strip(),
            base_commit=base_commit,
        )
    session_id = str(uuid.uuid4()) if successor is None else successor["session_id"]
    adapter_id = "mvp0-worker-" + uuid.uuid4().hex[:16]

    _run_git(source_repo, "worktree", "add", "--detach", str(worktree), base_commit)
    try:
        adapter_dir.mkdir(parents=False, exist_ok=False)
        manifest = {
            "adapter_id": adapter_id,
            "base_commit": base_commit,
            "claude_executable": str(claude),
            "claude_executable_sha256": _sha256_file(claude),
            "compiler_store": str(compiler_store.resolve()),
            "created_at": _now(),
            "freeze_approval_scope": freeze_record["approval_scope"],
            "freeze_receipt_path": str(freeze_receipt.resolve()),
            "freeze_receipt_sha256": freeze_digest,
            "isolation_assurance": "task-scoped per-turn change boundary; not an OS sandbox",
            "max_budget_usd_per_turn": float(max_budget_usd_per_turn),
            "permission_mode": PERMISSION_MODE,
            "research_ir_path": str(
                compiler_store.resolve() / "objects" / "sha256" / f"{ir_digest}.json"
            ),
            "research_ir_sha256": ir_digest,
            "result_schema_sha256": _sha256_file(RESULT_SCHEMA_PATH),
            "result_transport_schema_sha256": _sha256_bytes(
                _canonical_bytes(_result_transport_schema())
            ),
            "schema_version": (
                ADAPTER_VERSION if successor is None else SUCCESSOR_ADAPTER_VERSION
            ),
            "session_id": session_id,
            "source_repo": str(source_repo),
            "task_schema_sha256": _sha256_file(TASK_SCHEMA_PATH),
            "tools": list(ALLOWED_TOOLS),
            "worker_model": worker_model.strip(),
            "worktree_root": str(worktree),
        }
        if successor is not None:
            manifest.update({key: value for key, value in successor.items() if key != "session_id"})
        _write_json(adapter_dir / "adapter-manifest.json", manifest, immutable=True)
        session = {
            "adapter_manifest_sha256": _sha256_file(adapter_dir / "adapter-manifest.json"),
            "created_at": manifest["created_at"],
            "last_receipt_path": None,
            "last_receipt_sha256": None,
            "paused_reason": None,
            "schema_version": SESSION_VERSION,
            "session_id": session_id,
            "state": "READY",
            "turn_count": 0,
            "updated_at": manifest["created_at"],
        }
        _write_json(adapter_dir / "session.json", session)
    except Exception:
        if adapter_dir.exists():
            shutil.rmtree(adapter_dir)
        _run_git(source_repo, "worktree", "remove", "--force", str(worktree), check=False)
        raise
    return {
        "adapter_dir": str(adapter_dir),
        "adapter_id": adapter_id,
        "base_commit": base_commit,
        "session_id": session_id,
        "state": "READY",
        "worker_model": worker_model.strip(),
        "worktree_root": str(worktree),
    }


def _load_ir_from_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(manifest["research_ir_path"])
    ir = _load_json(path)
    if not isinstance(ir, dict) or _sha256_bytes(_canonical_bytes(ir)) != manifest["research_ir_sha256"]:
        raise AdapterError("frozen Research IR bytes drifted")
    return ir


def validate_task_contract(contract: Any, manifest: Mapping[str, Any], ir: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a task against the closed schema and frozen Research IR authority."""

    _validate_against_schema(contract, TASK_SCHEMA_PATH, "Worker task contract")
    if not isinstance(contract, dict):
        raise AdapterError("Worker task contract must be an object")
    if contract["research_ir_sha256"] != manifest["research_ir_sha256"]:
        raise AdapterError("Worker task contract names a different Research IR")
    experiments = {
        item.get("id"): item
        for item in ir.get("experiment_plan", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    experiment = experiments.get(contract["experiment_id"])
    if experiment is None:
        raise AdapterError("Worker task experiment_id is not present in the frozen Research IR")
    selected_ids = set(contract["search_space_ids"])
    experiment_ids = set(experiment.get("search_space_ids", []))
    if not selected_ids.issubset(experiment_ids):
        raise AdapterError("Worker task selects search space outside its frozen experiment")
    spaces = {
        item.get("id"): item
        for item in ir.get("allowed_search_space", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if any(item not in spaces for item in selected_ids):
        raise AdapterError("Worker task selects an unknown frozen search space")
    authorized_paths: set[str] = {
        _safe_relative_path(path, "Research IR allowed path")
        for space_id in selected_ids
        for path in spaces[space_id].get("paths", [])
    }
    authorized_paths.update(
        _safe_relative_path(path, "Research IR expected artifact")
        for path in experiment.get("expected_artifacts", [])
    )
    task_paths = {
        _safe_relative_path(path, "Worker task allowed path")
        for path in contract["allowed_paths"]
    }
    if not task_paths.issubset(authorized_paths):
        raise AdapterError(
            "Worker task allowed_paths must be exact patterns already frozen by "
            "the selected search spaces or experiment expected artifacts"
        )
    authorized_operations = {"READ", "EXECUTE"}
    for space_id in selected_ids:
        authorized_operations.update(spaces[space_id].get("operations", []))
    if not set(contract["allowed_operations"]).issubset(authorized_operations):
        raise AdapterError("Worker task requests operations outside the frozen search space")
    if not {"READ", "EXECUTE"}.issubset(set(contract["allowed_operations"])):
        raise AdapterError("Worker task requires explicit READ and EXECUTE operations")
    if contract["command_argv"] != experiment.get("command_argv"):
        raise AdapterError("Worker task command_argv must equal the frozen experiment command")
    input_paths: set[str] = set()
    input_digests: dict[str, str] = {}
    for item in contract["input_artifacts"]:
        path = _safe_relative_path(item["path"], "Worker task input artifact")
        if path in input_paths:
            raise AdapterError("Worker task input_artifacts contain duplicate paths")
        input_paths.add(path)
        input_digests[path] = item["sha256"]
    context = contract["experiment_context"]
    for label, artifacts in (
        ("data", context["data_artifacts"]),
        ("environment", context["environment"]["artifacts"]),
    ):
        seen: set[str] = set()
        for item in artifacts:
            path = _safe_relative_path(item["path"], f"Worker task {label} artifact")
            if path in seen:
                raise AdapterError(f"Worker task {label} artifacts contain duplicate paths")
            seen.add(path)
            if input_digests.get(path) != item["sha256"]:
                raise AdapterError(
                    f"Worker task {label} provenance must name an exact input_artifact: {path}"
                )
    return contract


def _file_digest(path: Path) -> tuple[str, str]:
    if path.is_symlink():
        return "symlink", _sha256_bytes(("symlink:" + os.readlink(path)).encode("utf-8"))
    if path.is_file():
        return "file", _sha256_file(path)
    if not path.exists():
        return "missing", ""
    return "special", ""


def _assert_no_symlink_traversal(
    worktree: Path,
    relative: str,
    *,
    label: str,
    allow_leaf_symlink: bool = False,
) -> None:
    """Reject symlinks in every existing component of a worktree path."""

    parts = PurePosixPath(_safe_relative_path(relative, label)).parts
    current = worktree
    for index, part in enumerate(parts):
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return
        is_leaf = index == len(parts) - 1
        if stat.S_ISLNK(mode) and not (is_leaf and allow_leaf_symlink):
            raise AdapterError(f"{label} traverses a symbolic link: {relative}")


def _pattern_scan_root(pattern: str) -> Path:
    parts: list[str] = []
    for part in PurePosixPath(pattern).parts:
        if any(marker in part for marker in ("*", "?", "[")):
            break
        parts.append(part)
    return Path(*parts) if parts else Path(".")


def _inventory(
    worktree: Path,
    include_patterns: Iterable[str] = (),
) -> dict[str, dict[str, str]]:
    raw = _run_git(worktree, "ls-files", "-co", "--exclude-standard", "-z").stdout
    patterns = tuple(include_patterns)
    paths = {
        item.decode("utf-8", errors="strict") for item in raw.split(b"\0") if item
    }
    paths = {path for path in paths if not _is_ephemeral_runtime_path(path)}
    # Git intentionally hides ignored files.  Explicit task paths are a stronger
    # boundary than ignore policy, so scan only their static roots and add any
    # matching ignored files to the per-turn inventory.
    for pattern in patterns:
        scan_root = worktree / _pattern_scan_root(pattern)
        relative_root = scan_root.relative_to(worktree).as_posix()
        if relative_root != ".":
            _assert_no_symlink_traversal(
                worktree,
                relative_root,
                label="task inventory root",
                allow_leaf_symlink=True,
            )
        if scan_root.is_symlink():
            paths.add(relative_root)
            continue
        if not scan_root.exists():
            continue
        if scan_root.is_file():
            relative = scan_root.relative_to(worktree).as_posix()
            if _matches(relative, patterns):
                paths.add(relative)
            continue
        for directory, names, filenames in os.walk(scan_root, followlinks=False):
            directory_path = Path(directory)
            retained_names: list[str] = []
            for name in names:
                if name in {".git", ".pytest_cache", "__pycache__"}:
                    continue
                candidate = directory_path / name
                relative = candidate.relative_to(worktree).as_posix()
                if candidate.is_symlink():
                    paths.add(relative)
                else:
                    retained_names.append(name)
            names[:] = retained_names
            for filename in filenames:
                candidate = directory_path / filename
                relative = candidate.relative_to(worktree).as_posix()
                if (
                    not _is_ephemeral_runtime_path(relative)
                    and _matches(relative, patterns)
                ):
                    paths.add(relative)
    result: dict[str, dict[str, str]] = {}
    for raw_path in sorted(paths):
        path = _safe_relative_path(raw_path, "Git inventory path")
        _assert_no_symlink_traversal(
            worktree,
            path,
            label="Git inventory path",
            allow_leaf_symlink=True,
        )
        kind, digest = _file_digest(worktree / path)
        result[path] = {"kind": kind, "sha256": digest}
    return result


def _is_ephemeral_runtime_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return (
        path.endswith((".pyc", ".pyo"))
        or "__pycache__" in parts
        or ".pytest_cache" in parts
    )


def _inventory_delta(
    before: Mapping[str, Mapping[str, str]],
    after: Mapping[str, Mapping[str, str]],
) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for path in sorted(set(before) | set(after)):
        old = before.get(path)
        new = after.get(path)
        if old == new:
            continue
        if old is None and new is not None:
            change_type = "CREATED"
        elif new is None or new.get("kind") == "missing":
            change_type = "DELETED"
        else:
            change_type = "MODIFIED"
        changes.append({
            "path": path,
            "change_type": change_type,
            "kind": "missing" if new is None else new["kind"],
            "sha256": "" if new is None else new["sha256"],
        })
    return changes


def _reject_writable_symlinks(
    inventory: Mapping[str, Mapping[str, str]],
    patterns: Iterable[str],
) -> None:
    roots = {
        _pattern_scan_root(pattern).as_posix()
        for pattern in patterns
    }
    for path, identity in inventory.items():
        if identity.get("kind") != "symlink":
            continue
        if any(
            root == "."
            or path == root
            or path.startswith(root + "/")
            or root.startswith(path + "/")
            for root in roots
        ):
            raise AdapterError(
                f"task write boundary contains a symbolic link: {path}"
            )


def _publish_contract(adapter_dir: Path, contract: Mapping[str, Any]) -> tuple[str, Path]:
    payload = _canonical_bytes(contract)
    digest = _sha256_bytes(payload)
    path = adapter_dir / "contracts" / "sha256" / f"{digest}.json"
    if path.exists():
        if path.is_symlink() or path.read_bytes() != payload or path.stat().st_mode & 0o777 != 0o444:
            raise AdapterError("content-addressed task contract collided or became mutable")
    else:
        _atomic_write(path, payload, immutable=True)
    return digest, path


def _parse_stream(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line, parse_constant=_reject_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise AdapterError(f"Claude stream-json line {line_number} is invalid: {exc}") from exc
        if not isinstance(value, dict):
            raise AdapterError(f"Claude stream-json line {line_number} is not an object")
        events.append(value)
    if not events:
        raise AdapterError("Claude Code returned an empty stream-json response")
    return events


def _string_values(events: Sequence[Mapping[str, Any]], key: str) -> set[str]:
    values: set[str] = set()
    for event in events:
        value = event.get(key)
        if isinstance(value, str) and value:
            values.add(value)
    return values


def _reported_models(events: Sequence[Mapping[str, Any]]) -> set[str]:
    models = _string_values(events, "model")
    for event in events:
        message = event.get("message")
        if isinstance(message, dict) and isinstance(message.get("model"), str):
            models.add(message["model"])
        for key in ("modelUsage", "model_usage"):
            usage = event.get(key)
            if isinstance(usage, dict):
                models.update(item for item in usage if isinstance(item, str) and item)
    return models


def _usage_value(usage: Mapping[str, Any], *names: str) -> int | None:
    for name in names:
        value = usage.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def _transport_usage(events: Sequence[Mapping[str, Any]]) -> dict[str, int | None]:
    for event in reversed(events):
        usage = event.get("usage")
        if isinstance(usage, dict):
            return {
                "input_tokens": _usage_value(usage, "input_tokens", "inputTokens"),
                "output_tokens": _usage_value(usage, "output_tokens", "outputTokens"),
                "cache_creation_input_tokens": _usage_value(
                    usage, "cache_creation_input_tokens", "cacheCreationInputTokens"
                ),
                "cache_read_input_tokens": _usage_value(
                    usage, "cache_read_input_tokens", "cacheReadInputTokens"
                ),
            }
    return {
        "input_tokens": None,
        "output_tokens": None,
        "cache_creation_input_tokens": None,
        "cache_read_input_tokens": None,
    }


def _structured_result(events: Sequence[Mapping[str, Any]]) -> Any:
    for event in reversed(events):
        if "structured_output" in event:
            return event["structured_output"]
        result = event.get("result")
        if isinstance(result, dict):
            if "structured_output" in result:
                return result["structured_output"]
            return result
    raise AdapterError("Claude Code did not return structured_output")


def _verify_result(
    result: Any,
    *,
    contract: Mapping[str, Any],
    worktree: Path,
    delta: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    _validate_against_schema(result, RESULT_SCHEMA_PATH, "Worker result")
    if not isinstance(result, dict):
        raise AdapterError("Worker result must be an object")
    if result["task_id"] != contract["task_id"]:
        raise AdapterError("Worker result task_id differs from the task contract")
    if result["status"] == "COMPLETED" and not any(
        result[field] for field in ("artifacts", "commands_run", "observations")
    ):
        raise AdapterError("COMPLETED Worker result requires delivery or execution evidence")
    if result["status"] == "BLOCKED" and (result["artifacts"] or delta):
        raise AdapterError("BLOCKED Worker result must not leave worktree changes")
    allowed_paths = contract["allowed_paths"]
    operations = set(contract["allowed_operations"])
    actual: dict[str, Mapping[str, str]] = {}
    for item in delta:
        path = item["path"]
        if item["change_type"] == "DELETED":
            raise AdapterError(f"P2 forbids deletion: {path}")
        if item["kind"] != "file":
            raise AdapterError(f"P2 accepts only regular-file changes: {path}")
        if not _matches(path, allowed_paths):
            raise AdapterError(f"Worker changed a path outside the task contract: {path}")
        required_operation = "CREATE" if item["change_type"] == "CREATED" else "MODIFY"
        if required_operation not in operations:
            raise AdapterError(f"Worker performed unauthorized {required_operation}: {path}")
        actual[path] = item
    declared: dict[str, Mapping[str, Any]] = {}
    for item in result["artifacts"]:
        path = _safe_relative_path(item["path"], "Worker result artifact")
        if path in declared:
            raise AdapterError("Worker result contains duplicate artifact paths")
        declared[path] = item
    if set(declared) != set(actual):
        raise AdapterError(
            "Worker result artifact list must exactly equal this turn's Git-visible changes"
        )
    for path, item in declared.items():
        observed = actual[path]
        if item["change_type"] != observed["change_type"] or item["sha256"] != observed["sha256"]:
            raise AdapterError(f"Worker artifact identity differs from controller bytes: {path}")
    input_paths = {item["path"] for item in contract["input_artifacts"]}
    for observation in result["observations"]:
        for evidence in observation["evidence"]:
            path = _safe_relative_path(evidence["path"], "Worker observation evidence")
            if path not in input_paths and not _matches(path, allowed_paths):
                raise AdapterError(f"Worker observation cites out-of-contract evidence: {path}")
            target = worktree / path
            _assert_no_symlink_traversal(
                worktree,
                path,
                label="Worker observation evidence",
            )
            if not target.is_file() or target.is_symlink():
                raise AdapterError(f"Worker observation evidence is not a regular file: {path}")
            if _sha256_file(target) != evidence["sha256"]:
                raise AdapterError(f"Worker observation evidence hash is wrong: {path}")
    authorized_commands = {
        tuple(contract["command_argv"]),
        *(tuple(item["argv"]) for item in contract["acceptance_checks"]),
    }
    for command in result["commands_run"]:
        if tuple(command["argv"]) not in authorized_commands:
            raise AdapterError("Worker reported a command outside the task contract")
    return result


def _prompt(
    *,
    manifest: Mapping[str, Any],
    contract: Mapping[str, Any],
    contract_digest: str,
) -> str:
    envelope = {
        "authority": {
            "host": "Codex",
            "worker": "Claude Code with the frozen MiniMax model",
            "worker_role": "bounded artifact producer only",
            "forbidden": [
                "change the Research IR, evaluator contract, research goal, or paper direction",
                "claim scientific acceptance or SOTA",
                "edit, delete, or create files outside allowed_paths",
                "delete files, commit, switch branches, create worktrees, or alter Git metadata",
            ],
        },
        "worktree_root": manifest["worktree_root"],
        "research_ir_sha256": manifest["research_ir_sha256"],
        "task_contract_sha256": contract_digest,
        "task_contract": contract,
        "execution_rules": [
            "Work only in the supplied current working directory.",
            "Treat allowed_paths as the complete write boundary.",
            "Use only command_argv and acceptance_checks for material experiment execution.",
            (
                "Invoke every authorized Bash command as exactly the shell-joined argv "
                "provided by command_argv or acceptance_checks. Do not append 2>&1, "
                "echo, semicolons, pipes, redirects, cd, environment assignments, or "
                "any other wrapper because the non-interactive permission rule is an "
                "exact command capability."
            ),
            (
                "The Host already verified every input_artifact path and SHA-256 before "
                "dispatch. Inspect them with Read, Glob, or Grep; do not run extra Bash "
                "diagnostic commands such as sha256sum or ls."
            ),
            "Return BLOCKED without file changes when the task cannot be completed honestly.",
            "Return every file changed in this turn and its exact lowercase SHA-256.",
            "Your JSON is a proposal; the Host validates bytes and retains all acceptance authority.",
        ],
        "required_result_schema": _load_json(RESULT_SCHEMA_PATH),
    }
    return json.dumps(envelope, ensure_ascii=False, indent=2) + "\n"


def _classify_failure(
    returncode: int,
    stderr: str,
    events: Sequence[Mapping[str, Any]] = (),
) -> str:
    result_subtypes = {
        str(event.get("subtype", "")).lower()
        for event in events
        if event.get("type") == "result"
    }
    if any("max_budget" in subtype for subtype in result_subtypes):
        return "adapter_turn_budget_exhausted"
    if any(
        marker in subtype
        for subtype in result_subtypes
        for marker in ("rate_limit", "usage_limit", "quota")
    ):
        return "provider_quota"
    normalized = stderr.lower()
    if any(marker in normalized for marker in (
        "rate limit", "usage limit", "quota", "5-hour", "5 hour", "token plan", "retry after"
    )):
        return "provider_quota"
    if "session" in normalized and any(marker in normalized for marker in (
        "not found", "unknown", "missing", "does not exist", "invalid"
    )):
        return "session_missing"
    if any(marker in normalized for marker in (
        "authentication", "unauthorized", "invalid api key", "login required"
    )):
        return "authentication_failure"
    return f"claude_exit_{returncode}"


def _update_session(adapter_dir: Path, session: dict[str, Any], **updates: Any) -> dict[str, Any]:
    current = _load_json(adapter_dir / "session.json")
    if not isinstance(current, dict) or current.get("session_id") != session.get("session_id"):
        raise AdapterError("session changed while delivery lease was held")
    current.update(updates)
    current["updated_at"] = _now()
    _write_json(adapter_dir / "session.json", current)
    return current


def _receipt_path(adapter_dir: Path, turn_index: int, task_id: str) -> Path:
    return adapter_dir / "turns" / f"{turn_index:06d}-{task_id}.json"


def _write_rejected_change_manifest(
    *,
    run_dir: Path,
    worktree: Path,
    manifest: Mapping[str, Any],
    before: Mapping[str, Mapping[str, str]],
    contract: Mapping[str, Any],
    contract_digest: str,
    turn_index: int,
    rejection: str,
) -> Path:
    path = run_dir / "rejected-change-manifest.json"
    try:
        after = _inventory(worktree, contract["allowed_paths"])
        evidence: dict[str, Any] = {
            "changes": _inventory_delta(before, after),
            "evidence_capture_error": None,
            "evidence_complete": True,
            "head_after": _git_text(worktree, "rev-parse", "HEAD"),
        }
    except Exception as exc:  # post-launch Git/filesystem evidence may be damaged
        evidence = {
            "changes": None,
            "evidence_capture_error": f"{type(exc).__name__}:{str(exc)[:240]}",
            "evidence_complete": False,
            "head_after": None,
        }
    _write_json(path, {
        "base_commit": manifest["base_commit"],
        **evidence,
        "rejection": rejection,
        "task_contract_sha256": contract_digest,
        "task_id": contract["task_id"],
        "turn_index": turn_index,
        "worktree_root": str(worktree),
    }, immutable=True)
    return path


def _archive_turn_inputs(
    *,
    run_dir: Path,
    worktree: Path,
    contract: Mapping[str, Any],
) -> Path:
    """Snapshot verified pre-execution inputs for later experiment provenance."""

    entries: list[dict[str, str]] = []
    for item in contract["input_artifacts"]:
        source = worktree / item["path"]
        digest = item["sha256"]
        blob = run_dir / "input-blobs" / "sha256" / digest
        if _sha256_file(source) != digest:
            raise AdapterError(f"task input changed before archival: {item['path']}")
        if blob.exists() or blob.is_symlink():
            if (
                blob.is_symlink()
                or not blob.is_file()
                or blob.stat().st_mode & 0o777 != 0o444
                or _sha256_file(blob) != digest
            ):
                raise AdapterError(f"task input archive collision: {item['path']}")
        else:
            _atomic_write(blob, source.read_bytes(), immutable=True)
        entries.append({
            "blob_path": str(blob),
            "path": item["path"],
            "purpose": item["purpose"],
            "sha256": digest,
        })
    archive_path = run_dir / "input-archive.json"
    _write_json(archive_path, {"artifacts": entries}, immutable=True)
    return archive_path


def _run_transport(
    command: Sequence[str],
    *,
    prompt: str,
    worktree: Path,
    timeout_seconds: int,
    heartbeat_callback: Callable[[int, str, int], None] | None = None,
    heartbeat_interval_seconds: float | None = None,
) -> tuple[int, bytes, bytes, bool]:
    """Run Claude in a new process group and quiesce the group on timeout."""

    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=worktree,
        start_new_session=True,
    )
    heartbeat_stop = threading.Event()
    heartbeat_errors: list[BaseException] = []
    heartbeat_thread: threading.Thread | None = None
    if heartbeat_callback is not None:
        if heartbeat_interval_seconds is None or heartbeat_interval_seconds <= 0:
            proc.terminate()
            proc.communicate()
            raise OSError("runtime heartbeat interval is invalid")
        try:
            process_identity = _process_identity(proc.pid)
            heartbeat_callback(proc.pid, process_identity, 1)
        except BaseException as exc:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
            proc.communicate()
            raise OSError(f"initial runtime heartbeat failed: {exc}") from exc

        def pulse() -> None:
            sequence = 2
            while not heartbeat_stop.wait(heartbeat_interval_seconds):
                try:
                    heartbeat_callback(proc.pid, process_identity, sequence)
                except BaseException as exc:  # forwarded to the owning Host thread
                    heartbeat_errors.append(exc)
                    heartbeat_stop.set()
                    return
                sequence += 1

        heartbeat_thread = threading.Thread(
            target=pulse,
            name=f"mvp0-l2-heartbeat-{proc.pid}",
            daemon=True,
        )
        heartbeat_thread.start()
    try:
        stdout, stderr = proc.communicate(
            input=prompt.encode("utf-8"),
            timeout=timeout_seconds,
        )
        result = (proc.returncode, stdout, stderr, False)
    except subprocess.TimeoutExpired:
        # Capture descendants before terminating the direct process; after it
        # exits, orphaned children may be reparented and no longer discoverable.
        descendants: list[int] = []
        try:
            listing = subprocess.run(
                ["ps", "-axo", "pid=,ppid="],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            children: dict[int, list[int]] = {}
            for line in listing.splitlines():
                fields = line.split()
                if len(fields) == 2 and all(field.isdigit() for field in fields):
                    child, parent = map(int, fields)
                    children.setdefault(parent, []).append(child)
            pending = list(children.get(proc.pid, []))
            while pending:
                child = pending.pop()
                if child not in descendants:
                    descendants.append(child)
                    pending.extend(children.get(child, []))
        except (OSError, subprocess.SubprocessError):
            descendants = []
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            proc.terminate()
            for child in descendants:
                try:
                    os.kill(child, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
        try:
            stdout, stderr = proc.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            stdout = b""
            stderr = b""
        # The direct Claude process can exit and close its pipes while an
        # inherited same-group child ignores SIGTERM.  Check the group itself,
        # not communicate() completion, before publishing any terminal bytes.
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            group_exists = False
        except PermissionError:
            group_exists = True
        else:
            group_exists = True
        if group_exists:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                proc.kill()
                for child in descendants:
                    try:
                        os.kill(child, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
        final_stdout, final_stderr = proc.communicate()
        if final_stdout:
            stdout = final_stdout
        if final_stderr:
            stderr = final_stderr
        # Give the kernel a bounded moment to reap killed descendants.  They
        # cannot write after SIGKILL; this loop only tightens the receipt time.
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            try:
                os.killpg(proc.pid, 0)
            except ProcessLookupError:
                break
            except PermissionError:
                living = []
                for child in descendants:
                    try:
                        os.kill(child, 0)
                    except ProcessLookupError:
                        continue
                    except PermissionError:
                        living.append(child)
                    else:
                        living.append(child)
                if not living:
                    break
            time.sleep(0.02)
        result = (proc.returncode, stdout, stderr, True)
    finally:
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1)
    if heartbeat_errors:
        raise OSError(f"runtime heartbeat failed: {heartbeat_errors[0]}")
    return result


def _process_identity(pid: int) -> str:
    """Return a reuse-resistant identity for the exact launched process."""

    try:
        proc = subprocess.run(
            ["ps", "-o", "lstart=,command=", "-p", str(pid)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise AdapterError(f"cannot inspect Worker process identity: {exc}") from exc
    rendered = proc.stdout.strip()
    if proc.returncode != 0 or not rendered:
        raise AdapterError("cannot prove Worker process start identity")
    return _sha256_bytes(_canonical_bytes({"pid": pid, "ps_identity": rendered}))


def _finalize_turn(
    *,
    adapter_dir: Path,
    manifest: Mapping[str, Any],
    session: dict[str, Any],
    run_dir: Path,
    contract: Mapping[str, Any],
    contract_digest: str,
    command: Sequence[str],
    prompt_sha256: str,
    started_at: str,
    invocation_mode: str,
    events: Sequence[Mapping[str, Any]],
    outcome: str,
    failure: str | None,
    result_path: Path | None,
    change_manifest_path: Path | None,
    runtime_store: Path | None = None,
    worker_binding_path: Path | None = None,
) -> dict[str, Any]:
    turn_index = session["turn_count"] + 1
    usage = _transport_usage(events)
    session_ids = sorted(_string_values(events, "session_id"))
    reported_models = sorted(_reported_models(events))
    expected_normalized = _normalize_model(manifest["worker_model"])
    model_verified = bool(reported_models) and all(
        _normalize_model(value) == expected_normalized for value in reported_models
    )
    receipt = {
        "adapter_id": manifest["adapter_id"],
        "change_manifest_path": None if change_manifest_path is None else str(change_manifest_path),
        "change_manifest_sha256": None if change_manifest_path is None else _sha256_file(change_manifest_path),
        "claude_executable": manifest["claude_executable"],
        "claude_executable_sha256": manifest["claude_executable_sha256"],
        "command_sha256": _sha256_bytes(_canonical_bytes(list(command))),
        "completed_at": _now(),
        "failure": failure,
        "freeze_receipt_sha256": manifest["freeze_receipt_sha256"],
        "invocation_mode": invocation_mode,
        "input_archive_path": str(run_dir / "input-archive.json"),
        "input_archive_sha256": _sha256_file(run_dir / "input-archive.json"),
        "outcome": outcome,
        "prompt_sha256": prompt_sha256,
        "raw_stderr_sha256": _sha256_file(run_dir / "transport.stderr"),
        "raw_stream_sha256": _sha256_file(run_dir / "transport.jsonl"),
        "reported_models": reported_models,
        "reported_session_ids": session_ids,
        "research_ir_sha256": manifest["research_ir_sha256"],
        "result_path": None if result_path is None else str(result_path),
        "result_sha256": None if result_path is None else _sha256_file(result_path),
        "run_dir": str(run_dir),
        "schema_version": RECEIPT_VERSION,
        "session_id": manifest["session_id"],
        "started_at": started_at,
        "task_contract_sha256": contract_digest,
        "task_id": contract["task_id"],
        "turn_index": turn_index,
        "usage": usage,
        "usage_complete": all(value is not None for value in usage.values()),
        "worker_model_argument": manifest["worker_model"],
        "worker_model_verified": model_verified,
        "worktree_root": manifest["worktree_root"],
    }
    receipt_path = _receipt_path(adapter_dir, turn_index, contract["task_id"])
    _write_json(receipt_path, receipt, immutable=True)
    next_state = "READY" if outcome in {"COMPLETED", "BLOCKED"} else "PAUSED"
    paused_reason = None if next_state == "READY" else failure
    _update_session(
        adapter_dir,
        session,
        state=next_state,
        turn_count=turn_index,
        last_receipt_path=str(receipt_path),
        last_receipt_sha256=_sha256_file(receipt_path),
        paused_reason=paused_reason,
    )
    receipt_digest = _sha256_file(receipt_path)
    if runtime_store is not None and worker_binding_path is not None:
        try:
            runtime_assurance.complete_worker(
                store_dir=runtime_store,
                worker_binding_path=worker_binding_path,
                outcome=outcome,
                turn_receipt_path=receipt_path,
                turn_receipt_sha256=receipt_digest,
                completed_at=receipt["completed_at"],
            )
        except runtime_assurance.AssuranceError as exc:
            raise AdapterError(f"runtime Worker completion failed: {exc}") from exc
    return {
        "outcome": outcome,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_digest,
        "result_path": None if result_path is None else str(result_path),
        "session_id": manifest["session_id"],
        "session_state": next_state,
        "task_id": contract["task_id"],
        "turn_index": turn_index,
        "worker_model_verified": model_verified,
    }


def dispatch_task(
    *,
    adapter_dir: Path,
    task_contract: Path,
    unattended: bool = False,
    runtime_store: Path | None = None,
    scheduler: Any | None = None,
) -> dict[str, Any]:
    """Deliver one validated task to the exact persistent Claude session."""

    adapter_dir = adapter_dir.resolve()
    if not adapter_dir.is_dir():
        raise AdapterError("adapter_dir does not exist")
    runtime_store_resolved: Path | None = None
    if unattended:
        if runtime_store is None:
            raise AdapterError("unattended dispatch requires a runtime assurance store")
        runtime_store_resolved = runtime_store.resolve()
        resolved_scheduler = LaunchctlScheduler() if scheduler is None else scheduler
        try:
            runtime_assurance.verify_activation(
                store_dir=runtime_store_resolved,
                scheduler=resolved_scheduler,
                now=_now(),
            )
        except runtime_assurance.AssuranceError as exc:
            raise AdapterError(f"runtime assurance activation is invalid: {exc}") from exc
    lock_path = adapter_dir / ".delivery.lock"
    lock_handle = lock_path.open("a+")
    try:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AdapterError("fixed Claude session already has an active delivery") from exc
        manifest = _adapter_manifest(adapter_dir)
        session = _session_state(adapter_dir, manifest)
        if session["state"] != "READY":
            raise AdapterError(
                f"Worker session is {session['state']}; P2 does not auto-retry or recover it"
            )
        worktree = Path(manifest["worktree_root"])
        if not worktree.is_dir():
            raise AdapterError("bound research worktree is missing")
        if _git_text(worktree, "rev-parse", "HEAD") != manifest["base_commit"]:
            raise AdapterError("bound worktree HEAD drifted; Worker commits are forbidden")
        ir = _load_ir_from_manifest(manifest)
        contract = validate_task_contract(
            _load_json(task_contract.resolve()),
            manifest,
            ir,
        )
        contract_digest, contract_path = _publish_contract(adapter_dir, contract)
        if (
            manifest["schema_version"] == SUCCESSOR_ADAPTER_VERSION
            and contract_digest == manifest["predecessor_task_contract_sha256"]
        ):
            raise AdapterError("successor task contract must differ from the failed predecessor")
        for receipt_path in (
            (adapter_dir / "turns").glob("*.json")
            if (adapter_dir / "turns").exists()
            else ()
        ):
            prior = _load_json(receipt_path)
            if isinstance(prior, dict) and prior.get("task_id") == contract["task_id"]:
                raise AdapterError("task_id was already dispatched; task replay is forbidden")
        for item in contract["input_artifacts"]:
            _assert_no_symlink_traversal(
                worktree,
                item["path"],
                label="Worker task input",
            )
            target = worktree / item["path"]
            if not target.is_file():
                raise AdapterError(f"task input is missing or not a regular file: {item['path']}")
            if _sha256_file(target) != item["sha256"]:
                raise AdapterError(f"task input hash changed: {item['path']}")
        turn_index = session["turn_count"] + 1
        run_dir = adapter_dir / "runs" / f"{turn_index:06d}-{contract['task_id']}"
        before = _inventory(worktree, contract["allowed_paths"])
        _reject_writable_symlinks(before, contract["allowed_paths"])
        run_dir.mkdir(parents=True, exist_ok=False)
        _archive_turn_inputs(run_dir=run_dir, worktree=worktree, contract=contract)
        _write_json(run_dir / "before-inventory.json", before, immutable=True)
        prompt = _prompt(manifest=manifest, contract=contract, contract_digest=contract_digest)
        prompt_sha256 = _sha256_bytes(prompt.encode("utf-8"))
        invocation_mode = (
            "created"
            if turn_index == 1 and manifest["schema_version"] == ADAPTER_VERSION
            else "resumed"
        )
        command = [
            manifest["claude_executable"],
            "-p",
            "--model",
            manifest["worker_model"],
            "--output-format",
            "stream-json",
            "--verbose",
            "--json-schema",
            json.dumps(_result_transport_schema(), separators=(",", ":")),
            "--max-budget-usd",
            str(manifest["max_budget_usd_per_turn"]),
            "--permission-mode",
            manifest["permission_mode"],
            "--tools",
            ",".join(manifest["tools"]),
            "--allowedTools",
            *[tool for tool in manifest["tools"] if tool != "Bash"],
            *[
                f"Bash({shlex.join(argv)})"
                for argv in (
                    contract["command_argv"],
                    *(item["argv"] for item in contract["acceptance_checks"]),
                )
            ],
            "--name",
            manifest["adapter_id"],
        ]
        if turn_index == 1 and manifest["schema_version"] == ADAPTER_VERSION:
            command.extend(["--session-id", manifest["session_id"]])
        else:
            command.extend(["--resume", manifest["session_id"]])
        instruction = {
            "command_sha256": _sha256_bytes(_canonical_bytes(command)),
            "created_at": _now(),
            "invocation_mode": invocation_mode,
            "prompt_sha256": prompt_sha256,
            "research_ir_sha256": manifest["research_ir_sha256"],
            "session_id": manifest["session_id"],
            "task_contract_path": str(contract_path),
            "task_contract_sha256": contract_digest,
            "task_id": contract["task_id"],
            "turn_index": turn_index,
            "worktree_root": str(worktree),
        }
        _write_json(run_dir / "instruction.json", instruction, immutable=True)
        started_at = _now()
        session = _update_session(
            adapter_dir,
            session,
            state="BUSY",
            paused_reason=None,
        )
        heartbeat_callback: Callable[[int, str, int], None] | None = None
        heartbeat_interval: float | None = None
        binding_path: Path | None = None
        if unattended:
            assert runtime_store_resolved is not None
            heartbeat_interval = float(
                runtime_assurance.heartbeat_interval_seconds(
                    store_dir=runtime_store_resolved,
                )
            )
            def publish_heartbeat(pid: int, process_identity: str, sequence: int) -> None:
                nonlocal binding_path
                observed_at = _now()
                if sequence == 1:
                    bound = runtime_assurance.bind_worker(
                        store_dir=runtime_store_resolved,
                        adapter_id=manifest["adapter_id"],
                        turn_id=f"{manifest['adapter_id']}:{turn_index:06d}:{contract['task_id']}",
                        session_id=manifest["session_id"],
                        worker_model=manifest["worker_model"],
                        task_contract_sha256=contract_digest,
                        process_id=pid,
                        process_identity=process_identity,
                        now=observed_at,
                    )
                    binding_path = Path(bound["worker_binding_path"])
                if binding_path is None:
                    raise AdapterError("runtime Worker binding was not established")
                runtime_assurance.record_worker_heartbeat(
                    store_dir=runtime_store_resolved,
                    worker_binding_path=binding_path,
                    sequence=sequence,
                    session_id=manifest["session_id"],
                    process_id=pid,
                    process_identity=process_identity,
                    task_contract_sha256=contract_digest,
                    observed_at=observed_at,
                )

            heartbeat_callback = publish_heartbeat
        try:
            returncode, stdout_bytes, stderr_bytes, timed_out = _run_transport(
                command,
                prompt=prompt,
                worktree=worktree,
                timeout_seconds=contract["max_runtime_seconds"],
                heartbeat_callback=heartbeat_callback,
                heartbeat_interval_seconds=heartbeat_interval,
            )
        except OSError as exc:
            stdout_bytes = b""
            stderr_bytes = str(exc).encode("utf-8", errors="replace")
            _atomic_write(run_dir / "transport.jsonl", stdout_bytes, immutable=True)
            _atomic_write(run_dir / "transport.stderr", stderr_bytes, immutable=True)
            rejected_path = _write_rejected_change_manifest(
                run_dir=run_dir,
                worktree=worktree,
                manifest=manifest,
                before=before,
                contract=contract,
                contract_digest=contract_digest,
                turn_index=turn_index,
                rejection="transport_launch_failure",
            )
            return _finalize_turn(
                adapter_dir=adapter_dir,
                manifest=manifest,
                session=session,
                run_dir=run_dir,
                contract=contract,
                contract_digest=contract_digest,
                command=command,
                prompt_sha256=prompt_sha256,
                started_at=started_at,
                invocation_mode=invocation_mode,
                events=[],
                outcome="FAILED",
                failure=f"transport_launch_failure:{str(exc)[:200]}",
                result_path=None,
                change_manifest_path=rejected_path,
                runtime_store=runtime_store_resolved,
                worker_binding_path=binding_path,
            )
        if timed_out:
            _atomic_write(run_dir / "transport.jsonl", stdout_bytes, immutable=True)
            _atomic_write(run_dir / "transport.stderr", stderr_bytes, immutable=True)
            rejected_path = _write_rejected_change_manifest(
                run_dir=run_dir,
                worktree=worktree,
                manifest=manifest,
                before=before,
                contract=contract,
                contract_digest=contract_digest,
                turn_index=turn_index,
                rejection="worker_timeout",
            )
            return _finalize_turn(
                adapter_dir=adapter_dir,
                manifest=manifest,
                session=session,
                run_dir=run_dir,
                contract=contract,
                contract_digest=contract_digest,
                command=command,
                prompt_sha256=prompt_sha256,
                started_at=started_at,
                invocation_mode=invocation_mode,
                events=[],
                outcome="FAILED",
                failure="worker_timeout",
                result_path=None,
                change_manifest_path=rejected_path,
                runtime_store=runtime_store_resolved,
                worker_binding_path=binding_path,
            )
        _atomic_write(run_dir / "transport.jsonl", stdout_bytes, immutable=True)
        _atomic_write(run_dir / "transport.stderr", stderr_bytes, immutable=True)
        try:
            stdout = stdout_bytes.decode("utf-8", errors="strict")
            stderr = stderr_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            rejected_path = _write_rejected_change_manifest(
                run_dir=run_dir,
                worktree=worktree,
                manifest=manifest,
                before=before,
                contract=contract,
                contract_digest=contract_digest,
                turn_index=turn_index,
                rejection="invalid_transport_encoding",
            )
            return _finalize_turn(
                adapter_dir=adapter_dir,
                manifest=manifest,
                session=session,
                run_dir=run_dir,
                contract=contract,
                contract_digest=contract_digest,
                command=command,
                prompt_sha256=prompt_sha256,
                started_at=started_at,
                invocation_mode=invocation_mode,
                events=[],
                outcome="FAILED",
                failure=f"invalid_transport_encoding:{str(exc)[:160]}",
                result_path=None,
                change_manifest_path=rejected_path,
                runtime_store=runtime_store_resolved,
                worker_binding_path=binding_path,
            )
        try:
            events = _parse_stream(stdout)
        except AdapterError:
            events = []
        if returncode != 0:
            failure = _classify_failure(returncode, stderr, events)
            rejected_path = _write_rejected_change_manifest(
                run_dir=run_dir,
                worktree=worktree,
                manifest=manifest,
                before=before,
                contract=contract,
                contract_digest=contract_digest,
                turn_index=turn_index,
                rejection=failure,
            )
            return _finalize_turn(
                adapter_dir=adapter_dir,
                manifest=manifest,
                session=session,
                run_dir=run_dir,
                contract=contract,
                contract_digest=contract_digest,
                command=command,
                prompt_sha256=prompt_sha256,
                started_at=started_at,
                invocation_mode=invocation_mode,
                events=events,
                outcome="FAILED",
                failure=failure,
                result_path=None,
                change_manifest_path=rejected_path,
                runtime_store=runtime_store_resolved,
                worker_binding_path=binding_path,
            )
        try:
            events = _parse_stream(stdout)
            session_ids = _string_values(events, "session_id")
            if session_ids != {manifest["session_id"]}:
                raise AdapterError("Claude response did not prove the exact bound session_id")
            reported_models = _reported_models(events)
            if not reported_models or any(
                _normalize_model(model) != _normalize_model(manifest["worker_model"])
                for model in reported_models
            ):
                raise AdapterError("Claude response did not prove the frozen MiniMax model")
            result = _structured_result(events)
            after = _inventory(worktree, contract["allowed_paths"])
            _write_json(run_dir / "after-inventory.json", after, immutable=True)
            delta = _inventory_delta(before, after)
            if _git_text(worktree, "rev-parse", "HEAD") != manifest["base_commit"]:
                raise AdapterError("Worker changed worktree HEAD; commits are forbidden")
            result = _verify_result(
                result,
                contract=contract,
                worktree=worktree,
                delta=delta,
            )
            change_manifest = {
                "base_commit": manifest["base_commit"],
                "changes": delta,
                "isolation_assurance": manifest["isolation_assurance"],
                "task_contract_sha256": contract_digest,
                "task_id": contract["task_id"],
                "turn_index": turn_index,
                "worktree_root": str(worktree),
            }
            change_manifest_path = run_dir / "change-manifest.json"
            _write_json(change_manifest_path, change_manifest, immutable=True)
            result_path = run_dir / "result.json"
            _write_json(result_path, result, immutable=True)
            return _finalize_turn(
                adapter_dir=adapter_dir,
                manifest=manifest,
                session=session,
                run_dir=run_dir,
                contract=contract,
                contract_digest=contract_digest,
                command=command,
                prompt_sha256=prompt_sha256,
                started_at=started_at,
                invocation_mode=invocation_mode,
                events=events,
                outcome=result["status"],
                failure=None,
                result_path=result_path,
                change_manifest_path=change_manifest_path,
                runtime_store=runtime_store_resolved,
                worker_binding_path=binding_path,
            )
        except Exception as exc:
            change_manifest_path = _write_rejected_change_manifest(
                run_dir=run_dir,
                worktree=worktree,
                manifest=manifest,
                before=before,
                contract=contract,
                contract_digest=contract_digest,
                turn_index=turn_index,
                rejection=str(exc),
            )
            return _finalize_turn(
                adapter_dir=adapter_dir,
                manifest=manifest,
                session=session,
                run_dir=run_dir,
                contract=contract,
                contract_digest=contract_digest,
                command=command,
                prompt_sha256=prompt_sha256,
                started_at=started_at,
                invocation_mode=invocation_mode,
                events=events,
                outcome="FAILED",
                failure=f"invalid_worker_delivery:{str(exc)[:240]}",
                result_path=None,
                change_manifest_path=change_manifest_path,
                runtime_store=runtime_store_resolved,
                worker_binding_path=binding_path,
            )
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


def inspect_adapter(*, adapter_dir: Path) -> dict[str, Any]:
    adapter_dir = adapter_dir.resolve()
    manifest = _adapter_manifest(adapter_dir)
    session = _session_state(adapter_dir, manifest)
    return {
        "adapter_id": manifest["adapter_id"],
        "base_commit": manifest["base_commit"],
        "isolation_assurance": manifest["isolation_assurance"],
        "last_receipt_path": session["last_receipt_path"],
        "research_ir_sha256": manifest["research_ir_sha256"],
        "session_id": manifest["session_id"],
        "session_state": session["state"],
        "turn_count": session["turn_count"],
        "worker_model": manifest["worker_model"],
        "worktree_root": manifest["worktree_root"],
    }


def _emit(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MVP-0 P2 fixed-session Worker Adapter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="bind one frozen IR, worktree, and Claude session")
    init_parser.add_argument("--freeze-receipt", type=Path, required=True)
    init_parser.add_argument("--compiler-store", type=Path, required=True)
    init_parser.add_argument("--source-repo", type=Path, required=True)
    init_parser.add_argument("--adapter-dir", type=Path, required=True)
    init_parser.add_argument("--worktree", type=Path, required=True)
    init_parser.add_argument("--claude-bin", default="claude")
    init_parser.add_argument("--worker-model", default="MiniMax-M3")
    init_parser.add_argument("--max-budget-usd-per-turn", type=float, default=2.0)
    init_parser.add_argument("--engineering-test", action="store_true")
    init_parser.add_argument("--predecessor-turn-receipt", type=Path)
    init_parser.add_argument("--p5-store", type=Path)
    init_parser.add_argument("--p5-freeze-binding", type=Path)

    validate_parser = subparsers.add_parser("validate-task", help="validate one task against the frozen IR")
    validate_parser.add_argument("--adapter-dir", type=Path, required=True)
    validate_parser.add_argument("--task-contract", type=Path, required=True)

    dispatch_parser = subparsers.add_parser("dispatch", help="send one task through the exact Claude session")
    dispatch_parser.add_argument("--adapter-dir", type=Path, required=True)
    dispatch_parser.add_argument("--task-contract", type=Path, required=True)
    dispatch_parser.add_argument("--unattended", action="store_true")
    dispatch_parser.add_argument("--runtime-store", type=Path)

    inspect_parser = subparsers.add_parser("inspect", help="read the minimal adapter/session state")
    inspect_parser.add_argument("--adapter-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            result = initialize_adapter(
                freeze_receipt=args.freeze_receipt,
                compiler_store=args.compiler_store,
                source_repo=args.source_repo,
                adapter_dir=args.adapter_dir,
                worktree=args.worktree,
                claude_bin=args.claude_bin,
                worker_model=args.worker_model,
                max_budget_usd_per_turn=args.max_budget_usd_per_turn,
                engineering_test=args.engineering_test,
                predecessor_turn_receipt=args.predecessor_turn_receipt,
                p5_store=args.p5_store,
                p5_freeze_binding=args.p5_freeze_binding,
            )
        elif args.command == "validate-task":
            manifest = _adapter_manifest(args.adapter_dir.resolve())
            ir = _load_ir_from_manifest(manifest)
            contract = validate_task_contract(_load_json(args.task_contract.resolve()), manifest, ir)
            result = {
                "research_ir_sha256": manifest["research_ir_sha256"],
                "task_contract_sha256": _sha256_bytes(_canonical_bytes(contract)),
                "task_id": contract["task_id"],
                "valid": True,
            }
        elif args.command == "dispatch":
            result = dispatch_task(
                adapter_dir=args.adapter_dir,
                task_contract=args.task_contract,
                unattended=args.unattended,
                runtime_store=args.runtime_store,
            )
        else:
            result = inspect_adapter(adapter_dir=args.adapter_dir)
        _emit(result)
        return 0 if result.get("outcome") != "FAILED" else 2
    except AdapterError as exc:
        print(json.dumps({"error": str(exc), "valid": False}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
