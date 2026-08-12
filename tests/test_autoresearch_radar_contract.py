import unittest
from pathlib import Path

from tests.skill_contract_helpers import assert_compact_skill


RADAR_DIR = Path(__file__).resolve().parents[1] / "skills" / "autoresearch-radar"


class ResearchRadarContractTests(unittest.TestCase):
    def test_radar_accepts_only_an_adapter_issued_watch_profile(self):
        body = assert_compact_skill(self, "autoresearch-radar")
        section = body.split("## Sole handoff modes", 1)[1].split(
            "## Source cycle", 1
        )[0]
        self.assertIn(
            "| Scheduled or explicit scan | `autoresearch/research-watch-profile.yaml` |",
            section,
        )
        self.assertIn("Adapter-issued", section)
        self.assertNotIn("research-brief.md", section)
        self.assertNotIn("experiment-contract.md", section)

    def test_radar_keeps_source_signal_and_adoption_state_separate(self):
        body = assert_compact_skill(self, "autoresearch-radar")
        normalized = " ".join(body.split())
        for token in (
            "Source Cursor",
            "Signal Decision Ledger",
            "Adoption Ledger",
            "Experiment owns",
        ):
            self.assertIn(token, normalized)
        self.assertIn("never marks a signal adopted", normalized)

    def test_folo_adapter_is_official_sync_then_local_read_only(self):
        body = assert_compact_skill(self, "autoresearch-radar")
        self.assertIn("folo-local-source.md", body)
        source = (RADAR_DIR / "references" / "folo-local-source.md").read_text()
        normalized = " ".join(source.split())
        for token in (
            "FOLO official UI",
            "read-only local cache snapshot",
            "subscriptions",
            "read/unread",
            "favorites",
            "stale cache",
            "stop before state advancement",
        ):
            self.assertIn(token, normalized)

    def test_candidate_decisions_use_orthogonal_research_fields(self):
        body = assert_compact_skill(self, "autoresearch-radar")
        package = (RADAR_DIR / "references" / "research-signal-package.md").read_text()
        normalized = " ".join(package.split())
        for token in (
            "relevance",
            "evidence_level",
            "contract_fit",
            "signal_type",
            "source_claim",
            "applicable_scope",
            "verification_status",
        ):
            self.assertIn(token, normalized)
        self.assertIn("one decision for every extracted candidate", body)

    def test_rss_summary_is_a_lead_not_scientific_evidence(self):
        body = assert_compact_skill(self, "autoresearch-radar")
        normalized = " ".join(body.split())
        self.assertIn("RSS summary", normalized)
        self.assertIn("lead", normalized)
        self.assertIn("primary source", normalized)
        self.assertIn("cannot satisfy", normalized)

    def test_outputs_are_verified_before_atomic_cursor_advance(self):
        body = assert_compact_skill(self, "autoresearch-radar")
        lifecycle = body.split("## Commit order", 1)[1].split("## Stop", 1)[0]
        normalized = " ".join(lifecycle.split())
        for token in (
            "candidates.jsonl",
            "decisions.jsonl",
            "manifest.json",
            "validate",
            "atomically replace",
            "sole stable commit-root pointer",
        ):
            self.assertIn(token, normalized)
        self.assertLess(normalized.index("validate"), normalized.index("atomically replace"))
        self.assertIn("zero forwarded signals", normalized)
        self.assertIn("still advances", normalized)
        self.assertIn("stale cache", normalized)
        self.assertIn("does not advance state", normalized)

    def test_radar_is_not_a_scheduler_or_scientific_stage(self):
        body = assert_compact_skill(self, "autoresearch-radar")
        boundaries = body.split("## Boundaries", 1)[1]
        normalized = " ".join(boundaries.split())
        for token in (
            "scheduler",
            "Research Brief",
            "Experiment Contract",
            "evaluator",
            "candidate",
            "Claim Boundary",
            "paper",
        ):
            self.assertIn(token, normalized)


if __name__ == "__main__":
    unittest.main()
