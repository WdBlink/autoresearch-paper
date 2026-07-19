#!/usr/bin/env python3
"""Run one durable, declarative Claude Code Harness workflow.

The workflow is a closed list of harness-runtime commands. Step outputs may be
referenced as ``${step_id.field}``; every completed step is journaled so a
controller restart resumes without repeating successful external calls.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

RUNTIME = Path(__file__).with_name("harness-runtime.py")
STEP_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
REFERENCE = re.compile(r"\$\{([a-z][a-z0-9_]{0,63})\.([A-Za-z0-9_]+)\}")
ALLOWED = {
    "init-policy", "create-human-action", "apply-human-action", "cancel-worker",
    "create-frontier-request", "send-frontier-request", "reconcile-frontier-request",
    "validate-frontier-response", "apply-frontier-response", "assert-transition",
    "dispatch-worker", "promote-worker-artifacts", "wait-worker", "run-evaluator",
    "freeze-evaluator", "record-evaluator-verdict", "record-failure", "pivot-eligibility",
    "apply-structural-pivot", "resolve-acceptance-dispute", "check-writing-gate",
    "schedule-patrol", "run-patrol", "remove-resource", "validate-action-receipt",
}


class FlowError(RuntimeError):
    pass


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def resolve(value: Any, outputs: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            step, field = match.groups()
            if step not in outputs or field not in outputs[step]:
                raise FlowError(f"unresolved workflow reference: {match.group(0)}")
            result = outputs[step][field]
            if isinstance(result, (dict, list)):
                return json.dumps(result, separators=(",", ":"))
            return str(result)
        return REFERENCE.sub(replace, value)
    if isinstance(value, list):
        return [resolve(item, outputs) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, outputs) for key, item in value.items()}
    return value


def command_argv(plan_dir: Path, command: str, values: dict[str, Any]) -> list[str]:
    if command not in ALLOWED:
        raise FlowError(f"workflow command is not allowed: {command}")
    if "plan-dir" in values or "plan_dir" in values:
        raise FlowError("workflow steps inherit the top-level plan-dir")
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
    return argv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-dir", required=True)
    parser.add_argument("--workflow", required=True)
    args = parser.parse_args()
    plan_dir = Path(args.plan_dir).resolve()
    workflow_path = Path(args.workflow).resolve()
    try:
        workflow = json.loads(workflow_path.read_text())
        if not isinstance(workflow, dict) or set(workflow) != {"schema_version", "flow_id", "steps"}:
            raise FlowError("workflow requires exactly schema_version, flow_id, steps")
        if workflow["schema_version"] != 1 or not STEP_ID.fullmatch(workflow["flow_id"]):
            raise FlowError("invalid workflow schema_version or flow_id")
        if not isinstance(workflow["steps"], list) or not workflow["steps"]:
            raise FlowError("workflow steps must be a non-empty array")
        journal_path = plan_dir / "state" / "canonical_flows" / f"{workflow['flow_id']}.json"
        workflow_hash = __import__("hashlib").sha256(workflow_path.read_bytes()).hexdigest()
        journal = json.loads(journal_path.read_text()) if journal_path.exists() else {
            "schema_version": 1, "flow_id": workflow["flow_id"], "workflow_sha256": workflow_hash,
            "status": "RUNNING", "completed_steps": [], "outputs": {},
        }
        if journal.get("workflow_sha256") != workflow_hash:
            raise FlowError("workflow bytes changed after execution began")
        outputs = journal["outputs"]
        seen: set[str] = set()
        for raw_step in workflow["steps"]:
            if not isinstance(raw_step, dict) or set(raw_step) - {"id", "command", "args", "expect_failure", "error_contains"}:
                raise FlowError("workflow step has unexpected fields")
            step_id = raw_step.get("id")
            if not isinstance(step_id, str) or not STEP_ID.fullmatch(step_id) or step_id in seen:
                raise FlowError("workflow step ids must be unique normalized identifiers")
            seen.add(step_id)
            if step_id in journal["completed_steps"]:
                continue
            values = resolve(raw_step.get("args", {}), outputs)
            if not isinstance(values, dict):
                raise FlowError("workflow step args must be an object")
            proc = subprocess.run(command_argv(plan_dir, raw_step.get("command"), values), cwd=plan_dir,
                                  text=True, capture_output=True)
            expected_failure = raw_step.get("expect_failure") is True
            combined = proc.stdout or proc.stderr
            if expected_failure:
                if proc.returncode == 0 or raw_step.get("error_contains", "") not in combined:
                    raise FlowError(f"step {step_id} did not fail closed as expected")
                result = {"expected_block": True, "returncode": proc.returncode, "evidence": combined.strip()}
            else:
                if proc.returncode != 0:
                    raise FlowError(f"step {step_id} failed: {proc.stderr.strip()}")
                result = json.loads(proc.stdout)
            outputs[step_id] = result
            journal["completed_steps"].append(step_id)
            journal["last_step"] = step_id
            atomic_json(journal_path, journal)
        journal["status"] = "COMPLETED"
        atomic_json(journal_path, journal)
        print(json.dumps({"ok": True, "flow_id": workflow["flow_id"], "journal": str(journal_path),
                          "completed_steps": journal["completed_steps"], "outputs": outputs}, indent=2))
        return 0
    except (OSError, json.JSONDecodeError, FlowError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
