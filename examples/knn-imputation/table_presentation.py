#!/usr/bin/env python3
"""Replay the actual footer clarification, preserving every numeric table byte.

This helper was recorded after the real study. --check verifies byte identity
with the already reviewed output; it is not a pre-outcome scientific protocol.
"""
import argparse
import hashlib
import json
from pathlib import Path


def main(root, check):
    design=json.loads((root/'experiment/design.json').read_text())
    results=json.loads((root/'experiment/results.json').read_text())
    if len(design['cases'])!=8 or len(design['seeds'])!=5 or len(results['runs'])!=80 or any(x['status']!='completed' for x in results['runs']):
        raise ValueError('This presentation describes only the completed frozen eight-dataset/five-seed study')
    source='figures/macro.tex';target='figures/generated-v2/macro-display.tex'
    original=(root/source).read_text()
    boundary='\\par\\smallskip\\footnotesize\\raggedright '
    if original.count(boundary)!=1 or not original.endswith('\\end{minipage}\n'):
        raise ValueError('Inspect the changed canonical renderer before modifying its footer')
    footer=('The condition rows summarize eight fixed dataset means after averaging five seeds within each dataset. '
        'All 80 planned fits completed. The delta row summarizes the eight paired dataset mean changes, '
        'pre-imputation minus post-imputation scaling. Bounds are mean plus/minus sample SD (ddof=1), '
        'not confidence limits or feasible-score ranges.')
    display=original.split(boundary)[0]+boundary+footer+'\n\\end{minipage}\n'
    if display.split('\\end{tabular}')[0]!=original.split('\\end{tabular}')[0]:
        raise ValueError('Numeric table bytes changed')
    record={'kind':'footer-only clarification; no numeric or header-row change','canonical_source':source,
        'canonical_sha256':hashlib.sha256(original.encode()).hexdigest(),'display_source':target,
        'display_sha256':hashlib.sha256(display.encode()).hexdigest(),'tabular_bytes_equal':True,
        'reason':'A real manuscript reader identified machine-oriented independent-case/unused-penalty wording that could obscure the actual fixed-dataset descriptive estimand. Canonical renderer output remains preserved.'}
    outputs={target:display,'figures/table-presentation.json':json.dumps(record,indent=2)+'\n'}
    for name,text in outputs.items():
        path=root/name
        if path.exists():
            if path.read_bytes()!=text.encode(): raise ValueError('Preserve the differing existing presentation: '+name)
        elif check:
            raise ValueError('Reviewed output is missing: '+name)
        else:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    print('Exact reviewed presentation and sidecar match; numeric table bytes unchanged.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path);parser.add_argument('--check',action='store_true')
    args=parser.parse_args();main(args.run.resolve(),args.check)
