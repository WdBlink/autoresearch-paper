"""Host checkpoint advice distinguishes progress from a justified handoff."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.rounds import continuation

class ContinuationTests(unittest.TestCase):
    def test_pending_question_does_not_end_active_work(self):
        result = continuation({'last_round_status':'active', 'user_questions':{'budget':{'status':'needs_input'}}})
        self.assertFalse(result['host_turn_end_allowed'])
        self.assertEqual(['budget'], result['pending_question_kinds'])
        self.assertEqual('continue_authorized_work', result['action'])

    def test_waiting_still_needs_host_presentation_and_independent_work_check(self):
        result = continuation({'last_round_status':'needs_input'})
        self.assertIsNone(result['host_turn_end_allowed'])
        self.assertEqual('verify_actual_external_handoff', result['action'])

    def test_recorded_delivery_and_user_stop_are_distinct_from_completion(self):
        delivered = continuation({'delivery':'delivery/manifest.json'})
        stopped = continuation({'task_stop':{'reason':'user_request'}})
        self.assertTrue(delivered['host_turn_end_allowed'])
        self.assertTrue(stopped['host_turn_end_allowed'])
        self.assertNotEqual(delivered['action'], stopped['action'])

if __name__ == '__main__': unittest.main()
