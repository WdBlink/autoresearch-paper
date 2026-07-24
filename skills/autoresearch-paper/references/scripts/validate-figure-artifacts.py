#!/usr/bin/env python3
"""Offline, fail-closed validator for autoresearch paper figure manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FIGURE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
VECTOR_MEDIA = {"application/pdf", "image/svg+xml"}
PREVIEW_MEDIA = {"image/png", "image/jpeg"}
SCIENTIFIC_VISUALIZATION_REVISION = "70a0d595e54b8d92ca54f216d4315e0ab8c7d967"
DETERMINISTIC_CAPABILITIES = {
    "scientific-visualization",
    "deterministic-local-renderer",
}
TIER_MINIMUM_FIGURES = {
    "arxiv": 1,
    "conference": 4,
    "journal-q1": 6,
}


class ValidationFailure(Exception):
    """A typed contract or artifact failure."""

    def __init__(self, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field

    def as_dict(self) -> dict[str, str]:
        value = {"code": self.code, "message": self.message}
        if self.field is not None:
            value["field"] = self.field
        return value


class DuplicateKey(ValueError):
    pass


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    except FileNotFoundError as exc:
        raise ValidationFailure("FILE_NOT_FOUND", f"file does not exist: {path}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateKey) as exc:
        raise ValidationFailure("INVALID_JSON", f"invalid JSON in {path}: {exc}") from exc


def require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationFailure("SCHEMA_TYPE", "must be an object", field)
    return value


def require_array(value: Any, field: str, *, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationFailure("SCHEMA_TYPE", "must be an array", field)
    if len(value) < minimum:
        raise ValidationFailure("SCHEMA_MIN_ITEMS", f"must contain at least {minimum} item(s)", field)
    return value


def require_string(value: Any, field: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValidationFailure(
            "SCHEMA_STRING", f"must be a non-empty string of at most {maximum} characters", field
        )
    if "\x00" in value:
        raise ValidationFailure("SCHEMA_STRING", "must not contain NUL", field)
    return value


def require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationFailure("SCHEMA_TYPE", "must be a boolean", field)
    return value


def require_exact_keys(
    value: dict[str, Any],
    field: str,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - required - optional)
    if missing:
        raise ValidationFailure("SCHEMA_REQUIRED", f"missing required key(s): {', '.join(missing)}", field)
    if unknown:
        raise ValidationFailure("SCHEMA_ADDITIONAL_PROPERTY", f"unknown key(s): {', '.join(unknown)}", field)


def ensure_under_root(candidate: Path, root: Path, field: str) -> Path:
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValidationFailure("FILE_NOT_FOUND", f"path does not exist: {candidate}", field) from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValidationFailure(
            "PATH_ESCAPE", f"path resolves outside plan root: {candidate} -> {resolved}", field
        ) from exc
    return resolved


def resolve_artifact_path(raw: Any, root: Path, field: str) -> tuple[str, Path]:
    value = require_string(raw, field, maximum=2048)
    if "\\" in value or WINDOWS_DRIVE_RE.match(value) or Path(value).is_absolute():
        raise ValidationFailure("UNSAFE_PATH", "artifact path must be a relative POSIX path", field)
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValidationFailure("UNSAFE_PATH", "artifact path must not contain empty, '.' or '..' segments", field)
    resolved = ensure_under_root(root.joinpath(*parts), root, field)
    if not resolved.is_file():
        raise ValidationFailure("NOT_A_FILE", f"artifact is not a regular file: {value}", field)
    return value, resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_hashed_artifact(
    artifact: Any,
    root: Path,
    field: str,
    verified: list[dict[str, str]],
) -> tuple[str, Path]:
    value = require_object(artifact, field)
    require_exact_keys(value, field, required={"path", "sha256"})
    raw_hash = require_string(value["sha256"], f"{field}.sha256", maximum=64)
    if not SHA256_RE.fullmatch(raw_hash):
        raise ValidationFailure("INVALID_SHA256", "must be 64 lowercase hexadecimal characters", f"{field}.sha256")
    logical, resolved = resolve_artifact_path(value["path"], root, f"{field}.path")
    observed = sha256_file(resolved)
    if observed != raw_hash:
        raise ValidationFailure(
            "HASH_MISMATCH",
            f"SHA-256 mismatch for {logical}: expected {raw_hash}, observed {observed}",
            f"{field}.sha256",
        )
    verified.append({"path": logical, "sha256": observed})
    return logical, resolved


def validate_input(
    artifact: Any,
    root: Path,
    index: int,
    verified: list[dict[str, str]],
) -> tuple[str, str]:
    field = f"inputs[{index}]"
    value = require_object(artifact, field)
    require_exact_keys(value, field, required={"path", "sha256", "role", "purpose"})
    logical, _ = verify_hashed_artifact(
        {"path": value["path"], "sha256": value["sha256"]}, root, field, verified
    )
    role = require_string(value["role"], f"{field}.role", maximum=64)
    if role not in {"source_data", "render_script", "render_spec", "style", "other"}:
        raise ValidationFailure("SCHEMA_ENUM", f"unsupported input role: {role}", f"{field}.role")
    require_string(value["purpose"], f"{field}.purpose", maximum=1024)
    return logical, role


def validate_output_format(path: Path, logical: str, media_type: str, field: str) -> None:
    suffix = path.suffix.lower()
    allowed_suffixes = {
        "application/pdf": {".pdf"},
        "image/svg+xml": {".svg"},
        "image/png": {".png"},
        "image/jpeg": {".jpg", ".jpeg"},
    }
    if suffix not in allowed_suffixes[media_type]:
        raise ValidationFailure(
            "FORMAT_EXTENSION_MISMATCH",
            f"{logical} extension does not match declared media type {media_type}",
            field,
        )
    head = path.read_bytes()[:16]
    if media_type == "application/pdf" and not head.startswith(b"%PDF-"):
        raise ValidationFailure("FORMAT_SIGNATURE_MISMATCH", f"{logical} is not a PDF", field)
    if media_type == "image/png" and not head.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValidationFailure("FORMAT_SIGNATURE_MISMATCH", f"{logical} is not a PNG", field)
    if media_type == "image/jpeg" and not head.startswith(b"\xff\xd8"):
        raise ValidationFailure("FORMAT_SIGNATURE_MISMATCH", f"{logical} is not a JPEG", field)
    if media_type == "image/svg+xml":
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as exc:
            raise ValidationFailure("FORMAT_SIGNATURE_MISMATCH", f"{logical} is not valid XML/SVG", field) from exc
        if root.tag.rsplit("}", 1)[-1].lower() != "svg":
            raise ValidationFailure("FORMAT_SIGNATURE_MISMATCH", f"{logical} root element is not svg", field)


def validate_output(
    artifact: Any,
    root: Path,
    index: int,
    verified: list[dict[str, str]],
) -> tuple[str, str, str]:
    field = f"outputs[{index}]"
    value = require_object(artifact, field)
    require_exact_keys(value, field, required={"path", "sha256", "role", "media_type"})
    logical, resolved = verify_hashed_artifact(
        {"path": value["path"], "sha256": value["sha256"]}, root, field, verified
    )
    role = require_string(value["role"], f"{field}.role", maximum=64)
    if role not in {"manuscript", "preview", "auxiliary"}:
        raise ValidationFailure("SCHEMA_ENUM", f"unsupported output role: {role}", f"{field}.role")
    media_type = require_string(value["media_type"], f"{field}.media_type", maximum=64)
    if media_type not in VECTOR_MEDIA | PREVIEW_MEDIA:
        raise ValidationFailure("SCHEMA_ENUM", f"unsupported media type: {media_type}", f"{field}.media_type")
    validate_output_format(resolved, logical, media_type, f"{field}.media_type")
    return logical, role, media_type


def validate_manifest(manifest: Any, plan_root: Path) -> dict[str, Any]:
    value = require_object(manifest, "$")
    required = {
        "schema_version", "figure_id", "figure_kind", "generation", "inputs",
        "transformations", "renderer", "outputs", "provenance", "independent_review",
    }
    require_exact_keys(value, "$", required=required)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValidationFailure("SCHEMA_VERSION", "schema_version must equal integer 1", "schema_version")
    figure_id = require_string(value["figure_id"], "figure_id", maximum=128)
    if not FIGURE_ID_RE.fullmatch(figure_id):
        raise ValidationFailure("SCHEMA_PATTERN", "figure_id has an invalid format", "figure_id")
    figure_kind = require_string(value["figure_kind"], "figure_kind", maximum=64)
    if figure_kind not in {"result", "statistical", "method_schematic", "other"}:
        raise ValidationFailure("SCHEMA_ENUM", f"unsupported figure kind: {figure_kind}", "figure_kind")

    generation = require_object(value["generation"], "generation")
    require_exact_keys(
        generation,
        "generation",
        required={"mode", "capability", "capability_revision"},
        optional={"proposal_source"},
    )
    mode = require_string(generation["mode"], "generation.mode", maximum=64)
    capability = require_string(generation["capability"], "generation.capability", maximum=128)
    capability_revision = require_string(
        generation["capability_revision"],
        "generation.capability_revision",
        maximum=256,
    )
    if mode not in {"deterministic", "ai_schematic_proposal"}:
        raise ValidationFailure("SCHEMA_ENUM", f"unsupported generation mode: {mode}", "generation.mode")
    if "proposal_source" in generation:
        require_string(generation["proposal_source"], "generation.proposal_source", maximum=256)
    if mode != "deterministic" or capability not in DETERMINISTIC_CAPABILITIES:
        raise ValidationFailure(
            "AI_PROPOSAL_ONLY",
            "AI-generated schematics are proposal-only; deterministically re-render before promotion",
            "generation",
        )
    if (
        capability == "scientific-visualization"
        and capability_revision != SCIENTIFIC_VISUALIZATION_REVISION
    ):
        raise ValidationFailure(
            "UNPINNED_CAPABILITY",
            "scientific-visualization must use the repository-audited revision",
            "generation.capability_revision",
        )

    verified: list[dict[str, str]] = []
    inputs = require_array(value["inputs"], "inputs", minimum=1)
    input_paths: set[str] = set()
    input_roles: set[str] = set()
    for index, artifact in enumerate(inputs):
        logical, role = validate_input(artifact, plan_root, index, verified)
        if logical in input_paths:
            raise ValidationFailure("DUPLICATE_ARTIFACT", f"duplicate input path: {logical}", f"inputs[{index}].path")
        input_paths.add(logical)
        input_roles.add(role)
    if figure_kind in {"result", "statistical"} and "source_data" not in input_roles:
        raise ValidationFailure(
            "MISSING_SOURCE_DATA",
            "result/statistical figures require at least one source_data input",
            "inputs",
        )
    if not input_roles.intersection({"render_script", "render_spec"}):
        raise ValidationFailure("MISSING_RENDER_SOURCE", "a render_script or render_spec input is required", "inputs")

    transformations = require_array(value["transformations"], "transformations")
    for index, item in enumerate(transformations):
        field = f"transformations[{index}]"
        transform = require_object(item, field)
        require_exact_keys(transform, field, required={"order", "operation", "description", "parameters"})
        if type(transform["order"]) is not int or transform["order"] != index:
            raise ValidationFailure(
                "TRANSFORMATION_ORDER", "transformation order must be contiguous and zero-based", f"{field}.order"
            )
        require_string(transform["operation"], f"{field}.operation", maximum=256)
        require_string(transform["description"], f"{field}.description", maximum=1024)
        require_object(transform["parameters"], f"{field}.parameters")

    renderer = require_object(value["renderer"], "renderer")
    require_exact_keys(
        renderer,
        "renderer",
        required={"identity", "version", "source_revision", "command", "random_seed"},
    )
    for key, maximum in (("identity", 256), ("version", 128), ("source_revision", 256)):
        require_string(renderer[key], f"renderer.{key}", maximum=maximum)
    if (
        capability == "deterministic-local-renderer"
        and capability_revision != renderer["source_revision"]
    ):
        raise ValidationFailure(
            "CAPABILITY_REVISION_MISMATCH",
            "local renderer capability revision must match renderer.source_revision",
            "generation.capability_revision",
        )
    command = require_array(renderer["command"], "renderer.command", minimum=1)
    for index, argument in enumerate(command):
        text = require_string(argument, f"renderer.command[{index}]", maximum=4096)
        if "\n" in text or "\r" in text:
            raise ValidationFailure("UNSAFE_COMMAND_RECORD", "command arguments must not contain newlines", f"renderer.command[{index}]")
    seed = renderer["random_seed"]
    if type(seed) is not int or seed < 0:
        raise ValidationFailure("SCHEMA_INTEGER", "random_seed must be a non-negative integer", "renderer.random_seed")

    outputs = require_array(value["outputs"], "outputs", minimum=2)
    output_paths: set[str] = set()
    output_records: list[tuple[str, str, str]] = []
    for index, artifact in enumerate(outputs):
        record = validate_output(artifact, plan_root, index, verified)
        if record[0] in output_paths or record[0] in input_paths:
            raise ValidationFailure("DUPLICATE_ARTIFACT", f"duplicate or input/output-overlapping path: {record[0]}", f"outputs[{index}].path")
        output_paths.add(record[0])
        output_records.append(record)
    if not any(role == "manuscript" and media in VECTOR_MEDIA for _, role, media in output_records):
        raise ValidationFailure("MISSING_VECTOR_OUTPUT", "a manuscript PDF or SVG output is required", "outputs")
    if not any(role == "preview" and media in PREVIEW_MEDIA for _, role, media in output_records):
        raise ValidationFailure("MISSING_PREVIEW", "a PNG or JPEG preview output is required", "outputs")

    provenance = require_object(value["provenance"], "provenance")
    require_exact_keys(
        provenance,
        "provenance",
        required={"plan_id", "created_at", "research_authority", "claim_ids"},
    )
    require_string(provenance["plan_id"], "provenance.plan_id", maximum=256)
    created_at = require_string(provenance["created_at"], "provenance.created_at", maximum=128)
    try:
        parsed_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationFailure("INVALID_DATETIME", "created_at must be an ISO-8601 date-time", "provenance.created_at") from exc
    if parsed_at.tzinfo is None:
        raise ValidationFailure("INVALID_DATETIME", "created_at must include a timezone", "provenance.created_at")
    authority = require_object(provenance["research_authority"], "provenance.research_authority")
    require_exact_keys(authority, "provenance.research_authority", required={"kind", "path", "sha256"})
    authority_kind = require_string(authority["kind"], "provenance.research_authority.kind", maximum=64)
    if authority_kind not in {"keep_receipt", "arxiv_negative_result_waiver", "method_spec"}:
        raise ValidationFailure("SCHEMA_ENUM", f"unsupported research authority: {authority_kind}", "provenance.research_authority.kind")
    verify_hashed_artifact(
        {"path": authority["path"], "sha256": authority["sha256"]},
        plan_root,
        "provenance.research_authority",
        verified,
    )
    if figure_kind in {"result", "statistical"} and authority_kind not in {
        "keep_receipt", "arxiv_negative_result_waiver"
    }:
        raise ValidationFailure(
            "INVALID_RESEARCH_AUTHORITY",
            "result/statistical figures require a KEEP receipt or arxiv negative-result waiver",
            "provenance.research_authority.kind",
        )
    claim_ids = require_array(provenance["claim_ids"], "provenance.claim_ids")
    if figure_kind in {"result", "statistical"} and not claim_ids:
        raise ValidationFailure("MISSING_CLAIM_BINDING", "result/statistical figures require at least one claim id", "provenance.claim_ids")
    seen_claims: set[str] = set()
    for index, claim in enumerate(claim_ids):
        text = require_string(claim, f"provenance.claim_ids[{index}]", maximum=256)
        if text in seen_claims:
            raise ValidationFailure("DUPLICATE_CLAIM", f"duplicate claim id: {text}", f"provenance.claim_ids[{index}]")
        seen_claims.add(text)

    review = require_object(value["independent_review"], "independent_review")
    require_exact_keys(
        review,
        "independent_review",
        required={
            "receipt", "reviewer_kind", "reviewer_identity", "independent_of_renderer",
            "decision", "ai_quality_score_used_as_authority",
        },
        optional={"ai_quality_score"},
    )
    _, review_receipt_path = verify_hashed_artifact(
        review["receipt"], plan_root, "independent_review.receipt", verified
    )
    reviewer_kind = require_string(review["reviewer_kind"], "independent_review.reviewer_kind", maximum=64)
    if reviewer_kind not in {"human", "independent_agent", "ai_model"}:
        raise ValidationFailure("SCHEMA_ENUM", f"unsupported reviewer kind: {reviewer_kind}", "independent_review.reviewer_kind")
    require_string(review["reviewer_identity"], "independent_review.reviewer_identity", maximum=256)
    independent = require_bool(review["independent_of_renderer"], "independent_review.independent_of_renderer")
    decision = require_string(review["decision"], "independent_review.decision", maximum=16)
    ai_authority = require_bool(
        review["ai_quality_score_used_as_authority"],
        "independent_review.ai_quality_score_used_as_authority",
    )
    if "ai_quality_score" in review and (
        isinstance(review["ai_quality_score"], bool)
        or not isinstance(review["ai_quality_score"], (int, float))
    ):
        raise ValidationFailure("SCHEMA_NUMBER", "ai_quality_score must be numeric", "independent_review.ai_quality_score")
    if reviewer_kind != "human" or ai_authority:
        raise ValidationFailure(
            "AI_REVIEW_NOT_AUTHORITY",
            "only a human independent review may grant figure acceptance; AI agents/models and AI scores cannot",
            "independent_review",
        )
    if not independent:
        raise ValidationFailure("REVIEW_NOT_INDEPENDENT", "review must be independent of the renderer", "independent_review.independent_of_renderer")
    if decision != "PASS":
        raise ValidationFailure("REVIEW_NOT_PASS", "independent review decision must be PASS", "independent_review.decision")

    receipt = require_object(read_json(review_receipt_path), "independent_review.receipt.content")
    require_exact_keys(
        receipt,
        "independent_review.receipt.content",
        required={
            "schema_version", "figure_id", "reviewed_at", "reviewer_kind",
            "reviewer_identity", "independent_of_renderer", "decision",
            "reviewed_outputs",
        },
    )
    if type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1:
        raise ValidationFailure(
            "REVIEW_RECEIPT_SCHEMA",
            "review receipt schema_version must equal integer 1",
            "independent_review.receipt.content.schema_version",
        )
    receipt_figure_id = require_string(
        receipt["figure_id"],
        "independent_review.receipt.content.figure_id",
        maximum=128,
    )
    if receipt_figure_id != figure_id:
        raise ValidationFailure(
            "REVIEW_RECEIPT_MISMATCH",
            "review receipt figure_id does not match manifest",
            "independent_review.receipt.content.figure_id",
        )
    reviewed_at = require_string(
        receipt["reviewed_at"],
        "independent_review.receipt.content.reviewed_at",
        maximum=128,
    )
    try:
        parsed_reviewed_at = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationFailure(
            "INVALID_DATETIME",
            "reviewed_at must be an ISO-8601 date-time",
            "independent_review.receipt.content.reviewed_at",
        ) from exc
    if parsed_reviewed_at.tzinfo is None:
        raise ValidationFailure(
            "INVALID_DATETIME",
            "reviewed_at must include a timezone",
            "independent_review.receipt.content.reviewed_at",
        )
    receipt_kind = require_string(
        receipt["reviewer_kind"],
        "independent_review.receipt.content.reviewer_kind",
        maximum=64,
    )
    receipt_identity = require_string(
        receipt["reviewer_identity"],
        "independent_review.receipt.content.reviewer_identity",
        maximum=256,
    )
    receipt_independent = require_bool(
        receipt["independent_of_renderer"],
        "independent_review.receipt.content.independent_of_renderer",
    )
    receipt_decision = require_string(
        receipt["decision"],
        "independent_review.receipt.content.decision",
        maximum=16,
    )
    if (
        receipt_kind != reviewer_kind
        or receipt_identity != review["reviewer_identity"]
        or receipt_independent != independent
        or receipt_decision != decision
    ):
        raise ValidationFailure(
            "REVIEW_RECEIPT_MISMATCH",
            "review receipt authority fields do not match manifest",
            "independent_review.receipt.content",
        )
    reviewed_outputs = require_array(
        receipt["reviewed_outputs"],
        "independent_review.receipt.content.reviewed_outputs",
        minimum=2,
    )
    receipt_output_set: set[tuple[str, str]] = set()
    for index, item in enumerate(reviewed_outputs):
        field = f"independent_review.receipt.content.reviewed_outputs[{index}]"
        artifact = require_object(item, field)
        require_exact_keys(artifact, field, required={"path", "sha256"})
        path_value = require_string(artifact["path"], f"{field}.path", maximum=2048)
        hash_value = require_string(artifact["sha256"], f"{field}.sha256", maximum=64)
        if not SHA256_RE.fullmatch(hash_value):
            raise ValidationFailure("INVALID_SHA256", "must be 64 lowercase hexadecimal characters", f"{field}.sha256")
        record = (path_value, hash_value)
        if record in receipt_output_set:
            raise ValidationFailure("DUPLICATE_ARTIFACT", f"duplicate reviewed output: {path_value}", field)
        receipt_output_set.add(record)
    current_output_set = {
        (artifact["path"], artifact["sha256"])
        for artifact in outputs
    }
    if receipt_output_set != current_output_set:
        raise ValidationFailure(
            "STALE_REVIEW_RECEIPT",
            "review receipt must bind the complete current output path/hash set",
            "independent_review.receipt.content.reviewed_outputs",
        )

    return {
        "schema_version": 1,
        "status": "PASS",
        "eligible": True,
        "figure_id": figure_id,
        "verified_artifacts": verified,
    }


def validate_requirements(requirements: Any) -> dict[str, Any]:
    value = require_object(requirements, "requirements")
    require_exact_keys(
        value,
        "requirements",
        required={"schema_version", "plan_id", "tier", "expected_figure_ids"},
    )
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValidationFailure(
            "SCHEMA_VERSION",
            "requirements schema_version must equal integer 1",
            "requirements.schema_version",
        )
    plan_id = require_string(value["plan_id"], "requirements.plan_id", maximum=256)
    tier = require_string(value["tier"], "requirements.tier", maximum=32)
    if tier not in TIER_MINIMUM_FIGURES:
        raise ValidationFailure(
            "SCHEMA_ENUM",
            f"unsupported figure-requirement tier: {tier}",
            "requirements.tier",
        )
    raw_ids = require_array(
        value["expected_figure_ids"],
        "requirements.expected_figure_ids",
        minimum=TIER_MINIMUM_FIGURES[tier],
    )
    expected_ids: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_ids):
        field = f"requirements.expected_figure_ids[{index}]"
        figure_id = require_string(raw, field, maximum=128)
        if not FIGURE_ID_RE.fullmatch(figure_id):
            raise ValidationFailure(
                "SCHEMA_PATTERN",
                "figure_id has an invalid format",
                field,
            )
        if figure_id in seen:
            raise ValidationFailure(
                "DUPLICATE_FIGURE",
                f"duplicate required figure_id: {figure_id}",
                field,
            )
        seen.add(figure_id)
        expected_ids.append(figure_id)
    return {
        "schema_version": 1,
        "plan_id": plan_id,
        "tier": tier,
        "expected_figure_ids": expected_ids,
    }


def validate_inventory(
    inventory: Any,
    plan_root: Path,
    requirements: Any,
) -> dict[str, Any]:
    requirement = validate_requirements(requirements)
    value = require_object(inventory, "$")
    require_exact_keys(
        value,
        "$",
        required={"schema_version", "plan_id", "required_figures"},
    )
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValidationFailure("SCHEMA_VERSION", "schema_version must equal integer 1", "schema_version")
    plan_id = require_string(value["plan_id"], "plan_id", maximum=256)
    if plan_id != requirement["plan_id"]:
        raise ValidationFailure(
            "PLAN_ID_MISMATCH",
            "inventory plan_id does not match frozen figure requirements",
            "plan_id",
        )
    required_figures = require_array(
        value["required_figures"],
        "required_figures",
        minimum=1,
    )
    seen_ids: set[str] = set()
    seen_manifests: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, raw in enumerate(required_figures):
        field = f"required_figures[{index}]"
        record = require_object(raw, field)
        require_exact_keys(record, field, required={"figure_id", "manifest", "sha256"})
        figure_id = require_string(record["figure_id"], f"{field}.figure_id", maximum=128)
        if not FIGURE_ID_RE.fullmatch(figure_id):
            raise ValidationFailure("SCHEMA_PATTERN", "figure_id has an invalid format", f"{field}.figure_id")
        if figure_id in seen_ids:
            raise ValidationFailure("DUPLICATE_FIGURE", f"duplicate figure_id: {figure_id}", f"{field}.figure_id")
        seen_ids.add(figure_id)
        expected_hash = require_string(record["sha256"], f"{field}.sha256", maximum=64)
        if not SHA256_RE.fullmatch(expected_hash):
            raise ValidationFailure("INVALID_SHA256", "must be 64 lowercase hexadecimal characters", f"{field}.sha256")
        logical, manifest_path = resolve_artifact_path(
            record["manifest"],
            plan_root,
            f"{field}.manifest",
        )
        if logical in seen_manifests:
            raise ValidationFailure("DUPLICATE_ARTIFACT", f"duplicate manifest path: {logical}", f"{field}.manifest")
        seen_manifests.add(logical)
        observed_hash = sha256_file(manifest_path)
        if observed_hash != expected_hash:
            raise ValidationFailure(
                "HASH_MISMATCH",
                f"SHA-256 mismatch for {logical}: expected {expected_hash}, observed {observed_hash}",
                f"{field}.sha256",
            )
        manifest = read_json(manifest_path)
        result = validate_manifest(manifest, plan_root)
        if result["figure_id"] != figure_id:
            raise ValidationFailure(
                "FIGURE_ID_MISMATCH",
                "inventory figure_id does not match manifest",
                f"{field}.figure_id",
            )
        manifest_plan_id = require_string(
            require_object(manifest.get("provenance"), "provenance").get("plan_id"),
            "provenance.plan_id",
            maximum=256,
        )
        if manifest_plan_id != plan_id:
            raise ValidationFailure(
                "PLAN_ID_MISMATCH",
                "manifest provenance.plan_id does not match inventory",
                "provenance.plan_id",
            )
        validated.append({
            "figure_id": figure_id,
            "manifest": logical,
            "manifest_sha256": observed_hash,
            "verified_artifacts": result["verified_artifacts"],
        })
    expected_ids = set(requirement["expected_figure_ids"])
    observed_ids = set(seen_ids)
    if observed_ids != expected_ids:
        missing = sorted(expected_ids - observed_ids)
        unexpected = sorted(observed_ids - expected_ids)
        raise ValidationFailure(
            "INCOMPLETE_FIGURE_INVENTORY",
            f"inventory does not match frozen figure requirements; missing={missing}, unexpected={unexpected}",
            "required_figures",
        )
    return {
        "schema_version": 1,
        "status": "PASS",
        "eligible": True,
        "plan_id": plan_id,
        "tier": requirement["tier"],
        "expected_figure_ids": requirement["expected_figure_ids"],
        "required_figure_count": len(validated),
        "figures": validated,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-dir", required=True, help="Plan root that contains every referenced artifact")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--manifest", help="Figure manifest JSON inside the plan root")
    target.add_argument("--inventory", help="Plan-level required-figure inventory JSON inside the plan root")
    target.add_argument(
        "--requirements-only",
        help="Validate one frozen figure-requirements JSON inside the plan root",
    )
    parser.add_argument(
        "--requirements",
        help="Frozen controller-owned figure requirements JSON; required with --inventory",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        plan_arg = Path(args.plan_dir)
        if not plan_arg.exists() or not plan_arg.is_dir():
            raise ValidationFailure("INVALID_PLAN_ROOT", f"plan root is not a directory: {plan_arg}", "--plan-dir")
        plan_root = plan_arg.resolve(strict=True)
        if args.manifest is not None:
            raw_target, target_field = args.manifest, "--manifest"
        elif args.inventory is not None:
            raw_target, target_field = args.inventory, "--inventory"
        else:
            raw_target, target_field = args.requirements_only, "--requirements-only"
        target_arg = Path(raw_target)
        if not target_arg.is_absolute():
            target_arg = plan_root / target_arg
        target_path = ensure_under_root(target_arg, plan_root, target_field)
        if not target_path.is_file():
            raise ValidationFailure("NOT_A_FILE", f"target is not a file: {target_path}", target_field)
        payload = read_json(target_path)
        if args.inventory is not None and not args.requirements:
            raise ValidationFailure(
                "MISSING_REQUIREMENTS",
                "--requirements is mandatory with --inventory",
                "--requirements",
            )
        if args.inventory is None and args.requirements:
            raise ValidationFailure(
                "UNEXPECTED_REQUIREMENTS",
                "--requirements is valid only with --inventory",
                "--requirements",
            )
        requirements_path: Path | None = None
        requirements_payload: Any = None
        if args.requirements:
            requirements_arg = Path(args.requirements)
            if not requirements_arg.is_absolute():
                requirements_arg = plan_root / requirements_arg
            requirements_path = ensure_under_root(
                requirements_arg,
                plan_root,
                "--requirements",
            )
            if not requirements_path.is_file():
                raise ValidationFailure(
                    "NOT_A_FILE",
                    f"requirements is not a file: {requirements_path}",
                    "--requirements",
                )
            requirements_payload = read_json(requirements_path)
        if args.manifest is not None:
            result = validate_manifest(payload, plan_root)
        elif args.inventory is not None:
            result = validate_inventory(payload, plan_root, requirements_payload)
        else:
            result = {
                "status": "PASS",
                "eligible": True,
                **validate_requirements(payload),
            }
        result["plan_root"] = str(plan_root)
        if args.manifest is not None:
            target_name = "manifest"
        elif args.inventory is not None:
            target_name = "inventory"
        else:
            target_name = "requirements"
        result[target_name] = str(target_path)
        result[f"{target_name}_sha256"] = sha256_file(target_path)
        if requirements_path is not None:
            result["requirements"] = str(requirements_path)
            result["requirements_sha256"] = sha256_file(requirements_path)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ValidationFailure as exc:
        failure = {
            "schema_version": 1,
            "status": "FAIL",
            "eligible": False,
            "errors": [exc.as_dict()],
        }
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
