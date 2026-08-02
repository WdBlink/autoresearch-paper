#!/usr/bin/env python3
"""Independent non-MiniMax review for execution-only P6 Research IR changes."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


REVIEW_VERSION = "delegated-engineering-review/v1"
METADATA_POINTERS = {"/version", "/parent_ir_sha256"}
ALLOWED_ROOTS = {"/budget", "/experiment_plan"}
ALLOWED_EVALUATOR_POINTERS = {
    "/evaluator_spec/status",
    "/evaluator_spec/implementation_artifact",
    "/evaluator_spec/implementation_sha256",
}
FROZEN_EXPERIMENT_FIELDS = {
    "stage",
    "hypothesis",
    "falsification_condition_ids",
    "search_space_ids",
    "command_argv",
}
RECEIPT_KEYS = {
    "approver",
    "changed_pointers",
    "changed_roots",
    "child_ir_path",
    "child_ir_sha256",
    "compiler_author",
    "parent_ir_path",
    "parent_ir_sha256",
    "policy_result",
    "proposal_path",
    "proposal_sha256",
    "request_path",
    "request_sha256",
    "retained_root_sha256s",
    "reviewed_at",
    "reviewer",
    "revision_author",
    "schema_version",
    "summary",
    "verdict",
}


class DelegatedReviewError(RuntimeError):
    """A fail-closed delegated-review policy or replay error."""


def canonical_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise DelegatedReviewError(f"value is not canonical JSON: {exc}") from exc
    return (text + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_addressed(path: Path, label: str) -> tuple[Any, str]:
    resolved = path.resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise DelegatedReviewError(f"{label} must be an existing regular file")
    data = resolved.read_bytes()
    try:
        value = json.loads(data, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise DelegatedReviewError(f"{label} is not strict JSON: {exc}") from exc
    canonical = canonical_bytes(value)
    if data != canonical:
        raise DelegatedReviewError(f"{label} is not canonical JSON")
    return value, _sha(data)


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _atomic_immutable(path: Path, data: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_mode & 0o777 != 0o444
            or path.read_bytes() != data
        ):
            raise DelegatedReviewError(f"delegated review collision: {path}")
        return True
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
        path.chmod(0o444)
    finally:
        if temporary.exists():
            temporary.unlink()
    return False


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _diff_pointers(parent: Any, child: Any, pointer: str = "") -> set[str]:
    if type(parent) is not type(child):
        return {pointer or "/"}
    if isinstance(parent, dict):
        changed: set[str] = set()
        for key in sorted(set(parent) | set(child)):
            item_pointer = f"{pointer}/{_escape_pointer(key)}"
            if key not in parent or key not in child:
                changed.add(item_pointer)
            else:
                changed.update(_diff_pointers(parent[key], child[key], item_pointer))
        return changed
    if isinstance(parent, list):
        if parent == child:
            return set()
        # Arrays are governed as one semantic field; index-level allowlists are
        # too easy to bypass through reordering.
        return {pointer or "/"}
    return set() if parent == child else {pointer or "/"}


def _root(pointer: str) -> str:
    if pointer == "/":
        return pointer
    return "/" + pointer.lstrip("/").split("/", 1)[0]


def _validate_identity(value: str, label: str) -> str:
    if not isinstance(value, str) or len(value.strip()) < 3:
        raise DelegatedReviewError(f"{label} identity must be non-empty")
    identity = value.strip()
    lowered = identity.lower().replace("-", "").replace("_", "")
    if "minimax" in lowered or "m3" in lowered:
        raise DelegatedReviewError(f"{label} must be a non-MiniMax identity")
    if not identity.startswith("codex/"):
        raise DelegatedReviewError(f"{label} must use the codex/<role> namespace")
    return identity


def _validate_time(value: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DelegatedReviewError("reviewed_at must be an RFC3339 UTC timestamp")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise DelegatedReviewError("reviewed_at is invalid") from exc
    return value


def validate_engineering_delta(parent: Mapping[str, Any], child: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    if not isinstance(parent, Mapping) or not isinstance(child, Mapping):
        raise DelegatedReviewError("parent and child Research IR must be objects")
    parent_digest = _sha(canonical_bytes(parent))
    if child.get("ir_id") != parent.get("ir_id"):
        raise DelegatedReviewError("delegated child changes the Research IR identity")
    if child.get("version") != parent.get("version", 0) + 1:
        raise DelegatedReviewError("delegated child version is not the exact successor")
    if child.get("parent_ir_sha256") != parent_digest:
        raise DelegatedReviewError("delegated child does not bind the parent Research IR")
    pointers = sorted(_diff_pointers(parent, child))
    material = [pointer for pointer in pointers if pointer not in METADATA_POINTERS]
    forbidden = [
        pointer
        for pointer in material
        if _root(pointer) not in ALLOWED_ROOTS and pointer not in ALLOWED_EVALUATOR_POINTERS
    ]
    if forbidden:
        raise DelegatedReviewError(
            f"Research IR changes are not delegated: {forbidden}"
        )
    if not material:
        raise DelegatedReviewError("delegated review requires one material execution-only change")
    _validate_budget_delta(parent, child)
    _validate_experiment_plan_delta(parent, child)
    return material, sorted({_root(pointer) for pointer in material})


def _validate_external_bindings(
    *,
    child_digest: str,
    request: Any,
    proposal: Any,
    changed_roots: list[str],
) -> None:
    if not isinstance(proposal, dict):
        raise DelegatedReviewError("P5 proposal must be an object")
    if proposal.get("child_ir_sha256") != child_digest:
        raise DelegatedReviewError("P5 proposal binds a different child Research IR")
    if sorted(proposal.get("changed_roots", [])) != changed_roots:
        raise DelegatedReviewError("P5 proposal changed_roots differ from actual bytes")
    if not isinstance(request, dict) or not isinstance(request.get("requested_changes"), list):
        raise DelegatedReviewError("P5 request does not contain requested_changes")
    requested = sorted(
        item.get("path") for item in request["requested_changes"] if isinstance(item, dict)
    )
    if requested != changed_roots:
        raise DelegatedReviewError("P5 request does not authorize the actual changed roots")


def _retained_hashes(parent: Mapping[str, Any], child: Mapping[str, Any], changed_roots: list[str]) -> dict[str, str]:
    changed_names = {root.lstrip("/") for root in changed_roots}
    retained: dict[str, str] = {}
    for key in sorted(set(parent) & set(child)):
        if key in changed_names or key in {"version", "parent_ir_sha256"}:
            continue
        if parent[key] != child[key]:
            raise DelegatedReviewError(f"retained root /{key} changed unexpectedly")
        retained[f"/{key}"] = _sha(canonical_bytes(parent[key]))
    return retained


def _validate_budget_delta(parent: Mapping[str, Any], child: Mapping[str, Any]) -> None:
    before = parent.get("budget")
    after = child.get("budget")
    if before == after:
        return
    if not isinstance(before, dict) or not isinstance(after, dict) or set(before) != set(after):
        raise DelegatedReviewError("delegated budget must preserve the closed budget shape")
    bounds = {
        "max_experiments": (4, 64),
        "max_failed_experiments": (2, 32),
        "max_wall_clock_seconds": (86400, 604800),
    }
    for field, (max_increase, absolute_maximum) in bounds.items():
        old = before.get(field)
        new = after.get(field)
        if not isinstance(old, int) or isinstance(old, bool) or not isinstance(new, int) or isinstance(new, bool):
            raise DelegatedReviewError(f"delegated budget field {field} must remain an integer")
        if new > old + max_increase or new > absolute_maximum:
            raise DelegatedReviewError(f"delegated budget field {field} exceeds the bounded increase")


def _validate_experiment_plan_delta(parent: Mapping[str, Any], child: Mapping[str, Any]) -> None:
    before = parent.get("experiment_plan")
    after = child.get("experiment_plan")
    if before == after:
        return
    if not isinstance(before, list) or not isinstance(after, list) or len(before) != len(after):
        raise DelegatedReviewError("delegated experiment plan must preserve the stage count")
    for index, (old, new) in enumerate(zip(before, after, strict=True)):
        if not isinstance(old, dict) or not isinstance(new, dict):
            raise DelegatedReviewError("delegated experiment plan entries must remain objects")
        for field in FROZEN_EXPERIMENT_FIELDS:
            if old.get(field) != new.get(field):
                raise DelegatedReviewError(
                    f"delegated experiment plan changes frozen field /experiment_plan/{index}/{field}"
                )


def publish_review(
    *,
    store_dir: Path,
    parent_ir_path: Path,
    child_ir_path: Path,
    request_path: Path,
    proposal_path: Path,
    compiler_author: str,
    reviewer: str,
    revision_author: str,
    approver: str,
    verdict: str,
    summary: str,
    reviewed_at: str,
) -> dict[str, str]:
    parent, parent_digest = _load_addressed(parent_ir_path, "parent Research IR")
    child, child_digest = _load_addressed(child_ir_path, "child Research IR")
    request, request_digest = _load_addressed(request_path, "P5 request")
    proposal, proposal_digest = _load_addressed(proposal_path, "P5 proposal")
    if not isinstance(parent, dict) or not isinstance(child, dict):
        raise DelegatedReviewError("Research IR roots must be objects")
    changed_pointers, changed_roots = validate_engineering_delta(parent, child)
    _validate_external_bindings(
        child_digest=child_digest,
        request=request,
        proposal=proposal,
        changed_roots=changed_roots,
    )
    identities = {
        "compiler_author": _validate_identity(compiler_author, "compiler author"),
        "reviewer": _validate_identity(reviewer, "reviewer"),
        "revision_author": _validate_identity(revision_author, "revision author"),
        "approver": _validate_identity(approver, "approver"),
    }
    if len(set(identities.values())) != 4:
        raise DelegatedReviewError("compiler, reviewer, revision author, and approver must be distinct")
    if verdict != "ACCEPT":
        raise DelegatedReviewError("delegated engineering review must ACCEPT or remain unfrozen")
    if not isinstance(summary, str) or len(summary.strip()) < 20:
        raise DelegatedReviewError("delegated review summary is too short")
    receipt = {
        **identities,
        "changed_pointers": changed_pointers,
        "changed_roots": changed_roots,
        "child_ir_path": str(child_ir_path.resolve()),
        "child_ir_sha256": child_digest,
        "parent_ir_path": str(parent_ir_path.resolve()),
        "parent_ir_sha256": parent_digest,
        "policy_result": "PASS",
        "proposal_path": str(proposal_path.resolve()),
        "proposal_sha256": proposal_digest,
        "request_path": str(request_path.resolve()),
        "request_sha256": request_digest,
        "retained_root_sha256s": _retained_hashes(parent, child, changed_roots),
        "reviewed_at": _validate_time(reviewed_at),
        "schema_version": REVIEW_VERSION,
        "summary": summary.strip(),
        "verdict": verdict,
    }
    payload = canonical_bytes(receipt)
    digest = _sha(payload)
    path = store_dir.resolve() / "objects" / "sha256" / f"{digest}.json"
    already = _atomic_immutable(path, payload)
    return {
        "already_applied": "true" if already else "false",
        "review_receipt_path": str(path),
        "review_receipt_sha256": digest,
        "verdict": verdict,
    }


def verify_review(*, receipt_path: Path) -> dict[str, Any]:
    receipt, digest = _load_addressed(receipt_path, "delegated review receipt")
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_KEYS:
        raise DelegatedReviewError("delegated review receipt fields differ")
    if receipt["schema_version"] != REVIEW_VERSION or receipt["policy_result"] != "PASS" or receipt["verdict"] != "ACCEPT":
        raise DelegatedReviewError("delegated review receipt policy outcome is invalid")
    parent, parent_digest = _load_addressed(Path(receipt["parent_ir_path"]), "parent Research IR")
    child, child_digest = _load_addressed(Path(receipt["child_ir_path"]), "child Research IR")
    request, request_digest = _load_addressed(Path(receipt["request_path"]), "P5 request")
    proposal, proposal_digest = _load_addressed(Path(receipt["proposal_path"]), "P5 proposal")
    if (
        parent_digest != receipt["parent_ir_sha256"]
        or child_digest != receipt["child_ir_sha256"]
        or request_digest != receipt["request_sha256"]
        or proposal_digest != receipt["proposal_sha256"]
    ):
        raise DelegatedReviewError("delegated review external digest binding changed")
    changed_pointers, changed_roots = validate_engineering_delta(parent, child)
    _validate_external_bindings(
        child_digest=child_digest,
        request=request,
        proposal=proposal,
        changed_roots=changed_roots,
    )
    if changed_pointers != receipt["changed_pointers"] or changed_roots != receipt["changed_roots"]:
        raise DelegatedReviewError("delegated review changed-root evidence differs")
    if _retained_hashes(parent, child, changed_roots) != receipt["retained_root_sha256s"]:
        raise DelegatedReviewError("delegated review retained-root evidence differs")
    identities = [
        _validate_identity(receipt[field], field.replace("_", " "))
        for field in ("compiler_author", "reviewer", "revision_author", "approver")
    ]
    if len(set(identities)) != 4:
        raise DelegatedReviewError("delegated review identities are not distinct")
    _validate_time(receipt["reviewed_at"])
    resolved_receipt = receipt_path.resolve()
    if resolved_receipt.parent.name != "sha256" or resolved_receipt.name != f"{digest}.json":
        raise DelegatedReviewError("delegated review receipt is not at its content address")
    return {
        "changed_pointers": changed_pointers,
        "changed_roots": changed_roots,
        "review_receipt_sha256": digest,
        "verdict": "ACCEPT",
    }
