#!/usr/bin/env python3
"""Deterministic Codex App thread-heartbeat registration for MVP-0 P6 L1."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, Mapping


THREAD_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
CONTROLLER_ID_RE = re.compile(r"^mvp0-supervisor-[0-9a-f]{16,64}$")
RRULE_RE = re.compile(r"^RRULE:FREQ=MINUTELY;INTERVAL=([0-9]{1,2})$")
AUTOMATION_KEYS = {
    "version",
    "id",
    "kind",
    "name",
    "prompt",
    "status",
    "rrule",
    "target_thread_id",
    "created_at",
    "updated_at",
}


class AutomationError(RuntimeError):
    """A fail-closed L1 automation registration error."""


def _quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _validate_values(value: Mapping[str, Any]) -> None:
    if set(value) != AUTOMATION_KEYS:
        raise AutomationError(
            "automation fields differ: "
            f"missing={sorted(AUTOMATION_KEYS - set(value))}, "
            f"unknown={sorted(set(value) - AUTOMATION_KEYS)}"
        )
    if value["version"] != 1:
        raise AutomationError("automation version must be 1")
    if not isinstance(value["id"], str) or CONTROLLER_ID_RE.fullmatch(value["id"]) is None:
        raise AutomationError("automation id must be an MVP0 supervisor id")
    if value["kind"] != "heartbeat":
        raise AutomationError("automation kind must be heartbeat")
    if not isinstance(value["name"], str) or not value["name"].strip():
        raise AutomationError("automation name must be non-empty")
    if not isinstance(value["prompt"], str) or not value["prompt"].strip():
        raise AutomationError("automation prompt must be non-empty")
    if value["status"] not in {"ACTIVE", "PAUSED"}:
        raise AutomationError("automation status must be ACTIVE or PAUSED")
    match = RRULE_RE.fullmatch(value["rrule"]) if isinstance(value["rrule"], str) else None
    if match is None or not 5 <= int(match.group(1)) <= 60:
        raise AutomationError("automation minute interval must be between 5 and 60")
    thread_id = value["target_thread_id"]
    if not isinstance(thread_id, str) or THREAD_ID_RE.fullmatch(thread_id) is None:
        raise AutomationError("target_thread_id must be a canonical UUID-shaped id")
    for field in ("created_at", "updated_at"):
        if not isinstance(value[field], int) or isinstance(value[field], bool) or value[field] < 0:
            raise AutomationError(f"automation {field} must be a non-negative integer")
    if value["updated_at"] < value["created_at"]:
        raise AutomationError("automation updated_at precedes created_at")


def render_thread_automation(
    *,
    controller_id: str,
    name: str,
    prompt: str,
    target_thread_id: str,
    created_at_ms: int,
    updated_at_ms: int | None = None,
    status: str = "ACTIVE",
    rrule: str = "RRULE:FREQ=MINUTELY;INTERVAL=10",
) -> str:
    value = {
        "version": 1,
        "id": controller_id,
        "kind": "heartbeat",
        "name": name,
        "prompt": prompt,
        "status": status,
        "rrule": rrule,
        "target_thread_id": target_thread_id,
        "created_at": created_at_ms,
        "updated_at": created_at_ms if updated_at_ms is None else updated_at_ms,
    }
    _validate_values(value)
    ordered = (
        "version",
        "id",
        "kind",
        "name",
        "prompt",
        "status",
        "rrule",
        "target_thread_id",
        "created_at",
        "updated_at",
    )
    lines = [
        f"{key} = {value[key] if isinstance(value[key], int) else _quote(value[key])}"
        for key in ordered
    ]
    return "\n".join(lines) + "\n"


def parse_thread_automation(data: bytes | str) -> dict[str, Any]:
    try:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        parsed = tomllib.loads(text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise AutomationError(f"cannot parse automation TOML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise AutomationError("automation root must be a TOML table")
    _validate_values(parsed)
    return parsed


def validate_thread_automation(
    path: Path,
    *,
    expected_thread_id: str,
    expected_controller_id: str,
) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_absolute() or not resolved.is_file() or resolved.is_symlink():
        raise AutomationError("automation path must be an existing absolute regular file")
    value = parse_thread_automation(resolved.read_bytes())
    if value["target_thread_id"] != expected_thread_id:
        raise AutomationError("automation target thread mismatch")
    if value["id"] != expected_controller_id:
        raise AutomationError("automation controller id mismatch")
    return value


def with_status(data: bytes, *, status: str, updated_at_ms: int) -> bytes:
    value = parse_thread_automation(data)
    return render_thread_automation(
        controller_id=value["id"],
        name=value["name"],
        prompt=value["prompt"],
        target_thread_id=value["target_thread_id"],
        created_at_ms=value["created_at"],
        updated_at_ms=updated_at_ms,
        status=status,
        rrule=value["rrule"],
    ).encode("utf-8")
