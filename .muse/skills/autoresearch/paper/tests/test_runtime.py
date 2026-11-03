from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.runtime import Controller, Refusal, digest, read_json, safe, tex_without_comments


def brief():
    return {'question': 'Offline software check', 'venue': 'Synthetic', 'direction': 'software', 'paper_type': 'original',
            'scope': 'Software only', 'angle': 'Contract test', 'audience': 'Developer', 'resources': {'local_cpu': True}, 'software_fixture': True, 'reviewers': ['reviewer'],
            'deliverable_plan': [{'id': 'F1', 'kind': 'figure', 'title': 'Fixture', 'purpose': 'Software check',
                                  'acceptance_criteria': ['correct numbers'], 'evidence_requirements': ['raw logs']}]}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.ctl = Controller(self.root)
        self.init = self.ctl.init(brief())

    def approve(self):
        self.ctl.approve(self.init['brief_sha256'], 'offline fixture')

    def test_exact_approval_and_no_history_reset(self):
        with self.assertRaises(Refusal): self.ctl.approve('wrong', 'fixture')
        with self.assertRaisesRegex(Refusal, 'approval'): self.ctl.ready(self.ctl.load())
        with self.assertRaisesRegex(Refusal, 'already exists'): self.ctl.init(brief())
        self.approve()
        self.assertEqual('software fixture', self.ctl.load()['approval']['basis'])

    def test_tex_comments_do_not_count_as_manuscript_insertion(self):
        visible = tex_without_comments("% \\includegraphics{missing.pdf}\nActual \\includegraphics{present.pdf} % \\label{fake}\nEscaped \\% is text")
        self.assertNotIn('missing.pdf', visible)
        self.assertNotIn('label{fake}', visible)
        self.assertIn('present.pdf', visible)
        self.assertIn(r'\%', visible)

    def test_duplicate_json_and_path_escape(self):
        (self.root / 'x.json').write_text('{"x":1,"x":2}')
        with self.assertRaisesRegex(Refusal, 'Duplicate'): read_json(self.root / 'x.json')
        for path in ('../x', '/etc/passwd', '.paper/control.json'):
            with self.assertRaises(Refusal): safe(self.root, path)
        (self.root / 'link').symlink_to(self.ctl.path)
        with self.assertRaises(Refusal): safe(self.root, 'link')

    def test_round_binding_idempotence_staleness_and_structural_pivot(self):
        self.approve(); (self.root / 'evidence.json').write_text('{"fixture":1}')
        def decide(op, **changes):
            request = self.ctl.prepare_round(['evidence.json'])
            decision = {'request_sha256': request['request_sha256'], 'progress': 'no_progress',
                        'reason': 'Fixture exercise; no research performed', 'status': 'active', **changes}
            return request, decision, self.ctl.apply_round(request, decision, op)
        request, decision, result = decide('r1')
        self.assertEqual(result, self.ctl.apply_round(request, decision, 'r1'))
        self.assertEqual(1, len(self.ctl.load()['rounds']))
        decide('r2')
        request = self.ctl.prepare_round(['evidence.json'])
        decision = {'request_sha256': request['request_sha256'], 'progress': 'no_progress', 'reason': 'Fixture', 'status': 'active'}
        with self.assertRaisesRegex(Refusal, 'pivot'): self.ctl.apply_round(request, decision, 'r3')
        decision['direction'] = {'id': 'different-comparison', 'change': 'Compare a different algorithm family', 'reason': 'Previous family plateaued'}
        self.ctl.apply_round(request, decision, 'r3')
        request = self.ctl.prepare_round(['evidence.json'])
        (self.root / 'evidence.json').write_text('{"fixture":2}')
        decision['request_sha256'] = request['request_sha256']
        with self.assertRaisesRegex(Refusal, 'evidence changed'): self.ctl.apply_round(request, decision, 'r4')

    def test_unresolved_citations_do_not_produce_an_accepted_pdf(self):
        (self.root / 'bad.tex').write_text(r'\documentclass{article}\begin{document}Missing source \cite{missing}.\end{document}')
        with self.assertRaises(Refusal):
            self.ctl._action(self.ctl.load(), {'type': 'compile_tex', 'source': 'bad.tex', 'pdf': 'bad.pdf'})
        self.assertFalse((self.root / 'bad.pdf').exists())

    def test_work_order_omission_unknown_action_and_coverage(self):
        state = self.ctl.load()
        with self.assertRaisesRegex(Refusal, 'requires work_orders'): self.ctl.check_orders(state, [])
        order = {'id': 'W1', 'producer': 'author', 'requirement_ids': ['other'], 'actions': [{'type': 'validate_packet', 'packet': 'p.json'}]}
        with self.assertRaisesRegex(Refusal, 'Unknown'): self.ctl.check_orders(state, [order])
        order['requirement_ids'] = ['F1']; order['actions'] = [{'type': 'shell', 'command': 'true'}]
        with self.assertRaisesRegex(Refusal, 'Unknown action'): self.ctl.check_orders(state, [order])
        order['actions'] = [{'type': 'validate_packet', 'packet': 'p.json'}]
        self.ctl.check_orders(state, [order])


if __name__ == '__main__': unittest.main()
