#!/usr/bin/env python3
"""Deterministic, source-bound validator for bootstrap inventory artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


VALIDATOR_ID = "source_inventory_v1"
VALIDATOR_VERSION = "source-inventory-validator/7"
SYMBOL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$")


class SourceInventoryValidationError(ValueError):
    pass


def symbol_occurs_on_line(symbol: str, line: str) -> bool:
    """Match one complete identifier or dotted identifier on a source line."""
    if SYMBOL_RE.fullmatch(symbol) is None:
        return False
    return re.search(
        rf"(?<![A-Za-z0-9_.]){re.escape(symbol)}(?![A-Za-z0-9_.])",
        line,
    ) is not None


def _strict_json_loads(content: str) -> Any:
    def reject_constant(value: str) -> None:
        raise SourceInventoryValidationError(
            f"non-finite JSON constant is forbidden: {value}"
        )

    try:
        return json.loads(content, parse_constant=reject_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SourceInventoryValidationError(
            f"source inventory content is not strict JSON: {exc}"
        ) from exc


def validate_source_inventory(
    content: str,
    source_manifest: list[dict[str, Any]],
) -> None:
    inventory = _strict_json_loads(content)
    if not isinstance(inventory, dict) or set(inventory) != {
        "schema_version", "records", "uncertainties_and_next_questions",
    }:
        raise SourceInventoryValidationError(
            "source inventory has an invalid closed shape"
        )
    records = inventory.get("records")
    questions = inventory.get("uncertainties_and_next_questions")
    if (
        isinstance(inventory.get("schema_version"), bool)
        or not isinstance(inventory.get("schema_version"), int)
        or inventory.get("schema_version") != 1
        or not isinstance(records, list)
        or len(records) != len(source_manifest)
        or not isinstance(questions, list)
        or not 1 <= len(questions) <= 10
        or any(
            not isinstance(item, str)
            or not item.strip()
            or len(item) > 500
            for item in questions
        )
    ):
        raise SourceInventoryValidationError(
            "source inventory cardinality or questions are invalid"
        )
    for index, (record, source) in enumerate(zip(records, source_manifest)):
        if (
            not isinstance(source, dict)
            or not {"path", "sha256", "symbol", "line_start"} <= set(source)
            or set(source) - {
                "path", "sha256", "symbol", "line_start",
                "size_bytes", "line_count",
            }
        ):
            raise SourceInventoryValidationError(
                f"source manifest entry {index} has an invalid closed shape"
            )
        required = {
            "path", "source_sha256", "symbol", "line_start",
            "observation", "hypothesis",
        }
        if not isinstance(record, dict) or set(record) != required:
            raise SourceInventoryValidationError(
                f"source inventory record {index} has an invalid closed shape"
            )
        if (
            record.get("path") != source["path"]
            or record.get("source_sha256") != source["sha256"]
            or record.get("symbol") != source["symbol"]
            or record.get("line_start") != source["line_start"]
        ):
            raise SourceInventoryValidationError(
                f"source inventory record {index} identity mismatch"
            )
        symbol = record.get("symbol")
        line_start = record.get("line_start")
        observation = record.get("observation")
        hypothesis = record.get("hypothesis")
        if (
            not isinstance(symbol, str)
            or SYMBOL_RE.fullmatch(symbol) is None
            or isinstance(line_start, bool)
            or not isinstance(line_start, int)
            or line_start < 1
            or not isinstance(observation, str)
            or not observation.strip()
            or len(observation) > 1000
            or not isinstance(hypothesis, str)
            or not hypothesis.strip()
            or len(hypothesis) > 1000
        ):
            raise SourceInventoryValidationError(
                f"source inventory record {index} is incomplete or unbounded"
            )
        source_path = Path(source["path"])
        if source_path.is_symlink() or not source_path.is_file():
            raise SourceInventoryValidationError(
                f"source inventory record {index} source is unavailable"
            )
        source_bytes = source_path.read_bytes()
        if hashlib.sha256(source_bytes).hexdigest() != source["sha256"]:
            raise SourceInventoryValidationError(
                f"source inventory record {index} source hash changed"
            )
        lines = source_bytes.decode("utf-8").splitlines()
        if line_start > len(lines):
            raise SourceInventoryValidationError(
                f"source inventory record {index} line citation is out of range"
            )
        cited_line = lines[line_start - 1]
        if not symbol_occurs_on_line(symbol, cited_line):
            raise SourceInventoryValidationError(
                f"source inventory record {index} symbol citation is not exact"
            )
        if observation != cited_line.strip():
            raise SourceInventoryValidationError(
                f"source inventory record {index} observation is not the exact "
                "trimmed source line"
            )


def validate_source_inventory_construction(
    content: str, construction_contract: dict[str, Any],
) -> None:
    """Bind free-text hypotheses/questions and exact bytes to a frozen contract."""
    fields = {
        "schema_version", "contract_id", "record_construction",
        "uncertainties_and_next_questions", "expected_content_sha256",
    }
    if (
        not isinstance(construction_contract, dict)
        or set(construction_contract) != fields
        or construction_contract.get("schema_version") != 1
        or not isinstance(construction_contract.get("contract_id"), str)
        or not construction_contract["contract_id"]
        or not isinstance(
            construction_contract.get("record_construction"), list,
        )
        or not isinstance(
            construction_contract.get("uncertainties_and_next_questions"),
            list,
        )
        or not re.fullmatch(
            r"[0-9a-f]{64}",
            str(construction_contract.get("expected_content_sha256", "")),
        )
    ):
        raise SourceInventoryValidationError(
            "source inventory construction contract has an invalid closed shape"
        )
    inventory = _strict_json_loads(content)
    expected_records = construction_contract["record_construction"]
    actual_records = inventory.get("records") if isinstance(inventory, dict) else None
    if not isinstance(actual_records, list) or len(actual_records) != len(
        expected_records,
    ):
        raise SourceInventoryValidationError(
            "source inventory construction record cardinality changed"
        )
    bound_fields = {
        "path", "source_sha256", "symbol", "line_start", "hypothesis",
    }
    for index, (actual, expected) in enumerate(
        zip(actual_records, expected_records),
    ):
        if (
            not isinstance(expected, dict)
            or set(expected) != bound_fields
            or not isinstance(actual, dict)
            or any(actual.get(field) != expected[field] for field in bound_fields)
        ):
            raise SourceInventoryValidationError(
                f"source inventory construction record {index} changed"
            )
    if inventory.get(
        "uncertainties_and_next_questions",
    ) != construction_contract["uncertainties_and_next_questions"]:
        raise SourceInventoryValidationError(
            "source inventory construction questions changed"
        )
    if hashlib.sha256(content.encode("utf-8")).hexdigest() != (
        construction_contract["expected_content_sha256"]
    ):
        raise SourceInventoryValidationError(
            "source inventory exact constructed bytes changed"
        )


def run_conformance_suite() -> dict[str, Any]:
    """Exercise positive and adversarial cases against the shipped validator."""
    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "source.py"
        source_path.write_text("class Alpha:\n    value = 3\n")
        source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
        manifest = [{
            "path": str(source_path),
            "sha256": source_sha,
            "symbol": "Alpha",
            "line_start": 1,
        }]
        valid = {
            "schema_version": 1,
            "records": [{
                "path": str(source_path),
                "source_sha256": source_sha,
                "symbol": "Alpha",
                "line_start": 1,
                "observation": "class Alpha:",
                "hypothesis": "Alpha may own configuration state.",
            }],
            "uncertainties_and_next_questions": ["Where is Alpha instantiated?"],
        }
        dotted_path = Path(temp_dir) / "dotted.py"
        dotted_path.write_text("register(pkg.mod.ClassName)\n")
        dotted_sha = hashlib.sha256(dotted_path.read_bytes()).hexdigest()
        dotted_manifest = [{
            "path": str(dotted_path), "sha256": dotted_sha,
            "symbol": "pkg.mod.ClassName", "line_start": 1,
        }]
        dotted = {
            "schema_version": 1,
            "records": [{
                "path": str(dotted_path), "source_sha256": dotted_sha,
                "symbol": "pkg.mod.ClassName", "line_start": 1,
                "observation": "register(pkg.mod.ClassName)",
                "hypothesis": "The dotted identifier may be registered here.",
            }],
            "uncertainties_and_next_questions": ["Who consumes the registry?"],
        }
        substring_path = Path(temp_dir) / "substring.py"
        substring_path.write_text("class AlphaBeta:\nclass BetaAlpha:\n")
        substring_sha = hashlib.sha256(substring_path.read_bytes()).hexdigest()
        prefix_manifest = [{
            "path": str(substring_path), "sha256": substring_sha,
            "symbol": "Alpha", "line_start": 1,
        }]
        suffix_manifest = [{
            "path": str(substring_path), "sha256": substring_sha,
            "symbol": "Alpha", "line_start": 2,
        }]
        prefix = {
            "schema_version": 1,
            "records": [{
                "path": str(substring_path), "source_sha256": substring_sha,
                "symbol": "Alpha", "line_start": 1,
                "observation": "class AlphaBeta:",
                "hypothesis": "A prefix must not bind the Alpha identifier.",
            }],
            "uncertainties_and_next_questions": ["Is Alpha an exact symbol?"],
        }
        suffix = {
            **prefix,
            "records": [{
                **prefix["records"][0],
                "line_start": 2, "observation": "class BetaAlpha:",
            }],
        }
        cases: list[
            tuple[str, dict[str, Any], list[dict[str, Any]], bool]
        ] = [
            ("valid_grounded_record", valid, manifest, True),
            ("valid_dotted_symbol", dotted, dotted_manifest, True),
            ("boolean_schema_version", {**valid, "schema_version": True}, manifest, False),
            ("symbol_prefix_collision", prefix, prefix_manifest, False),
            ("symbol_suffix_collision", suffix, suffix_manifest, False),
            ("wrong_cardinality", {**valid, "records": []}, manifest, False),
            (
                "extra_record_field",
                {**valid, "records": [{**valid["records"][0], "extra": "x"}]},
                manifest,
                False,
            ),
            (
                "wrong_source_hash",
                {**valid, "records": [{
                    **valid["records"][0], "source_sha256": "0" * 64,
                }]},
                manifest,
                False,
            ),
            (
                "wrong_line",
                {**valid, "records": [{**valid["records"][0], "line_start": 2}]},
                manifest,
                False,
            ),
            (
                "wrong_symbol",
                {**valid, "records": [{
                    **valid["records"][0], "symbol": "value",
                }]},
                manifest,
                False,
            ),
            (
                "ungrounded_observation",
                {**valid, "records": [{
                    **valid["records"][0],
                    "observation": "Alpha definitely controls training.",
                }]},
                manifest,
                False,
            ),
        ]
        results = []
        for case_id, payload, case_manifest, should_accept in cases:
            accepted = True
            try:
                validate_source_inventory(
                    json.dumps(payload, ensure_ascii=False), case_manifest,
                )
            except SourceInventoryValidationError:
                accepted = False
            results.append({
                "case_id": case_id,
                "expected": "accept" if should_accept else "reject",
                "observed": "accept" if accepted else "reject",
                "passed": accepted is should_accept,
            })
        preflight_path = Path(temp_dir) / "preflight.json"
        candidate_path = Path(temp_dir) / "candidate.json"
        receipt_path = Path(temp_dir) / "receipt.json"
        manifest_sha = hashlib.sha256(json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        preflight_path.write_text(json.dumps({
            "verified_source_manifest": manifest,
            "verified_source_manifest_sha256": manifest_sha,
        }), encoding="utf-8")
        candidate_path.write_text(
            json.dumps(valid, ensure_ascii=False), encoding="utf-8",
        )
        cli_passed = False
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--candidate", str(candidate_path),
                    "--preflight", str(preflight_path),
                    "--receipt", str(receipt_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            stdout_receipt = json.loads(completed.stdout)
            disk_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            cli_passed = (
                completed.returncode == 0
                and stdout_receipt == disk_receipt
                and disk_receipt.get("result") == "pass"
                and disk_receipt.get("validator_version") == VALIDATOR_VERSION
                and disk_receipt.get("source_manifest_sha256") == manifest_sha
                and disk_receipt.get("candidate_sha256")
                    == hashlib.sha256(candidate_path.read_bytes()).hexdigest()
                and disk_receipt.get("preflight_sha256")
                    == hashlib.sha256(preflight_path.read_bytes()).hexdigest()
            )
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            cli_passed = False
        results.append({
            "case_id": "cli_validate_artifact_receipt",
            "expected": "accept",
            "observed": "accept" if cli_passed else "reject",
            "passed": cli_passed,
        })
        valid_content = json.dumps(valid, ensure_ascii=False)
        construction = {
            "schema_version": 1,
            "contract_id": "source_inventory_construction_v1",
            "record_construction": [{
                field: valid["records"][0][field]
                for field in (
                    "path", "source_sha256", "symbol", "line_start",
                    "hypothesis",
                )
            }],
            "uncertainties_and_next_questions": valid[
                "uncertainties_and_next_questions"
            ],
            "expected_content_sha256": hashlib.sha256(
                valid_content.encode("utf-8"),
            ).hexdigest(),
        }
        try:
            validate_source_inventory_construction(valid_content, construction)
        except SourceInventoryValidationError:
            construction_accepts = False
        else:
            construction_accepts = True
        results.append({
            "case_id": "construction_contract_accepts_exact_bytes",
            "expected": "accept",
            "observed": "accept" if construction_accepts else "reject",
            "passed": construction_accepts,
        })
        changed = json.loads(valid_content)
        changed["records"][0]["hypothesis"] = "A different hypothesis."
        try:
            validate_source_inventory_construction(
                json.dumps(changed, ensure_ascii=False), construction,
            )
        except SourceInventoryValidationError:
            construction_rejects = True
        else:
            construction_rejects = False
        results.append({
            "case_id": "construction_contract_rejects_changed_hypothesis",
            "expected": "reject",
            "observed": "reject" if construction_rejects else "accept",
            "passed": construction_rejects,
        })
        if not all(item["passed"] for item in results):
            raise SourceInventoryValidationError(
                "source inventory conformance suite failed"
            )
        return {
            "validator_id": VALIDATOR_ID,
            "validator_version": VALIDATOR_VERSION,
            "case_count": len(results),
            "cases": results,
            "status": "PASS",
        }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_artifact(
    candidate_path: Path, preflight_path: Path, receipt_path: Path,
) -> dict[str, Any]:
    """Validate one candidate against the Controller-verified source manifest."""
    preflight = _strict_json_loads(preflight_path.read_text(encoding="utf-8"))
    if not isinstance(preflight, dict):
        raise SourceInventoryValidationError("preflight must be a JSON object")
    source_manifest = preflight.get("verified_source_manifest")
    expected_manifest_sha = preflight.get("verified_source_manifest_sha256")
    if (
        not isinstance(source_manifest, list)
        or not source_manifest
        or expected_manifest_sha != hashlib.sha256(
            json.dumps(
                source_manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    ):
        raise SourceInventoryValidationError(
            "preflight source-manifest identity is missing or changed"
        )
    content = candidate_path.read_text(encoding="utf-8")
    validate_source_inventory(content, source_manifest)
    receipt = {
        "schema_version": 1,
        "validator_id": VALIDATOR_ID,
        "validator_version": VALIDATOR_VERSION,
        "candidate_path": str(candidate_path.resolve()),
        "candidate_sha256": _sha256_file(candidate_path),
        "preflight_path": str(preflight_path.resolve()),
        "preflight_sha256": _sha256_file(preflight_path),
        "source_manifest_sha256": expected_manifest_sha,
        "record_count": len(source_manifest),
        "result": "pass",
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a frozen source inventory against canonical preflight",
    )
    parser.add_argument("--conformance", action="store_true")
    parser.add_argument("--candidate")
    parser.add_argument("--preflight")
    parser.add_argument("--receipt")
    args = parser.parse_args()
    artifact_args = (args.candidate, args.preflight, args.receipt)
    if args.conformance:
        if any(artifact_args):
            parser.error("--conformance cannot be combined with artifact arguments")
        print(json.dumps(run_conformance_suite(), ensure_ascii=False, sort_keys=True))
        return 0
    if not all(artifact_args):
        parser.error("--candidate, --preflight, and --receipt are required")
    try:
        receipt = validate_artifact(
            Path(args.candidate).resolve(),
            Path(args.preflight).resolve(),
            Path(args.receipt).resolve(),
        )
    except (OSError, UnicodeError, SourceInventoryValidationError) as exc:
        parser.error(str(exc))
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
