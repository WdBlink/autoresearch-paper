"""Deterministic round workload and stopping evidence; no research judgment."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib

DEFAULTS = {'session_rounds': 15, 'session_minutes': 30, 'experiment_rounds': 5,
            'refinement_rounds': 12, 'small_gain': .3, 'large_files': 5, 'large_file_lines': 300}


def experimental_scope(brief):
    return not (brief.get('paper_type') in {'review', 'survey'} and brief.get('not_applicable', {}).get('experiment'))


def policy(brief):
    overrides = brief.get('round_limits', {})
    if not isinstance(overrides, dict) or set(overrides) - set(DEFAULTS):
        raise ValueError('Unknown round limit fields')
    limits = {**DEFAULTS, **overrides}
    if any(not isinstance(v, (float, int)) or isinstance(v, bool) or v <= 0 for v in limits.values()):
        raise ValueError('Round limits must be positive measured bounds')
    if any(type(limits[k]) is not int for k in ('session_rounds','experiment_rounds','refinement_rounds','large_files','large_file_lines')):
        raise ValueError('Round and document counts must be integers')
    return limits


def documents(root):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        if path.suffix not in {'.tex', '.md', '.bib', '.jsonl', '.py', '.json', '.yaml', '.yml', '.csv', '.sh'} or not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(p in {'.paper', 'delivery', '.git'} for p in relative.parts) or relative.parts[:2] == ('control','round-decisions'):
            continue
        if path.is_symlink() or path.stat().st_nlink != 1:
            raise ValueError('Round documents cannot be linked: ' + str(relative))
        value = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''): value.update(block)
        with path.open(errors='replace') as stream: lines = sum(1 for _ in stream)
        result[str(relative)] = {'sha256': value.hexdigest(), 'lines': lines}
    return result


def workload(root, before, limits):
    current = documents(root)
    changed = [p for p, value in current.items() if value != before.get(p)]
    large = [p for p in changed if current[p]['lines'] >= limits['large_file_lines']]
    return {'changed_files': changed, 'deleted_files': sorted(set(before) - set(current)),
            'large_files': large, 'large_file_threshold_lines': limits['large_file_lines'],
            'maximum_large_files': limits['large_files'], 'exceeded': len(large) > limits['large_files'],
            'oversized_new_tex': [p for p in changed if p.endswith('.tex') and current[p]['lines'] > 300 and (p not in before or before[p]['lines'] <= 300)],
            'oversized_existing_tex': [p for p in changed if p.endswith('.tex') and current[p]['lines'] > 300 and p in before and before[p]['lines'] > 300]}


def stop_reasons(state, decision=None):
    limits = policy(state['brief']); session = state['session']
    started = datetime.fromisoformat(session['started_at'].replace('Z', '+00:00'))
    elapsed = (datetime.now(timezone.utc) - started).total_seconds() / 60
    reasons = []
    if session['rounds'] >= limits['session_rounds']: reasons.append('session_rounds')
    if elapsed >= limits['session_minutes']: reasons.append('session_minutes')
    stage = ('intake','venue','plan','literature','experiment','figures','write','review','delivery')[min(len(state['receipts']),8)]
    pending = (state.get('active_round') or {}).get('stages_completed', []).count('experiment')
    if experimental_scope(state['brief']) and ((stage == 'experiment' and session['experiment_rounds'] + pending >= limits['experiment_rounds']) or
            ((decision or {}).get('phase') == 'experiment' and session['experiment_rounds'] >= limits['experiment_rounds'])):
        reasons.append('experiment_rounds')
    refinement = [r['decision'] for r in state['rounds'] if r['decision'].get('phase') == 'refinement']
    if len(refinement) > limits['refinement_rounds']: reasons.append('refinement_rounds')
    gains = [r.get('gain') for r in refinement[-2:]]
    if len(gains) == 2 and all(isinstance(x, (int,float)) and x <= limits['small_gain'] for x in gains):
        reasons.append('two_small_refinement_gains')
    target = state['brief'].get('refinement_target')
    if refinement and target is not None and refinement[-1].get('score', float('-inf')) >= target:
        reasons.append('declared_refinement_target')
    return {'reasons': reasons, 'elapsed_minutes': elapsed, 'policy': limits,
            'attention_required': state['stale_count'] >= 4}
