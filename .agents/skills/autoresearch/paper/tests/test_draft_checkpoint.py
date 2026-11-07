"""Draft preparation checkpoints preserve approval and evidence boundaries."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.runtime import Controller, Refusal, digest
from run_fixture import FixturePaused, make_brief, put, run


class DraftCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ctl = Controller(self.root)

    def initialize(self):
        brief = make_brief()
        brief.update(contract_status='draft', venue='undecided', deliverable_plan=[])
        self.ctl.init(brief)

    def decide(self, request, op='checkpoint', **changes):
        return self.ctl.apply_round(request, {
            'request_sha256': request['request_sha256'], 'status': 'active',
            'progress': 'verified_progress', 'reason': 'Verified local preparation only',
            **changes}, op)

    def test_draft_preparation_progress_closes_without_approval_or_usage_reset(self):
        for stage in (None, 'intake', 'venue'):
            with self.subTest(stage=stage):
                self.root = Path(self.temp.name) / (stage or 'initial')
                self.ctl = Controller(self.root)
                if stage is None:
                    self.initialize()
                else:
                    with self.assertRaises(FixturePaused):
                        run(self.root, undecided=True, stop_after=stage)
                put(self.root, 'history/usage.json', {'calls': 1, 'usage': 'unreported'})
                self.ctl.settle_budget(None, {'receipt': 'history/usage.json',
                    'status': 'unknown', 'usage': {'calls': 1}}, 'historical-use')
                before = self.ctl.load()
                self.ctl.begin_round()
                put(self.root, 'preparation.md', 'Local preparation checked; no scientific execution.')
                request = self.ctl.prepare_round(['preparation.md'])
                result = self.decide(request)
                after = self.ctl.load()
                self.assertEqual('round_recorded', result['status'])
                self.assertIsNone(after['approval'])
                self.assertEqual(before['brief'], after['brief'])
                self.assertEqual(before['created_at'], after['created_at'])
                self.assertEqual(before['usage_ledger'], after['usage_ledger'])
                self.assertEqual(before['receipts'], after['receipts'])
                self.assertIsNone(after['active_round'])
                self.assertIsNone(after['pending_round'])
                self.assertEqual('active', after['last_round_status'])
                self.assertFalse(result['checkpoint']['continuation']['host_turn_end_allowed'])
                self.assertEqual('continue_authorized_work', result['checkpoint']['continuation']['action'])

    def test_draft_empty_checkpoint_does_not_require_final_brief(self):
        self.initialize()
        self.ctl.begin_round()
        request = self.ctl.prepare_round([])
        self.decide(request, progress='no_progress')
        self.assertIsNone(self.ctl.load()['approval'])

    def test_draft_tampered_evidence_remains_rejected(self):
        self.initialize()
        self.ctl.begin_round()
        put(self.root, 'preparation.md', 'Original evidence')
        request = self.ctl.prepare_round(['preparation.md'])
        put(self.root, 'preparation.md', 'Changed after judgment preparation')
        with self.assertRaisesRegex(Refusal, 'Round evidence changed'):
            self.decide(request)
        self.assertEqual([], self.ctl.load()['rounds'])

    def test_draft_forged_request_remains_rejected(self):
        self.initialize()
        self.ctl.begin_round()
        request = self.ctl.prepare_round([])
        forged = copy.deepcopy(request)
        forged['workload'] = None
        forged['request_sha256'] = digest({k: v for k, v in forged.items() if k != 'request_sha256'})
        with self.assertRaisesRegex(Refusal, 'not issued'):
            self.decide(forged, progress='no_progress')

    def test_checkpoint_does_not_authorize_research_or_finalization(self):
        self.initialize()
        self.ctl.begin_round()
        request = self.ctl.prepare_round([])
        self.decide(request, progress='no_progress')
        for stage in ('plan', 'experiment'):
            with self.subTest(stage=stage), self.assertRaisesRegex(Refusal, 'Exact Brief approval'):
                self.ctl.commit({'stage': stage}, 'unauthorized-' + stage)
        with self.assertRaisesRegex(Refusal, 'Exact Brief approval'):
            self.ctl.finalize('unauthorized-delivery')
        with self.assertRaises(Refusal):
            self.ctl.reserve_budget({'usage': {'calls': 1}, 'purpose': 'Not authorized'}, 'unauthorized-resource')
        self.assertIsNone(self.ctl.load()['approval'])

    def test_draft_checkpoint_keeps_stop_validation(self):
        self.initialize()
        self.ctl.begin_round()
        request = self.ctl.prepare_round([])
        with self.assertRaisesRegex(Refusal, 'cannot stop'):
            self.decide(request, progress='no_progress', stop={'reason': 'internal repair'})
        self.assertEqual([], self.ctl.load()['rounds'])


if __name__ == '__main__':
    unittest.main()
