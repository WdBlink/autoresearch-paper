#!/usr/bin/env python3
"""Plan-bound macOS launchd registration for the P6 zero-model L0."""

from __future__ import annotations

import hashlib
import os
import plistlib
import re
import subprocess
from pathlib import Path
from typing import Protocol, Sequence


LABEL_RE = re.compile(r"^com\.autoresearch-paper\.mvp0\.l0\.[0-9a-f]{16}$")


class LaunchdError(RuntimeError):
    """A fail-closed launchd registration error."""


class Scheduler(Protocol):
    def is_loaded(self, label: str) -> bool: ...

    def load(self, label: str, plist_path: Path) -> None: ...

    def unload(self, label: str) -> None: ...


def command_sha256(argv: Sequence[str]) -> str:
    payload = b"\x00".join(item.encode("utf-8") for item in argv) + b"\x00"
    return hashlib.sha256(payload).hexdigest()


def label_for_controller(controller_id: str) -> str:
    suffix = hashlib.sha256(controller_id.encode("utf-8")).hexdigest()[:16]
    return f"com.autoresearch-paper.mvp0.l0.{suffix}"


def render_l0_plist(
    *,
    label: str,
    program_arguments: Sequence[str],
    interval_seconds: int,
    stdout_path: Path,
    stderr_path: Path,
) -> bytes:
    if LABEL_RE.fullmatch(label) is None:
        raise LaunchdError("invalid plan-bound L0 scheduler label")
    if not 60 <= interval_seconds <= 3600:
        raise LaunchdError("L0 interval must be between 60 and 3600 seconds")
    if not program_arguments or any(not isinstance(item, str) or not item for item in program_arguments):
        raise LaunchdError("L0 program arguments must be non-empty strings")
    if not Path(program_arguments[0]).is_absolute():
        raise LaunchdError("L0 executable must be absolute")
    for path, label_name in ((stdout_path, "stdout"), (stderr_path, "stderr")):
        if not path.is_absolute():
            raise LaunchdError(f"L0 {label_name} path must be absolute")
    value = {
        "Label": label,
        "ProgramArguments": list(program_arguments),
        "RunAtLoad": True,
        "StandardErrorPath": str(stderr_path),
        "StandardOutPath": str(stdout_path),
        "StartInterval": interval_seconds,
    }
    return plistlib.dumps(value, fmt=plistlib.FMT_XML, sort_keys=True)


def validate_l0_plist(
    data: bytes,
    *,
    expected_label: str,
    expected_arguments: Sequence[str],
) -> dict[str, object]:
    try:
        value = plistlib.loads(data)
    except Exception as exc:  # plistlib exposes several parse exception types
        raise LaunchdError(f"cannot parse L0 plist: {exc}") from exc
    expected_keys = {
        "Label",
        "ProgramArguments",
        "RunAtLoad",
        "StandardErrorPath",
        "StandardOutPath",
        "StartInterval",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise LaunchdError("L0 plist fields differ from the closed contract")
    if value["Label"] != expected_label or value["ProgramArguments"] != list(expected_arguments):
        raise LaunchdError("L0 plist identity or command mismatch")
    if value["RunAtLoad"] is not True:
        raise LaunchdError("L0 plist must RunAtLoad")
    if not isinstance(value["StartInterval"], int) or not 60 <= value["StartInterval"] <= 3600:
        raise LaunchdError("L0 plist interval is invalid")
    for key in ("StandardOutPath", "StandardErrorPath"):
        if not isinstance(value[key], str) or not Path(value[key]).is_absolute():
            raise LaunchdError("L0 plist log path must be absolute")
    return value


class LaunchctlScheduler:
    """Small user-domain launchctl adapter; tests inject an in-memory backend."""

    def __init__(self, *, launchctl: Path = Path("/bin/launchctl"), uid: int | None = None) -> None:
        self.launchctl = launchctl.resolve()
        self.uid = os.getuid() if uid is None else uid
        if not self.launchctl.is_file() or not os.access(self.launchctl, os.X_OK):
            raise LaunchdError(f"launchctl is unavailable: {self.launchctl}")

    @property
    def domain(self) -> str:
        return f"gui/{self.uid}"

    def _run(self, *args: str, check: bool = False) -> subprocess.CompletedProcess[bytes]:
        proc = subprocess.run(
            [str(self.launchctl), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check and proc.returncode != 0:
            message = proc.stderr.decode("utf-8", errors="replace").strip()
            raise LaunchdError(f"launchctl {' '.join(args)} failed: {message[:500]}")
        return proc

    def is_loaded(self, label: str) -> bool:
        return self._run("print", f"{self.domain}/{label}").returncode == 0

    def load(self, label: str, plist_path: Path) -> None:
        if self.is_loaded(label):
            return
        self._run("bootstrap", self.domain, str(plist_path.resolve()), check=True)
        if not self.is_loaded(label):
            raise LaunchdError("launchctl bootstrap returned without a loaded L0 service")

    def unload(self, label: str) -> None:
        if not self.is_loaded(label):
            return
        proc = self._run("bootout", f"{self.domain}/{label}")
        if proc.returncode != 0 and self.is_loaded(label):
            message = proc.stderr.decode("utf-8", errors="replace").strip()
            raise LaunchdError(f"launchctl bootout failed: {message[:500]}")
