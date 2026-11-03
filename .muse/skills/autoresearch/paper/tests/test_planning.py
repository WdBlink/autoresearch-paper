from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import planning


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def visual_plan():
    return {'items': [
        {'id': 'F1', 'kind': 'figure', 'type': 'quantitative_results',
         'question': 'Which method has the lower error?', 'claim': 'The candidate has lower measured error.',
         'data': 'Measured trials.', 'section': 'Results', 'priority': 'must'},
        {'id': 'T1', 'kind': 'table', 'type': 'main_results',
         'question': 'What are the observed trial outcomes?', 'claim': 'The table includes failures as well as successes.',
         'data': 'The complete trial ledger.', 'section': 'Results', 'priority': 'must'}]}


def make_pdf(root, name='sample', separator='.'):
    source = root / (name + '.tex')
    source.write_text(r'''\documentclass{article}
\begin{document}
Fixture study. This is software test data, not an accepted research paper.
Figure 1 and Table 1 summarize the measured fixture outcomes.

\noindent Figure 1. Candidate comparison under fixed test conditions.

\noindent Table 1. Main results including all recorded failures.

The comparison uses the full fixture ledger and is not scientific evidence.
\end{document}
'''.replace('Figure 1. Candidate', 'Figure 1' + separator + ' Candidate').replace('Table 1. Main', 'Table 1' + separator + ' Main'))
    out = subprocess.run(['pdflatex', '-interaction=nonstopmode', '-halt-on-error', source.name],
                         cwd=root, capture_output=True, timeout=60)
    if out.returncode:
        raise AssertionError(out.stdout.decode(errors='replace')[-1500:])
    return root / (name + '.pdf')


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        text = 'The fixture supports a deterministic local CPU comparison.'
        (self.root / 'source.txt').write_text(text)
        self.quote = {'material_id': 'M1', 'start': 0, 'end': len(text), 'quote': text}
        self.packet = {'artifacts': ['source.txt'],
            'materials': [{'id': 'M1', 'path': 'source.txt', 'sha256': sha(self.root / 'source.txt'),
                           'availability': 'readable', 'read_spans': [[0, len(text)]]}],
            'evidence': [self.quote],
            'feasibility': {'status': 'feasible', 'selected_option': 'cpu',
                'options': [{'id': 'cpu', 'implementation': 'A deterministic standard-library fixture.',
                             'selection_reason': 'No external model or remote computer is required.', 'evidence': [self.quote]}],
                'single_option_reason': 'The software fixture has one fixed reference implementation.',
                'resources': {'authorization': 'Offline software test only.', 'cost_basis': 'No paid calls.'},
                'experiments': [{'claim': 'The fixture produces complete evidence.', 'metric': 'error in metres',
                    'comparison': 'candidate against the fixed baseline', 'protocol': 'frozen paired cases and seeds',
                    'completion': 'all declared cases have terminal records', 'failure_route': 'retain failed and unknown trials'}]}}

    def test_full_read_and_source_grounded_feasibility(self):
        self.assertEqual([], planning.validate('intake', self.packet, self.root))

    def test_registered_material_is_not_read_content(self):
        self.packet['materials'][0]['read_spans'] = [[0, 5]]
        self.assertIn('partially read', ';'.join(planning.validate('intake', self.packet, self.root)))

    def test_quote_must_match_actual_read_span(self):
        self.packet['evidence'][0] = {**self.quote, 'quote': 'invented evidence'}
        self.assertIn('quote does not match', ';'.join(planning.validate('intake', self.packet, self.root)))

    def test_metadata_only_has_limit_and_cannot_be_evidence(self):
        self.packet['materials'][0].update(availability='metadata_only', read_spans=[], limitation='Binary metadata only.')
        self.assertIn('readable material', ';'.join(planning.validate('intake', self.packet, self.root)))

    def test_omitting_experiments_needs_the_frozen_scope(self):
        self.packet['feasibility']['experiments'] = []
        self.packet['feasibility']['no_experiment_reason'] = 'Review-only comparison of published evidence.'
        self.assertIn('approved review/survey', ';'.join(planning.validate('intake', self.packet, self.root)))
        self.packet['_brief'] = {'paper_type': 'review', 'not_applicable': {'experiment': 'Review-only comparison of published evidence.'}}
        self.assertEqual([], planning.validate('intake', self.packet, self.root))

    def test_changed_material_and_unsupported_route_fail(self):
        (self.root / 'source.txt').write_text('changed')
        self.assertIn('changed', ';'.join(planning.validate('intake', self.packet, self.root)))
        self.packet['materials'][0]['sha256'] = sha(self.root / 'source.txt')
        self.packet['materials'][0]['read_spans'] = [[0, 7]]
        self.packet['evidence'] = [{'material_id': 'M1', 'start': 0, 'end': 7, 'quote': 'changed'}]
        self.packet['feasibility']['options'][0]['evidence'] = []
        self.packet['feasibility']['options'][0]['basis'] = 'assumption'
        self.assertIn('actually read evidence', ';'.join(planning.validate('intake', self.packet, self.root)))


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'template.tex').write_text(r'\documentclass[10pt,twocolumn]{article}')
        (self.root / 'main.tex').write_text(r'\documentclass[10pt, twocolumn]{article}' + '\n' + r'\usepackage[labelsep=period]{caption}')
        (self.root / 'rules.md').write_text('Use a two-column article format. No official template is available.')
        self.venue = {'template': {'status': 'available', 'path': 'template.tex', 'sha256': sha(self.root / 'template.tex')},
                      'official_rules': {'path': 'rules.md', 'sha256': sha(self.root / 'rules.md')}}
        self.packet = {'stage': 'write', 'manuscript_tex': 'main.tex', 'template_source': 'template.tex',
                       'template_sha256': self.venue['template']['sha256'], 'artifacts': ['main.tex', 'template.tex'],
                       '_history': {'venue': self.venue}}

    def test_literal_official_class_and_options_are_preserved(self):
        self.assertEqual([], planning.validate('write', self.packet, self.root))
        (self.root / 'main.tex').write_text(r'% \documentclass{wrong}' + '\n' + r'\documentclass[10pt, twocolumn]{article}')
        self.assertEqual([], planning.validate('write', self.packet, self.root))

    def test_changed_class_or_options_cannot_silently_replace_the_template(self):
        for declaration in (r'\documentclass[10pt,twocolumn]{report}', r'\documentclass[12pt]{article}'):
            with self.subTest(declaration=declaration):
                (self.root / 'main.tex').write_text(declaration)
                self.assertIn('documentclass/options differ', ';'.join(planning.validate('write', self.packet, self.root)))

    def test_template_version_and_required_packages_are_checked(self):
        self.packet['template_sha256'] = '0' * 64
        self.assertIn('hash differs', ';'.join(planning.validate('write', self.packet, self.root)))
        self.packet['template_sha256'] = self.venue['template']['sha256']
        self.venue['template']['required_packages'] = [{'name': 'caption', 'options': ['labelsep=period']}]
        self.assertEqual([], planning.validate('write', self.packet, self.root))
        self.venue['template']['required_packages'][0]['options'] = ['labelsep=colon']
        self.assertIn('package options', ';'.join(planning.validate('write', self.packet, self.root)))
        self.venue['template']['required_packages'] = ['graphicx']
        self.assertIn('omitted required', ';'.join(planning.validate('write', self.packet, self.root)))

    def test_no_official_template_requires_a_bound_format_decision(self):
        self.venue['template'] = {'status': 'not_available', 'reason': 'The author rules provide format requirements only.'}
        self.packet['template_source'] = 'rules.md'; self.packet['artifacts'].append('rules.md')
        self.packet['template_sha256'] = self.venue['official_rules']['sha256']
        self.assertIn('format check', ';'.join(planning.validate('write', self.packet, self.root)))
        self.packet['format_check'] = {'basis': 'official_requirement', 'reason': 'Literal format matches the frozen author rules.',
            'documentclass': 'article', 'options': ['10pt', 'twocolumn'],
            'evidence_quote': 'Use a two-column article format.'}
        self.assertEqual([], planning.validate('write', self.packet, self.root))
        self.packet['format_check']['evidence_quote'] = 'Invented rules'
        self.assertIn('quote is absent', ';'.join(planning.validate('write', self.packet, self.root)))


@unittest.skipUnless(shutil.which('pdflatex') and shutil.which('pdftotext') and shutil.which('pdfinfo'),
                     'Real PDF checks need pdflatex and Poppler')
class PlanningPdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        make_pdf(self.root)
        for name, text in [('rules.md', 'Fixture author rules with a template. This is synthetic.'),
                           ('template.tex', '\\documentclass{article}'),
                           ('accepted.md', 'Synthetic acceptance evidence, software fixture only.')]:
            (self.root / name).write_text(text)
        dump(self.root / 'visual-plan.json', visual_plan())
        self.packet = {'stage': 'venue', 'software_fixture': True, 'venue': 'Fixture venue',
            'direction': 'software verification', 'paper_type': 'original',
            'artifacts': ['sample.pdf', 'rules.md', 'template.tex', 'accepted.md', 'visual-plan.json',
                          'measurements.json', 'profile.json', 'plan-check.json'],
            'official_rules': self.evidence('rules.md', basis='official_requirement'),
            'template': self.evidence('template.tex', status='available'),
            'samples': [{'id': 'S1', 'pdf': 'sample.pdf', 'venue_label': 'Fixture venue', 'year': 2026,
                         'acceptance_evidence': self.evidence('accepted.md'),
                         'direction_match': 'Synthetic study of the same fixture question.',
                         'design': {'figures': [{'type': 'quantitative_results', 'placement': 'body'}],
                                    'tables': [{'type': 'main_results', 'placement': 'body'}]}}],
            'sampling_limitations': 'One synthetic PDF exercises measurement, not a real venue preference.',
            'figure_table_plan': 'visual-plan.json', 'measurements': 'measurements.json',
            'venue_profile': 'profile.json', 'venue_plan_check': 'plan-check.json'}
        self.recompute()
        self.plan_packet = {'stage': 'plan', 'figure_table_plan': 'visual-plan.json',
            'plan_snapshot': 'snapshot.json', 'artifacts': ['visual-plan.json', 'snapshot.json'],
            '_history': {'venue': self.packet},
            '_brief': {'deliverable_plan': [
                {'id': item['id'], 'kind': item['kind'], 'title': item['claim'],
                 'purpose': item['question'], 'acceptance_criteria': ['Evidence-backed result'],
                 'evidence_requirements': ['Full trial ledger']} for item in visual_plan()['items']]}}
        dump(self.root / 'snapshot.json', planning.plan_snapshot(self.root / 'visual-plan.json'))

    def evidence(self, name, **extra):
        return {'path': name, 'sha256': sha(self.root / name), 'url': 'https://fixture.invalid/' + name, **extra}

    def recompute(self):
        computed = planning.calibrate(self.packet, self.root)
        for key in ('measurements', 'venue_profile', 'venue_plan_check'):
            dump(self.root / self.packet[key], computed[key])

    def review_packet(self):
        return {'stage': 'review', 'figure_table_plan': 'visual-plan.json', 'plan_snapshot': 'snapshot.json',
            'manuscript_pdf': 'sample.pdf', 'artifacts': ['visual-plan.json', 'snapshot.json', 'sample.pdf'],
            '_history': {'plan': self.plan_packet},
            'r6_reviews': [{'id': key, 'verdict': 'fulfilled', 'reason': 'Verified the actual fixture caption and evidence.',
                            'evidence_locations': ['sample.pdf page 1']} for key in ('F1', 'T1')]}

    def test_actual_pdf_measurement_profile_budget_and_frozen_plan(self):
        self.assertEqual([], planning.validate('venue', self.packet, self.root))
        self.assertEqual([], planning.validate('plan', self.plan_packet, self.root))
        profile = json.loads((self.root / 'profile.json').read_text())
        self.assertEqual(1, profile['budget']['figures']['target'])
        self.assertEqual(1, profile['budget']['tables']['target'])
        self.assertEqual([], planning.validate('review', self.review_packet(), self.root))

    def test_standard_colon_captions_are_not_mistaken_for_missing_outputs(self):
        make_pdf(self.root, name='colon', separator=':')
        review = self.review_packet()
        review['manuscript_pdf'] = 'colon.pdf'; review['artifacts'].append('colon.pdf')
        self.assertEqual([], planning.validate('review', review, self.root))

    def test_fake_measurement_or_stale_official_template_fails(self):
        measurements = json.loads((self.root / 'measurements.json').read_text())
        measurements[0]['counts']['figures'] = 42
        dump(self.root / 'measurements.json', measurements)
        self.assertIn('recomputed', ';'.join(planning.validate('venue', self.packet, self.root)))
        self.recompute()
        (self.root / 'template.tex').write_text('changed template')
        self.assertIn('stale', ';'.join(planning.validate('venue', self.packet, self.root)))

    def test_missing_acceptance_evidence_or_direction_fails(self):
        self.packet['samples'][0]['acceptance_evidence']['sha256'] = '0' * 64
        self.assertIn('acceptance evidence', ';'.join(planning.validate('venue', self.packet, self.root)))
        self.packet['samples'][0]['acceptance_evidence'] = self.evidence('accepted.md')
        self.packet['samples'][0]['direction_match'] = ''
        self.assertIn('direction-match', ';'.join(planning.validate('venue', self.packet, self.root)))

    def test_snapshot_cannot_freeze_a_different_promise_set(self):
        snapshot = json.loads((self.root / 'snapshot.json').read_text())
        snapshot['items'].pop()
        dump(self.root / 'snapshot.json', snapshot)
        self.assertIn('different items', ';'.join(planning.validate('plan', self.plan_packet, self.root)))

    def test_r6_omitted_item_and_rewritten_plan_fail_despite_total_score(self):
        review = self.review_packet()
        review['overall_score'] = 100
        review['r6_reviews'].pop()
        self.assertIn('every original', ';'.join(planning.validate('review', review, self.root)))
        current = visual_plan(); current['items'].pop()
        dump(self.root / 'current.json', current)
        review = self.review_packet(); review['figure_table_plan'] = 'current.json'; review['artifacts'].append('current.json')
        self.assertIn('changed promise fulfilled', ';'.join(planning.validate('review', review, self.root)))

    def test_r6_uses_bound_original_snapshot(self):
        review = self.review_packet()
        dump(self.root / 'other.json', planning.plan_snapshot(self.root / 'visual-plan.json'))
        review['plan_snapshot'] = 'other.json'; review['artifacts'].append('other.json')
        self.assertIn('original frozen', ';'.join(planning.validate('review', review, self.root)))

    def test_fixture_must_not_be_mislabelled_real_venue_evidence(self):
        self.packet['software_fixture'] = False
        self.assertIn('fixture URL', ';'.join(planning.validate('venue', self.packet, self.root)))


if __name__ == '__main__':
    unittest.main()
