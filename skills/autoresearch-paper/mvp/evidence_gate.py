#!/usr/bin/env python3
"""Deterministic MVP-0 P4 Evidence Gate over one P3 Experiment Receipt.

The domain evaluator is frozen by Research IR and emits a closed report. This
module verifies that report and computes KEEP/PIVOT/STOP/RECOMPILE. It does not
analyze failures, revise Research IR, dispatch Workers, or run an autonomous
loop; those are P5 or later concerns.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from . import experiment_ledger as ledger
    from . import worker_adapter as worker
except ImportError:  # pragma: no cover - direct script execution
    import experiment_ledger as ledger  # type: ignore[no-redef]
    import worker_adapter as worker  # type: ignore[no-redef]


MVP_ROOT = Path(__file__).resolve().parent
REPORT_SCHEMA_PATH = MVP_ROOT / "schemas" / "evaluator-report.schema.json"
DECISION_SCHEMA_PATH = MVP_ROOT / "schemas" / "evidence-gate-decision.schema.json"
STORE_VERSION = "evidence-gate-store/v1"
REPORT_VERSION = "evaluator-report/v1"
DECISION_VERSION = "evidence-gate-decision/v1"
RECORD_VERSION = "evidence-gate-record/v1"


class GateError(RuntimeError):
    """A fail-closed evaluator, decision, or replay error."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return worker._canonical_bytes(value)  # noqa: SLF001
    except worker.AdapterError as exc:
        raise GateError(str(exc)) from exc


def _sha256_bytes(value: bytes) -> str:
    return worker._sha256_bytes(value)  # noqa: SLF001


def _sha256_file(path: Path) -> str:
    return worker._sha256_file(path)  # noqa: SLF001


def _load_json(path: Path) -> Any:
    try:
        return worker._load_json(path)  # noqa: SLF001
    except worker.AdapterError as exc:
        raise GateError(str(exc)) from exc


def _atomic_write(path: Path, payload: bytes, *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and (path.exists() or path.is_symlink()):
        raise GateError(f"immutable artifact already exists: {path}")
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
            raise GateError(f"content-addressed artifact collided or became mutable: {path}")
        return
    _atomic_write(path, payload, immutable=True)


def _immutable_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o777 != 0o444:
        raise GateError(f"{label} is missing, mutable, or a symlink: {path}")
    value = _load_json(path)
    if not isinstance(value, dict):
        raise GateError(f"{label} must be a JSON object")
    return value, _sha256_file(path)


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise GateError(
            f"{label} fields differ: missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _validate(value: Any, schema: Path, label: str) -> dict[str, Any]:
    try:
        worker._validate_against_schema(value, schema, label)  # noqa: SLF001
    except worker.AdapterError as exc:
        raise GateError(str(exc)) from exc
    if not isinstance(value, dict):
        raise GateError(f"{label} must be an object")
    return value


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def initialize_store(*, ledger_dir: Path, store_dir: Path) -> dict[str, Any]:
    """Bind a new P4 store to one P3 ledger and its frozen Research IR."""

    ledger_dir = ledger_dir.resolve()
    try:
        ledger.verify_ledger(ledger_dir=ledger_dir)
        ledger_manifest, adapter_manifest, _session = ledger._ledger_manifest(  # noqa: SLF001
            ledger_dir
        )
    except (ledger.LedgerError, worker.AdapterError) as exc:
        raise GateError(f"P3 ledger replay failed: {exc}") from exc
    store_dir = store_dir.resolve()
    if store_dir.exists() or store_dir.is_symlink():
        raise GateError("store_dir already exists")
    protected = (
        Path(adapter_manifest["source_repo"]).resolve(),
        Path(adapter_manifest["worktree_root"]).resolve(),
        Path(ledger_manifest["adapter_dir"]).resolve(),
        ledger_dir,
    )
    if any(_inside(store_dir, root) or _inside(root, store_dir) for root in protected):
        raise GateError("store_dir must not overlap the source, worktree, Adapter, or P3 ledger")
    store_dir.parent.mkdir(parents=True, exist_ok=True)
    store_dir.mkdir()
    try:
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            ),
            "decision_schema_sha256": _sha256_file(DECISION_SCHEMA_PATH),
            "gate_id": "mvp0-gate-" + uuid.uuid4().hex[:16],
            "ledger_dir": str(ledger_dir),
            "ledger_id": ledger_manifest["ledger_id"],
            "ledger_manifest_path": str(ledger_dir / "ledger-manifest.json"),
            "ledger_manifest_sha256": _sha256_file(ledger_dir / "ledger-manifest.json"),
            "report_schema_sha256": _sha256_file(REPORT_SCHEMA_PATH),
            "research_ir_sha256": ledger_manifest["research_ir_sha256"],
            "schema_version": STORE_VERSION,
        }
        _publish_json(store_dir / "gate-manifest.json", manifest)
        for relative in (
            "reports/sha256",
            "decisions/sha256",
            "records/by-experiment-receipt",
            "blobs/sha256",
        ):
            (store_dir / relative).mkdir(parents=True)
    except Exception:
        shutil.rmtree(store_dir)
        raise
    return {
        "gate_id": manifest["gate_id"],
        "ledger_id": manifest["ledger_id"],
        "research_ir_sha256": manifest["research_ir_sha256"],
        "store_dir": str(store_dir),
    }


def _store_manifest(
    store_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest, _digest = _immutable_json(store_dir / "gate-manifest.json", "Gate manifest")
    _exact_keys(manifest, {
        "created_at",
        "decision_schema_sha256",
        "gate_id",
        "ledger_dir",
        "ledger_id",
        "ledger_manifest_path",
        "ledger_manifest_sha256",
        "report_schema_sha256",
        "research_ir_sha256",
        "schema_version",
    }, "Gate manifest")
    if manifest["schema_version"] != STORE_VERSION:
        raise GateError("Gate store version is unsupported")
    if (
        _sha256_file(REPORT_SCHEMA_PATH) != manifest["report_schema_sha256"]
        or _sha256_file(DECISION_SCHEMA_PATH) != manifest["decision_schema_sha256"]
    ):
        raise GateError("P4 schema drifted after Gate initialization")
    ledger_dir = Path(manifest["ledger_dir"]).resolve()
    if (
        Path(manifest["ledger_manifest_path"]).resolve() != ledger_dir / "ledger-manifest.json"
        or _sha256_file(ledger_dir / "ledger-manifest.json") != manifest["ledger_manifest_sha256"]
    ):
        raise GateError("Gate store P3 ledger binding changed")
    try:
        ledger.verify_ledger(ledger_dir=ledger_dir)
        ledger_manifest, adapter_manifest, _session = ledger._ledger_manifest(  # noqa: SLF001
            ledger_dir
        )
        ir = worker._load_ir_from_manifest(adapter_manifest)  # noqa: SLF001
    except (ledger.LedgerError, worker.AdapterError) as exc:
        raise GateError(f"bound P3 ledger replay failed: {exc}") from exc
    if (
        ledger_manifest["ledger_id"] != manifest["ledger_id"]
        or ledger_manifest["research_ir_sha256"] != manifest["research_ir_sha256"]
    ):
        raise GateError("Gate store identity differs from the bound P3 ledger")
    return manifest, ledger_manifest, ir


def _receipt(
    *, store_manifest: Mapping[str, Any], digest: str
) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
    ledger_dir = Path(store_manifest["ledger_dir"])
    try:
        entries = ledger._load_index(ledger_dir)  # noqa: SLF001
    except ledger.LedgerError as exc:
        raise GateError(str(exc)) from exc
    entry = next((item for item in entries if item["receipt_sha256"] == digest), None)
    if entry is None:
        raise GateError("Experiment Receipt digest is not in the bound complete P3 ledger")
    path = ledger_dir / "objects" / "sha256" / f"{digest}.json"
    value, actual = _immutable_json(path, "Experiment Receipt")
    if actual != digest or value != entry["receipt"]:
        raise GateError("Experiment Receipt object differs from its P3 index")
    return value, path, entries[: entry["sequence"]]


def _metric_contracts(ir: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    contract = ir.get("metric_contract")
    if not isinstance(contract, dict):
        raise GateError("Research IR lacks a P4 metric contract")
    primary = contract.get("primary_metric")
    guardrails = contract.get("guardrails")
    if not isinstance(primary, dict) or not isinstance(guardrails, list):
        raise GateError("Research IR metric contract is malformed")
    return [("PRIMARY", primary), *[("GUARDRAIL", item) for item in guardrails]]


def _known_receipt_artifacts(receipt: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    provenance = receipt["provenance"]
    items: list[Mapping[str, Any]] = [
        *provenance["input_artifacts"],
        *provenance["data_artifacts"],
        *provenance["environment"]["artifacts"],
        *receipt["artifacts"],
    ]
    for observation in receipt["observations"]:
        items.extend(observation["evidence"])
    known: dict[tuple[str, str], str] = {}
    for item in items:
        identity = (item["path"], item["sha256"])
        blob_path = item["blob_path"]
        prior = known.get(identity)
        if prior is not None and prior != blob_path:
            raise GateError("Experiment Receipt maps one artifact identity to multiple blobs")
        known[identity] = blob_path
    return known


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise GateError(f"invalid bound timestamp: {value}") from exc


def _prepare_report(
    *,
    path: Path,
    ledger_dir: Path,
    ir: Mapping[str, Any],
    ir_digest: str,
    receipt: Mapping[str, Any],
    receipt_digest: str,
) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file():
        raise GateError("Evaluator report is missing, non-regular, or a symlink")
    report = _validate(_load_json(path), REPORT_SCHEMA_PATH, "Evaluator report")
    if report["schema_version"] != REPORT_VERSION:
        raise GateError("Evaluator report version is unsupported")
    evaluator = ir.get("evaluator_spec")
    baseline = ir.get("baseline_contract")
    if not isinstance(evaluator, dict) or not isinstance(baseline, dict):
        raise GateError("Research IR lacks P4 evaluator/baseline contracts")
    expected_evaluator_sha = evaluator.get("implementation_sha256")
    if evaluator.get("status") != "READY" or not isinstance(expected_evaluator_sha, str):
        raise GateError("a completed evaluator report requires a READY frozen evaluator")
    if (
        report["research_ir_sha256"] != ir_digest
        or report["experiment_receipt_sha256"] != receipt_digest
        or report["candidate_id"] != receipt["task"]["id"]
        or report["baseline_id"] != baseline.get("baseline_id")
        or report["evaluator_implementation_sha256"] != expected_evaluator_sha
        or report["execution"] != {
            "working_directory": evaluator.get("working_directory"),
            "command_argv": evaluator.get("command_argv"),
            "exit_code": 0,
        }
    ):
        raise GateError("Evaluator report identity or frozen execution binding differs")
    if report["seeds"] != receipt["task"]["seeds"]:
        raise GateError("Evaluator report seeds differ from the pre-dispatch task contract")
    if _parse_time(report["evaluated_at"]) < _parse_time(receipt["execution"]["completed_at"]):
        raise GateError("Evaluator report predates the Experiment Receipt")

    metrics = _metric_contracts(ir)
    by_metric: dict[str, Mapping[str, Any]] = {}
    for result in report["metrics"]:
        metric_id = result["metric_id"]
        if metric_id in by_metric:
            raise GateError(f"Evaluator report duplicates metric {metric_id}")
        for label in ("candidate", "baseline"):
            aggregate = result[label]
            if not aggregate["ci_lower"] <= aggregate["estimate"] <= aggregate["ci_upper"]:
                raise GateError(f"Evaluator report {label} confidence interval is incoherent")
        by_metric[metric_id] = result
    expected_metric_ids = {metric["metric_id"] for _role, metric in metrics}
    if set(by_metric) != expected_metric_ids:
        raise GateError("Evaluator report metric set differs from frozen Research IR")
    for _role, metric in metrics:
        result = by_metric[metric["metric_id"]]
        if (
            result["unit"] != metric["unit"]
            or result["confidence_level"] != metric["acceptance"]["confidence_level"]
        ):
            raise GateError("Evaluator report unit/confidence differs from frozen metric")

    rules = ir.get("stop_rules")
    if not isinstance(rules, list):
        raise GateError("Research IR lacks frozen stop rules")
    by_rule: dict[str, Mapping[str, Any]] = {}
    for result in report["stop_rules"]:
        if result["rule_id"] in by_rule:
            raise GateError(f"Evaluator report duplicates stop rule {result['rule_id']}")
        by_rule[result["rule_id"]] = result
    if set(by_rule) != {rule["id"] for rule in rules}:
        raise GateError("Evaluator report stop-rule set differs from frozen Research IR")

    known = _known_receipt_artifacts(receipt)
    source_digests: set[str] = set()
    source_identities: set[tuple[str, str]] = set()
    for item in report["source_artifacts"]:
        identity = (item["path"], item["sha256"])
        if identity in source_identities:
            raise GateError("Evaluator report duplicates a source artifact identity")
        source_identities.add(identity)
        if known.get(identity) != item["blob_path"]:
            raise GateError("Evaluator source artifact is not bound by the Experiment Receipt")
        try:
            ledger._verify_blob(ledger_dir, item["blob_path"], item["sha256"])  # noqa: SLF001
        except ledger.LedgerError as exc:
            raise GateError(f"Evaluator source artifact replay failed: {exc}") from exc
        source_digests.add(item["sha256"])
    for rule in rules:
        result = by_rule[rule["id"]]
        evidence = result["evidence"]
        if not result["triggered"] and evidence:
            raise GateError("an untriggered stop rule must not claim evidence")
        if result["triggered"]:
            requirements = [item["requirement"] for item in evidence]
            if (
                len(requirements) != len(set(requirements))
                or set(requirements) != set(rule["evidence_required"])
            ):
                raise GateError("triggered stop-rule evidence requirements are incomplete")
            if any(item["artifact_sha256"] not in source_digests for item in evidence):
                raise GateError("stop-rule evidence is not among evaluator source artifacts")
    return report, _sha256_bytes(_canonical_bytes(report))


def _archive_evaluator(store_dir: Path, ir: Mapping[str, Any], digest: str) -> Path:
    path = Path(ir["evaluator_spec"]["implementation_artifact"]).resolve()
    if path.is_symlink() or not path.is_file() or _sha256_file(path) != digest:
        raise GateError("frozen evaluator implementation is missing or hash-drifted")
    target = store_dir / "blobs" / "sha256" / digest
    if target.exists() or target.is_symlink():
        if (
            target.is_symlink()
            or not target.is_file()
            or target.stat().st_mode & 0o777 != 0o444
            or _sha256_file(target) != digest
        ):
            raise GateError("archived evaluator implementation drifted")
    else:
        _atomic_write(target, path.read_bytes(), immutable=True)
    return target


def _compare(left: float, operator: str, right: float) -> bool:
    return {
        "<": left < right,
        "<=": left <= right,
        ">": left > right,
        ">=": left >= right,
    }[operator]


def _budget(ir: Mapping[str, Any], prefix: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    contract = ir.get("budget")
    if not isinstance(contract, dict):
        raise GateError("Research IR lacks a P4 budget contract")
    failed = sum(item["receipt"]["execution"]["status"] != "COMPLETED" for item in prefix)
    first = _parse_time(prefix[0]["receipt"]["execution"]["started_at"])
    last = _parse_time(prefix[-1]["receipt"]["execution"]["completed_at"])
    elapsed = max(0, int((last - first).total_seconds()))
    failure_exhausted = failed > 0 and failed >= contract["max_failed_experiments"]
    return {
        "max_experiments": contract["max_experiments"],
        "observed_experiments": len(prefix),
        "experiment_budget_exhausted": len(prefix) >= contract["max_experiments"],
        "max_failed_experiments": contract["max_failed_experiments"],
        "observed_failed_experiments": failed,
        "failure_budget_exhausted": failure_exhausted,
        "max_wall_clock_seconds": contract["max_wall_clock_seconds"],
        "observed_wall_clock_seconds": elapsed,
        "wall_clock_budget_exhausted": elapsed >= contract["max_wall_clock_seconds"],
    }


def _assess_metrics(
    ir: Mapping[str, Any], report: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results = {item["metric_id"]: item for item in report["metrics"]}
    assessments: list[dict[str, Any]] = []
    observed_seeds = len(report["seeds"])
    for role, metric in _metric_contracts(ir):
        acceptance = metric["acceptance"]
        result = results[metric["metric_id"]]
        aggregation = acceptance["aggregation"]
        candidate = result["candidate"][aggregation]
        baseline = result["baseline"][aggregation]
        seeds_pass = observed_seeds >= acceptance["minimum_seeds"]
        threshold_pass = _compare(candidate, acceptance["operator"], acceptance["value"])
        noninferior: bool | None = None
        if role == "PRIMARY":
            noninferior = (
                candidate >= baseline
                if metric["direction"] == "maximize"
                else candidate <= baseline
            )
        assessments.append({
            "aggregation": aggregation,
            "baseline_noninferior": noninferior,
            "baseline_value": baseline,
            "candidate_value": candidate,
            "metric_id": metric["metric_id"],
            "minimum_seeds": acceptance["minimum_seeds"],
            "observed_seeds": observed_seeds,
            "operator": acceptance["operator"],
            "passed": seeds_pass and threshold_pass and noninferior is not False,
            "role": role,
            "seeds_pass": seeds_pass,
            "threshold": acceptance["value"],
            "threshold_pass": threshold_pass,
        })
    minimum_seeds = {
        metric["metric_id"]: metric["acceptance"]["minimum_seeds"]
        for _role, metric in _metric_contracts(ir)
    }
    falsification: list[dict[str, Any]] = []
    for condition in ir["falsification_conditions"]:
        result = results[condition["metric_id"]]
        value = result["candidate"][condition["aggregation"]]
        sufficient = observed_seeds >= minimum_seeds[condition["metric_id"]]
        falsification.append({
            "aggregation": condition["aggregation"],
            "condition_id": condition["id"],
            "evidence_sufficient": sufficient,
            "metric_id": condition["metric_id"],
            "observed_value": value,
            "operator": condition["operator"],
            "threshold": condition["value"],
            "triggered": sufficient and _compare(value, condition["operator"], condition["value"]),
        })
    return assessments, falsification


def _build_decision(
    *,
    store_manifest: Mapping[str, Any],
    ir: Mapping[str, Any],
    receipt: Mapping[str, Any],
    receipt_path: Path,
    receipt_digest: str,
    prefix: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any] | None,
    report_path: Path | None,
    report_digest: str | None,
) -> dict[str, Any]:
    budget = _budget(ir, prefix)
    metrics: list[dict[str, Any]] = []
    falsification: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    reasons: list[str] = []
    accepted = False
    status = receipt["execution"]["status"]

    if status != "COMPLETED":
        if report is not None:
            raise GateError("BLOCKED/FAILED receipts cannot carry an evaluator report")
        reasons.append("RECEIPT_BLOCKED" if status == "BLOCKED" else "RECEIPT_FAILED")
    elif ir["evaluator_spec"]["status"] != "READY":
        if report is not None:
            raise GateError("a PLANNED evaluator cannot produce a Gate evaluator report")
        reasons.append("EVALUATOR_REQUIRES_FREEZE")
    else:
        if report is None or report_path is None or report_digest is None:
            raise GateError("a COMPLETED receipt with READY evaluator requires --evaluator-report")
        metrics, falsification = _assess_metrics(ir, report)
        rule_results = {item["rule_id"]: item for item in report["stop_rules"]}
        rules = [
            {
                "action": rule["action"],
                "evidence": rule_results[rule["id"]]["evidence"],
                "rule_id": rule["id"],
                "triggered": rule_results[rule["id"]]["triggered"],
            }
            for rule in ir["stop_rules"]
        ]
        accepted = all(item["passed"] for item in metrics) and not any(
            item["triggered"] for item in falsification
        ) and not any(item["triggered"] for item in rules)
        if accepted:
            reasons.append("CANDIDATE_MEETS_GATE")
        if any(not item["seeds_pass"] for item in metrics):
            reasons.append("INSUFFICIENT_SEEDS")
        primary = next(item for item in metrics if item["role"] == "PRIMARY")
        if not primary["threshold_pass"]:
            reasons.append("PRIMARY_THRESHOLD_MISSED")
        if primary["baseline_noninferior"] is False:
            reasons.append("BASELINE_COMPARISON_MISSED")
        if any(not item["threshold_pass"] for item in metrics if item["role"] == "GUARDRAIL"):
            reasons.append("GUARDRAIL_MISSED")
        if any(item["triggered"] for item in falsification):
            reasons.append("CLAIM_FALSIFIED")
        if any(item["triggered"] and item["action"] == "STOP" for item in rules):
            reasons.append("STOP_RULE_TRIGGERED")
        if any(item["triggered"] and item["action"] == "RECOMPILE" for item in rules):
            reasons.append("RECOMPILE_RULE_TRIGGERED")

    budget_codes = (
        ("experiment_budget_exhausted", "EXPERIMENT_BUDGET_EXHAUSTED"),
        ("failure_budget_exhausted", "FAILURE_BUDGET_EXHAUSTED"),
        ("wall_clock_budget_exhausted", "WALL_CLOCK_BUDGET_EXHAUSTED"),
    )
    for field, code in budget_codes:
        if budget[field]:
            reasons.append(code)

    hard_stop = (
        any(item["triggered"] for item in falsification)
        or any(item["triggered"] and item["action"] == "STOP" for item in rules)
        or any(budget[field] for field, _code in budget_codes)
    )
    recompile = (
        "EVALUATOR_REQUIRES_FREEZE" in reasons
        or any(item["triggered"] and item["action"] == "RECOMPILE" for item in rules)
    )
    if hard_stop:
        decision = "STOP"
    elif recompile:
        decision = "RECOMPILE"
    elif accepted:
        decision = "KEEP"
    else:
        decision = "PIVOT"
    unique_reasons = list(dict.fromkeys(reasons))
    if not unique_reasons:
        raise GateError("Evidence Gate produced no auditable reason")
    decision_value = {
        "budget_assessment": budget,
        "candidate_accepted": accepted,
        "decided_at": (
            report["evaluated_at"] if report is not None else receipt["execution"]["completed_at"]
        ),
        "decision": decision,
        "evaluator_report": (
            None
            if report is None
            else {
                "evaluator_implementation_sha256": report["evaluator_implementation_sha256"],
                "path": str(report_path),
                "sha256": report_digest,
            }
        ),
        "experiment_receipt": {
            "path": str(receipt_path),
            "sequence": receipt["sequence"],
            "sha256": receipt_digest,
            "status": status,
        },
        "falsification_assessments": falsification,
        "gate_id": store_manifest["gate_id"],
        "metric_assessments": metrics,
        "reason_codes": unique_reasons,
        "research_ir": {
            "ir_id": ir["ir_id"],
            "sha256": store_manifest["research_ir_sha256"],
            "version": ir["version"],
        },
        "schema_version": DECISION_VERSION,
        "stop_rule_assessments": rules,
    }
    return _validate(decision_value, DECISION_SCHEMA_PATH, "Evidence Gate decision")


def _object_digests(root: Path, suffix: str) -> set[str]:
    if root.is_symlink() or not root.is_dir():
        raise GateError(f"Gate object directory is missing or a symlink: {root}")
    digests: set[str] = set()
    for path in root.iterdir():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix != suffix
            or not ledger.SHA256_RE.fullmatch(path.stem)
            or path.stat().st_mode & 0o777 != 0o444
        ):
            raise GateError(f"invalid Gate object-store entry: {path}")
        digests.add(path.stem)
    return digests


def _records(store_dir: Path) -> list[tuple[dict[str, Any], Path]]:
    root = store_dir / "records" / "by-experiment-receipt"
    if root.is_symlink() or not root.is_dir():
        raise GateError("Gate record directory is missing or a symlink")
    records: list[tuple[dict[str, Any], Path]] = []
    for path in sorted(root.iterdir()):
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix != ".json"
            or not ledger.SHA256_RE.fullmatch(path.stem)
        ):
            raise GateError(f"invalid Gate record entry: {path}")
        record, _digest = _immutable_json(path, "Gate receipt record")
        _exact_keys(record, {
            "decision_path",
            "decision_sha256",
            "evaluator_report_sha256",
            "experiment_receipt_sha256",
            "schema_version",
        }, "Gate receipt record")
        if (
            record["schema_version"] != RECORD_VERSION
            or record["experiment_receipt_sha256"] != path.stem
            or not ledger.SHA256_RE.fullmatch(record["decision_sha256"])
            or (
                record["evaluator_report_sha256"] is not None
                and not ledger.SHA256_RE.fullmatch(record["evaluator_report_sha256"])
            )
        ):
            raise GateError("Gate receipt record identity is invalid")
        records.append((record, path))
    return records


def _verify_store(*, store_dir: Path, strict_inventory: bool) -> dict[str, Any]:
    store_dir = store_dir.resolve()
    manifest, _ledger_manifest, ir = _store_manifest(store_dir)
    records = _records(store_dir)
    expected_reports: set[str] = set()
    expected_decisions: set[str] = set()
    expected_blobs: set[str] = set()
    decided_sequences: list[int] = []
    for record, _record_path in records:
        receipt, receipt_path, prefix = _receipt(
            store_manifest=manifest,
            digest=record["experiment_receipt_sha256"],
        )
        decided_sequences.append(receipt["sequence"])
        report: dict[str, Any] | None = None
        report_path: Path | None = None
        report_digest = record["evaluator_report_sha256"]
        if report_digest is not None:
            expected_reports.add(report_digest)
            report_path = store_dir / "reports" / "sha256" / f"{report_digest}.json"
            report, actual = _immutable_json(report_path, "Evaluator report object")
            if actual != report_digest:
                raise GateError("Evaluator report object is not content addressed")
            report, rebuilt_digest = _prepare_report(
                path=report_path,
                ledger_dir=Path(manifest["ledger_dir"]),
                ir=ir,
                ir_digest=manifest["research_ir_sha256"],
                receipt=receipt,
                receipt_digest=record["experiment_receipt_sha256"],
            )
            if rebuilt_digest != report_digest:
                raise GateError("Evaluator report canonical digest changed")
            evaluator_blob = store_dir / "blobs" / "sha256" / report["evaluator_implementation_sha256"]
            expected_blobs.add(report["evaluator_implementation_sha256"])
            if (
                evaluator_blob.is_symlink()
                or not evaluator_blob.is_file()
                or evaluator_blob.stat().st_mode & 0o777 != 0o444
                or _sha256_file(evaluator_blob) != report["evaluator_implementation_sha256"]
            ):
                raise GateError("archived evaluator implementation is unavailable or drifted")
        decision_digest = record["decision_sha256"]
        expected_decisions.add(decision_digest)
        decision_path = store_dir / "decisions" / "sha256" / f"{decision_digest}.json"
        decision, actual = _immutable_json(decision_path, "Evidence Gate decision object")
        if actual != decision_digest or str(decision_path) != record["decision_path"]:
            raise GateError("Evidence Gate decision is not content addressed")
        rebuilt = _build_decision(
            store_manifest=manifest,
            ir=ir,
            receipt=receipt,
            receipt_path=receipt_path,
            receipt_digest=record["experiment_receipt_sha256"],
            prefix=prefix,
            report=report,
            report_path=report_path,
            report_digest=report_digest,
        )
        if decision != rebuilt:
            raise GateError("Evidence Gate decision does not replay from frozen inputs")
    if sorted(decided_sequences) != list(range(1, len(decided_sequences) + 1)):
        raise GateError("Gate records must be a contiguous prefix of P3 Experiment Receipts")
    if strict_inventory:
        if _object_digests(store_dir / "reports" / "sha256", ".json") != expected_reports:
            raise GateError("Evaluator report object inventory differs from Gate records")
        if _object_digests(store_dir / "decisions" / "sha256", ".json") != expected_decisions:
            raise GateError("Decision object inventory differs from Gate records")
        if _object_digests(store_dir / "blobs" / "sha256", "") != expected_blobs:
            raise GateError("Evaluator implementation blob inventory differs from Gate records")
    return {
        "decision_count": len(records),
        "gate_id": manifest["gate_id"],
        "research_ir_sha256": manifest["research_ir_sha256"],
        "store_dir": str(store_dir),
        "verified": True,
    }


def verify_store(*, store_dir: Path) -> dict[str, Any]:
    """Replay every one-query Gate record from the bound complete P3 ledger."""

    return _verify_store(store_dir=store_dir, strict_inventory=True)


def decide(
    *,
    store_dir: Path,
    experiment_receipt_sha256: str,
    evaluator_report: Path | None,
) -> dict[str, Any]:
    """Publish one deterministic decision for one Experiment Receipt."""

    if not ledger.SHA256_RE.fullmatch(experiment_receipt_sha256):
        raise GateError("experiment_receipt_sha256 must be lowercase SHA-256")
    store_dir = store_dir.resolve()
    lock_path = store_dir / ".gate.lock"
    lock_path.touch(exist_ok=True)
    lock = lock_path.open("r+")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        manifest, _ledger_manifest, ir = _store_manifest(store_dir)
        _verify_store(store_dir=store_dir, strict_inventory=False)
        receipt, receipt_path, prefix = _receipt(
            store_manifest=manifest,
            digest=experiment_receipt_sha256,
        )
        records = _records(store_dir)
        report: dict[str, Any] | None = None
        report_digest: str | None = None
        report_path: Path | None = None
        if evaluator_report is not None:
            report, report_digest = _prepare_report(
                path=evaluator_report.resolve(),
                ledger_dir=Path(manifest["ledger_dir"]),
                ir=ir,
                ir_digest=manifest["research_ir_sha256"],
                receipt=receipt,
                receipt_digest=experiment_receipt_sha256,
            )
            report_path = store_dir / "reports" / "sha256" / f"{report_digest}.json"

        record_path = (
            store_dir
            / "records"
            / "by-experiment-receipt"
            / f"{experiment_receipt_sha256}.json"
        )
        if record_path.exists() or record_path.is_symlink():
            record, _record_digest = _immutable_json(record_path, "Gate receipt record")
            if record.get("evaluator_report_sha256") != report_digest:
                raise GateError("one-query Gate record already binds a different evaluator report")
            verified = verify_store(store_dir=store_dir)
            decision_value, _decision_digest = _immutable_json(
                Path(record["decision_path"]),
                "Evidence Gate decision object",
            )
            return {
                "already_decided": True,
                "candidate_accepted": decision_value["candidate_accepted"],
                "decision": decision_value["decision"],
                "decision_path": record["decision_path"],
                "decision_sha256": record["decision_sha256"],
                "experiment_receipt_sha256": experiment_receipt_sha256,
                "gate_id": manifest["gate_id"],
                "reason_codes": decision_value["reason_codes"],
                "verified_decision_count": verified["decision_count"],
            }
        if receipt["sequence"] != len(records) + 1:
            raise GateError(
                "P4 requires the next unskipped P3 receipt: "
                f"expected {len(records) + 1}, received {receipt['sequence']}"
            )

        decision = _build_decision(
            store_manifest=manifest,
            ir=ir,
            receipt=receipt,
            receipt_path=receipt_path,
            receipt_digest=experiment_receipt_sha256,
            prefix=prefix,
            report=report,
            report_path=report_path,
            report_digest=report_digest,
        )
        decision_digest = _sha256_bytes(_canonical_bytes(decision))
        decision_path = store_dir / "decisions" / "sha256" / f"{decision_digest}.json"
        indexed_reports = {
            item["evaluator_report_sha256"]
            for item, _path in records
            if item["evaluator_report_sha256"] is not None
        }
        indexed_decisions = {item["decision_sha256"] for item, _path in records}
        indexed_blobs: set[str] = set()
        for item, _path in records:
            prior_report_digest = item["evaluator_report_sha256"]
            if prior_report_digest is None:
                continue
            prior_report, _prior_digest = _immutable_json(
                store_dir / "reports" / "sha256" / f"{prior_report_digest}.json",
                "indexed Evaluator report object",
            )
            indexed_blobs.add(prior_report["evaluator_implementation_sha256"])
        actual_reports = _object_digests(store_dir / "reports" / "sha256", ".json")
        actual_decisions = _object_digests(store_dir / "decisions" / "sha256", ".json")
        actual_blobs = _object_digests(store_dir / "blobs" / "sha256", "")
        allowed_reports = indexed_reports | ({report_digest} if report_digest else set())
        allowed_blobs = indexed_blobs | (
            {report["evaluator_implementation_sha256"]} if report is not None else set()
        )
        if actual_reports not in (indexed_reports, allowed_reports):
            raise GateError("Gate store contains an unrelated unindexed evaluator report")
        if actual_decisions not in (indexed_decisions, indexed_decisions | {decision_digest}):
            raise GateError("Gate store contains an unrelated unindexed decision")
        if actual_blobs not in (indexed_blobs, allowed_blobs):
            raise GateError("Gate store contains an unrelated evaluator implementation blob")
        if report is not None and report_path is not None and report_digest is not None:
            _archive_evaluator(store_dir, ir, report["evaluator_implementation_sha256"])
            _publish_json(report_path, report)
        _publish_json(decision_path, decision)
        record = {
            "decision_path": str(decision_path),
            "decision_sha256": decision_digest,
            "evaluator_report_sha256": report_digest,
            "experiment_receipt_sha256": experiment_receipt_sha256,
            "schema_version": RECORD_VERSION,
        }
        _publish_json(record_path, record)
        verify_store(store_dir=store_dir)
        return {
            "already_decided": False,
            "candidate_accepted": decision["candidate_accepted"],
            "decision": decision["decision"],
            "decision_path": str(decision_path),
            "decision_sha256": decision_digest,
            "experiment_receipt_sha256": experiment_receipt_sha256,
            "gate_id": manifest["gate_id"],
            "reason_codes": decision["reason_codes"],
        }
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MVP-0 P4 deterministic Evidence Gate")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="bind a new Gate store to one complete P3 ledger")
    init.add_argument("--ledger-dir", type=Path, required=True)
    init.add_argument("--store-dir", type=Path, required=True)
    decision = sub.add_parser("decide", help="publish one decision for one Experiment Receipt")
    decision.add_argument("--store-dir", type=Path, required=True)
    decision.add_argument("--experiment-receipt-sha256", required=True)
    decision.add_argument("--evaluator-report", type=Path)
    verify = sub.add_parser("verify", help="replay all Gate decisions")
    verify.add_argument("--store-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            result = initialize_store(ledger_dir=args.ledger_dir, store_dir=args.store_dir)
        elif args.command == "decide":
            result = decide(
                store_dir=args.store_dir,
                experiment_receipt_sha256=args.experiment_receipt_sha256,
                evaluator_report=args.evaluator_report,
            )
        else:
            result = verify_store(store_dir=args.store_dir)
    except (GateError, ledger.LedgerError, worker.AdapterError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
