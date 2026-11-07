"""Logical task time survives explicit same-task controller succession."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.runtime import Controller, Refusal, file_hash, digest
from lib.budget import elapsed, summary
from lib.user_input import prepare
from run_fixture import make_brief, put


class TaskClockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.ctl = Controller(self.root)
        brief = make_brief(); brief['budget'] = {'minutes': 30}
        self.ctl.init(brief)
        self.ctl.approve(self.ctl.load()['brief_sha256'], 'software-fixture')
        put(self.root, 'usage.json', {'dispatch': 'historical fixture', 'calls': 2})
        self.ctl.settle_budget(None, {'receipt': 'usage.json', 'status': 'unknown',
            'usage': {'calls': 2}}, 'historical-usage')
        self.before = self.ctl.load()

    def packet(self, minutes=60, changes=None, name='predecessor.json'):
        prior = copy.deepcopy(self.before)
        prior['created_at'] = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        if changes: prior.update(changes)
        put(self.root, name, prior)
        return {'snapshot': name, 'sha256': file_hash(self.root / name)}

    def test_recovery_preserves_state_and_budget_question_uses_same_clock(self):
        packet = self.packet()
        result = self.ctl.restore_task_clock(packet, 'restore')
        state = self.ctl.load()
        for field in ('brief', 'brief_sha256', 'approval', 'usage_ledger', 'receipts', 'created_at'):
            self.assertEqual(self.before[field], state[field])
        self.assertGreaterEqual(elapsed(state), 60)
        self.assertIn('minutes', summary(state)['exhausted'])
        put(self.root, 'plan.json', {'items': []})
        question = prepare('budget', {'budget': {}, 'plan': 'plan.json', 'reason': 'Software test'}, self.root, state)
        self.assertEqual(result['task_started_at'], question['time_scope']['started_at'])
        self.assertIn(result['task_started_at'], question['summary'])
        self.assertEqual(result, self.ctl.restore_task_clock(packet, 'restore'))

    def test_completed_restore_replays_without_moving_a_newer_earlier_clock(self):
        first = self.packet(60, name='first.json')
        first_result = self.ctl.restore_task_clock(first, 'first')
        earlier = self.packet(120, name='earlier.json')
        self.ctl.restore_task_clock(earlier, 'earlier')
        before_replay = self.ctl.load()
        self.assertEqual(first_result, self.ctl.restore_task_clock(first, 'first'))
        self.assertEqual(before_replay['task_clock'], self.ctl.load()['task_clock'])
        with self.assertRaisesRegex(Refusal, 'later'):
            self.ctl.restore_task_clock(first, 'new-operation')

    def test_future_later_and_unrelated_sources_are_rejected(self):
        with self.assertRaisesRegex(Refusal, 'future'):
            self.ctl.restore_task_clock(self.packet(-60), 'future')
        self.ctl.restore_task_clock(self.packet(), 'restore')
        with self.assertRaisesRegex(Refusal, 'later'):
            self.ctl.restore_task_clock(self.packet(20, name='later.json'), 'later')
        brief = copy.deepcopy(self.before['brief']); brief['question'] = 'Unrelated task'
        with self.assertRaisesRegex(Refusal, 'different task'):
            self.ctl.restore_task_clock(self.packet(changes={'brief': brief, 'brief_sha256': digest(brief)}, name='unrelated.json'), 'unrelated')

    def test_tampering_rejected_before_and_after_restore(self):
        packet = self.packet(); original = (self.root / packet['snapshot']).read_bytes()
        (self.root / packet['snapshot']).write_bytes(original + b' ')
        with self.assertRaisesRegex(Refusal, 'hash differs'):
            self.ctl.restore_task_clock(packet, 'restore')
        (self.root / packet['snapshot']).write_bytes(original)
        self.ctl.restore_task_clock(packet, 'restore')
        (self.root / packet['snapshot']).write_bytes(original + b' ')
        with self.assertRaisesRegex(Refusal, 'snapshot changed'):
            self.ctl.load()

    def test_old_controller_without_clock_uses_created_at(self):
        self.assertNotIn('task_clock', self.before)
        self.assertEqual(self.before['created_at'], summary(self.before)['task_started_at'])
        self.assertLess(elapsed(self.before), 1)

    def test_timezone_and_snapshot_integrity_are_required(self):
        with self.assertRaisesRegex(Refusal, 'timezone-aware'):
            self.ctl.restore_task_clock(self.packet(changes={'created_at': '2020-01-01'}), 'naive')
        with self.assertRaisesRegex(Refusal, 'preserved schema2'):
            self.ctl.restore_task_clock(self.packet(changes={'brief_sha256': 'wrong'}), 'bad-brief')

    def test_cli_restores_preserved_snapshot(self):
        packet = self.packet(); put(self.root, 'clock-packet.json', packet)
        script = Path(__file__).resolve().parents[1] / 'scripts/research.py'
        result = subprocess.run([sys.executable, '-B', str(script), '--run', str(self.root),
            'restore-task-clock', '--packet', 'clock-packet.json', '--operation-id', 'restore-cli'], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual('task_clock_restored', json.loads(result.stdout)['status'])
        self.assertGreaterEqual(elapsed(self.ctl.load()), 60)


if __name__ == '__main__': unittest.main()
