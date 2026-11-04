"""Prepare independent judgments and assemble their exact, variable-size contract."""
import copy
import hashlib
from pathlib import Path

from .runtime import digest, file_hash, read_json, safe
from .production import json_bytes, require, write_once, observed

GATES = {'G1', 'G2', 'G3', 'G4', 'G5', 'R6'}


def request(root, context):
    require(context.get('stage') == 'review', 'Prepare review after writing and all bindings')
    requirements = context['brief']['deliverable_plan']
    bindings = context['bindings']
    require(set(bindings) == {item['id'] for item in requirements}, 'Bind every approved requirement before review')
    inputs = {record['stage']: record for record in context['inputs']}
    require('write' in inputs and 'plan' in inputs and 'literature' in inputs, 'Review needs accepted write, plan and literature evidence')
    hashes = {name: value for record in inputs.values() for name, value in record['hashes'].items()}
    for binding in bindings.values():
        require(all(hashes.get(name) == value for name, value in binding['hashes'].items()), 'Binding differs from accepted evidence')
    require(all(file_hash(safe(root, name)) == value for name, value in hashes.items()), 'Review inputs are stale')
    original = read_json(safe(root, inputs['plan']['packet']['plan_snapshot']))
    guidance = context.get('knowledge', '')
    require(isinstance(guidance, str) and hashlib.sha256(guidance.encode()).hexdigest() == context.get('knowledge_sha256'),
            'Review guidance differs from the supplied stage context')
    core = {'schema_version': 1, 'purpose': 'independent_review', 'brief': context['brief'],
            'brief_sha256': digest(context['brief']), 'bindings': copy.deepcopy(bindings),
            'inputs': [{'stage': record['stage'], 'packet': record['packet']} for record in inputs.values()],
            'input_hashes': hashes, 'knowledge_sha256': context.get('knowledge_sha256'),
            'review_guidance': guidance,
            'judgment_template': {
                'reviewer': None, 'reviewer_identity': {}, 'reports': [], 'findings': [],
                'requirement_checks': [{'requirement_id': key, 'binding_sha256': value['binding_sha256'],
                                        'verdict': 'not_checked', 'rationale': ''} for key, value in bindings.items()],
                'gates': {key: {'verdict': 'not_checked', 'reason': '', 'evidence': []} for key in sorted(GATES)},
                'r6_reviews': [{'id': item['id'], 'verdict': 'not_checked', 'reason': '', 'evidence_locations': []} for item in original['items']]},
            'response_contract': {
                'reviewer': 'An actually executed independent reviewer declared in the Brief',
                'request_sha256': 'Copy this request digest; do not rewrite the request',
                'reports': 'Paths of actual nonempty review evidence, including reviewer identity and scope',
                'reviewer_identity': 'Actual host/model identity and independence boundary; software checks must say software_fixture',
                'findings': '[{id,severity,status,...}]; final assembly requires every finding closed',
                'requirement_checks': '[{requirement_id,binding_sha256,verdict,rationale}] for every approved ID',
                'gates': '{G1,G2,G3,G4,G5,R6}: {verdict,reason,evidence:[actual report paths]}',
                'r6_reviews': '[{id,verdict,reason,evidence_locations}] for every original visual; deviations need disclosure_quote',
                'verdicts': {'requirements': ['fulfilled', 'unmet', 'blocked', 'not_checked'],
                             'gates': ['pass', 'revise', 'fail', 'not_applicable', 'not_checked'],
                             'findings_status': ['open', 'closed'],
                             'r6': ['fulfilled', 'disclosed_deviation', 'scientifically_adjusted', 'not_applicable', 'not_checked']},
                'boundary': 'Program integrity does not prove actual independent execution or semantic correctness'}}
    return {**core, 'request_sha256': digest(core)}


def prepare(packet, root):
    context = read_json(safe(root, packet['context']))
    value = request(root, context)
    write_once(root, packet['target'], json_bytes(value))
    return observed(root, [packet['target']], status='needs_independent_judgment', request_sha256=value['request_sha256'],
                    schema=value['response_contract'])


def assemble(packet, root):
    """Copy facts/hashes from a request; the host supplies only its actual judgments."""
    from . import science, planning
    frozen = read_json(safe(root, packet['request']))
    core = {key: value for key, value in frozen.items() if key != 'request_sha256'}
    require(digest(core) == frozen.get('request_sha256'), 'Review request digest differs')
    require(all(file_hash(safe(root, name)) == value for name, value in frozen['input_hashes'].items()), 'Review request evidence changed')
    judgment = read_json(safe(root, packet['judgment']))
    require(judgment.get('request_sha256') == frozen['request_sha256'], 'Review judgment is for a different request')
    reviewer = judgment.get('reviewer')
    identity = judgment.get('reviewer_identity')
    require(isinstance(identity, dict) and identity, 'Record the actual reviewer identity and independence boundary')
    findings = judgment.get('findings')
    require(isinstance(findings, list) and all(isinstance(item, dict) and item.get('status') == 'closed' for item in findings),
            'Unresolved independent findings prevent final assembly')
    authors = {item['packet']['producer'] for item in frozen['inputs']}
    require(reviewer in frozen['brief'].get('reviewers', []) and reviewer not in authors, 'Actual reviewer must be declared and independent from producers')
    reports = judgment.get('reports')
    require(isinstance(reports, list) and reports and len(reports) == len(set(reports)), 'Declare the actual independent review report paths')
    require(all(safe(root, name).read_bytes().strip() for name in reports), 'Empty review evidence')
    checks = judgment.get('requirement_checks')
    require(isinstance(checks, list) and len(checks) == len(frozen['bindings']) and
            {item.get('requirement_id') for item in checks} == set(frozen['bindings']), 'Review every approved ID exactly once')
    actual_checks = []
    for check in checks:
        binding = frozen['bindings'][check['requirement_id']]
        require(check.get('binding_sha256') == binding['binding_sha256'] and check.get('verdict') == 'fulfilled' and bool(check.get('rationale')),
                'Unmet or stale independent requirement: ' + check['requirement_id'])
        actual_checks.append({**check, 'evidence_hashes': copy.deepcopy(binding['hashes'])})
    gates = judgment.get('gates')
    require(isinstance(gates, dict) and set(gates) == GATES, 'Actual judgments must address G1–G5 and R6')
    for key, gate in gates.items():
        allowed_na = key == 'G2' and gate.get('verdict') == 'not_applicable' and gate.get('reason') == frozen['brief'].get('not_applicable', {}).get('experiment')
        require(gate.get('verdict') == 'pass' or allowed_na, 'Unresolved quality gate: ' + key)
        require(gate.get('reason') and isinstance(gate.get('evidence'), list) and gate['evidence'] and set(gate['evidence']) <= set(reports),
                'A gate needs its actual declared independent report evidence')
    history = {item['stage']: item['packet'] for item in frozen['inputs']}
    write, literature, plan = (history[key] for key in ['write', 'literature', 'plan'])
    config = packet.get('completion', {})
    require(isinstance(config, dict), 'completion configuration must be an object')
    allowed = {'extra_source', 'extra_pdf', 'review', 'revision', 'extra_artifacts', 'snapshot', 'r6_report'}
    require(set(config) <= allowed, 'Unknown completion configuration field')
    accepted_paths = list(frozen['input_hashes'])
    bundle = science._source_bundle({'manuscript': write['manuscript'], 'artifacts': accepted_paths}, root)
    completion = {'source': list(bundle), 'pdf': [write['manuscript_pdf']],
                  **{key: [literature[key]] for key in ['bibliography', 'citation_plan', 'citation_verification']},
                  'review': list(dict.fromkeys([*reports, *config.get('review', [])])),
                  'revision': config.get('revision', []), 'snapshot': [config['snapshot']]}
    for key in ['source', 'pdf']:
        completion[key] = list(dict.fromkeys([*completion[key], *config.get('extra_' + key, [])]))
    variant = write.get('submission_variant')
    if variant:
        for role, field in [('source', 'source'), ('pdf', 'pdf')]:
            if variant[field] not in completion[role]:
                completion[role].append(variant[field])
    require(completion['revision'], 'Supply the actual initial-draft or revision identity; do not invent one')
    artifacts = list(dict.fromkeys([name for role, paths in completion.items() if role != 'snapshot' for name in paths] +
                                  config.get('extra_artifacts', []) + [packet['request'], packet['judgment'], plan['figure_table_plan'], plan['plan_snapshot']]))
    for path in completion['revision']:
        revision = read_json(safe(root, path))
        for change in revision.get('changes', []):
            for name in [change['baseline']['path'], change['after']]:
                if name not in artifacts:
                    artifacts.append(name)
    r6_name = config['r6_report']
    result = {'stage': 'review', 'producer': reviewer, 'reviewer': reviewer, 'artifacts': artifacts,
              'manuscript_pdf': write['manuscript_pdf'], 'figure_table_plan': plan['figure_table_plan'],
              'plan_snapshot': plan['plan_snapshot'], 'requirement_checks': actual_checks, 'gates': gates,
              'r6_reviews': judgment.get('r6_reviews'), 'completion': completion,
              'reviewer_identity': identity, 'findings': findings,
              'review_request': {'path': packet['request'], 'sha256': file_hash(safe(root, packet['request']))}}
    augmented = {**result, '_history': history, '_brief': frozen['brief']}
    mechanical = planning.review_plan(augmented, root)
    planning.review(augmented, root)
    write_once(root, r6_name, json_bytes(mechanical)); artifacts.append(r6_name)
    snapshot = {'files': {name: file_hash(safe(root, name)) for name in artifacts}}
    write_once(root, config['snapshot'], json_bytes(snapshot)); artifacts += completion['snapshot']
    # Validate exactly the inferred roles and current source closure before writing the packet.
    issues = science.validate_delivery({**result, '_history': {**history, 'review': result}, '_brief': frozen['brief']}, root)
    require(not issues, '; '.join(issues))
    write_once(root, packet['target'], json_bytes(result))
    return observed(root, [packet['target'], r6_name, config['snapshot']],
                    status='assembled_not_committed', requirements=len(actual_checks), original_visuals=len(result['r6_reviews']),
                    completion_roles=list(completion), reviewer=reviewer)
