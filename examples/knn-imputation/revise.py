#!/usr/bin/env python3
"""Apply the recorded real-paper R0 corrections through the public controller.

This is a case-specific revision, not an automatic scientific reviewer. The
independent reports must exist before it runs. Original experiment outputs and
the pre-outcome plan remain unchanged.
"""
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from control import invoke, put


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(root, name):
    return json.loads((root / name).read_text())


def main(root):
    if (root / 'venue/packet-r1.json').exists():
        raise ValueError('R1 has already begun; resume the recorded public CLI operations instead of overwriting revision history')
    reports = ['review/artifact-review-r0.json', 'review/methods-manuscript-r0.json']
    for name in reports:
        if not (root / name).is_file():
            raise ValueError('The actual independent R0 report is missing: ' + name)
    print(invoke(root, 'rewind', '--stage', 'venue', '--reason',
        'Actual independent R0 review: correct S01 T13 boldface reading, bibliography identity/display and figure read-order; retain the frozen scientific protocol and every real outcome',
        '--operation-id', 'rewind-real-review-r1')['status'])

    # Preserve the exact first reading before correcting the current record.
    changes = []
    for name in ('venue/analysis/S01.json', 'venue/analysis/S01.md'):
        before = name.replace('S01.', 'revisions/S01-r0.')
        put(root, before, (root / name).read_text())
        changes.append({'baseline': {'path': before, 'sha256': digest(root / before)},
                        'after': name, 'reason': 'Correct the primary host misreading of T13 typeface; preserve the real T14 inconsistency.'})
    reading = load(root, 'venue/analysis/S01.json')
    table = next(x for x in reading['tables'] if x['number'] == 13)
    old_claim = table['claim']
    table['claim'] = ('At n=500/DGP4, stacking minimizes displayed MSIE and SVR has the smallest numerical MAPIE per block. '
        'At 30%, SVR MAPIE 37.6659 is bold and XGB 42.4364 is not bold; the independent PDF font-span check corrected the primary host\'s initial reading.')
    old_caveat = reading['summary']['source_caveats'][0]
    reading['summary']['source_caveats'] = [
        'Table14 40% MSIE emphasis does not mark the numerical minimum: SVR 1.0873 is below the emphasized stacking 1.0987. Source values were not independently rerun.',
        'The initial Table13 typeface warning was a host reading error, corrected by independent PDF font-span inspection; it is not a defect in the source.']
    reading['visual_read']['correction_evidence'] = reports[0]
    put(root, 'venue/analysis/S01.json', reading)
    markdown = (root / 'venue/analysis/S01.md').read_text().replace(old_claim, table['claim']).replace(old_caveat, '\n'.join(reading['summary']['source_caveats']))
    put(root, 'venue/analysis/S01.md', markdown)
    put(root, 'review/source-reading-revision.json', {'status': 'revised', 'changes': changes, 'review': reports[0]})
    venue = load(root, 'venue/packet.json')
    sample = next(x for x in venue['samples'] if x['id'] == 'S01')
    sample['design'] = {k: reading[k] for k in ('figures', 'tables')}
    sample['visual_read'] = reading['visual_read']
    for key, path in {'measurements': 'venue/measurements-r1.json', 'venue_profile': 'venue/profile-r1.json',
        'venue_plan_check': 'venue/plan-check-r1.json', 'venue_comparison': 'venue/comparison-r1.json'}.items():
        venue['artifacts'].remove(venue[key])
        venue[key] = path
        venue['artifacts'].append(path)
    venue['artifacts'] += [c['baseline']['path'] for c in changes] + ['review/source-reading-revision.json', *reports]
    put(root, 'venue/packet-r1.json', venue)
    return finish(root, reports)


def finish(root, reports):
    """Continue after the saved source-reading revision, without repeating it."""
    value = invoke(root, 'tool', '--name', 'venue-calibrate', '--packet', 'venue/packet-r1.json', '--publish')
    print('venue remeasured', len(value['written']))
    print(invoke(root, 'commit', '--packet', 'venue/packet-r1.json', '--operation-id', 'accept-real-venue-r1')['stage'])
    print(invoke(root, 'commit', '--packet', 'plan/packet.json', '--operation-id', 'reaccept-unchanged-frozen-plan-r1')['stage'])

    # The publisher's JATS explicitly identifies the compound family name.
    xml_path = 'venue/samples/S07/article.xml'
    names = []
    for contributor in ET.fromstring((root / xml_path).read_bytes()).findall('.//article-meta/contrib-group/contrib'):
        if contributor.get('contrib-type') != 'author':
            continue
        family = contributor.findtext('name/surname')
        given = contributor.findtext('name/given-names')
        names.append({'given': given, 'family': family, 'bibtex': f'{family}, {given}'})
    assert names[-1] == {'given': 'Ben', 'family': 'Van Calster', 'bibtex': 'Van Calster, Ben'}
    put(root, 'literature/s07-name-components.json', {'source': xml_path, 'sha256': digest(root / xml_path),
        'derivation': 'Literal author given-names/surname components from publisher JATS, expressed as BibTeX family, given syntax', 'authors': names})
    bib = (root / 'manuscript/references.bib').read_text()
    bib = bib.replace('Ben Van Calster', 'Van Calster, Ben')
    bib = re.sub(r'^  note = \{Citation year is supplied by the source\..*\},\n', '', bib, flags=re.M)
    last = bib.index('@article{sklearn2011,')
    bib = bib[:last] + bib[last:].replace('  journal = {JMLR},', '  journal = {JMLR},\n  volume = {12},\n  number = {85},\n  pages = {2825--2830},')
    put(root, 'manuscript/references-r1.bib', bib)
    plan = [json.loads(line) for line in (root / 'literature/citation-plan.jsonl').read_text().splitlines()]
    next(x for x in plan if x['key'] == 's07')['authors'][-1] = 'Van Calster, Ben'
    put(root, 'literature/citation-plan-r1.jsonl', '\n'.join(json.dumps(x, ensure_ascii=False) for x in plan) + '\n')
    verification = load(root, 'literature/citation-verification.json')
    record = next(x for x in verification['records'] if x['key'] == 's07')
    record['identity']['authors'][-1] = 'Van Calster, Ben'
    record['evidence'] += ['literature/s07-name-components.json', xml_path]
    put(root, 'literature/citation-verification-r1.json', verification)
    packet = load(root, 'literature/packet.json')
    for key, path in {'bibliography': 'manuscript/references-r1.bib', 'citation_plan': 'literature/citation-plan-r1.jsonl',
        'citation_verification': 'literature/citation-verification-r1.json'}.items():
        packet['artifacts'].remove(packet[key]); packet[key] = path; packet['artifacts'].append(path)
    packet['artifacts'] += ['literature/s07-name-components.json']
    put(root, 'literature/packet-r1.json', packet)
    check = invoke(root, 'tool', '--name', 'citation-check', '--packet', 'literature/packet-r1.json')
    if check['value']['status'] != 'pass':
        raise ValueError(check)
    for stage, path in [('literature', 'literature/packet-r1.json'), ('experiment', 'experiment/packet.json'), ('figures', 'figures/packet.json')]:
        print(invoke(root, 'commit', '--packet', path, '--operation-id', 'reaccept-real-' + stage + '-r1')['stage'])

    for edition in ('main', 'submission'):
        source = (root / f'manuscript/{edition}.tex').read_text()
        source = source.replace('\\bibliography{references}', '\\bibliography{references-r1}')
        source = source.replace('targets were never masked or passed to the imputer.',
            'targets were never masked or included among the imputed feature columns.')
        source = source.replace('Consequently, the pre-imputation scaler estimated',
            "Training labels are passed through the pipeline's fit interface, but \\texttt{KNNImputer} ignores this argument; the target column is absent from the predictor matrix.\nConsequently, the pre-imputation scaler estimated")
        source = source.replace('\\section*{Discussion and limitations}', '\\clearpage\n\\section*{Discussion and limitations}')
        if edition == 'submission':
            block = re.search(r'\\begin\{figure\}.*?\\label\{fig:F1\}.*?\\end\{figure\}\n', source, re.S).group()
            source = source.replace(block, '')
            source = source.replace('\\subsection*{Compared pipelines and scoring}', block + '\n\\subsection*{Compared pipelines and scoring}')
        assert len(source.splitlines()) <= 300
        put(root, f'manuscript/{edition}-r1.tex', source)
    orders = []
    for edition, old_id, ids in [('main', 'W-writing', ['S1', 'S2', 'M1']), ('submission', 'W-submission-format', ['M1'])]:
        orders.append({'id': 'W-' + edition + '-r1', 'producer': 'research-author', 'requirement_ids': ids,
            'supersedes': old_id, 'actions': [{'type': 'compile_tex', 'source': f'manuscript/{edition}-r1.tex', 'pdf': f'manuscript/{edition}-r1.pdf'}]})
    put(root, 'plan/writing-orders-r1.json', orders)
    invoke(root, 'revise-orders', '--packet', 'plan/writing-orders-r1.json', '--reason',
        'Actual independent R0 bibliography and float/read-order corrections; scientific facts and frozen requirements unchanged', '--operation-id', 'orders-real-writing-r1')
    for edition in ('main', 'submission'):
        print(invoke(root, 'execute', '--work-id', 'W-' + edition + '-r1', '--operation-id', 'compile-real-' + edition + '-r1')['status'])
    packet = load(root, 'write/packet.json')
    replacements = {'manuscript/main.tex': 'manuscript/main-r1.tex', 'manuscript/main.pdf': 'manuscript/main-r1.pdf',
        'manuscript/submission.tex': 'manuscript/submission-r1.tex', 'manuscript/submission.pdf': 'manuscript/submission-r1.pdf',
        'manuscript/references.bib': 'manuscript/references-r1.bib'}
    def replace(value):
        if isinstance(value, str): return replacements.get(value, value)
        if isinstance(value, list): return [replace(v) for v in value]
        if isinstance(value, dict): return {k: replace(v) for k, v in value.items()}
        return value
    packet = replace(packet)
    put(root, 'software/revise.py', Path(__file__).read_text())
    put(root, 'software/control-r1.py', (Path(__file__).parent / 'control.py').read_text())
    packet['section_packets'][0]['baseline'] = {'path': 'manuscript/main.tex', 'sha256': digest(root / 'manuscript/main.tex')}
    packet['artifacts'] += ['manuscript/main.tex', 'manuscript/submission.tex', 'review/revision-r1.json', 'manuscript/references.bib', 'software/revise.py', 'software/control-r1.py']
    changes = [{'baseline': {'path': before, 'sha256': digest(root / before)}, 'after': after,
        'reason': 'Independent R0: compound surname and reference locator/notes; constrain result floats before Discussion; move submission Fig1 caption to first-reference paragraph; correct the inaccurate statement that Pipeline never passes training y to the imputer (it passes y, which KNNImputer ignores). No experiment, reported value or scientific conclusion changed.'}
        for before, after in replacements.items() if before.endswith(('.tex', '.bib'))]
    put(root, 'review/revision-r1.json', {'status': 'revised', 'changes': changes, 'reports': reports, 'scientific_values_changed': False})
    put(root, 'write/packet-r1.json', packet)
    print(invoke(root, 'commit', '--packet', 'write/packet-r1.json', '--operation-id', 'accept-real-write-r1')['stage'])
    for before in sorted((root / 'bindings/r0').glob('*.json')):
        binding = load(root, str(before.relative_to(root)))
        binding = replace(binding)
        if binding['work_id'] == 'W-writing': binding['work_id'] = 'W-main-r1'
        name = 'bindings/r1/' + before.name
        put(root, name, binding)
        invoke(root, 'bind', '--packet', name, '--operation-id', 'bind-real-r1-' + before.stem)
    put(root, 'control/context-review-r1.json', invoke(root, 'context'))
    print('Actual R1 manuscript and all nine bindings are ready for independent review.')


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
