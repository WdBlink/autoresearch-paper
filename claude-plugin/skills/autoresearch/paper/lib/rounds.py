"""Checkpoint and workload observations, independent of task resource limits."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib

CHECKPOINT_MINUTES = 30
LARGE_FILE_LINES = 300


def experimental_scope(brief):
    return not (brief.get('paper_type') in {'review', 'survey'} and brief.get('not_applicable', {}).get('experiment'))


def documents(root):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        if path.suffix not in {'.tex', '.md', '.bib', '.jsonl', '.py', '.json', '.yaml', '.yml', '.csv', '.sh'} or not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(p in {'.paper', 'delivery', '.git'} for p in relative.parts) or relative.parts[:2] == ('control', 'round-decisions'):
            continue
        if path.is_symlink() or path.stat().st_nlink != 1:
            raise ValueError('Round documents cannot be linked: ' + str(relative))
        value = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                value.update(block)
        with path.open(errors='replace') as stream:
            lines = sum(1 for _ in stream)
        result[str(relative)] = {'sha256': value.hexdigest(), 'lines': lines}
    return result


def workload(root, before):
    current = documents(root)
    changed = [p for p, value in current.items() if value != before.get(p)]
    large = [p for p in changed if current[p]['lines'] >= LARGE_FILE_LINES]
    return {'changed_files': changed, 'deleted_files': sorted(set(before) - set(current)),
            'large_files': large, 'large_file_threshold_lines': LARGE_FILE_LINES,
            'attention_required': len(large) > 5,
            'guidance': 'Inspect substantial changes and preserve evidence; file counts and line lengths do not stop the task'}


def checkpoint(state):
    start = state.get('last_checkpoint_at', state['created_at'])
    elapsed = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(start.replace('Z', '+00:00'))).total_seconds() / 60)
    advice = []
    if state['stale_count'] >= 2:
        advice.append('Try a structurally different approach and retain failed evidence')
    refinements = [r['decision'] for r in state['rounds'] if r['decision'].get('phase') == 'refinement']
    gains = [r.get('gain') for r in refinements[-2:]]
    if len(gains) == 2 and all(type(value) in {int, float} and value <= .3 for value in gains):
        advice.append('Two small refinement gains; inspect remaining requirements before doing more polishing')
    return {'due': elapsed >= CHECKPOINT_MINUTES, 'interval_minutes': CHECKPOINT_MINUTES,
            'minutes_since_checkpoint': elapsed, 'attention_required': state['stale_count'] >= 4,
            'advice': advice, 'action': 'Save an evidence-bound checkpoint, then continue authorized available work',
            'terminal': False}
