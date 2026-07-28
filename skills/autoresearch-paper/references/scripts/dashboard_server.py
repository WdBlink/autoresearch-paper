#!/usr/bin/env python3
"""Loopback-only, read-only Dashboard transport for one research plan."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import mimetypes
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit


DASHBOARD_SCHEMA_VERSION = 1
DEFAULT_LOG_BYTES = 64 * 1024
MAX_LOG_BYTES = 256 * 1024
MAX_DOSSIER_BYTES = 256 * 1024
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "font-src 'self'; img-src 'self' data:; connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'none'"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


class DashboardError(ValueError):
    """Dashboard request or startup violates the read-only boundary."""


@dataclass(frozen=True)
class BoundLog:
    token: str
    kind: str
    path: Path
    relative_path: str
    exists: bool
    size_bytes: int | None
    sha256: str | None


def require_loopback_host(host: str) -> str:
    """Accept literal loopback addresses only; DNS names are not bind authority."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise DashboardError("dashboard host must be a literal loopback address") from exc
    if not address.is_loopback:
        raise DashboardError("dashboard host must be loopback-only")
    return host


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_plan_file(value: Any, plan_dir: Path) -> dict[str, Any]:
    """Expose plan-relative evidence metadata, never an absolute filesystem path."""
    if not isinstance(value, dict):
        return {"present": False, "exists": False}
    raw_path = value.get("path")
    path = Path(raw_path).resolve() if isinstance(raw_path, str) else None
    safe = bool(path is not None and _within(path, plan_dir))
    exists = bool(value.get("exists")) if safe else False
    return {
        "present": exists,
        "path_bound": safe,
        "relative_path": str(path.relative_to(plan_dir)) if safe and path else None,
        "exists": exists,
        "size_bytes": value.get("size_bytes") if safe else None,
        "sha256": value.get("sha256") if safe else None,
    }


def _log_token(kind: str, relative_path: str) -> str:
    return hashlib.sha256(f"{kind}\0{relative_path}".encode()).hexdigest()[:32]


def bound_logs(raw: dict[str, Any], plan_dir: Path) -> dict[str, BoundLog]:
    """Rebuild the allow-list from the current inspection on every log request."""
    plan_dir = plan_dir.resolve()
    discovered: dict[str, BoundLog] = {}

    def add(kind: str, value: Any) -> None:
        if not isinstance(value, dict) or not isinstance(value.get("path"), str):
            return
        path = Path(value["path"]).resolve()
        if not _within(path, plan_dir):
            return
        relative_path = str(path.relative_to(plan_dir))
        token = _log_token(kind, relative_path)
        discovered[token] = BoundLog(
            token=token,
            kind=kind,
            path=path,
            relative_path=relative_path,
            exists=path.is_file(),
            size_bytes=path.stat().st_size if path.is_file() else None,
            sha256=_sha256_file(path) if path.is_file() else None,
        )

    for index, scheduler in enumerate(raw.get("schedulers", [])):
        if not isinstance(scheduler, dict):
            continue
        identity = str(scheduler.get("kind", "scheduler"))
        prefix = f"scheduler:{index}:{identity}"
        add(f"{prefix}:stdout", scheduler.get("stdout"))
        add(f"{prefix}:stderr", scheduler.get("stderr"))
    for worker in raw.get("workers", []):
        if not isinstance(worker, dict):
            continue
        identity = str(worker.get("run_id", "worker"))
        add(f"worker:{identity}:stdout", worker.get("stdout"))
        add(f"worker:{identity}:stderr", worker.get("stderr"))
    return discovered


def _public_log(value: Any, kind: str, logs: dict[str, BoundLog]) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        return {"bound": False, "exists": False}
    candidate = next((item for item in logs.values() if item.kind == kind), None)
    if candidate is None:
        return {"bound": False, "exists": False}
    return {
        "bound": True,
        "exists": candidate.exists,
        "relative_path": candidate.relative_path,
        "size_bytes": candidate.size_bytes,
        "sha256": candidate.sha256,
        "api_path": f"/api/logs/{candidate.token}",
    }


def public_snapshot(raw: dict[str, Any], plan_dir: Path) -> dict[str, Any]:
    """Project inspection into a stable, credential-free browser contract."""
    plan_dir = plan_dir.resolve()
    logs = bound_logs(raw, plan_dir)
    canonical = raw.get("canonical") if isinstance(raw.get("canonical"), dict) else {}
    schedulers: list[dict[str, Any]] = []
    for index, item in enumerate(raw.get("schedulers", [])):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "scheduler"))
        log_prefix = f"scheduler:{index}:{kind}"
        current = item.get("current") if isinstance(item.get("current"), dict) else {}
        schedulers.append({
            "kind": kind,
            "present": bool(item.get("present")),
            "active": bool(item.get("active")),
            "label": item.get("label"),
            "loaded": item.get("loaded"),
            "state_matches_scheduler": item.get("state_matches_scheduler"),
            "generation": current.get("generation"),
            "receipt": _safe_plan_file(item.get("receipt"), plan_dir),
            "stdout": _public_log(item.get("stdout"), f"{log_prefix}:stdout", logs),
            "stderr": _public_log(item.get("stderr"), f"{log_prefix}:stderr", logs),
        })
    workers: list[dict[str, Any]] = []
    for item in raw.get("workers", []):
        if not isinstance(item, dict):
            continue
        run_id = str(item.get("run_id", "worker"))
        status = item.get("status") if isinstance(item.get("status"), dict) else {}
        process = item.get("process") if isinstance(item.get("process"), dict) else {}
        workers.append({
            "run_id": run_id,
            "status": status.get("status"),
            "updated_at": status.get("updated_at"),
            "process": {
                "running": process.get("running"),
                "identity_match": process.get("identity_match"),
                "reason": process.get("reason"),
            },
            "status_file": _safe_plan_file({
                "path": item.get("status_path"),
                "exists": True,
                "sha256": item.get("status_sha256"),
            }, plan_dir),
            "stdout": _public_log(item.get("stdout"), f"worker:{run_id}:stdout", logs),
            "stderr": _public_log(item.get("stderr"), f"worker:{run_id}:stderr", logs),
        })
    mismatches = []
    for item in raw.get("mismatches", []):
        if isinstance(item, dict):
            mismatches.append({
                key: item.get(key)
                for key in ("kind", "label", "run_id", "reason")
                if item.get(key) is not None
            })
    resources = []
    for item in raw.get("declared_resources", []):
        if isinstance(item, dict):
            resources.append({
                key: item.get(key)
                for key in ("kind", "name", "id", "status", "pid")
                if item.get(key) is not None
            })
    shutdown_raw = raw.get("shutdown")
    shutdown = None
    if isinstance(shutdown_raw, dict):
        shutdown = {
            key: shutdown_raw.get(key)
            for key in ("status", "completed_at", "residuals", "artifacts_deleted")
            if shutdown_raw.get(key) is not None
        }
    return {
        "schema_version": DASHBOARD_SCHEMA_VERSION,
        "ok": raw.get("ok") is True,
        "plan_id": raw.get("plan_id"),
        "observed_at": raw.get("observed_at"),
        "observation_only": True,
        "canonical": {
            "controller": _safe_plan_file(canonical.get("controller"), plan_dir),
            "controller_status": canonical.get("controller_status"),
            "staged_state": _safe_plan_file(canonical.get("staged_state"), plan_dir),
            "staged_status": canonical.get("staged_status"),
            "durable_head": _safe_plan_file(canonical.get("durable_head"), plan_dir),
            "durable_projection": _safe_plan_file(
                canonical.get("durable_projection"), plan_dir,
            ),
        },
        "schedulers": schedulers,
        "workers": workers,
        "mismatches": mismatches,
        "shutdown": shutdown,
        "declared_resources": resources,
        "dossier": {"api_path": "/api/dossier", "transition_authority": False},
    }


class DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        plan_dir: Path,
        assets_dir: Path,
        snapshot_provider: Callable[[], dict[str, Any]],
    ) -> None:
        self.plan_dir = plan_dir.resolve(strict=True)
        if not self.plan_dir.is_dir():
            raise DashboardError("plan_dir must resolve to one directory")
        self.assets_dir = assets_dir.resolve(strict=True)
        if not (self.assets_dir / "index.html").is_file():
            raise DashboardError("compiled dashboard index is missing")
        self.snapshot_provider = snapshot_provider
        super().__init__(address, DashboardHandler)


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _host_allowed(self) -> bool:
        host = self.headers.get("Host", "")
        if not host:
            return False
        if host.startswith("["):
            hostname = host.split("]", 1)[0] + "]"
        else:
            hostname = host.rsplit(":", 1)[0] if ":" in host else host
        return hostname.lower() in {"127.0.0.1", "localhost", "[::1]"}

    def _send(
        self,
        status: int,
        body: bytes = b"",
        *,
        content_type: str = "application/json; charset=utf-8",
        cache_control: str = "no-store",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _json(self, status: int, value: dict[str, Any]) -> None:
        self._send(
            status,
            json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
        )

    def _reject_method(self) -> None:
        self._json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {"ok": False, "error": "dashboard is GET/HEAD observation-only"},
        )

    do_POST = _reject_method
    do_PUT = _reject_method
    do_PATCH = _reject_method
    do_DELETE = _reject_method

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if not self._host_allowed():
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid Host"})
            return
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        if ".." in Path(path).parts or "\\" in path or "\x00" in path:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid path"})
            return
        try:
            if path == "/api/snapshot":
                raw = self.server.snapshot_provider()
                self._json(HTTPStatus.OK, public_snapshot(raw, self.server.plan_dir))
                return
            if path == "/api/dossier":
                self._serve_dossier()
                return
            if path.startswith("/api/logs/"):
                self._serve_log(path.removeprefix("/api/logs/"))
                return
            if path.startswith("/api/"):
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "unknown route"})
                return
            if path == "/favicon.ico":
                self._send(HTTPStatus.NO_CONTENT)
                return
            self._serve_asset(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "error": "observation unavailable", "detail": type(exc).__name__},
            )

    def _serve_dossier(self) -> None:
        path = self.server.plan_dir / "state" / "research-dossier.md"
        if not path.is_file():
            self._json(HTTPStatus.NOT_FOUND, {
                "ok": False,
                "present": False,
                "projection": True,
                "transition_authority": False,
            })
            return
        raw = path.read_bytes()
        truncated = len(raw) > MAX_DOSSIER_BYTES
        content = raw[:MAX_DOSSIER_BYTES].decode("utf-8", errors="replace")
        self._json(HTTPStatus.OK, {
            "ok": True,
            "present": True,
            "projection": True,
            "transition_authority": False,
            "relative_path": "state/research-dossier.md",
            "sha256": _sha256_file(path),
            "size_bytes": len(raw),
            "truncated": truncated,
            "content": content,
        })

    def _serve_log(self, token: str) -> None:
        if not token or len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "unbound log"})
            return
        logs = bound_logs(self.server.snapshot_provider(), self.server.plan_dir)
        item = logs.get(token)
        if item is None or not item.path.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "unbound log"})
            return
        size = item.path.stat().st_size
        read_size = min(size, DEFAULT_LOG_BYTES, MAX_LOG_BYTES)
        with item.path.open("rb") as handle:
            if size > read_size:
                handle.seek(size - read_size)
            body = handle.read(read_size)
        self._send(
            HTTPStatus.OK,
            body,
            content_type="text/plain; charset=utf-8",
            extra_headers={
                "X-Log-Truncated": "true" if size > read_size else "false",
                "X-Log-SHA256": _sha256_file(item.path),
            },
        )

    def _serve_asset(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        target = (self.server.assets_dir / relative).resolve()
        if not _within(target, self.server.assets_dir) or not target.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "asset not found"})
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        immutable = target.parent.name == "assets" and target.name != "index.html"
        self._send(
            HTTPStatus.OK,
            body,
            content_type=f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type,
            cache_control="public, max-age=31536000, immutable" if immutable else "no-store",
        )


def make_dashboard_server(
    *,
    host: str,
    port: int,
    plan_dir: Path,
    assets_dir: Path,
    snapshot_provider: Callable[[], dict[str, Any]],
) -> DashboardHTTPServer:
    require_loopback_host(host)
    if not 0 <= port <= 65535:
        raise DashboardError("dashboard port must be between 0 and 65535")
    return DashboardHTTPServer(
        (host, port),
        plan_dir=plan_dir,
        assets_dir=assets_dir,
        snapshot_provider=snapshot_provider,
    )
