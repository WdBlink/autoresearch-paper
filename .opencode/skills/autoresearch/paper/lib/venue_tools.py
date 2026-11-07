"""Scriptable venue comparison and accepted-paper calibration packets.

These helpers measure and check bytes and declarations. A host must actually read
sources, inspect rendered pages, and judge fit; no ranking or acceptance is guessed.
"""
from __future__ import annotations

from datetime import date
import copy
import hashlib
import json


def _planning():
    from . import planning
    return planning


def comparison_digest(report):
    return hashlib.sha256(json.dumps(report, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def comparison_report(packet, root):
    """Check candidate evidence and produce a comparison, without choosing for a human."""
    p = _planning()
    selection = p._dict(packet.get('venue_selection'), 'venue_selection')
    mode = selection.get('mode')
    p._need(mode in {'existing_target', 'candidate_comparison'}, 'Venue selection needs existing_target or candidate_comparison mode')
    candidates = p._list(selection.get('candidates'), 'venue_selection.candidates')
    p._need(mode == 'existing_target' or len(candidates) >= 2, 'An undecided target needs at least two compared venue candidates')
    criteria = p._list(selection.get('criteria'), 'venue_selection.criteria')
    p._need(all(p._text(value) for value in criteria), 'Venue comparison criteria cannot be blank')
    p._need(p._text(selection.get('rationale')), 'Venue selection needs a rationale')
    ids, rows = set(), []
    for candidate in candidates:
        p._dict(candidate, 'venue candidate')
        key = candidate.get('id')
        p._need(p._text(key) and key not in ids, 'Venue candidate IDs must be unique')
        ids.add(key)
        for field in ('venue', 'scope_fit', 'article_type_fit', 'constraints'):
            p._need(p._text(candidate.get(field)), 'Venue candidate missing ' + field)
        p._need(candidate.get('kind') in {'journal', 'conference'}, 'Venue candidate kind must be journal or conference')
        for field in ('advantages', 'limitations'):
            p._need(all(p._text(value) for value in p._list(candidate.get(field), 'candidate.' + field)),
                    'Venue comparison needs substantive ' + field)
        for field in ('cost', 'timing'):
            value = p._dict(candidate.get(field), 'candidate.' + field)
            p._need(value.get('status') in {'known', 'unknown'} and p._text(value.get('basis')),
                    'Candidate ' + field + ' must state known/unknown and its source or uncertainty')
        evidence = p._list(candidate.get('evidence'), 'candidate.evidence')
        for source in evidence:
            path = p._evidence(root, packet, source, 'Candidate source')
            quote = source.get('quote')
            p._need(p._text(quote) and quote in path.read_text(encoding='utf-8'),
                    'Venue candidate quote is absent from its actual source')
        rows.append(copy.deepcopy(candidate))
    selected = selection.get('selected_id')
    p._need(selected in ids, 'Selected venue candidate is absent from the comparison')
    row = next(candidate for candidate in rows if candidate['id'] == selected)
    p._need(row['venue'] == packet.get('venue'), 'Selected candidate does not match the venue packet')
    return {'version': 1, 'mode': mode, 'criteria': list(criteria), 'candidates': rows,
            'selected_id': selected, 'selected_venue': row['venue'], 'rationale': selection['rationale'],
            'status': 'existing_target' if mode == 'existing_target' else 'requires_human_confirmation',
            'limits': 'Source/quote checking does not establish semantic fit or guarantee editorial acceptance.'}


def validate_selection(packet, root):
    p = _planning()
    report = comparison_report(packet, root)
    brief = packet.get('_brief', {})
    known_target = brief.get('venue') not in (None, '', 'undecided')
    if report['mode'] == 'existing_target':
        p._need(known_target and report['selected_venue'] == brief['venue'],
                'Existing-target mode requires the exact previously chosen Brief venue')
    else:
        if known_target:
            p._need(report['selected_venue'] == brief['venue'], 'Venue comparison cannot change an already approved target')
        receipt = packet.get('_venue_confirmation')
        p._need(isinstance(receipt, dict), 'Compared venues require an actual controller-recorded human selection')
        p._need(receipt.get('candidate_id') == report['selected_id']
                and receipt.get('venue') == report['selected_venue']
                and receipt.get('comparison_sha256') == comparison_digest(report),
                'Venue confirmation is stale or names another candidate/comparison')
    return report


def sampling_report(packet, records):
    """Apply the Deli local 8–15-paper and recent-edition/year default policy."""
    p = _planning()
    policy = p._dict(packet.get('sampling_policy'), 'sampling_policy')
    kind = policy.get('kind')
    p._need(kind in {'journal', 'conference'}, 'Sampling policy kind must be journal or conference')
    try:
        as_of = date.fromisoformat(policy.get('as_of', ''))
    except (TypeError, ValueError) as error:
        raise p.PlanningError('Sampling policy needs an explicit ISO as_of date') from error
    count = len(records)
    fixture = packet.get('software_fixture') is True
    fixture_reason = policy.get('fixture_exception_reason')
    if fixture:
        p._need(p._text(fixture_reason), 'Software fixture needs an explicit sample-policy exception reason')
    count_reason = policy.get('sample_count_deviation_reason')
    concrete = lambda value: p._text(value) and len(value.strip()) >= 20 and value.strip().lower() not in {'todo', 'unknown', 'pending'}
    if not 8 <= count <= 15:
        p._need(concrete(count_reason) or (fixture and concrete(fixture_reason)),
                'Venue calibration defaults to 8–15 accepted papers; count deviation needs a concrete reason')
    editions = policy.get('recent_editions')
    if kind == 'conference':
        p._need(isinstance(editions, list) and len(editions) == 2 and len(set(editions)) == 2
                and all(type(value) is int and 1900 <= value <= as_of.year for value in editions),
                'Conference sampling must identify its two most recent completed editions')
        in_window = lambda record: record['year'] in editions
        window = {'basis': 'recent_two_completed_editions', 'editions': sorted(editions, reverse=True)}
    else:
        try:
            start = as_of.replace(year=as_of.year - 2)
        except ValueError:  # February 29 has no counterpart in a common year.
            start = as_of.replace(year=as_of.year - 2, day=28)
        def in_window(record):
            if record.get('publication_date'):
                try:
                    published = date.fromisoformat(record['publication_date'])
                except (TypeError, ValueError) as error:
                    raise p.PlanningError('Journal publication_date must be ISO date') from error
                p._need(published.year == record['year'], 'Publication date and sample year disagree')
                return start <= published <= as_of
            # Year-only metadata cannot establish which side of the boundary
            # date a paper occupies; retaining it needs a stated deviation.
            return start.year < record['year'] <= as_of.year
        window = {'basis': 'last_two_years', 'start': start.isoformat(), 'end': as_of.isoformat(),
                  'year_only_boundary': 'A boundary-year sample needs an exact publication_date or a deviation reason.'}
    outside = [record['sample_id'] for record in records if not in_window(record)]
    window_reason = policy.get('time_window_deviation_reason')
    if outside:
        p._need(concrete(window_reason) or (fixture and concrete(fixture_reason)),
                'Accepted-paper samples outside the recent window need a concrete time-window deviation reason')
    all_warnings = [{'sample_id': record['sample_id'], 'warnings': record.get('warnings', [])}
                    for record in records if record.get('warnings')]
    if all_warnings:
        p._need(p._text(policy.get('measurement_warning_review')),
                'PDF measurement warnings require a visible review/limitation note')
    return {'default_count': {'min': 8, 'max': 15}, 'actual_count': count,
            'count_in_default_range': 8 <= count <= 15, 'count_deviation_reason': count_reason or None,
            'kind': kind, 'as_of': as_of.isoformat(), 'time_window': window,
            'outside_window_samples': outside, 'time_window_deviation_reason': window_reason or None,
            'software_fixture': fixture, 'fixture_exception_reason': fixture_reason if fixture else None,
            'measurement_warnings': all_warnings,
            'measurement_warning_review': policy.get('measurement_warning_review'),
            'budget_is_reference_only': count < 8,
            'limits': 'Edition/year labels and justifications are host claims; source and visual review remain required.'}


def measure_sample(sample, root, packet):
    """Preserve raw extraction and bind host-observed omissions to rendered evidence."""
    p = _planning()
    raw = p.venue_profile.measure_pdf(p._path(root, sample.get('pdf'), packet))
    additions = p._list(sample.get('measurement_additions', []), 'measurement_additions', nonempty=False)
    corrections = p._list(sample.get('measurement_corrections', []), 'measurement_corrections', nonempty=False)
    if not additions and not corrections:
        return raw
    measured = copy.deepcopy(raw)
    reading = p._dict(sample.get('visual_read'), 'sample visual_read')
    p._need(reading.get('method') == 'rendered_pdf' and p._text(reading.get('notes')),
            'Manual measurement additions require actual rendered reading')
    touched = set()
    for mode, addition in [('add', row) for row in additions] + [('correct', row) for row in corrections]:
        p._dict(addition, 'measurement addition')
        plural = addition.get('kind')
        p._need(plural in ('figures', 'tables'), 'Measurement addition kind must be figures or tables')
        number = addition.get('number')
        p._need(type(number) in (int, str) and p.venue_profile.label_number(str(number)) == number,
                'Measurement addition needs a canonical visual number')
        identity = (plural, number)
        p._need(identity not in touched, 'Duplicate manual measurement identity')
        touched.add(identity)
        previous = next((row for row in raw[plural] if row['number'] == number), None)
        if mode == 'add':
            p._need(previous is None, 'Measurement addition duplicates an existing visual')
        else:
            p._need(previous is not None, 'Measurement correction needs an existing raw visual')
            p._need(addition.get('expected_raw') == {key: previous[key] for key in ('page', 'caption')},
                    'Measurement correction does not bind the original extraction')
        page = addition.get('page')
        p._need(type(page) is int and 1 <= page <= raw['pages_total'] and page in reading.get('pages', []),
                'Measurement addition lacks an actual read PDF page')
        p._need(p._text(addition.get('caption')) and p._text(addition.get('reason')),
                'Measurement addition needs its observed caption and omission reason')
        p._need(addition.get('pdf_sha256') == raw['sha256'], 'Measurement addition PDF hash differs')
        evidence = p._dict(addition.get('rendered_evidence'), 'rendered evidence')
        image_path = p._path(root, evidence.get('path'), packet)
        p._need(p._hash(image_path) == evidence.get('sha256'), 'Rendered evidence hash differs')
        from PIL import Image
        try:
            with Image.open(image_path) as image:
                p._need(image.format in ('PNG', 'JPEG'), 'Rendered evidence must be PNG or JPEG')
                image.verify()
        except (OSError, ValueError) as exc:
            raise p.PlanningError('Rendered evidence is not a valid image') from exc
        panels = p._list(addition.get('panels', []), 'addition panels', nonempty=False)
        p._need(all(p._text(label) for label in panels) and len(panels) == len(set(panels)),
                'Addition panel labels must be unique text')
        record = {'number': number, 'label_text': str(number), 'page': page,
                  'caption': addition['caption'], 'measurement_origin': 'host_rendered_reading'}
        if plural == 'figures':
            record.update(panels=panels, panel_count=len(panels))
        else:
            p._need(not panels, 'Table measurement additions use semantic panels only in design')
            record['result_hint'] = bool(p.venue_profile.RESULT_HINT.search(addition['caption']))
        if mode == 'correct':
            measured[plural] = [row for row in measured[plural] if row['number'] != number]
        measured[plural].append(record)
    for plural in ('figures', 'tables'):
        measured[plural].sort(key=lambda row: p.venue_profile.label_sort_key(row['number']))
    measured['counts'] = {'figures': len(measured['figures']), 'tables': len(measured['tables']),
        'figure_panels': sum(row['panel_count'] for row in measured['figures']),
        'result_tables': sum(bool(row['result_hint']) for row in measured['tables'])}
    measured['raw_extraction'] = raw
    measured['measurement_additions'] = copy.deepcopy(additions)
    measured['measurement_corrections'] = copy.deepcopy(corrections)
    measured['warnings'].append('Host rendered-reading additions/corrections are included; image hashes bind evidence, not semantic correctness or exhaustive coverage.')
    return measured


def design_template(packet, root):
    """Prefill only measurable fields; empty semantic fields require actual reading."""
    p = _planning()
    papers = {}
    for sample in p._list(packet.get('samples'), 'venue.samples'):
        p._dict(sample, 'venue sample')
        sample_id = sample.get('id')
        p._need(p._text(sample_id) and sample_id not in papers, 'Sample IDs must be unique')
        measured = measure_sample(sample, root, packet)
        entry = {'visual_read': {'pages': [], 'method': 'rendered_pdf', 'notes': ''}, 'figures': [], 'tables': []}
        for plural, letter in (('figures', 'F'), ('tables', 'T')):
            for visual in measured[plural]:
                row = {'id': f"{sample_id}-{letter}{visual['number']}", 'number': visual['number'],
                       'page': visual['page'], 'caption': visual['caption'], 'type': '', 'placement': '',
                       'question': '', 'claim': '', 'evidence': '', 'design_takeaway': '', 'limitations': ''}
                row['panels'] = [{'label': label, 'question': '', 'claim': '', 'evidence': '',
                                  'design_takeaway': '', 'limitations': ''} for label in visual.get('panels', [])]
                entry[plural].append(row)
        papers[sample_id] = entry
    return {'version': 1, 'papers': papers,
            'status': 'requires_actual_rendered_page_reading_and_semantic_completion',
            'limits': 'PDF text captions/page numbers and panel labels are heuristic, not semantic ground truth.'}


def validate_design(sample, measured):
    p = _planning()
    design = p._dict(sample.get('design'), 'sample design')
    read = p._dict(sample.get('visual_read'), 'sample visual_read')
    pages = p._list(read.get('pages'), 'visual_read.pages')
    p._need(all(type(value) is int and 1 <= value <= measured['pages_total'] for value in pages),
            'Visual-read pages must name actual PDF pages')
    p._need(read.get('method') == 'rendered_pdf' and p._text(read.get('notes')),
            'Per-visual design requires an actual rendered-PDF reading declaration')
    used = set()
    for plural, allowed in (('figures', p.venue_profile.FIGURE_TYPES), ('tables', p.venue_profile.TABLE_TYPES)):
        entries = p._list(design.get(plural, []), 'sample design.' + plural, nonempty=False)
        expected = {record['number']: record for record in measured[plural]}
        p._need(len(entries) == len(expected), 'Design notes must cover every measured ' + plural)
        numbers = []
        for entry in entries:
            p._dict(entry, 'sample design visual')
            identifier = entry.get('id')
            number = entry.get('number')
            p._need(p._text(identifier) and identifier not in used, 'Each visual needs a unique stable ID')
            used.add(identifier)
            p._need(type(number) in (int, str) and number in expected,
                    'Visual number differs from measured PDF evidence')
            numbers.append(number)
            raw = expected[number]
            p._need(entry.get('page') == raw['page'] and entry.get('page') in pages,
                    'Visual design lacks the recorded PDF page reading')
            p._need(entry.get('caption') == raw['caption'], 'Visual caption differs from measured PDF evidence')
            p._need(entry.get('type') in allowed and entry.get('placement') in p.venue_profile.PLACEMENTS,
                    'Visual needs a supported argument type and actual placement')
            for field in ('question', 'claim', 'evidence', 'design_takeaway', 'limitations'):
                p._need(p._text(entry.get(field)), 'Per-visual design missing ' + field)
            p._need(entry['question'] != entry['claim'], 'Visual claim must answer a question rather than repeat it')
            panels = p._list(entry.get('panels'), 'visual.panels', nonempty=False)
            labels = [panel.get('label') for panel in panels if isinstance(panel, dict)]
            p._need(len(labels) == len(panels) == len(set(labels)) and all(p._text(label) for label in labels),
                    'Per-panel design needs unique nonempty panel labels')
            if set(labels) != set(raw.get('panels', [])):
                p._need(p._text(entry.get('panel_measurement_note')),
                        'Per-panel design must cover detected panel labels or explain the rendered-page correction')
            for panel in panels:
                for field in ('question', 'claim', 'evidence', 'design_takeaway', 'limitations'):
                    p._need(p._text(panel.get(field)), 'Per-panel design missing ' + field)
        p._need(len(set(numbers)) == len(expected), 'Per-visual design duplicated or omitted a measured number')
    return copy.deepcopy(design)


def page_budget_report(packet, root, records):
    """Keep official counting rules separate from heuristic sample statistics."""
    p = _planning()
    budget = p._dict(packet.get('page_budget'), 'page_budget')
    basis = budget.get('basis')
    limit_type = budget.get('limit_type')
    p._need(basis in {'official_requirement', 'sample_inference', 'unknown'}, 'Unknown page-budget evidence basis')
    p._need(limit_type in {'hard_limit', 'target', 'unlimited', 'unknown'}, 'Unknown page-budget limit_type')
    p._need(p._text(budget.get('reason')), 'Page budget needs its source and applicability explanation')
    target = budget.get('target')
    if limit_type in {'hard_limit', 'target'}:
        p._need(type(target) is int and target > 0, 'Page budget target must be a positive integer')
    else:
        p._need(target is None, 'Unknown/unlimited page budget must not invent a numerical target')
    for field in ('includes_references', 'includes_appendix'):
        p._need(type(budget.get(field)) is bool or (basis == 'unknown' and budget.get(field) is None),
                'Page budget must explicitly state reference and appendix counting')
    if basis == 'official_requirement':
        source = budget.get('source')
        path = p._evidence(root, packet, source, 'Official page-budget source')
        p._need(source.get('path') == packet.get('official_rules', {}).get('path'),
                'Page budget official basis must bind the selected author rules')
        p._need(p._text(source.get('quote')) and source['quote'] in path.read_text(encoding='utf-8'),
                'Official page-budget quote is absent from the source')
    elif basis == 'sample_inference':
        p._need(limit_type == 'target', 'Sample page measurements cannot become an official hard limit')
        selected = p._list(budget.get('sample_ids'), 'page_budget.sample_ids')
        expected = {record['sample_id'] for record in records}
        p._need(len(selected) == len(set(selected)) and set(selected) <= expected, 'Inferred page budget names unknown/duplicate samples')
        bases = {record['pages_basis'] for record in records if record['sample_id'] in selected}
        p._need(len(bases) == 1, 'Mixed sample page-count bases cannot define one inferred page target')
        if budget['includes_references']:
            p._need(budget['includes_appendix'], 'Total-page inference cannot silently exclude appendix pages')
        else:
            p._need(bases == {'references_heading'}, 'Body-page inference cannot use total-page fallback as references-excluded')
            p._need(p._text(budget.get('measurement_limitations')),
                    'References-heading page inference must disclose shared-page/appendix measurement limitations')
    else:
        p._need(limit_type == 'unknown', 'Unknown page-budget evidence must retain unknown limit_type')
    return {'selected_rule': copy.deepcopy(budget),
            'sample_statistics': [{'sample_id': row['sample_id'], 'pages_total': row['pages_total'],
                                   'pages_main_body': row['pages_main_body'], 'pages_basis': row['pages_basis']}
                                  for row in records],
            'limits': 'References-heading/body pages are heuristic and cannot certify compliance with reference/appendix exclusions.'}
