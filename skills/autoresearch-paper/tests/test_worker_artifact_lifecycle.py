from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "references" / "scripts" / "worker_artifact_lifecycle.py"
)
SPEC = importlib.util.spec_from_file_location("worker_artifact_lifecycle", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class WorkerArtifactLifecycleTests(unittest.TestCase):
    def test_conformance_suite_closes_exact_bytes_and_order(self) -> None:
        result = MODULE.run_conformance_suite()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["case_count"], 6)
        self.assertTrue(all(case["passed"] for case in result["cases"]))

    def test_controller_compute_owns_digest(self) -> None:
        content = '{"value":1}'
        self.assertEqual(
            MODULE.controller_owned_digest(content, "controller-compute"),
            MODULE.exact_utf8_sha256(content),
        )


if __name__ == "__main__":
    unittest.main()
