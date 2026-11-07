from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import planning, venue_tools

vp = planning.venue_profile


class VisualLabelTests(unittest.TestCase):
    def test_numeric_and_roman_identities_remain_integers(self):
        measured = vp.measure_text("Figure I: First.\n\nFigure II. Second.\n\nTable 1: First.\n\nReferences")
        self.assertEqual([1, 2], [x['number'] for x in measured['figures']])
        self.assertEqual([1], [x['number'] for x in measured['tables']])
        self.assertEqual(['I', 'II'], [x['label_text'] for x in measured['figures']])
        self.assertEqual([], measured['warnings'])

    def test_prefixed_labels_are_distinct_and_naturally_ordered(self):
        text = "\n\n".join(f"Figure {n}: Measured caption." for n in ['A10', '1', 'A2', 'A1', 'B1', 's1', 'A.1', 'S-1'])
        measured = vp.measure_text(text)
        self.assertEqual([1, 'A1', 'A2', 'A10', 'A.1', 'B1', 'S1', 'S-1'], [x['number'] for x in measured['figures']])
        self.assertEqual('s1', next(x for x in measured['figures'] if x['number'] == 'S1')['label_text'])
        self.assertTrue(any('not contiguous' in x for x in measured['warnings']))

    def test_contiguity_is_checked_within_each_prefix(self):
        text = "\n\n".join(f"Figure {n}: Caption." for n in ['1','2','A1','A2','B1']) + "\n\nReferences"
        self.assertEqual([], vp.measure_text(text)['warnings'])

    def test_mixed_missing_mentions_do_not_crash_or_disappear(self):
        measured = vp.measure_text("See Figure 2 and Figure A1 and Table S2.\n\nFigure 1: Present.\fReferences")
        self.assertTrue(any("[2, 'A1']" in x for x in measured['warnings']))
        self.assertTrue(any("['S2']" in x for x in measured['warnings']))

    def test_prose_and_ranges_are_not_captions(self):
        measured = vp.measure_text("Figure A1 is discussed here.\nFigures 1-3: A range.\nFigure A1a: A panel reference.\nTable Discussion: Words.")
        self.assertEqual([], measured['figures'])
        self.assertEqual([], measured['tables'])

    def test_prefixed_design_requires_exact_identity_and_full_coverage(self):
        measured = vp.measure_text("Figure 1: Main.\n\nFigure A1: Appendix.\n\nReferences")
        rows=[]
        for raw in measured['figures']:
            rows.append({**raw,'id':'F'+str(raw['number']),'type':'analysis_plot','placement':'appendix',
                'question':'Which synthetic label is present?','claim':'The synthetic label is retained.',
                'evidence':'Software fixture only.','design_takeaway':'Keep label identity.',
                'limitations':'No scientific evidence.','panels':[]})
        sample={'design':{'figures':rows,'tables':[]},'visual_read':{'pages':[1],'method':'rendered_pdf','notes':'Synthetic test declaration only.'}}
        self.assertEqual(rows, venue_tools.validate_design(sample, measured)['figures'])
        for invalid in (True, 1.0, '1', 'a1', 'B1', [], {}):
            other=deepcopy(sample);other['design']['figures'][1]['number']=invalid
            with self.subTest(number=invalid), self.assertRaises(planning.PlanningError):
                venue_tools.validate_design(other, measured)
        for rows in (sample['design']['figures'][:1], [sample['design']['figures'][0]]*2):
            other=deepcopy(sample);other['design']['figures']=rows
            with self.assertRaises(planning.PlanningError): venue_tools.validate_design(other, measured)


if __name__ == '__main__':
    unittest.main()
