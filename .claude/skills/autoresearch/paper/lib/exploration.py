"""Fresh-context requests and Git isolation for the fork-and-flush protocol.

The host owns agents and research approval. This module creates worktrees and
checks selection artifacts; it never merges into an authoritative paper run.
"""
import math
import fnmatch
import os
import re
from pathlib import Path
import subprocess
from .runtime import Refusal, digest, file_hash, identifier, read_json


def trigger(*, iterations, budget, since_keep, rounds=0, unbounded=False,
            orchestrator=False, plateau=False, ceiling=False, no_fork=False):
    if ceiling or no_fork:
        return {'fork': False, 'reason': 'ceiling' if ceiling else 'disabled'}
    if orchestrator:
        return {'fork': bool(plateau and rounds < 2), 'reason': 'plateau' if plateau else 'progress',
                'terminal': 'PLATEAU' if plateau and rounds >= 2 else None}
    scheduled = None if unbounded else ([math.ceil(budget * .33), math.ceil(budget * .66)] if budget >= 12 else [math.ceil(budget * .5)])
    due = iterations >= 20 * (rounds + 1) if unbounded else rounds < len(scheduled) and iterations >= scheduled[rounds]
    eligible = unbounded or rounds < len(scheduled)
    return {'fork': bool(eligible and (due or since_keep >= 5)),
            'reason': 'scheduled' if due else 'early' if eligible and since_keep >= 5 else 'continue',
            'scheduled': scheduled, 'next_round': rounds + 1}


def request(*, goal, scope, metric, direction, verify, guard, incumbent, results,
            budget, forks=None, guided=.5, slow=False, shared=False):
    if direction not in {'higher', 'lower'} or not 0 <= guided <= 1:
        raise Refusal('Invalid metric direction or guided fraction')
    forks = forks if forks is not None else (2 if slow or shared else 4)
    if not isinstance(forks, int) or not 1 <= forks <= 16 or not isinstance(budget, int) or budget <= 0:
        raise Refusal('Invalid branch budget')
    # This is the entire allowed fresh context. No leader plans or conversation.
    base = {'Goal': goal, 'Scope': scope, 'Metric': metric, 'Direction': direction,
            'Verify': verify, 'Guard': guard, 'incumbent': incumbent, 'results_tsv': results,
            'iterations': max(2, math.floor(.06 * budget + .5))}
    count = math.floor(forks * guided)
    return {'schema_version': 1, 'parallel': not shared,
            'branches': [{'id': 'b' + str(n + 1), 'kind': 'guided' if n < count else 'random',
                          'context': dict(base)} for n in range(forks)],
            'advisor': {'read_only': True, 'inputs': ['Goal', 'Scope', 'Metric', 'Direction', 'results_tsv', 'git log', 'incumbent diff'],
                        'assignments': count, 'distinct': True, 'exclude_logged_failures': True}}


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True, stderr=subprocess.DEVNULL).strip()


def create_worktrees(repo, plan, destination):
    repo, destination = Path(repo).resolve(), Path(destination).resolve()
    if git(repo, 'status', '--porcelain'):
        raise Refusal('Exploration needs a clean isolated source checkout')
    if destination == repo or destination.is_relative_to(repo):
        raise Refusal('Worktrees must be outside the source checkout')
    incumbent = plan['branches'][0]['context']['incumbent']
    if not re.fullmatch(r'[a-f0-9]{40}(?:[a-f0-9]{24})?', incumbent):
        raise Refusal('Pin a full immutable Git commit for the incumbent')
    git(repo, 'rev-parse', '--verify', incumbent + '^{commit}')
    tag_name = 'autoresearch/incumbent-' + incumbent
    try:
        tag = git(repo, 'rev-parse', '--verify', 'refs/tags/' + tag_name)
    except subprocess.CalledProcessError:
        git(repo, 'tag', tag_name, incumbent)
    else:
        if tag != git(repo, 'rev-parse', incumbent):
            raise Refusal('Protected incumbent tag was changed')
    created = []
    for branch in plan['branches']:
        name = identifier(branch['id'])
        path = destination / name
        if path.exists():
            raise Refusal('Branch worktree already exists')
        path.parent.mkdir(parents=True, exist_ok=True)
        git(repo, 'worktree', 'add', '--detach', str(path), incumbent)
        created.append({'id': name, 'path': str(path), 'incumbent': git(path, 'rev-parse', 'HEAD')})
    return created


def select(plan, candidates, incumbent_metric):
    expected = {b['id'] for b in plan['branches']}
    if {c.get('id') for c in candidates} != expected or len(candidates) != len(expected):
        raise Refusal('Every branch, including failures, needs a result')
    valid = []
    for candidate in candidates:
        if candidate.get('status') not in {'completed', 'failed', 'unknown'}:
            raise Refusal('Unknown branch outcome')
        if candidate['status'] == 'unknown':
            raise Refusal('Reconcile unknown branch outcomes before selection')
        if candidate['status'] == 'failed':
            if not candidate.get('reason'):
                raise Refusal('Failure must remain explained')
            continue
        value = candidate.get('metric')
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise Refusal('Invalid branch metric')
        evidence = Path(candidate['evidence'])
        if evidence.is_symlink() or not evidence.is_file() or file_hash(evidence) != candidate.get('evidence_sha256'):
            raise Refusal('Branch evidence is stale')
        observed = read_json(evidence)
        if any(observed.get(k) != candidate.get(k) for k in ('metric', 'guard_passed', 'commit')):
            raise Refusal('Branch metric/guard/commit does not match its verification artifact')
        if not candidate.get('guard_passed') or not re.fullmatch(r'[a-f0-9]{40}(?:[a-f0-9]{24})?', str(candidate.get('commit'))):
            raise Refusal('Selection needs guard verification and a candidate commit')
        valid.append(candidate)
    direction = plan['branches'][0]['context']['Direction']
    if isinstance(incumbent_metric, bool) or not isinstance(incumbent_metric, (float, int)) or not math.isfinite(incumbent_metric):
        raise Refusal('Invalid incumbent metric')
    valid.sort(key=lambda c: c['metric'], reverse=direction == 'higher')
    winner = valid[0] if valid else None
    at_least = winner and (winner['metric'] >= incumbent_metric if direction == 'higher' else winner['metric'] <= incumbent_metric)
    return {'winner': winner['id'] if winner else None, 'promote': bool(at_least),
            'incumbent_retained': not at_least, 'fresh_context_leader': winner['id'] if winner else None,
            'results_sha256': digest(candidates), 'authority': 'working metric only; independent paper acceptance required'}


def promote(repo, plan, candidates, incumbent_metric):
    repo = Path(repo).resolve()
    selected = select(plan, candidates, incumbent_metric)
    if not selected['promote']:
        return selected
    incumbent = plan['branches'][0]['context']['incumbent']
    if git(repo, 'status', '--porcelain') or git(repo, 'rev-parse', 'HEAD') != git(repo, 'rev-parse', incumbent):
        raise Refusal('Source changed after round preparation; no merge performed')
    candidate = next(c for c in candidates if c['id'] == selected['winner'])
    if subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', incumbent, candidate['commit']], capture_output=True).returncode:
        raise Refusal('Winner is not descended from the protected incumbent')
    scope = plan['branches'][0]['context']['Scope']
    if not isinstance(scope, list) or not scope or not all(isinstance(p, str) and p and not Path(p).is_absolute() and '..' not in Path(p).parts for p in scope):
        raise Refusal('Promotion requires explicit run-relative allowed Scope patterns')
    raw_paths = subprocess.check_output(['git', '-C', str(repo), 'diff', '--no-renames', '--name-only', '-z', incumbent, candidate['commit']])
    paths = [os.fsdecode(name) for name in raw_paths.split(b'\0') if name]
    for name in paths:
        if any(part in {'.paper', '.git', 'delivery'} for part in Path(name).parts):
            raise Refusal('Branch touches controller-owned state: ' + name)
        if not any(fnmatch.fnmatchcase(name, pattern) for pattern in scope):
            raise Refusal('Branch change is outside the frozen Scope: ' + name)
    git(repo, 'merge', '--ff-only', candidate['commit'])
    return {**selected, 'head': git(repo, 'rev-parse', 'HEAD')}
