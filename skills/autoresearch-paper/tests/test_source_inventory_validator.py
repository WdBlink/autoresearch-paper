#!/usr/bin/env python3
"""Deterministic regressions for the source-bound bootstrap evaluator."""

from __future__ import annotations

import importlib.util
import hashlib
import json
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
        self.assertEqual(result["case_count"], 7)
        self.assertTrue(all(item["passed"] for item in result["cases"]))

    def test_executable_adapter_emits_source_bound_receipt(self) -> None:
        validator = load_module(
            "source_inventory_validator_adapter_test",
            SCRIPTS / "source_inventory_validator.py",
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.py"
            source.write_text("class Alpha:\n    pass\n")
            manifest = [{
                "path": str(source),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "symbol": "Alpha",
                "line_start": 1,
                "size_bytes": source.stat().st_size,
                "line_count": 2,
            }]
            manifest_sha = hashlib.sha256(json.dumps(
                manifest, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            preflight = root / "preflight.json"
            preflight.write_text(json.dumps({
                "verified_source_manifest": manifest,
                "verified_source_manifest_sha256": manifest_sha,
            }))
            candidate = root / "candidate.json"
            candidate.write_text(json.dumps({
                "schema_version": 1,
                "records": [{
                    "path": str(source),
                    "source_sha256": manifest[0]["sha256"],
                    "symbol": "Alpha",
                    "line_start": 1,
                    "observation": "class Alpha:",
                    "hypothesis": "Alpha may identify the source class.",
                }],
                "uncertainties_and_next_questions": [
                    "Where is Alpha instantiated?",
                ],
            }))
            receipt_path = root / "receipt.json"
            receipt = validator.validate_artifact(
                candidate, preflight, receipt_path,
            )
            self.assertEqual(receipt["result"], "pass")
            self.assertEqual(receipt["source_manifest_sha256"], manifest_sha)
            self.assertEqual(json.loads(receipt_path.read_text()), receipt)

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
