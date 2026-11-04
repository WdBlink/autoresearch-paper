"""Paper handoffs for the upstream Autoresearch host. No model or remote executor."""
import contextlib
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone

STAGES = ('intake', 'venue', 'plan', 'literature', 'experiment', 'figures', 'write', 'review')
ACTIONS = {
    'compile_tex': ('source', 'pdf'),
    'render_statistics': ('input', 'table', 'figure'),
    'copy_artifact': ('source', 'target'),
    'validate_packet': ('packet',),
    'export_image': ('source', 'target', 'options'),
    'prepare_tex': ('source', 'target', 'options'),
}
IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$')


class Refusal(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Refusal('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    if Path(path).stat().st_size > 16 * 1024 * 1024:
        raise Refusal('JSON exceeds the 16 MiB input limit')
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(Refusal('Non-finite JSON: ' + x)))


def safe(root, value, *, output=False, internal=False):
    if not isinstance(value, str) or not value or Path(value).is_absolute() or '..' in Path(value).parts:
        raise Refusal('Expected a run-relative path: ' + str(value))
    if not internal and (Path(value).parts[0] in {'.paper', 'delivery', '.git'} or Path(value).parts[:2] == ('control','round-decisions')):
        raise Refusal('Artifact cannot write controller-owned paths: ' + value)
    path = root / value
    current = root
    for part in Path(value).parts:
        current = current / part
        if current.is_symlink():
            raise Refusal('Symlink paths are not artifacts: ' + value)
    if not path.resolve().is_relative_to(root.resolve()):
        raise Refusal('Path escapes run')
    if not output and not path.is_file():
        raise Refusal('Missing artifact: ' + value)
    if path.is_file() and path.stat().st_nlink != 1:
        raise Refusal('Hard-linked artifacts are not accepted: ' + value)
    return path


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise Refusal('Invalid identifier: ' + str(value))
    return value


def check_brief(brief, *, draft=False):
    if not isinstance(brief, dict):
        raise Refusal('Brief must be an object')
    from .budget import limits
    limits(brief)
    for field in ('question', 'venue', 'direction', 'paper_type', 'resources', 'scope', 'angle', 'audience'):
        if not brief.get(field):
            raise Refusal('Brief missing ' + field)
    if 'software_fixture' in brief and type(brief['software_fixture']) is not bool:
        raise Refusal('software_fixture must be a boolean fixed in the Brief')
    items = brief.get('deliverable_plan')
    if draft and items == []:
        return set()
    if not isinstance(items, list) or not items:
        raise Refusal('Brief requires an itemized deliverable_plan')
    ids = set()
    for item in items:
        key = identifier(item.get('id'))
        if not key[0].isalpha() or not key[0].isascii():
            raise Refusal('Requirement IDs must start with an ASCII letter')
        if key in ids:
            raise Refusal('Duplicate requirement ' + key)
        ids.add(key)
        if item.get('kind') not in {'figure', 'table', 'section', 'manuscript'}:
            raise Refusal('Invalid requirement kind')
        for field in ('title', 'purpose', 'acceptance_criteria', 'evidence_requirements'):
            if not item.get(field):
                raise Refusal(key + ': missing ' + field)
    return ids


def build_tex(source, output_directory):
    executable = shutil.which('pdflatex')
    if not executable:
        raise Refusal('pdflatex is unavailable')
    latexmk = shutil.which('latexmk')
    if latexmk:
        commands = [[latexmk, '-norc', '-pdf', '-pdflatex=pdflatex -no-shell-escape %O %S',
                     '-interaction=nonstopmode', '-halt-on-error', '-outdir=' + str(output_directory), source.name]]
    else:
        commands = [[executable, '-no-shell-escape', '-interaction=nonstopmode', '-halt-on-error',
                     '-output-directory', str(output_directory), source.name]] * 3
    last = None
    for command in commands:
        last = subprocess.run(command, cwd=source.parent, capture_output=True, text=True, timeout=60)
        if last.returncode:
            raise Refusal('TeX compile failed: ' + last.stdout[-2500:])
    built = Path(output_directory) / (source.stem + '.pdf')
    log = Path(output_directory) / (source.stem + '.log')
    if not built.is_file() or not log.is_file():
        raise Refusal('TeX did not produce a PDF and build log')
    text = log.read_text(errors='replace')
    if re.search(r'(?:Citation|Reference) .+ undefined|There were undefined (?:references|citations)|Rerun to get cross-references right', text):
        raise Refusal('Unresolved citations or cross references remain in the compiled manuscript')
    return built


def tex_without_comments(text):
    lines = []
    for line in text.splitlines():
        for position, char in enumerate(line):
            if char != '%':
                continue
            backslashes = 0
            cursor = position - 1
            while cursor >= 0 and line[cursor] == chr(92):
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                line = line[:position]
                break
        lines.append(line)
    return '\n'.join(lines)


class Controller:
    def __init__(self, run, package=None):
        self.root = Path(run).resolve()
        self.home = self.root / '.paper'
        self.package = Path(package).resolve() if package else Path(__file__).resolve().parents[1]
        self.path = self.home / 'control.json'

    @contextlib.contextmanager
    def lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        if self.home.is_symlink() or self.path.is_symlink():
            raise Refusal('Controller paths cannot be symlinks')
        self.home.mkdir(exist_ok=True)
        lockpath = self.home / 'lock'
        if lockpath.is_symlink():
            raise Refusal('Lock cannot be a symlink')
        with lockpath.open('a') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            yield

    def load(self):
        if not self.path.exists():
            raise Refusal('Not initialized; use a new run directory')
        value = read_json(self.path)
        if value.get('schema_version') != 2:
            raise Refusal('Old or unknown run format; use its pinned runtime or an explicit reviewed migration')
        if digest(value['brief']) != value['brief_sha256']:
            raise Refusal('Approved Brief changed')
        checkpoint = self.home / 'checkpoint.json'
        if checkpoint.exists():
            if checkpoint.is_symlink() or checkpoint.stat().st_nlink != 1: raise Refusal('Recovery checkpoint cannot be linked')
            latest = read_json(checkpoint)
            if latest.get('sha256') != digest(latest.get('state')) or digest(value) != latest['sha256']:
                raise Refusal('Controller and latest durable checkpoint differ; recover before proceeding')
        if value.get('implementation_sha256') != self.implementation():
            raise Refusal('Execution code or stage knowledge changed; pin the old implementation or migrate explicitly')
        self.task_clock_evidence(value)
        return value

    def implementation(self):
        paths = [*sorted((self.package / 'lib').glob('*.py')), *sorted((self.package / 'references').rglob('*.md')), *sorted((self.package / 'vendor').rglob('scripts/*.py'))]
        return digest({str(p.relative_to(self.package)): file_hash(p) for p in paths})

    def save(self, state):
        # The same controller writes a latest-state recovery copy before its live projection.
        # An interrupted pair is detected on load; recovery never selects an older export.
        atomic(self.home / 'checkpoint.json', {'state': state, 'sha256': digest(state)})
        atomic(self.path, state)

    def init(self, brief):
        check_brief(brief, draft=brief.get('contract_status') == 'draft')
        with self.lock():
            if self.path.exists():
                raise Refusal('Run already exists; do not reset its history')
            if any(p.name != 'lock' for p in self.home.iterdir()) or (self.root / 'delivery').exists():
                raise Refusal('Historical controller/export records exist; recover the ledger instead of reinitializing')
            state = {'schema_version': 2, 'created_at': now(), 'brief': brief,
                     'brief_sha256': digest(brief), 'implementation_sha256': self.implementation(), 'approval': None, 'receipts': [],
                     'history': [], 'operations': {}, 'attempts': {}, 'bindings': {},
                     'frozen_plan': None, 'delivery': None, 'rounds': [], 'stale_count': 0, 'material_reads': [], 'additional_orders': [], 'venue_confirmation': None, 'active_round': None, 'last_seen_at': now(), 'last_progress_at': None, 'session': {'started_at': now(), 'rounds': 0, 'experiment_rounds': 0}, 'last_round_status': None, 'pending_round': None,
                     'usage_ledger': {}, 'task_stop': None, 'last_checkpoint_at': now(), 'user_questions': {}, 'budget_confirmation': None}
            self.save(state)
            return {'status': 'preparation' if brief.get('contract_status') == 'draft' else 'needs_brief_approval', 'brief_sha256': state['brief_sha256'], 'brief': brief}

    def authorization(self, record):
        if record is None:
            return None
        if not isinstance(record, dict) or set(record) != {'mode', 'path', 'sha256', 'quote', 'scope'} or record.get('mode') != 'delegated':
            raise Refusal('Delegated authorization requires mode, source path/hash/quote and concrete scope')
        path = safe(self.root, record['path'])
        if file_hash(path) != record['sha256'] or not isinstance(record['quote'], str) or not record['quote'].strip() or record['quote'] not in path.read_text():
            raise Refusal('Delegated authorization source hash or exact instruction quote differs')
        if not isinstance(record['scope'], str) or not record['scope'].strip():
            raise Refusal('Delegated authorization needs its actual scope; the host must verify its meaning')
        return copy.deepcopy(record)

    def approve(self, brief_sha256, actor, authorization=None):
        with self.lock():
            state = self.load()
            check_brief(state['brief'])
            if state['brief'].get('contract_status') == 'draft':
                raise Refusal('Calibrate the venue and set the concrete contract before final Brief approval')
            authority = self.authorization(authorization)
            if brief_sha256 != state['brief_sha256'] or not actor.strip():
                raise Refusal('Approval must bind the exact Brief and truthful decision actor')
            if state['approval'] and (state['approval']['actor'] != actor or state['approval'].get('authorization') != authority):
                raise Refusal('Approval already recorded with different actor or authorization')
            if not state['approval']:
                state['approval'] = {'actor': actor, 'brief_sha256': brief_sha256, 'at': now(),
                                     'basis': 'host-relayed human approval' if not state['brief'].get('software_fixture') else 'software fixture'}
                if authority is not None:
                    state['approval'].update(basis='delegated user instruction', authorization=authority)
                self.save(state)
            return {'status': 'approved', 'approval': state['approval']}

    def ready(self, state, *, preparation=False):
        if not preparation and (not state['approval'] or state['brief'].get('contract_status') == 'draft'):
            raise Refusal('Exact Brief approval is required before research stages')
        if state['approval']:
            self.authorization(state['approval'].get('authorization'))
            from .user_input import check_human_response
            for change in state['approval'].get('user_amendments', []):
                check_human_response(change['human_response'], self.root)
        issues = self.stale(state)
        if issues:
            raise Refusal('; '.join(issues))
        unresolved = [key for key, a in state['attempts'].items() if a['status'] in {'running', 'uncertain'}]
        if unresolved:
            raise Refusal('Uncertain effects require reconciliation: ' + ', '.join(unresolved))

    def stale(self, state):
        issues = []
        for receipt in state['receipts']:
            for name, expected in receipt['hashes'].items():
                try:
                    actual = file_hash(safe(self.root, name))
                except (ValueError, OSError) as exc:
                    issues.append(str(exc))
                    continue
                if actual != expected:
                    issues.append('Stale ' + receipt['stage'] + ' artifact: ' + name + '; rewind this stage and resubmit')
        return issues

    def set_contract(self, brief, op):
        with self.lock():
            state = self.load()
            request = {'command': 'set-contract', 'brief': brief}
            previous = self.operation(state, op, request)
            if previous is not None:
                return previous
            if [r['stage'] for r in state['receipts']] != ['intake', 'venue']:
                raise Refusal('Set the concrete contract after venue calibration and before plan acceptance')
            check_brief(brief)
            for field in ('question', 'direction', 'paper_type', 'resources'):
                if brief.get(field) != state['brief'].get(field):
                    raise Refusal('Contract cannot silently change the research scope or resources: ' + field)
            venue = state['receipts'][-1]['packet']['venue']
            if brief.get('venue') != venue or brief.get('contract_status') == 'draft':
                raise Refusal('Final contract must use the calibrated venue')
            state['history'].append({'event': 'brief_superseded', 'brief': state['brief'], 'approval': state['approval'], 'at': now()})
            state['brief'], state['brief_sha256'], state['approval'] = brief, digest(brief), None
            return self.record(state, op, request, {'status': 'needs_brief_approval', 'brief': brief, 'brief_sha256': digest(brief)})

    def prepare_user_input(self, kind, packet):
        from .user_input import prepare
        with self.lock():
            state = self.load()
            self.ready(state, preparation=True)
            stages = [r['stage'] for r in state['receipts']]
            if kind == 'venue' and stages != ['intake']:
                raise Refusal('Ask venue choice after intake and before calibration acceptance')
            if kind == 'budget':
                if 'venue' not in stages:
                    raise Refusal('Ask the concrete plan budget after venue calibration')
                from .budget import quantities
                quantities(packet.get('budget'), caps=True)
            question = prepare(kind, packet, self.root, state)
            previous = state['user_questions'].get(kind)
            if previous and previous['question'] == question:
                return {'status': previous['status'], 'question': question}
            if previous:
                state['history'].append({'event': 'user_question_superseded', 'record': previous, 'at': now()})
            state['user_questions'][kind] = {'status': 'needs_input', 'question': question}
            self.save(state)
            return {'status': 'needs_user_input', 'question': question}

    def _answer(self, state, kind, response):
        from .user_input import validate_response
        issued = state['user_questions'].get(kind)
        if not issued or issued['status'] != 'needs_input':
            raise Refusal('Prepare and ask the current ' + kind + ' question; wait for an actual user answer')
        answer = validate_response(issued['question'], response, self.root, state)
        state['user_questions'][kind] = {**issued, 'status': 'answered', 'response': copy.deepcopy(response), 'answer': answer}
        return issued['question'], answer

    def _amend_user_field(self, state, field, value, response):
        if state['brief'].get(field, {} if field == 'budget' else None) == value:
            return
        state['history'].append({'event': 'user_field_amendment', 'field': field,
                                 'brief': copy.deepcopy(state['brief']), 'approval': copy.deepcopy(state['approval']),
                                 'response': copy.deepcopy(response), 'at': now()})
        state['brief'][field] = copy.deepcopy(value)
        state['brief_sha256'] = digest(state['brief'])
        if state['approval']:
            state['approval'] = {**state['approval'], 'brief_sha256': state['brief_sha256'],
                                'user_amendments': [*state['approval'].get('user_amendments', []),
                                    {'field': field, 'question_sha256': response['question_sha256'],
                                     'human_response': copy.deepcopy(response['human_response'])}]}

    def confirm_venue(self, packet, actor, comparison_sha256, op, authorization=None, response=None):
        from .venue_tools import comparison_digest, comparison_report
        with self.lock():
            state = self.load()
            request = {'command': 'confirm-venue', 'packet': packet, 'actor': actor, 'comparison_sha256': comparison_sha256,
                       'authorization': authorization, 'response': response}
            previous = self.operation(state, op, request)
            if previous is not None:
                return previous
            if not actor.strip() or comparison_digest(comparison_report(packet, self.root)) != comparison_sha256:
                raise Refusal('Venue confirmation must bind the exact sourced comparison and actual user selection')
            if len(state['receipts']) != 1 or state['receipts'][0]['stage'] != 'intake':
                raise Refusal('Confirm venue after intake and before calibration acceptance')
            if authorization is not None:
                raise Refusal('Delegated execution authorization does not replace the venue user answer')
            question, answer = self._answer(state, 'venue', response)
            report = comparison_report(packet, self.root)
            if report['candidates'] != question['candidates'] or report['criteria'] != question['comparison']['criteria']:
                raise Refusal('Venue candidate materials changed; ask again')
            if answer['candidate_id'] != report['selected_id']:
                raise Refusal('Final venue packet does not match the actual user choice')
            self._amend_user_field(state, 'venue', packet['venue'], response)
            state['venue_confirmation'] = {'candidate_id': packet['venue_selection']['selected_id'], 'venue': packet['venue'],
                                           'comparison_sha256': comparison_sha256, 'actor': actor, 'at': now(),
                                           'basis': 'source-bound user answer', 'human_response': response['human_response']}
            return self.record(state, op, request, {'status': 'venue_confirmed', **state['venue_confirmation']})

    def confirmed_venue(self, state, packet):
        from .user_input import check_human_response
        from .venue_tools import comparison_report, comparison_digest
        record = state.get('venue_confirmation')
        if not record:
            raise Refusal('Ask the user to choose the venue before accepting calibration')
        check_human_response(record['human_response'], self.root)
        if comparison_digest(comparison_report(packet, self.root)) != record['comparison_sha256']:
            raise Refusal('Venue selection changed after the user answer; ask again')

    def confirm_budget(self, response, op):
        from .budget import quantities, summary
        with self.lock():
            state = self.load()
            request = {'command': 'confirm-budget', 'response': response}
            previous = self.operation(state, op, request)
            if previous is not None:
                return previous
            question, answer = self._answer(state, 'budget', response)
            if not answer['proceed']:
                return self.record(state, op, request, {'status': 'budget_declined', 'action': 'Revise the proposed plan or continue work within the existing approved budget'})
            value = quantities(answer['budget'], caps=True)
            self._amend_user_field(state, 'budget', value, response)
            state['budget_confirmation'] = {'budget_sha256': digest(value), 'plan': question['plan'],
                'contract_sha256': digest({k:v for k,v in state['brief'].items() if k != 'budget'}),
                'human_response': copy.deepcopy(response['human_response']), 'question_sha256': question['question_sha256'], 'at': now()}
            if (state.get('task_stop') or {}).get('reason') == 'budget_exhausted':
                state['task_stop'] = None
            return self.record(state, op, request, {'status': 'budget_confirmed', 'budget': summary(state)})

    def confirmed_budget(self, state, plan=None):
        from .user_input import check_human_response
        from .budget import limits
        record = state.get('budget_confirmation')
        if not record:
            raise Refusal('Show defaults and optional caps, then ask the user to confirm the plan budget')
        check_human_response(record['human_response'], self.root)
        if digest(limits(state['brief'])) != record['budget_sha256'] or digest({k:v for k,v in state['brief'].items() if k != 'budget'}) != record['contract_sha256']:
            raise Refusal('Budget or research contract changed; ask the current plan-budget question again')
        if plan is not None and plan != record['plan']['path']:
            raise Refusal('Budget answer names another plan')
        if file_hash(safe(self.root, record['plan']['path'])) != record['plan']['sha256']:
            raise Refusal('Plan changed after the user budget answer; ask again')

    def reserve_budget(self, packet, op):
        from .budget import admit, summary
        identifier(op)
        with self.lock():
            state = self.load()
            request = {'command': 'budget-reserve', 'packet': packet}
            previous = self.operation(state, op, request)
            if previous is not None:
                return previous
            self.ready(state)
            self.confirmed_budget(state)
            self.budget_evidence(state)
            if op in state['usage_ledger']:
                raise Refusal('Resource ledger identity already exists; use a new operation ID')
            if state['frozen_plan'] is None or not any(r['stage'] == 'plan' for r in state['receipts']):
                raise Refusal('Freeze the confirmed research plan before reserving research calls')
            if state['active_round'] is None:
                raise Refusal('begin-round must capture the research baseline before reserving a call')
            state['usage_ledger'][op] = {**admit(state, packet), 'created_at': now()}
            return self.record(state, op, request, {'status': 'reserved', 'reservation': op, 'budget': summary(state)})

    def settle_budget(self, reservation, packet, op):
        from .budget import settlement, summary
        identifier(op)
        with self.lock():
            state = self.load()
            request = {'command': 'budget-settle', 'reservation': reservation, 'packet': packet}
            previous = self.operation(state, op, request)
            if previous is not None:
                return previous
            key = reservation if reservation is not None else 'unreserved-' + digest(op)[:24]
            entry = state['usage_ledger'].get(key)
            if reservation is None and entry is not None:
                raise Refusal('Resource ledger identity already exists')
            if reservation is not None and entry is None:
                raise Refusal('Unknown reservation')
            filling_missing = bool(entry and key in summary(state)['incomplete_capped_usage'])
            if entry and entry['status'] not in {'reserved', 'unknown'} and not filling_missing:
                raise Refusal('Usage already settled; identical operations can be replayed, not recharged')
            self.budget_evidence(state)
            value = settlement(state, entry, packet)
            if entry and value['status'] != 'not_started' and any(value['reported_usage'].get(field) != amount for field, amount in entry.get('reported_usage', {}).items()):
                raise Refusal('Reconciliation may fill missing meters, not rewrite previously known usage')
            receipt = safe(self.root, value['receipt'])
            receipt_sha = file_hash(receipt)
            if any(other != key and item.get('receipt') == value['receipt'] for other, item in state['usage_ledger'].items()):
                raise Refusal('This actual receipt is already accounted for')
            receipts = list((entry or {}).get('receipts', []))
            source = {'path': value['receipt'], 'sha256': receipt_sha}
            if source not in receipts:
                receipts.append(source)
            state['usage_ledger'][key] = {**value, 'receipt_sha256': receipt_sha, 'receipts': receipts, 'settled_at': now()}
            return self.record(state, op, request, {'status': value['status'], 'reservation': key, 'budget': summary(state)})

    def budget_evidence(self, state):
        sources = {}
        for entry in state['usage_ledger'].values():
            for source in entry.get('receipts', []):
                if file_hash(safe(self.root, source['path'])) != source['sha256']:
                    raise Refusal('Recorded usage receipt changed; restore it and use a new version for corrections')
                sources[source['path']] = source['sha256']
        return sources

    def task_clock_evidence(self, state, root=None):
        sources = {}
        for source in state.get('task_clock', {}).get('sources', []):
            if file_hash(safe(root or self.root, source['path'])) != source['sha256']:
                raise Refusal('Task clock snapshot changed; restore its original bytes')
            sources[source['path']] = source['sha256']
        return sources

    def available_local_orders(self, state):
        completed = {a['work_id'] for a in state['attempts'].values() if a['status'] == 'completed'}
        orders = [*[o for r in state['receipts'] if r['stage'] == 'plan' for o in r['packet']['work_orders']], *state['additional_orders']]
        available = []
        for order in orders:
            if order['id'] in completed:
                continue
            produced = set()
            for action in order['actions']:
                outputs = action_outputs(action)
                inputs = [action[key] for key in ACTIONS[action['type']]
                          if key != 'options' and action[key] not in outputs]
                if any(name not in produced and not (self.root / name).is_file() for name in inputs):
                    break
                produced.update(outputs)
            else:
                available.append(order['id'])
        return available

    def validate_exit(self, state, request, decision):
        from .budget import summary
        from .user_input import check_human_response
        status = decision['status']
        if status == 'active':
            if decision.get('stop'):
                raise Refusal('An active checkpoint cannot stop the task')
            return
        stop = decision.get('stop', {})
        if not isinstance(stop, dict):
            raise Refusal('stop must name a user_request or a verifiable budget_exhausted reason')
        if status == 'stopped' and stop.get('reason') == 'user_request':
            check_human_response(stop.get('human_response'), self.root)
            state['task_stop'] = copy.deepcopy(stop)
            return
        view = summary(state)
        if status == 'stopped' and stop.get('reason') != 'budget_exhausted':
            raise Refusal('Internal work or a checkpoint cannot stop the task; stopped needs user_request or verified budget_exhausted')
        if status == 'stopped' and not view['exhausted']:
            raise Refusal('No explicit task budget is exhausted')
        if status == 'stopped' and 'minutes' in view['exhausted']:
            state['task_stop'] = {'reason': 'budget_exhausted', 'meters': view['exhausted']}
            return
        if status == 'stopped' and not any(r['stage'] == 'plan' for r in state['receipts']):
            raise Refusal('Resource caps do not stop local plan preparation; only their new calls are blocked')
        blockers = decision.get('blockers')
        if not isinstance(blockers, list) or not blockers:
            raise Refusal('Waiting needs concrete external blockers; internal work remains active')
        ids = {item['id'] for item in state['brief']['deliverable_plan']}
        covered = set()
        for blocker in blockers:
            if not isinstance(blocker, dict) or blocker.get('kind') not in {'input', 'authorization', 'external_service', 'budget'} or not isinstance(blocker.get('reason'), str) or not blocker['reason'].strip():
                raise Refusal('Use structured external blockers; internal implementation failures are actionable work')
            requirements = blocker.get('requirement_ids')
            if not isinstance(requirements, list) or not all(isinstance(value, str) for value in requirements) or not set(requirements) <= ids:
                raise Refusal('External blocker must name actual requirement_ids')
            covered.update(requirements)
        if covered != ids:
            raise Refusal('Only some requirements are externally blocked; continue the remaining authorized work')
        if self.available_local_orders(state):
            raise Refusal('Known local WorkOrders remain executable; an external dependency cannot stop them')
        if status == 'stopped':
            state['task_stop'] = {'reason': 'budget_exhausted', 'meters': view['exhausted']}

    def restore_task_clock(self, packet, op):
        from .budget import task_started_at
        with self.lock():
            state = self.load()
            if not isinstance(packet, dict) or set(packet) != {'snapshot', 'sha256'}:
                raise Refusal('Task clock recovery needs snapshot and sha256')
            request = {'command': 'restore-task-clock', 'packet': packet}
            previous = self.operation(state, op, request)
            if previous is not None:
                return previous
            path = safe(self.root, packet['snapshot'])
            if file_hash(path) != packet['sha256']:
                raise Refusal('Task clock snapshot hash differs')
            prior = read_json(path)
            if (not isinstance(prior, dict) or prior.get('schema_version') != 2 or not isinstance(prior.get('brief'), dict)
                    or prior.get('brief_sha256') != digest(prior['brief'])
                    or not isinstance(prior.get('usage_ledger'), dict)
                    or not isinstance(prior.get('history'), list)):
                raise Refusal('Task clock source must be a preserved schema2 controller snapshot')
            for field in ('question', 'direction', 'paper_type', 'scope', 'deliverable_plan'):
                if prior['brief'].get(field) != state['brief'].get(field):
                    raise Refusal('Task clock snapshot belongs to a different task: ' + field)
            try:
                start = task_started_at(prior)
                origin = datetime.fromisoformat(start.replace('Z', '+00:00'))
                created = datetime.fromisoformat(prior['created_at'].replace('Z', '+00:00'))
                current = datetime.fromisoformat(task_started_at(state).replace('Z', '+00:00'))
                if any(value.tzinfo is None for value in (origin, created, current)):
                    raise ValueError('Timezone required')
            except (KeyError, TypeError, ValueError, AttributeError) as error:
                raise Refusal('Task clock needs timezone-aware controller timestamps') from error
            if origin > datetime.now(timezone.utc) or created > datetime.now(timezone.utc):
                raise Refusal('Task clock snapshot is in the future')
            if origin > created or origin > current:
                raise Refusal('Task clock recovery cannot move the task start later')
            sources = list(state.get('task_clock', {}).get('sources', []))
            source = {'path': packet['snapshot'], 'sha256': packet['sha256']}
            if source not in sources:
                sources.append(source)
            state['task_clock'] = {'started_at': start, 'sources': sources}
            return self.record(state, op, request, {'status': 'task_clock_restored',
                'task_started_at': start, 'run_created_at': state['created_at'], 'source': source})

    def resume_task(self, human_response, op):
        from .user_input import check_human_response
        with self.lock():
            state = self.load()
            request = {'command': 'resume-task', 'human_response': human_response}
            previous = self.operation(state, op, request)
            if previous is not None:
                return previous
            check_human_response(human_response, self.root)
            if human_response == (state.get('task_stop') or {}).get('human_response'):
                raise Refusal('Resumption needs a new actual user instruction, not the stop instruction')
            state['history'].append({'event': 'task_resumed', 'previous_stop': state.get('task_stop'), 'human_response': human_response, 'at': now()})
            state['task_stop'] = None
            return self.record(state, op, request, {'status': 'resumed', 'scope': 'Original task authorization and remaining budget only'})

    def context(self, writing_cases=()):
        with self.lock():
            state = self.load()
            stage = STAGES[len(state['receipts'])] if len(state['receipts']) < len(STAGES) else 'delivery'
            knowledge = self.package / 'references/knowledge' / (stage + '.md')
            if not knowledge.is_file():
                raise Refusal('Missing stage knowledge: ' + str(knowledge))
            name = 'iterate.md' if stage == 'experiment' else 'plan.md' if stage in {'intake', 'venue', 'plan'} else 'reason.md'
            protocol = self.package / 'upstream' / name
            if not protocol.is_file():
                protocol = self.package.parent / '.claude/commands' / ('autoresearch.md' if name == 'autoresearch.md' else 'autoresearch/' + name)
            if not protocol.is_file():
                raise Refusal('Upstream stage protocol missing from installation')
            from .writing import guidance
            prose = guidance(self.package, writing_cases) if stage in {'write','review'} else None
            production_steps = {
                'intake': ['source-fetch for declared public inputs', 'environment', 'read-material'],
                'venue': ['source-fetch', 'venue-compare', 'ask-user --kind venue', 'Host asks actual user and records response', 'confirm-venue --response', 'venue-design-template', 'venue-calibrate --publish (includes reading index)'],
                'plan': ['environment', 'Prepare the concrete local plan and resource proposal', 'ask-user --kind budget', 'Host asks defaults and optional caps; wait for actual response', 'confirm-budget --response', 'experiment-template for the frozen task-specific measure function'],
                'experiment': ['Use lib.experiments.ExperimentRecorder; preserve all planned attempt slots'],
                'literature': ['bibliography from explicit primary metadata', 'citation-check'],
                'figures': ['render_statistics', 'export_image with source-bound venue policy', 'pdf-inspect'],
                'write': ['prepare_tex with explicit variant policy', 'compile_tex', 'pdf-inspect with visible annotations'],
                'review': ['bind-all', 'prepare-review', 'actual independent judgment', 'assemble-review', 'commit'],
                'delivery': ['prepare-round', 'actual host decision', 'deliver --decision (apply, rebuild, finalize, verify ZIP)'],
            }
            pending = state.get('pending_round')
            return {'writing_guidance': prose, 'stage': stage, 'brief': state['brief'], 'approval': state['approval'],
                    'inputs': [{k: r[k] for k in ('stage', 'packet', 'hashes')} for r in state['receipts']],
                    'stale': self.stale(state), 'attempts': state['attempts'],
                    'knowledge': knowledge.read_text(), 'knowledge_sha256': file_hash(knowledge),
                    'upstream_protocol': protocol.read_text(),
                    'action_contracts': ACTIONS,
                    'requirements': state['brief']['deliverable_plan'],
                    'budget': __import__('lib.budget', fromlist=['summary']).summary(state),
                    'checkpoint': __import__('lib.rounds', fromlist=['checkpoint']).checkpoint(state), 'active_round': state['active_round'],
                    'user_questions': [q['question'] for q in state['user_questions'].values() if q.get('status') == 'needs_input'],
                    'user_input_contract': 'references/user-input.md',
                    'bindings': state['bindings'],
                    'work_orders': [*[o for r in state['receipts'] if r['stage'] == 'plan' for o in r['packet']['work_orders']], *state['additional_orders']],
                    'production_steps': production_steps.get(stage, []),
                    'production_contract': 'references/production.md',
                    'round_request_path': ('control/round-decisions/' + pending['request_sha256'] + '-request.json') if pending else None,
                    'contract': (self.package / 'references/runtime-contract.md').read_text()}

    def prepare_review(self, out):
        from .production import json_bytes, write_once
        from .reviewing import request
        context = self.context()
        value = request(self.root, context)
        write_once(self.root, out, json_bytes(value))
        return {'status': 'needs_independent_judgment', 'request': out,
                'request_sha256': value['request_sha256'], 'response_contract': value['response_contract']}

    def assemble_review(self, packet):
        from .reviewing import assemble
        current = self.context()
        if current['stage'] != 'review':
            raise Refusal('Assemble review only for the current review stage')
        frozen = read_json(safe(self.root, packet['request']))
        if frozen.get('brief_sha256') != digest(current['brief']) or frozen.get('bindings') != current['bindings']:
            raise Refusal('Review request differs from the current approved contract or bindings')
        return assemble(packet, self.root)

    def tool(self, name, packet, out=None, *, publish=False):
        from . import planning, science, venue_tools
        with self.lock():
            state = self.load()
            p = copy.deepcopy(packet)
            p['_brief'] = state['brief']
            p['_history'] = {r['stage']: r['packet'] for r in state['receipts']}
            p['_plan'] = p['_history'].get('plan', {})
            p['_venue_confirmation'] = state.get('venue_confirmation')
            if name == 'venue-compare':
                value = venue_tools.comparison_report(p, self.root)
                value = {'comparison': value, 'comparison_sha256': venue_tools.comparison_digest(value)}
            elif name == 'venue-design-template': value = venue_tools.design_template(p, self.root)
            elif name == 'venue-calibrate': value = planning.calibrate(p, self.root)
            elif name == 'plan-snapshot': value = planning.plan_snapshot(safe(self.root, p['figure_table_plan']))
            elif name == 'plan-audit': value = planning.review_plan(p, self.root)
            elif name == 'citation-check':
                issues = science.validate('literature', p, self.root)
                value = {'status': 'fail' if issues else 'pass', 'issues': issues, 'validation': 'record_integrity_not_external_truth'}
            elif name == 'experiment-template':
                from .experiments import template
                value = template(p, self.root, self.package)
            elif name in {'environment', 'source-fetch', 'reading-index', 'image-export', 'tex-prepare', 'pdf-inspect', 'bibliography', 'revision-record', 'statistics'}:
                from .production import run
                value = run(name, p, self.root)
            else: raise Refusal('Unknown deterministic research tool')
            writes = {out: value} if out else {}
            extra_written = {}
            if publish:
                if name != 'venue-calibrate': raise Refusal('publish is only defined for venue-calibrate output fields')
                writes = {p[key]: item for key, item in value.items() if key in {'measurements', 'venue_profile', 'venue_plan_check', 'venue_comparison'}}
                if p.get('reading_index'):
                    from .production import reading_index
                    extra_written = reading_index(p, self.root)['hashes']
            for target_name, item in writes.items():
                target = safe(self.root, target_name, output=True)
                if target.exists():
                    if planning._without_clock({k:v for k,v in read_json(target).items() if k != 'captured_at'} if name == 'plan-snapshot' else read_json(target)) != planning._without_clock({k:v for k,v in item.items() if k != 'captured_at'} if name == 'plan-snapshot' else item):
                        raise Refusal('Tool output exists with different content; use a new versioned path')
                else: atomic(target, item)
            return {'tool': name, 'value': value, 'written': {**{name: file_hash(safe(self.root, name)) for name in writes}, **extra_written}}

    def draft_preview(self, source, out):
        with self.lock():
            state = self.load()
            pdf = safe(self.root, source)
            if not pdf.read_bytes().startswith(b'%PDF-'): raise Refusal('Draft preview requires an actual PDF')
            target = safe(self.root, out, output=True)
            if target.exists() or not out.endswith('.pdf'): raise Refusal('Use a new .pdf path for each draft preview')
            total, bound = len(state['brief']['deliverable_plan']), len(state['bindings'])
            missing = sorted({i['id'] for i in state['brief']['deliverable_plan']} - set(state['bindings']))
            blockers = ['missing_binding:' + key for key in missing]
            if not any(r['stage'] == 'review' for r in state['receipts']): blockers.append('independent_review_pending')
            blockers += ['unresolved_effect:' + key for key,value in state['attempts'].items() if value['status'] in {'running','uncertain'}]
            blockers += self.stale(state)
            if state['active_round'] is not None: blockers.append('round_checkpoint_pending')
            banner = 'DRAFT COPY - ' + str(bound) + '/' + str(total) + ' items bound; blockers=' + str(len(blockers))
            with tempfile.TemporaryDirectory(prefix='research-draft-') as temp:
                folder = Path(temp); shutil.copyfile(pdf, folder / 'input.pdf')
                tex = folder / 'draft.tex'
                tex.write_text(r'\documentclass{article}\usepackage{pdfpages,xcolor}\begin{document}'
                    + r'\includepdf[pages=-,pagecommand={\thispagestyle{empty}\begin{picture}(0,0)\put(0,0){\color{red}\sffamily\bfseries '
                    + banner + r'}\end{picture}}]{input.pdf}\end{document}')
                built = build_tex(tex, folder)
                target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(built, target)
            return {'status': 'review_draft', 'path': out, 'sha256': file_hash(target), 'items_bound': bound,
                    'items_total': total, 'missing_requirement_ids': missing, 'blockers': blockers, 'not_delivered': True}

    def recover(self, manifest=None):
        with self.lock():
            checkpoint = self.home / 'checkpoint.json'
            if not checkpoint.is_file() or checkpoint.is_symlink() or checkpoint.stat().st_nlink != 1:
                raise Refusal('No provably latest durable checkpoint exists; an older export cannot establish full history')
            latest = read_json(checkpoint)
            state = latest.get('state')
            if latest.get('sha256') != digest(state): raise Refusal('Latest checkpoint failed integrity verification')
            if state.get('implementation_sha256') != self.implementation():
                raise Refusal('Recovery requires the pinned implementation that created the checkpoint')
            if self.path.exists() and digest(read_json(self.path)) == latest['sha256']:
                raise Refusal('The current ledger is intact; it must not be overwritten by recovery')
            if manifest: self.verify_export(manifest)
            self.task_clock_evidence(state)
            state['history'].append({'event': 'ledger_recovered', 'source': 'latest_durable_checkpoint', 'at': now()})
            self.save(state)
            return {'status': 'recovered', 'source': 'latest_durable_checkpoint', 'history_preserved': True,
                    'stale': self.stale(state), 'unresolved_effects': [k for k,v in state['attempts'].items() if v['status'] in {'running','uncertain'}]}

    def read_material(self, name, start=0, end=None):
        with self.lock():
            state = self.load()
            text = safe(self.root, name).read_text()
            end = len(text) if end is None else end
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text) or end - start > 100000:
                raise Refusal('Read a nonempty bounded character span (at most 100000 per call)')
            record = {'path': name, 'sha256': file_hash(self.root / name), 'start': start, 'end': end}
            if record not in state['material_reads']:
                state['material_reads'].append(record)
                self.save(state)
            return {**record, 'text': text[start:end], 'receipt_sha256': digest(record),
                    'meaning': 'bytes returned by the controller; understanding remains a host responsibility'}

    def _hashes(self, packet):
        files = packet.get('artifacts')
        if not isinstance(files, list) or not files or len(files) != len(set(files)):
            raise Refusal('Packet needs a nonempty unique artifacts list')
        return {name: file_hash(safe(self.root, name)) for name in files}

    def validate(self, state, packet):
        from . import planning, science
        if not isinstance(packet, dict) or any(key.startswith('_') for key in packet):
            raise Refusal('Controller fields cannot be supplied by a stage packet')
        original_packet = copy.deepcopy(packet)
        packet = copy.deepcopy(packet)
        if not isinstance(packet, dict) or packet.get('stage') not in STAGES:
            raise Refusal('Unknown packet stage')
        identifier(packet.get('producer'))
        if 'software_fixture' in packet and packet['software_fixture'] is not bool(state['brief'].get('software_fixture')):
            raise Refusal('Stage fixture identity must match the approved Brief')
        self._hashes(packet)
        packet['_brief'] = copy.deepcopy(state['brief'])
        packet['_history'] = {r['stage']: copy.deepcopy(r['packet']) for r in state['receipts']}
        packet['_plan'] = packet['_history'].get('plan', {})
        packet['_venue_confirmation'] = copy.deepcopy(state.get('venue_confirmation'))
        if packet['stage'] == 'write':
            if packet.get('manuscript') != packet.get('manuscript_tex'):
                raise Refusal('Writing checks and final compilation must use the same manuscript source')
        if packet['stage'] == 'review':
            accepted_write = packet['_history'].get('write', {})
            if packet.get('manuscript_pdf') != accepted_write.get('manuscript_pdf'):
                raise Refusal('Independent review must examine the exact accepted manuscript PDF')
        not_applicable = state['brief'].get('not_applicable', {})
        if packet['stage'] in not_applicable:
            if packet['stage'] != 'experiment' or state['brief']['paper_type'] not in {'review', 'survey'} or packet.get('not_applicable') != not_applicable['experiment']:
                raise Refusal('Stage applicability must match the explicitly approved review/survey scope')
            issues = []
        else:
            issues = planning.validate(packet['stage'], packet, self.root) + science.validate(packet['stage'], packet, self.root)
        if issues:
            raise Refusal('; '.join(issues))
        if packet['stage'] == 'intake':
            for material in packet.get('materials', []):
                if material.get('availability') != 'readable':
                    continue
                reads = [(r['start'], r['end']) for r in state['material_reads'] if r['path'] == material['path'] and r['sha256'] == material['sha256']]
                reached = 0
                for start, end in sorted(reads):
                    if start > reached:
                        break
                    reached = max(reached, end)
                if reached != len(safe(self.root, material['path']).read_text()):
                    raise Refusal('Intake needs controller read-material receipts for ' + material['path'])
        if packet['stage'] == 'plan':
            self.check_orders(state, packet.get('work_orders'))
            if state['frozen_plan'] and digest(original_packet) != state['frozen_plan']:
                raise Refusal('Frozen plan cannot be weakened by rewind; approve a revised Brief in a new run')
        if packet['stage'] == 'review':
            self.check_reviews(state, packet)
        return self._hashes(packet)

    def check_orders(self, state, orders):
        if not isinstance(orders, list) or not orders:
            raise Refusal('Plan requires work_orders')
        wanted = check_brief(state['brief'])
        covered, seen = set(), set()
        for order in orders:
            key = identifier(order.get('id'))
            identifier(order.get('producer'))
            if key in seen:
                raise Refusal('Duplicate WorkOrder ' + key)
            seen.add(key)
            reqs = order.get('requirement_ids')
            if not isinstance(reqs, list) or not reqs or not set(reqs) <= wanted:
                raise Refusal('Unknown or empty WorkOrder.requirement_ids')
            covered.update(reqs)
            if not isinstance(order.get('actions'), list) or not order['actions']:
                raise Refusal('WorkOrder requires registered typed actions')
            for action in order['actions']:
                kind = action.get('type')
                if kind not in ACTIONS or set(action) != {'type', *ACTIONS[kind]}:
                    raise Refusal('Unknown action or fields: ' + str(kind))
                for name in ACTIONS[kind]:
                    if name == 'options':
                        from .production import validate_options
                        validate_options(kind, action[name])
                    else:
                        safe(self.root, action[name], output=True)
        if wanted - covered:
            raise Refusal('Plan omits requirements: ' + ', '.join(sorted(wanted - covered)))

    def operation(self, state, op, request):
        identifier(op)
        if op in state['operations']:
            stored = state['operations'][op]
            if stored['request_sha256'] != digest(request):
                raise Refusal('Operation ID reused with different arguments')
            return stored['result']
        return None

    def record(self, state, op, request, result):
        state['operations'][op] = {'request_sha256': digest(request), 'result': result}
        state['history'].append({'operation': op, 'at': now(), 'request_sha256': digest(request), 'result': result})
        self.save(state)
        return result

    def commit(self, packet, op):
        with self.lock():
            state = self.load()
            request = {'command': 'commit', 'packet': packet}
            previous = self.operation(state, op, request)
            if previous is not None:
                return previous
            self.ready(state, preparation=packet.get('stage') in {'intake', 'venue'})
            if packet.get('stage') in {'literature','experiment','figures','write','review'} and state['active_round'] is None:
                raise Refusal('begin-round must record the pre-work snapshot before research artifacts are committed')
            if len(state['receipts']) == len(STAGES) or packet.get('stage') != STAGES[len(state['receipts'])]:
                raise Refusal('Out-of-order stage')
            if packet.get('stage') == 'venue':
                self.confirmed_venue(state, packet)
            if packet.get('stage') == 'plan':
                self.confirmed_budget(state, packet['figure_table_plan'])
            hashes = self.validate(state, packet)
            if packet['stage'] == 'plan':
                state['frozen_plan'] = digest(packet)
            if state['active_round'] is not None: state['active_round']['stages_completed'].append(packet['stage'])
            state['receipts'].append({'stage': packet['stage'], 'packet': packet,
                                      'hashes': hashes, 'at': now(), 'operation': op})
            return self.record(state, op, request, {'status': 'recorded', 'stage': packet['stage'], 'hashes': hashes})

    def rewind(self, stage, reason, op, preserve=()):
        with self.lock():
            state = self.load()
            request = {'command': 'rewind', 'stage': stage, 'reason': reason, 'preserve': list(preserve)}
            previous = self.operation(state, op, request)
            if previous is not None:
                return previous
            if stage not in STAGES or not reason.strip():
                raise Refusal('Rewind requires a known stage and reason')
            if state['active_round'] is None:
                from .rounds import documents
                from .budget import ensure_work_allowed
                ensure_work_allowed(state)
                plan_path = next((r['packet']['figure_table_plan'] for r in state['receipts'] if r['stage'] == 'plan'), None)
                state['active_round'] = {'id': 'round-' + str(len(state['rounds'])+1), 'started_at': now(), 'stage': stage, 'stages_completed': [], 'documents': documents(self.root),
                    'plan_path': plan_path, 'plan': read_json(safe(self.root,plan_path)) if plan_path else None, 'plan_sha256': file_hash(safe(self.root,plan_path)) if plan_path else None}
            cut = STAGES.index(stage)
            removed = state['receipts'][cut:]
            if not removed:
                raise Refusal('Stage has no recorded receipt')
            available = {name: value for receipt in removed for name, value in receipt['hashes'].items()}
            baselines = []
            from .production import write_once
            for name in preserve:
                origin = safe(self.root, name)
                if available.get(name) != file_hash(origin):
                    raise Refusal('Preserve an accepted baseline before modifying it: ' + name)
                target = 'revisions/' + identifier(op) + '/' + name
                write_once(self.root, target, origin.read_bytes())
                baselines.append({'original_path': name, 'path': target, 'sha256': file_hash(origin)})
            state['receipts'] = state['receipts'][:cut]
            state['bindings'] = {}
            state['delivery'] = None
            state['history'].append({'event': 'invalidated', 'reason': reason, 'receipts': removed,
                                     'baselines': baselines, 'at': now()})
            return self.record(state, op, request, {'status': 'rewound', 'stage': stage, 'baselines': baselines})

    def begin_round(self, *, session_id=None):
        from .rounds import documents, checkpoint
        with self.lock():
            state = self.load()
            self.ready(state, preparation=True)
            if session_id:
                identifier(session_id)
                if state['session'].get('id') != session_id:
                    if state['active_round'] is not None:
                        raise Refusal('Finish the current checkpoint before changing host session identity')
                    if any(h.get('event') == 'session_started' and h.get('id') == session_id for h in state['history']):
                        raise Refusal('Session identifier was already used')
                    state['session'] = {'id': session_id, 'started_at': now(), 'rounds': 0, 'experiment_rounds': 0}
                    state['history'].append({'event': 'session_started', 'id': session_id, 'at': now()})
            from .budget import ensure_work_allowed
            ensure_work_allowed(state)
            state['last_seen_at'] = now()
            if state['active_round'] is None:
                plan = next((r['packet']['figure_table_plan'] for r in state['receipts'] if r['stage'] == 'plan'), None)
                state['active_round'] = {'id': 'round-' + str(len(state['rounds']) + 1), 'started_at': now(), 'stage': STAGES[min(len(state['receipts']),7)], 'stages_completed': [],
                                         'documents': documents(self.root), 'plan_path': plan,
                                         'plan': read_json(safe(self.root, plan)) if plan else None,
                                         'plan_sha256': file_hash(safe(self.root, plan)) if plan else None}
            self.save(state)
            from .budget import summary
            return {'status': 'round_started', 'round': state['active_round'], 'budget': summary(state), 'checkpoint': checkpoint(state)}

    def prepare_round(self, evidence, current_plan=None):
        from .rounds import workload, documents
        with self.lock():
            state = self.load()
            self.ready(state, preparation=True)
            if state['active_round'] is None and any(r['stage'] == 'plan' for r in state['receipts']):
                raise Refusal('begin-round must capture the original plan before work starts')
            hashes = self._hashes({'artifacts': evidence}) if evidence else {}
            active = state['active_round']
            plan_path = current_plan or (active and active['plan_path'])
            plan = read_json(safe(self.root, plan_path)) if plan_path else None
            old = {i['id']: i for i in active['plan'].get('items', [])} if active and active['plan'] else {}
            new = {i['id']: i for i in plan.get('items', [])} if plan else {}
            state['pending_round'] = None
            request = {'state_sha256': digest({**state, 'last_seen_at': None}), 'brief_sha256': state['brief_sha256'],
                       'evidence': hashes, 'stale_count': state['stale_count'],
                       'round': copy.deepcopy(active), 'current_plan': plan_path,
                       'current_plan_sha256': file_hash(safe(self.root, plan_path)) if plan_path else None,
                       'plan_diff': {'removed': sorted(set(old)-set(new)), 'added': sorted(set(new)-set(old)),
                                     'changed': sorted(k for k in set(old)&set(new) if old[k] != new[k])},
                       'workload': workload(self.root, active['documents']) if active else None,
                       'documents_sha256': digest(documents(self.root)), 'rules_sha256': self.rules_hash()}
            issued = {**request, 'request_sha256': digest(request)}
            state['pending_round'] = issued
            self.save(state)
            # This reserved directory is excluded from research workload digests.
            target = self.root / 'control/round-decisions' / (issued['request_sha256'] + '-request.json')
            safe(self.root, str(target.relative_to(self.root)), output=True, internal=True)
            if target.exists() and read_json(target) != issued:
                raise Refusal('Stored round request differs from its digest')
            atomic(target, issued)
            return issued

    def rules_hash(self):
        paths = [Path(__file__), *sorted((self.package / 'references/knowledge').glob('*.md'))]
        return digest({str(p.relative_to(self.package)): file_hash(p) for p in paths})

    def apply_round(self, request, decision, op):
        with self.lock():
            state = self.load()
            if request is None:
                request = state.get('pending_round')
            if not isinstance(request, dict):
                raise Refusal('Prepare the actual round request before applying its judgment')
            arguments = {'command': 'round', 'request': request, 'decision': decision}
            previous = self.operation(state, op, arguments)
            if previous is not None:
                return previous
            preparation_round = state['brief'].get('contract_status') == 'draft' and all(
                receipt['stage'] in {'intake', 'venue'} for receipt in state['receipts'])
            self.ready(state, preparation=preparation_round)
            core = {k: v for k, v in request.items() if k != 'request_sha256'}
            if request.get('request_sha256') != digest(core) or decision.get('request_sha256') != digest(core):
                raise Refusal('Round request digest mismatch')
            if state.get('pending_round') != request:
                raise Refusal('Round request was not issued by the current controller preparation')
            base_state = {**state, 'pending_round': None, 'last_seen_at': None}
            if request.get('state_sha256') != digest(base_state) or request.get('rules_sha256') != self.rules_hash():
                raise Refusal('Round state or knowledge changed; prepare and judge again')
            if any(file_hash(safe(self.root, name)) != sha for name, sha in request.get('evidence', {}).items()):
                raise Refusal('Round evidence changed; prepare and judge again')
            from .rounds import documents
            if request.get('documents_sha256') != digest(documents(self.root)):
                raise Refusal('Round documents changed after preparation; recompute workload and judge again')
            kind = decision.get('progress')
            if kind not in {'verified_progress', 'no_progress', 'regression'} or not decision.get('reason'):
                raise Refusal('Round needs a supported progress kind and reason')
            if decision.get('status') not in {'active', 'needs_input', 'stopped'}:
                raise Refusal('Round cannot grant completion; use the deterministic finalizer')
            self.validate_exit(state, request, decision)
            if state['rounds'] and kind == 'verified_progress' and request['evidence'] == state['rounds'][-1]['request']['evidence']:
                raise Refusal('Unchanged evidence is not new progress')
            from .rounds import checkpoint, experimental_scope
            active = state['active_round'] or {}
            experiment_steps = active.get('stages_completed', []).count('experiment')
            experimental_round = experimental_scope(state['brief']) and (decision.get('phase') == 'experiment' or active.get('stage') == 'experiment' or experiment_steps > 0)
            if kind != 'no_progress' and not request.get('evidence'):
                raise Refusal('Progress or regression needs real evidence')
            if request.get('current_plan') and file_hash(safe(self.root, request['current_plan'])) != request['current_plan_sha256']:
                raise Refusal('Current plan changed after round preparation')
            changed_plan = any(request.get('plan_diff', {}).values())
            if changed_plan:
                r6 = decision.get('r6', {})
                refs = r6.get('evidence')
                if r6.get('verdict') not in {'disclosed_deviation','scientifically_adjusted'} or not isinstance(refs,list) or not refs or not set(refs) <= set(request['evidence']):
                    raise Refusal('Changed round commitments require explicit evidence-bound R6 disclosure')
                reports = [read_json(safe(self.root,name)) for name in refs if name.endswith('.json')]
                if not any(report.get('round_id') == active.get('id') and report.get('original_plan_sha256') == active.get('plan_sha256')
                           and report.get('current_plan_sha256') == request.get('current_plan_sha256') and report.get('verdict') == r6['verdict'] for report in reports):
                    raise Refusal('R6 report must bind this round original plan and actual current plan')
            direction = decision.get('direction')
            if direction:
                if not direction.get('id') or not direction.get('change') or not direction.get('reason'):
                    raise Refusal('Pivot must state the structural change and rationale')
                if any(r['decision'].get('direction', {}).get('id') == direction['id'] for r in state['rounds'] if r['decision'].get('direction')):
                    raise Refusal('Direction already tried')
            finding = decision.get('finding')
            if finding:
                if kind == 'no_progress' or not finding.get('claim') or 'limitations' not in finding or not isinstance(finding['limitations'], str) or not finding.get('validation'):
                    raise Refusal('Finding requires evidence interpretation and limitations')
                identifier(finding.get('id'))
                existing = {r['decision']['finding']['id']: r['decision']['finding'] for r in state['rounds'] if r['decision'].get('finding')}
                if finding['id'] in existing or (finding.get('revises') is not None and finding['revises'] not in existing):
                    raise Refusal('Finding identity or revision lineage is invalid')
                normalized = ' '.join(finding['claim'].casefold().split())
                for row in state['rounds']:
                    old = row['decision'].get('finding')
                    if old and ' '.join(old['claim'].casefold().split()) == normalized and finding.get('revises') is None:
                        raise Refusal('Duplicate finding cannot inflate progress')
            state['stale_count'] = 0 if kind == 'verified_progress' else state['stale_count'] + 1
            state['session']['rounds'] += 1
            if experimental_round: state['session']['experiment_rounds'] += max(1, experiment_steps)
            state['last_seen_at'] = now()
            if kind == 'verified_progress': state['last_progress_at'] = now()
            state['last_round_status'] = decision['status']
            state['last_checkpoint_at'] = now()
            state['active_round'] = None
            state['pending_round'] = None
            state['rounds'].append({'request': request, 'decision': decision, 'at': now(),
                                    'validation': 'structure_and_binding_only'})
            from .budget import summary
            return self.record(state, op, arguments, {'status': 'round_recorded', 'round': len(state['rounds']),
                                                      'stale_count': state['stale_count'], 'budget': summary(state), 'checkpoint': checkpoint(state), 'attention_required': state['stale_count'] >= 4, 'total_findings': sum(1 for r in state['rounds'] if r['decision'].get('finding') and not r['decision']['finding'].get('revises'))})

    def revise_orders(self, orders, reason, op):
        with self.lock():
            state = self.load()
            request = {'command': 'revise-orders', 'orders': orders, 'reason': reason}
            previous = self.operation(state, op, request)
            if previous is not None:
                return previous
            self.ready(state)
            if not reason.strip() or any(r['stage'] == 'review' for r in state['receipts']):
                raise Refusal('Rewind review before revising work; record the reason')
            plan = next((r['packet'] for r in state['receipts'] if r['stage'] == 'plan'), None)
            if not plan or not isinstance(orders, list) or not orders:
                raise Refusal('A validated plan and new versioned work orders are required')
            existing = [*plan['work_orders'], *state['additional_orders']]
            self.check_orders(state, [*existing, *orders])
            known = {o['id'] for o in existing}
            for order in orders:
                if order.get('supersedes') and order['supersedes'] not in known:
                    raise Refusal('Superseded WorkOrder is unknown')
            state['additional_orders'].extend(orders)
            state['history'].append({'event': 'work_orders_revised', 'orders': orders, 'reason': reason, 'at': now()})
            return self.record(state, op, request, {'status': 'orders_registered', 'ids': [o['id'] for o in orders]})

    def _order(self, state, key):
        plan = next((r['packet'] for r in state['receipts'] if r['stage'] == 'plan'), None)
        if not plan:
            raise Refusal('A validated plan is required')
        orders = [*plan['work_orders'], *state['additional_orders']]
        self.check_orders(state, orders)
        order = next((o for o in orders if o['id'] == key), None)
        if not order:
            raise Refusal('Unknown WorkOrder')
        return order

    def _action(self, state, action):
        kind = action['type']
        if kind in {'export_image', 'prepare_tex'}:
            from .production import export_image, prepare_tex
            if safe(self.root, action['target'], output=True).exists():
                raise Refusal('Typed production output exists; use a new versioned path')
            packet = {key: value for key, value in action.items() if key != 'type'}
            value = (export_image if kind == 'export_image' else prepare_tex)(packet, self.root)
            return {'status': 'completed', **value}
        if kind == 'validate_packet':
            packet = read_json(safe(self.root, action['packet']))
            self.validate(state, packet)
            return {'status': 'completed', 'hashes': self._hashes(packet)}
        if kind == 'compile_tex':
            source = safe(self.root, action['source'])
            target = safe(self.root, action['pdf'], output=True)
            if source.suffix != '.tex' or target.suffix != '.pdf':
                raise Refusal('compile_tex expects .tex and .pdf')
            if target.exists():
                raise Refusal('compile_tex output already exists; use a new versioned path')
            executable = shutil.which('pdflatex')
            if not executable:
                raise Refusal('pdflatex is unavailable')
            with tempfile.TemporaryDirectory(prefix='paper-tex-') as temp:
                built = build_tex(source, temp)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(built, target)
            return {'status': 'completed', 'hashes': {action['pdf']: file_hash(target)}}
        if kind == 'render_statistics':
            from .science import render_statistics
            for key in ('table', 'figure'):
                if safe(self.root, action[key], output=True).exists():
                    raise Refusal('Render output already exists; use a new versioned path')
            return render_statistics(self.root, action['input'], action['table'], action['figure'])
        if kind == 'copy_artifact':
            source = safe(self.root, action['source'])
            target = safe(self.root, action['target'], output=True)
            if target.exists():
                raise Refusal('Copy would overwrite an artifact')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            return {'status': 'completed', 'hashes': {action['target']: file_hash(target)}}
        raise Refusal('Unknown typed action')

    def execute(self, work_id, op, *, fixture_fault=False):
        with self.lock():
            state = self.load()
            order = self._order(state, work_id)
            request = {'command': 'execute', 'work_id': work_id, 'order_sha256': digest(order)}
            previous = self.operation(state, op, request)
            if previous is not None:
                return previous
            if op in state['attempts']:
                raise Refusal('Attempt has no terminal receipt; reconcile before replay')
            self.ready(state)
            from .budget import ensure_work_allowed
            ensure_work_allowed(state)
            if state['active_round'] is None:
                raise Refusal('begin-round must capture pre-work evidence before typed actions execute')
            if any(a['work_id'] == work_id and a['status'] == 'completed' for a in state['attempts'].values()):
                raise Refusal('WorkOrder already completed; create a new versioned order for new effects')
            attempt = {'work_id': work_id, 'order_sha256': digest(order), 'status': 'running',
                       'started_at': now(), 'actions': [], 'brief_sha256': state['brief_sha256']}
            state['attempts'][op] = attempt
            self.save(state)
            for action in order['actions']:
                attempt['pending_action'] = action
                attempt['pending_input_hashes'] = {}
                try:
                    inputs = {'compile_tex': ('source',), 'copy_artifact': ('source',), 'render_statistics': ('input',),
                              'validate_packet': ('packet',), 'export_image': ('source',), 'prepare_tex': ('source',)}[action['type']]
                    attempt['pending_input_hashes'] = {action[k]: file_hash(safe(self.root, action[k])) for k in inputs if safe(self.root, action[k], output=True).is_file()}
                    if action['type'] == 'prepare_tex':
                        from .production import tex_bytes
                        _, included = tex_bytes(self.root, action['source'], action['options'])
                        attempt['pending_input_hashes'].update(included)
                    self.save(state)
                    effect = self._action(state, action)
                    if fixture_fault and state['brief'].get('software_fixture'):
                        raise KeyboardInterrupt('software fixture: terminal receipt lost')
                    outputs = action_outputs(action)
                    if action['type'] == 'render_statistics':
                        outputs += [action['table'] + '.stats.json', action['figure'] + '.trace.json']
                    effect['hashes'] = {**effect.get('hashes', {}), **{name: file_hash(safe(self.root, name)) for name in outputs}}
                    attempt['actions'].append({'action': action, 'effect': effect, 'input_hashes': dict(attempt['pending_input_hashes'])})
                    attempt.pop('pending_action', None)
                    self.save(state)
                except KeyboardInterrupt:
                    attempt['status'] = 'uncertain'
                    self.save(state)
                    raise
                except Exception as exc:
                    # A callable may have written before failing. Retain uncertainty until reconciled.
                    attempt['status'] = 'uncertain' if any(safe(self.root, name, output=True).exists() for name in action_outputs(action)) else 'failed'
                    attempt['error'] = str(exc)
                    self.save(state)
                    if attempt['status'] == 'uncertain':
                        raise Refusal('Effect may have occurred; reconcile: ' + str(exc)) from exc
                    return self.record(state, op, request, {'status': 'failed', 'error': str(exc)})
            attempt['status'] = 'completed'
            attempt['finished_at'] = now()
            return self.record(state, op, request, {'status': 'completed', 'attempt': op, 'effects': attempt['actions']})

    def reconcile(self, attempt_id, outcome, evidence, op):
        with self.lock():
            state = self.load()
            request = {'command': 'reconcile', 'attempt': attempt_id, 'outcome': outcome, 'evidence': evidence}
            previous = self.operation(state, op, request)
            if previous is not None:
                return previous
            attempt = state['attempts'].get(attempt_id)
            if not attempt or attempt['status'] not in {'running', 'uncertain'}:
                raise Refusal('No uncertain attempt to reconcile')
            report = read_json(safe(self.root, evidence))
            if report.get('attempt') != attempt_id or report.get('outcome') != outcome or not report.get('reason'):
                raise Refusal('Reconciliation must identify the attempt, disposition and evidence')
            if report.get('order_sha256') != attempt['order_sha256'] or report.get('pending_action') != attempt.get('pending_action'):
                raise Refusal('Reconciliation must bind the exact order and pending action')
            if self.stale(state) or any(file_hash(safe(self.root, name)) != sha for name, sha in attempt.get('pending_input_hashes', {}).items()):
                raise Refusal('Reconciliation inputs changed; retain the uncertain disposition')
            hashes = report.get('artifact_hashes', {})
            if not hashes or any(file_hash(safe(self.root, name)) != sha for name, sha in hashes.items()):
                raise Refusal('Reconciliation requires current, bound evidence')
            if outcome not in {'completed', 'failed', 'not_started'}:
                raise Refusal('Unknown disposition')
            pending = attempt.get('pending_action')
            expected_outputs = action_outputs(pending) if pending else []
            if pending and pending['type'] == 'render_statistics':
                expected_outputs += [pending['table'] + '.stats.json', pending['figure'] + '.trace.json']
            if outcome == 'completed':
                for finished in attempt['actions']:
                    for name, sha in {**finished.get('input_hashes', {}), **finished['effect'].get('hashes', {})}.items():
                        if not safe(self.root, name, output=True).is_file() or file_hash(safe(self.root, name)) != sha:
                            raise Refusal('Earlier action input or output changed during reconciliation')
                if pending and pending['type'] == 'validate_packet':
                    self._action(state, pending)  # A pure check is safe to recompute, never to assume completed.
                order = self._order(state, attempt['work_id'])
                count = len(attempt['actions']) + (1 if pending else 0)
                if count != len(order['actions']) or not set(expected_outputs) <= set(hashes):
                    raise Refusal('Completed reconciliation must account for every action and its expected outputs')
                for name in expected_outputs:
                    if not safe(self.root, name).stat().st_size:
                        raise Refusal('Completed action output is empty')
                if pending and pending['type'] == 'compile_tex' and not safe(self.root, pending['pdf']).read_bytes().startswith(b'%PDF-'):
                    raise Refusal('Completed compilation requires its actual PDF')
                if pending and pending['type'] == 'copy_artifact' and hashes[pending['target']] != attempt['pending_input_hashes'].get(pending['source']):
                    raise Refusal('Copy output does not match its captured source')
                if pending and pending['type'] in {'prepare_tex', 'export_image'}:
                    from .production import tex_bytes, image_bytes
                    if pending['type'] == 'prepare_tex':
                        expected, _ = tex_bytes(self.root, pending['source'], pending['options'])
                    else:
                        expected, _ = image_bytes(self.root, pending['source'], pending['target'], pending['options'])
                    if safe(self.root, pending['target']).read_bytes() != expected:
                        raise Refusal('Reconciled production output differs from its captured policy and source')
            if outcome == 'not_started' and (attempt['actions'] or any(safe(self.root, name, output=True).exists() for name in expected_outputs)):
                raise Refusal('Effects exist; this attempt cannot be classified not_started')
            attempt['status'] = outcome
            attempt['reconciliation'] = {'path': evidence, 'sha256': file_hash(self.root / evidence), 'at': now()}
            attempt.pop('pending_action', None)
            return self.record(state, op, request, {'status': 'reconciled', 'outcome': outcome})

    def bind(self, binding, op):
        with self.lock():
            state = self.load()
            request = {'command': 'bind', 'binding': binding}
            previous = self.operation(state, op, request)
            if previous is not None:
                return previous
            self.ready(state)
            if len(state['receipts']) < 7 or any(r['stage'] == 'review' for r in state['receipts']):
                raise Refusal('Bind after writing and before independent review')
            wanted = check_brief(state['brief'])
            key = binding.get('requirement_id')
            if key not in wanted:
                raise Refusal('Unknown requirement binding')
            order = self._order(state, binding.get('work_id'))
            if key not in order['requirement_ids']:
                raise Refusal('WorkOrder does not cover this requirement')
            if not any(a['work_id'] == order['id'] and a['status'] == 'completed' for a in state['attempts'].values()):
                raise Refusal('Binding needs a completed WorkOrder receipt')
            write = next(r['packet'] for r in state['receipts'] if r['stage'] == 'write')
            if binding.get('manuscript') != write.get('manuscript_tex'):
                raise Refusal('Binding refers to a different manuscript')
            text = tex_without_comments(safe(self.root, binding['manuscript']).read_text())
            if not binding.get('location') or binding['location'] not in text:
                raise Refusal('Bound item is absent from manuscript')
            if not binding.get('assets') or not binding.get('evidence'):
                raise Refusal('Binding needs assets and evidence')
            names = [*binding['assets'], *binding['evidence'], binding['manuscript']]
            available = {p: sha for r in state['receipts'] for p, sha in r['hashes'].items()}
            hashes = {name: file_hash(safe(self.root, name)) for name in names}
            if any(available.get(name) != sha for name, sha in hashes.items()):
                raise Refusal('Binding uses unvalidated or stale assets/evidence')
            requirement = next(i for i in state['brief']['deliverable_plan'] if i['id'] == key)
            if requirement['kind'] in {'figure', 'table'}:
                for other_id, other in state['bindings'].items():
                    other_requirement = next(i for i in state['brief']['deliverable_plan'] if i['id'] == other_id)
                    if other_id != key and other_requirement['kind'] in {'figure', 'table'} and set(binding['assets']) & set(other['assets']):
                        raise Refusal('Distinct visual requirements cannot reuse the same primary asset')
                command = 'includegraphics' if requirement['kind'] == 'figure' else '(?:input|include)'
                references = re.findall(r'\\' + command + r'(?:\[[^\]]*\])?\{([^}]+)\}', text)
                referenced = set()
                source_dir = safe(self.root, binding['manuscript']).parent
                for value in references:
                    candidate = source_dir / value
                    referenced.add(candidate.resolve())
                    if not candidate.suffix:
                        referenced.add(candidate.with_suffix('.pdf' if requirement['kind'] == 'figure' else '.tex').resolve())
                if any(safe(self.root, asset).resolve() not in referenced for asset in binding['assets']):
                    raise Refusal('Figure/table asset is not literally inserted in the selected manuscript')
            if key in state['bindings']:
                state['history'].append({'event': 'binding_superseded', 'binding': state['bindings'][key], 'at': now()})
            stored = {**binding, 'hashes': hashes, 'producer': order['producer'], 'brief_sha256': state['brief_sha256']}
            stored['binding_sha256'] = digest(stored)
            state['bindings'][key] = stored
            return self.record(state, op, request, {'status': 'bound', 'requirement_id': key, 'binding_sha256': stored['binding_sha256']})

    def bind_all(self, bindings, op):
        identifier(op)
        if not isinstance(bindings, list) or not bindings:
            raise Refusal('bind-all expects a nonempty array of task-specific bindings')
        ids = [item.get('requirement_id') for item in bindings if isinstance(item, dict)]
        if len(ids) != len(bindings) or len(set(ids)) != len(ids):
            raise Refusal('bind-all needs unique requirement IDs')
        results = []
        for binding in bindings:
            # Each completed suboperation is durable and can be reused on retry.
            suffix = digest(binding['requirement_id'])[:12]
            results.append(self.bind(binding, 'batch-' + digest(op)[:24] + '-' + suffix))
        return {'status': 'bound', 'items': results}

    def check_reviews(self, state, packet):
        if 'findings' in packet and (not isinstance(packet['findings'], list) or
                any(not isinstance(item, dict) or item.get('status') != 'closed' for item in packet['findings'])):
            raise Refusal('Unresolved independent findings prevent final acceptance')
        wanted = check_brief(state['brief'])
        if set(state['bindings']) != wanted:
            raise Refusal('Missing requirement bindings: ' + ', '.join(sorted(wanted - set(state['bindings']))))
        reviewers = state['brief'].get('reviewers', [])
        reviewer = packet.get('reviewer')
        if reviewer not in reviewers:
            raise Refusal('Review requires an independently declared reviewer')
        authors = {r['packet']['producer'] for r in state['receipts'] if r['stage'] != 'review'}
        authors.update(b['producer'] for b in state['bindings'].values())
        if reviewer in authors:
            raise Refusal('Reviewer also produced this evidence')
        checks = packet.get('requirement_checks')
        if not isinstance(checks, list) or len(checks) != len(wanted) or {c.get('requirement_id') for c in checks} != wanted:
            raise Refusal('Independent requirement_checks must cover every approved ID exactly once')
        for check in checks:
            binding = state['bindings'][check['requirement_id']]
            if check.get('binding_sha256') != binding['binding_sha256'] or check.get('verdict') != 'fulfilled':
                raise Refusal('Unmet or stale requirement: ' + check['requirement_id'])
            if check.get('evidence_hashes') != binding['hashes'] or not check.get('rationale'):
                raise Refusal('Requirement review lacks exact artifact evidence')
            for name, sha in binding['hashes'].items():
                if file_hash(safe(self.root, name)) != sha:
                    raise Refusal('Requirement artifact changed: ' + name)
        gates = packet.get('gates', {})
        if any(not g.get('reason') for g in gates.values()):
            raise Refusal('Every quality gate requires a substantive reason and bound evidence')
        if any(not isinstance(g.get('evidence'), list) or not set(g['evidence']) <= set(packet['artifacts']) for g in gates.values()):
            raise Refusal('Review gate evidence must be declared and hash-bound')
        allowed_na = state['brief'].get('not_applicable', {}).get('experiment')
        if set(gates) != {'G1', 'G2', 'G3', 'G4', 'G5', 'R6'} or any((g.get('verdict') != 'pass' and not (key == 'G2' and g.get('verdict') == 'not_applicable' and allowed_na and g.get('reason') == allowed_na)) or not g.get('evidence') for key, g in gates.items()):
            raise Refusal('Review requires evidence for G1-G5 and R6; overall score cannot waive an item')

    def rebuild_package(self, directory, write):
        source = directory / 'artifacts' / write['manuscript_tex']
        original = directory / 'artifacts' / write['manuscript_pdf']
        executable, extractor = shutil.which('pdflatex'), shutil.which('pdftotext')
        if not executable or not extractor:
            raise Refusal('Verified export requires pdflatex and pdftotext')
        with tempfile.TemporaryDirectory(prefix='paper-rebuild-') as temp:
            rebuilt = build_tex(source, temp)
            def text(path):
                return subprocess.check_output([extractor, '-layout', str(path), '-'], text=True)
            if text(original) != text(rebuilt):
                raise Refusal('Rebuilt source does not reproduce the reviewed PDF text')
            return {'status': 'rebuilt_from_exported_assets', 'pdf_text_sha256': hashlib.sha256(text(original).encode()).hexdigest(),
                    'tool': subprocess.check_output([executable, '--version'], text=True).splitlines()[0]}

    def finalize(self, op):
        with self.lock():
            state = self.load()
            request = {'command': 'finalize'}
            previous = self.operation(state, op, request)
            if previous is not None:
                self.verify_export(previous['manifest'])
                return previous
            self.ready(state)
            if state['active_round'] is not None:
                raise Refusal('Record the actual final round checkpoint before delivery')
            if len(state['receipts']) != len(STAGES):
                raise Refusal('All stages, including independent itemized review, must be recorded')
            completed = {a['work_id'] for a in state['attempts'].values() if a['status'] == 'completed'}
            for attempt in state['attempts'].values():
                if attempt['status'] == 'failed' and attempt['work_id'] not in completed and not any(o.get('supersedes') == attempt['work_id'] and o['id'] in completed for o in state['additional_orders']):
                    raise Refusal('Failed work needs a completed retry or explicitly superseding work before delivery')
            for receipt in state['receipts']:
                self.validate(state, receipt['packet'])
            write = next(r['packet'] for r in state['receipts'] if r['stage'] == 'write')
            from .science import validate_delivery
            review = next(r['packet'] for r in state['receipts'] if r['stage'] == 'review')
            delivery_packet = {'artifacts': list({p for r in state['receipts'] for p in r['hashes']}), 'completion': review.get('completion'), '_brief': state['brief'], '_history': {r['stage']: r['packet'] for r in state['receipts']}}
            issues = validate_delivery(delivery_packet, self.root)
            if issues: raise Refusal('; '.join(issues))
            pdf = safe(self.root, write['manuscript_pdf'])
            if not pdf.read_bytes().startswith(b'%PDF-'):
                raise Refusal('Final manuscript is not a PDF')
            assets = {name: sha for r in state['receipts'] for name, sha in r['hashes'].items()}
            assets.update(self.budget_evidence(state))
            assets.update(self.task_clock_evidence(state))
            from .user_input import check_human_response
            answers = [q['response']['human_response'] for q in state['user_questions'].values() if q.get('status') == 'answered']
            answers += [change['human_response'] for change in (state.get('approval') or {}).get('user_amendments', [])]
            answers += [record['human_response'] for record in [state.get('venue_confirmation'), state.get('budget_confirmation')] if record and record.get('human_response')]
            for answer in answers:
                source = check_human_response(answer, self.root)
                assets[source['path']] = source['sha256']
            dest = self.root / 'delivery' / op
            if dest.exists():
                # Reconcile an interrupted export by verifying a finished manifest; never overwrite it.
                manifest = 'delivery/' + op + '/manifest.json'
                self.verify_export(manifest)
            else:
                dest.parent.mkdir(exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='.export-', dir=dest.parent) as td:
                    temp = Path(td) / 'package'
                    temp.mkdir()
                    for name in assets:
                        target = temp / 'artifacts' / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(safe(self.root, name), target)
                    software = {}
                    for folder in ('lib', 'scripts', 'references', 'vendor'):
                        for origin in sorted((self.package / folder).rglob('*')):
                            if not origin.is_file() or '__pycache__' in origin.parts or 'tests' in origin.parts or origin.suffix == '.pyc':
                                continue
                            name = str(origin.relative_to(self.package))
                            target = temp / 'software' / name
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(origin, target)
                            software[name] = file_hash(target)
                    # The installed runtime and repository checkout resolve these
                    # protocols differently. Ship the actual closure in either case.
                    for name in ('plan.md', 'reason.md', 'iterate.md', 'autoresearch.md', 'fork-and-flush.md'):
                        origin = self.package / 'upstream' / name
                        if not origin.is_file():
                            if name == 'fork-and-flush.md':
                                origin = self.package.parent / '.claude/skills/autoresearch/references' / name
                            else:
                                origin = self.package.parent / '.claude/commands/autoresearch' / ('iterate.md' if name == 'autoresearch.md' else name)
                        if not origin.is_file():
                            raise Refusal('Export runtime lacks its upstream protocol: ' + name)
                        target = temp / 'software/upstream' / name
                        target.parent.mkdir(exist_ok=True)
                        shutil.copyfile(origin, target)
                        software['upstream/' + name] = file_hash(target)
                    for name in ('NOTICE.md', 'provenance.json', 'upstream-license.txt'):
                        origin = self.package / name
                        if not origin.exists() and name == 'upstream-license.txt':
                            origin = self.package.parent / 'LICENSE'
                        if origin.is_file():
                            target = temp / 'software' / name
                            shutil.copyfile(origin, target)
                            software[name] = file_hash(target)
                    rebuild = self.rebuild_package(temp, write)
                    atomic(temp / 'control.json', state)
                    from .budget import summary
                    payload = {'schema_version': 1, 'brief_sha256': state['brief_sha256'], 'task_budget': summary(state),
                               'software_fixture': bool(state['brief'].get('software_fixture')), 'rebuild': rebuild,
                               'artifacts': assets, 'software': software, 'state_sha256': file_hash(temp / 'control.json'),
                               'manuscript_pdf': write['manuscript_pdf'], 'manuscript_tex': write['manuscript_tex']}
                    atomic(temp / 'manifest.json', payload)
                    os.rename(temp, dest)
                manifest = 'delivery/' + op + '/manifest.json'
            self.verify_export(manifest)
            archive = self.root / 'delivery' / (op + '.zip')
            if not archive.exists():
                with tempfile.NamedTemporaryFile(dir=archive.parent, suffix='.zip', delete=False) as stream:
                    pending_zip = Path(stream.name)
                try:
                    with zipfile.ZipFile(pending_zip, 'w', zipfile.ZIP_DEFLATED) as zipped:
                        for item in sorted(dest.rglob('*')):
                            if item.is_file():
                                zipped.write(item, str(item.relative_to(dest)))
                    os.rename(pending_zip, archive)
                finally:
                    if pending_zip.exists():
                        pending_zip.unlink()
            state['delivery'] = manifest
            self.verify_export(manifest)
            return self.record(state, op, request, {'status': 'software_fixture_complete' if state['brief'].get('software_fixture') else 'internally_reviewed',
                                                  'manifest': manifest, 'pdf': str(dest / 'artifacts' / write['manuscript_pdf']),
                                                  'tex': str(dest / 'artifacts' / write['manuscript_tex']), 'archive': str(archive)})

    def verify_export(self, manifest):
        path = safe(self.root, manifest, internal=True)
        payload = read_json(path)
        if payload.get('schema_version') != 1 or not payload.get('artifacts'):
            raise Refusal('Invalid export manifest')
        for name, sha in payload['artifacts'].items():
            item = safe(path.parent / 'artifacts', name)
            if file_hash(item) != sha:
                raise Refusal('Export artifact changed: ' + name)
        for name, sha in payload.get('software', {}).items():
            if file_hash(safe(path.parent / 'software', name)) != sha:
                raise Refusal('Export runtime changed: ' + name)
        if file_hash(path.parent / 'control.json') != payload['state_sha256']:
            raise Refusal('Export control record changed')
        exported_state = read_json(path.parent / 'control.json')
        for source in exported_state.get('task_clock', {}).get('sources', []):
            if payload['artifacts'].get(source['path']) != source['sha256']:
                raise Refusal('Task clock source missing or mismatched in export manifest: ' + source['path'])
        self.task_clock_evidence(exported_state, path.parent / 'artifacts')
        archive = path.parent.parent / (path.parent.name + '.zip')
        result = {'status': 'verified', 'manifest': manifest}
        if archive.exists():
            safe(self.root, str(archive.relative_to(self.root)), internal=True)
            with zipfile.ZipFile(archive) as zipped:
                names = zipped.namelist()
                files = {str(item.relative_to(path.parent)) for item in path.parent.rglob('*') if item.is_file()}
                if len(names) != len(set(names)) or set(names) != files:
                    raise Refusal('Export ZIP has missing, duplicate or unexpected files')
                for name in names:
                    value = hashlib.sha256()
                    with zipped.open(name) as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b''): value.update(block)
                    if value.hexdigest() != file_hash(path.parent / name):
                        raise Refusal('Export ZIP bytes differ: ' + name)
            result['archive'] = {'path': str(archive.relative_to(self.root)), 'files': len(names), 'crc_and_hashes': 'verified'}
        return result

    def deliver(self, decision, op):
        identifier(op)
        state = self.load()
        request = state.get('pending_round') or next((item['request'] for item in state['rounds']
                   if item['request']['request_sha256'] == decision.get('request_sha256')), None)
        if request is None:
            raise Refusal('Prepare and actually judge the final round before delivery')
        self.apply_round(request, decision, 'close-' + digest(op)[:24])
        result = self.finalize(op)
        return {**result, 'verification': self.verify_export(result['manifest'])}


def action_outputs(action):
    keys = {'compile_tex': ('pdf',), 'render_statistics': ('table', 'figure'), 'copy_artifact': ('target',),
            'validate_packet': (), 'export_image': ('target',), 'prepare_tex': ('target',)}
    return [action[k] for k in keys[action['type']]]
