#!/usr/bin/env python3
"""Fail-closed, read-only FOLO source adapter for AutoResearch Radar.

The ``candidates`` phase reads a disposable snapshot of FOLO's local cache and
never changes source state.  The ``record`` phase is the sole state writer: it
accepts exactly one validated decision per emitted candidate and commits the
new state with compare-and-swap and an atomic replace.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import secrets
import shutil
import sqlite3
import stat
import sys
import tempfile
import types
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.parse import quote

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - wrapper installs the pin
    yaml = None

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ModuleNotFoundError:  # pragma: no cover - wrapper installs the pins
    InvalidSignature = None
    Ed25519PublicKey = None


DEFAULT_LEVELDB = Path.home() / (
    "Library/Application Support/Folo/IndexedDB/"
    "app_folo.is_0.indexeddb.leveldb"
)
DATABASE_NAME = "WA_SQLITE"
OBJECT_STORE_NAME = "blocks"
DATABASE_PATH = "/follow.db"
SCHEMA_VERSION = 1
MAX_BODY_CHARS = 20_000
MAX_CANDIDATES = 500
MAX_SQLITE_BYTES = 8 * 1024 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")
DECISIONS = {"forwarded", "ignored", "deferred"}
EVIDENCE_LEVELS = {
    "summary-only",
    "primary-opened",
    "method-checked",
    "result-checked",
}
CONTRACT_FITS = {"in-scope", "adjacent", "out-of-scope", "unknown"}
SIGNAL_TYPES = {
    "method-opportunity",
    "evaluator",
    "benchmark",
    "dataset",
    "novelty-threat",
    "contradiction",
    "background",
}
VERIFICATION_STATUSES = {
    "unverified",
    "primary-verified",
    "qualified",
    "contradicted",
}


class FoloSourceError(RuntimeError):
    """Expected, user-facing source adapter failure."""


class FoloCommitIndeterminate(FoloSourceError):
    """The atomic replace occurred but directory durability is indeterminate."""

    def __init__(self, message: str, observed_status: str) -> None:
        super().__init__(message)
        self.observed_status = observed_status
        self.pointer_status = observed_status


def _resolved(path: str | os.PathLike[str] | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _reject_symlink(path: str | os.PathLike[str] | Path, field: str) -> Path:
    raw = Path(path).expanduser()
    try:
        absolute = raw if raw.is_absolute() else Path.cwd() / raw
        components = absolute.parts
        current = Path(components[0]) if components else absolute
        for component in components[1:]:
            current = current / component
            if current.is_symlink():
                raise FoloSourceError(
                    f"{field} path must not contain a symlink: {current}"
                )
    except OSError as exc:
        raise FoloSourceError(f"unable to inspect {field}: {raw}") from exc
    return raw.resolve(strict=False)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def leveldb_path(override: str | os.PathLike[str] | None = None) -> Path:
    raw = override or os.environ.get("FOLO_LEVELDB_PATH")
    path = _reject_symlink(raw or DEFAULT_LEVELDB, "FOLO LevelDB directory")
    if not path.is_dir():
        raise FoloSourceError(f"FOLO LevelDB directory does not exist: {path}")
    if not (path / "CURRENT").is_file():
        raise FoloSourceError(
            f"not a Chromium LevelDB directory (CURRENT is missing): {path}"
        )
    return path


def _protected_folo_roots() -> tuple[Path, ...]:
    roots = {_resolved(DEFAULT_LEVELDB.parents[1])}
    for variable in ("FOLO_APP_SUPPORT", "FOLO_LEVELDB_PATH"):
        value = os.environ.get(variable)
        if value:
            roots.add(_resolved(value))
    return tuple(roots)


def _refuse_live_write(path: Path, additional_roots: Iterable[Path] = ()) -> None:
    target = _resolved(path)
    roots = (*_protected_folo_roots(), *(_resolved(root) for root in additional_roots))
    for root in roots:
        if target == root or _is_within(target, root):
            raise FoloSourceError(
                f"refusing to write inside protected FOLO data: {target}"
            )


def _system_scratch_root() -> Path:
    candidate = Path("/private/tmp") if Path("/private/tmp").is_dir() else Path("/tmp")
    try:
        root = candidate.resolve(strict=True)
    except OSError as exc:
        raise FoloSourceError(f"system scratch root is unavailable: {candidate}") from exc
    if not root.is_dir():
        raise FoloSourceError(f"system scratch root is not a directory: {root}")
    return root


def _safe_scratch_root(protected_roots: Iterable[Path] = ()) -> Path:
    root = _system_scratch_root()
    for protected in (*_protected_folo_roots(), *protected_roots):
        protected = _resolved(protected)
        if root == protected or _is_within(root, protected):
            raise FoloSourceError("system scratch root overlaps protected data")
    return root


@contextlib.contextmanager
def _snapshot_temp_directory(source: Path) -> Iterator[Path]:
    scratch = _system_scratch_root()
    protected = (*_protected_folo_roots(), _resolved(source))
    if any(scratch == root or _is_within(scratch, root) for root in protected):
        raise FoloSourceError("system scratch root overlaps protected FOLO data")
    with tempfile.TemporaryDirectory(
        prefix="autoresearch-folo-readonly-", dir=scratch
    ) as temp_name:
        temp_root = Path(temp_name).resolve(strict=True)
        if any(temp_root == root or _is_within(temp_root, root) for root in protected):
            raise FoloSourceError("snapshot directory overlaps protected FOLO data")
        yield temp_root


def _import_indexeddb_reader() -> Any:
    # These optional cache decompressors are imported by the reader facade but
    # are not used by its IndexedDB path.  Stubs keep the --no-deps runtime
    # deliberately narrow.
    for optional_name in ("brotli", "zstd"):
        sys.modules.setdefault(optional_name, types.ModuleType(optional_name))
    try:
        from ccl_chromium_reader import ccl_chromium_indexeddb
    except ModuleNotFoundError as exc:
        raise FoloSourceError(
            "CCL Chromium Reader is unavailable; run through the folo-source wrapper"
        ) from exc
    return ccl_chromium_indexeddb


def _record_block(record: Any) -> tuple[int, bytes] | None:
    value = record.value
    if not record.is_live or not isinstance(value, Mapping):
        return None
    if value.get("path") != DATABASE_PATH:
        return None
    try:
        offset_number = float(value["offset"])
        if (
            not math.isfinite(offset_number)
            or offset_number < 0
            or not offset_number.is_integer()
        ):
            raise ValueError("offset is not a non-negative integer")
        offset = int(offset_number)
        data = bytes(value["data"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise FoloSourceError("a live /follow.db block is malformed") from exc
    if not data:
        raise FoloSourceError("a live /follow.db block is empty")
    if offset + len(data) > MAX_SQLITE_BYTES:
        raise FoloSourceError("reconstructed /follow.db exceeds the 8 GiB limit")
    return offset, data


def _select_live_blocks(records: Iterable[Any]) -> dict[int, tuple[int, bytes]]:
    # CCL's ``is_live`` describes the state of one LevelDB operation, not the
    # final state of an IndexedDB key.  Collapse the complete operation history
    # by raw key first so a newer tombstone suppresses every older live value.
    latest_by_key: dict[bytes, tuple[int, Any]] = {}
    for record in records:
        try:
            sequence = int(record.ldb_seq_no)
            raw_key = bytes(record.key.raw_key)
        except (AttributeError, TypeError, ValueError, OverflowError) as exc:
            raise FoloSourceError(
                "an IndexedDB block operation has invalid key provenance"
            ) from exc
        if sequence < 0 or not raw_key:
            raise FoloSourceError(
                "an IndexedDB block operation has invalid key provenance"
            )
        prior = latest_by_key.get(raw_key)
        if prior is not None and sequence == prior[0]:
            prior_record = prior[1]
            try:
                identical = (
                    bool(record.is_live) == bool(prior_record.is_live)
                    and record.value == prior_record.value
                )
            except Exception as exc:
                raise FoloSourceError(
                    "conflicting IndexedDB operations share a key and sequence"
                ) from exc
            if not identical:
                raise FoloSourceError(
                    "conflicting IndexedDB operations share a key and sequence"
                )
        if prior is None or sequence > prior[0]:
            latest_by_key[raw_key] = (sequence, record)

    selected: dict[int, tuple[int, bytes]] = {}
    for sequence, record in latest_by_key.values():
        block = _record_block(record)
        if block is None:
            continue
        offset, data = block
        prior = selected.get(offset)
        if prior is not None and sequence == prior[0] and data != prior[1]:
            raise FoloSourceError(
                "conflicting live /follow.db blocks share an offset and sequence"
            )
        if prior is None or sequence > prior[0]:
            selected[offset] = (sequence, data)
    if not selected:
        raise FoloSourceError("no live /follow.db blocks found in WA_SQLITE/blocks")
    return selected


def _write_reconstructed_sqlite(
    blocks: Mapping[int, tuple[int, bytes]], destination: Path
) -> int:
    _refuse_live_write(destination)
    with destination.open("w+b") as handle:
        for offset, (_sequence, data) in sorted(blocks.items()):
            handle.seek(offset)
            handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return destination.stat().st_size


def _open_readonly_sqlite(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FoloSourceError(f"SQLite database does not exist: {path}")
    uri_path = quote(str(path.resolve()), safe="/")
    connection = sqlite3.connect(f"file:{uri_path}?mode=ro&immutable=1", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def inspect_sqlite(path: Path) -> dict[str, Any]:
    try:
        with contextlib.closing(_open_readonly_sqlite(path)) as connection:
            check = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
            if check != ["ok"]:
                detail = "; ".join(check[:3]) if check else "no result"
                raise FoloSourceError(f"SQLite quick_check failed: {detail}")
            counts: dict[str, int] = {}
            for table in ("entries", "feeds", "subscriptions"):
                present = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                if not present:
                    raise FoloSourceError(f"SQLite is missing required table: {table}")
                counts[table] = int(
                    connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                )
    except FoloSourceError:
        raise
    except sqlite3.Error as exc:
        raise FoloSourceError(
            f"unable to validate reconstructed SQLite ({type(exc).__name__})"
        ) from exc
    return {"quick_check": "ok", "tables": counts, "sqlite_bytes": path.stat().st_size}


@contextlib.contextmanager
def reconstructed_database(source: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    source = leveldb_path(source)
    reader = _import_indexeddb_reader()
    with _snapshot_temp_directory(source) as temp_root:
        snapshot = temp_root / source.name
        before_fingerprint, before_files = _directory_fingerprint(source)
        try:
            shutil.copytree(source, snapshot)
        except OSError as exc:
            raise FoloSourceError(
                f"unable to copy FOLO cache into a disposable snapshot ({type(exc).__name__})"
            ) from exc
        after_fingerprint, after_files = _directory_fingerprint(source)
        snapshot_fingerprint, snapshot_files = _directory_fingerprint(snapshot)
        if (
            before_fingerprint != after_fingerprint
            or before_files != after_files
            or before_fingerprint != snapshot_fingerprint
            or before_files != snapshot_files
        ):
            raise FoloSourceError(
                "FOLO cache changed while the disposable snapshot was copied"
            )
        wrapper = None
        try:
            wrapper = reader.WrappedIndexDB(snapshot)
            if DATABASE_NAME not in wrapper:
                raise FoloSourceError(f"IndexedDB database is missing: {DATABASE_NAME}")
            database = wrapper[DATABASE_NAME]
            if OBJECT_STORE_NAME not in database:
                raise FoloSourceError(
                    f"IndexedDB object store is missing: {OBJECT_STORE_NAME}"
                )
            blocks = _select_live_blocks(
                database[OBJECT_STORE_NAME].iterate_records()
            )
        except FoloSourceError:
            raise
        except Exception as exc:
            raise FoloSourceError(
                f"unable to decode disposable IndexedDB snapshot ({type(exc).__name__})"
            ) from exc
        finally:
            if wrapper is not None:
                wrapper.close()
        sqlite_path = temp_root / "follow.db"
        _write_reconstructed_sqlite(blocks, sqlite_path)
        details = inspect_sqlite(sqlite_path)
        details.update(
            {
                "live_blocks": len(blocks),
                "snapshot_files": sum(1 for item in snapshot.rglob("*") if item.is_file()),
                "source_snapshot_sha256": snapshot_fingerprint,
                "database_snapshot_sha256": _sha256_file(sqlite_path),
            }
        )
        yield sqlite_path, details


class _PlainTextParser(HTMLParser):
    _BLOCKS = {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
        "dt", "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5",
        "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
        "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    }
    _IGNORED = {"script", "style", "template", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.lower()
        if tag in self._IGNORED:
            self.ignored_depth += 1
        elif not self.ignored_depth and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._IGNORED:
            self.ignored_depth = max(0, self.ignored_depth - 1)
        elif not self.ignored_depth and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def _html_to_text(value: Any) -> str:
    if value is None:
        return ""
    parser = _PlainTextParser()
    try:
        parser.feed(str(value))
        parser.close()
        raw = "".join(parser.parts)
    except Exception:
        raw = str(value)
    lines = [" ".join(line.split()) for line in raw.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _preferred_content(row: Mapping[str, Any]) -> tuple[str, str]:
    for column in ("source_content", "content", "description"):
        cleaned = _html_to_text(row.get(column))
        if cleaned:
            return cleaned[:MAX_BODY_CHARS], column
    return "", "none"


def _timestamp_ms(value: Any, field: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FoloSourceError(f"entry has invalid {field}") from exc
    if not math.isfinite(number) or number < 0:
        raise FoloSourceError(f"entry has invalid {field}")
    if number < 100_000_000_000:
        number *= 1_000
    elif number > 100_000_000_000_000:
        number /= 1_000
    return int(number)


def iso_utc(milliseconds: int) -> str:
    """Return a stable UTC ISO-8601 timestamp for milliseconds since epoch."""
    try:
        return (
            dt.datetime.fromtimestamp(milliseconds / 1000, tz=dt.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (OSError, OverflowError, ValueError) as exc:
        raise FoloSourceError("timestamp is outside the supported range") from exc


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FoloSourceError("record is not canonical JSON data") from exc


def _pretty_json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FoloSourceError("record is not JSON-serializable") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise FoloSourceError(f"unable to hash artifact: {path}") from exc
    return digest.hexdigest()


def _read_regular_bytes(path: Path, field: str) -> bytes:
    path = _reject_symlink(path, field)
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise FoloSourceError(
                f"{field} must be a single-link regular file"
            )
        data = path.read_bytes()
        after = path.stat()
    except FoloSourceError:
        raise
    except OSError as exc:
        raise FoloSourceError(f"unable to read {field}: {path}") from exc
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_nlink,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_nlink,
    )
    if identity_before != identity_after:
        raise FoloSourceError(f"{field} changed while reading")
    return data


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise FoloSourceError(f"{field} must be a lowercase sha256")
    return value


def _directory_fingerprint(root: Path) -> tuple[str, list[dict[str, Any]]]:
    """Return a content manifest for a live or disposable LevelDB directory."""
    root = root.resolve(strict=True)
    records: list[dict[str, Any]] = []
    try:
        paths = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
        for path in paths:
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise FoloSourceError(
                    f"FOLO cache snapshot contains an unsupported symlink: {relative}"
                )
            if path.is_dir():
                continue
            if not path.is_file():
                raise FoloSourceError(
                    f"FOLO cache snapshot contains an unsupported file: {relative}"
                )
            stat_before = path.stat()
            digest = _sha256_file(path)
            stat_after = path.stat()
            before_identity = (
                stat_before.st_dev,
                stat_before.st_ino,
                stat_before.st_size,
                stat_before.st_mtime_ns,
            )
            after_identity = (
                stat_after.st_dev,
                stat_after.st_ino,
                stat_after.st_size,
                stat_after.st_mtime_ns,
            )
            if before_identity != after_identity:
                raise FoloSourceError(
                    f"FOLO cache changed while fingerprinting: {relative}"
                )
            records.append(
                {"path": relative, "bytes": stat_after.st_size, "sha256": digest}
            )
    except FoloSourceError:
        raise
    except OSError as exc:
        raise FoloSourceError(
            f"unable to fingerprint FOLO cache ({type(exc).__name__})"
        ) from exc
    return _sha256_bytes(_canonical_bytes({"files": records})), records


def candidate_digest(candidate: Mapping[str, Any]) -> str:
    """Hash candidate content, excluding its self-referential digest field."""
    payload = dict(candidate)
    payload.pop("candidate_sha256", None)
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _empty_state(source_instance_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "folo-local",
        "source_instance_id": source_instance_id,
        "processed": {},
        "pending": {},
    }


def _validate_state_payload(
    payload: Any, source_instance_id: str | None = None
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise FoloSourceError("state must be a JSON object")
    expected = {
        "schema_version": SCHEMA_VERSION,
        "source": "folo-local",
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise FoloSourceError(f"state.{field} must equal {value!r}")
    actual_instance = payload.get("source_instance_id")
    if not isinstance(actual_instance, str) or not actual_instance:
        raise FoloSourceError("state.source_instance_id must be a non-empty string")
    if source_instance_id and actual_instance != source_instance_id:
        raise FoloSourceError("state source_instance_id does not match the source")
    if set(payload) != {
        "schema_version", "source", "source_instance_id", "processed", "pending"
    }:
        raise FoloSourceError("state contains unexpected fields")
    if not isinstance(payload.get("processed"), dict):
        raise FoloSourceError("state.processed must be an object")
    if not isinstance(payload.get("pending"), dict):
        raise FoloSourceError("state.pending must be an object")
    if set(payload["processed"]) & set(payload["pending"]):
        raise FoloSourceError("state ids must not be both processed and pending")
    return payload


def _load_state(path: Path, source_instance_id: str | None = None) -> dict[str, Any]:
    if not path.exists():
        if not source_instance_id:
            raise FoloSourceError("source_instance_id is required to initialize state")
        return _empty_state(source_instance_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FoloSourceError(f"unable to read state JSON: {path}") from exc
    return _validate_state_payload(payload, source_instance_id)


def _parse_utc(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise FoloSourceError(f"{field} must be a non-empty ISO-8601 timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FoloSourceError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise FoloSourceError(f"{field} must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def _validate_refresh_receipt_payload(
    payload: Mapping[str, Any],
    *,
    source_instance_id: str,
    source_snapshot_sha256: str | None = None,
    database_snapshot_sha256: str | None = None,
    now: dt.datetime | None = None,
    max_age_minutes: float = 30,
    profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an externally signed proof of a fresh official FOLO sync."""
    if not math.isfinite(max_age_minutes) or max_age_minutes <= 0:
        raise FoloSourceError("max_age_minutes must be positive and finite")
    if not isinstance(payload, dict):
        raise FoloSourceError("refresh receipt must be a JSON object")
    required = {
        "schema_version": SCHEMA_VERSION,
        "source": "folo-local",
        "source_instance_id": source_instance_id,
        "status": "synced",
        "timeline": "all",
        "pagination_complete": True,
        "cache_stable": True,
    }
    for field, expected in required.items():
        if payload.get(field) != expected:
            raise FoloSourceError(
                f"refresh receipt {field} must equal {expected!r}"
            )
    producer = payload.get("producer_identity")
    if not isinstance(producer, str) or not producer.strip():
        raise FoloSourceError("refresh receipt requires an external producer_identity")
    if producer in {"folo-source", "autoresearch-radar"}:
        raise FoloSourceError("refresh receipt cannot be self-attested by this adapter")
    if profile is None:
        raise FoloSourceError("refresh receipt verification requires a frozen Watch Profile")
    if producer != profile.get("trusted_producer_identity"):
        raise FoloSourceError("refresh receipt producer is not trusted by the Watch Profile")
    if (
        payload.get("profile_id") != profile.get("profile_id")
        or payload.get("profile_sha256") != profile.get("profile_sha256")
    ):
        raise FoloSourceError("refresh receipt is not bound to the Watch Profile")
    attestation = payload.get("attestation")
    if not isinstance(attestation, dict):
        raise FoloSourceError("refresh receipt requires an attestation object")
    if attestation.get("kind") != "folo-official-ui-refresh":
        raise FoloSourceError("refresh receipt attestation kind is invalid")
    if attestation.get("verified") is not True:
        raise FoloSourceError("refresh receipt attestation must be externally verified")
    attested_snapshot = _require_sha256(
        attestation.get("source_snapshot_sha256"),
        "refresh receipt attestation source_snapshot_sha256",
    )
    attested_database = _require_sha256(
        attestation.get("database_snapshot_sha256"),
        "refresh receipt attestation database_snapshot_sha256",
    )
    if source_snapshot_sha256 is not None:
        expected_snapshot = _require_sha256(
            source_snapshot_sha256, "expected source_snapshot_sha256"
        )
        if attested_snapshot != expected_snapshot:
            raise FoloSourceError(
                "refresh receipt does not bind the extracted cache snapshot"
            )
    if database_snapshot_sha256 is not None:
        expected_database = _require_sha256(
            database_snapshot_sha256, "expected database_snapshot_sha256"
        )
        if attested_database != expected_database:
            raise FoloSourceError(
                "refresh receipt does not bind the reconstructed database snapshot"
            )
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        raise FoloSourceError("receipt validation time must include a timezone")
    current = current.astimezone(dt.timezone.utc)
    refreshed = _parse_utc(payload.get("refreshed_at"), "refresh receipt refreshed_at")
    age = current - refreshed
    if age < dt.timedelta(minutes=-5):
        raise FoloSourceError("refresh receipt timestamp is in the future")
    if age > dt.timedelta(minutes=max_age_minutes):
        raise FoloSourceError("refresh receipt is stale")
    signature_hex = payload.get("signature_ed25519")
    if (
        not isinstance(signature_hex, str)
        or re.fullmatch(r"[0-9a-f]{128}", signature_hex) is None
    ):
        raise FoloSourceError("refresh receipt signature_ed25519 is invalid")
    signed_payload = dict(payload)
    signed_payload.pop("signature_ed25519", None)
    key_bytes = profile.get("ed25519_public_key_bytes")
    if not isinstance(key_bytes, bytes) or len(key_bytes) != 32:
        raise FoloSourceError("Watch Profile Ed25519 public key is unavailable")
    if Ed25519PublicKey is None or InvalidSignature is None:
        raise FoloSourceError(
            "cryptography is unavailable; run through the folo-source wrapper"
        )
    try:
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(
            bytes.fromhex(signature_hex), _canonical_bytes(signed_payload)
        )
    except (ValueError, InvalidSignature) as exc:
        raise FoloSourceError(
            "refresh receipt Ed25519 signature verification failed"
        ) from exc
    return dict(payload)


def validate_refresh_receipt(
    path: Path,
    *,
    source_instance_id: str,
    source_snapshot_sha256: str | None = None,
    database_snapshot_sha256: str | None = None,
    now: dt.datetime | None = None,
    max_age_minutes: float = 30,
    profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read and validate proof that the official FOLO UI completed a sync."""
    try:
        payload = json.loads(_read_regular_bytes(Path(path), "refresh receipt").decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FoloSourceError(f"unable to read refresh receipt: {path}") from exc
    return _validate_refresh_receipt_payload(
        payload,
        source_instance_id=source_instance_id,
        source_snapshot_sha256=source_snapshot_sha256,
        database_snapshot_sha256=database_snapshot_sha256,
        now=now,
        max_age_minutes=max_age_minutes,
        profile=profile,
    )


def _parse_mapping_bytes(data: bytes, path: Path, kind: str) -> dict[str, Any]:
    try:
        raw = data.decode("utf-8")
        if path.suffix.lower() == ".json":
            payload = json.loads(raw)
        else:
            if yaml is None:
                raise FoloSourceError(
                    "PyYAML is unavailable; run through the folo-source wrapper"
                )
            payload = yaml.safe_load(raw)
    except FoloSourceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise FoloSourceError(f"unable to read {kind}: {path}") from exc
    if not isinstance(payload, dict):
        raise FoloSourceError(f"{kind} must contain an object")
    return payload


def _load_mapping(path: Path, kind: str) -> dict[str, Any]:
    return _parse_mapping_bytes(_read_regular_bytes(path, kind), path, kind)


def _authority_artifact(
    profile_path: Path, value: Any, field: str
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise FoloSourceError(f"watch profile authority.{field} must be an object")
    identifier = _require_nonempty_text(
        value.get("id"), f"watch profile authority.{field}.id"
    )
    raw_path = value.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise FoloSourceError(
            f"watch profile authority.{field}.path must be non-empty"
        )
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise FoloSourceError(
            f"watch profile authority.{field}.path must be a contained relative path"
        )
    artifact_path = _reject_symlink(
        profile_path.parent / Path(*relative.parts),
        f"watch profile authority.{field}",
    )
    expected = _require_sha256(
        value.get("sha256"), f"watch profile authority.{field}.sha256"
    )
    artifact_bytes = _read_regular_bytes(
        artifact_path, f"watch profile authority.{field}"
    )
    if _sha256_bytes(artifact_bytes) != expected:
        raise FoloSourceError(
            f"watch profile authority.{field} artifact hash does not match"
        )
    return {"id": identifier, "path": raw_path, "sha256": expected}


def load_watch_profile(path: Path) -> dict[str, Any]:
    """Load the complete authority envelope and FOLO operational subset."""
    path = _reject_symlink(path, "Research Watch Profile")
    profile_bytes = _read_regular_bytes(path, "Research Watch Profile")
    payload = _parse_mapping_bytes(
        profile_bytes, path, "Research Watch Profile"
    )
    profile_id = payload.get("profile_id", payload.get("id"))
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise FoloSourceError("watch profile requires profile_id")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise FoloSourceError("watch profile schema_version is invalid")
    if payload.get("source") != "folo-local":
        raise FoloSourceError("watch profile source must be folo-local")
    authority = payload.get("authority")
    if not isinstance(authority, dict):
        raise FoloSourceError("watch profile requires authority envelope")
    research_brief = _authority_artifact(
        path, authority.get("research_brief"), "research_brief"
    )
    adaptation_plan = _authority_artifact(
        path, authority.get("adaptation_plan"), "adaptation_plan"
    )
    repository = authority.get("repository")
    if not isinstance(repository, dict):
        raise FoloSourceError("watch profile authority.repository must be an object")
    repository_id = _require_nonempty_text(
        repository.get("id"), "watch profile authority.repository.id"
    )
    repository_scope = repository.get("scope")
    if (
        repository_scope in (None, "", [], {})
        or isinstance(repository_scope, (bool, int, float))
    ):
        raise FoloSourceError("watch profile authority.repository.scope is invalid")
    contract = authority.get("experiment_contract")
    if not isinstance(contract, dict):
        raise FoloSourceError(
            "watch profile authority.experiment_contract must be an object"
        )
    contract_status = contract.get("status")
    if contract_status not in {"pre-contract", "frozen"}:
        raise FoloSourceError(
            "watch profile authority.experiment_contract.status is invalid"
        )
    contract_policy = contract.get("policy")
    if not isinstance(contract_policy, dict) or not contract_policy:
        raise FoloSourceError(
            "watch profile authority.experiment_contract.policy is required"
        )
    contract_ref: dict[str, Any]
    if contract_status == "frozen":
        contract_ref = {
            "status": contract_status,
            "policy": contract_policy,
            **_authority_artifact(path, contract, "experiment_contract"),
        }
    else:
        unexpected = set(contract) - {"status", "id", "policy"}
        if unexpected:
            raise FoloSourceError(
                "watch profile authority.experiment_contract pre-contract "
                f"contains forbidden fields: {sorted(unexpected)}"
            )
        contract_ref = {
            "status": contract_status,
            "policy": contract_policy,
            "id": _require_nonempty_text(
                contract.get("id"),
                "watch profile authority.experiment_contract.id",
            ),
        }
    contract_fit_rules = authority.get("contract_fit_rules")
    if not isinstance(contract_fit_rules, dict) or not contract_fit_rules:
        raise FoloSourceError("watch profile authority.contract_fit_rules is required")
    proposal_budget = authority.get("proposal_budget")
    if (
        isinstance(proposal_budget, bool)
        or not isinstance(proposal_budget, int)
        or proposal_budget <= 0
    ):
        raise FoloSourceError(
            "watch profile authority.proposal_budget must be a positive integer"
        )
    out_of_scope_action = authority.get("out_of_scope_action")
    if out_of_scope_action not in {"backlog", "reauthorize", "ignore"}:
        raise FoloSourceError(
            "watch profile authority.out_of_scope_action is invalid"
        )
    source_instance_id = payload.get("source_instance_id")
    if not isinstance(source_instance_id, str) or not source_instance_id:
        raise FoloSourceError("watch profile requires source_instance_id")
    source_scope = payload.get("source_scope")
    if not isinstance(source_scope, dict):
        raise FoloSourceError("watch profile requires source_scope")
    feed_ids = source_scope.get("authorized_feed_ids")
    if (
        not isinstance(feed_ids, list)
        or not feed_ids
        or not all(isinstance(value, str) and value for value in feed_ids)
        or len(set(feed_ids)) != len(feed_ids)
    ):
        raise FoloSourceError(
            "watch profile authorized_feed_ids must be a non-empty unique string array"
        )
    include_any = source_scope.get("query_terms")
    exclude_any = source_scope.get("excluded_terms", [])
    if (
        not isinstance(include_any, list)
        or not include_any
        or not all(isinstance(value, str) and value.strip() for value in include_any)
    ):
        raise FoloSourceError("watch profile source_scope.query_terms is required")
    if not isinstance(exclude_any, list) or not all(
        isinstance(value, str) and value.strip() for value in exclude_any
    ):
        raise FoloSourceError("watch profile source_scope.excluded_terms must be a string array")
    scan = payload.get("scan")
    if not isinstance(scan, dict):
        raise FoloSourceError("watch profile scan_bounds must be an object")
    max_hours = scan.get("hours")
    max_candidates = scan.get("limit")
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise FoloSourceError("watch profile requires policy")
    refresh_age = policy.get("refresh_max_age_minutes", 30)
    if isinstance(max_hours, bool) or not isinstance(max_hours, (int, float)):
        raise FoloSourceError("watch profile scan_bounds.max_hours is required")
    if not math.isfinite(float(max_hours)) or float(max_hours) < 0:
        raise FoloSourceError("watch profile max_hours must be non-negative and finite")
    if (
        isinstance(max_candidates, bool)
        or not isinstance(max_candidates, int)
        or not 1 <= max_candidates <= MAX_CANDIDATES
    ):
        raise FoloSourceError(
            f"watch profile max_candidates must be from 1 through {MAX_CANDIDATES}"
        )
    if (
        isinstance(refresh_age, bool)
        or not isinstance(refresh_age, (int, float))
        or not math.isfinite(float(refresh_age))
        or float(refresh_age) <= 0
    ):
        raise FoloSourceError("watch profile refresh_max_age_minutes must be positive")
    minimum_evidence_level = policy.get("minimum_evidence_level")
    if minimum_evidence_level not in EVIDENCE_LEVELS - {"summary-only"}:
        raise FoloSourceError(
            "watch profile minimum_evidence_level must require a primary source"
        )
    allowed_signal_types = policy.get("allowed_signal_types")
    if (
        not isinstance(allowed_signal_types, list)
        or not allowed_signal_types
        or not set(allowed_signal_types).issubset(SIGNAL_TYPES)
    ):
        raise FoloSourceError("watch profile allowed_signal_types is invalid")
    trust = payload.get("refresh_trust")
    if not isinstance(trust, dict):
        raise FoloSourceError("watch profile requires refresh_trust")
    producer_identity = _require_nonempty_text(
        trust.get("producer_identity"), "watch profile refresh producer_identity"
    )
    raw_key_path = trust.get("ed25519_public_key_path")
    if not isinstance(raw_key_path, str) or not raw_key_path:
        raise FoloSourceError(
            "watch profile requires refresh_trust.ed25519_public_key_path"
        )
    key_relative = PurePosixPath(raw_key_path)
    if (
        key_relative.is_absolute()
        or any(part in {"", ".", ".."} for part in key_relative.parts)
    ):
        raise FoloSourceError(
            "watch profile Ed25519 public key path must be contained and relative"
        )
    key_path = _reject_symlink(
        path.parent / Path(*key_relative.parts),
        "Watch Profile Ed25519 public key",
    )
    if not key_path.is_file():
        raise FoloSourceError(
            "watch profile Ed25519 public key path is not a regular file"
        )
    key_sha256 = _require_sha256(
        trust.get("ed25519_public_key_sha256"),
        "watch profile Ed25519 public key hash",
    )
    key_bytes = _read_regular_bytes(key_path, "Watch Profile Ed25519 public key")
    if _sha256_bytes(key_bytes) != key_sha256:
        raise FoloSourceError("watch profile Ed25519 public key hash does not match")
    if len(key_bytes) != 32:
        raise FoloSourceError("watch profile Ed25519 public key must be 32 raw bytes")
    return {
        "profile_id": profile_id.strip(),
        "profile_sha256": _sha256_bytes(profile_bytes),
        "profile_path": str(path),
        "profile_bytes": profile_bytes,
        "authority": {
            "research_brief": research_brief,
            "repository": {"id": repository_id, "scope": repository_scope},
            "adaptation_plan": adaptation_plan,
            "experiment_contract": contract_ref,
            "contract_fit_rules": contract_fit_rules,
            "proposal_budget": proposal_budget,
            "out_of_scope_action": out_of_scope_action,
        },
        "authority_sha256": _sha256_bytes(_canonical_bytes(authority)),
        "source_instance_id": source_instance_id,
        "authorized_feed_ids": sorted(feed_ids),
        "query_scope": {
            "include_any": [value.strip().casefold() for value in include_any],
            "exclude_any": [value.strip().casefold() for value in exclude_any],
        },
        "max_hours": float(max_hours),
        "max_candidates": max_candidates,
        "refresh_max_age_minutes": float(refresh_age),
        "minimum_evidence_level": minimum_evidence_level,
        "allowed_signal_types": sorted(set(allowed_signal_types)),
        "trusted_producer_identity": producer_identity,
        "ed25519_public_key_path": str(key_path),
        "ed25519_public_key_relative_path": raw_key_path,
        "ed25519_public_key_sha256": key_sha256,
        "ed25519_public_key_bytes": key_bytes,
    }


def extract_candidates(
    database_path: Path,
    *,
    state_path: Path,
    source_instance_id: str,
    hours: float = 72,
    limit: int = MAX_CANDIDATES,
    now_ms: int | None = None,
    authorized_feed_ids: Sequence[str] | None = None,
    query_scope: Mapping[str, Sequence[str]] | None = None,
    profile_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Read unseen recent entries from subscribed feeds without mutating state."""
    if profile_path is not None:
        frozen_profile = load_watch_profile(profile_path)
        if source_instance_id != frozen_profile["source_instance_id"]:
            raise FoloSourceError("source_instance_id does not match profile")
        if hours > frozen_profile["max_hours"] or limit > frozen_profile["max_candidates"]:
            raise FoloSourceError("candidate extraction exceeds profile scan bounds")
        authorized_feed_ids = frozen_profile["authorized_feed_ids"]
        query_scope = frozen_profile["query_scope"]
    if not isinstance(source_instance_id, str) or not source_instance_id:
        raise FoloSourceError("source_instance_id must be a non-empty string")
    if not math.isfinite(hours) or hours < 0:
        raise FoloSourceError("hours must be non-negative and finite")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_CANDIDATES:
        raise FoloSourceError(f"limit must be between 1 and {MAX_CANDIDATES}")
    if authorized_feed_ids is not None:
        if (
            not isinstance(authorized_feed_ids, Sequence)
            or isinstance(authorized_feed_ids, (str, bytes))
            or not authorized_feed_ids
            or not all(isinstance(value, str) and value for value in authorized_feed_ids)
        ):
            raise FoloSourceError("authorized_feed_ids must be a non-empty string array")
        if len(set(authorized_feed_ids)) != len(authorized_feed_ids):
            raise FoloSourceError("authorized_feed_ids must not contain duplicates")
        authorized_feeds = set(authorized_feed_ids)
    else:
        # Kept only for pure extraction unit calls. Production extraction always
        # supplies the Adapter-issued profile scope.
        authorized_feeds = None
    include_terms: tuple[str, ...] = ()
    exclude_terms: tuple[str, ...] = ()
    if query_scope is not None:
        raw_include = query_scope.get("include_any")
        raw_exclude = query_scope.get("exclude_any", [])
        if (
            not isinstance(raw_include, Sequence)
            or isinstance(raw_include, (str, bytes))
            or not raw_include
            or not all(isinstance(value, str) and value for value in raw_include)
        ):
            raise FoloSourceError("query_scope.include_any must be a non-empty string array")
        if (
            not isinstance(raw_exclude, Sequence)
            or isinstance(raw_exclude, (str, bytes))
            or not all(isinstance(value, str) and value for value in raw_exclude)
        ):
            raise FoloSourceError("query_scope.exclude_any must be a string array")
        include_terms = tuple(value.casefold() for value in raw_include)
        exclude_terms = tuple(value.casefold() for value in raw_exclude)
    state = _load_state(_resolved(state_path), source_instance_id)
    processed = set(state["processed"])
    pending = state["pending"]
    current_ms = (
        int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
        if now_ms is None
        else int(now_ms)
    )
    threshold = current_ms - int(hours * 60 * 60 * 1000)
    sql = """
        SELECT e.id AS entry_id, e.feed_id, e.title, e.url, e.author,
               e.inserted_at, e.published_at, e.source_content, e.content,
               e.description, f.title AS feed_title, f.url AS feed_url,
               f.site_url AS feed_site_url
        FROM entries AS e
        JOIN feeds AS f ON f.id = e.feed_id
        WHERE EXISTS (
            SELECT 1 FROM subscriptions AS s
            WHERE s.feed_id = e.feed_id AND s.type = 'feed'
        )
    """
    try:
        inspect_sqlite(_resolved(database_path))
        with contextlib.closing(_open_readonly_sqlite(_resolved(database_path))) as connection:
            connection.row_factory = sqlite3.Row
            rows = list(connection.execute(sql))
    except FoloSourceError:
        raise
    except sqlite3.Error as exc:
        raise FoloSourceError(
            f"unable to query FOLO candidates ({type(exc).__name__})"
        ) from exc

    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sqlite_row in rows:
        row = dict(sqlite_row)
        if authorized_feeds is not None and str(row["feed_id"]) not in authorized_feeds:
            continue
        entry_id = str(row["entry_id"])
        identifier = f"folo:{entry_id}"
        if identifier in processed or identifier in seen:
            continue
        pending_record = pending.get(identifier)
        retry_due = False
        if pending_record is not None:
            if not isinstance(pending_record, dict):
                raise FoloSourceError(f"state.pending.{identifier} must be an object")
            retry = _parse_utc(
                pending_record.get("retry_after"), f"state.pending.{identifier}.retry_after"
            )
            if current_ms < int(retry.timestamp() * 1000):
                continue
            retry_due = True
        inserted_ms = _timestamp_ms(row["inserted_at"], "inserted_at")
        published_ms = _timestamp_ms(row["published_at"], "published_at")
        effective_ms = max(inserted_ms, published_ms)
        # A due deferred item must reappear even if its original publication
        # has since aged beyond the ordinary discovery window.
        if (effective_ms < threshold and not retry_due) or effective_ms > current_ms:
            continue
        body, content_source = _preferred_content(row)
        if query_scope is not None and not _candidate_matches_query_scope(
            {
                "title": row.get("title"),
                "body": body,
                "author": row.get("author"),
                "url": row.get("url"),
                "feed_title": row.get("feed_title"),
            },
            {"include_any": include_terms, "exclude_any": exclude_terms},
        ):
            continue
        candidate: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "id": identifier,
            "source": "folo-local",
            "source_instance_id": source_instance_id,
            "entry_id": entry_id,
            "feed_id": str(row["feed_id"]),
            "feed_title": row["feed_title"],
            "feed_url": row["feed_url"],
            "feed_site_url": row["feed_site_url"],
            "title": row["title"],
            "url": row["url"],
            "author": row["author"],
            "inserted_at": iso_utc(inserted_ms),
            "published_at": iso_utc(published_ms),
            "effective_at": iso_utc(effective_ms),
            "effective_at_ms": effective_ms,
            "content_source": content_source,
            "body": body,
        }
        if retry_due:
            prior_digest = pending_record.get("decision_sha256")
            _require_sha256(
                prior_digest, f"state.pending.{identifier}.decision_sha256"
            )
            candidate["prior_decision_sha256"] = prior_digest
        candidate["candidate_sha256"] = candidate_digest(candidate)
        output.append(candidate)
        seen.add(identifier)
    output.sort(key=lambda item: (-item["effective_at_ms"], item["id"]))
    return output[:limit]


def _candidate_matches_query_scope(
    candidate: Mapping[str, Any], query_scope: Mapping[str, Sequence[str]]
) -> bool:
    searchable = "\n".join(
        str(candidate.get(field) or "")
        for field in ("title", "body", "author", "url", "feed_title")
    ).casefold()
    include_terms = tuple(value.casefold() for value in query_scope["include_any"])
    exclude_terms = tuple(value.casefold() for value in query_scope.get("exclude_any", []))
    return any(term in searchable for term in include_terms) and not any(
        term in searchable for term in exclude_terms
    )


def _read_jsonl(path: Path, kind: str) -> list[dict[str, Any]]:
    try:
        raw = _read_regular_bytes(path, kind).decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise FoloSourceError(f"unable to read {kind}: {path}") from exc
    return _read_jsonl_text(raw, kind, path)


def _read_jsonl_bytes(data: bytes, kind: str, path: Path) -> list[dict[str, Any]]:
    try:
        raw = data.decode("utf-8")
    except UnicodeError as exc:
        raise FoloSourceError(f"unable to decode {kind}: {path}") from exc
    return _read_jsonl_text(raw, kind, path)


def _read_jsonl_text(raw: str, kind: str, path: Path) -> list[dict[str, Any]]:
    lines = raw.splitlines()
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FoloSourceError(
                f"invalid JSON in {kind} at line {line_number}: {path}"
            ) from exc
        if not isinstance(record, dict):
            raise FoloSourceError(f"{kind} line {line_number} must be an object")
        records.append(record)
    return records


def _unique_by_id(
    records: Sequence[dict[str, Any]], kind: str
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        identifier = record.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise FoloSourceError(f"every {kind} must have a non-empty string id")
        if identifier in indexed:
            raise FoloSourceError(f"duplicate {kind} id: {identifier}")
        indexed[identifier] = record
    return indexed


def _aliases(first: Path, second: Path) -> bool:
    if first == second:
        return True
    try:
        return first.samefile(second)
    except OSError:
        return False


def _artifact_path(
    raw: str,
    root: Path,
    identifier: str,
    protected_roots: Iterable[Path] = (),
) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = _reject_symlink(candidate, f"decision {identifier} receipt")
    if not _is_within(candidate, root):
        raise FoloSourceError(
            f"decision {identifier} receipt escapes artifact_root: {raw}"
        )
    if not candidate.is_file():
        raise FoloSourceError(
            f"decision {identifier} receipt is not a regular file: {raw}"
        )
    for protected in protected_roots:
        protected = _resolved(protected)
        if candidate == protected or _is_within(candidate, protected):
            raise FoloSourceError(
                f"decision {identifier} receipt is inside protected source data"
            )
    return candidate


def _hashed_artifact(
    receipt: Any,
    root: Path,
    identifier: str,
    protected_roots: Iterable[Path] = (),
    *,
    anchor: _AnchoredArtifacts | None = None,
) -> tuple[dict[str, Any], Path, bytes]:
    if not isinstance(receipt, dict):
        raise FoloSourceError(
            f"decision {identifier} receipts must be hashed artifact descriptors"
        )
    descriptor = dict(receipt)
    raw_path = descriptor.get("path", descriptor.get("artifact"))
    if not isinstance(raw_path, str) or not raw_path:
        raise FoloSourceError(
            f"decision {identifier} receipt requires an artifact path"
        )
    expected_sha256 = descriptor.get("sha256")
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise FoloSourceError(
            f"decision {identifier} receipt requires a lowercase sha256"
        )
    role = descriptor.get("role")
    if not isinstance(role, str) or not role:
        raise FoloSourceError(f"decision {identifier} receipt requires a role")
    path = _artifact_path(raw_path, root, identifier, protected_roots)
    if anchor is not None:
        artifact_bytes = anchor.read(
            anchor.relative(path, f"decision {identifier} receipt"),
            f"decision {identifier} receipt",
        )
    else:
        artifact_bytes = _read_regular_bytes(
            path, f"decision {identifier} receipt"
        )
    actual_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise FoloSourceError(
            f"decision {identifier} signal receipt sha256 does not match"
        )
    return (
        {
            "role": role,
            "path": path.relative_to(root).as_posix(),
            "sha256": actual_sha256,
        },
        path,
        artifact_bytes,
    )


def _json_artifact(data: bytes, identifier: str, role: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FoloSourceError(
            f"decision {identifier} {role} artifact must be valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise FoloSourceError(
            f"decision {identifier} {role} artifact must contain an object"
        )
    return value


def _cas_path(sha256: str) -> str:
    digest = _require_sha256(sha256, "content-addressed object sha256")
    return f"autoresearch/research-radar/objects/sha256/{digest}"


def _stage_cas_object(
    objects: dict[str, bytes], data: bytes, *, role: str | None = None
) -> dict[str, str]:
    digest = _sha256_bytes(data)
    relative = _cas_path(digest)
    existing = objects.setdefault(relative, data)
    if existing != data:
        raise FoloSourceError("content-addressed object digest collision")
    descriptor = {"path": relative, "sha256": digest}
    if role is not None:
        descriptor["role"] = role
    return descriptor


def _require_nonempty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FoloSourceError(f"{field} must be a non-empty string")
    return value.strip()


def _normalize_decision(
    decision: dict[str, Any],
    candidate: dict[str, Any],
    artifact_root: Path,
    profile: Mapping[str, Any],
    *,
    now: dt.datetime,
    protected_roots: Iterable[Path] = (),
    staged_objects: dict[str, bytes] | None = None,
    anchor: _AnchoredArtifacts | None = None,
) -> dict[str, Any]:
    identifier = candidate["id"]
    expected_digest = candidate["candidate_sha256"]
    if decision.get("candidate_sha256") != expected_digest:
        raise FoloSourceError(f"decision {identifier} candidate digest does not match")
    action = decision.get("decision")
    if action not in DECISIONS:
        raise FoloSourceError(f"decision {identifier} has an invalid decision")
    if "disposition" in decision:
        raise FoloSourceError(
            f"decision {identifier} uses deprecated disposition; use decision"
        )
    reason = _require_nonempty_text(decision.get("reason"), f"decision {identifier} reason")
    relevance = decision.get("relevance")
    if relevance not in {"high", "medium", "low", "none"}:
        raise FoloSourceError(f"decision {identifier} relevance is invalid")
    evidence_level = decision.get("evidence_level")
    contract_fit = decision.get("contract_fit")
    signal_type = decision.get("signal_type")
    verification_status = decision.get("verification_status")
    if evidence_level not in EVIDENCE_LEVELS:
        raise FoloSourceError(f"decision {identifier} evidence_level is invalid")
    if contract_fit not in CONTRACT_FITS:
        raise FoloSourceError(f"decision {identifier} contract_fit is invalid")
    if signal_type not in SIGNAL_TYPES:
        raise FoloSourceError(f"decision {identifier} signal_type is invalid")
    if signal_type not in profile["allowed_signal_types"]:
        raise FoloSourceError(
            f"decision {identifier} signal_type is not authorized by the Watch Profile"
        )
    if verification_status not in VERIFICATION_STATUSES:
        raise FoloSourceError(f"decision {identifier} verification_status is invalid")
    source_claim = _require_nonempty_text(
        decision.get("source_claim"), f"decision {identifier} source_claim"
    )
    applicable_scope = _require_nonempty_text(
        decision.get("applicable_scope"), f"decision {identifier} applicable_scope"
    )
    uncertainty = _require_nonempty_text(
        decision.get("uncertainty"), f"decision {identifier} uncertainty"
    )
    if decision.get("profile_id") != profile["profile_id"]:
        raise FoloSourceError(f"decision {identifier} profile_id does not match")
    if decision.get("profile_sha256") != profile["profile_sha256"]:
        raise FoloSourceError(f"decision {identifier} profile_sha256 does not match")
    raw_receipts = decision.get("receipts", [])
    if not isinstance(raw_receipts, list):
        raise FoloSourceError(f"decision {identifier} receipts must be an array")
    receipt_records = [
        _hashed_artifact(
            receipt,
            artifact_root,
            identifier,
            protected_roots,
            anchor=anchor,
        )
        for receipt in raw_receipts
    ]
    receipts = [record[0] for record in receipt_records]
    receipt_paths = [record[1] for record in receipt_records]
    for left_index, left in enumerate(receipt_paths):
        for right in receipt_paths[left_index + 1 :]:
            if _aliases(left, right):
                raise FoloSourceError(
                    f"decision {identifier} receipt roles must not alias"
                )
    evidence_payload: dict[str, Any] | None = None
    evidence_sources_resolved: list[tuple[dict[str, Any], Path, str]] = []
    if action == "forwarded":
        roles: dict[str, tuple[dict[str, Any], Path, bytes]] = {}
        primary_records: list[tuple[dict[str, Any], Path, bytes]] = []
        for record in receipt_records:
            role = record[0]["role"]
            if role == "primary-source":
                primary_records.append(record)
            elif role in roles:
                raise FoloSourceError(
                    f"forwarded decision {identifier} has duplicate {role} receipt"
                )
            else:
                roles[role] = record
        if set(roles) != {"profile", "evidence"} or not primary_records:
            raise FoloSourceError(
                f"forwarded decision {identifier} requires profile, evidence, and primary-source receipts"
            )
        profile_receipt = roles["profile"][0]
        if (
            profile_receipt["sha256"] != profile["profile_sha256"]
            or not _aliases(roles["profile"][1], _resolved(profile["profile_path"]))
        ):
            raise FoloSourceError(
                f"forwarded decision {identifier} profile receipt does not match"
            )
        evidence = _json_artifact(roles["evidence"][2], identifier, "evidence")
        evidence_payload = evidence
        required_evidence = {
            "schema_version": SCHEMA_VERSION,
            "type": "research-signal",
            "candidate_id": identifier,
            "candidate_sha256": expected_digest,
            "profile_id": profile["profile_id"],
            "profile_sha256": profile["profile_sha256"],
            "relevance": relevance,
            "evidence_level": evidence_level,
            "contract_fit": contract_fit,
            "signal_type": signal_type,
            "source_claim": source_claim,
            "applicable_scope": applicable_scope,
            "verification_status": verification_status,
            "uncertainty": uncertainty,
        }
        for field, expected in required_evidence.items():
            if evidence.get(field) != expected:
                raise FoloSourceError(
                    f"forwarded decision {identifier} evidence {field} does not match"
                )
        evidence_sources = evidence.get("primary_sources")
        if not isinstance(evidence_sources, list) or not evidence_sources:
            raise FoloSourceError(
                f"forwarded decision {identifier} evidence lacks primary_sources"
            )
        evidence_source_pairs: set[tuple[str, str]] = set()
        for source in evidence_sources:
            if not isinstance(source, dict):
                raise FoloSourceError(
                    f"forwarded decision {identifier} primary_sources is invalid"
                )
            raw_path = source.get("path")
            digest = _require_sha256(
                source.get("sha256"),
                f"forwarded decision {identifier} primary source sha256",
            )
            path = _artifact_path(
                raw_path, artifact_root, identifier, protected_roots
            ) if isinstance(raw_path, str) else None
            if path is None:
                raise FoloSourceError(
                    f"forwarded decision {identifier} primary source hash does not match"
                )
            evidence_source_pairs.add((str(path), digest))
            evidence_sources_resolved.append((dict(source), path, digest))
        receipt_source_pairs = {
            (str(record[1]), record[0]["sha256"]) for record in primary_records
        }
        if evidence_source_pairs != receipt_source_pairs:
            raise FoloSourceError(
                f"forwarded decision {identifier} primary-source receipts do not match evidence"
            )
        evidence_order = [
            "summary-only", "primary-opened", "method-checked", "result-checked"
        ]
        if evidence_order.index(evidence_level) < evidence_order.index(
            profile["minimum_evidence_level"]
        ):
            raise FoloSourceError(
                f"forwarded decision {identifier} does not meet minimum evidence level"
            )
        if contract_fit != "in-scope":
            raise FoloSourceError(
                f"forwarded decision {identifier} must be in-scope"
            )
        if verification_status != "primary-verified":
            raise FoloSourceError(
                f"forwarded decision {identifier} requires primary verification"
            )
    if staged_objects is not None:
        portable_by_identity: dict[tuple[str, str], dict[str, str]] = {}
        for descriptor, receipt_path, artifact_bytes in receipt_records:
            portable = _stage_cas_object(
                staged_objects, artifact_bytes, role=descriptor["role"]
            )
            portable_by_identity[(str(receipt_path), descriptor["sha256"])] = portable
        if action == "forwarded" and evidence_payload is not None:
            portable_sources: list[dict[str, Any]] = []
            for source, source_path, digest in evidence_sources_resolved:
                portable = portable_by_identity.get((str(source_path), digest))
                if portable is None:
                    raise FoloSourceError(
                        f"forwarded decision {identifier} primary source was not staged"
                    )
                rewritten = dict(source)
                rewritten["path"] = portable["path"]
                rewritten["sha256"] = portable["sha256"]
                portable_sources.append(rewritten)
            rewritten_evidence = dict(evidence_payload)
            rewritten_evidence["primary_sources"] = portable_sources
            rewritten_evidence_bytes = _pretty_json_bytes(rewritten_evidence)
            portable_evidence = _stage_cas_object(
                staged_objects, rewritten_evidence_bytes, role="evidence"
            )
            portable_by_identity[
                (str(roles["evidence"][1]), roles["evidence"][0]["sha256"])
            ] = portable_evidence
        receipts = [
            portable_by_identity[(str(path), descriptor["sha256"])]
            for descriptor, path, _artifact_bytes in receipt_records
        ]
    retry_after: str | None = None
    if action == "deferred":
        parsed = _parse_utc(decision.get("retry_after"), f"decision {identifier} retry_after")
        if parsed <= now:
            raise FoloSourceError(
                f"decision {identifier} retry_after must be in the future"
            )
        retry_after = parsed.isoformat().replace("+00:00", "Z")
    elif "retry_after" in decision:
        raise FoloSourceError(
            f"decision {identifier} retry_after is allowed only when deferred"
        )
    normalized: dict[str, Any] = {
        "id": identifier,
        "candidate_sha256": expected_digest,
        "decision": action,
        "reason": reason,
        "relevance": relevance,
        "evidence_level": evidence_level,
        "contract_fit": contract_fit,
        "signal_type": signal_type,
        "source_claim": source_claim,
        "applicable_scope": applicable_scope,
        "verification_status": verification_status,
        "uncertainty": uncertainty,
        "profile_id": profile["profile_id"],
        "profile_sha256": profile["profile_sha256"],
        "receipts": receipts,
    }
    prior_digest = candidate.get("prior_decision_sha256")
    if prior_digest is not None:
        if decision.get("prior_decision_sha256") != prior_digest:
            raise FoloSourceError(
                f"decision {identifier} must bind prior_decision_sha256"
            )
        normalized["prior_decision_sha256"] = prior_digest
    elif "prior_decision_sha256" in decision:
        raise FoloSourceError(
            f"decision {identifier} has an unexpected prior_decision_sha256"
        )
    if retry_after is not None:
        normalized["retry_after"] = retry_after
    normalized["decision_sha256"] = hashlib.sha256(
        _canonical_bytes(normalized)
    ).hexdigest()
    return normalized


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class _AnchoredArtifacts:
    """Descriptor-anchored artifact-root I/O with no symlink traversal."""

    def __init__(self, root: Path) -> None:
        raw = Path(root).expanduser()
        self.path = _reject_symlink(raw, "artifact_root").resolve(strict=True)
        if not self.path.is_dir():
            raise FoloSourceError(f"artifact_root is not a directory: {self.path}")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            self.fd = os.open(self.path, flags)
        except OSError as exc:
            raise FoloSourceError("unable to anchor artifact_root") from exc
        root_stat = os.fstat(self.fd)
        if not stat.S_ISDIR(root_stat.st_mode):
            os.close(self.fd)
            raise FoloSourceError("artifact_root anchor is not a directory")

    def close(self) -> None:
        if getattr(self, "fd", -1) >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> "_AnchoredArtifacts":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    @staticmethod
    def _parts(relative: str | os.PathLike[str] | Path, field: str) -> tuple[str, ...]:
        raw = str(relative).replace(os.sep, "/")
        value = PurePosixPath(raw)
        parts = value.parts
        if (
            value.is_absolute()
            or not parts
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise FoloSourceError(f"{field} must be a contained relative path")
        return parts

    def relative(self, path: Path, field: str) -> str:
        resolved = _resolved(path)
        try:
            relative = resolved.relative_to(self.path).as_posix()
        except ValueError as exc:
            raise FoloSourceError(f"{field} escapes artifact_root: {path}") from exc
        self._parts(relative, field)
        return relative

    def _open_parent(
        self, relative: str | os.PathLike[str] | Path, *, create: bool, field: str
    ) -> tuple[int, str, Path]:
        parts = self._parts(relative, field)
        descriptor = os.dup(self.fd)
        current_path = self.path
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            for component in parts[:-1]:
                try:
                    next_fd = os.open(component, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create:
                        raise FoloSourceError(f"{field} parent directory is missing")
                    try:
                        os.mkdir(component, 0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    os.fsync(descriptor)
                    next_fd = os.open(component, flags, dir_fd=descriptor)
                except OSError as exc:
                    raise FoloSourceError(
                        f"{field} parent is not a safe directory"
                    ) from exc
                child_stat = os.fstat(next_fd)
                if not stat.S_ISDIR(child_stat.st_mode):
                    os.close(next_fd)
                    raise FoloSourceError(f"{field} parent is not a directory")
                os.close(descriptor)
                descriptor = next_fd
                current_path = current_path / component
            return descriptor, parts[-1], current_path
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _read_fd(descriptor: int, field: str) -> bytes:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise FoloSourceError(f"{field} must be a single-link regular file")
        chunks: list[bytes] = []
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            details.st_dev,
            details.st_ino,
            details.st_size,
            details.st_mtime_ns,
            details.st_nlink,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_nlink,
        ):
            raise FoloSourceError(f"{field} changed while reading")
        return b"".join(chunks)

    def read(self, relative: str, field: str) -> bytes:
        parent_fd, name, _parent_path = self._open_parent(
            relative, create=False, field=field
        )
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(name, flags, dir_fd=parent_fd)
            except OSError as exc:
                raise FoloSourceError(f"unable to open {field}") from exc
            try:
                return self._read_fd(descriptor, field)
            finally:
                os.close(descriptor)
        finally:
            os.close(parent_fd)

    def read_optional(self, relative: str, field: str) -> bytes | None:
        """Read a file relative to the root, returning None only when absent."""
        parts = self._parts(relative, field)
        descriptor = os.dup(self.fd)
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            for component in parts[:-1]:
                try:
                    next_fd = os.open(component, directory_flags, dir_fd=descriptor)
                except FileNotFoundError:
                    return None
                except OSError as exc:
                    raise FoloSourceError(
                        f"{field} parent is not a safe directory"
                    ) from exc
                os.close(descriptor)
                descriptor = next_fd
            try:
                file_fd = os.open(
                    parts[-1],
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                return None
            except OSError as exc:
                raise FoloSourceError(f"unable to open {field}") from exc
            try:
                return self._read_fd(file_fd, field)
            finally:
                os.close(file_fd)
        finally:
            os.close(descriptor)

    def open_lock(self, relative: str) -> int:
        """Open a single-link advisory lock through the anchored directory tree."""
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        last_error: OSError | None = None
        for _attempt in range(4):
            parent_fd, name, _parent_path = self._open_parent(
                relative, create=True, field="stable commit lock"
            )
            try:
                try:
                    descriptor = os.open(name, flags, 0o600, dir_fd=parent_fd)
                except OSError as exc:
                    last_error = exc
                    continue
                details = os.fstat(descriptor)
                if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
                    os.close(descriptor)
                    raise FoloSourceError(
                        "stable commit lock must be a single-link regular file"
                    )
                try:
                    bound_fd = os.open(
                        name,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=parent_fd,
                    )
                except OSError as exc:
                    os.close(descriptor)
                    last_error = exc
                    continue
                try:
                    bound = os.fstat(bound_fd)
                    locked = os.fstat(descriptor)
                    if (
                        bound.st_dev,
                        bound.st_ino,
                        bound.st_nlink,
                    ) != (
                        locked.st_dev,
                        locked.st_ino,
                        locked.st_nlink,
                    ):
                        os.close(descriptor)
                        last_error = OSError("stable commit lock was rebound")
                        continue
                finally:
                    os.close(bound_fd)
                return descriptor
            finally:
                os.close(parent_fd)
        if last_error is not None:
            raise FoloSourceError("unable to open stable commit lock") from last_error
        raise FoloSourceError("unable to open stable commit lock")

    def verify_lock_binding(self, relative: str, descriptor: int) -> None:
        """Prove the locked inode is still the inode named by the lock path."""
        parent_fd, name, _parent_path = self._open_parent(
            relative, create=False, field="stable commit lock"
        )
        try:
            try:
                bound_fd = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent_fd,
                )
            except OSError as exc:
                raise FoloSourceError(
                    "stable commit lock path changed while locked"
                ) from exc
            try:
                bound = os.fstat(bound_fd)
                locked = os.fstat(descriptor)
                if (
                    bound.st_dev,
                    bound.st_ino,
                    bound.st_nlink,
                ) != (
                    locked.st_dev,
                    locked.st_ino,
                    locked.st_nlink,
                ) or not stat.S_ISREG(bound.st_mode) or bound.st_nlink != 1:
                    raise FoloSourceError(
                        "stable commit lock path was rebound while locked"
                    )
            finally:
                os.close(bound_fd)
        finally:
            os.close(parent_fd)

    def write_immutable(
        self,
        relative: str,
        data: bytes,
        *,
        field: str = "immutable artifact",
        forbidden_inodes: set[tuple[int, int]] | None = None,
    ) -> None:
        parent_fd, name, _parent_path = self._open_parent(
            relative, create=True, field=field
        )
        descriptor: int | None = None
        try:
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                descriptor = os.open(name, flags, 0o600, dir_fd=parent_fd)
            except FileExistsError:
                existing = os.open(
                    name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd
                )
                try:
                    details = os.fstat(existing)
                    if (
                        not stat.S_ISREG(details.st_mode)
                        or details.st_nlink != 1
                        or (forbidden_inodes and (details.st_dev, details.st_ino) in forbidden_inodes)
                        or self._read_fd(existing, field) != data
                    ):
                        raise FoloSourceError(
                            f"immutable artifact already exists with unsafe or different bytes: {relative}"
                        )
                    os.fsync(existing)
                    os.fsync(parent_fd)
                finally:
                    os.close(existing)
                return
            except OSError as exc:
                raise FoloSourceError(f"unable to create {field}") from exc
            details = os.fstat(descriptor)
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_nlink != 1
                or (forbidden_inodes and (details.st_dev, details.st_ino) in forbidden_inodes)
            ):
                raise FoloSourceError(f"new {field} is not an isolated regular file")
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
            os.fsync(parent_fd)
        except BaseException:
            if descriptor is not None:
                with contextlib.suppress(OSError):
                    os.unlink(name, dir_fd=parent_fd)
            raise
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent_fd)

    def replace(
        self,
        relative: str,
        data: bytes,
        original: bytes,
        *,
        post_sync_hook: Path | None = None,
    ) -> None:
        parent_fd, name, parent_path = self._open_parent(
            relative, create=True, field="stable commit-root pointer"
        )
        temp_name = f".{name}.{secrets.token_hex(12)}.tmp"
        temp_fd: int | None = None
        replaced = False
        try:
            try:
                current_fd = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent_fd,
                )
            except FileNotFoundError:
                current = b""
            except OSError as exc:
                raise FoloSourceError(
                    "unable to read stable commit-root pointer"
                ) from exc
            else:
                try:
                    current = self._read_fd(
                        current_fd, "stable commit-root pointer"
                    )
                finally:
                    os.close(current_fd)
            if current != original:
                raise FoloSourceError("stable commit-root changed while locked")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            temp_fd = os.open(temp_name, flags, 0o600, dir_fd=parent_fd)
            view = memoryview(data)
            while view:
                written = os.write(temp_fd, view)
                view = view[written:]
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = None
            os.rename(temp_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            replaced = True
            os.fsync(parent_fd)
            fresh_parent_fd, _fresh_name, _fresh_parent_path = self._open_parent(
                relative, create=False, field="stable commit-root pointer"
            )
            try:
                if (
                    os.fstat(fresh_parent_fd).st_dev,
                    os.fstat(fresh_parent_fd).st_ino,
                ) != (
                    os.fstat(parent_fd).st_dev,
                    os.fstat(parent_fd).st_ino,
                ):
                    raise FoloSourceError(
                        "stable pointer parent changed during publication"
                    )
            finally:
                os.close(fresh_parent_fd)
            if post_sync_hook is not None:
                _fsync_directory(post_sync_hook)
        except BaseException as exc:
            if replaced:
                observed = b""
                with contextlib.suppress(BaseException):
                    observed_fd = os.open(
                        name,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=parent_fd,
                    )
                    try:
                        observed = self._read_fd(
                            observed_fd, "stable commit-root pointer"
                        )
                    finally:
                        os.close(observed_fd)
                status = "new" if observed == data else "old" if observed == original else "invalid"
                raise FoloCommitIndeterminate(
                    "stable pointer replacement completed but durable completion is indeterminate",
                    status,
                ) from exc
            if isinstance(exc, FoloSourceError):
                raise
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise FoloSourceError(
                f"unable to publish stable commit-root pointer ({type(exc).__name__})"
            ) from exc
        finally:
            if temp_fd is not None:
                os.close(temp_fd)
            if not replaced:
                with contextlib.suppress(OSError):
                    os.unlink(temp_name, dir_fd=parent_fd)
            os.close(parent_fd)


def _write_immutable(
    path: Path,
    data: bytes,
    *,
    artifact_root: Path,
    protected_roots: Iterable[Path] = (),
    anchor: _AnchoredArtifacts | None = None,
    forbidden_inodes: set[tuple[int, int]] | None = None,
) -> None:
    raw_root = Path(artifact_root).expanduser()
    raw_target = Path(path).expanduser()
    root = _reject_symlink(raw_root, "artifact_root")
    target = _reject_symlink(raw_target, "immutable artifact path")
    if not _is_within(target, root):
        raise FoloSourceError(f"immutable artifact escapes artifact_root: {path}")
    _refuse_live_write(target, protected_roots)
    owned = anchor is None
    active = anchor or _AnchoredArtifacts(raw_root)
    try:
        active.write_immutable(
            active.relative(target, "immutable artifact"),
            data,
            forbidden_inodes=forbidden_inodes,
        )
    finally:
        if owned:
            active.close()


def _relative(path: Path, root: Path, field: str) -> str:
    path = _resolved(path)
    root = _resolved(root)
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise FoloSourceError(f"{field} escapes artifact_root: {path}") from exc


def _descriptor(path: Path, root: Path, field: str) -> dict[str, str]:
    path = _reject_symlink(path, field)
    if not path.is_file():
        raise FoloSourceError(f"{field} must be a regular non-symlink file: {path}")
    return {"path": _relative(path, root, field), "sha256": _sha256_file(path)}


def _resolve_descriptor(
    value: Any,
    root: Path,
    field: str,
    protected_roots: Iterable[Path] = (),
    *,
    anchor: _AnchoredArtifacts | None = None,
) -> tuple[Path, bytes]:
    root = _resolved(root)
    if not isinstance(value, dict):
        raise FoloSourceError(f"{field} must be an artifact descriptor")
    raw_path = value.get("path")
    expected = _require_sha256(value.get("sha256"), f"{field}.sha256")
    if not isinstance(raw_path, str) or not raw_path:
        raise FoloSourceError(f"{field}.path must be non-empty")
    relative = PurePosixPath(raw_path)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise FoloSourceError(f"{field}.path must be a contained relative path")
    path = root / Path(*relative.parts)
    for protected in protected_roots:
        protected = _resolved(protected)
        if _resolved(path) == protected or _is_within(_resolved(path), protected):
            raise FoloSourceError(f"{field} is inside protected source data")
    if anchor is not None:
        data = anchor.read(relative.as_posix(), field)
    else:
        path = _reject_symlink(path, field)
        if not _is_within(path, root) or not path.is_file():
            raise FoloSourceError(f"{field} path is not a regular artifact")
        data = _read_regular_bytes(path, field)
    if _sha256_bytes(data) != expected:
        raise FoloSourceError(f"{field} sha256 does not match")
    return path, data


def _require_cas_descriptor(value: Any, field: str) -> None:
    if not isinstance(value, dict):
        raise FoloSourceError(f"{field} must be an artifact descriptor")
    digest = _require_sha256(value.get("sha256"), f"{field}.sha256")
    if value.get("path") != _cas_path(digest):
        raise FoloSourceError(f"{field} must reference its content-addressed object")


def _validate_committed_decision(
    decision: dict[str, Any],
    candidate: dict[str, Any],
    *,
    profile_id: str,
    profile_sha256: str,
    policy: Mapping[str, Any],
    recorded_at: dt.datetime,
) -> None:
    identifier = candidate["id"]
    action = decision.get("decision")
    expected_fields = {
        "id", "candidate_sha256", "decision", "reason", "relevance",
        "evidence_level", "contract_fit", "signal_type", "source_claim",
        "applicable_scope", "verification_status", "uncertainty", "profile_id",
        "profile_sha256", "receipts", "decision_sha256",
    }
    if candidate.get("prior_decision_sha256") is not None:
        expected_fields.add("prior_decision_sha256")
    if action == "deferred":
        expected_fields.add("retry_after")
    if set(decision) != expected_fields:
        raise FoloSourceError(
            f"committed decision {identifier} has an invalid field set"
        )
    if decision.get("id") != identifier:
        raise FoloSourceError(f"committed decision {identifier} identity is invalid")
    if decision.get("candidate_sha256") != candidate.get("candidate_sha256"):
        raise FoloSourceError(
            f"committed decision {identifier} candidate digest does not match"
        )
    if action not in DECISIONS:
        raise FoloSourceError(f"committed decision {identifier} action is invalid")
    for field in ("reason", "source_claim", "applicable_scope", "uncertainty"):
        _require_nonempty_text(decision.get(field), f"committed decision {identifier} {field}")
    if decision.get("relevance") not in {"high", "medium", "low", "none"}:
        raise FoloSourceError(f"committed decision {identifier} relevance is invalid")
    if decision.get("evidence_level") not in EVIDENCE_LEVELS:
        raise FoloSourceError(
            f"committed decision {identifier} evidence_level is invalid"
        )
    if decision.get("contract_fit") not in CONTRACT_FITS:
        raise FoloSourceError(
            f"committed decision {identifier} contract_fit is invalid"
        )
    if decision.get("signal_type") not in SIGNAL_TYPES:
        raise FoloSourceError(f"committed decision {identifier} signal_type is invalid")
    allowed = policy.get("allowed_signal_types")
    if not isinstance(allowed, list) or decision["signal_type"] not in allowed:
        raise FoloSourceError(
            f"committed decision {identifier} violates signal-type policy"
        )
    if decision.get("verification_status") not in VERIFICATION_STATUSES:
        raise FoloSourceError(
            f"committed decision {identifier} verification_status is invalid"
        )
    if (
        decision.get("profile_id") != profile_id
        or decision.get("profile_sha256") != profile_sha256
    ):
        raise FoloSourceError(f"committed decision {identifier} profile binding is invalid")
    prior_digest = candidate.get("prior_decision_sha256")
    if prior_digest is not None and decision.get("prior_decision_sha256") != prior_digest:
        raise FoloSourceError(
            f"committed decision {identifier} pending binding is invalid"
        )
    if action == "deferred":
        retry_after = _parse_utc(
            decision.get("retry_after"),
            f"committed decision {identifier} retry_after",
        )
        if retry_after <= recorded_at:
            raise FoloSourceError(
                f"committed decision {identifier} retry_after is invalid"
            )
    if action == "forwarded":
        levels = ["summary-only", "primary-opened", "method-checked", "result-checked"]
        minimum = policy.get("minimum_evidence_level")
        if minimum not in levels or levels.index(decision["evidence_level"]) < levels.index(minimum):
            raise FoloSourceError(
                f"committed decision {identifier} violates evidence policy"
            )
        if decision["contract_fit"] != "in-scope":
            raise FoloSourceError(
                f"committed decision {identifier} violates contract-fit policy"
            )
        if decision["verification_status"] != "primary-verified":
            raise FoloSourceError(
                f"committed decision {identifier} violates verification policy"
            )
    claimed_digest = _require_sha256(
        decision.get("decision_sha256"),
        f"committed decision {identifier} decision_sha256",
    )
    digest_payload = dict(decision)
    digest_payload.pop("decision_sha256")
    if _sha256_bytes(_canonical_bytes(digest_payload)) != claimed_digest:
        raise FoloSourceError(
            f"committed decision {identifier} decision_sha256 does not match"
        )


def _historical_profile_policy(
    raw_profile: Mapping[str, Any], profile_bytes: bytes, source_instance_id: str
) -> dict[str, Any]:
    profile_id = raw_profile.get("profile_id", raw_profile.get("id"))
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise FoloSourceError("run profile id is invalid")
    if (
        raw_profile.get("schema_version") != SCHEMA_VERSION
        or raw_profile.get("source") != "folo-local"
        or raw_profile.get("source_instance_id") != source_instance_id
    ):
        raise FoloSourceError("run profile source binding is invalid")
    source_scope = raw_profile.get("source_scope")
    scan = raw_profile.get("scan")
    policy = raw_profile.get("policy")
    if not isinstance(source_scope, dict) or not isinstance(scan, dict) or not isinstance(policy, dict):
        raise FoloSourceError("run profile operational policy is invalid")
    feed_ids = source_scope.get("authorized_feed_ids")
    include = source_scope.get("query_terms")
    exclude = source_scope.get("excluded_terms", [])
    if (
        not isinstance(feed_ids, list)
        or not feed_ids
        or not all(isinstance(value, str) and value for value in feed_ids)
        or len(feed_ids) != len(set(feed_ids))
        or not isinstance(include, list)
        or not include
        or not all(isinstance(value, str) and value.strip() for value in include)
        or not isinstance(exclude, list)
        or not all(isinstance(value, str) and value.strip() for value in exclude)
    ):
        raise FoloSourceError("run profile source scope is invalid")
    hours = scan.get("hours")
    limit = scan.get("limit")
    refresh_age = policy.get("refresh_max_age_minutes")
    minimum = policy.get("minimum_evidence_level")
    allowed = policy.get("allowed_signal_types")
    if (
        isinstance(hours, bool)
        or not isinstance(hours, (int, float))
        or not math.isfinite(float(hours))
        or float(hours) < 0
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_CANDIDATES
        or isinstance(refresh_age, bool)
        or not isinstance(refresh_age, (int, float))
        or not math.isfinite(float(refresh_age))
        or float(refresh_age) <= 0
        or minimum not in EVIDENCE_LEVELS - {"summary-only"}
        or not isinstance(allowed, list)
        or not allowed
        or not set(allowed).issubset(SIGNAL_TYPES)
    ):
        raise FoloSourceError("run profile scan or evidence policy is invalid")
    return {
        "profile_id": profile_id.strip(),
        "profile_sha256": _sha256_bytes(profile_bytes),
        "authorized_feed_ids": sorted(feed_ids),
        "query_scope": {
            "include_any": [value.strip().casefold() for value in include],
            "exclude_any": [value.strip().casefold() for value in exclude],
        },
        "max_hours": float(hours),
        "max_candidates": limit,
        "refresh_max_age_minutes": float(refresh_age),
        "minimum_evidence_level": minimum,
        "allowed_signal_types": sorted(set(allowed)),
    }


def _read_pointer(
    pointer_path: Path,
    artifact_root: Path,
    source_instance_id: str,
    *,
    anchor: _AnchoredArtifacts | None = None,
) -> tuple[bytes, dict[str, Any] | None, dict[str, Any], bytes, Path | None]:
    root = _resolved(artifact_root)
    owned = anchor is None
    active = anchor or _AnchoredArtifacts(root)
    try:
        pointer_relative = active.relative(
            pointer_path, "stable commit-root pointer"
        )
        pointer_bytes = active.read_optional(
            pointer_relative, "stable commit-root pointer"
        ) or b""
        if not pointer_bytes:
            state = _empty_state(source_instance_id)
            state_bytes = _pretty_json_bytes(state)
            return pointer_bytes, None, state, state_bytes, None
        try:
            pointer = json.loads(pointer_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FoloSourceError("stable commit-root pointer is invalid JSON") from exc
        if not isinstance(pointer, dict) or pointer.get("schema_version") != SCHEMA_VERSION:
            raise FoloSourceError("stable commit-root pointer schema is invalid")
        if pointer.get("source") != "folo-local":
            raise FoloSourceError("stable commit-root pointer source is invalid")
        state_path, state_bytes = _resolve_descriptor(
            {"path": pointer.get("state_path"), "sha256": pointer.get("state_sha256")},
            root,
            "stable pointer state",
            anchor=active,
        )
        _manifest_path, manifest_bytes = _resolve_descriptor(
            {
                "path": pointer.get("manifest_path"),
                "sha256": pointer.get("manifest_sha256"),
            },
            root,
            "stable pointer run manifest",
            anchor=active,
        )
        try:
            state = json.loads(state_bytes.decode("utf-8"))
            run_manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FoloSourceError("stable pointer target is invalid JSON") from exc
        state = _validate_state_payload(state, source_instance_id)
        if not isinstance(run_manifest, dict):
            raise FoloSourceError("stable pointer run manifest is invalid")
        if (
            run_manifest.get("schema_version") != SCHEMA_VERSION
            or run_manifest.get("type") != "research-radar-run-manifest"
            or run_manifest.get("source") != "folo-local"
            or run_manifest.get("source_instance_id") != source_instance_id
            or run_manifest.get("publication_status") != "validated"
            or pointer.get("outcome") != "research-radar-cycle-complete"
            or run_manifest.get("run_id") != pointer.get("run_id")
            or run_manifest.get("state_sha256") != pointer.get("state_sha256")
            or run_manifest.get("profile_sha256") != pointer.get("profile_sha256")
            or run_manifest.get("previous_commit_root_sha256")
            != pointer.get("previous_commit_root_sha256")
        ):
            raise FoloSourceError("stable pointer does not bind its run manifest")
        _profile_path, profile_bytes = _resolve_descriptor(
            {
                "path": run_manifest.get("profile_path"),
                "sha256": run_manifest.get("profile_sha256"),
            },
            root,
            "run profile",
            anchor=active,
        )
        _receipt_path, receipt_bytes = _resolve_descriptor(
            {
                "path": run_manifest.get("refresh_receipt_path"),
                "sha256": run_manifest.get("refresh_receipt_sha256"),
            },
            root,
            "run refresh receipt",
            anchor=active,
        )
        _key_path, public_key_bytes = _resolve_descriptor(
            run_manifest.get("refresh_public_key"),
            root,
            "run refresh public key",
            anchor=active,
        )
        _database_path, database_bytes = _resolve_descriptor(
            run_manifest.get("database_snapshot"),
            root,
            "run database snapshot",
            anchor=active,
        )
        try:
            raw_profile = _parse_mapping_bytes(
                profile_bytes, _profile_path, "run profile"
            )
            receipt = json.loads(receipt_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FoloSourceError("run provenance artifact is invalid JSON") from exc
        if not isinstance(raw_profile, dict):
            raise FoloSourceError("run profile is invalid")
        trust = raw_profile.get("refresh_trust")
        policy = raw_profile.get("policy")
        if not isinstance(trust, dict) or not isinstance(policy, dict):
            raise FoloSourceError("run profile trust policy is invalid")
        operational_profile = _historical_profile_policy(
            raw_profile, profile_bytes, source_instance_id
        )
        if (
            run_manifest.get("profile_id") != operational_profile["profile_id"]
            or run_manifest.get("profile_sha256")
            != operational_profile["profile_sha256"]
        ):
            raise FoloSourceError("run manifest profile binding is invalid")
        expected_public_key_sha256 = _require_sha256(
            trust.get("ed25519_public_key_sha256"),
            "run profile Ed25519 public key hash",
        )
        if (
            run_manifest.get("refresh_public_key", {}).get("sha256")
            != expected_public_key_sha256
            or _sha256_bytes(public_key_bytes) != expected_public_key_sha256
        ):
            raise FoloSourceError(
                "run refresh public key is not bound to the frozen profile"
            )
        raw_authority = raw_profile.get("authority")
        if not isinstance(raw_authority, dict):
            raise FoloSourceError("run profile authority envelope is invalid")
        if run_manifest.get("authority_sha256") != _sha256_bytes(
            _canonical_bytes(raw_authority)
        ):
            raise FoloSourceError("run authority envelope hash does not match")
        expected_authority: dict[str, dict[str, Any]] = {}
        for profile_field, role in (
            ("research_brief", "research-brief"),
            ("adaptation_plan", "adaptation-plan"),
        ):
            ref = raw_authority.get(profile_field)
            if not isinstance(ref, dict):
                raise FoloSourceError(f"run authority {profile_field} is invalid")
            expected_authority[role] = ref
        contract_ref = raw_authority.get("experiment_contract")
        if not isinstance(contract_ref, dict):
            raise FoloSourceError("run experiment contract authority is invalid")
        if contract_ref.get("status") == "frozen":
            expected_authority["experiment-contract"] = contract_ref
        raw_authority_artifacts = run_manifest.get("authority_artifacts")
        if not isinstance(raw_authority_artifacts, list):
            raise FoloSourceError("run authority artifacts are invalid")
        actual_roles = [
            item.get("role") if isinstance(item, dict) else None
            for item in raw_authority_artifacts
        ]
        if len(actual_roles) != len(set(actual_roles)) or set(actual_roles) != set(
            expected_authority
        ):
            raise FoloSourceError(
                "run authority artifact roles do not match the frozen profile"
            )
        for descriptor in raw_authority_artifacts:
            role = descriptor["role"]
            expected_ref = expected_authority[role]
            if (
                descriptor.get("id") != expected_ref.get("id")
                or descriptor.get("sha256") != expected_ref.get("sha256")
            ):
                raise FoloSourceError(
                    f"run authority artifact {role} does not match the frozen profile"
                )
            _require_cas_descriptor(
                descriptor, f"run authority artifact {role}"
            )
            _resolve_descriptor(
                descriptor,
                root,
                f"run authority artifact {role}",
                anchor=active,
            )
        historical_profile = {
            "profile_id": raw_profile.get("profile_id", raw_profile.get("id")),
            "profile_sha256": run_manifest.get("profile_sha256"),
            "trusted_producer_identity": trust.get("producer_identity"),
            "ed25519_public_key_bytes": public_key_bytes,
        }
        validated_at = _parse_utc(
            run_manifest.get("validated_at"), "run manifest validated_at"
        )
        _validate_refresh_receipt_payload(
            receipt,
            source_instance_id=source_instance_id,
            source_snapshot_sha256=run_manifest.get("source_snapshot_sha256"),
            database_snapshot_sha256=_sha256_bytes(database_bytes),
            now=validated_at,
            max_age_minutes=operational_profile["refresh_max_age_minutes"],
            profile=historical_profile,
        )
        _extraction_path, extraction_bytes = _resolve_descriptor(
            {
                "path": run_manifest.get("extraction_manifest_path"),
                "sha256": run_manifest.get("extraction_manifest_sha256"),
            },
            root,
            "run extraction manifest",
            anchor=active,
        )
        _candidates_path, candidates_bytes = _resolve_descriptor(
            {
                "path": run_manifest.get("candidates_path"),
                "sha256": run_manifest.get("candidates_sha256"),
            },
            root,
            "run candidate ledger",
            anchor=active,
        )
        _input_state_path, input_state_bytes = _resolve_descriptor(
            run_manifest.get("input_state"),
            root,
            "run input state",
            anchor=active,
        )
        try:
            extraction = json.loads(extraction_bytes.decode("utf-8"))
            input_state_raw = json.loads(input_state_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FoloSourceError("run extraction provenance is invalid JSON") from exc
        if not isinstance(extraction, dict) or set(extraction) != {
            "schema_version", "type", "source", "source_instance_id", "profile",
            "refresh_receipt", "source_snapshot_sha256", "database_snapshot",
            "source_path", "candidates", "input_state", "input_commit_root_sha256",
            "extraction_bounds", "extracted_at",
        }:
            raise FoloSourceError("run extraction manifest shape is invalid")
        if (
            extraction.get("schema_version") != SCHEMA_VERSION
            or extraction.get("type") != "folo-extraction-manifest"
            or extraction.get("source") != "folo-local"
            or extraction.get("source_instance_id") != source_instance_id
            or extraction.get("profile", {}).get("id")
            != operational_profile["profile_id"]
            or extraction.get("profile", {}).get("sha256")
            != operational_profile["profile_sha256"]
            or extraction.get("refresh_receipt", {}).get("sha256")
            != run_manifest.get("refresh_receipt_sha256")
            or extraction.get("source_snapshot_sha256")
            != run_manifest.get("source_snapshot_sha256")
            or extraction.get("database_snapshot", {}).get("sha256")
            != _sha256_bytes(database_bytes)
            or extraction.get("candidates", {}).get("sha256")
            != _sha256_bytes(candidates_bytes)
            or extraction.get("input_state", {}).get("sha256")
            != _sha256_bytes(input_state_bytes)
            or extraction.get("input_commit_root_sha256")
            != run_manifest.get("previous_commit_root_sha256")
        ):
            raise FoloSourceError("run extraction manifest binding is invalid")
        input_state = _validate_state_payload(input_state_raw, source_instance_id)
        if input_state_bytes != _pretty_json_bytes(input_state):
            raise FoloSourceError("run input state is not canonically encoded")
        candidates_raw = _read_jsonl_bytes(
            candidates_bytes, "run candidates", _candidates_path
        )
        candidates = _unique_by_id(candidates_raw, "run candidate")
        if extraction.get("candidates", {}).get("count") != len(candidates):
            raise FoloSourceError("run extraction candidate count does not match")
        bounds = extraction.get("extraction_bounds")
        if not isinstance(bounds, dict) or set(bounds) != {"hours", "limit"}:
            raise FoloSourceError("run extraction bounds are invalid")
        try:
            hours = float(bounds["hours"])
            limit = int(bounds["limit"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise FoloSourceError("run extraction bounds are invalid") from exc
        if (
            not math.isfinite(hours)
            or hours < 0
            or hours > operational_profile["max_hours"]
            or isinstance(bounds["limit"], bool)
            or limit != bounds["limit"]
            or not 1 <= limit <= operational_profile["max_candidates"]
        ):
            raise FoloSourceError("run extraction bounds exceed the frozen profile")
        extracted_at = _parse_utc(
            extraction.get("extracted_at"), "run extraction extracted_at"
        )
        if (
            extracted_at > validated_at
            or validated_at - extracted_at
            > dt.timedelta(minutes=operational_profile["refresh_max_age_minutes"])
        ):
            raise FoloSourceError("run extraction time is outside the validation window")
        verification_database: Path | None = None
        verification_state: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=_safe_scratch_root((_database_path,)),
                prefix="autoresearch-folo-historical-db-", suffix=".sqlite",
                delete=False,
            ) as handle:
                verification_database = Path(handle.name)
                handle.write(database_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=_safe_scratch_root((_database_path,)),
                prefix="autoresearch-folo-historical-state-", suffix=".json",
                delete=False,
            ) as handle:
                verification_state = Path(handle.name)
                handle.write(input_state_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            inspect_sqlite(verification_database)
            expected_candidates = extract_candidates(
                verification_database,
                state_path=verification_state,
                source_instance_id=source_instance_id,
                hours=hours,
                limit=limit,
                now_ms=int(extracted_at.timestamp() * 1000),
                authorized_feed_ids=operational_profile["authorized_feed_ids"],
                query_scope=operational_profile["query_scope"],
            )
        finally:
            for temporary in (verification_database, verification_state):
                if temporary is not None:
                    with contextlib.suppress(OSError):
                        temporary.unlink()
        if candidates_raw != expected_candidates:
            raise FoloSourceError(
                "run candidates do not equal deterministic historical extraction"
            )
        _decisions_path, decisions_bytes = _resolve_descriptor(
            {
                "path": run_manifest.get("decisions_path"),
                "sha256": run_manifest.get("decisions_sha256"),
            },
            root,
            "run decision ledger",
            anchor=active,
        )
        decision_records = _read_jsonl_bytes(
            decisions_bytes, "run decisions", _decisions_path
        )
        decisions = _unique_by_id(decision_records, "run decision")
        if set(decisions) != set(candidates):
            raise FoloSourceError("run decisions are not one-to-one with candidates")
        normalized_decision_bytes = "".join(
            json.dumps(decisions[key], ensure_ascii=False, sort_keys=True) + "\n"
            for key in sorted(decisions)
        ).encode("utf-8")
        if decisions_bytes != normalized_decision_bytes:
            raise FoloSourceError("run decision ledger is not canonically encoded")
        for identifier in sorted(decisions):
            decision = decisions[identifier]
            _validate_committed_decision(
                decision,
                candidates[identifier],
                profile_id=operational_profile["profile_id"],
                profile_sha256=operational_profile["profile_sha256"],
                policy=operational_profile,
                recorded_at=validated_at,
            )
            receipts = decision.get("receipts")
            if not isinstance(receipts, list):
                raise FoloSourceError("run decision receipts are invalid")
            receipt_records: list[tuple[dict[str, Any], bytes]] = []
            for descriptor in receipts:
                _require_cas_descriptor(descriptor, "run decision receipt")
                _receipt_artifact_path, artifact_bytes = _resolve_descriptor(
                    descriptor,
                    root,
                    "run decision receipt",
                    anchor=active,
                )
                receipt_records.append((descriptor, artifact_bytes))
            if decision.get("decision") == "forwarded":
                roles = [descriptor.get("role") for descriptor, _ in receipt_records]
                if (
                    roles.count("profile") != 1
                    or roles.count("evidence") != 1
                    or roles.count("primary-source") < 1
                    or set(roles) != {"profile", "evidence", "primary-source"}
                ):
                    raise FoloSourceError(
                        "forwarded run decision requires exact profile, evidence, "
                        "and primary-source receipts"
                    )
                profile_descriptor, profile_receipt_bytes = next(
                    record for record in receipt_records if record[0]["role"] == "profile"
                )
                if (
                    profile_descriptor.get("sha256")
                    != run_manifest.get("profile_sha256")
                    or profile_receipt_bytes != profile_bytes
                ):
                    raise FoloSourceError(
                        "forwarded run decision profile receipt is invalid"
                    )
                evidence_descriptor, evidence_bytes = next(
                    record for record in receipt_records if record[0]["role"] == "evidence"
                )
                del evidence_descriptor
                evidence = _json_artifact(
                    evidence_bytes, str(decision.get("id")), "evidence"
                )
                for field in (
                    "candidate_sha256",
                    "profile_id",
                    "profile_sha256",
                    "relevance",
                    "evidence_level",
                    "contract_fit",
                    "signal_type",
                    "source_claim",
                    "applicable_scope",
                    "verification_status",
                    "uncertainty",
                ):
                    if evidence.get(field) != decision.get(field):
                        raise FoloSourceError(
                            f"forwarded run decision evidence {field} does not match"
                        )
                if (
                    evidence.get("schema_version") != SCHEMA_VERSION
                    or evidence.get("type") != "research-signal"
                    or evidence.get("candidate_id") != decision.get("id")
                ):
                    raise FoloSourceError(
                        "forwarded run decision evidence identity is invalid"
                    )
                sources = evidence.get("primary_sources")
                if not isinstance(sources, list) or not sources:
                    raise FoloSourceError(
                        "forwarded run evidence lacks primary sources"
                    )
                expected_primary = {
                    (item.get("path"), item.get("sha256"))
                    for item in sources
                    if isinstance(item, dict)
                }
                actual_primary = {
                    (item.get("path"), item.get("sha256"))
                    for item, _ in receipt_records
                    if item.get("role") == "primary-source"
                }
                if len(expected_primary) != len(sources) or expected_primary != actual_primary:
                    raise FoloSourceError(
                        "forwarded run evidence primary sources do not match receipts"
                    )
                for source_descriptor in sources:
                    _require_cas_descriptor(
                        source_descriptor, "run evidence primary source"
                    )
                    _resolve_descriptor(
                        source_descriptor,
                        root,
                        "run evidence primary source",
                        anchor=active,
                    )
            else:
                for descriptor, artifact_bytes in receipt_records:
                    if descriptor.get("role") != "evidence":
                        continue
                    evidence = _json_artifact(
                        artifact_bytes, str(decision.get("id")), "evidence"
                    )
                    sources = evidence.get("primary_sources")
                    if not isinstance(sources, list):
                        raise FoloSourceError(
                            "run evidence primary_sources are invalid"
                        )
                    for source_descriptor in sources:
                        _require_cas_descriptor(
                            source_descriptor, "run evidence primary source"
                        )
                        _resolve_descriptor(
                            source_descriptor,
                            root,
                            "run evidence primary source",
                            anchor=active,
                        )
        processed = dict(input_state["processed"])
        pending = dict(input_state["pending"])
        recorded_text = validated_at.isoformat().replace("+00:00", "Z")
        for identifier in sorted(candidates):
            candidate = candidates[identifier]
            decision = decisions[identifier]
            record = {
                "entry_id": candidate.get("entry_id"),
                "effective_at": candidate.get("effective_at"),
                **decision,
                "recorded_at": recorded_text,
            }
            if decision["decision"] == "deferred":
                pending[identifier] = record
            else:
                pending.pop(identifier, None)
                processed[identifier] = record
        expected_state = {
            "schema_version": SCHEMA_VERSION,
            "source": "folo-local",
            "source_instance_id": source_instance_id,
            "processed": processed,
            "pending": pending,
        }
        if state != expected_state or state_bytes != _pretty_json_bytes(expected_state):
            raise FoloSourceError("run state does not derive from its input and decisions")
        counts = {value: 0 for value in DECISIONS}
        for decision in decisions.values():
            counts[decision["decision"]] += 1
        if run_manifest.get("counts") != {"total": len(candidates), **counts}:
            raise FoloSourceError("run manifest counts do not match its ledgers")
        return pointer_bytes, pointer, state, state_bytes, state_path
    finally:
        if owned:
            active.close()


def _source_fingerprint(path: Path) -> str:
    path = _resolved(path)
    if path.is_dir():
        return _directory_fingerprint(path)[0]
    if path.is_file() and not path.is_symlink():
        return _sha256_file(path)
    raise FoloSourceError(f"source path is not a regular file or directory: {path}")


def create_extraction_manifest(
    *,
    database_path: Path,
    candidates_path: Path,
    extraction_manifest_path: Path,
    profile_path: Path,
    profile_id: str,
    refresh_receipt_path: Path,
    source_instance_id: str,
    source_snapshot_sha256: str,
    input_state_path: Path | None,
    stable_pointer_path: Path,
    extracted_at: dt.datetime | None = None,
    extraction_bounds: Mapping[str, Any] | None = None,
    source_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Create an immutable provenance root for one candidate extraction."""
    candidates_path = _reject_symlink(candidates_path, "candidate ledger")
    database_path = _reject_symlink(database_path, "read-only database")
    extraction_manifest_path = _reject_symlink(
        extraction_manifest_path, "extraction manifest"
    )
    profile_path = _reject_symlink(profile_path, "Research Watch Profile")
    refresh_receipt_path = _reject_symlink(
        refresh_receipt_path, "refresh receipt"
    )
    stable_pointer_path = _reject_symlink(
        stable_pointer_path, "stable commit-root pointer"
    )
    root = _resolved(artifact_root or extraction_manifest_path.parent)
    if not root.is_dir():
        raise FoloSourceError(f"artifact_root is not a directory: {root}")
    profile = load_watch_profile(profile_path)
    if profile["profile_id"] != profile_id:
        raise FoloSourceError("profile_id does not match the Watch Profile")
    if profile["source_instance_id"] != source_instance_id:
        raise FoloSourceError("source_instance_id does not match the Watch Profile")
    extraction_paths: dict[str, Path] = {
        "candidates": candidates_path,
        "extraction manifest": extraction_manifest_path,
        "profile": profile_path,
        "refresh receipt": refresh_receipt_path,
        "stable pointer": stable_pointer_path,
        "Ed25519 public key": _resolved(profile["ed25519_public_key_path"]),
    }
    if input_state_path is not None:
        extraction_paths["input state"] = _resolved(input_state_path)
    if source_path is not None:
        extraction_paths["source"] = _resolved(source_path)
    if source_path is None or not _aliases(database_path, _resolved(source_path)):
        extraction_paths["read-only database"] = database_path
    _assert_distinct_paths(extraction_paths)
    inspect_sqlite(database_path)
    database_digest = _sha256_file(database_path)
    snapshot_digest = _require_sha256(
        source_snapshot_sha256, "source_snapshot_sha256"
    )
    if source_path is not None and _source_fingerprint(source_path) != snapshot_digest:
        raise FoloSourceError("source path fingerprint does not match extraction snapshot")
    validate_refresh_receipt(
        refresh_receipt_path,
        source_instance_id=source_instance_id,
        source_snapshot_sha256=snapshot_digest,
        database_snapshot_sha256=database_digest,
        now=extracted_at,
        max_age_minutes=profile["refresh_max_age_minutes"],
        profile=profile,
    )
    pointer_bytes, _pointer, state, state_bytes, committed_state_path = _read_pointer(
        stable_pointer_path, root, source_instance_id
    )
    if input_state_path is not None:
        actual_input = _resolved(input_state_path)
        if committed_state_path is None or not _aliases(actual_input, committed_state_path):
            raise FoloSourceError("input_state_path is not the committed state")
    candidate_records = _read_jsonl(candidates_path, "candidates")
    candidates = _unique_by_id(candidate_records, "candidate")
    processed = state["processed"]
    pending = state["pending"]
    timestamp = extracted_at or dt.datetime.now(dt.timezone.utc)
    if timestamp.tzinfo is None:
        raise FoloSourceError("extracted_at must include a timezone")
    timestamp = timestamp.astimezone(dt.timezone.utc)
    threshold = timestamp - dt.timedelta(hours=profile["max_hours"])
    for identifier, candidate in candidates.items():
        if (
            candidate.get("schema_version") != SCHEMA_VERSION
            or candidate.get("source") != "folo-local"
            or candidate.get("source_instance_id") != source_instance_id
            or candidate.get("candidate_sha256") != candidate_digest(candidate)
        ):
            raise FoloSourceError(f"candidate {identifier} provenance is invalid")
        if candidate.get("feed_id") not in profile["authorized_feed_ids"]:
            raise FoloSourceError(f"candidate {identifier} feed is not authorized")
        for field in (
            "entry_id", "feed_id", "title", "url", "effective_at", "body"
        ):
            if not isinstance(candidate.get(field), str) or not candidate[field]:
                raise FoloSourceError(f"candidate {identifier} requires {field}")
        if not _candidate_matches_query_scope(candidate, profile["query_scope"]):
            raise FoloSourceError(f"candidate {identifier} does not match query scope")
        effective_at = _parse_utc(
            candidate.get("effective_at"), f"candidate {identifier} effective_at"
        )
        due_retry = candidate.get("prior_decision_sha256") is not None
        if effective_at > timestamp or (effective_at < threshold and not due_retry):
            raise FoloSourceError(f"candidate {identifier} is outside extraction bounds")
        effective_ms = candidate.get("effective_at_ms")
        if effective_ms is not None and (
            isinstance(effective_ms, bool)
            or not isinstance(effective_ms, int)
            or abs(effective_ms - int(effective_at.timestamp() * 1000)) > 1
        ):
            raise FoloSourceError(f"candidate {identifier} effective time is inconsistent")
        if identifier in processed:
            raise FoloSourceError(f"candidate {identifier} is already processed")
        prior = candidate.get("prior_decision_sha256")
        if identifier in pending:
            if prior != pending[identifier].get("decision_sha256"):
                raise FoloSourceError(f"candidate {identifier} does not bind pending state")
        elif prior is not None:
            raise FoloSourceError(f"candidate {identifier} has unexpected prior state")
    bounds = dict(extraction_bounds or {})
    hours = float(bounds.get("hours", profile["max_hours"]))
    limit = int(bounds.get("limit", profile["max_candidates"]))
    if hours < 0 or hours > profile["max_hours"] or not 1 <= limit <= profile["max_candidates"]:
        raise FoloSourceError("extraction bounds exceed the Watch Profile")
    verification_state: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=_safe_scratch_root((database_path,)),
            prefix="autoresearch-folo-verification-state-",
            suffix=".json",
            delete=False,
        ) as handle:
            verification_state = Path(handle.name)
            handle.write(state_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        expected_candidates = extract_candidates(
            database_path,
            state_path=verification_state,
            source_instance_id=source_instance_id,
            hours=hours,
            limit=limit,
            now_ms=int(timestamp.timestamp() * 1000),
            profile_path=profile_path,
        )
    finally:
        if verification_state is not None:
            with contextlib.suppress(OSError):
                verification_state.unlink()
    if candidate_records != expected_candidates:
        raise FoloSourceError(
            "candidate ledger does not equal deterministic profile-scoped extraction"
        )
    database_object = (
        root
        / "autoresearch/research-radar/objects/sha256"
        / f"{database_digest}.sqlite"
    )
    database_bytes = _read_regular_bytes(database_path, "read-only database")
    forbidden_inodes: set[tuple[int, int]] = set()
    for input_path in extraction_paths.values():
        with contextlib.suppress(OSError):
            details = input_path.stat()
            forbidden_inodes.add((details.st_dev, details.st_ino))
    with _AnchoredArtifacts(root) as anchor:
        _write_immutable(
            database_object,
            database_bytes,
            artifact_root=root,
            protected_roots=(
                [source_path, _resolved(profile["ed25519_public_key_path"])]
                if source_path is not None
                else [_resolved(profile["ed25519_public_key_path"])]
            ),
            anchor=anchor,
            forbidden_inodes=forbidden_inodes,
        )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "type": "folo-extraction-manifest",
        "source": "folo-local",
        "source_instance_id": source_instance_id,
        "profile": {
            "id": profile_id,
            **_descriptor(profile_path, root, "profile"),
        },
        "refresh_receipt": _descriptor(
            refresh_receipt_path, root, "refresh receipt"
        ),
        "source_snapshot_sha256": snapshot_digest,
        "database_snapshot": {
            "path": _relative(database_object, root, "database snapshot"),
            "sha256": database_digest,
        },
        "source_path": str(_resolved(source_path)) if source_path is not None else None,
        "candidates": {
            **_descriptor(candidates_path, root, "candidate ledger"),
            "count": len(candidates),
        },
        "input_state": {
            "path": (
                _relative(committed_state_path, root, "input state")
                if committed_state_path is not None
                else None
            ),
            "sha256": _sha256_bytes(state_bytes),
        },
        "input_commit_root_sha256": _sha256_bytes(pointer_bytes),
        "extraction_bounds": {"hours": hours, "limit": limit},
        "extracted_at": timestamp.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    data = _pretty_json_bytes(payload)
    with _AnchoredArtifacts(root) as anchor:
        _write_immutable(
            extraction_manifest_path,
            data,
            artifact_root=root,
            protected_roots=(
                [
                    source_path,
                    database_path,
                    _resolved(profile["ed25519_public_key_path"]),
                ]
                if source_path is not None
                else [database_path, _resolved(profile["ed25519_public_key_path"])]
            ),
            anchor=anchor,
            forbidden_inodes=forbidden_inodes,
        )
    return {
        **payload,
        "manifest_path": str(extraction_manifest_path),
        "manifest_sha256": _sha256_bytes(data),
    }


def _atomic_replace_pointer(
    path: Path,
    data: bytes,
    original: bytes,
    *,
    artifact_root: Path,
    protected_roots: Iterable[Path],
    anchor: _AnchoredArtifacts | None = None,
) -> None:
    root = _resolved(artifact_root)
    target = _resolved(path)
    if not _is_within(target, root):
        raise FoloSourceError("stable pointer escapes artifact_root")
    _refuse_live_write(target, protected_roots)
    owned = anchor is None
    active = anchor or _AnchoredArtifacts(root)
    try:
        active.replace(
            active.relative(target, "stable commit-root pointer"),
            data,
            original,
            post_sync_hook=target.parent,
        )
    finally:
        if owned:
            active.close()


def _assert_distinct_paths(named_paths: Mapping[str, Path]) -> None:
    entries = [(name, _resolved(path)) for name, path in named_paths.items()]
    for index, (left_name, left) in enumerate(entries):
        for right_name, right in entries[index + 1 :]:
            if _aliases(left, right):
                raise FoloSourceError(
                    f"artifact path alias is forbidden: {left_name} and {right_name}"
                )


def publish_run(
    extraction_manifest_path: Path,
    decisions_path: Path,
    *,
    artifact_root: Path,
    stable_pointer_path: Path | None = None,
    leveldb_path: Path | None = None,
    expected_commit_root_sha256: str | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Publish one validated run through the sole durable commit-root pointer."""
    root = _resolved(artifact_root)
    if not root.is_dir():
        raise FoloSourceError(f"artifact_root is not a directory: {root}")
    extraction_manifest_path = _reject_symlink(
        extraction_manifest_path, "extraction manifest"
    )
    decisions_path = _reject_symlink(decisions_path, "decision ledger")
    pointer_path = _reject_symlink(
        stable_pointer_path
        or root / "autoresearch/research-radar/manifest.json",
        "stable commit-root pointer",
    )
    protected_roots: list[Path] = []
    if leveldb_path is not None:
        protected_roots.append(_resolved(leveldb_path))
    for path, field in (
        (extraction_manifest_path, "extraction manifest"),
        (decisions_path, "decision ledger"),
        (pointer_path, "stable pointer"),
    ):
        if not _is_within(path, root):
            raise FoloSourceError(f"{field} escapes artifact_root")
        for protected in protected_roots:
            if path == protected or _is_within(path, protected):
                raise FoloSourceError(f"{field} overlaps protected source data")

    completed = now or dt.datetime.now(dt.timezone.utc)
    if completed.tzinfo is None:
        raise FoloSourceError("publish time must include a timezone")
    completed = completed.astimezone(dt.timezone.utc)
    completed_text = completed.isoformat().replace("+00:00", "Z")

    with _AnchoredArtifacts(root) as anchor, contextlib.ExitStack() as cleanup:
        extraction_relative = anchor.relative(
            extraction_manifest_path, "extraction manifest"
        )
        decisions_relative = anchor.relative(decisions_path, "decision ledger")
        pointer_relative = anchor.relative(pointer_path, "stable pointer")
        extraction_bytes = anchor.read(extraction_relative, "extraction manifest")
        decisions_input_bytes = anchor.read(decisions_relative, "decision ledger")
        extraction_sha256 = _sha256_bytes(extraction_bytes)
        input_decisions_sha256 = _sha256_bytes(decisions_input_bytes)
        try:
            extraction = json.loads(extraction_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FoloSourceError("extraction manifest is invalid JSON") from exc
        if (
            not isinstance(extraction, dict)
            or extraction.get("schema_version") != SCHEMA_VERSION
            or extraction.get("type") != "folo-extraction-manifest"
            or extraction.get("source") != "folo-local"
        ):
            raise FoloSourceError("extraction manifest schema is invalid")
        extracted_at = _parse_utc(extraction.get("extracted_at"), "extracted_at")
        extraction_age = completed - extracted_at
        if extraction_age < dt.timedelta(0):
            raise FoloSourceError("extraction timestamp is in the future")
        source_instance_id = _require_nonempty_text(
            extraction.get("source_instance_id"), "extraction source_instance_id"
        )
        source_path: Path | None = None
        if extraction.get("source_path") is not None:
            source_path = _resolved(extraction["source_path"])
            protected_roots.append(source_path)
        profile_path, profile_bytes = _resolve_descriptor(
            {
                "path": extraction.get("profile", {}).get("path"),
                "sha256": extraction.get("profile", {}).get("sha256"),
            },
            root,
            "extraction profile",
            protected_roots,
            anchor=anchor,
        )
        profile = load_watch_profile(profile_path)
        if profile["profile_bytes"] != profile_bytes:
            raise FoloSourceError("extraction profile changed while validating")
        if (
            profile["profile_id"] != extraction.get("profile", {}).get("id")
            or profile["profile_sha256"] != extraction.get("profile", {}).get("sha256")
            or profile["source_instance_id"] != source_instance_id
        ):
            raise FoloSourceError("extraction manifest profile binding is invalid")
        database_path, database_bytes = _resolve_descriptor(
            extraction.get("database_snapshot"),
            root,
            "extraction database snapshot",
            protected_roots,
            anchor=anchor,
        )
        database_sha256 = _sha256_bytes(database_bytes)
        refresh_path, refresh_bytes = _resolve_descriptor(
            extraction.get("refresh_receipt"),
            root,
            "extraction refresh receipt",
            protected_roots,
            anchor=anchor,
        )
        snapshot_sha256 = _require_sha256(
            extraction.get("source_snapshot_sha256"), "extraction source snapshot"
        )
        try:
            refresh_payload = json.loads(refresh_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FoloSourceError("extraction refresh receipt is invalid JSON") from exc
        _validate_refresh_receipt_payload(
            refresh_payload,
            source_instance_id=source_instance_id,
            source_snapshot_sha256=snapshot_sha256,
            database_snapshot_sha256=database_sha256,
            now=completed,
            max_age_minutes=profile["refresh_max_age_minutes"],
            profile=profile,
        )
        candidates_path, candidates_bytes = _resolve_descriptor(
            extraction.get("candidates"),
            root,
            "extraction candidate ledger",
            protected_roots,
            anchor=anchor,
        )
        candidate_records = _read_jsonl_bytes(
            candidates_bytes, "candidates", candidates_path
        )
        candidates = _unique_by_id(candidate_records, "candidate")
        if extraction.get("candidates", {}).get("count") != len(candidates):
            raise FoloSourceError("extraction candidate count does not match")
        bounds = extraction.get("extraction_bounds")
        if not isinstance(bounds, dict):
            raise FoloSourceError("extraction bounds are invalid")
        try:
            hours = float(bounds.get("hours"))
            limit = int(bounds.get("limit"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise FoloSourceError("extraction bounds are invalid") from exc
        if (
            not math.isfinite(hours)
            or hours < 0
            or hours > profile["max_hours"]
            or not 1 <= limit <= profile["max_candidates"]
        ):
            raise FoloSourceError("extraction bounds exceed the Watch Profile")

        core_paths: dict[str, Path] = {
            "extraction manifest": extraction_manifest_path,
            "candidate ledger": candidates_path,
            "decision ledger": decisions_path,
            "profile": profile_path,
            "refresh receipt": refresh_path,
            "database snapshot": database_path,
            "stable pointer": pointer_path,
            "Ed25519 public key": _resolved(profile["ed25519_public_key_path"]),
        }
        if source_path is not None:
            core_paths["source"] = source_path
        _assert_distinct_paths(core_paths)
        for name, path in core_paths.items():
            if name != "source":
                for protected in protected_roots:
                    if path == protected or _is_within(path, protected):
                        raise FoloSourceError(
                            "artifact input overlaps protected source data"
                        )
        protected_roots.append(_resolved(profile["ed25519_public_key_path"]))

        if extraction_age > dt.timedelta(minutes=profile["refresh_max_age_minutes"]):
            raise FoloSourceError("extraction manifest is too old to publish")

        verification_database: Path | None = None
        verification_state: Path | None = None
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=_safe_scratch_root(tuple(protected_roots)),
            prefix="autoresearch-folo-publish-db-",
            suffix=".sqlite",
            delete=False,
        ) as handle:
            verification_database = Path(handle.name)
            handle.write(database_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        cleanup.callback(lambda path=verification_database: path.unlink(missing_ok=True))
        inspect_sqlite(verification_database)
        # The committed state is read under the publication lock below.  The
        # database is frozen here; deterministic extraction is repeated once
        # that exact input state has been established.

        lock_path = pointer_path.with_name(f".{pointer_path.name}.lock")
        _refuse_live_write(lock_path, protected_roots)
        lock_relative = anchor.relative(lock_path, "stable commit lock")
        lock_descriptor = anchor.open_lock(lock_relative)
        cleanup.callback(os.close, lock_descriptor)
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        anchor.verify_lock_binding(lock_relative, lock_descriptor)
        cleanup.callback(fcntl.flock, lock_descriptor, fcntl.LOCK_UN)
        pointer_bytes, pointer, state, state_bytes, state_path = _read_pointer(
            pointer_path,
            root,
            source_instance_id,
            anchor=anchor,
        )
        current_root_sha256 = _sha256_bytes(pointer_bytes)
        if expected_commit_root_sha256 is not None:
            if _require_sha256(
                expected_commit_root_sha256, "expected_commit_root_sha256"
            ) != current_root_sha256:
                raise FoloSourceError("expected commit-root hash is stale")
        input_root = _require_sha256(
            extraction.get("input_commit_root_sha256"),
            "extraction input_commit_root_sha256",
        )
        if current_root_sha256 != input_root:
            if pointer is not None:
                _prior_manifest_path, prior_manifest_bytes = _resolve_descriptor(
                    {
                        "path": pointer.get("manifest_path"),
                        "sha256": pointer.get("manifest_sha256"),
                    },
                    root,
                    "current run manifest",
                    anchor=anchor,
                )
                try:
                    prior_manifest = json.loads(prior_manifest_bytes.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise FoloSourceError("current run manifest is invalid JSON") from exc
                if (
                    isinstance(prior_manifest, dict)
                    and prior_manifest.get("extraction_manifest_sha256")
                    == extraction_sha256
                    and prior_manifest.get("input_decisions_sha256")
                    == input_decisions_sha256
                ):
                    return {
                        "status": "ok",
                        "recorded": 0,
                        "already_recorded": len(candidates),
                        "total": len(candidates),
                        "run_id": pointer["run_id"],
                        "run_manifest_path": str(root / pointer["manifest_path"]),
                        "run_manifest_sha256": pointer["manifest_sha256"],
                        "state_path": str(root / pointer["state_path"]),
                        "state_sha256": pointer["state_sha256"],
                        "stable_pointer_path": str(pointer_path),
                        "stable_pointer_sha256": current_root_sha256,
                    }
            raise FoloSourceError("extraction commit-root provenance is stale")
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=_safe_scratch_root(tuple(protected_roots)),
                prefix="autoresearch-folo-publish-state-",
                suffix=".json",
                delete=False,
            ) as handle:
                verification_state = Path(handle.name)
                handle.write(state_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            expected_candidates = extract_candidates(
                verification_database,
                state_path=verification_state,
                source_instance_id=source_instance_id,
                hours=hours,
                limit=limit,
                now_ms=int(extracted_at.timestamp() * 1000),
                authorized_feed_ids=profile["authorized_feed_ids"],
                query_scope=profile["query_scope"],
            )
        finally:
            if verification_state is not None:
                with contextlib.suppress(OSError):
                    verification_state.unlink()
                verification_state = None
        if candidate_records != expected_candidates:
            raise FoloSourceError(
                "candidate ledger does not equal deterministic publication re-extraction"
            )
        input_state = extraction.get("input_state")
        if not isinstance(input_state, dict):
            raise FoloSourceError("extraction input_state is invalid")
        if input_state.get("sha256") != _sha256_bytes(state_bytes):
            raise FoloSourceError("extraction input state hash is stale")
        expected_state_path = input_state.get("path")
        actual_state_path = (
            _relative(state_path, root, "current state") if state_path is not None else None
        )
        if expected_state_path != actual_state_path:
            raise FoloSourceError("extraction input state path is stale")
        if pointer is not None and pointer.get("profile_sha256") != profile["profile_sha256"]:
            raise FoloSourceError("Watch Profile changed across one source cursor")

        processed = dict(state["processed"])
        pending = dict(state["pending"])
        for identifier, candidate in candidates.items():
            if (
                candidate.get("schema_version") != SCHEMA_VERSION
                or candidate.get("source") != "folo-local"
                or candidate.get("source_instance_id") != source_instance_id
                or candidate.get("candidate_sha256") != candidate_digest(candidate)
                or candidate.get("feed_id") not in profile["authorized_feed_ids"]
            ):
                raise FoloSourceError(f"candidate {identifier} validation failed")
            if identifier in processed:
                raise FoloSourceError(f"candidate {identifier} is already processed")
            prior = pending.get(identifier)
            if prior is not None:
                if candidate.get("prior_decision_sha256") != prior.get("decision_sha256"):
                    raise FoloSourceError(f"candidate {identifier} pending binding failed")
            elif candidate.get("prior_decision_sha256") is not None:
                raise FoloSourceError(f"candidate {identifier} has unexpected prior binding")
        decisions_raw = _unique_by_id(
            _read_jsonl_bytes(decisions_input_bytes, "decisions", decisions_path),
            "decision",
        )
        if set(decisions_raw) != set(candidates):
            missing = sorted(set(candidates) - set(decisions_raw))
            extra = sorted(set(decisions_raw) - set(candidates))
            raise FoloSourceError(
                f"decision ledger is not one-to-one (missing={missing}, extra={extra})"
            )
        staged_objects: dict[str, bytes] = {}
        profile_object = _stage_cas_object(staged_objects, profile_bytes)
        refresh_object = _stage_cas_object(staged_objects, refresh_bytes)
        public_key_object = _stage_cas_object(
            staged_objects, profile["ed25519_public_key_bytes"]
        )
        authority_artifacts: list[dict[str, str]] = []
        for profile_field, role in (
            ("research_brief", "research-brief"),
            ("adaptation_plan", "adaptation-plan"),
            ("experiment_contract", "experiment-contract"),
        ):
            authority_ref = profile["authority"].get(profile_field)
            if not isinstance(authority_ref, dict) or "path" not in authority_ref:
                continue
            relative = PurePosixPath(authority_ref["path"])
            authority_path = profile_path.parent / Path(*relative.parts)
            authority_bytes = _read_regular_bytes(
                authority_path, f"Watch Profile authority {profile_field}"
            )
            if _sha256_bytes(authority_bytes) != authority_ref["sha256"]:
                raise FoloSourceError(
                    f"Watch Profile authority {profile_field} changed"
                )
            authority_object = _stage_cas_object(staged_objects, authority_bytes)
            authority_artifacts.append(
                {
                    "role": role,
                    "id": str(authority_ref["id"]),
                    **authority_object,
                }
            )
        decisions = {
            identifier: _normalize_decision(
                decisions_raw[identifier], candidates[identifier], root, profile,
                now=completed,
                protected_roots=protected_roots,
                staged_objects=staged_objects,
                anchor=anchor,
            )
            for identifier in sorted(candidates)
        }
        for decision in decisions.values():
            for receipt in decision["receipts"]:
                receipt_path = _resolved(root / receipt["path"])
                if receipt["role"] != "profile":
                    for core_name, core_path in core_paths.items():
                        if _aliases(receipt_path, core_path):
                            raise FoloSourceError(
                                f"receipt aliases core artifact: {core_name}"
                            )

        for identifier in sorted(candidates):
            candidate = candidates[identifier]
            decision = decisions[identifier]
            new_record = {
                "entry_id": candidate.get("entry_id"),
                "effective_at": candidate.get("effective_at"),
                **decision,
                "recorded_at": completed_text,
            }
            if decision["decision"] == "deferred":
                pending[identifier] = new_record
            else:
                pending.pop(identifier, None)
                processed[identifier] = new_record
        next_state = {
            "schema_version": SCHEMA_VERSION,
            "source": "folo-local",
            "source_instance_id": source_instance_id,
            "processed": processed,
            "pending": pending,
        }
        normalized_decision_bytes = "".join(
            json.dumps(decisions[key], ensure_ascii=False, sort_keys=True) + "\n"
            for key in sorted(decisions)
        ).encode("utf-8")
        next_state_bytes = _pretty_json_bytes(next_state)
        next_state_sha256 = _sha256_bytes(next_state_bytes)
        decision_sha256 = _sha256_bytes(normalized_decision_bytes)
        run_preimage = {
            "extraction_manifest_sha256": extraction_sha256,
            "input_decisions_sha256": input_decisions_sha256,
            "decisions_sha256": decision_sha256,
            "state_sha256": next_state_sha256,
            "previous_commit_root_sha256": current_root_sha256,
            "profile_sha256": profile["profile_sha256"],
        }
        run_id = _sha256_bytes(_canonical_bytes(run_preimage))
        run_dir = root / "autoresearch/research-radar/runs" / run_id
        candidates_target = run_dir / "candidates.jsonl"
        decisions_target = run_dir / "decisions.jsonl"
        extraction_target = run_dir / "extraction-manifest.json"
        profile_target = run_dir / "research-watch-profile.json"
        refresh_target = run_dir / "refresh-receipt.json"
        public_key_target = run_dir / "refresh-public-key.ed25519"
        input_state_target = run_dir / "input-state.json"
        state_target = run_dir / "state.json"
        manifest_target = run_dir / "manifest.json"
        forbidden_inodes: set[tuple[int, int]] = set()
        for input_path in core_paths.values():
            with contextlib.suppress(OSError):
                details = input_path.stat()
                forbidden_inodes.add((details.st_dev, details.st_ino))
        for relative_path, object_bytes in sorted(staged_objects.items()):
            _write_immutable(
                root / relative_path,
                object_bytes,
                artifact_root=root,
                protected_roots=protected_roots,
                anchor=anchor,
                forbidden_inodes=forbidden_inodes,
            )
        for target, data in (
            (candidates_target, candidates_bytes),
            (decisions_target, normalized_decision_bytes),
            (extraction_target, extraction_bytes),
            (profile_target, profile_bytes),
            (refresh_target, refresh_bytes),
            (public_key_target, profile["ed25519_public_key_bytes"]),
            (input_state_target, state_bytes),
            (state_target, next_state_bytes),
        ):
            _write_immutable(
                target,
                data,
                artifact_root=root,
                protected_roots=protected_roots,
                anchor=anchor,
                forbidden_inodes=forbidden_inodes,
            )
        counts = {value: 0 for value in DECISIONS}
        for decision in decisions.values():
            counts[decision["decision"]] += 1
        run_manifest = {
            "schema_version": SCHEMA_VERSION,
            "type": "research-radar-run-manifest",
            "source": "folo-local",
            "source_instance_id": source_instance_id,
            "run_id": run_id,
            "profile_id": profile["profile_id"],
            "profile_sha256": profile["profile_sha256"],
            "profile_path": _relative(profile_target, root, "run profile"),
            "refresh_receipt_path": _relative(
                refresh_target, root, "run refresh receipt"
            ),
            "refresh_receipt_sha256": _sha256_bytes(refresh_bytes),
            "refresh_public_key": {
                "path": _relative(public_key_target, root, "run refresh public key"),
                "sha256": profile["ed25519_public_key_sha256"],
            },
            "source_snapshot_sha256": snapshot_sha256,
            "database_snapshot": {
                "path": _relative(database_path, root, "run database snapshot"),
                "sha256": database_sha256,
            },
            "authority_sha256": profile["authority_sha256"],
            "authority_artifacts": authority_artifacts,
            "extraction_manifest_path": _relative(extraction_target, root, "run extraction"),
            "extraction_manifest_sha256": extraction_sha256,
            "candidates_path": _relative(candidates_target, root, "run candidates"),
            "candidates_sha256": _sha256_bytes(candidates_bytes),
            "input_state": {
                "path": _relative(input_state_target, root, "run input state"),
                "sha256": _sha256_bytes(state_bytes),
            },
            "input_decisions_sha256": input_decisions_sha256,
            "decisions_path": _relative(decisions_target, root, "run decisions"),
            "decisions_sha256": decision_sha256,
            "state_path": _relative(state_target, root, "run state"),
            "state_sha256": next_state_sha256,
            "previous_commit_root_sha256": current_root_sha256,
            "counts": {"total": len(candidates), **counts},
            "publication_status": "validated",
            "validated_at": completed_text,
        }
        run_manifest_bytes = _pretty_json_bytes(run_manifest)
        _write_immutable(
            manifest_target, run_manifest_bytes, artifact_root=root,
            protected_roots=protected_roots, anchor=anchor,
            forbidden_inodes=forbidden_inodes,
        )
        run_manifest_sha256 = _sha256_bytes(run_manifest_bytes)
        pointer_payload = {
            "schema_version": SCHEMA_VERSION,
            "source": "folo-local",
            "run_id": run_id,
            "manifest_path": _relative(manifest_target, root, "run manifest"),
            "manifest_sha256": run_manifest_sha256,
            "state_path": _relative(state_target, root, "run state"),
            "state_sha256": next_state_sha256,
            "profile_id": profile["profile_id"],
            "profile_sha256": profile["profile_sha256"],
            "previous_commit_root_sha256": current_root_sha256,
            "outcome": "research-radar-cycle-complete",
            "completed_at": completed_text,
        }
        pointer_data = _pretty_json_bytes(pointer_payload)
        anchor.verify_lock_binding(lock_relative, lock_descriptor)
        _atomic_replace_pointer(
            pointer_path, pointer_data, pointer_bytes, artifact_root=root,
            protected_roots=protected_roots, anchor=anchor,
        )
        return {
            "status": "ok",
            "recorded": len(candidates),
            "already_recorded": 0,
            "total": len(candidates),
            "run_id": run_id,
            "run_manifest_path": str(manifest_target),
            "run_manifest_sha256": run_manifest_sha256,
            "state_path": str(state_target),
            "state_sha256": next_state_sha256,
            "stable_pointer_path": str(pointer_path),
            "stable_pointer_sha256": _sha256_bytes(pointer_data),
        }
def _default_source_instance(source: Path) -> str:
    identity = hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:16]
    return f"folo:{identity}"


def _database_context(
    database_override: str | None, leveldb_override: str | None
) -> contextlib.AbstractContextManager[Any]:
    if database_override:
        database = _resolved(database_override)
        details = inspect_sqlite(database)
        details.update(
            {
                "snapshot_mode": "explicit-sqlite",
                "source_snapshot_sha256": _sha256_file(database),
                "database_snapshot_sha256": _sha256_file(database),
            }
        )
        return contextlib.nullcontext((database, details))
    return reconstructed_database(leveldb_path(leveldb_override))


def _doctor(args: argparse.Namespace) -> int:
    source = leveldb_path(args.leveldb)
    with reconstructed_database(source) as (_database, details):
        result = {
            "status": "ok",
            "source": "folo-local",
            "source_instance_id": args.source_instance_id or _default_source_instance(source),
            "cache": str(source),
            "snapshot_mode": "temporary-copy",
            **details,
        }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "FOLO local source: ok\n"
            f"source_instance_id: {result['source_instance_id']}\n"
            f"quick_check: {result['quick_check']}\n"
            f"tables: {result['tables']}"
        )
    return 0


def _candidates(args: argparse.Namespace) -> int:
    root = _resolved(args.artifact_root)
    profile_path = _resolved(args.profile)
    profile = load_watch_profile(profile_path)
    source = leveldb_path(args.leveldb) if not args.database else _resolved(args.database)
    pointer_path = _resolved(
        args.stable_pointer or root / "autoresearch/research-radar/manifest.json"
    )
    _pointer_bytes, _pointer, _state, state_bytes, state_path = _read_pointer(
        pointer_path, root, profile["source_instance_id"]
    )
    extracted_at = (
        dt.datetime.fromtimestamp(args.now_ms / 1000, tz=dt.timezone.utc)
        if args.now_ms is not None
        else dt.datetime.now(dt.timezone.utc)
    )
    temporary_state: Path | None = None
    try:
        if state_path is None:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=_safe_scratch_root((source,)),
                prefix="autoresearch-folo-state-", suffix=".json",
                delete=False,
            ) as handle:
                temporary_state = Path(handle.name)
                handle.write(state_bytes)
            extraction_state_path = temporary_state
        else:
            extraction_state_path = state_path
        with _database_context(args.database, args.leveldb) as (database, details):
            snapshot_sha256 = details["source_snapshot_sha256"]
            validate_refresh_receipt(
                _resolved(args.refresh_receipt),
                source_instance_id=profile["source_instance_id"],
                source_snapshot_sha256=snapshot_sha256,
                now=extracted_at,
                max_age_minutes=profile["refresh_max_age_minutes"],
                profile=profile,
            )
            candidates = extract_candidates(
                database,
                state_path=extraction_state_path,
                source_instance_id=profile["source_instance_id"],
                hours=profile["max_hours"],
                limit=profile["max_candidates"],
                now_ms=args.now_ms,
                profile_path=profile_path,
            )
            candidate_bytes = "".join(
                json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                for record in candidates
            ).encode("utf-8")
            output_path = _resolved(args.output)
            manifest_path = _resolved(args.extraction_manifest)
            _assert_distinct_paths(
                {
                    "source": source,
                    "profile": profile_path,
                    "refresh receipt": _resolved(args.refresh_receipt),
                    "candidate output": output_path,
                    "extraction manifest": manifest_path,
                    "stable pointer": pointer_path,
                }
            )
            _write_immutable(
                output_path, candidate_bytes, artifact_root=root,
                protected_roots=(source, database),
            )
            manifest = create_extraction_manifest(
                database_path=database,
                candidates_path=output_path,
                extraction_manifest_path=manifest_path,
                profile_path=profile_path,
                profile_id=profile["profile_id"],
                refresh_receipt_path=_resolved(args.refresh_receipt),
                source_instance_id=profile["source_instance_id"],
                source_snapshot_sha256=snapshot_sha256,
                input_state_path=state_path,
                stable_pointer_path=pointer_path,
                extracted_at=extracted_at,
                extraction_bounds={
                    "hours": profile["max_hours"], "limit": profile["max_candidates"]
                },
                source_path=source,
                artifact_root=root,
            )
    finally:
        if temporary_state is not None:
            with contextlib.suppress(OSError):
                temporary_state.unlink()
    print(
        json.dumps(
            {
                "status": "ok",
                "candidates": len(candidates),
                "candidate_ledger_path": str(output_path),
                "candidate_ledger_sha256": _sha256_bytes(candidate_bytes),
                "extraction_manifest_path": str(manifest_path),
                "extraction_manifest_sha256": manifest["manifest_sha256"],
                "state_advanced": False,
            },
            sort_keys=True,
        )
    )
    return 0


def _record(args: argparse.Namespace) -> int:
    result = publish_run(
        _resolved(args.extraction_manifest),
        _resolved(args.decisions),
        artifact_root=_resolved(args.artifact_root),
        stable_pointer_path=(
            _resolved(args.stable_pointer) if args.stable_pointer else None
        ),
        leveldb_path=(_resolved(args.leveldb) if args.leveldb else None),
        expected_commit_root_sha256=args.expected_commit_root_sha256,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


class _MachineArgumentParser(argparse.ArgumentParser):
    """Return parse failures through the CLI's single JSON error channel."""

    def error(self, message: str) -> None:
        raise FoloSourceError(f"argument error: {message}")


def build_parser(*, machine_errors: bool = True) -> argparse.ArgumentParser:
    parser_class = _MachineArgumentParser if machine_errors else argparse.ArgumentParser
    parser = parser_class(prog="folo-source")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser(
        "doctor", help="validate a disposable read-only FOLO cache reconstruction"
    )
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--leveldb", default=os.environ.get("FOLO_LEVELDB_PATH"))
    doctor.add_argument(
        "--source-instance-id", default=os.environ.get("AUTORESEARCH_FOLO_SOURCE_ID")
    )
    doctor.set_defaults(func=_doctor)

    candidates = subparsers.add_parser(
        "candidates", help="write an immutable, profile-scoped extraction manifest"
    )
    candidates.add_argument("--refresh-receipt", required=True)
    candidates.add_argument("--profile", required=True)
    candidates.add_argument("--artifact-root", required=True)
    candidates.add_argument("--output", required=True)
    candidates.add_argument("--extraction-manifest", required=True)
    candidates.add_argument("--stable-pointer")
    candidates.add_argument("--leveldb", default=os.environ.get("FOLO_LEVELDB_PATH"))
    candidates.add_argument(
        "--database", default=os.environ.get("AUTORESEARCH_FOLO_SQLITE_PATH"),
        help=argparse.SUPPRESS,
    )
    candidates.add_argument("--now-ms", type=int, default=None, help=argparse.SUPPRESS)
    candidates.set_defaults(func=_candidates)

    record = subparsers.add_parser(
        "record", help="publish through the sole stable commit-root pointer"
    )
    record.add_argument("--extraction-manifest", required=True)
    record.add_argument("--decisions", required=True)
    record.add_argument("--artifact-root", required=True)
    record.add_argument("--stable-pointer")
    record.add_argument("--leveldb", default=os.environ.get("FOLO_LEVELDB_PATH"))
    record.add_argument("--expected-commit-root-sha256")
    record.set_defaults(func=_record)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parser = build_parser(machine_errors=True)
        args = parser.parse_args(argv)
        return int(args.func(args))
    except FoloCommitIndeterminate as exc:
        print(
            json.dumps(
                {
                    "status": "commit-indeterminate",
                    "observed_status": exc.observed_status,
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3
    except FoloSourceError as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print(
            json.dumps({"status": "interrupted", "error": "interrupted"}),
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
