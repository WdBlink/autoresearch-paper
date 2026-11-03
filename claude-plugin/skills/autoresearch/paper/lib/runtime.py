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
}
IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$')


class Refusal(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Refusal('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(Refusal('Non-finite JSON: ' + x)))


def safe(root, value, *, output=False, internal=False):
    if not isinstance(value, str) or not value or Path(value).is_absolute() or '..' in Path(value).parts:
        raise Refusal('Expected a run-relative path: ' + str(value))
    if not internal and Path(value).parts[0] in {'.paper', 'delivery', '.git'}:
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


def check_brief(brief):
    if not isinstance(brief, dict):
        raise Refusal('Brief must be an object')
    for field in ('question', 'venue', 'direction', 'paper_type', 'resources'):
        if not brief.get(field):
            raise Refusal('Brief missing ' + field)
    if 'software_fixture' in brief and type(brief['software_fixture']) is not bool:
        raise Refusal('software_fixture must be a boolean fixed in the Brief')
    items = brief.get('deliverable_plan')
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
        if value.get('schema_version') != 1:
            raise Refusal('Unknown run format; read-only migration required')
        if digest(value['brief']) != value['brief_sha256']:
            raise Refusal('Approved Brief changed')
        if value.get('implementation_sha256') != self.implementation():
            raise Refusal('Execution code or stage knowledge changed; pin the old implementation or migrate explicitly')
        return value

    def implementation(self):
        paths = [*sorted((self.package / 'lib').glob('*.py')), *sorted((self.package / 'references').rglob('*.md')), *sorted((self.package / 'vendor').rglob('scripts/*.py'))]
        return digest({str(p.relative_to(self.package)): file_hash(p) for p in paths})

    def save(self, state):
        atomic(self.path, state)

    def init(self, brief):
        check_brief(brief)
        with self.lock():
            if self.path.exists():
                raise Refusal('Run already exists; do not reset its history')
            state = {'schema_version': 1, 'created_at': now(), 'brief': brief,
                     'brief_sha256': digest(brief), 'implementation_sha256': self.implementation(), 'approval': None, 'receipts': [],
                     'history': [], 'operations': {}, 'attempts': {}, 'bindings': {},
                     'frozen_plan': None, 'delivery': None, 'rounds': [], 'stale_count': 0, 'material_reads': [], 'additional_orders': []}
            self.save(state)
            return {'status': 'needs_brief_approval', 'brief_sha256': state['brief_sha256'], 'brief': brief}

    def approve(self, brief_sha256, actor):
        with self.lock():
            state = self.load()
            if brief_sha256 != state['brief_sha256'] or not actor.strip():
                raise Refusal('Approval must name the exact displayed Brief and human actor')
            if state['approval'] and state['approval']['actor'] != actor:
                raise Refusal('Approval already recorded by a different actor')
            if not state['approval']:
                state['approval'] = {'actor': actor, 'brief_sha256': brief_sha256, 'at': now(),
                                     'basis': 'host-relayed human approval' if not state['brief'].get('software_fixture') else 'software fixture'}
                self.save(state)
            return {'status': 'approved', 'approval': state['approval']}

    def ready(self, state):
        if not state['approval']:
            raise Refusal('Exact Brief approval is required before research stages')
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

    def context(self):
        with self.lock():
            state = self.load()
            stage = STAGES[len(state['receipts'])] if len(state['receipts']) < len(STAGES) else 'delivery'
            knowledge = self.package / 'references/knowledge' / (stage + '.md')
            if not knowledge.is_file():
                raise Refusal('Missing stage knowledge: ' + str(knowledge))
            name = 'autoresearch.md' if stage == 'experiment' else 'plan.md' if stage in {'intake', 'venue', 'plan'} else 'reason.md'
            protocol = self.package / 'upstream' / name
            if not protocol.is_file():
                protocol = self.package.parent / '.claude/commands' / ('autoresearch.md' if name == 'autoresearch.md' else 'autoresearch/' + name)
            if not protocol.is_file():
                raise Refusal('Upstream stage protocol missing from installation')
            return {'stage': stage, 'brief': state['brief'], 'approval': state['approval'],
                    'inputs': [{k: r[k] for k in ('stage', 'packet', 'hashes')} for r in state['receipts']],
                    'stale': self.stale(state), 'attempts': state['attempts'],
                    'knowledge': knowledge.read_text(), 'knowledge_sha256': file_hash(knowledge),
                    'upstream_protocol': protocol.read_text(),
                    'action_contracts': ACTIONS,
                    'requirements': state['brief']['deliverable_plan'],
                    'bindings': state['bindings'],
                    'work_orders': [*[o for r in state['receipts'] if r['stage'] == 'plan' for o in r['packet']['work_orders']], *state['additional_orders']], 'contract': (self.package / 'references/runtime-contract.md').read_text()}

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
            self.ready(state)
            if len(state['receipts']) == len(STAGES) or packet.get('stage') != STAGES[len(state['receipts'])]:
                raise Refusal('Out-of-order stage')
            hashes = self.validate(state, packet)
            if packet['stage'] == 'plan':
                state['frozen_plan'] = digest(packet)
            state['receipts'].append({'stage': packet['stage'], 'packet': packet,
                                      'hashes': hashes, 'at': now(), 'operation': op})
            return self.record(state, op, request, {'status': 'recorded', 'stage': packet['stage'], 'hashes': hashes})

    def rewind(self, stage, reason, op):
        with self.lock():
            state = self.load()
            request = {'command': 'rewind', 'stage': stage, 'reason': reason}
            previous = self.operation(state, op, request)
            if previous is not None:
                return previous
            if stage not in STAGES or not reason.strip():
                raise Refusal('Rewind requires a known stage and reason')
            cut = STAGES.index(stage)
            removed = state['receipts'][cut:]
            if not removed:
                raise Refusal('Stage has no recorded receipt')
            state['receipts'] = state['receipts'][:cut]
            state['bindings'] = {}
            state['delivery'] = None
            state['history'].append({'event': 'invalidated', 'reason': reason, 'receipts': removed,
                                     'at': now()})
            return self.record(state, op, request, {'status': 'rewound', 'stage': stage})

    def prepare_round(self, evidence):
        with self.lock():
            state = self.load()
            self.ready(state)
            hashes = self._hashes({'artifacts': evidence})
            request = {'state_sha256': digest(state), 'brief_sha256': state['brief_sha256'],
                       'evidence': hashes, 'stale_count': state['stale_count'],
                       'rules_sha256': self.rules_hash()}
            return {**request, 'request_sha256': digest(request)}

    def rules_hash(self):
        paths = [Path(__file__), *sorted((self.package / 'references/knowledge').glob('*.md'))]
        return digest({str(p.relative_to(self.package)): file_hash(p) for p in paths})

    def apply_round(self, request, decision, op):
        with self.lock():
            state = self.load()
            arguments = {'command': 'round', 'request': request, 'decision': decision}
            previous = self.operation(state, op, arguments)
            if previous is not None:
                return previous
            self.ready(state)
            core = {k: v for k, v in request.items() if k != 'request_sha256'}
            if request.get('request_sha256') != digest(core) or decision.get('request_sha256') != digest(core):
                raise Refusal('Round request digest mismatch')
            if request.get('state_sha256') != digest(state) or request.get('rules_sha256') != self.rules_hash():
                raise Refusal('Round state or knowledge changed; prepare and judge again')
            if not request.get('evidence') or any(file_hash(safe(self.root, name)) != sha for name, sha in request['evidence'].items()):
                raise Refusal('Round evidence changed; prepare and judge again')
            kind = decision.get('progress')
            if kind not in {'verified_progress', 'no_progress', 'regression'} or not decision.get('reason'):
                raise Refusal('Round needs a supported progress kind and reason')
            if decision.get('status') not in {'active', 'needs_input', 'stopped'}:
                raise Refusal('Round cannot grant completion; use the deterministic finalizer')
            if decision['status'] != 'active' and not decision.get('blockers'):
                raise Refusal('A waiting or stopped round must name its blockers or stop reason')
            if state['rounds'] and kind == 'verified_progress' and request['evidence'] == state['rounds'][-1]['request']['evidence']:
                raise Refusal('Unchanged evidence is not new progress')
            direction = decision.get('direction')
            if state['stale_count'] >= 2 and decision['status'] == 'active' and not direction:
                raise Refusal('After two stale rounds, active continuation needs a structural pivot')
            if direction:
                if not direction.get('id') or not direction.get('change') or not direction.get('reason'):
                    raise Refusal('Pivot must state the structural change and rationale')
                if any(r['decision'].get('direction', {}).get('id') == direction['id'] for r in state['rounds'] if r['decision'].get('direction')):
                    raise Refusal('Direction already tried')
            finding = decision.get('finding')
            if finding:
                if kind == 'no_progress' or not finding.get('claim') or not finding.get('limitations') or not finding.get('validation'):
                    raise Refusal('Finding requires evidence interpretation and limitations')
                normalized = ' '.join(finding['claim'].casefold().split())
                for row in state['rounds']:
                    old = row['decision'].get('finding')
                    if old and ' '.join(old['claim'].casefold().split()) == normalized:
                        raise Refusal('Duplicate finding cannot inflate progress')
            state['stale_count'] = 0 if kind == 'verified_progress' else state['stale_count'] + 1
            state['rounds'].append({'request': request, 'decision': decision, 'at': now(),
                                    'validation': 'structure_and_binding_only'})
            return self.record(state, op, arguments, {'status': 'round_recorded', 'round': len(state['rounds']),
                                                      'stale_count': state['stale_count']})

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
            if any(a['work_id'] == work_id and a['status'] == 'completed' for a in state['attempts'].values()):
                raise Refusal('WorkOrder already completed; create a new versioned order for new effects')
            attempt = {'work_id': work_id, 'order_sha256': digest(order), 'status': 'running',
                       'started_at': now(), 'actions': [], 'brief_sha256': state['brief_sha256']}
            state['attempts'][op] = attempt
            self.save(state)
            for action in order['actions']:
                attempt['pending_action'] = action
                inputs = {'compile_tex': ('source',), 'copy_artifact': ('source',), 'render_statistics': ('input',), 'validate_packet': ('packet',)}[action['type']]
                attempt['pending_input_hashes'] = {action[k]: file_hash(safe(self.root, action[k])) for k in inputs if safe(self.root, action[k], output=True).is_file()}
                self.save(state)
                try:
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

    def check_reviews(self, state, packet):
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
            if len(state['receipts']) != len(STAGES):
                raise Refusal('All stages, including independent itemized review, must be recorded')
            completed = {a['work_id'] for a in state['attempts'].values() if a['status'] == 'completed'}
            for attempt in state['attempts'].values():
                if attempt['status'] == 'failed' and attempt['work_id'] not in completed and not any(o.get('supersedes') == attempt['work_id'] and o['id'] in completed for o in state['additional_orders']):
                    raise Refusal('Failed work needs a completed retry or explicitly superseding work before delivery')
            for receipt in state['receipts']:
                self.validate(state, receipt['packet'])
            write = next(r['packet'] for r in state['receipts'] if r['stage'] == 'write')
            pdf = safe(self.root, write['manuscript_pdf'])
            if not pdf.read_bytes().startswith(b'%PDF-'):
                raise Refusal('Final manuscript is not a PDF')
            assets = {name: sha for r in state['receipts'] for name, sha in r['hashes'].items()}
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
                    payload = {'schema_version': 1, 'brief_sha256': state['brief_sha256'],
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
        return {'status': 'verified', 'manifest': manifest}


def action_outputs(action):
    keys = {'compile_tex': ('pdf',), 'render_statistics': ('table', 'figure'), 'copy_artifact': ('target',), 'validate_packet': ()}
    return [action[k] for k in keys[action['type']]]
