#!/usr/bin/env python3
"""Deterministic regressions for the source-bound bootstrap evaluator."""

from __future__ import annotations

import importlib.util
import argparse
import hashlib
import json
import subprocess
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
        self.assertEqual(result["case_count"], 14)
        self.assertTrue(all(item["passed"] for item in result["cases"]))

    def test_conformance_cli_covers_the_executable_receipt_path(self) -> None:
        completed = subprocess.run(
            [
                "python3",
                str(SCRIPTS / "source_inventory_validator.py"),
                "--conformance",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        receipt = json.loads(completed.stdout)
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["case_count"], 14)
        self.assertTrue(any(
            case["case_id"] == "cli_validate_artifact_receipt"
            and case["passed"]
            for case in receipt["cases"]
        ))

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

    def test_symbol_matching_is_token_exact_and_cli_rejects_prefix(self) -> None:
        validator_path = SCRIPTS / "source_inventory_validator.py"
        validator = load_module(
            "source_inventory_validator_symbol_test", validator_path,
        )
        self.assertTrue(validator.symbol_occurs_on_line("Alpha", "class Alpha:"))
        self.assertTrue(
            validator.symbol_occurs_on_line(
                "pkg.mod.ClassName", "register(pkg.mod.ClassName)",
            )
        )
        self.assertFalse(
            validator.symbol_occurs_on_line("Alpha", "class AlphaBeta:"),
        )
        self.assertFalse(
            validator.symbol_occurs_on_line("Alpha", "class BetaAlpha:"),
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.py"
            source.write_text("class AlphaBeta:\n    pass\n")
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
                    "observation": "class AlphaBeta:",
                    "hypothesis": "This prefix must not bind Alpha.",
                }],
                "uncertainties_and_next_questions": ["Is Alpha exact?"],
            }))
            receipt = root / "receipt.json"
            rejected = subprocess.run(
                [
                    "python3", str(validator_path),
                    "--candidate", str(candidate),
                    "--preflight", str(preflight),
                    "--receipt", str(receipt),
                ],
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("symbol citation is not exact", rejected.stderr)
            self.assertFalse(receipt.exists())

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

    def test_construction_contract_freezes_hypotheses_questions_and_bytes(self) -> None:
        validator = load_module(
            "source_inventory_construction_test",
            SCRIPTS / "source_inventory_validator.py",
        )
        payload = {
            "schema_version": 1,
            "records": [{
                "path": "/tmp/source.py",
                "source_sha256": "1" * 64,
                "symbol": "Alpha",
                "line_start": 1,
                "observation": "class Alpha:",
                "hypothesis": "Alpha may own state.",
            }],
            "uncertainties_and_next_questions": [
                "Where is Alpha instantiated?",
            ],
        }
        content = json.dumps(payload, ensure_ascii=False)
        contract = {
            "schema_version": 1,
            "contract_id": "construction_v1",
            "record_construction": [{
                field: payload["records"][0][field]
                for field in (
                    "path", "source_sha256", "symbol", "line_start",
                    "hypothesis",
                )
            }],
            "uncertainties_and_next_questions": payload[
                "uncertainties_and_next_questions"
            ],
            "expected_content_sha256": hashlib.sha256(
                content.encode("utf-8"),
            ).hexdigest(),
        }
        validator.validate_source_inventory_construction(content, contract)
        changed = json.loads(content)
        changed["uncertainties_and_next_questions"] = ["Another question?"]
        with self.assertRaisesRegex(
            validator.SourceInventoryValidationError,
            "questions changed",
        ):
            validator.validate_source_inventory_construction(
                json.dumps(changed, ensure_ascii=False), contract,
            )

    def test_declared_output_preserves_source_citation_bindings(self) -> None:
        runtime = load_module("harness_runtime_manifest_test", SCRIPTS / "harness-runtime.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            source = root / "source.py"
            source.write_text("class Alpha: pass\n")
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            declaration = {
                "artifact_id": "source_inventory",
                "path": str(root / "candidate.json"),
                "content_field": "content",
                "max_bytes": 1000,
                "capability": {"class": "research-intermediate"},
                "content_validator": {
                    "kind": "source_inventory_v1",
                    "source_manifest": [{
                        "path": str(source),
                        "sha256": source_sha,
                        "symbol": "Alpha",
                        "line_start": 1,
                    }],
                },
            }
            normalized = runtime.normalize_declared_output(root, declaration)
            self.assertEqual(
                normalized["content_validator"]["source_manifest"],
                declaration["content_validator"]["source_manifest"],
            )

            broken = json.loads(json.dumps(declaration))
            broken["content_validator"]["source_manifest"] = [{
                "path": str(source), "sha256": source_sha, "purpose": "source",
            }]
            with self.assertRaisesRegex(
                runtime.ContractError, "must bind exactly path, sha256, symbol",
            ):
                runtime.normalize_declared_output(root, broken)

            for field, value in (
                ("size_bytes", float(len(source.read_bytes()))),
                ("line_count", True),
            ):
                typed = json.loads(json.dumps(declaration))
                typed["content_validator"]["source_manifest"][0][field] = value
                with self.assertRaisesRegex(
                    runtime.ContractError, "size metadata changed",
                ):
                    runtime.normalize_declared_output(root, typed)

            real_parent = root / "real"
            real_parent.mkdir()
            linked_parent = root / "linked"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            linked_source = real_parent / "source.py"
            linked_source.write_text("class Linked:\n    pass\n")
            linked_sha = hashlib.sha256(linked_source.read_bytes()).hexdigest()
            linked = json.loads(json.dumps(declaration))
            linked["content_validator"]["source_manifest"] = [{
                "path": str(linked_parent / "source.py"),
                "sha256": linked_sha,
                "symbol": "Linked",
                "line_start": 1,
            }]
            with self.assertRaisesRegex(
                runtime.ContractError, "must not traverse a symlink",
            ):
                runtime.normalize_declared_output(root, linked)

    def test_controller_enforces_byte_cap_for_normal_and_legacy_paths(self) -> None:
        runtime = load_module(
            "harness_runtime_byte_cap_test", SCRIPTS / "harness-runtime.py",
        )
        runtime.enforce_artifact_byte_cap(b"ok", {"max_bytes": 2})
        with self.assertRaisesRegex(runtime.ContractError, "declared max_bytes"):
            runtime.enforce_artifact_byte_cap(b"too large", {"max_bytes": 2})

    def test_runtime_attests_a_real_positive_worker_fixture(self) -> None:
        runtime = load_module(
            "harness_runtime_worker_attestation_test",
            SCRIPTS / "harness-runtime.py",
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / "resource_manifest.json").write_text(
                json.dumps({"plan_id": "plan_attestation"}),
            )
            source = root / "source.py"
            source.write_text("class Alpha:\n    pass\n")
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            candidate_path = root / "candidate.json"
            report_path = root / "report.md"
            declarations = [
                {
                    "artifact_id": "source_inventory",
                    "path": str(candidate_path),
                    "content_field": "content",
                    "max_bytes": 4096,
                    "capability": {"class": "research-intermediate"},
                    "content_validator": {
                        "kind": "source_inventory_v1",
                        "source_manifest": [{
                            "path": str(source),
                            "sha256": source_sha,
                            "symbol": "Alpha",
                            "line_start": 1,
                        }],
                    },
                },
                {
                    "artifact_id": "stage_report",
                    "path": str(report_path),
                    "content_field": "content",
                    "max_bytes": 4096,
                    "capability": {"class": "research-intermediate"},
                },
            ]
            contract = {
                "schema_version": 1,
                "task_id": "attest_source_inventory",
                "artifact_outputs": declarations,
                "output_schema": runtime.exact_worker_artifact_output_schema(
                    declarations,
                ),
            }
            contract_path = root / "task-contract.json"
            contract_path.write_text(json.dumps(contract))
            inventory = json.dumps({
                "schema_version": 1,
                "records": [{
                    "path": str(source),
                    "source_sha256": source_sha,
                    "symbol": "Alpha",
                    "line_start": 1,
                    "observation": "class Alpha:",
                    "hypothesis": "Alpha is the bounded source under review.",
                }],
                "uncertainties_and_next_questions": [
                    "Where is Alpha instantiated?",
                ],
            })
            response_path = root / "valid-response.json"
            response_path.write_text(json.dumps({"artifacts": [
                {
                    "artifact_id": "source_inventory",
                    "path": str(candidate_path),
                    "content": inventory,
                    "sha256": "controller-compute",
                },
                {
                    "artifact_id": "stage_report",
                    "path": str(report_path),
                    "content": "Bounded source inventory complete.",
                    "sha256": "controller-compute",
                },
            ]}))
            contract_path.chmod(0o444)
            response_path.chmod(0o444)
            external = root / "external"
            external.mkdir()
            linked = root / "linked"
            linked.symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(
                runtime.ContractError, "symlink parent",
            ):
                runtime.command_attest_worker_output_conformance(
                    argparse.Namespace(
                        plan_dir=str(root),
                        task_contract=str(contract_path),
                        valid_response=str(response_path),
                        output=str(linked / "escaped-conformance.json"),
                    ),
                )
            self.assertFalse((external / "escaped-conformance.json").exists())
            escaped_name = f"escaped-{root.name}.json"
            traversal = root / "nested" / ".." / ".." / escaped_name
            with self.assertRaisesRegex(
                runtime.ContractError, "must be plan-owned",
            ):
                runtime.command_attest_worker_output_conformance(
                    argparse.Namespace(
                        plan_dir=str(root),
                        task_contract=str(contract_path),
                        valid_response=str(response_path),
                        output=str(traversal),
                    ),
                )
            self.assertFalse(root.parent.joinpath(escaped_name).exists())
            receipt_path = root / "worker-conformance.json"
            result = runtime.command_attest_worker_output_conformance(
                argparse.Namespace(
                    plan_dir=str(root),
                    task_contract=str(contract_path),
                    valid_response=str(response_path),
                    output=str(receipt_path),
                ),
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["case_count"], 8)
            self.assertTrue(all(case["passed"] for case in result["cases"]))
            self.assertEqual(receipt_path.stat().st_mode & 0o777, 0o444)

    def test_runtime_rejects_placeholder_positive_worker_fixture(self) -> None:
        runtime = load_module(
            "harness_runtime_placeholder_attestation_test",
            SCRIPTS / "harness-runtime.py",
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / "resource_manifest.json").write_text(
                json.dumps({"plan_id": "plan_placeholder"}),
            )
            source = root / "source.py"
            source.write_text("class Alpha:\n    pass\n")
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            declaration = {
                "artifact_id": "source_inventory",
                "path": str(root / "candidate.json"),
                "content_field": "content",
                "max_bytes": 4096,
                "capability": {"class": "research-intermediate"},
                "content_validator": {
                    "kind": "source_inventory_v1",
                    "source_manifest": [{
                        "path": str(source),
                        "sha256": source_sha,
                        "symbol": "Alpha",
                        "line_start": 1,
                    }],
                },
            }
            contract = {
                "schema_version": 1,
                "task_id": "reject_placeholder",
                "artifact_outputs": [declaration],
                "output_schema": runtime.exact_worker_artifact_output_schema(
                    [declaration],
                ),
            }
            contract_path = root / "task-contract.json"
            response_path = root / "valid-response.json"
            contract_path.write_text(json.dumps(contract))
            response_path.write_text(json.dumps({"artifacts": [{
                "artifact_id": "source_inventory",
                "path": declaration["path"],
                "content": "{}",
                "sha256": "controller-compute",
            }]}))
            contract_path.chmod(0o444)
            response_path.chmod(0o444)
            receipt_path = root / "worker-conformance.json"
            with self.assertRaises(runtime.ContractError):
                runtime.command_attest_worker_output_conformance(
                    argparse.Namespace(
                        plan_dir=str(root),
                        task_contract=str(contract_path),
                        valid_response=str(response_path),
                        output=str(receipt_path),
                    ),
                )
            self.assertFalse(receipt_path.exists())


if __name__ == "__main__":
    unittest.main()
