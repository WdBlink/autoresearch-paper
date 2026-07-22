#!/usr/bin/env python3
"""Run the closed, resumable M1 Claude research conformance workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNTIME = Path(__file__).with_name("harness-runtime.py")
CANONICAL_TEMPLATE = RUNTIME.parent.parent / "canonical-conformance-workflow.json"
REFERENCE = re.compile(r"\$\{([a-z][a-z0-9_]{0,63})\.([A-Za-z0-9_]+)\}")
WORKFLOW_KIND = "claude-research-conformance-v1"
SPECIAL_COMMAND = "await-human-actions"


class FlowError(RuntimeError):
    pass


def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def strict_loads(raw: str | bytes) -> Any:
    try:
        return json.loads(raw, parse_constant=reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise FlowError(f"invalid strict JSON: {exc}") from exc


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode()


def stored_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict[str, Any], *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    with tmp.open("w") as handle:
        handle.write(stored_json(value).decode())
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    if immutable:
        path.chmod(0o444)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def stable_file_bytes(path: Path) -> bytes:
    if path.is_symlink():
        raise FlowError(f"terminal source is a symlink: {path}")
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise FlowError(f"terminal source is not a regular file: {path}")
            data = handle.read()
            after = os.fstat(handle.fileno())
        current = path.stat()
    except FileNotFoundError as exc:
        raise FlowError(f"missing terminal artifact: {path}") from exc
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns,
    )
    if identity(before) != identity(after) or identity(after) != identity(current):
        raise FlowError(f"terminal source changed during snapshot capture: {path}")
    return data


def terminal_snapshot(plan_dir: Path, source: Path) -> tuple[Path, str]:
    data = stable_file_bytes(source)
    digest = hashlib.sha256(data).hexdigest()
    root = plan_dir / "state" / "terminal_snapshots"
    if root.is_symlink():
        raise FlowError("terminal snapshot root must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    target = root / digest

    def verify_existing() -> None:
        try:
            metadata = target.lstat()
        except FileNotFoundError as exc:
            raise FlowError("terminal snapshot disappeared during capture") from exc
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o222:
            raise FlowError("terminal snapshot conflicts with immutable controller state")
        if file_sha256(target) != digest:
            raise FlowError("terminal snapshot content-address conflict")

    if target.exists() or target.is_symlink():
        verify_existing()
        return target, digest
    temporary = root / f".{digest}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o444)
        try:
            os.link(temporary, target)
        except FileExistsError:
            verify_existing()
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()
    verify_existing()
    return target, digest


def validate_waiting_proposal(plan_dir: Path, journal: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    proposal_path = plan_dir / "control" / "human_authorization_required.json"
    operation = journal.get("authorization_prepared_operation_id")
    if any((
        journal.get("authorization_proposal") != str(proposal_path),
        not isinstance(journal.get("authorization_proposal_sha256"), str),
        not isinstance(operation, str),
        not proposal_path.is_file(),
        proposal_path.is_symlink(),
    )):
        raise FlowError("durable authorization proposal identity is missing or mismatched")
    if file_sha256(proposal_path) != journal["authorization_proposal_sha256"]:
        raise FlowError("durable authorization proposal bytes changed after waiting was prepared")
    proposal = strict_loads(proposal_path.read_text())
    if proposal.get("prepared_operation_id") != operation:
        raise FlowError("authorization proposal operation identity mismatch")
    return proposal_path, proposal


def resolve(value: Any, outputs: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, str):
        exact = REFERENCE.fullmatch(value)
        if exact:
            step, field = exact.groups()
            if step not in outputs or field not in outputs[step]:
                raise FlowError(f"unresolved workflow reference: {value}")
            return outputs[step][field]

        def replace(match: re.Match[str]) -> str:
            step, field = match.groups()
            if step not in outputs or field not in outputs[step]:
                raise FlowError(f"unresolved workflow reference: {match.group(0)}")
            result = outputs[step][field]
            if isinstance(result, (dict, list)):
                return json.dumps(result, separators=(",", ":"), allow_nan=False)
            return str(result)

        return REFERENCE.sub(replace, value)
    if isinstance(value, list):
        return [resolve(item, outputs) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, outputs) for key, item in value.items()}
    return value


def operation_id(
    plan_dir: Path, workflow_hash: str, inputs_hash: str,
    step_id: str, command: str, values: dict[str, Any],
) -> str:
    return "op_" + hashlib.sha256(canonical_json({
        "plan_id": str(plan_dir), "workflow_sha256": workflow_hash,
        "inputs_sha256": inputs_hash, "step_id": step_id,
        "command": command, "args": values,
    })).hexdigest()


def command_argv(
    plan_dir: Path, command: str, values: dict[str, Any], op_id: str,
) -> list[str]:
    if command == SPECIAL_COMMAND:
        raise FlowError("await-human-actions is a runner boundary, not a runtime command")
    if "plan-dir" in values or "plan_dir" in values or "operation_id" in values:
        raise FlowError("workflow steps inherit plan-dir and operation-id")
    argv = [sys.executable, str(RUNTIME), command, "--plan-dir", str(plan_dir)]
    for key, value in values.items():
        flag = "--" + key.replace("_", "-")
        if isinstance(value, bool):
            if value:
                argv.append(flag)
        elif isinstance(value, list):
            for item in value:
                argv.extend([flag, str(item)])
        elif value is not None:
            argv.extend([flag, str(value)])
    argv.extend(["--operation-id", op_id])
    return argv


def validate_workflow(workflow: Any) -> tuple[dict[str, Any], str]:
    canonical = strict_loads(CANONICAL_TEMPLATE.read_text())
    if not isinstance(workflow, dict):
        raise FlowError("canonical workflow must be an object")
    if set(workflow) != set(canonical):
        raise FlowError("canonical workflow requires exactly the shipped closed template fields")
    if workflow.get("workflow_kind") != WORKFLOW_KIND:
        raise FlowError(f"workflow_kind must be {WORKFLOW_KIND}")
    if not isinstance(workflow.get("steps"), list) or len(workflow["steps"]) != len(canonical["steps"]):
        raise FlowError("canonical workflow is incomplete")
    if workflow != canonical:
        raise FlowError(
            "canonical workflow semantics differ from the shipped closed template "
            "(required inputs, step IDs/order/commands/args/references, or terminal producers changed)"
        )
    return canonical, hashlib.sha256(canonical_json(canonical)).hexdigest()


def run_runtime(plan_dir: Path, command: str, values: dict[str, Any], op_id: str) -> dict[str, Any]:
    proc = subprocess.run(
        command_argv(plan_dir, command, values, op_id),
        cwd=plan_dir, text=True, capture_output=True,
    )
    if proc.returncode != 0:
        raise FlowError(f"{command} failed: {(proc.stderr or proc.stdout).strip()}")
    result = strict_loads(proc.stdout)
    if not isinstance(result, dict):
        raise FlowError(f"{command} returned a non-object result")
    return result


def human_boundary(
    plan_dir: Path, actions_path: Path, parent_operation_id: str,
    proposal_path: Path, proposal: dict[str, Any], proposal_hash: str,
) -> dict[str, Any]:
    if proposal_path.is_symlink() or file_sha256(proposal_path) != proposal_hash:
        raise FlowError("authorization proposal changed before protected actions")
    if proposal.get("prepared_operation_id") != parent_operation_id:
        raise FlowError("authorization proposal operation identity changed before protected actions")
    actions = strict_loads(actions_path.read_text())
    if not isinstance(actions, dict) or set(actions) != {
        "schema_version", "key_file", "stop_record", "cleanup_actions",
    } or actions.get("schema_version") != 1:
        raise FlowError("human action bundle has an invalid closed shape")
    cleanups = actions["cleanup_actions"]
    if not isinstance(cleanups, list):
        raise FlowError("cleanup_actions must be an array")
    manifest = strict_loads((plan_dir / "resource_manifest.json").read_text())
    if not isinstance(manifest.get("plan_id"), str) or not manifest["plan_id"] or not isinstance(manifest.get("resources"), list):
        raise FlowError("resource manifest identity or resources are invalid")
    cleanup_journals = []
    cleanup_journal_root = plan_dir / "state" / "cleanup_journal"
    if cleanup_journal_root.exists():
        cleanup_journals = [strict_loads(path.read_text()) for path in cleanup_journal_root.glob("*.json")]
    eligible_resource_ids: set[str] = set()
    for resource in manifest["resources"]:
        if not isinstance(resource, dict) or resource.get("ephemeral") is not True or resource.get("run_scoped", True) is not True:
            continue
        resource_id = resource.get("resource_id")
        if not isinstance(resource_id, str) or not resource_id or resource_id in eligible_resource_ids:
            raise FlowError("eligible cleanup resources require unique non-empty resource IDs")
        raw_path = Path(str(resource.get("path", "")))
        candidate = raw_path if raw_path.is_absolute() else plan_dir / raw_path
        if candidate.is_symlink():
            raise FlowError("eligible cleanup resource must not be a symlink")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(plan_dir)
        except ValueError as exc:
            raise FlowError("eligible cleanup resource is outside the plan") from exc
        if resolved.exists():
            if not resolved.is_file():
                raise FlowError("eligible cleanup resource must be a regular file")
            eligible_resource_ids.add(resource_id)
        elif any(
            journal.get("phase") in {"PREPARED", "COMMITTED"}
            and journal.get("resource_id") == resource_id
            and journal.get("path") == str(resolved)
            for journal in cleanup_journals if isinstance(journal, dict)
        ):
            eligible_resource_ids.add(resource_id)
        else:
            raise FlowError("eligible manifest resource is missing without a cleanup journal")
    cleanup_resource_ids: list[str] = []
    for item in cleanups:
        if not isinstance(item, dict) or set(item) != {"record", "resource_id", "ownership_token"}:
            raise FlowError("cleanup action requires exactly record, resource_id, ownership_token")
        cleanup_resource_ids.append(item["resource_id"])
    if len(cleanup_resource_ids) != len(set(cleanup_resource_ids)) or set(cleanup_resource_ids) != eligible_resource_ids:
        raise FlowError("cleanup actions must match eligible manifest resources exactly")
    def validate_binding(record_path: str, expected_action: str) -> None:
        record = strict_loads(Path(record_path).read_text())
        details = record.get("details", {}) if isinstance(record, dict) else {}
        if record.get("action") != expected_action or any((
            details.get("authorization_proposal_path") != str(proposal_path),
            details.get("authorization_proposal_sha256") != proposal_hash,
            details.get("prepared_operation_id") != parent_operation_id,
        )):
            raise FlowError("human action is not bound to the durable authorization proposal")
        issued = datetime.fromisoformat(record["issued_at"].replace("Z", "+00:00"))
        created = datetime.fromisoformat(proposal["created_at"].replace("Z", "+00:00"))
        if issued < created:
            raise FlowError("human action predates the durable authorization proposal")

    validate_binding(actions["stop_record"], "stop")
    for item in cleanups:
        validate_binding(item["record"], "cleanup_resource")
    boundary_path = plan_dir / "state" / "human_authorization_boundaries" / "canonical_research_conformance.json"
    bundle_hash = file_sha256(actions_path)
    if boundary_path.exists():
        prior = strict_loads(boundary_path.read_text())
        if prior.get("bundle_sha256") != bundle_hash:
            raise FlowError("human authorization boundary was completed with a different bundle")
        return {"ok": True, "idempotent": True, "authorization_receipt": str(boundary_path), **prior}
    key_file = str(actions["key_file"])
    stop = run_runtime(plan_dir, "apply-human-action", {
        "record": actions["stop_record"], "key_file": key_file,
        "expected_action": "stop",
    }, "op_" + hashlib.sha256(f"{parent_operation_id}:stop".encode()).hexdigest())
    cleanup_results: list[dict[str, Any]] = []
    for index, item in enumerate(cleanups):
        applied = run_runtime(plan_dir, "apply-human-action", {
            "record": item["record"], "key_file": key_file,
            "expected_action": "cleanup_resource",
        }, "op_" + hashlib.sha256(f"{parent_operation_id}:cleanup-auth:{index}".encode()).hexdigest())
        removed = run_runtime(plan_dir, "remove-resource", {
            "resource_id": item["resource_id"],
            "ownership_token": item["ownership_token"],
            "authorization": applied["authorization_path"],
        }, "op_" + hashlib.sha256(f"{parent_operation_id}:cleanup-remove:{index}".encode()).hexdigest())
        cleanup_results.append({"applied": applied, "removed": removed})
    receipt = {
        "schema_version": 1, "status": "AUTHORIZED_AND_CLEANED",
        "bundle_path": str(actions_path.resolve()), "bundle_sha256": bundle_hash,
        "stop_receipt": stop["receipt"]["receipt_path"],
        "cleanup_results": cleanup_results,
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    atomic_json(boundary_path, receipt, immutable=True)
    return {"ok": True, "authorization_receipt": str(boundary_path), **receipt}


def finalize(
    plan_dir: Path, workflow: dict[str, Any], journal_path: Path,
    journal: dict[str, Any], outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    outputs["workflow"] = {"journal": str(journal_path)}
    manifest_path = journal_path.with_name(f"{workflow['flow_id']}.terminal-manifest.json")
    if journal.get("status") not in {"COMPLETED", "FINALIZATION_PREPARED"}:
        captured: list[dict[str, str]] = []
        for declaration in workflow["terminal_artifacts"]:
            source = Path(resolve(declaration["path"], outputs))
            if not source.is_absolute():
                source = plan_dir / source
            source = source.resolve()
            if source == journal_path.resolve():
                captured.append({"type": declaration["type"], "path": str(source)})
                continue
            snapshot, digest = terminal_snapshot(plan_dir, source)
            captured.append({
                "type": declaration["type"], "path": str(snapshot),
                "sha256": digest, "source_path": str(source),
            })
        journal.update({
            "status": "FINALIZATION_PREPARED",
            "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "terminal_manifest_path": str(manifest_path),
            "terminal_artifacts": captured,
        })
        outputs.pop("input", None)
        journal["outputs"] = outputs
        atomic_json(journal_path, journal)
    prepared = journal.get("terminal_artifacts")
    if not isinstance(prepared, list) or len(prepared) != len(workflow["terminal_artifacts"]):
        raise FlowError("prepared terminal snapshot set is missing or incomplete")
    snapshot_root = (plan_dir / "state" / "terminal_snapshots").resolve()
    for declaration, item in zip(workflow["terminal_artifacts"], prepared):
        if not isinstance(item, dict) or item.get("type") != declaration["type"]:
            raise FlowError("prepared terminal snapshot classes changed")
        path = Path(item.get("path", ""))
        if path == journal_path.resolve():
            if set(item) != {"type", "path"}:
                raise FlowError("workflow journal terminal binding changed")
            continue
        if set(item) != {"type", "path", "sha256", "source_path"}:
            raise FlowError("prepared terminal snapshot binding has an invalid shape")
        if path != path.resolve():
            raise FlowError("prepared terminal snapshot path is not canonical")
        try:
            path.relative_to(snapshot_root)
        except ValueError as exc:
            raise FlowError("prepared terminal artifact is outside snapshot authority") from exc
        if path.name != item["sha256"] or path.is_symlink() or not path.is_file():
            raise FlowError("prepared terminal snapshot identity changed")
        metadata = path.stat()
        if metadata.st_mode & 0o222 or file_sha256(path) != item["sha256"]:
            raise FlowError("prepared terminal snapshot bytes or permissions changed")
    outputs.pop("input", None)
    final_journal = strict_loads(stored_json(journal))
    final_journal["status"] = "COMPLETED"
    final_journal_bytes = stored_json(final_journal)
    final_journal_hash = hashlib.sha256(final_journal_bytes).hexdigest()
    terminal: list[dict[str, str]] = []
    for declaration in prepared:
        path = Path(declaration["path"])
        if path == journal_path.resolve():
            terminal.append({**declaration, "sha256": final_journal_hash})
            continue
        terminal.append(dict(declaration))
    manifest = {
        "schema_version": 1, "workflow_kind": WORKFLOW_KIND,
        "flow_id": workflow["flow_id"], "journal_path": str(journal_path),
        "journal_sha256": final_journal_hash,
        "artifacts": terminal,
    }
    if manifest_path.exists():
        prior = strict_loads(manifest_path.read_text())
        if prior != manifest:
            raise FlowError("terminal artifact bytes changed after immutable completion")
    else:
        atomic_json(manifest_path, manifest, immutable=True)
    if file_sha256(manifest_path) != hashlib.sha256(stored_json(manifest)).hexdigest():
        raise FlowError("detached terminal manifest changed before completion commit")
    if journal.get("status") != "COMPLETED":
        atomic_json(journal_path, final_journal)
        journal.clear()
        journal.update(final_journal)
    if file_sha256(journal_path) != manifest["journal_sha256"]:
        raise FlowError("completed journal does not match detached terminal manifest")
    return {
        "ok": True, "workflow_kind": WORKFLOW_KIND, "flow_id": workflow["flow_id"],
        "status": "COMPLETED", "journal": str(journal_path),
        "terminal_manifest": str(manifest_path),
        "terminal_manifest_sha256": file_sha256(manifest_path),
        "completed_steps": journal["completed_steps"],
        "terminal_artifacts": terminal, "outputs": outputs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-dir", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--human-actions")
    parser.add_argument("--simulate-crash-after-step")
    args = parser.parse_args()
    plan_dir = Path(args.plan_dir).resolve()
    workflow_path = Path(args.workflow).resolve()
    inputs_path = Path(args.inputs).resolve()
    try:
        workflow = strict_loads(workflow_path.read_text())
        inputs = strict_loads(inputs_path.read_text())
        canonical, template_digest = validate_workflow(workflow)
        if not isinstance(inputs, dict) or set(inputs) != set(canonical["required_inputs"]):
            raise FlowError("workflow inputs do not exactly match required_inputs")
        workflow_hash = file_sha256(workflow_path)
        inputs_hash = file_sha256(inputs_path)
        journal_path = plan_dir / "state" / "canonical_flows" / f"{workflow['flow_id']}.json"
        journal = strict_loads(journal_path.read_text()) if journal_path.exists() else {
            "schema_version": 1, "workflow_kind": WORKFLOW_KIND,
            "flow_id": workflow["flow_id"], "workflow_sha256": workflow_hash,
            "template_digest": template_digest, "inputs_sha256": inputs_hash,
            "status": "RUNNING", "completed_steps": [], "step_journal": {}, "outputs": {},
            "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if (
            journal.get("workflow_sha256") != workflow_hash
            or journal.get("template_digest") != template_digest
            or journal.get("inputs_sha256") != inputs_hash
        ):
            raise FlowError("workflow template or input bytes changed after execution began")
        if journal.get("status") == "AWAITING_HUMAN_AUTHORIZATION":
            validate_waiting_proposal(plan_dir, journal)
        if journal.get("status") == "COMPLETED":
            outputs = journal["outputs"]
            outputs["input"] = inputs
            print(json.dumps(finalize(plan_dir, workflow, journal_path, journal, outputs), indent=2))
            return 0
        outputs = journal["outputs"]
        outputs["input"] = inputs
        for raw_step in workflow["steps"]:
            step_id = raw_step["id"]
            if step_id in journal["completed_steps"]:
                continue
            values = resolve(raw_step["args"], outputs)
            op_id = operation_id(
                plan_dir, workflow_hash, inputs_hash, step_id, raw_step["command"], values,
            )
            prepared = journal["step_journal"].get(step_id)
            if prepared and prepared.get("operation_id") != op_id:
                raise FlowError(f"prepared operation changed for step {step_id}")
            journal["step_journal"][step_id] = {
                "phase": "PREPARED", "operation_id": op_id,
                "command": raw_step["command"],
                "args_sha256": hashlib.sha256(canonical_json(values)).hexdigest(),
            }
            proposal_path = plan_dir / "control" / "human_authorization_required.json"
            was_waiting = (
                journal.get("status") == "AWAITING_HUMAN_AUTHORIZATION"
                and journal.get("authorization_prepared_operation_id") == op_id
            )
            if raw_step["command"] != SPECIAL_COMMAND or not was_waiting:
                journal["status"] = "RUNNING"
                atomic_json(journal_path, journal)
            if raw_step["command"] == SPECIAL_COMMAND:
                if not was_waiting:
                    if proposal_path.exists():
                        raise FlowError("authorization proposal exists without matching durable waiting state")
                    proposal = {
                        "schema_version": 1, "flow_id": workflow["flow_id"],
                        "status": "AWAITING_HUMAN_AUTHORIZATION",
                        "required_actions": ["fresh_stop", "fresh_per_resource_cleanup"],
                        "prepared_operation_id": op_id,
                        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    }
                    atomic_json(proposal_path, proposal, immutable=True)
                    journal["status"] = "AWAITING_HUMAN_AUTHORIZATION"
                    journal["authorization_proposal"] = str(proposal_path)
                    journal["authorization_proposal_sha256"] = file_sha256(proposal_path)
                    journal["authorization_prepared_operation_id"] = op_id
                    atomic_json(journal_path, journal)
                    print(json.dumps({
                        "ok": False, "resumable": True,
                        "status": "AWAITING_HUMAN_AUTHORIZATION",
                        "journal": str(journal_path), "authorization_proposal": str(proposal_path),
                    }, indent=2))
                    return 3
                proposal_path, proposal = validate_waiting_proposal(plan_dir, journal)
                if journal["authorization_prepared_operation_id"] != op_id:
                    raise FlowError("authorization proposal operation identity is stale")
                if not args.human_actions:
                    journal["status"] = "AWAITING_HUMAN_AUTHORIZATION"
                    atomic_json(journal_path, journal)
                    print(json.dumps({"ok": False, "resumable": True,
                        "status": "AWAITING_HUMAN_AUTHORIZATION", "journal": str(journal_path),
                        "authorization_proposal": str(proposal_path)}, indent=2))
                    return 3
                result = human_boundary(
                    plan_dir, Path(args.human_actions).resolve(), op_id, proposal_path, proposal,
                    journal["authorization_proposal_sha256"],
                )
            else:
                result = run_runtime(plan_dir, raw_step["command"], values, op_id)
            if args.simulate_crash_after_step == step_id:
                raise FlowError(f"simulated runner crash after successful step {step_id}")
            outputs[step_id] = result
            journal["completed_steps"].append(step_id)
            journal["last_step"] = step_id
            journal["step_journal"][step_id].update({"phase": "COMMITTED", "result": result})
            journal["outputs"] = outputs
            atomic_json(journal_path, journal)
        result = finalize(plan_dir, workflow, journal_path, journal, outputs)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, FlowError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
