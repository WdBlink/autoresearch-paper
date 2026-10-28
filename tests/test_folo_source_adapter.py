from __future__ import annotations

import argparse
import contextlib
from contextlib import redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor
import copy
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "autoresearch-radar"
    / "scripts"
)
sys.path.insert(0, str(SCRIPT_DIR))
import folo_source as subject


NOW_MS = 2_000_000_000_000
NOW = dt.datetime.fromtimestamp(NOW_MS / 1000, tz=dt.timezone.utc)
HOUR_MS = 60 * 60 * 1000
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


# Minimal RFC 8032 primitives keep the protocol fixture independent of optional
# crypto wheels.  The signing seed is test-only; Watch Profiles contain only
# the corresponding public key descriptor.
_ED25519_Q = 2**255 - 19
_ED25519_L = 2**252 + 27742317777372353535851937790883648493
_ED25519_D = (-121665 * pow(121666, _ED25519_Q - 2, _ED25519_Q)) % _ED25519_Q
_ED25519_I = pow(2, (_ED25519_Q - 1) // 4, _ED25519_Q)


def _ed25519_xrecover(y: int) -> int:
    xx = (y * y - 1) * pow(_ED25519_D * y * y + 1, _ED25519_Q - 2, _ED25519_Q)
    x = pow(xx % _ED25519_Q, (_ED25519_Q + 3) // 8, _ED25519_Q)
    if (x * x - xx) % _ED25519_Q != 0:
        x = (x * _ED25519_I) % _ED25519_Q
    if x & 1:
        x = _ED25519_Q - x
    return x


_ED25519_BY = (4 * pow(5, _ED25519_Q - 2, _ED25519_Q)) % _ED25519_Q
_ED25519_B = (_ed25519_xrecover(_ED25519_BY), _ED25519_BY)


def _ed25519_add(left: tuple[int, int], right: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = left
    x2, y2 = right
    product = (_ED25519_D * x1 * x2 * y1 * y2) % _ED25519_Q
    x3 = (x1 * y2 + x2 * y1) * pow(1 + product, _ED25519_Q - 2, _ED25519_Q)
    y3 = (y1 * y2 + x1 * x2) * pow(1 - product, _ED25519_Q - 2, _ED25519_Q)
    return x3 % _ED25519_Q, y3 % _ED25519_Q


def _ed25519_scalarmult(point: tuple[int, int], scalar: int) -> tuple[int, int]:
    result = (0, 1)
    addend = point
    while scalar:
        if scalar & 1:
            result = _ed25519_add(result, addend)
        addend = _ed25519_add(addend, addend)
        scalar >>= 1
    return result


def _ed25519_encode(point: tuple[int, int]) -> bytes:
    x, y = point
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _ed25519_decode(encoded: bytes) -> tuple[int, int]:
    if len(encoded) != 32:
        raise ValueError("Ed25519 public key/point must be 32 bytes")
    value = int.from_bytes(encoded, "little")
    y = value & ((1 << 255) - 1)
    if y >= _ED25519_Q:
        raise ValueError("non-canonical Ed25519 point")
    x = _ed25519_xrecover(y)
    if (x & 1) != (value >> 255):
        x = _ED25519_Q - x
    if (-x * x + y * y - 1 - _ED25519_D * x * x * y * y) % _ED25519_Q:
        raise ValueError("point is not on Ed25519 curve")
    return x, y


def ed25519_public_key(signing_seed: bytes) -> bytes:
    digest = hashlib.sha512(signing_seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return _ed25519_encode(_ed25519_scalarmult(_ED25519_B, scalar))


def ed25519_sign(signing_seed: bytes, message: bytes) -> bytes:
    digest = hashlib.sha512(signing_seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    public_key = _ed25519_encode(_ed25519_scalarmult(_ED25519_B, scalar))
    nonce = int.from_bytes(hashlib.sha512(digest[32:] + message).digest(), "little")
    nonce %= _ED25519_L
    encoded_nonce = _ed25519_encode(_ed25519_scalarmult(_ED25519_B, nonce))
    challenge = int.from_bytes(
        hashlib.sha512(encoded_nonce + public_key + message).digest(), "little"
    ) % _ED25519_L
    signature_scalar = (nonce + challenge * scalar) % _ED25519_L
    return encoded_nonce + signature_scalar.to_bytes(32, "little")


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    if len(signature) != 64:
        return False
    try:
        public_point = _ed25519_decode(public_key)
        nonce_point = _ed25519_decode(signature[:32])
    except ValueError:
        return False
    signature_scalar = int.from_bytes(signature[32:], "little")
    if signature_scalar >= _ED25519_L:
        return False
    challenge = int.from_bytes(
        hashlib.sha512(signature[:32] + public_key + message).digest(), "little"
    ) % _ED25519_L
    return _ed25519_encode(_ed25519_scalarmult(_ED25519_B, signature_scalar)) == _ed25519_encode(
        _ed25519_add(nonce_point, _ed25519_scalarmult(public_point, challenge))
    )


class _TestInvalidSignature(Exception):
    """Test double for cryptography.exceptions.InvalidSignature."""


class _TestEd25519PublicKey:
    """Exercise production verification semantics without an optional test wheel."""

    def __init__(self, public_key: bytes) -> None:
        self.public_key = public_key

    @classmethod
    def from_public_bytes(cls, public_key: bytes) -> "_TestEd25519PublicKey":
        if len(public_key) != 32:
            raise ValueError("Ed25519 public key must be 32 bytes")
        return cls(public_key)

    def verify(self, signature: bytes, message: bytes) -> None:
        if not ed25519_verify(self.public_key, message, signature):
            raise _TestInvalidSignature("invalid Ed25519 signature")


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FoloProtocolFixture(unittest.TestCase):
    """Real filesystem/SQLite fixtures for the public FOLO publication protocol."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="autoresearch-folo-protocol-")
        # macOS exposes /var as a system symlink to /private/var.  Anchor test
        # artifacts at the physical temp path so only symlinks created by an
        # adversarial case participate in path-chain assertions.
        self.root = Path(self.temp.name).resolve(strict=True)
        self.source_instance_id = "folo:test-instance"
        self.profile_id = "profile:test"
        self.pointer = self.root / "autoresearch/research-radar/manifest.json"
        self.database = self.make_database()
        # A SQLite fixture is already a deterministic database snapshot, so its
        # byte digest can bind both halves of the refresh attestation.
        self.source_snapshot_sha256 = sha256_file(self.database)
        self.database_snapshot_sha256 = sha256_file(self.database)
        self.snapshot_sha256 = self.source_snapshot_sha256
        self.signing_seed = hashlib.sha256(b"autoresearch-folo-ed25519-test-key").digest()
        self.public_key = self.root / "inputs/folo-refresh-ed25519-public.key"
        self.public_key.parent.mkdir(parents=True, exist_ok=True)
        self.public_key.write_bytes(ed25519_public_key(self.signing_seed))
        self.research_brief = self.write_authority_artifact(
            "research-brief.md", "# Frozen research brief\n\nEvaluate methods only.\n"
        )
        self.adaptation_plan = self.write_authority_artifact(
            "adaptation-plan.md", "# Adaptation plan\n\nProposals require review.\n"
        )
        self.experiment_contract = self.write_authority_artifact(
            "experiment-contract.json",
            json.dumps({"dataset": "test", "metric": "accuracy", "frozen": True}) + "\n",
        )
        self.crypto_patchers = (
            mock.patch.object(subject, "Ed25519PublicKey", _TestEd25519PublicKey),
            mock.patch.object(subject, "InvalidSignature", _TestInvalidSignature),
        )
        for patcher in self.crypto_patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.profile = self.write_profile()
        self.refresh_receipt = self.write_refresh_receipt()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_database(self, entries: list[dict] | None = None) -> Path:
        path = self.root / "source/follow.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            CREATE TABLE feeds (
                id TEXT PRIMARY KEY, title TEXT, url TEXT NOT NULL, site_url TEXT
            );
            CREATE TABLE subscriptions (feed_id TEXT, type TEXT NOT NULL, id TEXT PRIMARY KEY);
            CREATE TABLE entries (
                id TEXT PRIMARY KEY, feed_id TEXT, title TEXT, url TEXT, author TEXT,
                inserted_at INTEGER NOT NULL, published_at INTEGER NOT NULL,
                source_content TEXT, content TEXT, description TEXT
            );
            """
        )
        connection.executemany(
            "INSERT INTO feeds VALUES (?, ?, ?, ?)",
            [
                ("sub", "Subscribed", "https://sub.example/feed", "https://sub.example"),
                ("other", "Other", "https://other.example/feed", None),
            ],
        )
        connection.executemany(
            "INSERT INTO subscriptions VALUES (?, ?, ?)",
            [("sub", "feed", "feed/sub"), ("other", "feed", "feed/other")],
        )
        records = entries or [
            {"id": "authorized", "feed_id": "sub"},
            {"id": "unauthorized", "feed_id": "other"},
        ]
        for item in records:
            row = {
                "id": "entry",
                "feed_id": "sub",
                "title": "Research method result",
                "url": "https://example.test/paper",
                "author": "Author",
                "inserted_at": NOW_MS,
                "published_at": NOW_MS,
                "source_content": None,
                "content": "<p>Research evidence lead</p>",
                "description": "Research description",
                **item,
            }
            connection.execute(
                "INSERT INTO entries VALUES (:id, :feed_id, :title, :url, :author, "
                ":inserted_at, :published_at, :source_content, :content, :description)",
                row,
            )
        connection.commit()
        connection.close()
        return path

    def write_authority_artifact(self, name: str, content: str) -> Path:
        path = self.root / "inputs" / "authority" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def authority_envelope(self) -> dict:
        return {
            "research_brief": {
                "id": "brief:test",
                "path": str(self.research_brief.relative_to(self.root / "inputs")),
                "sha256": sha256_file(self.research_brief),
            },
            "repository": {
                "id": "repository:autoresearch-paper",
                "scope": "skills/autoresearch-radar",
            },
            "adaptation_plan": {
                "id": "plan:test",
                "path": str(self.adaptation_plan.relative_to(self.root / "inputs")),
                "sha256": sha256_file(self.adaptation_plan),
            },
            "experiment_contract": {
                "status": "frozen",
                "id": "contract:test",
                "path": str(self.experiment_contract.relative_to(self.root / "inputs")),
                "sha256": sha256_file(self.experiment_contract),
                "policy": {"mutation": "proposal-only"},
            },
            "contract_fit_rules": {
                "allowed": ["in-scope", "proposal-only"],
                "default": "out-of-scope",
            },
            "proposal_budget": 3,
            "out_of_scope_action": "backlog",
        }

    def write_profile(self, **updates) -> Path:
        path = self.root / "inputs/research-watch-profile.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        profile = {
            "schema_version": 1,
            "profile_id": self.profile_id,
            "source": "folo-local",
            "source_instance_id": self.source_instance_id,
            "source_scope": {
                "authorized_feed_ids": ["sub"],
                "query_terms": ["research"],
                "excluded_terms": ["withdrawn"],
            },
            "scan": {"hours": 72, "limit": 100},
            "policy": {
                "minimum_evidence_level": "primary-opened",
                "allowed_signal_types": ["method-opportunity"],
                "refresh_max_age_minutes": 180,
            },
            "refresh_trust": {
                "producer_identity": "harness:folo-ui-controller:v1",
                "ed25519_public_key_path": self.public_key.name,
                "ed25519_public_key_sha256": sha256_file(self.public_key),
            },
            "authority": self.authority_envelope(),
        }
        profile.update(updates)
        path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def write_refresh_receipt(
        self,
        *,
        source_snapshot_sha256: str | None = None,
        database_snapshot_sha256: str | None = None,
        signing_seed: bytes | None = None,
        producer_identity: str = "harness:folo-ui-controller:v1",
        **updates,
    ) -> Path:
        path = self.root / "inputs/folo-refresh-receipt.json"
        payload = {
            "schema_version": 1,
            "source": "folo-local",
            "source_instance_id": self.source_instance_id,
            "profile_id": self.profile_id,
            "profile_sha256": sha256_file(self.profile),
            "producer_identity": producer_identity,
            "status": "synced",
            "timeline": "all",
            "pagination_complete": True,
            "cache_stable": True,
            "refreshed_at": NOW.isoformat().replace("+00:00", "Z"),
            "attestation": {
                "kind": "folo-official-ui-refresh",
                "source_snapshot_sha256": (
                    source_snapshot_sha256 or self.source_snapshot_sha256
                ),
                "database_snapshot_sha256": (
                    database_snapshot_sha256 or self.database_snapshot_sha256
                ),
                "verified": True,
            },
        }
        payload.update(updates)
        payload["signature_ed25519"] = ed25519_sign(
            signing_seed if signing_seed is not None else self.signing_seed,
            canonical_bytes(payload),
        ).hex()
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def sign_receipt_payload(
        self, payload: dict, *, signing_seed: bytes | None = None
    ) -> dict:
        signed = copy.deepcopy(payload)
        signed.pop("signature_ed25519", None)
        signed["signature_ed25519"] = ed25519_sign(
            signing_seed if signing_seed is not None else self.signing_seed,
            canonical_bytes(signed),
        ).hex()
        return signed

    def write_jsonl(self, path: Path, records: list[dict]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
            encoding="utf-8",
        )
        return path

    def extract(self, *, state_path: Path | None = None, now_ms: int = NOW_MS) -> list[dict]:
        return subject.extract_candidates(
            self.database,
            state_path=state_path or self.root / "missing-initial-state.json",
            source_instance_id=self.source_instance_id,
            hours=72,
            limit=100,
            now_ms=now_ms,
            profile_path=self.profile,
        )

    def make_extraction(
        self,
        name: str,
        *,
        candidates: list[dict] | None = None,
        input_state_path: Path | None = None,
        extracted_at: dt.datetime = NOW,
        source_path: Path | None = None,
    ) -> tuple[Path, Path, list[dict]]:
        records = candidates if candidates is not None else self.extract(state_path=input_state_path)
        directory = self.root / "extractions" / name
        candidates_path = self.write_jsonl(directory / "candidates.jsonl", records)
        manifest_path = directory / "extraction-manifest.json"
        subject.create_extraction_manifest(
            database_path=self.database,
            candidates_path=candidates_path,
            extraction_manifest_path=manifest_path,
            profile_path=self.profile,
            profile_id=self.profile_id,
            refresh_receipt_path=self.refresh_receipt,
            source_instance_id=self.source_instance_id,
            source_snapshot_sha256=self.snapshot_sha256,
            input_state_path=input_state_path,
            stable_pointer_path=self.pointer,
            extracted_at=extracted_at,
            extraction_bounds={"hours": 72, "limit": 100},
            source_path=source_path or self.database,
            artifact_root=self.root,
        )
        return manifest_path, candidates_path, records

    def decision(self, candidate: dict, decision: str = "ignored", **updates) -> dict:
        payload = {
            "id": candidate["id"],
            "candidate_sha256": candidate["candidate_sha256"],
            "profile_id": self.profile_id,
            "profile_sha256": sha256_file(self.profile),
            "decision": decision,
            "reason": "reviewed against the frozen watch profile",
            "uncertainty": "source result has not been reproduced",
            "relevance": "high",
            "evidence_level": "primary-opened",
            "contract_fit": "in-scope",
            "signal_type": "method-opportunity",
            "source_claim": "The primary source reports a research method result.",
            "applicable_scope": "The evaluated task, dataset, metric, and stated caveats.",
            "verification_status": "primary-verified",
            "receipts": [],
        }
        payload.update(updates)
        return payload

    def publish(
        self,
        name: str,
        *,
        manifest_path: Path | None = None,
        candidates: list[dict] | None = None,
        decisions: list[dict] | None = None,
        input_state_path: Path | None = None,
        expected_commit_root_sha256: str | None = None,
        leveldb_path: Path | None = None,
        now: dt.datetime = NOW,
    ) -> dict:
        if manifest_path is None:
            manifest_path, _candidate_path, extracted = self.make_extraction(
                name, candidates=candidates, input_state_path=input_state_path, extracted_at=now
            )
        else:
            extracted = candidates or []
        if decisions is None:
            decisions = [self.decision(candidate) for candidate in extracted]
        decisions_path = self.write_jsonl(
            self.root / "extractions" / name / "decisions.jsonl", decisions
        )
        return subject.publish_run(
            manifest_path,
            decisions_path,
            artifact_root=self.root,
            stable_pointer_path=self.pointer,
            leveldb_path=leveldb_path,
            expected_commit_root_sha256=expected_commit_root_sha256,
            now=now,
        )

    def resolve(self, descriptor_path: str) -> Path:
        return (self.root / descriptor_path).resolve()

    def rewrite_committed_run_manifest(
        self, manifest_path: Path, manifest: dict
    ) -> None:
        manifest_bytes = (
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        manifest_path.write_bytes(manifest_bytes)
        pointer = json.loads(self.pointer.read_text(encoding="utf-8"))
        pointer["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        self.pointer.write_text(
            json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def rewrite_committed_decision_bundle(
        self,
        result: dict,
        *,
        mutate_decision=None,
        recompute_decision_sha256: bool = False,
        mirror_decision_into_state: bool = True,
        mutate_state=None,
    ) -> tuple[dict, dict, dict]:
        """Simulate an attacker who can rewrite every non-trusted outer hash."""
        manifest_path = Path(result["run_manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        decisions_path = self.resolve(manifest["decisions_path"])
        decisions = [
            json.loads(line)
            for line in decisions_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(decisions), 1)
        decision = decisions[0]
        if mutate_decision is not None:
            mutate_decision(decision)
        if recompute_decision_sha256:
            decision.pop("decision_sha256", None)
            decision["decision_sha256"] = hashlib.sha256(
                canonical_bytes(decision)
            ).hexdigest()
        decision_bytes = (
            json.dumps(decision, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
        decisions_path.write_bytes(decision_bytes)
        manifest["decisions_sha256"] = hashlib.sha256(decision_bytes).hexdigest()

        state_path = self.resolve(manifest["state_path"])
        state = json.loads(state_path.read_text(encoding="utf-8"))
        identifier = decision["id"]
        bucket = state["pending"] if identifier in state["pending"] else state["processed"]
        self.assertIn(identifier, bucket)
        state_record = bucket[identifier]
        if mirror_decision_into_state:
            state_record.update(copy.deepcopy(decision))
        if mutate_state is not None:
            mutate_state(state_record)
        state_bytes = (
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        state_path.write_bytes(state_bytes)
        manifest["state_sha256"] = hashlib.sha256(state_bytes).hexdigest()

        manifest_bytes = (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        manifest_path.write_bytes(manifest_bytes)
        pointer = json.loads(self.pointer.read_text(encoding="utf-8"))
        pointer["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        pointer["state_sha256"] = manifest["state_sha256"]
        self.pointer.write_text(
            json.dumps(pointer, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return decision, state_record, manifest


class IndexedDbHistorySelectionTests(unittest.TestCase):
    @staticmethod
    def operation(
        raw_key: bytes,
        sequence: int,
        *,
        live: bool,
        offset: int = 0,
        data: bytes = b"block",
    ) -> SimpleNamespace:
        return SimpleNamespace(
            key=SimpleNamespace(raw_key=raw_key),
            ldb_seq_no=sequence,
            is_live=live,
            value={"path": subject.DATABASE_PATH, "offset": offset, "data": data},
        )

    def test_newer_tombstone_for_raw_key_suppresses_older_live_block(self) -> None:
        old_live = self.operation(b"same-key", 10, live=True, offset=0, data=b"old")
        tombstone = self.operation(b"same-key", 11, live=False)
        survivor = self.operation(b"other-key", 4, live=True, offset=64, data=b"kept")

        selected = subject._select_live_blocks([old_live, tombstone, survivor])

        self.assertEqual(selected, {64: (4, b"kept")})

    def test_newer_live_operation_for_raw_key_replaces_older_live_block(self) -> None:
        old_live = self.operation(b"same-key", 10, live=True, offset=0, data=b"old")
        new_live = self.operation(b"same-key", 11, live=True, offset=0, data=b"new")

        selected = subject._select_live_blocks([old_live, new_live])

        self.assertEqual(selected, {0: (11, b"new")})

    def test_conflicting_operations_with_same_key_and_sequence_fail_closed(self) -> None:
        live = self.operation(b"same-key", 10, live=True, offset=0, data=b"old")
        tombstone = self.operation(b"same-key", 10, live=False)

        for records in ([live, tombstone], [tombstone, live]):
            with self.subTest(order=[record.is_live for record in records]):
                with self.assertRaisesRegex(subject.FoloSourceError, "conflicting"):
                    subject._select_live_blocks(records)


class ProfileAndExtractionProvenanceTests(FoloProtocolFixture):
    def test_ed25519_fixture_matches_rfc8032_vector_one(self) -> None:
        seed = bytes.fromhex(
            "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
        )
        public_key = bytes.fromhex(
            "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
        )
        signature = bytes.fromhex(
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
            "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        )
        self.assertEqual(ed25519_public_key(seed), public_key)
        self.assertEqual(ed25519_sign(seed, b""), signature)
        self.assertTrue(ed25519_verify(public_key, b"", signature))

    def test_explicit_sqlite_reports_both_snapshot_digests(self) -> None:
        with subject._database_context(str(self.database), None) as (database, details):
            expected = sha256_file(self.database)
            self.assertEqual(database, self.database.resolve())
            self.assertEqual(details["source_snapshot_sha256"], expected)
            self.assertEqual(details["database_snapshot_sha256"], expected)

    def test_doctor_reports_distinct_source_and_database_snapshot_digests(self) -> None:
        fake_leveldb = self.root / "fake-leveldb"
        fake_leveldb.mkdir()
        (fake_leveldb / "CURRENT").write_text("MANIFEST-000001\n", encoding="utf-8")
        details = {
            "quick_check": "ok",
            "tables": {"entries": 2, "feeds": 2, "subscriptions": 2},
            "sqlite_bytes": self.database.stat().st_size,
            "live_blocks": 3,
            "snapshot_files": 4,
            "source_snapshot_sha256": "1" * 64,
            "database_snapshot_sha256": "2" * 64,
        }

        @contextlib.contextmanager
        def fake_reconstruction(source: Path):
            self.assertEqual(source, fake_leveldb.resolve())
            yield self.database, details

        output = io.StringIO()
        args = argparse.Namespace(
            leveldb=str(fake_leveldb), source_instance_id=self.source_instance_id, json=True
        )
        with mock.patch.object(
            subject, "reconstructed_database", side_effect=fake_reconstruction
        ), redirect_stdout(output):
            self.assertEqual(subject._doctor(args), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["source_snapshot_sha256"], "1" * 64)
        self.assertEqual(report["database_snapshot_sha256"], "2" * 64)

    def test_profile_scope_filters_unauthorized_subscriptions_and_query_misses(self) -> None:
        records = self.extract()
        self.assertEqual([record["id"] for record in records], ["folo:authorized"])
        self.assertEqual(records[0]["feed_id"], "sub")

    def test_extraction_manifest_binds_every_input_and_actual_snapshot(self) -> None:
        manifest_path, candidates_path, records = self.make_extraction("bound")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["profile"], {
            "id": self.profile_id,
            "path": str(self.profile.relative_to(self.root)),
            "sha256": sha256_file(self.profile),
        })
        self.assertEqual(payload["refresh_receipt"], {
            "path": str(self.refresh_receipt.relative_to(self.root)),
            "sha256": sha256_file(self.refresh_receipt),
        })
        self.assertEqual(payload["source_snapshot_sha256"], sha256_file(self.database))
        database_snapshot = payload["database_snapshot"]
        snapshot_path = self.resolve(database_snapshot["path"])
        self.assertEqual(database_snapshot["sha256"], self.database_snapshot_sha256)
        self.assertEqual(sha256_file(snapshot_path), self.database_snapshot_sha256)
        self.assertNotEqual(snapshot_path, self.database)
        self.assertEqual(payload["candidates"], {
            "path": str(candidates_path.relative_to(self.root)),
            "sha256": sha256_file(candidates_path),
            "count": len(records),
        })
        expected_initial_state = {
            "schema_version": 1,
            "source": "folo-local",
            "source_instance_id": self.source_instance_id,
            "processed": {},
            "pending": {},
        }
        expected_state_bytes = (
            json.dumps(expected_initial_state, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        self.assertEqual(payload["input_state"], {
            "path": None,
            "sha256": hashlib.sha256(expected_state_bytes).hexdigest(),
        })
        self.assertEqual(payload["input_commit_root_sha256"], EMPTY_SHA256)

    def test_refresh_receipt_is_authenticated_and_snapshot_bound(self) -> None:
        candidates = self.extract()
        candidates_path = self.write_jsonl(
            self.root / "extractions/auth/candidates.jsonl", candidates
        )
        manifest_path = self.root / "extractions/auth/extraction-manifest.json"
        original = self.refresh_receipt.read_bytes()
        cases = []

        forged = json.loads(original)
        forged["signature_ed25519"] = "0" * 128
        cases.append(("forged-signature", forged))
        wrong_key = self.sign_receipt_payload(
            json.loads(original),
            signing_seed=hashlib.sha256(b"wrong-ed25519-key").digest(),
        )
        cases.append(("wrong-key", wrong_key))
        tampered = json.loads(original)
        tampered["attestation"]["verified"] = False
        cases.append(("tampered-attestation", tampered))
        source_mismatch = json.loads(original)
        source_mismatch["attestation"]["source_snapshot_sha256"] = "0" * 64
        cases.append((
            "source-snapshot-mismatch", self.sign_receipt_payload(source_mismatch)
        ))
        database_mismatch = json.loads(original)
        database_mismatch["attestation"]["database_snapshot_sha256"] = "0" * 64
        cases.append((
            "database-snapshot-mismatch", self.sign_receipt_payload(database_mismatch)
        ))

        for label, receipt in cases:
            with self.subTest(label=label):
                self.refresh_receipt.write_text(json.dumps(receipt), encoding="utf-8")
                with self.assertRaises(subject.FoloSourceError):
                    subject.create_extraction_manifest(
                        database_path=self.database,
                        candidates_path=candidates_path,
                        extraction_manifest_path=manifest_path,
                        profile_path=self.profile,
                        profile_id=self.profile_id,
                        refresh_receipt_path=self.refresh_receipt,
                        source_instance_id=self.source_instance_id,
                        source_snapshot_sha256=self.snapshot_sha256,
                        input_state_path=None,
                        stable_pointer_path=self.pointer,
                        extracted_at=NOW,
                        source_path=self.database,
                        artifact_root=self.root,
                    )
                self.assertFalse(manifest_path.exists())
                self.refresh_receipt.write_bytes(original)

    def test_refresh_receipt_keeps_source_and_database_digests_distinct(self) -> None:
        source_digest = "1" * 64
        database_digest = "2" * 64
        self.refresh_receipt = self.write_refresh_receipt(
            source_snapshot_sha256=source_digest,
            database_snapshot_sha256=database_digest,
        )
        profile = subject.load_watch_profile(self.profile)
        receipt = subject.validate_refresh_receipt(
            self.refresh_receipt,
            source_instance_id=self.source_instance_id,
            source_snapshot_sha256=source_digest,
            database_snapshot_sha256=database_digest,
            now=NOW,
            max_age_minutes=180,
            profile=profile,
        )
        self.assertEqual(
            receipt["attestation"]["source_snapshot_sha256"], source_digest
        )
        self.assertEqual(
            receipt["attestation"]["database_snapshot_sha256"], database_digest
        )
        with self.assertRaises(subject.FoloSourceError):
            subject.validate_refresh_receipt(
                self.refresh_receipt,
                source_instance_id=self.source_instance_id,
                source_snapshot_sha256=database_digest,
                database_snapshot_sha256=source_digest,
                now=NOW,
                max_age_minutes=180,
                profile=profile,
            )

    def test_profile_contains_complete_fail_closed_authority_envelope(self) -> None:
        base = self.authority_envelope()

        def without(field: str) -> dict:
            authority = copy.deepcopy(base)
            authority.pop(field)
            return authority

        cases: dict[str, dict] = {
            "missing-research-brief": without("research_brief"),
            "tampered-research-brief": copy.deepcopy(base),
            "missing-repository": without("repository"),
            "tampered-repository": copy.deepcopy(base),
            "missing-adaptation-plan": without("adaptation_plan"),
            "tampered-adaptation-plan": copy.deepcopy(base),
            "missing-experiment-contract": without("experiment_contract"),
            "tampered-experiment-contract": copy.deepcopy(base),
            "missing-contract-fit-rules": without("contract_fit_rules"),
            "empty-contract-fit-rules": copy.deepcopy(base),
            "missing-proposal-budget": without("proposal_budget"),
            "invalid-proposal-budget": copy.deepcopy(base),
            "missing-out-of-scope-action": without("out_of_scope_action"),
            "invalid-out-of-scope-action": copy.deepcopy(base),
        }
        cases["tampered-research-brief"]["research_brief"]["sha256"] = "0" * 64
        cases["tampered-repository"]["repository"]["scope"] = ""
        cases["tampered-adaptation-plan"]["adaptation_plan"]["sha256"] = "0" * 64
        cases["tampered-experiment-contract"]["experiment_contract"]["sha256"] = "0" * 64
        cases["empty-contract-fit-rules"]["contract_fit_rules"] = {}
        cases["invalid-proposal-budget"]["proposal_budget"] = 0
        cases["invalid-out-of-scope-action"]["out_of_scope_action"] = "forward"

        original_profile = self.profile.read_bytes()
        for label, authority in cases.items():
            with self.subTest(label=label):
                self.write_profile(authority=authority)
                with self.assertRaises(subject.FoloSourceError):
                    subject.load_watch_profile(self.profile)
                self.profile.write_bytes(original_profile)

    def test_authority_artifacts_cannot_change_behind_frozen_hashes(self) -> None:
        for artifact in (
            self.research_brief,
            self.adaptation_plan,
            self.experiment_contract,
        ):
            with self.subTest(artifact=artifact.name):
                original = artifact.read_bytes()
                artifact.write_bytes(original + b"tampered\n")
                with self.assertRaises(subject.FoloSourceError):
                    subject.load_watch_profile(self.profile)
                artifact.write_bytes(original)

    def test_pre_contract_profile_vendors_only_brief_and_plan_authority(self) -> None:
        authority = self.authority_envelope()
        authority["experiment_contract"] = {
            "status": "pre-contract",
            "id": "contract:pending",
            "policy": {"mutation": "proposal-only"},
        }
        self.profile = self.write_profile(authority=authority)
        self.refresh_receipt = self.write_refresh_receipt()

        result = self.publish(
            "pre-contract", expected_commit_root_sha256=EMPTY_SHA256
        )
        run_manifest = json.loads(
            Path(result["run_manifest_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            {descriptor["role"] for descriptor in run_manifest["authority_artifacts"]},
            {"research-brief", "adaptation-plan"},
        )
        pointer_bytes, pointer, _state, _state_bytes, _state_path = subject._read_pointer(
            self.pointer, self.root, self.source_instance_id
        )
        self.assertEqual(pointer["run_id"], result["run_id"])
        self.assertEqual(
            hashlib.sha256(pointer_bytes).hexdigest(), result["stable_pointer_sha256"]
        )

    def test_pre_contract_authority_forbids_artifact_fields(self) -> None:
        base = self.authority_envelope()
        cases = {
            "path": "authority/experiment-contract.json",
            "sha256": "0" * 64,
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                authority = copy.deepcopy(base)
                authority["experiment_contract"] = {
                    "status": "pre-contract",
                    "id": "contract:pending",
                    "policy": {"mutation": "proposal-only"},
                    field: value,
                }
                self.write_profile(authority=authority)
                with self.assertRaisesRegex(
                    subject.FoloSourceError, "pre-contract|experiment_contract"
                ):
                    subject.load_watch_profile(self.profile)

    def test_trust_inputs_reject_ancestor_symlinks(self) -> None:
        authority_directory = self.root / "inputs/authority"
        real_authority_directory = self.root / "inputs/authority-real"
        authority_directory.rename(real_authority_directory)
        authority_directory.symlink_to(real_authority_directory, target_is_directory=True)
        with self.assertRaisesRegex(subject.FoloSourceError, "symlink|safe|contained"):
            subject.load_watch_profile(self.profile)

    def test_public_key_rejects_an_ancestor_symlink(self) -> None:
        real_directory = self.root / "inputs/trust-real"
        real_directory.mkdir()
        real_key = real_directory / "refresh-public.key"
        real_key.write_bytes(self.public_key.read_bytes())
        linked_directory = self.root / "inputs/trust"
        linked_directory.symlink_to(real_directory, target_is_directory=True)
        self.profile = self.write_profile(refresh_trust={
            "producer_identity": "harness:folo-ui-controller:v1",
            "ed25519_public_key_path": "trust/refresh-public.key",
            "ed25519_public_key_sha256": sha256_file(real_key),
        })
        with self.assertRaisesRegex(subject.FoloSourceError, "symlink|safe|contained"):
            subject.load_watch_profile(self.profile)

    def test_frozen_trust_inputs_must_be_single_link_files(self) -> None:
        public_key_alias = self.root / "inputs/public-key-alias"
        os.link(self.public_key, public_key_alias)
        with self.assertRaisesRegex(subject.FoloSourceError, "link|regular"):
            subject.load_watch_profile(self.profile)

    def test_authority_artifacts_must_be_single_link_files(self) -> None:
        brief_alias = self.root / "inputs/research-brief-alias.md"
        os.link(self.research_brief, brief_alias)
        with self.assertRaisesRegex(subject.FoloSourceError, "link|regular"):
            subject.load_watch_profile(self.profile)

    def test_manifest_cannot_wrap_a_handwritten_candidate_ledger(self) -> None:
        authentic = self.extract()[0]
        cases: dict[str, dict] = {}
        query_miss = copy.deepcopy(authentic)
        query_miss.update({
            "title": "Unrelated item",
            "body": "No matching topic",
            "url": "https://example.test/unrelated",
        })
        query_miss["candidate_sha256"] = subject.candidate_digest(query_miss)
        cases["query-miss"] = query_miss

        future = copy.deepcopy(authentic)
        future_time = NOW + dt.timedelta(seconds=1)
        future["effective_at"] = future_time.isoformat().replace("+00:00", "Z")
        future["effective_at_ms"] = int(future_time.timestamp() * 1000)
        future["candidate_sha256"] = subject.candidate_digest(future)
        cases["future"] = future

        old = copy.deepcopy(authentic)
        old_time = NOW - dt.timedelta(hours=73)
        old["effective_at"] = old_time.isoformat().replace("+00:00", "Z")
        old["effective_at_ms"] = int(old_time.timestamp() * 1000)
        old["candidate_sha256"] = subject.candidate_digest(old)
        cases["outside-window"] = old

        forged = copy.deepcopy(authentic)
        forged["title"] = "Research forged but otherwise in scope"
        forged["candidate_sha256"] = subject.candidate_digest(forged)
        cases["not-in-database-extraction"] = forged

        for label, candidate in cases.items():
            with self.subTest(label=label):
                directory = self.root / "extractions" / f"handwritten-{label}"
                candidates_path = self.write_jsonl(directory / "candidates.jsonl", [candidate])
                manifest_path = directory / "extraction-manifest.json"
                with self.assertRaises(subject.FoloSourceError):
                    subject.create_extraction_manifest(
                        database_path=self.database,
                        candidates_path=candidates_path,
                        extraction_manifest_path=manifest_path,
                        profile_path=self.profile,
                        profile_id=self.profile_id,
                        refresh_receipt_path=self.refresh_receipt,
                        source_instance_id=self.source_instance_id,
                        source_snapshot_sha256=self.snapshot_sha256,
                        input_state_path=None,
                        stable_pointer_path=self.pointer,
                        extracted_at=NOW,
                        extraction_bounds={"hours": 72, "limit": 100},
                        source_path=self.database,
                        artifact_root=self.root,
                    )
                self.assertFalse(manifest_path.exists())

    def test_publish_reextracts_vendored_database_and_rejects_ghost_candidate(self) -> None:
        manifest_path, candidates_path, candidates = self.make_extraction(
            "publish-ghost"
        )
        ghost = copy.deepcopy(candidates[0])
        ghost.update({
            "id": "folo:ghost",
            "entry_id": "ghost",
            "title": "Research ghost method",
            "url": "https://example.test/ghost",
        })
        ghost["candidate_sha256"] = subject.candidate_digest(ghost)
        forged_candidates = [*candidates, ghost]
        self.write_jsonl(candidates_path, forged_candidates)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["candidates"].update({
            "sha256": sha256_file(candidates_path),
            "count": len(forged_candidates),
        })
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        decisions_path = self.write_jsonl(
            self.root / "extractions/publish-ghost/decisions.jsonl",
            [self.decision(candidate) for candidate in forged_candidates],
        )

        with self.assertRaisesRegex(
            subject.FoloSourceError, "deterministic|re-extract|candidate ledger"
        ):
            subject.publish_run(
                manifest_path,
                decisions_path,
                artifact_root=self.root,
                stable_pointer_path=self.pointer,
                expected_commit_root_sha256=EMPTY_SHA256,
                now=NOW,
            )
        self.assertFalse(self.pointer.exists())

    def test_live_database_mutation_after_extraction_does_not_change_publication(self) -> None:
        manifest_path, _candidates_path, candidates = self.make_extraction(
            "database-mutated-after-extraction"
        )
        extraction = json.loads(manifest_path.read_text(encoding="utf-8"))
        snapshot_descriptor = extraction["database_snapshot"]
        snapshot_path = self.resolve(snapshot_descriptor["path"])
        original_snapshot = snapshot_path.read_bytes()
        connection = sqlite3.connect(self.database)
        connection.execute(
            "INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "late-live-row", "sub", "Research late live row",
                "https://example.test/late-live-row", "Author", NOW_MS, NOW_MS,
                None, "Research evidence lead", "Research description",
            ),
        )
        connection.commit()
        connection.close()
        self.assertNotEqual(sha256_file(self.database), snapshot_descriptor["sha256"])

        result = self.publish(
            "database-mutated-after-extraction",
            manifest_path=manifest_path,
            candidates=candidates,
            decisions=[self.decision(candidate) for candidate in candidates],
            expected_commit_root_sha256=EMPTY_SHA256,
        )
        run_manifest = json.loads(Path(result["run_manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(run_manifest["database_snapshot"], snapshot_descriptor)
        self.assertEqual(snapshot_path.read_bytes(), original_snapshot)
        with sqlite3.connect(snapshot_path) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            ids = {row[0] for row in connection.execute("SELECT id FROM entries")}
        self.assertNotIn("late-live-row", ids)

    def test_live_database_deletion_after_extraction_remains_publish_auditable(self) -> None:
        manifest_path, _candidates_path, candidates = self.make_extraction(
            "database-deleted-after-extraction"
        )
        extraction = json.loads(manifest_path.read_text(encoding="utf-8"))
        snapshot_descriptor = extraction["database_snapshot"]
        snapshot_path = self.resolve(snapshot_descriptor["path"])
        self.database.unlink()

        result = self.publish(
            "database-deleted-after-extraction",
            manifest_path=manifest_path,
            candidates=candidates,
            decisions=[self.decision(candidate) for candidate in candidates],
            expected_commit_root_sha256=EMPTY_SHA256,
        )
        pointer = json.loads(self.pointer.read_text(encoding="utf-8"))
        run_manifest_path = self.resolve(pointer["manifest_path"])
        self.assertEqual(sha256_file(run_manifest_path), pointer["manifest_sha256"])
        run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(run_manifest["database_snapshot"], snapshot_descriptor)
        self.assertEqual(sha256_file(snapshot_path), snapshot_descriptor["sha256"])
        self.assertEqual(result["run_id"], pointer["run_id"])

    def test_only_manifest_bound_publish_api_can_advance_durable_state(self) -> None:
        self.assertFalse(
            hasattr(subject, "record_decisions"),
            "there must be no bare durable writer that bypasses extraction provenance",
        )
        parser = subject.build_parser()
        with self.assertRaisesRegex(subject.FoloSourceError, "extraction-manifest"):
            parser.parse_args([
                "record", "--candidates", "candidates.jsonl", "--decisions",
                "decisions.jsonl", "--artifact-root", str(self.root),
            ])
        parsed = parser.parse_args([
            "record", "--extraction-manifest", "extraction.json", "--decisions",
            "decisions.jsonl", "--artifact-root", str(self.root),
        ])
        self.assertEqual(parsed.extraction_manifest, "extraction.json")


class PublicationContractTests(FoloProtocolFixture):
    def test_tampered_provenance_is_rejected_without_advancing_commit_root(self) -> None:
        manifest_path, candidates_path, candidates = self.make_extraction("tamper")
        decisions_path = self.write_jsonl(
            self.root / "extractions/tamper/decisions.jsonl",
            [self.decision(candidate) for candidate in candidates],
        )
        original_manifest = manifest_path.read_bytes()
        original_candidates = candidates_path.read_bytes()
        cases = [
            ("manifest-profile-hash", manifest_path, lambda data: data.replace(
                sha256_file(self.profile).encode(), ("0" * 64).encode(), 1
            )),
            ("candidate-ledger", candidates_path, lambda data: data + b"{}\n"),
            ("profile-artifact", self.profile, lambda data: data + b" \n"),
            ("refresh-artifact", self.refresh_receipt, lambda data: data + b" \n"),
        ]
        originals = {
            manifest_path: original_manifest,
            candidates_path: original_candidates,
            self.profile: self.profile.read_bytes(),
            self.refresh_receipt: self.refresh_receipt.read_bytes(),
        }
        for label, path, mutate in cases:
            with self.subTest(label=label):
                path.write_bytes(mutate(originals[path]))
                with self.assertRaises(subject.FoloSourceError):
                    subject.publish_run(
                        manifest_path,
                        decisions_path,
                        artifact_root=self.root,
                        stable_pointer_path=self.pointer,
                        expected_commit_root_sha256=EMPTY_SHA256,
                        now=NOW,
                    )
                self.assertFalse(self.pointer.exists())
                path.write_bytes(originals[path])

    def test_publication_persists_strict_decision_fields_in_immutable_run(self) -> None:
        result = self.publish("strict", expected_commit_root_sha256=EMPTY_SHA256)
        pointer = json.loads(self.pointer.read_text(encoding="utf-8"))
        self.assertEqual(sha256_file(self.pointer), result["stable_pointer_sha256"])
        manifest_path = self.resolve(pointer["manifest_path"])
        self.assertEqual(sha256_file(manifest_path), pointer["manifest_sha256"])
        run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        decisions_path = self.resolve(run_manifest["decisions_path"])
        self.assertEqual(sha256_file(decisions_path), run_manifest["decisions_sha256"])
        recorded = json.loads(decisions_path.read_text(encoding="utf-8").splitlines()[0])
        expected_fields = {
            "decision", "relevance", "evidence_level", "contract_fit", "signal_type",
            "source_claim", "applicable_scope", "verification_status", "uncertainty",
        }
        self.assertTrue(expected_fields.issubset(recorded))
        self.assertNotIn("disposition", recorded)
        self.assertEqual(recorded["decision"], "ignored")
        state_path = self.resolve(pointer["state_path"])
        self.assertEqual(sha256_file(state_path), pointer["state_sha256"])
        state = json.loads(state_path.read_text(encoding="utf-8"))
        persisted = state["processed"]["folo:authorized"]
        for field in expected_fields:
            self.assertEqual(persisted[field], recorded[field])

    def test_legacy_or_incomplete_decision_schema_is_rejected(self) -> None:
        manifest, _path, candidates = self.make_extraction("decision-schema")
        valid = self.decision(candidates[0])
        broken_cases = {}
        legacy = dict(valid)
        legacy["disposition"] = legacy.pop("decision")
        broken_cases["legacy-disposition"] = legacy
        for field in (
            "relevance", "evidence_level", "contract_fit", "signal_type",
            "source_claim", "applicable_scope", "verification_status", "uncertainty",
        ):
            missing = dict(valid)
            missing.pop(field)
            broken_cases[f"missing-{field}"] = missing
        for label, decision in broken_cases.items():
            with self.subTest(label=label):
                decisions_path = self.write_jsonl(
                    self.root / f"extractions/decision-schema/{label}.jsonl", [decision]
                )
                with self.assertRaises(subject.FoloSourceError):
                    subject.publish_run(
                        manifest,
                        decisions_path,
                        artifact_root=self.root,
                        stable_pointer_path=self.pointer,
                        expected_commit_root_sha256=EMPTY_SHA256,
                        now=NOW,
                    )
                self.assertFalse(self.pointer.exists())

        invalid_relevance = dict(valid, relevance="prestigious")
        decisions_path = self.write_jsonl(
            self.root / "extractions/decision-schema/invalid-relevance.jsonl",
            [invalid_relevance],
        )
        with self.assertRaises(subject.FoloSourceError):
            subject.publish_run(
                manifest,
                decisions_path,
                artifact_root=self.root,
                stable_pointer_path=self.pointer,
                expected_commit_root_sha256=EMPTY_SHA256,
                now=NOW,
            )
        self.assertFalse(self.pointer.exists())


class ForwardedSignalReceiptTests(FoloProtocolFixture):
    def forwarded_artifacts(self, candidate: dict, *, candidate_id: str | None = None,
                            candidate_sha256: str | None = None) -> list[dict]:
        directory = self.root / "evidence" / candidate["entry_id"]
        directory.mkdir(parents=True, exist_ok=True)
        primary = directory / "primary-source.json"
        primary.write_text(
            json.dumps({"doi": "10.0000/example", "title": "Primary paper"}) + "\n",
            encoding="utf-8",
        )
        signal = directory / "research-signal.json"
        signal.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "type": "research-signal",
                    "candidate_id": candidate_id or candidate["id"],
                    "candidate_sha256": candidate_sha256 or candidate["candidate_sha256"],
                    "profile_id": self.profile_id,
                    "profile_sha256": sha256_file(self.profile),
                    "relevance": "high",
                    "evidence_level": "primary-opened",
                    "contract_fit": "in-scope",
                    "signal_type": "method-opportunity",
                    "source_claim": "The primary source reports a research method result.",
                    "applicable_scope": "The evaluated task, dataset, metric, and stated caveats.",
                    "verification_status": "primary-verified",
                    "uncertainty": "source result has not been reproduced",
                    "primary_sources": [{
                        "path": str(primary.relative_to(self.root)),
                        "sha256": sha256_file(primary),
                    }],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return [
            {
                "role": "profile",
                "path": str(self.profile.relative_to(self.root)),
                "sha256": sha256_file(self.profile),
            },
            {
                "role": "evidence",
                "path": str(signal.relative_to(self.root)),
                "sha256": sha256_file(signal),
            },
            {
                "role": "primary-source",
                "path": str(primary.relative_to(self.root)),
                "sha256": sha256_file(primary),
            },
        ]

    def test_forwarded_signal_requires_id_digest_profile_evidence_and_primary_source(self) -> None:
        manifest, _path, candidates = self.make_extraction("forwarded-bindings")
        candidate = candidates[0]
        valid_receipts = self.forwarded_artifacts(candidate)
        cases = {
            "wrong-candidate-id": self.forwarded_artifacts(candidate, candidate_id="folo:other"),
            "wrong-candidate-digest": self.forwarded_artifacts(candidate, candidate_sha256="0" * 64),
            "missing-profile": [r for r in valid_receipts if r["role"] != "profile"],
            "missing-evidence": [r for r in valid_receipts if r["role"] != "evidence"],
            "missing-primary-source": [r for r in valid_receipts if r["role"] != "primary-source"],
        }
        for label, receipts in cases.items():
            with self.subTest(label=label):
                decisions_path = self.write_jsonl(
                    self.root / f"extractions/forwarded-bindings/{label}.jsonl",
                    [self.decision(candidate, decision="forwarded", receipts=receipts)],
                )
                with self.assertRaises(subject.FoloSourceError):
                    subject.publish_run(
                        manifest,
                        decisions_path,
                        artifact_root=self.root,
                        stable_pointer_path=self.pointer,
                        expected_commit_root_sha256=EMPTY_SHA256,
                        now=NOW,
                    )
                self.assertFalse(self.pointer.exists())

    def test_valid_forwarded_signal_publishes_bound_receipts(self) -> None:
        manifest, _path, candidates = self.make_extraction("forwarded-valid")
        candidate = candidates[0]
        receipts = self.forwarded_artifacts(candidate)
        result = self.publish(
            "forwarded-valid",
            manifest_path=manifest,
            candidates=candidates,
            decisions=[self.decision(candidate, decision="forwarded", receipts=receipts)],
            expected_commit_root_sha256=EMPTY_SHA256,
        )
        run_manifest = json.loads(Path(result["run_manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(run_manifest["publication_status"], "validated")
        self.assertNotIn("outcome", run_manifest)
        recorded = json.loads(
            self.resolve(run_manifest["decisions_path"]).read_text(encoding="utf-8").splitlines()[0]
        )
        self.assertEqual({receipt["role"] for receipt in recorded["receipts"]}, {
            "profile", "evidence", "primary-source"
        })
        original_receipt_paths = {
            receipt["role"]: self.resolve(receipt["path"])
            for receipt in receipts
            if receipt["role"] != "profile"
        }
        for receipt in recorded["receipts"]:
            self.assertFalse(
                Path(receipt["path"]).is_absolute(),
                "published receipt descriptors must be portable relative paths",
            )
            self.assertTrue(
                receipt["path"].startswith(
                    "autoresearch/research-radar/objects/sha256/"
                ),
                "decision receipts must be vendored into content-addressed storage",
            )
            receipt_path = self.resolve(receipt["path"])
            self.assertEqual(sha256_file(receipt_path), receipt["sha256"])

        evidence_receipt = next(
            receipt for receipt in recorded["receipts"] if receipt["role"] == "evidence"
        )
        evidence = json.loads(
            self.resolve(evidence_receipt["path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(len(evidence["primary_sources"]), 1)
        primary_descriptor = evidence["primary_sources"][0]
        self.assertTrue(
            primary_descriptor["path"].startswith(
                "autoresearch/research-radar/objects/sha256/"
            )
        )
        self.assertEqual(
            sha256_file(self.resolve(primary_descriptor["path"])),
            primary_descriptor["sha256"],
        )

        for original in original_receipt_paths.values():
            original.unlink()
        pointer_bytes, pointer, _state, state_bytes, _state_path = subject._read_pointer(
            self.pointer, self.root, self.source_instance_id
        )
        self.assertEqual(
            hashlib.sha256(pointer_bytes).hexdigest(), result["stable_pointer_sha256"]
        )
        self.assertEqual(pointer["run_id"], result["run_id"])
        self.assertEqual(hashlib.sha256(state_bytes).hexdigest(), pointer["state_sha256"])
        for receipt in recorded["receipts"]:
            self.assertEqual(
                sha256_file(self.resolve(receipt["path"])), receipt["sha256"]
            )

    def test_pointer_rejects_forwarded_decision_with_receipts_removed(self) -> None:
        manifest, _path, candidates = self.make_extraction(
            "forwarded-historical-tamper"
        )
        candidate = candidates[0]
        result = self.publish(
            "forwarded-historical-tamper",
            manifest_path=manifest,
            candidates=candidates,
            decisions=[self.decision(
                candidate,
                decision="forwarded",
                receipts=self.forwarded_artifacts(candidate),
            )],
            expected_commit_root_sha256=EMPTY_SHA256,
        )
        run_manifest_path = Path(result["run_manifest_path"])
        run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        decisions_path = self.resolve(run_manifest["decisions_path"])
        decision = json.loads(decisions_path.read_text(encoding="utf-8").splitlines()[0])
        decision["receipts"] = []
        decision.pop("decision_sha256", None)
        decision["decision_sha256"] = hashlib.sha256(canonical_bytes(decision)).hexdigest()
        decisions_path.write_text(
            json.dumps(decision, sort_keys=True) + "\n", encoding="utf-8"
        )
        run_manifest["decisions_sha256"] = sha256_file(decisions_path)
        self.rewrite_committed_run_manifest(run_manifest_path, run_manifest)

        with self.assertRaisesRegex(
            subject.FoloSourceError, "forwarded|receipt|evidence|decision"
        ):
            subject._read_pointer(
                self.pointer, self.root, self.source_instance_id
            )


class CommitRootAtomicityTests(FoloProtocolFixture):
    def test_empty_successful_scan_publishes_a_run_and_pointer(self) -> None:
        self.database.unlink()
        self.database = self.make_database([{
            "id": "query-miss",
            "title": "Unrelated item",
            "content": "No matching topic",
            "description": "No matching topic",
        }])
        self.source_snapshot_sha256 = sha256_file(self.database)
        self.database_snapshot_sha256 = sha256_file(self.database)
        self.snapshot_sha256 = self.source_snapshot_sha256
        self.refresh_receipt = self.write_refresh_receipt()
        result = self.publish(
            "empty", candidates=[], decisions=[], expected_commit_root_sha256=EMPTY_SHA256
        )
        self.assertEqual(result["recorded"], 0)
        self.assertTrue(self.pointer.is_file())
        pointer = json.loads(self.pointer.read_text(encoding="utf-8"))
        self.assertEqual(pointer["outcome"], "research-radar-cycle-complete")
        manifest = json.loads(self.resolve(pointer["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["counts"]["total"], 0)
        state = json.loads(self.resolve(pointer["state_path"]).read_text(encoding="utf-8"))
        self.assertEqual(state["processed"], {})
        self.assertEqual(state["pending"], {})

    def test_same_publication_replay_is_idempotent(self) -> None:
        manifest, _path, candidates = self.make_extraction("replay")
        decisions = [self.decision(candidate) for candidate in candidates]
        first = self.publish(
            "replay", manifest_path=manifest, candidates=candidates, decisions=decisions,
            expected_commit_root_sha256=EMPTY_SHA256,
        )
        pointer_before = self.pointer.read_bytes()
        second = self.publish(
            "replay", manifest_path=manifest, candidates=candidates, decisions=decisions,
            expected_commit_root_sha256=first["stable_pointer_sha256"],
        )
        self.assertEqual(second["already_recorded"], len(candidates))
        self.assertEqual(second["run_id"], first["run_id"])
        self.assertEqual(self.pointer.read_bytes(), pointer_before)

    def test_two_concurrent_writers_from_same_commit_root_cannot_lose_update(self) -> None:
        manifest, _path, candidates = self.make_extraction("race")
        candidate = candidates[0]
        ignored_path = self.write_jsonl(
            self.root / "extractions/race/ignored.jsonl",
            [self.decision(candidate, decision="ignored")],
        )
        deferred_path = self.write_jsonl(
            self.root / "extractions/race/deferred.jsonl",
            [self.decision(
                candidate,
                decision="deferred",
                retry_after=(NOW + dt.timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            )],
        )
        barrier = __import__("threading").Barrier(2)

        def writer(decisions_path: Path) -> tuple[str, object]:
            barrier.wait(timeout=5)
            try:
                return "ok", subject.publish_run(
                    manifest,
                    decisions_path,
                    artifact_root=self.root,
                    stable_pointer_path=self.pointer,
                    expected_commit_root_sha256=EMPTY_SHA256,
                    now=NOW,
                )
            except subject.FoloSourceError as exc:
                return "error", exc

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(writer, (ignored_path, deferred_path)))
        self.assertEqual(sorted(status for status, _value in results), ["error", "ok"])
        error = next(value for status, value in results if status == "error")
        self.assertRegex(str(error), "stale")
        success = next(value for status, value in results if status == "ok")
        pointer = json.loads(self.pointer.read_text(encoding="utf-8"))
        self.assertEqual(pointer["run_id"], success["run_id"])
        state = json.loads(self.resolve(pointer["state_path"]).read_text(encoding="utf-8"))
        total_records = len(state["processed"]) + len(state["pending"])
        self.assertEqual(total_records, 1)
        self.assertTrue(
            candidate["id"] in state["processed"] or candidate["id"] in state["pending"]
        )

    def test_failure_before_pointer_replace_keeps_old_commit_root_byte_identical(self) -> None:
        first = self.publish("base", expected_commit_root_sha256=EMPTY_SHA256)
        old_pointer = self.pointer.read_bytes()
        state_path = Path(first["state_path"])
        next_time = NOW + dt.timedelta(minutes=1)
        connection = sqlite3.connect(self.database)
        connection.execute(
            "INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "next", "sub", "Research next method", "https://example.test/next",
                "Author", int(next_time.timestamp() * 1000), int(next_time.timestamp() * 1000),
                None, "Research evidence lead", "Research description",
            ),
        )
        connection.commit()
        connection.close()
        self.source_snapshot_sha256 = sha256_file(self.database)
        self.database_snapshot_sha256 = sha256_file(self.database)
        self.snapshot_sha256 = self.source_snapshot_sha256
        self.refresh_receipt = self.write_refresh_receipt(
            refreshed_at=next_time.isoformat().replace("+00:00", "Z")
        )
        records = self.extract(
            state_path=state_path,
            now_ms=int(next_time.timestamp() * 1000),
        )
        self.assertEqual([record["id"] for record in records], ["folo:next"])
        manifest, _path, records = self.make_extraction(
            "pre-replace-failure", candidates=records, input_state_path=state_path,
            extracted_at=next_time,
        )
        decisions_path = self.write_jsonl(
            self.root / "extractions/pre-replace-failure/decisions.jsonl",
            [self.decision(candidate) for candidate in records],
        )
        with mock.patch.object(subject, "_atomic_replace_pointer", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                subject.publish_run(
                    manifest,
                    decisions_path,
                    artifact_root=self.root,
                    stable_pointer_path=self.pointer,
                    expected_commit_root_sha256=sha256_file(self.pointer),
                    now=next_time,
                )
        self.assertEqual(self.pointer.read_bytes(), old_pointer)
        orphan_manifests = list(
            (self.root / "autoresearch/research-radar/runs").glob("*/manifest.json")
        )
        self.assertTrue(orphan_manifests)
        for orphan in orphan_manifests:
            payload = json.loads(orphan.read_text(encoding="utf-8"))
            self.assertEqual(payload["publication_status"], "validated")
            self.assertNotIn("outcome", payload)

    def test_post_replace_directory_sync_failure_is_commit_indeterminate_but_not_torn(self) -> None:
        manifest, _path, candidates = self.make_extraction("indeterminate")
        decisions_path = self.write_jsonl(
            self.root / "extractions/indeterminate/decisions.jsonl",
            [self.decision(candidate) for candidate in candidates],
        )
        real_fsync_directory = subject._fsync_directory

        def fail_pointer_parent(path: Path) -> None:
            if Path(path).resolve() == self.pointer.parent.resolve():
                raise OSError("injected directory fsync failure")
            real_fsync_directory(path)

        with mock.patch.object(subject, "_fsync_directory", side_effect=fail_pointer_parent):
            with self.assertRaises(subject.FoloCommitIndeterminate) as captured:
                subject.publish_run(
                    manifest,
                    decisions_path,
                    artifact_root=self.root,
                    stable_pointer_path=self.pointer,
                    expected_commit_root_sha256=EMPTY_SHA256,
                    now=NOW,
                )
        self.assertIn(captured.exception.observed_status, {"old", "new"})
        if self.pointer.exists():
            pointer = json.loads(self.pointer.read_text(encoding="utf-8"))
            self.assertEqual(sha256_file(self.resolve(pointer["manifest_path"])), pointer["manifest_sha256"])
            self.assertEqual(sha256_file(self.resolve(pointer["state_path"])), pointer["state_sha256"])

    def test_post_replace_keyboard_interrupt_is_commit_indeterminate(self) -> None:
        manifest, _path, candidates = self.make_extraction(
            "keyboard-interrupt-indeterminate"
        )
        decisions_path = self.write_jsonl(
            self.root / "extractions/keyboard-interrupt-indeterminate/decisions.jsonl",
            [self.decision(candidate) for candidate in candidates],
        )
        real_fsync_directory = subject._fsync_directory

        def interrupt_pointer_parent(path: Path) -> None:
            if Path(path).resolve() == self.pointer.parent.resolve():
                raise KeyboardInterrupt("injected after pointer replacement")
            real_fsync_directory(path)

        with mock.patch.object(
            subject, "_fsync_directory", side_effect=interrupt_pointer_parent
        ):
            with self.assertRaises(subject.FoloCommitIndeterminate) as captured:
                subject.publish_run(
                    manifest,
                    decisions_path,
                    artifact_root=self.root,
                    stable_pointer_path=self.pointer,
                    expected_commit_root_sha256=EMPTY_SHA256,
                    now=NOW,
                )
        self.assertIn(captured.exception.observed_status, {"old", "new"})
        if self.pointer.exists():
            pointer = json.loads(self.pointer.read_text(encoding="utf-8"))
            self.assertEqual(
                sha256_file(self.resolve(pointer["manifest_path"])),
                pointer["manifest_sha256"],
            )
            self.assertEqual(
                sha256_file(self.resolve(pointer["state_path"])),
                pointer["state_sha256"],
            )

    def test_publish_rejects_a_receipt_that_became_stale_after_extraction(self) -> None:
        manifest, _path, candidates = self.make_extraction("stale-at-publish")
        decisions_path = self.write_jsonl(
            self.root / "extractions/stale-at-publish/decisions.jsonl",
            [self.decision(candidate) for candidate in candidates],
        )
        with self.assertRaisesRegex(subject.FoloSourceError, "stale|too old"):
            subject.publish_run(
                manifest,
                decisions_path,
                artifact_root=self.root,
                stable_pointer_path=self.pointer,
                expected_commit_root_sha256=EMPTY_SHA256,
                now=NOW + dt.timedelta(minutes=181),
            )
        self.assertFalse(self.pointer.exists())

    def test_run_vendors_profile_and_refresh_receipt_for_historical_verification(self) -> None:
        original_profile = self.profile.read_bytes()
        original_receipt = self.refresh_receipt.read_bytes()
        original_public_key = self.public_key.read_bytes()
        profile_payload = json.loads(original_profile)
        self.assertEqual(
            set(profile_payload["refresh_trust"]),
            {
                "producer_identity",
                "ed25519_public_key_path",
                "ed25519_public_key_sha256",
            },
        )
        self.assertNotIn("private", original_profile.decode("utf-8").casefold())
        self.assertNotIn("hmac", original_profile.decode("utf-8").casefold())
        result = self.publish("vendored", expected_commit_root_sha256=EMPTY_SHA256)
        run_manifest_path = Path(result["run_manifest_path"])
        run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        run_dir = run_manifest_path.parent.resolve()
        profile_copy = self.resolve(run_manifest["profile_path"])
        receipt_copy = self.resolve(run_manifest["refresh_receipt_path"])
        public_key_descriptor = run_manifest["refresh_public_key"]
        public_key_copy = self.resolve(public_key_descriptor["path"])
        authority_artifacts = run_manifest["authority_artifacts"]
        self.assertEqual(
            {descriptor["role"] for descriptor in authority_artifacts},
            {"research-brief", "adaptation-plan", "experiment-contract"},
        )
        for descriptor in authority_artifacts:
            self.assertEqual(
                sha256_file(self.resolve(descriptor["path"])), descriptor["sha256"]
            )
        self.assertEqual(profile_copy.parent.resolve(), run_dir)
        self.assertEqual(receipt_copy.parent.resolve(), run_dir)
        self.assertEqual(profile_copy.read_bytes(), original_profile)
        self.assertEqual(receipt_copy.read_bytes(), original_receipt)
        self.assertEqual(public_key_copy.read_bytes(), original_public_key)
        self.assertEqual(sha256_file(profile_copy), run_manifest["profile_sha256"])
        self.assertEqual(sha256_file(receipt_copy), run_manifest["refresh_receipt_sha256"])
        self.assertEqual(
            sha256_file(public_key_copy), public_key_descriptor["sha256"]
        )
        self.assertEqual(
            public_key_descriptor["sha256"],
            profile_payload["refresh_trust"]["ed25519_public_key_sha256"],
        )
        receipt_payload = json.loads(receipt_copy.read_text(encoding="utf-8"))
        signature = bytes.fromhex(receipt_payload.pop("signature_ed25519"))
        self.assertTrue(
            ed25519_verify(
                public_key_copy.read_bytes(), canonical_bytes(receipt_payload), signature
            )
        )
        tampered_payload = copy.deepcopy(receipt_payload)
        tampered_payload["cache_stable"] = False
        self.assertFalse(
            ed25519_verify(
                public_key_copy.read_bytes(), canonical_bytes(tampered_payload), signature
            )
        )

        self.profile.unlink()
        self.public_key.unlink()
        self.research_brief.unlink()
        self.adaptation_plan.unlink()
        self.experiment_contract.unlink()
        self.refresh_receipt.write_text("tampered external receipt", encoding="utf-8")
        pointer_bytes, pointer, state, state_bytes, state_path = subject._read_pointer(
            self.pointer, self.root, self.source_instance_id
        )
        self.assertEqual(hashlib.sha256(pointer_bytes).hexdigest(), result["stable_pointer_sha256"])
        self.assertEqual(pointer["run_id"], result["run_id"])
        self.assertEqual(hashlib.sha256(state_bytes).hexdigest(), pointer["state_sha256"])
        self.assertEqual(state_path, Path(result["state_path"]))
        self.assertEqual(state["source_instance_id"], self.source_instance_id)
        self.assertEqual(public_key_copy.read_bytes(), original_public_key)
        for artifact in (self.root / "autoresearch/research-radar").rglob("*"):
            if artifact.is_file():
                self.assertNotIn(self.signing_seed, artifact.read_bytes())


class HistoricalAuditAdversarialTests(FoloProtocolFixture):
    def test_pointer_requires_exact_authority_artifact_set(self) -> None:
        result = self.publish(
            "audit-authority-set", expected_commit_root_sha256=EMPTY_SHA256
        )
        manifest_path = Path(result["run_manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            {descriptor["role"] for descriptor in manifest["authority_artifacts"]},
            {"research-brief", "adaptation-plan", "experiment-contract"},
        )
        manifest["authority_artifacts"] = manifest["authority_artifacts"][1:]
        self.rewrite_committed_run_manifest(manifest_path, manifest)

        with self.assertRaisesRegex(subject.FoloSourceError, "authority"):
            subject._read_pointer(
                self.pointer, self.root, self.source_instance_id
            )

    def test_pointer_rejects_public_key_not_matching_frozen_profile_trust(self) -> None:
        result = self.publish("audit-key-swap", expected_commit_root_sha256=EMPTY_SHA256)
        manifest_path = Path(result["run_manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        public_key_path = self.resolve(manifest["refresh_public_key"]["path"])
        receipt_path = self.resolve(manifest["refresh_receipt_path"])

        attacker_seed = hashlib.sha256(b"attacker-ed25519-key").digest()
        attacker_public_key = ed25519_public_key(attacker_seed)
        public_key_path.write_bytes(attacker_public_key)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt = self.sign_receipt_payload(receipt, signing_seed=attacker_seed)
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest["refresh_public_key"]["sha256"] = sha256_file(public_key_path)
        manifest["refresh_receipt_sha256"] = sha256_file(receipt_path)
        self.rewrite_committed_run_manifest(manifest_path, manifest)

        with self.assertRaisesRegex(subject.FoloSourceError, "public key|trust|hash"):
            subject._read_pointer(
                self.pointer, self.root, self.source_instance_id
            )

    def test_historical_receipt_freshness_is_checked_at_run_validated_at(self) -> None:
        result = self.publish(
            "audit-validation-time", expected_commit_root_sha256=EMPTY_SHA256
        )
        manifest_path = Path(result["run_manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["validated_at"], NOW.isoformat().replace("+00:00", "Z"))
        receipt_path = self.resolve(manifest["refresh_receipt_path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["refreshed_at"] = (
            NOW - dt.timedelta(minutes=181)
        ).isoformat().replace("+00:00", "Z")
        receipt = self.sign_receipt_payload(receipt)
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest["refresh_receipt_sha256"] = sha256_file(receipt_path)
        self.rewrite_committed_run_manifest(manifest_path, manifest)

        with self.assertRaisesRegex(subject.FoloSourceError, "stale"):
            subject._read_pointer(
                self.pointer, self.root, self.source_instance_id
            )

    def test_pointer_rejects_missing_replay_critical_run_artifacts(self) -> None:
        result = self.publish(
            "audit-missing-replay-artifacts", expected_commit_root_sha256=EMPTY_SHA256
        )
        manifest = json.loads(
            Path(result["run_manifest_path"]).read_text(encoding="utf-8")
        )
        artifacts = {
            "candidates": self.resolve(manifest["candidates_path"]),
            "extraction": self.resolve(manifest["extraction_manifest_path"]),
            "input-state": self.resolve(manifest["input_state"]["path"]),
        }

        for label, artifact in artifacts.items():
            with self.subTest(artifact=label):
                original = artifact.read_bytes()
                artifact.unlink()
                try:
                    with self.assertRaisesRegex(
                        subject.FoloSourceError,
                        "candidate|extraction|input.state|artifact|missing",
                    ):
                        subject._read_pointer(
                            self.pointer, self.root, self.source_instance_id
                        )
                finally:
                    artifact.write_bytes(original)

    def test_pointer_rejects_profile_unauthorized_committed_signal_type(self) -> None:
        result = self.publish(
            "audit-unauthorized-signal", expected_commit_root_sha256=EMPTY_SHA256
        )

        def unauthorized(decision: dict) -> None:
            decision["signal_type"] = "dataset"

        self.rewrite_committed_decision_bundle(
            result,
            mutate_decision=unauthorized,
            recompute_decision_sha256=True,
        )

        with self.assertRaisesRegex(subject.FoloSourceError, "signal|policy|decision"):
            subject._read_pointer(self.pointer, self.root, self.source_instance_id)

    def test_pointer_rejects_non_cas_committed_receipt(self) -> None:
        manifest_path, _candidate_path, candidates = self.make_extraction(
            "audit-non-cas-receipt"
        )
        note = self.root / "evidence/audit-note.json"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text('{"reviewed":true}\n', encoding="utf-8")
        result = self.publish(
            "audit-non-cas-receipt",
            manifest_path=manifest_path,
            candidates=candidates,
            decisions=[self.decision(candidates[0], receipts=[{
                "role": "note",
                "path": str(note.relative_to(self.root)),
                "sha256": sha256_file(note),
            }])],
            expected_commit_root_sha256=EMPTY_SHA256,
        )
        run_manifest = json.loads(
            Path(result["run_manifest_path"]).read_text(encoding="utf-8")
        )
        committed_decision = json.loads(
            self.resolve(run_manifest["decisions_path"])
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        cas_receipt = committed_decision["receipts"][0]
        non_cas = self.root / "tampered/non-cas-receipt.json"
        non_cas.parent.mkdir(parents=True, exist_ok=True)
        non_cas.write_bytes(self.resolve(cas_receipt["path"]).read_bytes())

        def point_outside_cas(decision: dict) -> None:
            decision["receipts"][0]["path"] = str(non_cas.relative_to(self.root))

        self.rewrite_committed_decision_bundle(
            result,
            mutate_decision=point_outside_cas,
            recompute_decision_sha256=True,
        )

        with self.assertRaisesRegex(
            subject.FoloSourceError, "content.addressed|CAS|receipt|decision"
        ):
            subject._read_pointer(self.pointer, self.root, self.source_instance_id)

    def test_pointer_rejects_stale_inner_decision_digest_after_outer_rehash(self) -> None:
        result = self.publish(
            "audit-stale-decision-digest", expected_commit_root_sha256=EMPTY_SHA256
        )

        self.rewrite_committed_decision_bundle(
            result,
            mutate_decision=lambda decision: decision.__setitem__(
                "decision_sha256", "0" * 64
            ),
        )

        with self.assertRaisesRegex(subject.FoloSourceError, "decision|sha256|digest"):
            subject._read_pointer(self.pointer, self.root, self.source_instance_id)

    def test_pointer_rejects_state_and_decision_ledger_disagreement(self) -> None:
        result = self.publish(
            "audit-state-ledger-disagreement", expected_commit_root_sha256=EMPTY_SHA256
        )

        self.rewrite_committed_decision_bundle(
            result,
            mirror_decision_into_state=False,
            mutate_state=lambda state_record: state_record.__setitem__(
                "reason", "state-only attacker rewrite"
            ),
        )

        with self.assertRaisesRegex(subject.FoloSourceError, "state|decision|ledger"):
            subject._read_pointer(self.pointer, self.root, self.source_instance_id)

    def test_vendored_input_state_supports_deterministic_historical_reextraction(self) -> None:
        result = self.publish(
            "audit-historical-reextraction", expected_commit_root_sha256=EMPTY_SHA256
        )
        manifest = json.loads(
            Path(result["run_manifest_path"]).read_text(encoding="utf-8")
        )
        extraction = json.loads(
            self.resolve(manifest["extraction_manifest_path"]).read_text(encoding="utf-8")
        )
        profile = json.loads(
            self.resolve(manifest["profile_path"]).read_text(encoding="utf-8")
        )
        expected = [
            json.loads(line)
            for line in self.resolve(manifest["candidates_path"])
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        extracted_at = dt.datetime.fromisoformat(
            extraction["extracted_at"].replace("Z", "+00:00")
        )
        source_scope = profile["source_scope"]
        self.database.unlink()

        actual = subject.extract_candidates(
            self.resolve(manifest["database_snapshot"]["path"]),
            state_path=self.resolve(manifest["input_state"]["path"]),
            source_instance_id=self.source_instance_id,
            hours=extraction["extraction_bounds"]["hours"],
            limit=extraction["extraction_bounds"]["limit"],
            now_ms=int(extracted_at.timestamp() * 1000),
            authorized_feed_ids=source_scope["authorized_feed_ids"],
            query_scope={
                "include_any": source_scope["query_terms"],
                "exclude_any": source_scope.get("excluded_terms", []),
            },
        )

        self.assertEqual(actual, expected)


class DeferredTransitionTests(FoloProtocolFixture):
    def test_due_deferred_candidate_can_be_deferred_again_to_a_later_future(self) -> None:
        candidate = self.extract()[0]
        first_manifest, _path, _records = self.make_extraction(
            "defer-first", candidates=[candidate]
        )
        first_retry = NOW + dt.timedelta(hours=1)
        first = self.publish(
            "defer-first",
            manifest_path=first_manifest,
            candidates=[candidate],
            decisions=[self.decision(
                candidate,
                decision="deferred",
                retry_after=first_retry.isoformat().replace("+00:00", "Z"),
            )],
            expected_commit_root_sha256=EMPTY_SHA256,
            now=NOW,
        )
        due = self.extract(
            state_path=Path(first["state_path"]),
            now_ms=int(first_retry.timestamp() * 1000),
        )
        self.assertEqual([record["id"] for record in due], [candidate["id"]])
        self.assertRegex(due[0]["prior_decision_sha256"], r"^[0-9a-f]{64}$")

        second_manifest, _path, _records = self.make_extraction(
            "defer-second",
            candidates=due,
            input_state_path=Path(first["state_path"]),
            extracted_at=first_retry,
        )
        second_retry = first_retry + dt.timedelta(hours=1)
        second = self.publish(
            "defer-second",
            manifest_path=second_manifest,
            candidates=due,
            decisions=[self.decision(
                due[0],
                decision="deferred",
                prior_decision_sha256=due[0]["prior_decision_sha256"],
                retry_after=second_retry.isoformat().replace("+00:00", "Z"),
            )],
            expected_commit_root_sha256=first["stable_pointer_sha256"],
            now=first_retry,
        )
        state = json.loads(Path(second["state_path"]).read_text(encoding="utf-8"))
        self.assertEqual(
            state["pending"][candidate["id"]]["retry_after"],
            second_retry.isoformat().replace("+00:00", "Z"),
        )

    def test_deferred_retry_time_must_be_after_publish_time(self) -> None:
        manifest, _path, candidates = self.make_extraction("defer-not-future")
        for label, retry_after in (
            ("equal", NOW),
            ("past", NOW - dt.timedelta(seconds=1)),
        ):
            with self.subTest(label=label):
                decisions_path = self.write_jsonl(
                    self.root / f"extractions/defer-not-future/{label}.jsonl",
                    [self.decision(
                        candidates[0],
                        decision="deferred",
                        retry_after=retry_after.isoformat().replace("+00:00", "Z"),
                    )],
                )
                with self.assertRaises(subject.FoloSourceError):
                    subject.publish_run(
                        manifest,
                        decisions_path,
                        artifact_root=self.root,
                        stable_pointer_path=self.pointer,
                        expected_commit_root_sha256=EMPTY_SHA256,
                        now=NOW,
                    )
                self.assertFalse(self.pointer.exists())


class PathSafetyTests(FoloProtocolFixture):
    def test_candidates_cli_refuses_to_replace_explicit_source_database(self) -> None:
        before = self.database.read_bytes()
        stderr = io.StringIO()
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = subject.main([
                "candidates",
                "--refresh-receipt", str(self.refresh_receipt),
                "--profile", str(self.profile),
                "--artifact-root", str(self.root),
                "--database", str(self.database),
                "--output", str(self.database),
                "--extraction-manifest", str(self.root / "extract.json"),
                "--now-ms", str(NOW_MS),
            ])
        self.assertEqual(result, 2)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertFalse((self.root / "extract.json").exists())

    def test_extraction_refuses_state_that_aliases_refresh_receipt(self) -> None:
        candidates = self.extract()
        candidates_path = self.write_jsonl(
            self.root / "extractions/state-alias/candidates.jsonl", candidates
        )
        manifest_path = self.root / "extractions/state-alias/extraction-manifest.json"
        receipt_before = self.refresh_receipt.read_bytes()
        with self.assertRaises(subject.FoloSourceError):
            subject.create_extraction_manifest(
                database_path=self.database,
                candidates_path=candidates_path,
                extraction_manifest_path=manifest_path,
                profile_path=self.profile,
                profile_id=self.profile_id,
                refresh_receipt_path=self.refresh_receipt,
                source_instance_id=self.source_instance_id,
                source_snapshot_sha256=self.snapshot_sha256,
                input_state_path=self.refresh_receipt,
                stable_pointer_path=self.pointer,
                extracted_at=NOW,
                source_path=self.database,
                artifact_root=self.root,
            )
        self.assertEqual(self.refresh_receipt.read_bytes(), receipt_before)
        self.assertFalse(manifest_path.exists())

    def test_publish_refuses_writes_inside_custom_protected_source_root(self) -> None:
        manifest, _path, candidates = self.make_extraction("protected-root")
        source_root = self.root / "custom-folo-source"
        source_root.mkdir()
        decisions_path = self.write_jsonl(
            source_root / "decisions.jsonl",
            [self.decision(candidate) for candidate in candidates],
        )
        pointer_inside_source = source_root / "manifest.json"
        source_before = {
            path.relative_to(source_root): path.read_bytes()
            for path in source_root.rglob("*") if path.is_file()
        }
        with self.assertRaises(subject.FoloSourceError):
            subject.publish_run(
                manifest,
                decisions_path,
                artifact_root=self.root,
                stable_pointer_path=pointer_inside_source,
                leveldb_path=source_root,
                expected_commit_root_sha256=EMPTY_SHA256,
                now=NOW,
            )
        source_after = {
            path.relative_to(source_root): path.read_bytes()
            for path in source_root.rglob("*") if path.is_file()
        }
        self.assertEqual(source_after, source_before)
        self.assertFalse(pointer_inside_source.exists())

    def test_ed25519_public_key_cannot_alias_candidate_or_output_artifact(self) -> None:
        candidate_path = self.root / "inputs/aliased-public-key.bin"
        candidate_path.write_bytes(ed25519_public_key(self.signing_seed))
        candidate_bytes = candidate_path.read_bytes()
        self.profile = self.write_profile(refresh_trust={
            "producer_identity": "harness:folo-ui-controller:v1",
            "ed25519_public_key_path": candidate_path.name,
            "ed25519_public_key_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        })
        self.refresh_receipt = self.write_refresh_receipt()
        manifest_path = self.root / "extractions/key-alias/extraction-manifest.json"
        with self.assertRaisesRegex(subject.FoloSourceError, "alias"):
            subject.create_extraction_manifest(
                database_path=self.database,
                candidates_path=candidate_path,
                extraction_manifest_path=manifest_path,
                profile_path=self.profile,
                profile_id=self.profile_id,
                refresh_receipt_path=self.refresh_receipt,
                source_instance_id=self.source_instance_id,
                source_snapshot_sha256=self.snapshot_sha256,
                input_state_path=None,
                stable_pointer_path=self.pointer,
                extracted_at=NOW,
                source_path=self.database,
                artifact_root=self.root,
            )
        self.assertEqual(candidate_path.read_bytes(), candidate_bytes)
        self.assertFalse(manifest_path.exists())

    def test_parent_directory_symlink_swap_cannot_escape_artifact_root(self) -> None:
        safe_parent = self.root / "symlink-race"
        safe_parent.mkdir()
        quarantined_parent = self.root / "symlink-race-original"
        target = safe_parent / "immutable.json"
        swapped = False

        with tempfile.TemporaryDirectory(prefix="autoresearch-symlink-escape-") as outside_raw:
            outside = Path(outside_raw)
            with subject._AnchoredArtifacts(self.root) as anchor:
                real_relative = anchor.relative

                def swap_after_relative_check(path: Path, field: str) -> str:
                    nonlocal swapped
                    relative = real_relative(path, field)
                    if not swapped:
                        safe_parent.rename(quarantined_parent)
                        safe_parent.symlink_to(outside, target_is_directory=True)
                        swapped = True
                    return relative

                with mock.patch.object(
                    anchor, "relative", side_effect=swap_after_relative_check
                ):
                    with self.assertRaises(subject.FoloSourceError):
                        subject._write_immutable(
                            target,
                            b'{"safe":true}\n',
                            artifact_root=self.root,
                            anchor=anchor,
                        )
            self.assertTrue(swapped)
            self.assertFalse((outside / target.name).exists())
            self.assertFalse((quarantined_parent / target.name).exists())

    def test_artifact_root_symlink_is_rejected_before_resolution(self) -> None:
        real_root = self.root / "real-artifact-root"
        real_root.mkdir()
        linked_root = self.root / "linked-artifact-root"
        linked_root.symlink_to(real_root, target_is_directory=True)
        target = linked_root / "artifact.json"

        with self.assertRaisesRegex(subject.FoloSourceError, "artifact_root|symlink"):
            subject._write_immutable(
                target, b'{"must-not-write":true}\n', artifact_root=linked_root
            )
        self.assertFalse((real_root / "artifact.json").exists())

    def test_preexisting_parent_symlink_chain_is_rejected_before_resolution(self) -> None:
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        target = linked_parent / "artifact.json"

        with self.assertRaisesRegex(subject.FoloSourceError, "symlink|safe"):
            subject._write_immutable(
                target, b'{"must-not-write":true}\n', artifact_root=self.root
            )
        self.assertFalse((real_parent / "artifact.json").exists())

    def test_preseeded_identical_hardlink_is_not_accepted_as_immutable(self) -> None:
        payload = b'{"same":"bytes"}\n'
        seed = self.root / "preseed-source.json"
        seed.write_bytes(payload)
        target = self.root / "immutable/preseeded.json"
        target.parent.mkdir()
        os.link(seed, target)
        self.assertEqual(seed.stat().st_ino, target.stat().st_ino)
        self.assertEqual(target.stat().st_nlink, 2)

        with self.assertRaisesRegex(subject.FoloSourceError, "unsafe|single-link"):
            subject._write_immutable(target, payload, artifact_root=self.root)
        self.assertEqual(seed.read_bytes(), payload)
        self.assertEqual(target.read_bytes(), payload)
        self.assertEqual(target.stat().st_nlink, 2)

    def test_reused_identical_immutable_is_file_and_directory_fsynced(self) -> None:
        payload = b'{"recovered-orphan":true}\n'
        target = self.root / "immutable/recovered.json"
        target.parent.mkdir()
        target.write_bytes(payload)
        file_identity = (target.stat().st_dev, target.stat().st_ino)
        parent_identity = (target.parent.stat().st_dev, target.parent.stat().st_ino)
        real_fsync = subject.os.fsync
        synced: list[tuple[int, int]] = []

        def tracked_fsync(descriptor: int) -> None:
            details = os.fstat(descriptor)
            synced.append((details.st_dev, details.st_ino))
            real_fsync(descriptor)

        with mock.patch.object(subject.os, "fsync", side_effect=tracked_fsync):
            subject._write_immutable(target, payload, artifact_root=self.root)
        self.assertIn(file_identity, synced)
        self.assertIn(parent_identity, synced)

    def test_every_new_directory_entry_is_fsynced_before_immutable_publish(self) -> None:
        target = self.root / "durability/one/two/three/artifact.json"
        real_mkdir = subject.os.mkdir
        real_fsync = subject.os.fsync
        created_in: list[tuple[int, int]] = []
        synced: list[tuple[int, int]] = []
        events: list[tuple[str, tuple[int, int]]] = []

        def tracked_mkdir(path, mode=0o777, *, dir_fd=None):
            self.assertIsNotNone(dir_fd)
            details = os.fstat(dir_fd)
            identity = (details.st_dev, details.st_ino)
            result = real_mkdir(path, mode, dir_fd=dir_fd)
            created_in.append(identity)
            events.append(("mkdir", identity))
            return result

        def tracked_fsync(descriptor: int) -> None:
            details = os.fstat(descriptor)
            identity = (details.st_dev, details.st_ino)
            synced.append(identity)
            events.append(("fsync", identity))
            real_fsync(descriptor)

        with mock.patch.object(subject.os, "mkdir", side_effect=tracked_mkdir), mock.patch.object(
            subject.os, "fsync", side_effect=tracked_fsync
        ):
            subject._write_immutable(
                target, b'{"durable":true}\n', artifact_root=self.root
            )
        self.assertGreaterEqual(len(created_in), 4)
        for parent_identity in created_in:
            self.assertIn(
                parent_identity,
                synced,
                "the parent of every newly created directory must be fsynced",
            )
        for index, event in enumerate(events):
            if event[0] == "mkdir":
                self.assertIn(
                    ("fsync", event[1]),
                    events[index + 1 :],
                    "a directory entry must be synced after, not merely before, mkdir",
                )
        self.assertEqual(target.read_bytes(), b'{"durable":true}\n')

    def test_crash_during_directory_chain_sync_cannot_create_artifact(self) -> None:
        target = self.root / "crash-chain/one/two/artifact.json"
        root_identity = (self.root.stat().st_dev, self.root.stat().st_ino)
        real_fsync = subject.os.fsync

        def crash_on_first_parent_sync(descriptor: int) -> None:
            details = os.fstat(descriptor)
            if (details.st_dev, details.st_ino) == root_identity:
                raise OSError("injected crash during parent directory sync")
            real_fsync(descriptor)

        with mock.patch.object(subject.os, "fsync", side_effect=crash_on_first_parent_sync):
            with self.assertRaises(OSError):
                subject._write_immutable(
                    target, b'{"must-not-exist":true}\n', artifact_root=self.root
                )
        self.assertFalse(target.exists())

    def test_lock_creation_race_cannot_split_the_lock_inode(self) -> None:
        lock_relative = "autoresearch/research-radar/.manifest.json.lock"
        lock_name = ".manifest.json.lock"
        real_open = subject.os.open
        real_fstat = subject.os.fstat
        swapped = False
        opened_lock_fd = None
        saved_parent_fd = None

        with subject._AnchoredArtifacts(self.root) as anchor:
            def capture_lock_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal opened_lock_fd, saved_parent_fd
                descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
                if path == lock_name and flags & os.O_CREAT and opened_lock_fd is None:
                    opened_lock_fd = descriptor
                    saved_parent_fd = os.dup(dir_fd)
                return descriptor

            def replace_entry_after_fstat(descriptor: int):
                nonlocal swapped
                details = real_fstat(descriptor)
                if descriptor == opened_lock_fd and not swapped:
                    os.unlink(lock_name, dir_fd=saved_parent_fd)
                    replacement = real_open(
                        lock_name,
                        os.O_RDWR | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=saved_parent_fd,
                    )
                    os.close(replacement)
                    swapped = True
                return details

            try:
                with mock.patch.object(
                    subject.os, "open", side_effect=capture_lock_open
                ), mock.patch.object(
                    subject.os, "fstat", side_effect=replace_entry_after_fstat
                ):
                    first = anchor.open_lock(lock_relative)
            finally:
                if saved_parent_fd is not None:
                    os.close(saved_parent_fd)
            second = None
            try:
                self.assertTrue(swapped)
                fcntl.flock(first, fcntl.LOCK_EX)
                second = anchor.open_lock(lock_relative)
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                if second is not None:
                    os.close(second)
                os.close(first)

    def test_argparse_failures_are_single_machine_readable_json_errors(self) -> None:
        cases = (
            ["record"],
            ["not-a-command"],
            ["candidates", "--definitely-not-an-option"],
            [
                "candidates",
                "--refresh-receipt", "receipt.json",
                "--profile", "profile.json",
                "--artifact-root", str(self.root),
                "--output", "candidates.jsonl",
                "--extraction-manifest", "extraction.json",
                "--now-ms", "not-an-integer",
            ],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    try:
                        result = subject.main(arguments)
                    except SystemExit as exc:
                        self.fail(
                            f"argument errors must return machine JSON, not SystemExit({exc.code})"
                        )
                self.assertEqual(result, 2)
                self.assertEqual(stdout.getvalue(), "")
                error = json.loads(stderr.getvalue())
                self.assertEqual(error["status"], "error")
                self.assertIsInstance(error.get("error"), str)
                self.assertTrue(error["error"])

    def test_cli_reports_commit_indeterminate_with_distinct_exit_code(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(
            subject,
            "publish_run",
            side_effect=subject.FoloCommitIndeterminate("durability uncertain", "new"),
        ), redirect_stderr(stderr):
            result = subject.main([
                "record",
                "--extraction-manifest", str(self.root / "extraction.json"),
                "--decisions", str(self.root / "decisions.jsonl"),
                "--artifact-root", str(self.root),
            ])
        self.assertEqual(result, 3)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["status"], "commit-indeterminate")
        self.assertEqual(payload["observed_status"], "new")


class WrapperRuntimeContractTests(unittest.TestCase):
    def run_wrapper_against_runtime(self, runtime: Path) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update({
            "AUTORESEARCH_FOLO_RUNTIME_DIR": str(runtime),
            "AUTORESEARCH_FOLO_PYTHON": "python3.11",
        })
        return subprocess.run(
            [str(SCRIPT_DIR / "folo-source"), "--help"],
            cwd=SCRIPT_DIR,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def assert_symlink_attack_failed_closed(
        self, completed: subprocess.CompletedProcess[str], victim: Path, sentinel: bytes
    ) -> None:
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        lines = completed.stderr.splitlines()
        self.assertEqual(len(lines), 1, "stderr must contain exactly one JSON record")
        payload = json.loads(lines[0])
        self.assertEqual(payload["status"], "error")
        self.assertIn("symbolic link", payload["error"])
        self.assertEqual((victim / "sentinel.txt").read_bytes(), sentinel)
        self.assertEqual(
            sorted(path.relative_to(victim).as_posix() for path in victim.rglob("*")),
            ["sentinel.txt"],
        )

    def test_runtime_base_symlink_fails_closed_without_mutating_victim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="autoresearch-wrapper-runtime-link-") as raw:
            root = Path(raw).resolve(strict=True)
            victim = root / "victim"
            victim.mkdir()
            sentinel = b"runtime-base-victim-must-not-change\n"
            (victim / "sentinel.txt").write_bytes(sentinel)
            runtime = root / "runtime"
            runtime.symlink_to(victim, target_is_directory=True)

            completed = self.run_wrapper_against_runtime(runtime)

            self.assert_symlink_attack_failed_closed(completed, victim, sentinel)

    def test_runtime_venv_symlink_fails_closed_without_mutating_victim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="autoresearch-wrapper-venv-link-") as raw:
            root = Path(raw).resolve(strict=True)
            runtime = root / "runtime"
            runtime.mkdir()
            victim = root / "victim"
            victim.mkdir()
            sentinel = b"venv-victim-must-not-change\n"
            (victim / "sentinel.txt").write_bytes(sentinel)
            (runtime / "venv").symlink_to(victim, target_is_directory=True)

            completed = self.run_wrapper_against_runtime(runtime)

            self.assert_symlink_attack_failed_closed(completed, victim, sentinel)

    def test_wrapper_declares_the_ed25519_verifier_and_its_install_dependencies(self) -> None:
        requirements = (SCRIPT_DIR / "requirements.txt").read_text(encoding="utf-8")
        wrapper = (SCRIPT_DIR / "folo-source").read_text(encoding="utf-8")
        self.assertRegex(
            requirements,
            r"(?m)^cryptography(?:==|\s*@\s+)",
            "the isolated wrapper runtime must install the production Ed25519 verifier",
        )
        if "--no-deps" in wrapper:
            self.assertRegex(requirements, r"(?m)^cffi(?:==|\s*@\s+)")
            self.assertRegex(requirements, r"(?m)^pycparser(?:==|\s*@\s+)")


if __name__ == "__main__":
    unittest.main()
