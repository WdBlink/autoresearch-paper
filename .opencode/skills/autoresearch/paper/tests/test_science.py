import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "lib" / "science.py"
spec = importlib.util.spec_from_file_location("paper_science", MODULE)
science = importlib.util.module_from_spec(spec)
spec.loader.exec_module(science)


class ScienceChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.design = {
            "experiment_id": "E1", "claim_id": "C1", "hypothesis": "Lower descriptive case error",
            "independent_variable": "method", "dependent_variable": "error",
            "control_variables": ["same evaluator", "same inputs"],
            "metric": {"name": "error", "unit": "m", "direction": "lower"},
            "statistical_unit": "case", "cases": ["a", "b", "c"], "seeds": [0, 1],
            "conditions": ["baseline", "candidate"], "failure_policy": "penalty", "failure_value": 10,
            "statistics": {"estimator": "mean", "interval": "sd", "paired": True},
            "data_roles": [{"id": "dev", "role": "development", "used_for_selection": True}],
            "planned_at": "2026-11-03T00:00:00Z",
        }
        self.put("experiment/design.json", self.design)
        self.design_hash = self.hash("experiment/design.json")
        self.results = {"design": "experiment/design.json", "design_sha256": self.design_hash,
                        "started_at": "2026-11-03T01:00:00Z", "outcome": "inconclusive",
                        "reported_denominator": 12, "runs": []}
        values = {"baseline": {"a": [2, 4], "b": [4, 6], "c": [6, 8]},
                  "candidate": {"a": [1, 3], "b": [2, 4], "c": [7, 9]}}
        for condition in self.design["conditions"]:
            for case in self.design["cases"]:
                for seed in self.design["seeds"]:
                    row = {"id": f"{case}-{condition}-{seed}", "case_id": case, "seed": seed,
                           "condition": condition, "status": "completed", "value": values[condition][case][seed],
                           "raw": f"experiment/raw/{case}-{condition}-{seed}.json"}
                    self.put(row["raw"], {key: row[key] for key in ("case_id", "seed", "condition", "status", "value")})
                    self.results["runs"].append(row)
        self.put("experiment/results.json", self.results)
        self.put("experiment/summary.md", "A descriptive paired case comparison with one adverse case.\n")
        self.plan = {"experiment_design_sha256": self.design_hash}

    def put(self, relative, value):
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(value, indent=2) if not isinstance(value, str) else value)

    def hash(self, relative):
        return hashlib.sha256((self.root / relative).read_bytes()).hexdigest()

    def paths(self):
        return [path.relative_to(self.root).as_posix() for path in self.root.rglob("*") if path.is_file()]

    def experiment_packet(self):
        return {"design": "experiment/design.json", "results": "experiment/results.json",
                "summary": "experiment/summary.md", "artifacts": self.paths(), "_plan": self.plan}

    def figure_packet(self, suffix="svg"):
        rendered = science.render_statistics(self.root, "experiment/results.json", "figures/results.tex",
                                             "figures/results." + suffix)
        packet = {"design": "experiment/design.json", "results": "experiment/results.json",
                  "statistics": rendered["statistics_path"], "table": rendered["table"],
                  "figure": rendered["figure"], "trace": rendered["trace"], "caption": rendered["caption"],
                  "_plan": self.plan, "artifacts": self.paths()}
        return packet, rendered

    def writing_packet(self):
        figures, rendered = self.figure_packet()
        assertion = {"id": "A1", "claim_id": "C1", "text": "The candidate mean error was 4.333333 m.",
                     "statistics": rendered["statistics_path"], "measure": "candidate.mean",
                     "value": 13 / 3, "unit": "m", "denominator": 3,
                     "condition": "all-planned-cases", "strength": "descriptive", "kind": "numeric"}
        document = {"assertions": [assertion],
                    "limitations": [{"kind": "scope", "text": "These results describe the planned cases only."},
                                    {"kind": "small_sample", "text": "Three independent cases limit generalization."},
                                    {"kind": "adverse", "text": "The candidate regressed on case c."}],
                    "prose_review": {"problem": "Measured case error", "choice": "Paired methods",
                                     "finding": "Lower mean, one adverse case", "scope": "Three cases"},
                    "revisions": []}
        self.put("paper/assertions.json", document)
        self.put("paper/main.tex", assertion["text"] + "\n" + "\n".join(item["text"] for item in document["limitations"]))
        self.put("paper/references.bib", "@misc{fixture, title={Synthetic software fixture}}")
        packet = {"manuscript": "paper/main.tex", "assertions": "paper/assertions.json",
                  "bibliography": "paper/references.bib", "artifacts": self.paths(),
                  "_plan": self.plan, "_history": {"figures": figures}}
        return packet, document

    def test_real_records_are_paired_at_case_level(self):
        self.assertEqual([], science.validate("experiment", self.experiment_packet(), self.root))
        packet, result = self.figure_packet()
        stats = result["statistics"]
        self.assertEqual(3, stats["n_cases"])
        self.assertEqual(2, stats["seeds_per_case"])
        self.assertEqual([3, 5, 7], stats["case_values"]["baseline"])
        self.assertAlmostEqual(2.0, stats["conditions"]["baseline"]["sd"])
        self.assertAlmostEqual(13 / 3, stats["conditions"]["candidate"]["mean"])
        self.assertAlmostEqual(-2 / 3, stats["delta"]["mean"])
        self.assertEqual(["c"], stats["adverse_case_ids"])
        self.assertEqual([], science.validate("figures", packet, self.root))

    def test_svg_and_tex_contain_data_and_uncertainty_labels(self):
        packet, rendered = self.figure_packet()
        self.assertIn("5.000000", (self.root / packet["table"]).read_text())
        self.assertIn("SD", rendered["caption"])
        self.assertIn("Denominator=12", rendered["caption"])
        self.assertIn("paired independent cases", rendered["caption"])
        self.assertIn("statistics sha256", (self.root / packet["figure"]).read_text())
        self.assertEqual(rendered, science.render_statistics(self.root, "experiment/results.json",
                                                            "figures/results.tex", "figures/results.svg"))

    def test_pdf_is_recomputed_and_deterministic_when_matplotlib_is_available(self):
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("PDF requires optional Matplotlib")
        packet, _ = self.figure_packet("pdf")
        self.assertTrue((self.root / packet["figure"]).read_bytes().startswith(b"%PDF-"))
        self.assertEqual([], science.validate("figures", packet, self.root))
        damaged = (self.root / packet["figure"]).read_bytes() + b"tampered chart"
        (self.root / packet["figure"]).write_bytes(damaged)
        trace = science.strict_json(self.root, packet["trace"])
        trace["figure_sha256"] = self.hash(packet["figure"])
        self.put(packet["trace"], trace)
        self.assertIn("figure differs", science.validate("figures", packet, self.root)[0])

    def test_frozen_design_cannot_change_after_results(self):
        self.design["failure_value"] = 99
        self.put("experiment/design.json", self.design)
        self.results["design_sha256"] = self.hash("experiment/design.json")
        self.put("experiment/results.json", self.results)
        self.assertIn("frozen plan", science.validate("experiment", self.experiment_packet(), self.root)[0])

    def test_raw_record_must_match_reported_measurement(self):
        self.results["runs"][0]["value"] = 999
        self.put("experiment/results.json", self.results)
        self.assertIn("raw measurement differs", science.validate("experiment", self.experiment_packet(), self.root)[0])

    def test_missing_run_does_not_become_success_only_subset(self):
        self.results["runs"].pop()
        self.put("experiment/results.json", self.results)
        self.assertIn("all planned runs", science.validate("experiment", self.experiment_packet(), self.root)[0])

    def test_failed_and_stopped_runs_count_with_penalty_and_summary(self):
        for row, status in zip(self.results["runs"][:2], ("failed", "stopped")):
            row.update(status=status, value=None, reason="controlled fixture measurement failure", failure_kind="measurement")
            self.put(row["raw"], {key: row[key] for key in ("case_id", "seed", "condition", "status", "value", "reason", "failure_kind")})
        self.put("experiment/results.json", self.results)
        self.assertIn("summary omits", science.validate("experiment", self.experiment_packet(), self.root)[0])
        self.put("experiment/summary.md", "Known attempts: a-baseline-0 failed; a-baseline-1 stopped. Neither is discarded.")
        self.assertEqual([], science.validate("experiment", self.experiment_packet(), self.root))
        _, result = self.figure_packet()
        self.assertEqual(12, result["statistics"]["planned_runs"])
        self.assertEqual(1, result["statistics"]["failed_runs"])
        self.assertEqual(1, result["statistics"]["stopped_runs"])
        self.assertEqual(10, result["statistics"]["case_values"]["baseline"][0])

    def test_uncertain_external_outcome_requires_reconciliation(self):
        self.results["runs"][0].update(status="unknown", value=None, reason="receipt missing")
        self.put("experiment/results.json", self.results)
        self.assertIn("requires reconciliation", science.validate("experiment", self.experiment_packet(), self.root)[0])

    def test_operation_failure_cannot_become_scientific_negative(self):
        row = self.results["runs"][0]
        row.update(status="failed", value=None, reason="process did not launch", failure_kind="operation")
        self.put(row["raw"], row)
        self.put("experiment/results.json", self.results)
        self.assertIn("cannot become scientific negative", science.validate("experiment", self.experiment_packet(), self.root)[0])

    def test_wrong_denominator_is_blocked(self):
        self.results["reported_denominator"] = 11
        self.put("experiment/results.json", self.results)
        self.assertIn("denominator mismatch", science.validate("experiment", self.experiment_packet(), self.root)[0])

    def test_holdout_selection_and_seed_only_pairing_are_blocked(self):
        self.design["data_roles"][0] = {"id": "hidden", "role": "holdout", "used_for_selection": True}
        self.put("experiment/design.json", self.design)
        self.assertIn("cannot be used", science.validate("experiment", self.experiment_packet(), self.root)[0])
        self.design["data_roles"][0]["used_for_selection"] = False
        self.design["statistics"]["paired"] = False
        self.put("experiment/design.json", self.design)
        self.assertIn("paired case comparison", science.validate("experiment", self.experiment_packet(), self.root)[0])

    def test_copied_seed_names_do_not_make_other_cases_paired(self):
        self.results["runs"][-1]["case_id"] = "another-case"
        self.put("experiment/results.json", self.results)
        self.assertIn("unplanned run identity", science.validate("experiment", self.experiment_packet(), self.root)[0])

    def test_declared_uncertainty_method_is_not_silently_changed(self):
        self.design["statistics"]["interval"] = "aesthetic-error"
        self.put("experiment/design.json", self.design)
        self.assertIn("unsupported interval", science.validate("experiment", self.experiment_packet(), self.root)[0])

    def test_unknown_estimator_does_not_fall_back_to_mean(self):
        self.design["statistics"]["estimator"] = "best-success"
        self.put("experiment/design.json", self.design)
        self.assertIn("unsupported estimator", science.validate("experiment", self.experiment_packet(), self.root)[0])

    def test_plotting_values_caption_and_image_are_all_checked(self):
        packet, rendered = self.figure_packet()
        original = copy.deepcopy(rendered["statistics"])
        changed = copy.deepcopy(original)
        changed["conditions"]["candidate"]["mean"] = 1
        self.put(packet["statistics"], changed)
        self.assertIn("statistics differ", science.validate("figures", packet, self.root)[0])
        self.put(packet["statistics"], original)
        packet["caption"] = "Error bars are CI; only successful samples count."
        self.assertIn("caption changes", science.validate("figures", packet, self.root)[0])
        packet["caption"] = rendered["caption"]
        (self.root / packet["table"]).write_text("candidate & 1.000000")
        self.assertIn("table values differ", science.validate("figures", packet, self.root)[0])

    def test_evaluator_bytes_are_frozen(self):
        self.put("experiment/evaluator.txt", "metric=error")
        self.design["evaluator"] = {"path": "experiment/evaluator.txt", "sha256": self.hash("experiment/evaluator.txt")}
        self.put("experiment/design.json", self.design)
        self.design_hash = self.hash("experiment/design.json")
        self.plan["experiment_design_sha256"] = self.design_hash
        self.results["design_sha256"] = self.design_hash
        self.put("experiment/results.json", self.results)
        self.assertEqual([], science.validate("experiment", self.experiment_packet(), self.root))
        self.put("experiment/evaluator.txt", "metric=always-win")
        self.assertIn("evaluator bytes changed", science.validate("experiment", self.experiment_packet(), self.root)[0])

    def test_artifact_references_are_closed(self):
        packet = self.experiment_packet()
        packet["artifacts"].remove(self.results["runs"][0]["raw"])
        self.assertIn("unbound science evidence", science.validate("experiment", packet, self.root)[0])

    def test_symlink_cannot_escape_run_root(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (Path(outside.name) / "secret.json").write_text("{}")
        (self.root / "escape").symlink_to(outside.name, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "escapes"):
            science.strict_json(self.root, "escape/secret.json")

    def test_rewriting_output_cannot_overwrite_raw_or_existing_different_artifact(self):
        with self.assertRaisesRegex(ValueError, "raw evidence"):
            science.render_statistics(self.root, "experiment/results.json", self.results["runs"][0]["raw"], "f.svg")
        self.put("occupied.tex", "unrelated user file")
        with self.assertRaisesRegex(ValueError, "different content"):
            science.render_statistics(self.root, "experiment/results.json", "occupied.tex", "f.svg")
        self.assertEqual("unrelated user file", (self.root / "occupied.tex").read_text())

    def test_initial_draft_with_evidence_bound_numbers_passes(self):
        packet, _ = self.writing_packet()
        self.assertEqual([], science.validate("write", packet, self.root))

    def test_causal_and_significance_assertions_are_not_approved_from_descriptive_data(self):
        packet, document = self.writing_packet()
        document["assertions"][0]["kind"] = "causal"
        self.put("paper/assertions.json", document)
        self.assertIn("causal interpretation", science.validate("write", packet, self.root)[0])
        document["assertions"][0].update(kind="numeric", strength="significant")
        self.put("paper/assertions.json", document)
        self.assertIn("conclusion strength", science.validate("write", packet, self.root)[0])

    def test_adverse_cases_cannot_disappear_from_manuscript(self):
        packet, document = self.writing_packet()
        document["limitations"] = [item for item in document["limitations"] if item["kind"] != "adverse"]
        self.put("paper/assertions.json", document)
        self.assertIn("adverse paired cases", science.validate("write", packet, self.root)[0])

    def test_writing_numbers_units_denominator_and_condition_are_bound(self):
        for key, wrong in (("value", 1.0), ("unit", "cm"), ("denominator", 6), ("condition", "successful-cases")):
            with self.subTest(key=key):
                # Build separate fixtures because the statistics renderer protects existing outputs.
                packet, document = self.writing_packet()
                document["assertions"][0][key] = wrong
                self.put("paper/assertions.json", document)
                self.assertTrue(science.validate("write", packet, self.root))

    def test_prose_must_contain_bound_number_not_only_a_correct_sidecar(self):
        packet, document = self.writing_packet()
        document["assertions"][0]["text"] = "The candidate mean error was 1.000000 m."
        self.put("paper/main.tex", (self.root / "paper/main.tex").read_text().replace("4.333333", "1.000000"))
        self.put("paper/assertions.json", document)
        self.assertIn("bound numerical value", science.validate("write", packet, self.root)[0])

    def test_revision_fidelity_checks_relationships(self):
        packet, document = self.writing_packet()
        facts = {"identity": "C1", "metric": "error", "data": ["a", "b", "c"], "baseline": "baseline",
                 "denominator": 3, "unit": "m", "interval": "sd", "strength": "descriptive"}
        revision = {"before": "An earlier sentence", "after": document["assertions"][0]["text"],
                    "reason": "Put the measured comparison first", "facts_before": facts,
                    "facts_after": {**facts, "denominator": 6}}
        document["revisions"] = [revision]
        self.put("paper/assertions.json", document)
        self.assertIn("factual relationships", science.validate("write", packet, self.root)[0])
        revision["facts_after"] = facts
        self.put("paper/assertions.json", document)
        self.assertEqual([], science.validate("write", packet, self.root))

    def catalog_packet(self):
        self.put("literature/source.txt", "Synthetic software source: a paired case example.")
        self.put("literature/metadata.txt", "This is software fixture metadata, not a real publication.")
        catalog = {"question_formed_at": "2026-11-03T00:00:00Z",
                   "searches": [{"query": "paired case error", "method": "keyword", "result_ids": ["S1", "S2"]}],
                   "naive_baseline_ids": ["S1"], "hard_negative_ids": ["S2"],
                   "candidates": [
                       {"id": "S1", "title": "Synthetic software source", "url": "https://example.org/fixture",
                        "published_at": "2026-10-01T00:00:00Z", "exposure": "prospective",
                        "purpose": "Compare the independent statistical unit", "decision": "include",
                        "read_status": "read", "read_path": "literature/source.txt",
                        "verification": {"status": "primary_checked", "evidence": "literature/metadata.txt"},
                        "evidence_spans": [{"path": "literature/source.txt", "quote": "a paired case example"}]},
                       {"id": "S2", "title": "Synthetic hard negative", "url": "https://example.org/negative",
                        "published_at": "2026-10-01T00:00:00Z", "exposure": "prospective",
                        "purpose": "Topical hit with wrong statistical unit", "decision": "exclude",
                        "read_status": "registered", "exclusion_reason": "Incompatible unit"}]}
        self.put("literature/catalog.json", catalog)
        return {"catalog": "literature/catalog.json", "artifacts": self.paths()}, catalog

    def test_literature_preserves_purpose_baseline_and_hard_negative(self):
        packet, _ = self.catalog_packet()
        self.assertEqual([], science.validate("literature", packet, self.root))

    def test_literature_unknown_spans_and_prospective_postdated_sources_are_blocked(self):
        packet, catalog = self.catalog_packet()
        catalog["candidates"][0]["evidence_spans"][0]["quote"] = "invented quote"
        self.put("literature/catalog.json", catalog)
        self.assertIn("span does not match", science.validate("literature", packet, self.root)[0])
        catalog["candidates"][0]["evidence_spans"][0]["quote"] = "a paired case example"
        catalog["candidates"][0]["published_at"] = "2026-11-04T00:00:00Z"
        self.put("literature/catalog.json", catalog)
        self.assertIn("prospective inspiration", science.validate("literature", packet, self.root)[0])
        catalog["candidates"][0]["exposure"] = "retrospective"
        self.put("literature/catalog.json", catalog)
        self.assertEqual([], science.validate("literature", packet, self.root))

    def test_registered_source_is_not_read_evidence(self):
        packet, catalog = self.catalog_packet()
        catalog["candidates"][0]["read_status"] = "registered"
        self.put("literature/catalog.json", catalog)
        self.assertIn("registered source", science.validate("literature", packet, self.root)[0])

    def test_json_duplicate_keys_and_nonfinite_values_fail(self):
        self.put("duplicate.json", '{"claim": 1, "claim": 2}')
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            science.strict_json(self.root, "duplicate.json")
        self.put("nonfinite.json", '{"measurement": NaN}')
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            science.strict_json(self.root, "nonfinite.json")


if __name__ == "__main__":
    unittest.main()
