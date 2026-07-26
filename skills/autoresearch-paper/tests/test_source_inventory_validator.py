#!/usr/bin/env python3
"""Deterministic regressions for the source-bound bootstrap evaluator."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "references" / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SourceInventoryValidatorTests(unittest.TestCase):
    def test_shipped_conformance_suite_covers_positive_and_adversarial_cases(self) -> None:
        validator = load_module(
            "source_inventory_validator_test",
            SCRIPTS / "source_inventory_validator.py",
        )
        result = validator.run_conformance_suite()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["case_count"], 6)
        self.assertTrue(all(item["passed"] for item in result["cases"]))

    def test_worker_receives_the_exact_closed_content_contract(self) -> None:
        runtime = load_module("harness_runtime_contract_test", SCRIPTS / "harness-runtime.py")
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.py"
            source.write_text("class Alpha:\n    pass\n")
            declaration = {
                "artifact_id": "source_inventory",
                "content_validator": {
                    "kind": "source_inventory_v1",
                    "source_manifest": [{"path": str(source), "sha256": "0" * 64}],
                },
            }
            visible = runtime.worker_visible_content_contracts([declaration])
        self.assertEqual(len(visible), 1)
        self.assertEqual(
            visible[0]["exact_top_level_fields"],
            ["schema_version", "records", "uncertainties_and_next_questions"],
        )
        self.assertEqual(
            visible[0]["exact_record_fields"],
            [
                "path", "source_sha256", "symbol", "line_start",
                "observation", "hypothesis",
            ],
        )
        self.assertEqual(visible[0]["additional_fields"], "forbidden at every object level")

    def test_controller_enforces_byte_cap_for_normal_and_legacy_paths(self) -> None:
        runtime = load_module(
            "harness_runtime_byte_cap_test", SCRIPTS / "harness-runtime.py",
        )
        runtime.enforce_artifact_byte_cap(b"ok", {"max_bytes": 2})
        with self.assertRaisesRegex(runtime.ContractError, "declared max_bytes"):
            runtime.enforce_artifact_byte_cap(b"too large", {"max_bytes": 2})


if __name__ == "__main__":
    unittest.main()
