#!/usr/bin/env python3
"""Bounded regression tests for the host-neutral scientific figure gate."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "references" / "scripts" / "validate-figure-artifacts.py"
SCHEMA = ROOT / "references" / "figure-artifact.schema.json"


class ScientificFigurePipelineTests(unittest.TestCase):
    @staticmethod
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def call(self, plan: Path, manifest: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                "--plan-dir",
                str(plan),
                "--manifest",
                str(manifest),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def write_fixture(self, root: Path) -> tuple[Path, Path, dict[str, object]]:
        plan = root / "plan"
        figure_dir = plan / "out" / "figures"
        source_dir = plan / "out" / "results-raw"
        state_dir = plan / "state"
        figure_dir.mkdir(parents=True)
        source_dir.mkdir(parents=True)
        state_dir.mkdir(parents=True)

        source = source_dir / "scores.csv"
        source.write_text("method,score\nbaseline,0.5\nours,0.7\n", encoding="utf-8")
        script = figure_dir / "render.py"
        script.write_text("print('frozen renderer fixture')\n", encoding="utf-8")
        vector = figure_dir / "fig-results.pdf"
        vector.write_bytes(b"%PDF-1.4\n% deterministic fixture\n%%EOF\n")
        preview = figure_dir / "fig-results.png"
        preview.write_bytes(b"\x89PNG\r\n\x1a\nfixture-preview")
        authority = state_dir / "keep-receipt.json"
        authority.write_text('{"decision":"KEEP","candidate":"canonical"}\n', encoding="utf-8")
        review = figure_dir / "fig-results.review.json"
        review.write_text(
            json.dumps({
                "schema_version": 1,
                "figure_id": "fig-results",
                "reviewed_at": "2026-07-24T16:10:00+08:00",
                "reviewer_kind": "human",
                "reviewer_identity": "human-reviewer-fixture",
                "independent_of_renderer": True,
                "decision": "PASS",
                "reviewed_outputs": [
                    {"path": "out/figures/fig-results.pdf", "sha256": self.sha(vector)},
                    {"path": "out/figures/fig-results.png", "sha256": self.sha(preview)},
                ],
            }, indent=2) + "\n",
            encoding="utf-8",
        )

        manifest: dict[str, object] = {
            "schema_version": 1,
            "figure_id": "fig-results",
            "figure_kind": "result",
            "generation": {
                "mode": "deterministic",
                "capability": "scientific-visualization",
                "capability_revision": "70a0d595e54b8d92ca54f216d4315e0ab8c7d967",
            },
            "inputs": [
                {
                    "path": "out/results-raw/scores.csv",
                    "sha256": self.sha(source),
                    "role": "source_data",
                    "purpose": "Frozen experiment result table.",
                },
                {
                    "path": "out/figures/render.py",
                    "sha256": self.sha(script),
                    "role": "render_script",
                    "purpose": "Exact local render implementation.",
                },
            ],
            "transformations": [
                {
                    "order": 0,
                    "operation": "select_columns",
                    "description": "Select method and score without changing values.",
                    "parameters": {"columns": ["method", "score"]},
                }
            ],
            "renderer": {
                "identity": "python-matplotlib",
                "version": "3.10.3",
                "source_revision": "git:0123456789abcdef",
                "command": [
                    "python3",
                    "out/figures/render.py",
                    "--input",
                    "out/results-raw/scores.csv",
                ],
                "random_seed": 0,
            },
            "outputs": [
                {
                    "path": "out/figures/fig-results.pdf",
                    "sha256": self.sha(vector),
                    "role": "manuscript",
                    "media_type": "application/pdf",
                },
                {
                    "path": "out/figures/fig-results.png",
                    "sha256": self.sha(preview),
                    "role": "preview",
                    "media_type": "image/png",
                },
            ],
            "provenance": {
                "plan_id": "plan_fixture",
                "created_at": "2026-07-24T16:00:00+08:00",
                "research_authority": {
                    "kind": "keep_receipt",
                    "path": "state/keep-receipt.json",
                    "sha256": self.sha(authority),
                },
                "claim_ids": ["claim-primary-improvement"],
            },
            "independent_review": {
                "receipt": {
                    "path": "out/figures/fig-results.review.json",
                    "sha256": self.sha(review),
                },
                "reviewer_kind": "human",
                "reviewer_identity": "human-reviewer-fixture",
                "independent_of_renderer": True,
                "decision": "PASS",
                "ai_quality_score_used_as_authority": False,
            },
        }
        manifest_path = figure_dir / "fig-results.manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return plan, manifest_path, manifest

    def rewrite(self, path: Path, manifest: dict[str, object]) -> None:
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def failure_code(self, proc: subprocess.CompletedProcess[str]) -> str:
        self.assertEqual(proc.returncode, 2, proc.stdout)
        payload = json.loads(proc.stderr)
        self.assertFalse(payload["eligible"])
        return payload["errors"][0]["code"]

    def test_valid_source_bound_vector_manifest_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan, manifest_path, _ = self.write_fixture(Path(td))
            proc = self.call(plan, manifest_path)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["eligible"])
            self.assertEqual(result["figure_id"], "fig-results")
            self.assertEqual(len(result["verified_artifacts"]), 6)

    def test_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan, manifest_path, manifest = self.write_fixture(Path(td))
            manifest["outputs"][0]["sha256"] = "0" * 64  # type: ignore[index]
            self.rewrite(manifest_path, manifest)
            self.assertEqual(self.failure_code(self.call(plan, manifest_path)), "HASH_MISMATCH")

    def test_parent_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, manifest_path, manifest = self.write_fixture(root)
            outside = root / "outside.csv"
            outside.write_text("secret\n", encoding="utf-8")
            manifest["inputs"][0]["path"] = "../outside.csv"  # type: ignore[index]
            manifest["inputs"][0]["sha256"] = self.sha(outside)  # type: ignore[index]
            self.rewrite(manifest_path, manifest)
            self.assertEqual(self.failure_code(self.call(plan, manifest_path)), "UNSAFE_PATH")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are not supported")
    def test_symlink_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, manifest_path, manifest = self.write_fixture(root)
            outside = root / "outside.csv"
            outside.write_text("secret\n", encoding="utf-8")
            link = plan / "out" / "results-raw" / "linked.csv"
            link.symlink_to(outside)
            manifest["inputs"][0]["path"] = "out/results-raw/linked.csv"  # type: ignore[index]
            manifest["inputs"][0]["sha256"] = self.sha(outside)  # type: ignore[index]
            self.rewrite(manifest_path, manifest)
            self.assertEqual(self.failure_code(self.call(plan, manifest_path)), "PATH_ESCAPE")

    def test_manifest_itself_must_be_beneath_plan_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, manifest_path, _ = self.write_fixture(root)
            outside_manifest = root / "outside.manifest.json"
            outside_manifest.write_bytes(manifest_path.read_bytes())
            self.assertEqual(self.failure_code(self.call(plan, outside_manifest)), "PATH_ESCAPE")

    def test_vector_and_preview_are_both_required(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan, manifest_path, manifest = self.write_fixture(Path(td))
            manifest["outputs"][0]["role"] = "auxiliary"  # type: ignore[index]
            self.rewrite(manifest_path, manifest)
            self.assertEqual(self.failure_code(self.call(plan, manifest_path)), "MISSING_VECTOR_OUTPUT")

        with tempfile.TemporaryDirectory() as td:
            plan, manifest_path, manifest = self.write_fixture(Path(td))
            manifest["outputs"][1]["role"] = "auxiliary"  # type: ignore[index]
            self.rewrite(manifest_path, manifest)
            self.assertEqual(self.failure_code(self.call(plan, manifest_path)), "MISSING_PREVIEW")

    def test_ai_schematic_and_ai_score_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan, manifest_path, manifest = self.write_fixture(Path(td))
            manifest["figure_kind"] = "method_schematic"
            manifest["generation"] = {
                "mode": "ai_schematic_proposal",
                "capability": "scientific-schematics",
                "capability_revision": "70a0d595e54b8d92ca54f216d4315e0ab8c7d967",
                "proposal_source": "image-model-output-42",
            }
            manifest["independent_review"]["reviewer_kind"] = "ai_model"  # type: ignore[index]
            manifest["independent_review"]["ai_quality_score_used_as_authority"] = True  # type: ignore[index]
            manifest["independent_review"]["ai_quality_score"] = 9.9  # type: ignore[index]
            self.rewrite(manifest_path, manifest)
            self.assertEqual(self.failure_code(self.call(plan, manifest_path)), "AI_PROPOSAL_ONLY")

        with tempfile.TemporaryDirectory() as td:
            plan, manifest_path, manifest = self.write_fixture(Path(td))
            manifest["independent_review"]["reviewer_kind"] = "ai_model"  # type: ignore[index]
            manifest["independent_review"]["ai_quality_score_used_as_authority"] = True  # type: ignore[index]
            manifest["independent_review"]["ai_quality_score"] = 10  # type: ignore[index]
            self.rewrite(manifest_path, manifest)
            self.assertEqual(
                self.failure_code(self.call(plan, manifest_path)),
                "AI_REVIEW_NOT_AUTHORITY",
            )

    def test_review_receipt_content_and_current_outputs_are_bound(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan, manifest_path, manifest = self.write_fixture(Path(td))
            review = plan / manifest["independent_review"]["receipt"]["path"]  # type: ignore[index]
            review.write_text("{}\n", encoding="utf-8")
            manifest["independent_review"]["receipt"]["sha256"] = self.sha(review)  # type: ignore[index]
            self.rewrite(manifest_path, manifest)
            self.assertEqual(
                self.failure_code(self.call(plan, manifest_path)),
                "SCHEMA_REQUIRED",
            )

        with tempfile.TemporaryDirectory() as td:
            plan, manifest_path, manifest = self.write_fixture(Path(td))
            vector = plan / manifest["outputs"][0]["path"]  # type: ignore[index]
            vector.write_bytes(b"%PDF-1.4\n% changed after review\n%%EOF\n")
            manifest["outputs"][0]["sha256"] = self.sha(vector)  # type: ignore[index]
            self.rewrite(manifest_path, manifest)
            self.assertEqual(
                self.failure_code(self.call(plan, manifest_path)),
                "STALE_REVIEW_RECEIPT",
            )

    def test_schematics_alias_and_unpinned_visualization_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan, manifest_path, manifest = self.write_fixture(Path(td))
            manifest["generation"]["capability"] = "scientific-schematics@70a0d595"  # type: ignore[index]
            self.rewrite(manifest_path, manifest)
            self.assertEqual(
                self.failure_code(self.call(plan, manifest_path)),
                "AI_PROPOSAL_ONLY",
            )

        with tempfile.TemporaryDirectory() as td:
            plan, manifest_path, manifest = self.write_fixture(Path(td))
            manifest["generation"]["capability_revision"] = "main"  # type: ignore[index]
            self.rewrite(manifest_path, manifest)
            self.assertEqual(
                self.failure_code(self.call(plan, manifest_path)),
                "UNPINNED_CAPABILITY",
            )

    def test_renderer_identity_and_provenance_are_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan, manifest_path, manifest = self.write_fixture(Path(td))
            del manifest["renderer"]["source_revision"]  # type: ignore[index]
            self.rewrite(manifest_path, manifest)
            self.assertEqual(self.failure_code(self.call(plan, manifest_path)), "SCHEMA_REQUIRED")

        with tempfile.TemporaryDirectory() as td:
            plan, manifest_path, manifest = self.write_fixture(Path(td))
            manifest["provenance"]["research_authority"]["kind"] = "method_spec"  # type: ignore[index]
            self.rewrite(manifest_path, manifest)
            self.assertEqual(
                self.failure_code(self.call(plan, manifest_path)),
                "INVALID_RESEARCH_AUTHORITY",
            )

    def test_method_schematic_binds_spec_without_result_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan, manifest_path, manifest = self.write_fixture(Path(td))
            method_spec = plan / "state" / "method-spec.md"
            method_spec.write_text("# Frozen method\nagent -> evaluator\n", encoding="utf-8")
            manifest["figure_kind"] = "method_schematic"
            manifest["inputs"][0] = {  # type: ignore[index]
                "path": "state/method-spec.md",
                "sha256": self.sha(method_spec),
                "role": "render_spec",
                "purpose": "Frozen method structure rendered by the local script.",
            }
            manifest["provenance"]["research_authority"] = {  # type: ignore[index]
                "kind": "method_spec",
                "path": "state/method-spec.md",
                "sha256": self.sha(method_spec),
            }
            manifest["provenance"]["claim_ids"] = []  # type: ignore[index]
            self.rewrite(manifest_path, manifest)
            proc = self.call(plan, manifest_path)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["status"], "PASS")

    def test_plan_inventory_is_nonempty_complete_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan, manifest_path, manifest = self.write_fixture(Path(td))
            inventory = plan / "state" / "figure-inventory.json"
            requirements = plan / "state" / "figure-requirements.json"
            requirements.write_text(json.dumps({
                "schema_version": 1,
                "plan_id": manifest["provenance"]["plan_id"],  # type: ignore[index]
                "tier": "arxiv",
                "expected_figure_ids": [manifest["figure_id"]],
            }, indent=2) + "\n", encoding="utf-8")
            inventory.write_text(json.dumps({
                "schema_version": 1,
                "plan_id": manifest["provenance"]["plan_id"],  # type: ignore[index]
                "required_figures": [{
                    "figure_id": manifest["figure_id"],
                    "manifest": str(manifest_path.relative_to(plan)),
                    "sha256": self.sha(manifest_path),
                }],
            }, indent=2) + "\n", encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable, str(VALIDATOR),
                    "--plan-dir", str(plan),
                    "--inventory", str(inventory),
                    "--requirements", str(requirements),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["required_figure_count"], 1)

            inventory_payload = json.loads(inventory.read_text())
            inventory_payload["required_figures"][0]["sha256"] = "0" * 64
            inventory.write_text(json.dumps(inventory_payload), encoding="utf-8")
            self.assertEqual(
                self.failure_code(subprocess.run(
                    [
                        sys.executable, str(VALIDATOR),
                        "--plan-dir", str(plan),
                        "--inventory", str(inventory),
                        "--requirements", str(requirements),
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )),
                "HASH_MISMATCH",
            )

            inventory_payload["required_figures"][0]["sha256"] = self.sha(manifest_path)
            inventory.write_text(json.dumps(inventory_payload), encoding="utf-8")
            requirements.write_text(json.dumps({
                "schema_version": 1,
                "plan_id": manifest["provenance"]["plan_id"],  # type: ignore[index]
                "tier": "conference",
                "expected_figure_ids": [
                    manifest["figure_id"],
                    "fig-results-2",
                    "fig-results-3",
                    "fig-results-4",
                ],
            }), encoding="utf-8")
            self.assertEqual(
                self.failure_code(subprocess.run(
                    [
                        sys.executable, str(VALIDATOR),
                        "--plan-dir", str(plan),
                        "--inventory", str(inventory),
                        "--requirements", str(requirements),
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )),
                "INCOMPLETE_FIGURE_INVENTORY",
            )

    def test_schema_is_offline_and_declares_required_contract(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertTrue(
            {
                "inputs",
                "outputs",
                "provenance",
                "transformations",
                "renderer",
                "independent_review",
            }.issubset(schema["required"])
        )


if __name__ == "__main__":
    unittest.main()
