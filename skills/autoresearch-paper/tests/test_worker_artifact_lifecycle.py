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
        self.assertEqual(result["case_count"], 16)
        self.assertTrue(all(case["passed"] for case in result["cases"]))

    def test_continuation_requires_real_terminal_review_evidence(self) -> None:
        complete = {
            guard: True for guard in MODULE.CONTINUATION_COMPILE_GUARDS
        }
        MODULE.require_staged_transition(
            "compile_continuation", "RECORDED", "CONTRACTED", complete,
        )
        for missing in MODULE.CONTINUATION_COMPILE_GUARDS:
            incomplete = dict(complete)
            incomplete[missing] = False
            with self.assertRaisesRegex(
                MODULE.WorkerArtifactLifecycleError,
                "continuation compilation requires",
            ):
                MODULE.require_staged_transition(
                    "compile_continuation", "RECORDED", "CONTRACTED",
                    incomplete,
                )

    def test_controller_compute_owns_digest(self) -> None:
        content = '{"value":1}'
        self.assertEqual(
            MODULE.controller_owned_digest(content, "controller-compute"),
            MODULE.exact_utf8_sha256(content),
        )

    def test_worker_declared_digest_is_never_authority(self) -> None:
        content = '{"value":1}'
        with self.assertRaisesRegex(
            MODULE.WorkerArtifactLifecycleError, "literal controller-compute",
        ):
            MODULE.controller_owned_digest(
                content, MODULE.exact_utf8_sha256(content),
            )

    def test_persisted_controller_authority_replays_canonical_digest(self) -> None:
        content = '{"value":1}'
        authority = MODULE.controller_digest_authority_record(
            "artifact_1", "artifact.json", content, "controller-compute",
        )
        MODULE.validate_controller_digest_authority_record(
            "artifact_1", "artifact.json", content,
            MODULE.exact_utf8_sha256(content), authority,
        )
        with self.assertRaisesRegex(
            MODULE.WorkerArtifactLifecycleError, "authority binding mismatch",
        ):
            MODULE.validate_controller_digest_authority_record(
                "artifact_1", "artifact.json", content + "\n",
                MODULE.exact_utf8_sha256(content), authority,
            )


if __name__ == "__main__":
    unittest.main()
