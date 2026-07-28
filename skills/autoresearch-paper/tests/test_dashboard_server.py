#!/usr/bin/env python3
"""Security and read-only contracts for the compiled local Dashboard."""

from __future__ import annotations

import hashlib
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "references" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from dashboard_server import DashboardError, make_dashboard_server


class DashboardServerContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.plan = self.root / "plan"
        (self.plan / "state" / "staged_research" / "v1").mkdir(parents=True)
        (self.plan / "state" / "research-dossier.md").write_text(
            "# Research dossier\n\nProjection only.\n",
        )
        self.staged = self.plan / "state" / "staged_research" / "v1" / "state.json"
        self.staged.write_text(json.dumps({"state": "CONTRACTED"}))
        self.log = self.plan / "logs" / "retry.stdout"
        self.log.parent.mkdir()
        self.log.write_text("bounded log evidence\n")
        self.assets = ROOT / "references" / "dashboard"
        self.raw = self.snapshot()
        self.server = make_dashboard_server(
            host="127.0.0.1",
            port=0,
            plan_dir=self.plan,
            assets_dir=self.assets,
            snapshot_provider=lambda: self.raw,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def snapshot(self) -> dict:
        staged_sha = hashlib.sha256(self.staged.read_bytes()).hexdigest()
        log_sha = hashlib.sha256(self.log.read_bytes()).hexdigest()
        absent = {"path": None, "exists": False, "size_bytes": None, "sha256": None}
        return {
            "ok": True,
            "schema_version": 1,
            "plan_id": "plan_dashboard_test",
            "observed_at": "2026-07-28T13:19:29Z",
            "observation_only": True,
            "canonical": {
                "controller": absent,
                "controller_status": None,
                "staged_state": {
                    "path": str(self.staged), "exists": True,
                    "size_bytes": self.staged.stat().st_size, "sha256": staged_sha,
                },
                "staged_status": "CONTRACTED",
                "durable_head": absent,
                "durable_projection": absent,
            },
            "schedulers": [{
                "kind": "frontier_retry_trigger",
                "present": True,
                "active": True,
                "label": "com.autoresearch-paper.test",
                "loaded": True,
                "state_matches_scheduler": True,
                "receipt": absent,
                "stdout": {
                    "path": str(self.log), "exists": True,
                    "size_bytes": self.log.stat().st_size, "sha256": log_sha,
                },
                "stderr": absent,
                "current": {"generation": 1, "secret": "must-not-escape"},
            }],
            "workers": [],
            "mismatches": [],
            "shutdown": None,
            "declared_resources": [{
                "kind": "sessions", "name": "bounded-session",
                "credential": "must-not-escape",
            }],
        }

    def request(self, method: str, path: str, *, host: str = "127.0.0.1"):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.putrequest(method, path, skip_host=True)
        connection.putheader("Host", host)
        connection.endheaders()
        response = connection.getresponse()
        body = response.read()
        headers = dict(response.getheaders())
        connection.close()
        return response.status, headers, body

    def digest_plan(self) -> dict[str, str]:
        return {
            str(path.relative_to(self.plan)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.plan.rglob("*") if path.is_file()
        }

    def test_snapshot_and_head_are_safe_and_non_mutating(self) -> None:
        before = self.digest_plan()
        status, headers, body = self.request("GET", "/api/snapshot")
        self.assertEqual(status, 200)
        value = json.loads(body)
        self.assertTrue(value["observation_only"])
        self.assertEqual(value["canonical"]["staged_status"], "CONTRACTED")
        self.assertEqual(value["canonical"]["staged_state"]["relative_path"], "state/staged_research/v1/state.json")
        serialized = body.decode()
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("must-not-escape", serialized)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        head_status, _, head_body = self.request("HEAD", "/api/snapshot")
        self.assertEqual(head_status, 200)
        self.assertEqual(head_body, b"")
        for _ in range(3):
            self.assertEqual(self.request("GET", "/api/snapshot")[0], 200)
        self.assertEqual(before, self.digest_plan())

    def test_bound_log_and_dossier_are_bounded_observations(self) -> None:
        snapshot = json.loads(self.request("GET", "/api/snapshot")[2])
        log_path = snapshot["schedulers"][0]["stdout"]["api_path"]
        status, headers, body = self.request("GET", log_path)
        self.assertEqual(status, 200)
        self.assertEqual(body, self.log.read_bytes())
        self.assertEqual(headers["X-Log-Truncated"], "false")
        status, _, body = self.request("GET", "/api/dossier")
        dossier = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(dossier["projection"])
        self.assertFalse(dossier["transition_authority"])

    def test_multiple_same_kind_schedulers_keep_distinct_log_bindings(self) -> None:
        second_log = self.plan / "logs" / "second.stdout"
        second_log.write_text("second scheduler\n")
        second = json.loads(json.dumps(self.raw["schedulers"][0]))
        second["label"] = "com.autoresearch-paper.second"
        second["stdout"] = {
            "path": str(second_log), "exists": True,
            "size_bytes": second_log.stat().st_size,
            "sha256": hashlib.sha256(second_log.read_bytes()).hexdigest(),
        }
        self.raw["schedulers"].append(second)
        snapshot = json.loads(self.request("GET", "/api/snapshot")[2])
        first_path = snapshot["schedulers"][0]["stdout"]["api_path"]
        second_path = snapshot["schedulers"][1]["stdout"]["api_path"]
        self.assertNotEqual(first_path, second_path)
        self.assertEqual(self.request("GET", first_path)[2], self.log.read_bytes())
        self.assertEqual(self.request("GET", second_path)[2], second_log.read_bytes())

    def test_methods_hosts_traversal_and_unbound_logs_fail_closed(self) -> None:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertEqual(self.request(method, "/api/snapshot")[0], 405)
        self.assertEqual(self.request("GET", "/api/snapshot", host="evil.example")[0], 400)
        self.assertEqual(self.request("GET", "/%2e%2e/secret")[0], 400)
        self.assertEqual(self.request("GET", "/api/logs/" + "0" * 32)[0], 404)

    def test_compiled_assets_are_local_and_loopback_is_enforced(self) -> None:
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b'id="root"', body)
        self.assertEqual(headers["Cache-Control"], "no-store")
        with self.assertRaises(DashboardError):
            make_dashboard_server(
                host="0.0.0.0", port=0, plan_dir=self.plan,
                assets_dir=self.assets, snapshot_provider=lambda: self.raw,
            )
        with self.assertRaises(DashboardError):
            make_dashboard_server(
                host="localhost", port=0, plan_dir=self.plan,
                assets_dir=self.assets, snapshot_provider=lambda: self.raw,
            )


if __name__ == "__main__":
    unittest.main()
