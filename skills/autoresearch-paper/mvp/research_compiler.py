#!/usr/bin/env python3
"""Compile, validate, review, revise, and freeze Research IR v1.

The module is stdlib-only and deliberately does not import the legacy Harness.
All workflow artifacts are immutable, canonical JSON objects addressed by SHA-256.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    from . import delegated_review
except ImportError:  # pragma: no cover - direct script execution
    import delegated_review  # type: ignore[no-redef]


MVP_ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = MVP_ROOT / "schemas" / "research-ir.schema.json"
COMPILER_PROMPT_PATH = MVP_ROOT / "prompts" / "codex-research-compiler.md"
VALIDATOR_PATH = Path(__file__).resolve()
# P1 originally published this digest from the released v1 compiler module.
# It now names the semantic-validation contract, rather than every workflow
# helper that happens to share this file.  Bump it only when Research IR v1
# validation semantics change, and provide an explicit store migration.
SEMANTIC_VALIDATOR_V1_SHA256 = (
    "31055c87350d76328a9f5b82a185db2a44b7b4c1677260231685ec69a9687eb5"
)
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
PROTECTED_FIELDS = {
    "problem_statement",
    "central_claim",
    "falsification_conditions",
    "related_work_gap",
    "baseline_contract",
    "metric_contract",
    "evaluator_spec",
    "allowed_search_space",
    "experiment_plan",
    "budget",
    "stop_rules",
}
REQUIRED_FINDING_SEVERITIES = {"blocker", "major"}
OWNER_IDENTITY_PREFIX = "owner/"
PROPOSAL_KEYS = {
    "author",
    "compiler_prompt_sha256",
    "record_kind",
    "recorded_at",
    "research_ir_sha256",
    "research_ir_schema_sha256",
}
CRITIQUE_KEYS = {
    "findings",
    "proposal_sha256",
    "record_kind",
    "recorded_at",
    "reviewer",
    "summary",
    "verdict",
}
REVISION_KEYS = {
    "addressed_finding_ids",
    "author",
    "critique_sha256",
    "proposal_sha256",
    "record_kind",
    "recorded_at",
    "research_ir_sha256",
    "summary",
}
RECEIPT_KEYS = {
    "approval_note",
    "approval_scope",
    "approved_at",
    "approved_by",
    "compiler_prompt_sha256",
    "critique_sha256",
    "ir_id",
    "ir_version",
    "proposal_sha256",
    "receipt_kind",
    "research_ir_schema_sha256",
    "research_ir_sha256",
    "revision_sha256",
    "semantic_validator_sha256",
}
DELEGATED_RECEIPT_KEYS = RECEIPT_KEYS | {
    "delegated_review_path",
    "delegated_review_sha256",
}


class CompilerError(RuntimeError):
    """A closed, user-correctable compiler workflow error."""


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str


def semantic_validator_sha256() -> str:
    """Return the stable identifier of the Research IR v1 semantic contract."""

    return SEMANTIC_VALIDATOR_V1_SHA256


def canonical_json_bytes(value: Any) -> bytes:
    """Return one stable JSON representation used for every content hash."""

    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise CompilerError(f"value is not canonical JSON: {exc}") from exc
    return (rendered + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle, parse_constant=_reject_non_finite)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise CompilerError(f"cannot read strict JSON from {path}: {exc}") from exc


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_timestamp(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CompilerError(f"{label} must be a UTC RFC3339 timestamp ending in Z")
    try:
        datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise CompilerError(f"{label} is not a valid RFC3339 timestamp") from exc
    return value


def _parsed_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _assert_time_order(earlier: str, later: str, transition: str) -> None:
    if _parsed_timestamp(later) < _parsed_timestamp(earlier):
        raise CompilerError(f"{transition} timestamp precedes its bound input")


def _recorded_at(value: str | None) -> str:
    return _validate_timestamp(value, "recorded_at") if value else _now()


def _schema() -> dict[str, Any]:
    value = load_json(SCHEMA_PATH)
    if not isinstance(value, dict):
        raise CompilerError("Research IR schema root must be an object")
    return value


def _resolve_ref(root: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise CompilerError(f"only local schema references are supported: {ref}")
    current: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or part not in current:
            raise CompilerError(f"unresolvable schema reference: {ref}")
        current = current[part]
    if not isinstance(current, Mapping):
        raise CompilerError(f"schema reference is not an object: {ref}")
    return current


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise CompilerError(f"unsupported schema type: {expected}")


def _schema_issues(
    value: Any,
    schema: Mapping[str, Any],
    *,
    root: Mapping[str, Any],
    path: str = "$",
) -> list[ValidationIssue]:
    if "$ref" in schema:
        return _schema_issues(value, _resolve_ref(root, schema["$ref"]), root=root, path=path)

    issues: list[ValidationIssue] = []
    expected = schema.get("type")
    if expected is not None:
        choices = [expected] if isinstance(expected, str) else expected
        if not isinstance(choices, list) or not all(isinstance(item, str) for item in choices):
            raise CompilerError(f"invalid type declaration in schema at {path}")
        if not any(_type_matches(value, item) for item in choices):
            return [ValidationIssue("schema.type", path, f"expected type {choices}")]

    if "const" in schema and value != schema["const"]:
        issues.append(ValidationIssue("schema.const", path, f"must equal {schema['const']!r}"))
    if "enum" in schema and value not in schema["enum"]:
        issues.append(ValidationIssue("schema.enum", path, f"must be one of {schema['enum']!r}"))

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            issues.append(ValidationIssue("schema.minLength", path, "string is too short"))
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            issues.append(ValidationIssue("schema.pattern", path, f"does not match {pattern!r}"))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            issues.append(ValidationIssue("schema.minimum", path, f"must be >= {schema['minimum']}"))
        if "maximum" in schema and value > schema["maximum"]:
            issues.append(ValidationIssue("schema.maximum", path, f"must be <= {schema['maximum']}"))

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            issues.append(ValidationIssue("schema.minItems", path, "array has too few items"))
        if schema.get("uniqueItems"):
            keys = [canonical_json_bytes(item) for item in value]
            if len(keys) != len(set(keys)):
                issues.append(ValidationIssue("schema.uniqueItems", path, "array items must be unique"))
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                issues.extend(_schema_issues(item, item_schema, root=root, path=f"{path}[{index}]"))

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for name in required:
            if name not in value:
                issues.append(ValidationIssue("schema.required", f"{path}.{name}", "required property is missing"))
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in properties:
                    issues.append(ValidationIssue("schema.additionalProperties", f"{path}.{name}", "property is not allowed"))
        for name, child_schema in properties.items():
            if name in value and isinstance(child_schema, Mapping):
                issues.extend(_schema_issues(value[name], child_schema, root=root, path=f"{path}.{name}"))

    return issues


def _issue(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(code, path, message)


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _transitive_dependencies(experiments: Mapping[str, Mapping[str, Any]], experiment_id: str) -> set[str]:
    found: set[str] = set()
    stack = list(experiments[experiment_id]["depends_on"])
    while stack:
        current = stack.pop()
        if current in found or current not in experiments:
            continue
        found.add(current)
        stack.extend(experiments[current]["depends_on"])
    return found


def _is_safe_relative_path(value: str) -> bool:
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def validate_research_ir(ir: Any, *, check_paths: bool = False) -> list[ValidationIssue]:
    """Validate shape plus cross-field scientific/execution semantics."""

    schema = _schema()
    issues = _schema_issues(ir, schema, root=schema)
    if issues or not isinstance(ir, dict):
        return issues

    if ir["version"] == 1 and ir["parent_ir_sha256"] is not None:
        issues.append(_issue("semantic.parent", "$.parent_ir_sha256", "version 1 must not have a parent"))
    if ir["version"] > 1 and not isinstance(ir["parent_ir_sha256"], str):
        issues.append(_issue("semantic.parent", "$.parent_ir_sha256", "versions after 1 must bind the prior IR hash"))

    claim = ir["central_claim"]
    baseline = ir["baseline_contract"]
    metrics = ir["metric_contract"]
    primary = metrics["primary_metric"]
    guardrails = metrics["guardrails"]
    metric_ids = [primary["metric_id"], *[item["metric_id"] for item in guardrails]]

    evidence_ids = [item["source_id"] for item in ir["related_work_gap"]["evidence_refs"]]
    if _duplicates(evidence_ids):
        issues.append(_issue("semantic.evidence_id_unique", "$.related_work_gap.evidence_refs", "source_id values must be unique"))

    if claim["baseline_id"] != baseline["baseline_id"]:
        issues.append(_issue("semantic.claim_baseline", "$.central_claim.baseline_id", "claim must reference baseline_contract.baseline_id"))
    if claim["primary_metric_id"] != primary["metric_id"]:
        issues.append(_issue("semantic.claim_metric", "$.central_claim.primary_metric_id", "claim must reference the primary metric"))
    if baseline["status"] == "PLANNED" and baseline["implementation_sha256"] is not None:
        issues.append(_issue("semantic.baseline_planned_hash", "$.baseline_contract.implementation_sha256", "a planned baseline cannot claim an implementation hash"))
    if baseline["status"] == "READY" and not isinstance(baseline["implementation_sha256"], str):
        issues.append(_issue("semantic.baseline_ready_hash", "$.baseline_contract.implementation_sha256", "a ready baseline must bind its implementation hash"))
    for duplicate in sorted(_duplicates(metric_ids)):
        issues.append(_issue("semantic.metric_id_unique", "$.metric_contract", f"duplicate metric_id {duplicate!r}"))

    for location, metric in [("$.metric_contract.primary_metric", primary), *[(f"$.metric_contract.guardrails[{i}]", value) for i, value in enumerate(guardrails)]]:
        acceptance = metric["acceptance"]
        allowed_operators = {">", ">="} if metric["direction"] == "maximize" else {"<", "<="}
        if acceptance["operator"] not in allowed_operators:
            issues.append(_issue("semantic.metric_direction", f"{location}.acceptance.operator", f"operator conflicts with {metric['direction']} direction"))

    falsification_ids = [item["id"] for item in ir["falsification_conditions"]]
    for duplicate in sorted(_duplicates(falsification_ids)):
        issues.append(_issue("semantic.falsification_id_unique", "$.falsification_conditions", f"duplicate id {duplicate!r}"))
    for index, condition in enumerate(ir["falsification_conditions"]):
        if condition["metric_id"] not in metric_ids:
            issues.append(_issue("semantic.falsification_metric", f"$.falsification_conditions[{index}].metric_id", "metric is not declared in metric_contract"))
            continue
        metric = primary if condition["metric_id"] == primary["metric_id"] else next(
            item for item in guardrails if item["metric_id"] == condition["metric_id"]
        )
        rejecting_operators = {"<", "<="} if metric["direction"] == "maximize" else {">", ">="}
        if condition["operator"] not in rejecting_operators:
            issues.append(_issue("semantic.falsification_direction", f"$.falsification_conditions[{index}].operator", f"operator cannot reject a metric with {metric['direction']} direction"))
        if condition["aggregation"] != metric["acceptance"]["aggregation"]:
            issues.append(_issue("semantic.falsification_aggregation", f"$.falsification_conditions[{index}].aggregation", "falsification and acceptance must use the same aggregation"))
    missing_falsification_metrics = set(metric_ids) - {item["metric_id"] for item in ir["falsification_conditions"]}
    if missing_falsification_metrics:
        issues.append(_issue("semantic.falsification_complete", "$.falsification_conditions", f"metrics without a rejection predicate: {sorted(missing_falsification_metrics)}"))

    bindings = ir["evaluator_spec"]["metric_bindings"]
    binding_ids = [item["metric_id"] for item in bindings]
    for duplicate in sorted(_duplicates(binding_ids)):
        issues.append(_issue("semantic.binding_unique", "$.evaluator_spec.metric_bindings", f"duplicate metric binding {duplicate!r}"))
    if set(binding_ids) != set(metric_ids):
        issues.append(_issue("semantic.binding_complete", "$.evaluator_spec.metric_bindings", "bindings must cover exactly the primary metric and all guardrails"))
    if _duplicates(item["json_path"] for item in bindings):
        issues.append(_issue("semantic.binding_path_unique", "$.evaluator_spec.metric_bindings", "each metric must bind a distinct evaluator JSON path"))

    evaluator = ir["evaluator_spec"]
    artifact_path = Path(evaluator["implementation_artifact"])
    if evaluator["status"] == "PLANNED" and evaluator["implementation_sha256"] is not None:
        issues.append(_issue("semantic.evaluator_planned_hash", "$.evaluator_spec.implementation_sha256", "a planned evaluator cannot claim an implementation hash"))
    if evaluator["status"] == "READY" and not isinstance(evaluator["implementation_sha256"], str):
        issues.append(_issue("semantic.evaluator_ready_hash", "$.evaluator_spec.implementation_sha256", "a ready evaluator must bind its implementation hash"))

    search_ids = [item["id"] for item in ir["allowed_search_space"]]
    for duplicate in sorted(_duplicates(search_ids)):
        issues.append(_issue("semantic.search_space_id_unique", "$.allowed_search_space", f"duplicate id {duplicate!r}"))
    for index, entry in enumerate(ir["allowed_search_space"]):
        unsafe_paths = [path for path in entry["paths"] if not _is_safe_relative_path(path)]
        if unsafe_paths:
            issues.append(_issue("semantic.search_space_path", f"$.allowed_search_space[{index}].paths", f"paths must stay relative to code_root: {unsafe_paths}"))

    protected = set(ir["forbidden_changes"])
    missing_protection = PROTECTED_FIELDS - protected
    if missing_protection:
        issues.append(_issue("semantic.protected_fields", "$.forbidden_changes", f"missing protected fields: {sorted(missing_protection)}"))

    experiments = {item["id"]: item for item in ir["experiment_plan"]}
    if len(experiments) != len(ir["experiment_plan"]):
        issues.append(_issue("semantic.experiment_id_unique", "$.experiment_plan", "experiment ids must be unique"))
    for index, experiment in enumerate(ir["experiment_plan"]):
        for dependency in experiment["depends_on"]:
            if dependency not in experiments:
                issues.append(_issue("semantic.unknown_dependency", f"$.experiment_plan[{index}].depends_on", f"unknown dependency {dependency!r}"))
            elif dependency == experiment["id"]:
                issues.append(_issue("semantic.self_dependency", f"$.experiment_plan[{index}].depends_on", "experiment cannot depend on itself"))
        unknown_search = set(experiment["search_space_ids"]) - set(search_ids)
        if unknown_search:
            issues.append(_issue("semantic.unknown_search_space", f"$.experiment_plan[{index}].search_space_ids", f"unknown ids: {sorted(unknown_search)}"))
        unknown_falsification = set(experiment["falsification_condition_ids"]) - set(falsification_ids)
        if unknown_falsification:
            issues.append(_issue("semantic.unknown_falsification", f"$.experiment_plan[{index}].falsification_condition_ids", f"unknown ids: {sorted(unknown_falsification)}"))
        unsafe_outputs = [path for path in experiment["expected_artifacts"] if not _is_safe_relative_path(path)]
        if unsafe_outputs:
            issues.append(_issue("semantic.expected_artifact_path", f"$.experiment_plan[{index}].expected_artifacts", f"artifacts must stay relative to code_root: {unsafe_outputs}"))

    for experiment_id in experiments:
        if experiment_id in _transitive_dependencies(experiments, experiment_id):
            issues.append(_issue("semantic.dependency_cycle", "$.experiment_plan", f"dependency cycle includes {experiment_id!r}"))

    baseline_experiments = [item for item in ir["experiment_plan"] if item["stage"] == "BASELINE"]
    method_experiments = [item for item in ir["experiment_plan"] if item["stage"] == "METHOD"]
    if not baseline_experiments:
        issues.append(_issue("semantic.baseline_experiment", "$.experiment_plan", "at least one BASELINE experiment is required"))
    if not method_experiments:
        issues.append(_issue("semantic.method_experiment", "$.experiment_plan", "at least one METHOD experiment is required"))
    baseline_ids = {item["id"] for item in baseline_experiments}
    for experiment in method_experiments:
        if not (_transitive_dependencies(experiments, experiment["id"]) & baseline_ids):
            issues.append(_issue("semantic.baseline_gate", "$.experiment_plan", f"method {experiment['id']!r} must transitively depend on a BASELINE experiment"))

    evaluator_builds = [item for item in ir["experiment_plan"] if item["stage"] == "EVALUATOR_BUILD"]
    if evaluator["status"] == "PLANNED":
        if len(evaluator_builds) != 1:
            issues.append(_issue("semantic.evaluator_build_count", "$.experiment_plan", "a planned evaluator requires exactly one EVALUATOR_BUILD experiment"))
        else:
            build_id = evaluator_builds[0]["id"]
            if evaluator_builds[0]["depends_on"]:
                issues.append(_issue("semantic.evaluator_build_first", "$.experiment_plan", "EVALUATOR_BUILD must have no dependencies"))
            for experiment in ir["experiment_plan"]:
                if experiment["id"] != build_id and build_id not in _transitive_dependencies(experiments, experiment["id"]):
                    issues.append(_issue("semantic.evaluator_gate", "$.experiment_plan", f"{experiment['id']!r} must transitively depend on {build_id!r}"))

    if ir["budget"]["max_experiments"] < len(ir["experiment_plan"]):
        issues.append(_issue("semantic.experiment_budget", "$.budget.max_experiments", "budget is smaller than the frozen initial experiment plan"))
    if ir["budget"]["max_failed_experiments"] > ir["budget"]["max_experiments"]:
        issues.append(_issue("semantic.failure_budget", "$.budget.max_failed_experiments", "failed experiment budget cannot exceed max_experiments"))
    stop_ids = [item["id"] for item in ir["stop_rules"]]
    if _duplicates(stop_ids):
        issues.append(_issue("semantic.stop_id_unique", "$.stop_rules", "stop rule ids must be unique"))
    actions = {item["action"] for item in ir["stop_rules"]}
    if "STOP" not in actions or "RECOMPILE" not in actions:
        issues.append(_issue("semantic.stop_coverage", "$.stop_rules", "stop rules must include both STOP and RECOMPILE"))

    if check_paths:
        source = ir["source"]
        for label in ("workspace_root", "code_root"):
            path = Path(source[label])
            if not path.is_absolute() or not path.exists():
                issues.append(_issue("semantic.path", f"$.source.{label}", "must be an existing absolute path"))
        brief = source["brief_artifact"]
        brief_path = Path(brief["path"])
        if not brief_path.is_file():
            issues.append(_issue("semantic.path", "$.source.brief_artifact.path", "source brief must be an existing file"))
        elif sha256_file(brief_path) != brief["sha256"]:
            issues.append(_issue("semantic.source_brief_hash", "$.source.brief_artifact.sha256", "source brief bytes do not match the declared hash"))
        working_directory = Path(evaluator["working_directory"])
        if not working_directory.is_absolute() or not working_directory.is_dir():
            issues.append(_issue("semantic.path", "$.evaluator_spec.working_directory", "must be an existing absolute directory"))
        for index, artifact in enumerate(baseline["source_artifacts"]):
            path = Path(artifact["path"])
            if not path.is_absolute() or not path.is_file():
                issues.append(_issue("semantic.path", f"$.baseline_contract.source_artifacts[{index}]", "must be an existing absolute path"))
            elif sha256_file(path) != artifact["sha256"]:
                issues.append(_issue("semantic.baseline_hash", f"$.baseline_contract.source_artifacts[{index}].sha256", "baseline source bytes do not match the declared hash"))
        if baseline["status"] == "READY":
            baseline_path = Path(baseline["implementation_artifact"])
            if not baseline_path.is_file():
                issues.append(_issue("semantic.path", "$.baseline_contract.implementation_artifact", "ready baseline artifact does not exist"))
            elif sha256_file(baseline_path) != baseline["implementation_sha256"]:
                issues.append(_issue("semantic.baseline_implementation_hash", "$.baseline_contract.implementation_sha256", "ready baseline bytes do not match the declared hash"))
        for index, evidence in enumerate(ir["related_work_gap"]["evidence_refs"]):
            locator = evidence["locator"]
            if locator.startswith("/"):
                evidence_path = Path(locator)
                if not evidence_path.is_file():
                    issues.append(_issue("semantic.path", f"$.related_work_gap.evidence_refs[{index}].locator", "local evidence must be an existing file"))
                elif evidence["sha256"] is None:
                    issues.append(_issue("semantic.evidence_hash", f"$.related_work_gap.evidence_refs[{index}].sha256", "local evidence must bind a SHA-256 digest"))
                elif sha256_file(evidence_path) != evidence["sha256"]:
                    issues.append(_issue("semantic.evidence_hash", f"$.related_work_gap.evidence_refs[{index}].sha256", "local evidence bytes do not match the declared hash"))
        if evaluator["status"] == "READY":
            if not artifact_path.is_file():
                issues.append(_issue("semantic.path", "$.evaluator_spec.implementation_artifact", "ready evaluator artifact does not exist"))
            elif sha256_file(artifact_path) != evaluator["implementation_sha256"]:
                issues.append(_issue("semantic.evaluator_hash", "$.evaluator_spec.implementation_sha256", "ready evaluator bytes do not match the declared hash"))

    return issues


def _assert_valid_ir(ir: Any, *, check_paths: bool = False) -> None:
    issues = validate_research_ir(ir, check_paths=check_paths)
    if issues:
        summary = "; ".join(f"{issue.code} at {issue.path}: {issue.message}" for issue in issues[:8])
        raise CompilerError(f"Research IR is invalid: {summary}")


def _object_path(store: Path, digest: str) -> Path:
    if HASH_RE.fullmatch(digest) is None:
        raise CompilerError(f"invalid SHA-256 digest: {digest!r}")
    return store / "objects" / "sha256" / f"{digest}.json"


def _receipt_path(store: Path, digest: str) -> Path:
    if HASH_RE.fullmatch(digest) is None:
        raise CompilerError(f"invalid SHA-256 digest: {digest!r}")
    return store / "receipts" / "sha256" / f"{digest}.json"


def _atomic_publish(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise CompilerError(f"content-address collision at {path}")
        return path
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o444)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise CompilerError(f"content-address collision at {path}")
        finally:
            temporary.unlink(missing_ok=True)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return path


def publish_object(store: Path, value: Any) -> tuple[str, Path]:
    payload = canonical_json_bytes(value)
    digest = sha256_bytes(payload)
    return digest, _atomic_publish(_object_path(store, digest), payload)


def publish_receipt(store: Path, value: Any) -> tuple[str, Path]:
    payload = canonical_json_bytes(value)
    digest = sha256_bytes(payload)
    return digest, _atomic_publish(_receipt_path(store, digest), payload)


def _load_addressed(path: Path, *, expected_kind: str | None = None) -> tuple[dict[str, Any], str]:
    value = load_json(path)
    if not isinstance(value, dict):
        raise CompilerError(f"addressed JSON root must be an object: {path}")
    canonical = canonical_json_bytes(value)
    if path.read_bytes() != canonical:
        raise CompilerError(f"addressed object is not canonical JSON: {path}")
    digest = sha256_bytes(canonical)
    if expected_kind and value.get("record_kind") != expected_kind:
        raise CompilerError(f"expected {expected_kind!r}, got {value.get('record_kind')!r}")
    return value, digest


def _load_object(store: Path, digest: str, *, expected_kind: str | None = None) -> dict[str, Any]:
    value, actual = _load_addressed(_object_path(store, digest), expected_kind=expected_kind)
    if actual != digest:
        raise CompilerError(f"object path digest mismatch for {digest}")
    return value


def _exact_keys(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    actual = set(value)
    if actual != keys:
        raise CompilerError(f"{label} keys must be exactly {sorted(keys)}; got {sorted(actual)}")


def _identity(value: str, label: str) -> str:
    if not isinstance(value, str) or len(value.strip()) < 3:
        raise CompilerError(f"{label} must be a non-empty recorded identity")
    return value.strip()


def _require_owner_identity(value: str, label: str) -> str:
    identity = _identity(value, label)
    if not identity.startswith(OWNER_IDENTITY_PREFIX) or len(identity) == len(OWNER_IDENTITY_PREFIX):
        raise CompilerError(f"{label} must use the owner/<identity> namespace")
    return identity


def _require_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise CompilerError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _validate_proposal_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CompilerError("proposal record must be an object")
    _exact_keys(value, PROPOSAL_KEYS, "proposal record")
    if value["record_kind"] != "research-ir-proposal/v1":
        raise CompilerError("unsupported proposal record kind")
    _identity(value["author"], "proposal author")
    _validate_timestamp(value["recorded_at"], "proposal recorded_at")
    for field in ("compiler_prompt_sha256", "research_ir_sha256", "research_ir_schema_sha256"):
        _require_hash(value[field], f"proposal {field}")
    return value


def _validate_critique_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CompilerError("critique record must be an object")
    _exact_keys(value, CRITIQUE_KEYS, "critique record")
    if value["record_kind"] != "research-ir-critique/v1":
        raise CompilerError("unsupported critique record kind")
    _require_hash(value["proposal_sha256"], "critique proposal_sha256")
    _identity(value["reviewer"], "critique reviewer")
    _validate_timestamp(value["recorded_at"], "critique recorded_at")
    _validate_critique_input(
        {"summary": value["summary"], "verdict": value["verdict"], "findings": value["findings"]}
    )
    return value


def _validate_revision_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CompilerError("revision record must be an object")
    _exact_keys(value, REVISION_KEYS, "revision record")
    if value["record_kind"] != "research-ir-revision/v1":
        raise CompilerError("unsupported revision record kind")
    for field in ("proposal_sha256", "critique_sha256", "research_ir_sha256"):
        _require_hash(value[field], f"revision {field}")
    _identity(value["author"], "revision author")
    _validate_timestamp(value["recorded_at"], "revision recorded_at")
    if not isinstance(value["summary"], str) or len(value["summary"].strip()) < 12:
        raise CompilerError("revision summary is too short")
    addressed = value["addressed_finding_ids"]
    if not isinstance(addressed, list) or not all(isinstance(item, str) for item in addressed) or _duplicates(addressed):
        raise CompilerError("revision addressed_finding_ids must contain unique strings")
    return value


def _assert_revision_addresses_critique(revision: Mapping[str, Any], critique_record: Mapping[str, Any]) -> None:
    known = {finding["finding_id"] for finding in critique_record["findings"]}
    required = {
        finding["finding_id"]
        for finding in critique_record["findings"]
        if finding["severity"] in REQUIRED_FINDING_SEVERITIES
    }
    addressed = set(revision["addressed_finding_ids"])
    unknown = addressed - known
    if unknown:
        raise CompilerError(f"revision claims unknown critique findings: {sorted(unknown)}")
    missing = required - addressed
    if missing:
        raise CompilerError(f"revision did not address required findings: {sorted(missing)}")


def _validate_receipt(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CompilerError("freeze receipt must be an object")
    receipt_kind = value.get("receipt_kind")
    expected_keys = (
        DELEGATED_RECEIPT_KEYS
        if receipt_kind == "research-ir-freeze/v2"
        else RECEIPT_KEYS
    )
    _exact_keys(value, expected_keys, "freeze receipt")
    if receipt_kind not in {"research-ir-freeze/v1", "research-ir-freeze/v2"}:
        raise CompilerError("unsupported freeze receipt kind")
    for field in (
        "compiler_prompt_sha256",
        "critique_sha256",
        "proposal_sha256",
        "research_ir_schema_sha256",
        "research_ir_sha256",
        "revision_sha256",
        "semantic_validator_sha256",
    ):
        _require_hash(value[field], f"freeze receipt {field}")
    _identity(value["approved_by"], "freeze approver")
    _validate_timestamp(value["approved_at"], "freeze approved_at")
    if value["approval_scope"] not in {
        "ENGINEERING_ACCEPTANCE",
        "OWNER_REVIEWED",
        "DELEGATED_ENGINEERING_REVIEW",
    }:
        raise CompilerError("freeze receipt has an invalid approval_scope")
    if value["approval_scope"] == "DELEGATED_ENGINEERING_REVIEW":
        if receipt_kind != "research-ir-freeze/v2":
            raise CompilerError("delegated freeze must use receipt v2")
        _require_hash(value["delegated_review_sha256"], "delegated review SHA-256")
        if not isinstance(value["delegated_review_path"], str) or not Path(value["delegated_review_path"]).is_absolute():
            raise CompilerError("delegated review path must be absolute")
    elif receipt_kind != "research-ir-freeze/v1":
        raise CompilerError("non-delegated freeze must use receipt v1")
    if not isinstance(value["approval_note"], str) or len(value["approval_note"].strip()) < 12:
        raise CompilerError("freeze receipt approval_note is too short")
    if not isinstance(value["ir_id"], str) or ID_RE.fullmatch(value["ir_id"]) is None:
        raise CompilerError("freeze receipt has an invalid ir_id")
    if not isinstance(value["ir_version"], int) or isinstance(value["ir_version"], bool) or value["ir_version"] < 1:
        raise CompilerError("freeze receipt has an invalid ir_version")
    return value


def propose(*, ir_path: Path, store: Path, author: str, recorded_at: str | None = None) -> dict[str, str]:
    ir = load_json(ir_path)
    _assert_valid_ir(ir, check_paths=True)
    ir_digest, ir_object = publish_object(store, ir)
    record = {
        "author": _identity(author, "author"),
        "compiler_prompt_sha256": sha256_file(COMPILER_PROMPT_PATH),
        "record_kind": "research-ir-proposal/v1",
        "recorded_at": _recorded_at(recorded_at),
        "research_ir_sha256": ir_digest,
        "research_ir_schema_sha256": sha256_file(SCHEMA_PATH),
    }
    digest, path = publish_object(store, record)
    return {"stage": "AWAITING_HUMAN_CRITIQUE", "proposal_sha256": digest, "proposal_path": str(path), "research_ir_sha256": ir_digest, "research_ir_path": str(ir_object)}


def _validate_critique_input(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CompilerError("critique input must be an object")
    _exact_keys(value, {"summary", "verdict", "findings"}, "critique input")
    if value["verdict"] not in {"ACCEPT", "REVISE"}:
        raise CompilerError("critique verdict must be ACCEPT or REVISE")
    if not isinstance(value["summary"], str) or len(value["summary"].strip()) < 12:
        raise CompilerError("critique summary is too short")
    if not isinstance(value["findings"], list):
        raise CompilerError("critique findings must be an array")
    finding_ids: list[str] = []
    for index, finding in enumerate(value["findings"]):
        if not isinstance(finding, dict):
            raise CompilerError(f"critique finding {index} must be an object")
        _exact_keys(finding, {"finding_id", "severity", "path", "message", "required_change"}, f"critique finding {index}")
        finding_id = finding["finding_id"]
        if not isinstance(finding_id, str) or ID_RE.fullmatch(finding_id) is None:
            raise CompilerError(f"critique finding {index} has an invalid finding_id")
        if finding["severity"] not in {"blocker", "major", "minor", "note"}:
            raise CompilerError(f"critique finding {index} has an invalid severity")
        for field in ("path", "message", "required_change"):
            if not isinstance(finding[field], str) or not finding[field].strip():
                raise CompilerError(f"critique finding {index}.{field} must be non-empty")
        finding_ids.append(finding_id)
    if _duplicates(finding_ids):
        raise CompilerError("critique finding_id values must be unique")
    if value["verdict"] == "ACCEPT" and any(item["severity"] in REQUIRED_FINDING_SEVERITIES for item in value["findings"]):
        raise CompilerError("ACCEPT critique cannot contain blocker or major findings")
    if value["verdict"] == "REVISE" and not value["findings"]:
        raise CompilerError("REVISE critique must contain at least one finding")
    return value


def critique(*, proposal_path: Path, critique_path: Path, store: Path, reviewer: str, recorded_at: str | None = None) -> dict[str, str]:
    proposal, proposal_digest = _load_addressed(proposal_path, expected_kind="research-ir-proposal/v1")
    _validate_proposal_record(proposal)
    _load_object(store, proposal_digest, expected_kind="research-ir-proposal/v1")
    _load_object(store, proposal["research_ir_sha256"])
    reviewer_id = _identity(reviewer, "reviewer")
    if reviewer_id == proposal["author"]:
        raise CompilerError("reviewer identity must differ from proposal author")
    critique_input = _validate_critique_input(load_json(critique_path))
    critique_time = _recorded_at(recorded_at)
    _assert_time_order(proposal["recorded_at"], critique_time, "critique")
    record = {
        "findings": critique_input["findings"],
        "proposal_sha256": proposal_digest,
        "record_kind": "research-ir-critique/v1",
        "recorded_at": critique_time,
        "reviewer": reviewer_id,
        "summary": critique_input["summary"],
        "verdict": critique_input["verdict"],
    }
    digest, path = publish_object(store, record)
    return {"stage": "CRITIQUED", "critique_sha256": digest, "critique_path": str(path), "proposal_sha256": proposal_digest}


def _validate_revision_input(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CompilerError("revision input must be an object")
    _exact_keys(value, {"changes", "summary", "addressed_finding_ids"}, "revision input")
    if not isinstance(value["summary"], str) or len(value["summary"].strip()) < 12:
        raise CompilerError("revision summary is too short")
    ids = value["addressed_finding_ids"]
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids) or _duplicates(ids):
        raise CompilerError("addressed_finding_ids must be an array of unique strings")
    changes = value["changes"]
    if not isinstance(changes, list) or not changes:
        raise CompilerError("revision changes must contain at least one explicit JSON Pointer operation")
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            raise CompilerError(f"revision change {index} must be an object")
        _exact_keys(change, {"op", "path", "value"}, f"revision change {index}")
        if change["op"] not in {"add", "replace", "remove"}:
            raise CompilerError(f"revision change {index}.op must be add, replace, or remove")
        if not isinstance(change["path"], str) or not change["path"].startswith("/"):
            raise CompilerError(f"revision change {index}.path must be a non-root JSON Pointer")
        if change["op"] == "remove" and change["value"] is not None:
            raise CompilerError(f"revision change {index}.value must be null for remove")
    return value


def _pointer_parts(pointer: str) -> list[str]:
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _apply_revision_changes(proposed_ir: Mapping[str, Any], changes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    revised = copy.deepcopy(proposed_ir)
    for index, change in enumerate(changes):
        parts = _pointer_parts(change["path"])
        if not parts:
            raise CompilerError(f"revision change {index} cannot replace the IR root")
        parent: Any = revised
        for part in parts[:-1]:
            if isinstance(parent, dict):
                if part not in parent:
                    raise CompilerError(f"revision change {index} has an unknown path segment {part!r}")
                parent = parent[part]
            elif isinstance(parent, list):
                try:
                    list_index = int(part)
                    parent = parent[list_index]
                except (ValueError, IndexError) as exc:
                    raise CompilerError(f"revision change {index} has an invalid array index {part!r}") from exc
            else:
                raise CompilerError(f"revision change {index} traverses through a scalar value")
        leaf = parts[-1]
        operation = change["op"]
        if isinstance(parent, dict):
            exists = leaf in parent
            if operation == "add":
                if exists:
                    raise CompilerError(f"revision change {index} add target already exists")
                parent[leaf] = copy.deepcopy(change["value"])
            elif operation == "replace":
                if not exists:
                    raise CompilerError(f"revision change {index} replace target does not exist")
                parent[leaf] = copy.deepcopy(change["value"])
            else:
                if not exists:
                    raise CompilerError(f"revision change {index} remove target does not exist")
                del parent[leaf]
        elif isinstance(parent, list):
            if operation == "add" and leaf == "-":
                parent.append(copy.deepcopy(change["value"]))
                continue
            try:
                list_index = int(leaf)
            except ValueError as exc:
                raise CompilerError(f"revision change {index} has an invalid array index {leaf!r}") from exc
            if operation == "add":
                if list_index < 0 or list_index > len(parent):
                    raise CompilerError(f"revision change {index} add index is out of range")
                parent.insert(list_index, copy.deepcopy(change["value"]))
            elif operation == "replace":
                if list_index < 0 or list_index >= len(parent):
                    raise CompilerError(f"revision change {index} replace index is out of range")
                parent[list_index] = copy.deepcopy(change["value"])
            else:
                if list_index < 0 or list_index >= len(parent):
                    raise CompilerError(f"revision change {index} remove index is out of range")
                del parent[list_index]
        else:
            raise CompilerError(f"revision change {index} target parent is not a container")
    return revised


def revise(
    *,
    proposal_path: Path,
    critique_record_path: Path,
    revision_path: Path,
    store: Path,
    author: str,
    recorded_at: str | None = None,
) -> dict[str, str]:
    proposal, proposal_digest = _load_addressed(proposal_path, expected_kind="research-ir-proposal/v1")
    critique_record, critique_digest = _load_addressed(critique_record_path, expected_kind="research-ir-critique/v1")
    _validate_proposal_record(proposal)
    _validate_critique_record(critique_record)
    _load_object(store, proposal_digest, expected_kind="research-ir-proposal/v1")
    _load_object(store, critique_digest, expected_kind="research-ir-critique/v1")
    if critique_record["proposal_sha256"] != proposal_digest:
        raise CompilerError("critique is not bound to the supplied proposal")
    if critique_record["verdict"] != "REVISE":
        raise CompilerError("revision requires a REVISE critique")
    revision_input = _validate_revision_input(load_json(revision_path))
    proposed_ir = _load_object(store, proposal["research_ir_sha256"])
    revised_ir = _apply_revision_changes(proposed_ir, revision_input["changes"])
    _assert_valid_ir(revised_ir, check_paths=True)
    for field in ("ir_id", "version", "parent_ir_sha256"):
        if revised_ir[field] != proposed_ir[field]:
            raise CompilerError(f"pre-freeze revision cannot change {field}")
    addressed = set(revision_input["addressed_finding_ids"])
    _assert_revision_addresses_critique({"addressed_finding_ids": list(addressed)}, critique_record)
    revised_ir_digest, revised_ir_object = publish_object(store, revised_ir)
    author_id = _identity(author, "author")
    revision_time = _recorded_at(recorded_at)
    _assert_time_order(critique_record["recorded_at"], revision_time, "revision")
    record = {
        "addressed_finding_ids": sorted(addressed),
        "author": author_id,
        "critique_sha256": critique_digest,
        "proposal_sha256": proposal_digest,
        "record_kind": "research-ir-revision/v1",
        "recorded_at": revision_time,
        "research_ir_sha256": revised_ir_digest,
        "summary": revision_input["summary"],
    }
    digest, path = publish_object(store, record)
    return {"stage": "AWAITING_HUMAN_APPROVAL", "revision_sha256": digest, "revision_path": str(path), "research_ir_sha256": revised_ir_digest, "research_ir_path": str(revised_ir_object)}


def confirm_revision(
    *,
    proposal_path: Path,
    critique_record_path: Path,
    store: Path,
    author: str,
    summary: str,
    recorded_at: str | None = None,
) -> dict[str, str]:
    """Publish a byte-identical revision after an independent ACCEPT critique.

    P6 still records proposal -> critique -> revision -> freeze.  An accepted
    execution-only proposal does not need a fabricated JSON edit merely to
    satisfy the lineage shape, so this confirmation record binds the exact
    proposed IR bytes without changing them.
    """

    proposal, proposal_digest = _load_addressed(
        proposal_path, expected_kind="research-ir-proposal/v1"
    )
    critique_record, critique_digest = _load_addressed(
        critique_record_path, expected_kind="research-ir-critique/v1"
    )
    _validate_proposal_record(proposal)
    _validate_critique_record(critique_record)
    _load_object(store, proposal_digest, expected_kind="research-ir-proposal/v1")
    _load_object(store, critique_digest, expected_kind="research-ir-critique/v1")
    if critique_record["proposal_sha256"] != proposal_digest:
        raise CompilerError("critique is not bound to the supplied proposal")
    if critique_record["verdict"] != "ACCEPT":
        raise CompilerError("confirmation revision requires an ACCEPT critique")
    author_id = _identity(author, "author")
    if author_id in {proposal["author"], critique_record["reviewer"]}:
        raise CompilerError("confirmation revision author must be independent")
    if not isinstance(summary, str) or len(summary.strip()) < 12:
        raise CompilerError("confirmation revision summary is too short")
    revision_time = _recorded_at(recorded_at)
    _assert_time_order(critique_record["recorded_at"], revision_time, "revision")
    ir = _load_object(store, proposal["research_ir_sha256"])
    _assert_valid_ir(ir, check_paths=True)
    record = {
        "addressed_finding_ids": [],
        "author": author_id,
        "critique_sha256": critique_digest,
        "proposal_sha256": proposal_digest,
        "record_kind": "research-ir-revision/v1",
        "recorded_at": revision_time,
        "research_ir_sha256": proposal["research_ir_sha256"],
        "summary": summary.strip(),
    }
    digest, path = publish_object(store, record)
    return {
        "stage": "AWAITING_DELEGATED_APPROVAL",
        "revision_sha256": digest,
        "revision_path": str(path),
        "research_ir_sha256": proposal["research_ir_sha256"],
        "research_ir_path": str(_object_path(store, proposal["research_ir_sha256"])),
    }


def freeze(
    *,
    revision_path: Path,
    store: Path,
    approved_by: str,
    approval_scope: str,
    approval_note: str,
    approved_at: str | None = None,
    engineering_test: bool = False,
    delegated_review_receipt: Path | None = None,
) -> dict[str, str]:
    revision, revision_digest = _load_addressed(revision_path, expected_kind="research-ir-revision/v1")
    _validate_revision_record(revision)
    _load_object(store, revision_digest, expected_kind="research-ir-revision/v1")
    proposal = _load_object(store, revision["proposal_sha256"], expected_kind="research-ir-proposal/v1")
    critique_record = _load_object(store, revision["critique_sha256"], expected_kind="research-ir-critique/v1")
    _validate_proposal_record(proposal)
    _validate_critique_record(critique_record)
    if critique_record["reviewer"] == proposal["author"]:
        raise CompilerError("reviewer identity must differ from proposal author")
    if critique_record["proposal_sha256"] != revision["proposal_sha256"]:
        raise CompilerError("revision chain contains a critique/proposal binding mismatch")
    ir = _load_object(store, revision["research_ir_sha256"])
    _assert_valid_ir(ir, check_paths=True)
    proposed_ir = _load_object(store, proposal["research_ir_sha256"])
    for field in ("ir_id", "version", "parent_ir_sha256"):
        if ir[field] != proposed_ir[field]:
            raise CompilerError(f"freeze revision illegally changed {field}")
    if proposal["research_ir_schema_sha256"] != sha256_file(SCHEMA_PATH):
        raise CompilerError("proposal was compiled against a different Research IR schema")
    if proposal["compiler_prompt_sha256"] != sha256_file(COMPILER_PROMPT_PATH):
        raise CompilerError("proposal was compiled with a different Codex compiler prompt")
    approver = _identity(approved_by, "approved_by")
    if approval_scope not in {
        "ENGINEERING_ACCEPTANCE",
        "OWNER_REVIEWED",
        "DELEGATED_ENGINEERING_REVIEW",
    }:
        raise CompilerError(
            "approval_scope must be ENGINEERING_ACCEPTANCE, OWNER_REVIEWED, or DELEGATED_ENGINEERING_REVIEW"
        )
    delegated_record: dict[str, Any] | None = None
    delegated_digest: str | None = None
    if approval_scope == "DELEGATED_ENGINEERING_REVIEW":
        if delegated_review_receipt is None:
            raise CompilerError("delegated freeze requires a delegated review receipt")
        if critique_record["verdict"] != "ACCEPT":
            raise CompilerError("delegated freeze must descend from an ACCEPT critique")
        if revision["research_ir_sha256"] != proposal["research_ir_sha256"]:
            raise CompilerError("delegated confirmation revision must preserve the accepted proposal bytes")
        if revision["addressed_finding_ids"]:
            raise CompilerError("delegated confirmation revision cannot claim addressed findings")
        try:
            delegated_result = delegated_review.verify_review(
                receipt_path=delegated_review_receipt
            )
        except delegated_review.DelegatedReviewError as exc:
            raise CompilerError(f"delegated review replay failed: {exc}") from exc
        delegated_record = load_json(delegated_review_receipt)
        delegated_digest = delegated_result["review_receipt_sha256"]
        expected_identities = {
            "compiler_author": proposal["author"],
            "reviewer": critique_record["reviewer"],
            "revision_author": revision["author"],
            "approver": approver,
        }
        for field, expected in expected_identities.items():
            if delegated_record.get(field) != expected:
                raise CompilerError(f"delegated review {field} does not bind the compiler lineage")
        if delegated_record.get("child_ir_sha256") != revision["research_ir_sha256"]:
            raise CompilerError("delegated review binds a different child Research IR")
    elif delegated_review_receipt is not None:
        raise CompilerError("delegated review receipt is only valid for delegated approval")
    else:
        if critique_record["verdict"] != "REVISE":
            raise CompilerError("freeze revision must descend from a REVISE critique")
        _assert_revision_addresses_critique(revision, critique_record)
    if approval_scope == "ENGINEERING_ACCEPTANCE":
        if not engineering_test:
            raise CompilerError("ENGINEERING_ACCEPTANCE is test-only and requires the explicit engineering_test flag")
        if approver in {proposal["author"], critique_record["reviewer"], revision["author"]}:
            raise CompilerError("engineering approver identity must be independent from proposal, critique, and revision identities")
    elif approval_scope == "OWNER_REVIEWED":
        _require_owner_identity(critique_record["reviewer"], "OWNER_REVIEWED critique reviewer")
        _require_owner_identity(approver, "OWNER_REVIEWED approver")
        if approver in {proposal["author"], revision["author"]}:
            raise CompilerError("owner approver identity must differ from proposal and revision author identities")
    elif approver in {proposal["author"], critique_record["reviewer"], revision["author"]}:
        raise CompilerError("delegated approver identity must be independent from proposal, critique, and revision identities")
    if not isinstance(approval_note, str) or len(approval_note.strip()) < 12:
        raise CompilerError("approval_note must explain the approval boundary")
    approval_time = _recorded_at(approved_at)
    _assert_time_order(revision["recorded_at"], approval_time, "approval")
    if delegated_record is not None:
        _assert_time_order(delegated_record["reviewed_at"], approval_time, "approval")
    receipt = {
        "approval_note": approval_note.strip(),
        "approval_scope": approval_scope,
        "approved_at": approval_time,
        "approved_by": approver,
        "compiler_prompt_sha256": proposal["compiler_prompt_sha256"],
        "critique_sha256": revision["critique_sha256"],
        "ir_id": ir["ir_id"],
        "ir_version": ir["version"],
        "proposal_sha256": revision["proposal_sha256"],
        "receipt_kind": (
            "research-ir-freeze/v2"
            if approval_scope == "DELEGATED_ENGINEERING_REVIEW"
            else "research-ir-freeze/v1"
        ),
        "research_ir_schema_sha256": sha256_file(SCHEMA_PATH),
        "research_ir_sha256": revision["research_ir_sha256"],
        "revision_sha256": revision_digest,
        "semantic_validator_sha256": semantic_validator_sha256(),
    }
    if delegated_record is not None and delegated_digest is not None:
        receipt["delegated_review_path"] = str(delegated_review_receipt.resolve())
        receipt["delegated_review_sha256"] = delegated_digest
    digest, path = publish_receipt(store, receipt)
    return {"stage": "FROZEN", "freeze_receipt_sha256": digest, "freeze_receipt_path": str(path), "research_ir_sha256": revision["research_ir_sha256"], "research_ir_path": str(_object_path(store, revision["research_ir_sha256"])), "approval_scope": approval_scope}


def verify_freeze(*, receipt_path: Path, store: Path, check_paths: bool = False) -> dict[str, str]:
    receipt, receipt_digest = _load_addressed(receipt_path, expected_kind=None)
    _validate_receipt(receipt)
    if receipt["research_ir_schema_sha256"] != sha256_file(SCHEMA_PATH):
        raise CompilerError("freeze receipt was created with a different Research IR schema")
    if receipt["compiler_prompt_sha256"] != sha256_file(COMPILER_PROMPT_PATH):
        raise CompilerError("freeze receipt was created with a different Codex compiler prompt")
    if receipt["semantic_validator_sha256"] != semantic_validator_sha256():
        raise CompilerError("freeze receipt was created with a different semantic validator")
    if receipt_path.resolve() != _receipt_path(store, receipt_digest).resolve():
        raise CompilerError("freeze receipt is not located at its content address in the supplied store")
    proposal = _load_object(store, receipt["proposal_sha256"], expected_kind="research-ir-proposal/v1")
    critique_record = _load_object(store, receipt["critique_sha256"], expected_kind="research-ir-critique/v1")
    revision = _load_object(store, receipt["revision_sha256"], expected_kind="research-ir-revision/v1")
    _validate_proposal_record(proposal)
    _validate_critique_record(critique_record)
    _validate_revision_record(revision)
    if critique_record["reviewer"] == proposal["author"]:
        raise CompilerError("freeze reviewer identity matches the proposal author")
    if receipt["approval_scope"] == "OWNER_REVIEWED":
        _require_owner_identity(critique_record["reviewer"], "OWNER_REVIEWED critique reviewer")
        _require_owner_identity(receipt["approved_by"], "OWNER_REVIEWED approver")
        if receipt["approved_by"] in {proposal["author"], revision["author"]}:
            raise CompilerError("owner freeze approver identity matches an AI author identity")
    elif receipt["approved_by"] in {proposal["author"], critique_record["reviewer"], revision["author"]}:
        raise CompilerError("engineering freeze approver identity is not independent")
    ir = _load_object(store, receipt["research_ir_sha256"])
    if critique_record["proposal_sha256"] != receipt["proposal_sha256"]:
        raise CompilerError("freeze critique does not bind the freeze proposal")
    if revision["proposal_sha256"] != receipt["proposal_sha256"] or revision["critique_sha256"] != receipt["critique_sha256"]:
        raise CompilerError("freeze revision lineage is inconsistent")
    if revision["research_ir_sha256"] != receipt["research_ir_sha256"]:
        raise CompilerError("freeze revision points to a different Research IR")
    delegated_record: dict[str, Any] | None = None
    if receipt["approval_scope"] == "DELEGATED_ENGINEERING_REVIEW":
        if critique_record["verdict"] != "ACCEPT":
            raise CompilerError("delegated freeze must descend from an ACCEPT critique")
        if revision["research_ir_sha256"] != proposal["research_ir_sha256"]:
            raise CompilerError("delegated confirmation revision changed the accepted proposal bytes")
        if revision["addressed_finding_ids"]:
            raise CompilerError("delegated confirmation revision claims addressed findings")
        review_path = Path(receipt["delegated_review_path"])
        try:
            delegated_result = delegated_review.verify_review(receipt_path=review_path)
        except delegated_review.DelegatedReviewError as exc:
            raise CompilerError(f"delegated review replay failed: {exc}") from exc
        if delegated_result["review_receipt_sha256"] != receipt["delegated_review_sha256"]:
            raise CompilerError("delegated review receipt digest differs from the freeze receipt")
        delegated_record = load_json(review_path)
        expected_identities = {
            "compiler_author": proposal["author"],
            "reviewer": critique_record["reviewer"],
            "revision_author": revision["author"],
            "approver": receipt["approved_by"],
        }
        for field, expected in expected_identities.items():
            if delegated_record.get(field) != expected:
                raise CompilerError(f"delegated review {field} does not bind the freeze lineage")
        if delegated_record.get("child_ir_sha256") != receipt["research_ir_sha256"]:
            raise CompilerError("delegated review binds a different frozen Research IR")
    else:
        if critique_record["verdict"] != "REVISE":
            raise CompilerError("freeze revision must descend from a REVISE critique")
        _assert_revision_addresses_critique(revision, critique_record)
    _assert_time_order(proposal["recorded_at"], critique_record["recorded_at"], "critique")
    _assert_time_order(critique_record["recorded_at"], revision["recorded_at"], "revision")
    _assert_time_order(revision["recorded_at"], receipt["approved_at"], "approval")
    if delegated_record is not None:
        _assert_time_order(delegated_record["reviewed_at"], receipt["approved_at"], "approval")
    if ir["ir_id"] != receipt["ir_id"] or ir["version"] != receipt["ir_version"]:
        raise CompilerError("freeze receipt IR identity does not match the frozen bytes")
    _assert_valid_ir(ir, check_paths=check_paths)
    if proposal["compiler_prompt_sha256"] != receipt["compiler_prompt_sha256"]:
        raise CompilerError("freeze compiler prompt lineage is inconsistent")
    if proposal["research_ir_schema_sha256"] != receipt["research_ir_schema_sha256"]:
        raise CompilerError("freeze schema lineage is inconsistent")
    return {"valid": "true", "stage": "FROZEN", "freeze_receipt_sha256": receipt_digest, "research_ir_sha256": receipt["research_ir_sha256"], "approval_scope": receipt["approval_scope"]}


def _emit(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MVP-0 Research IR compiler and freeze workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate Research IR schema and semantics")
    validate_parser.add_argument("--ir", type=Path, required=True)
    validate_parser.add_argument("--check-paths", action="store_true")

    proposal_parser = subparsers.add_parser("propose", help="publish a validated proposal")
    proposal_parser.add_argument("--ir", type=Path, required=True)
    proposal_parser.add_argument("--store", type=Path, required=True)
    proposal_parser.add_argument("--author", required=True)
    proposal_parser.add_argument("--recorded-at")

    critique_parser = subparsers.add_parser("critique", help="publish an independent critique")
    critique_parser.add_argument("--proposal", type=Path, required=True)
    critique_parser.add_argument("--critique", type=Path, required=True)
    critique_parser.add_argument("--store", type=Path, required=True)
    critique_parser.add_argument("--reviewer", required=True)
    critique_parser.add_argument("--recorded-at")

    revision_parser = subparsers.add_parser("revise", help="publish a revision bound to required findings")
    revision_parser.add_argument("--proposal", type=Path, required=True)
    revision_parser.add_argument("--critique-record", type=Path, required=True)
    revision_parser.add_argument("--revision", type=Path, required=True)
    revision_parser.add_argument("--store", type=Path, required=True)
    revision_parser.add_argument("--author", required=True)
    revision_parser.add_argument("--recorded-at")

    confirm_parser = subparsers.add_parser(
        "confirm", help="publish a byte-identical revision after an ACCEPT critique"
    )
    confirm_parser.add_argument("--proposal", type=Path, required=True)
    confirm_parser.add_argument("--critique-record", type=Path, required=True)
    confirm_parser.add_argument("--store", type=Path, required=True)
    confirm_parser.add_argument("--author", required=True)
    confirm_parser.add_argument("--summary", required=True)
    confirm_parser.add_argument("--recorded-at")

    freeze_parser = subparsers.add_parser("freeze", help="publish a content-addressed freeze receipt")
    freeze_parser.add_argument("--revision", type=Path, required=True)
    freeze_parser.add_argument("--store", type=Path, required=True)
    freeze_parser.add_argument("--approved-by", required=True)
    freeze_parser.add_argument(
        "--approval-scope",
        choices=("ENGINEERING_ACCEPTANCE", "OWNER_REVIEWED", "DELEGATED_ENGINEERING_REVIEW"),
        required=True,
    )
    freeze_parser.add_argument("--approval-note", required=True)
    freeze_parser.add_argument("--approved-at")
    freeze_parser.add_argument("--delegated-review-receipt", type=Path)
    freeze_parser.add_argument(
        "--engineering-test",
        action="store_true",
        help="allow test-fixture ENGINEERING_ACCEPTANCE; never use for interactive research",
    )

    verify_parser = subparsers.add_parser("verify-freeze", help="replay a freeze receipt and its lineage")
    verify_parser.add_argument("--receipt", type=Path, required=True)
    verify_parser.add_argument("--store", type=Path, required=True)
    verify_parser.add_argument("--check-paths", action="store_true", help="also revalidate live local input paths")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            ir = load_json(args.ir)
            issues = validate_research_ir(ir, check_paths=args.check_paths)
            _emit({"valid": not issues, "issues": [asdict(issue) for issue in issues], "research_ir_sha256": sha256_bytes(canonical_json_bytes(ir))})
            return 0 if not issues else 2
        if args.command == "propose":
            _emit(propose(ir_path=args.ir, store=args.store, author=args.author, recorded_at=args.recorded_at))
        elif args.command == "critique":
            _emit(critique(proposal_path=args.proposal, critique_path=args.critique, store=args.store, reviewer=args.reviewer, recorded_at=args.recorded_at))
        elif args.command == "revise":
            _emit(revise(proposal_path=args.proposal, critique_record_path=args.critique_record, revision_path=args.revision, store=args.store, author=args.author, recorded_at=args.recorded_at))
        elif args.command == "confirm":
            _emit(confirm_revision(proposal_path=args.proposal, critique_record_path=args.critique_record, store=args.store, author=args.author, summary=args.summary, recorded_at=args.recorded_at))
        elif args.command == "freeze":
            _emit(freeze(revision_path=args.revision, store=args.store, approved_by=args.approved_by, approval_scope=args.approval_scope, approval_note=args.approval_note, approved_at=args.approved_at, engineering_test=args.engineering_test, delegated_review_receipt=args.delegated_review_receipt))
        elif args.command == "verify-freeze":
            _emit(verify_freeze(receipt_path=args.receipt, store=args.store, check_paths=args.check_paths))
        return 0
    except CompilerError as exc:
        print(json.dumps({"error": str(exc), "valid": False}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
