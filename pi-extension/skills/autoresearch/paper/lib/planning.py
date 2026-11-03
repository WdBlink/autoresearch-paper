"""Research intake, venue calibration and R6 evidence checks.

The migrated local Deli helpers remain state-free at this boundary. This module
never calls their ledger-writing CLI commands and never grants research approval.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone
from urllib.parse import urlsplit

VENDOR = Path(__file__).resolve().parents[1] / 'vendor' / 'deli-local' / 'scripts'


def _module(name):
    spec = importlib.util.spec_from_file_location('paper_local_' + name, VENDOR / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


venue_profile = _module('venue_profile')
plan_audit = _module('plan_audit')
deliverable_contract = _module('deliverable_contract')


class PlanningError(ValueError):
    pass


def _need(condition, message):
    if not condition:
        raise PlanningError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _list(value, label, nonempty=True):
    _need(isinstance(value, list) and (value or not nonempty), label + ' must be an array' + (' with entries' if nonempty else ''))
    return value


def _dict(value, label):
    _need(isinstance(value, dict), label + ' must be an object')
    return value


def _path(root, name, packet=None):
    _need(_text(name) and not Path(name).is_absolute() and '..' not in Path(name).parts,
          'Expected a run-relative evidence path: ' + str(name))
    _need(Path(name).parts[0] not in {'.paper', '.git', 'delivery'}, 'Evidence must not use controller-owned paths')
    path = Path(root) / name
    current = Path(root)
    for part in Path(name).parts:
        current /= part
        _need(not current.is_symlink(), 'Evidence symlinks are not allowed: ' + name)
    _need(path.resolve().is_relative_to(Path(root).resolve()) and path.is_file(), 'Missing evidence: ' + name)
    if packet is not None:
        _need(name in packet.get('artifacts', []), 'Evidence is absent from packet.artifacts: ' + name)
    return path


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(PlanningError('Non-finite JSON value: ' + x)))


def _artifact(root, packet, key):
    return _path(root, packet.get(key), packet)


def _evidence(root, packet, record, label):
    _dict(record, label)
    path = _path(root, record.get('path'), packet)
    _need(record.get('sha256') == _hash(path), label + ' has stale or missing SHA-256')
    url = record.get('url', '')
    _need(_text(url) and urlsplit(url).scheme == 'https' and urlsplit(url).hostname,
          label + ' needs a source HTTPS URL')
    if not packet.get('software_fixture'):
        host = urlsplit(url).hostname
        _need(not host.endswith(('.invalid', '.example')) and host != 'example.com',
              label + ' uses a fixture URL in real research')
    return path


def _quote(record, materials, label):
    _dict(record, label)
    entry = materials.get(record.get('material_id'))
    _need(entry is not None and entry['availability'] == 'readable', label + ' must cite a readable material')
    start, end = record.get('start'), record.get('end')
    _need(type(start) is int and type(end) is int and 0 <= start < end <= len(entry['text']), label + ' has an invalid span')
    _need(any(a <= start and end <= b for a, b in entry['read_spans']), label + ' cites a span that was not read')
    _need(_text(record.get('quote')) and record['quote'] == entry['text'][start:end], label + ' quote does not match the recorded span')


def intake(packet, root):
    materials = {}
    for index, raw in enumerate(_list(packet.get('materials'), 'intake.materials')):
        record = _dict(raw, 'material')
        key = record.get('id')
        _need(_text(key) and key not in materials, 'Material IDs must be unique and nonempty')
        path = _path(root, record.get('path'), packet)
        _need(record.get('sha256') == _hash(path), 'Material ' + key + ' changed')
        availability = record.get('availability')
        _need(availability in {'readable', 'metadata_only'}, 'Material availability must distinguish readable and metadata_only')
        entry = {**record, 'text': None}
        if availability == 'metadata_only':
            _need(_text(record.get('limitation')), 'Metadata-only material ' + key + ' needs its unread-content limitation')
            _need(not record.get('read_spans'), 'Metadata-only material cannot claim content reads')
        else:
            text = path.read_text(encoding='utf-8')
            spans = _list(record.get('read_spans'), 'material.read_spans')
            for span in spans:
                _need(isinstance(span, list) and len(span) == 2 and all(type(x) is int for x in span)
                      and 0 <= span[0] < span[1] <= len(text), 'Material ' + key + ' has invalid read spans')
            reached = 0
            for start, end in sorted(spans):
                _need(start <= reached, 'Readable material ' + key + ' has an unread span')
                reached = max(reached, end)
            _need(reached == len(text), 'Readable material ' + key + ' was only partially read')
            entry['text'] = text
        materials[key] = entry
    for record in _list(packet.get('evidence'), 'intake.evidence'):
        _quote(record, materials, 'Intake evidence')
    feasibility = _dict(packet.get('feasibility'), 'intake.feasibility')
    status = feasibility.get('status')
    _need(status in {'feasible', 'conditional', 'blocked'}, 'Unknown feasibility status')
    options = _list(feasibility.get('options'), 'feasibility.options')
    _need(len(options) >= 2 or _text(feasibility.get('single_option_reason')), 'Compare two routes or justify a single standard route')
    selected = feasibility.get('selected_option')
    ids = set()
    for option in options:
        _dict(option, 'feasibility option')
        key = option.get('id')
        _need(_text(key) and key not in ids, 'Feasibility option IDs must be unique')
        ids.add(key)
        for field in ('implementation', 'selection_reason'):
            _need(_text(option.get(field)), 'Feasibility option missing ' + field)
        evidence = option.get('evidence', [])
        _need(isinstance(evidence, list), 'Option evidence must be an array')
        for record in evidence:
            _quote(record, materials, 'Option evidence')
        _need(evidence or option.get('basis') == 'assumption', 'Unsupported option must be labelled assumption')
        if key == selected and status == 'feasible':
            _need(bool(evidence) and option.get('basis') != 'assumption', 'Selected feasible route needs actually read evidence')
    _need(selected in ids, 'Selected feasibility route is missing')
    resources = _dict(feasibility.get('resources'), 'feasibility.resources')
    for field in ('authorization', 'cost_basis'):
        _need(_text(resources.get(field)), 'Resource assessment missing ' + field)
    if status == 'conditional':
        _list(feasibility.get('prerequisites'), 'conditional prerequisites')
    if status == 'blocked':
        _list(feasibility.get('blocking_questions'), 'blocking questions')
    experiments = feasibility.get('experiments', [])
    _need(isinstance(experiments, list), 'Feasibility experiments must be an array')
    if not experiments:
        _need(_text(feasibility.get('no_experiment_reason')), 'No experimental plan requires an explicit reason')
        brief = packet.get('_brief', {})
        _need(brief.get('paper_type') in {'review', 'survey'} and _text(brief.get('not_applicable', {}).get('experiment')),
              'Omitting experiments requires the exact approved review/survey applicability reason')
    for experiment in experiments:
        _dict(experiment, 'feasibility experiment')
        for field in ('claim', 'metric', 'comparison', 'protocol', 'completion', 'failure_route'):
            _need(_text(experiment.get(field)), 'Experiment feasibility missing ' + field)


def plan_snapshot(plan_path):
    path = Path(plan_path)
    plan = _json(path)
    return {'plan_path': str(path), 'sha256': _hash(path),
            'captured_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'items': copy.deepcopy(plan.get('items', [])),
            'pending_visuals': copy.deepcopy(plan.get('pending_visuals', [])),
            'original_promise_set': copy.deepcopy(plan.get('original_promise_set')),
            'plan_change_log': copy.deepcopy(plan.get('plan_change_log', []))}


def calibrate(packet, root):
    """Measure actual accepted-paper PDFs and recompute the venue budget and plan."""
    root = Path(root)
    for field in ('venue', 'direction', 'paper_type'):
        _need(_text(packet.get(field)), 'Venue calibration missing ' + field)
    rules = packet.get('official_rules')
    _evidence(root, packet, rules, 'Official rules')
    _need(rules.get('basis') == 'official_requirement', 'Official rules and sample preferences must be distinguished')
    template = _dict(packet.get('template'), 'template')
    if template.get('status') == 'available':
        _evidence(root, packet, template, 'Official template')
    else:
        _need(template.get('status') == 'not_available' and _text(template.get('reason')),
              'Template must be available or explicitly unavailable with a reason')
        _need(template.get('evidence') == rules['path'], 'Unavailable template needs the actual official-rule evidence')
    records, designs, ids, pdf_hashes = [], {}, set(), set()
    samples = _list(packet.get('samples'), 'venue.samples')
    _need(len(samples) >= 3 or _text(packet.get('sampling_limitations')), 'Fewer than three samples needs a sampling limitation')
    for sample in samples:
        _dict(sample, 'venue sample')
        sample_id = sample.get('id')
        _need(_text(sample_id) and sample_id not in ids, 'Venue sample IDs must be unique')
        ids.add(sample_id)
        path = _path(root, sample.get('pdf'), packet)
        _need(path.suffix.lower() == '.pdf', 'Representative samples must be actual PDFs')
        sha = _hash(path)
        _need(sha not in pdf_hashes, 'The same paper cannot count as multiple independent venue samples')
        pdf_hashes.add(sha)
        _need(sample.get('venue_label') == packet['venue'], 'Representative sample venue does not match the selected venue')
        _need(type(sample.get('year')) is int and sample['year'] >= 1900, 'Representative sample missing publication year')
        _need(_text(sample.get('direction_match')), 'Representative sample needs its direction-match reason')
        _evidence(root, packet, sample.get('acceptance_evidence'), 'Sample acceptance evidence')
        measured = venue_profile.measure_pdf(path)
        record = {**measured, 'source': sample['pdf'], 'sample_id': sample_id, 'venue_label': sample['venue_label'],
                  'year': sample['year'], 'acceptance_evidence': sample['acceptance_evidence'],
                  'direction_match': sample['direction_match']}
        records.append(record)
        design = _dict(sample.get('design'), 'sample design')
        for plural in ('figures', 'tables'):
            entries = _list(design.get(plural, []), 'sample design.' + plural, nonempty=False)
            _need(len(entries) == measured['counts'][plural], 'Design notes must cover each measured ' + plural)
            for item in entries:
                _dict(item, 'sample design item')
                allowed = venue_profile.FIGURE_TYPES if plural == 'figures' else venue_profile.TABLE_TYPES
                _need(item.get('type') in allowed, 'Unknown sample design type')
                _need(item.get('placement') in venue_profile.PLACEMENTS, 'Sample design needs actual placement')
        designs[sample_id] = design
    profile = venue_profile.build_profile(records, packet['venue'], packet['direction'], {'papers': designs})
    plan = _json(_artifact(root, packet, 'figure_table_plan'))
    checked = venue_profile.check_plan(profile, plan)
    return {'measurements': records, 'venue_profile': profile, 'venue_plan_check': checked}


def _without_clock(value):
    if isinstance(value, dict):
        return {key: _without_clock(item) for key, item in value.items() if key != 'generated_at'}
    if isinstance(value, list):
        return [_without_clock(item) for item in value]
    return value


def venue(packet, root):
    computed = calibrate(packet, root)
    brief = packet.get('_brief', {})
    for field in ('venue', 'direction', 'paper_type'):
        if brief.get(field):
            _need(packet[field] == brief[field], 'Venue calibration changed the approved ' + field)
    for field in ('measurements', 'venue_profile', 'venue_plan_check'):
        actual = _json(_artifact(root, packet, field))
        _need(_without_clock(actual) == _without_clock(computed[field]), 'Stored ' + field + ' differs from recomputed PDF evidence')
    _need(computed['venue_plan_check']['status'] != 'fail', '; '.join(computed['venue_plan_check']['errors']))


def plan(packet, root):
    history = packet.get('_history', {})
    intake_packet = history.get('intake', {})
    if intake_packet:
        _need(intake_packet.get('feasibility', {}).get('status') == 'feasible',
              'Conditional or blocked feasibility cannot become a research plan without resolving intake')
    path = _artifact(root, packet, 'figure_table_plan')
    data = _json(path)
    snapshot = _json(_artifact(root, packet, 'plan_snapshot'))
    _need(snapshot.get('sha256') == _hash(path), 'Plan snapshot hash does not freeze the actual original plan')
    for key, fallback in (('items', []), ('pending_visuals', []), ('original_promise_set', None), ('plan_change_log', [])):
        _need(snapshot.get(key, fallback) == data.get(key, fallback), 'Plan snapshot has different ' + key)
    items = venue_profile.plan_items(data)
    # The migrated item validator is reused only as a pure schema check. Its
    # freeze/bind/review CLI commands would create another state owner.
    brief_items = packet.get('_brief', {}).get('deliverable_plan')
    if brief_items is not None:
        normalized = [{**item, 'claim': item.get('claim') or item.get('purpose', '')} for item in brief_items]
        deliverable_contract.validate_items(normalized)
        expected = {item['id']: item for item in normalized if item['kind'] in {'figure', 'table'}}
        actual = {item.get('id'): item for item in items}
        _need(len(actual) == len(items), 'Figure/table plan has duplicated IDs')
        _need(set(expected) == set(actual), 'Figure/table plan omitted or invented approved visual requirements')
        for identifier, item in actual.items():
            _need(item.get('kind') == expected[identifier]['kind'], 'Figure/table plan changed requirement kind ' + identifier)
    venue_packet = history.get('venue')
    if venue_packet:
        profile = _json(_artifact(root, venue_packet, 'venue_profile'))
        result = venue_profile.check_plan(profile, data)
        _need(result['status'] != 'fail', '; '.join(result['errors']))



def _tex_literal(text):
    lines = []
    for line in text.splitlines():
        cut = len(line)
        for match in re.finditer('%', line):
            backslashes, index = 0, match.start() - 1
            while index >= 0 and line[index] == '\\':
                backslashes += 1
                index -= 1
            if backslashes % 2 == 0:
                cut = match.start()
                break
        lines.append(line[:cut])
    return '\n'.join(lines)


def _tex_options(value):
    if not value:
        return []
    return [part.strip() for part in value.strip('[]').split(',') if part.strip()]


def _documentclass(text):
    clean = _tex_literal(text)
    found = re.findall(r'\\documentclass\s*(\[[^\]]*\])?\s*\{([^{}]*)\}', clean)
    _need(len(found) == 1, 'Template checking requires one explicit literal documentclass declaration')
    options, name = found[0]
    _need(bool(re.fullmatch(r'[A-Za-z0-9_.-]+', name.strip())), 'Document class must be an explicit class name')
    return {'name': name.strip(), 'options': _tex_options(options)}


def write(packet, root):
    venue_packet = packet.get('_history', {}).get('venue')
    _need(isinstance(venue_packet, dict), 'Writing requires the accepted venue and template evidence')
    template = _dict(venue_packet.get('template'), 'accepted template')
    rules = _dict(venue_packet.get('official_rules'), 'accepted official rules')
    source = template if template.get('status') == 'available' else rules
    _need(packet.get('template_source') == source.get('path'), 'Writing changed the accepted template source')
    path = _artifact(root, packet, 'template_source')
    _need(packet.get('template_sha256') == source.get('sha256') == _hash(path), 'Writing template hash differs from the frozen venue source')
    manuscript = _artifact(root, packet, 'manuscript_tex').read_text(encoding='utf-8')
    actual_class = _documentclass(manuscript)
    if template.get('status') == 'available':
        expected_class = _documentclass(path.read_text(encoding='utf-8'))
        _need(actual_class == expected_class, 'Manuscript documentclass/options differ from the accepted official template')
        required = template.get('required_packages', [])
        _need(isinstance(required, list), 'Template required_packages must be an array')
        used = {}
        for options, names in re.findall(r'\\usepackage\s*(\[[^\]]*\])?\s*\{([^{}]*)\}', _tex_literal(manuscript)):
            for name in names.split(','):
                used.setdefault(name.strip(), []).append(_tex_options(options))
        for package in required:
            if isinstance(package, str):
                package = {'name': package}
            _dict(package, 'required package')
            name = package.get('name')
            _need(_text(name) and name in used, 'Manuscript omitted required template package: ' + str(name))
            if 'options' in package:
                options = _list(package['options'], 'required package options', nonempty=False)
                _need(all(_text(value) for value in options) and options in used[name],
                      'Manuscript changed required template package options: ' + name)
    else:
        _need(template.get('status') == 'not_available', 'Unknown template availability')
        check = _dict(packet.get('format_check'), 'no-template format check')
        _need(check.get('basis') == 'official_requirement' and _text(check.get('reason')),
              'No official template requires an explicit source-based format check')
        _need(_text(check.get('evidence_quote')) and check['evidence_quote'] in path.read_text(encoding='utf-8'),
              'Format-check quote is absent from the frozen official rules')
        _need(check.get('documentclass') == actual_class['name'] and check.get('options') == actual_class['options'],
              'Manuscript does not match the explicitly checked no-template format')


def review_plan(packet, root):
    """Recompute R6 mechanics from the frozen snapshot, current plan and real PDF."""
    original = packet.get('_history', {}).get('plan') or packet.get('_plan')
    _need(isinstance(original, dict), 'R6 requires the original accepted plan packet')
    _need(packet.get('plan_snapshot') == original.get('plan_snapshot'), 'R6 must use the original frozen plan snapshot')
    current_path = _artifact(root, packet, 'figure_table_plan')
    snapshot_path = _artifact(root, packet, 'plan_snapshot')
    current, snapshot = _json(current_path), _json(snapshot_path)
    original_path = _artifact(root, original, 'figure_table_plan')
    _need(snapshot.get('sha256') == _hash(original_path), 'R6 snapshot does not match the frozen original plan')
    _need(snapshot.get('items') == _json(original_path).get('items'), 'R6 snapshot changed the original promise set')
    pdf = _artifact(root, packet, 'manuscript_pdf')
    text = venue_profile.pdf_to_text(pdf)
    figures, tables = plan_audit.draft_labels(text)
    measured = venue_profile.measure_pdf(pdf)
    # The older R6 helper recognizes only period captions; the venue parser
    # also recognizes ordinary colon captions and Roman table numbering.
    figures |= {item['number'] for item in measured['figures']}
    tables |= {item['number'] for item in measured['tables']}
    rows, rewrites, _, _ = plan_audit.audit(current, current_path, snapshot_path, text, figures, tables, pdf, _hash(current_path))
    baseline = {**current, 'items': snapshot['items'], 'pending_visuals': snapshot.get('pending_visuals', [])}
    original_rows, _, _, _ = plan_audit.audit(baseline, original_path, None, text, figures, tables, pdf, snapshot['sha256'])
    # Auditing both versions makes removal from the current plan visible even
    # when the renamed/current plan would otherwise obtain a perfect score.
    numbers = plan_audit.audit_numbers(baseline, text)
    realize = venue_profile.check_realize(baseline, measured)
    return {'items': rows, 'original_items': original_rows, 'rewrites': rewrites, 'numbers': numbers, 'realize': realize}


def review(packet, root):
    result = review_plan(packet, root)
    checks = _list(packet.get('r6_reviews'), 'R6 per-item reviews')
    ids = [check.get('id') for check in checks if isinstance(check, dict)]
    expected = {item['id'] for item in result['original_items']}
    _need(len(ids) == len(checks) == len(set(ids)) and set(ids) == expected,
          'R6 must address every original planned item exactly once')
    by_id = {item['id']: item for item in checks}
    changed = {item['id'] for item in result['rewrites']}
    allowed = {'fulfilled', 'disclosed_deviation', 'scientifically_adjusted', 'not_applicable'}
    for row in result['original_items']:
        check = by_id[row['id']]
        _need(check.get('verdict') in allowed and _text(check.get('reason')), 'R6 needs a supported per-item judgment')
        locations = _list(check.get('evidence_locations'), 'R6 evidence locations')
        _need(all(_text(value) for value in locations), 'R6 evidence locations cannot be blank')
        if row['verdict'] != 'fulfilled' or row['id'] in changed:
            _need(check['verdict'] != 'fulfilled', 'R6 cannot call a missing/changed promise fulfilled: ' + row['id'])
            _need(_text(check.get('disclosure_quote')), 'R6 deviation needs its exact disclosure quote')
            pdf_text = venue_profile.pdf_to_text(_artifact(root, packet, 'manuscript_pdf'))
            _need(check['disclosure_quote'] in pdf_text, 'R6 disclosure quote is absent from the manuscript')
        if check['verdict'] == 'fulfilled':
            _need(row['verdict'] == 'fulfilled', 'R6 promise is not mechanically fulfilled')
    _need(all(item['found_in_draft'] for item in result['numbers']), 'R6 found numeric promises absent from the draft')
    _need(result['realize']['status'] != 'fail', '; '.join(result['realize']['errors']))


def validate(stage: str, packet: dict, root: Path) -> list[str]:
    checker = {'intake': intake, 'venue': venue, 'plan': plan, 'write': write, 'review': review, 'delivery': review}.get(stage)
    if checker is None:
        return []
    try:
        _dict(packet, stage + ' packet')
        checker(packet, Path(root))
        return []
    except (PlanningError, OSError, UnicodeError, ValueError, TypeError, KeyError,
            venue_profile.VenueError, deliverable_contract.ContractError, subprocess.SubprocessError, SystemExit) as error:
        return [stage + ': ' + str(error)]
