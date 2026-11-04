"""Local vector-response evidence, not a scientific execution or budget controller.

The finite, nested design has three independent instances per phase and two
states per instance. Repeats are not independent cases. No pooled means or CIs
are supported. The caller supplies controller admission before every start.
"""
from contextlib import contextmanager
from collections import Counter, defaultdict
from itertools import combinations
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re

PROTOCOL = 'local_response_identification'
ALGORITHM = 'central-difference-baseline-conditioned-v1'
SEMANTICS = ('correct', 'incorrect', 'irrelevant')
LENGTHS = (80, 160, 240)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', value), 'invalid identifier')
    return value


def number(value):
    require(type(value) in (float, int) and math.isfinite(value), 'nonfinite or nonnumeric coordinate')
    return value


def digest(value):
    require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value), 'invalid sha256')
    return value


def safe(root, name):
    require(isinstance(name, str) and name and not Path(name).is_absolute() and '..' not in Path(name).parts, 'invalid artifact path')
    path = Path(root).resolve() / name
    require(path.resolve().is_relative_to(Path(root).resolve()), 'artifact escapes root')
    return path


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(canonical(value) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())


def vector(value, size):
    require(isinstance(value, list) and len(value) == size, 'vector dimension mismatch')
    return [number(x) for x in value]


def policy(value):
    vector(value, 12)
    require(all(0 <= x <= 1 for x in value) and abs(math.fsum(value) - 1) <= 1e-6, 'invalid probability simplex; no clipping or normalization')
    return value


def tv(left, right):
    policy(left); policy(right)
    return .5 * math.fsum(abs(a-b) for a, b in zip(left, right))


def finite_difference(plus, minus, half_step):
    require(number(half_step) > 0 and len(plus) == len(minus), 'invalid central difference endpoints')
    return [(number(a)-number(b))/(2*half_step) for a, b in zip(plus, minus)]


def average(values):
    require(values and len({len(v) for v in values}) == 1, 'missing or inconsistent response vectors')
    return [math.fsum(v[i] for v in values)/len(values) for i in range(len(values[0]))]


def model_binding(binding, resolved=False):
    require(isinstance(binding, dict) and binding.get('status') in {'draft', 'resolved'}, 'invalid model binding')
    if not resolved and binding['status'] == 'draft':
        return
    require(binding['status'] == 'resolved', 'formal recording requires a resolved model binding')
    for key in ('provider', 'model', 'version'):
        value = binding.get(key)
        require(isinstance(value, str) and value.strip() and value.lower() not in {'unknown', 'pending', 'tbd', 'placeholder'} and '<' not in value,
                'unresolved model identity: ' + key)
    require(binding.get('fresh_session') is True, 'fresh sessions are required')
    require(binding.get('response_representation') == 'probabilities', 'only explicit probability responses are implemented')
    for key in ('prompt_sha256', 'response_schema_sha256'):
        digest(binding.get(key))
    require(isinstance(binding.get('settings'), dict), 'freeze decoding settings, including explicitly unknown controls')


def source_artifacts(design, root, require_resolved=False):
    """Verify only declared protocol sources, never recurse through arbitrary metadata."""
    formal = require_resolved or design.get('model_binding', {}).get('status') == 'resolved'
    require(not require_resolved or design.get('formal_collection_blocked') is not True, 'formal collection is explicitly blocked')
    if formal and not design.get('software_fixture', False):
        require(isinstance(design.get('source_snapshot'), dict), 'resolved scientific design needs source_snapshot')
        require(all(isinstance(op.get('reference_path'), dict) for op in design.get('operating_points', [])), 'resolved scientific operating points need reference_path')
    require(root is not None or not require_resolved, 'resolved source verification requires a root')
    verified = {}
    def source(reference):
        require(isinstance(reference, dict) and isinstance(reference.get('path'), str), 'invalid declared source reference')
        name=reference['path'];digest(reference.get('sha256'))
        require(not Path(name).is_absolute() and '..' not in Path(name).parts, 'invalid source artifact path')
        if root is None: return None
        path=safe(root,name)
        require(path.is_file(), 'declared source artifact is missing: '+name)
        require(sha(path.read_bytes())==reference['sha256'], 'declared source artifact hash mismatch: '+name)
        require(name not in verified or verified[name]==reference['sha256'], 'conflicting source hashes')
        verified[name]=reference['sha256']
        return path
    snapshot=design.get('source_snapshot')
    if snapshot is not None:
        path=source(snapshot)
        require(snapshot['sha256']==design.get('source_snapshot_sha256'), 'source snapshot binding mismatch')
        if path is not None:
            document=read(path);require(isinstance(document,dict), 'source snapshot must be an object')
            files=document.get('files')
            if isinstance(files,dict): files=[{'path':name,'sha256':value} for name,value in files.items()]
            require(isinstance(files,list) and files, 'source snapshot needs explicit dependency files')
            for reference in files: source(reference)
            if document.get('exposure_audit') is not None: source(document['exposure_audit'])
    for op in design.get('operating_points', []):
        path=source(op.get('public_state'))
        if path is not None:
            public=read(path)
            require(isinstance(public,dict) and public.get('instance_id')==op.get('instance_id'), 'public state instance identity mismatch')
            evidence=public.get('evidence')
            if evidence is not None:
                require(isinstance(evidence,list) and all(isinstance(item,dict) and isinstance(item.get('id'),str) for item in evidence), 'invalid public evidence records')
                evidence_ids=[item['id'] for item in evidence]
            else:
                require(design.get('software_fixture') is True, 'scientific public state needs actual evidence records')
                evidence_ids=public.get('evidence_ids')
            require(isinstance(evidence_ids,list) and all(isinstance(item,str) for item in evidence_ids) and len(set(evidence_ids))==len(evidence_ids)
                    and set(evidence_ids)==set(op.get('evidence_ids', [])), 'public state evidence identity mismatch')
            if 'action_space' in public:
                actions=public['action_space']
                require(isinstance(actions,list) and all(isinstance(item,str) for item in actions) and len(actions)==len(set(actions))
                        and set(actions)==set(design['coordinates']['action_ids']), 'public action space identity mismatch')
        if op.get('reference_path') is not None: source(op['reference_path'])
    for template in design.get('templates', []):
        if 'hypothesis_sha256' in template:
            digest(template['hypothesis_sha256'])
            require(isinstance(template.get('hypothesis'),str) and sha(template['hypothesis'].encode('utf-8'))==template['hypothesis_sha256'], 'fixed hypothesis byte hash mismatch')
    if design.get('execution_schedule') is not None: source(design['execution_schedule'])
    return verified


def validate_design(design, root=None, require_resolved=False):
    require(isinstance(design, dict) and design.get('protocol') == PROTOCOL and design.get('schema_version') == 1, 'unsupported local response design')
    identifier(design.get('experiment_id')); identifier(design.get('claim_id'))
    require(design.get('statistical_unit') == 'independent_instance_with_nested_states_probes_repeats', 'nested instance/state identity is required')
    require(type(design.get('software_fixture', False)) is bool, 'invalid software fixture marker')
    model_binding(design.get('model_binding'), require_resolved)
    digest(design.get('source_snapshot_sha256'))
    require(not require_resolved or design.get('formal_collection_blocked') is not True,'formal collection is explicitly blocked')
    coordinates = design.get('coordinates', {})
    actions = coordinates.get('action_ids')
    require(isinstance(actions, list) and len(actions) == 12 and len(set(actions)) == 12, 'exactly 12 distinct action IDs required')
    for action in actions: identifier(action)
    require('confidence' not in actions, 'confidence is a reserved output coordinate')
    require(coordinates.get('q_step') == .02 and coordinates.get('confidence_center') == .5 and coordinates.get('confidence_step') == .1,
            'this protocol freezes q/confidence steps and center')
    require(design.get('thresholds') == {'same_input_tv': .1, 'prediction_policy_tv': .1, 'prediction_confidence_abs': .1, 'min_valid_repeats': 2}, 'unsupported thresholds')
    require(design.get('repeat_ids') == [0, 1, 2], 'exactly three registered repeats required')
    require(design.get('none_memory_policy') == 'policy_only_diagnostic', 'freeze none-memory output semantics')
    instances, ops, templates, probes = {}, {}, {}, {}
    for item in design.get('instances', []):
        key = identifier(item.get('id')); identifier(item.get('family'))
        require(key not in instances and item.get('phase') in {'development', 'prospective'}, 'duplicate instance or invalid phase')
        instances[key] = item
    families = {v['family'] for v in instances.values()}
    require(len(instances) == 6 and len(families) == 3 and Counter((v['phase'], v['family']) for v in instances.values()) == Counter({(p, f): 1 for p in ('development', 'prospective') for f in families}), 'need three distinct instances per phase, one per family')
    for item in design.get('operating_points', []):
        key = identifier(item.get('id'))
        require(key not in ops and item.get('instance_id') in instances and type(item.get('reference_step')) is int and item['reference_step'] in (0,4), 'invalid nested operating point')
        source = item.get('public_state', {})
        digest(source.get('sha256'))
        require(isinstance(source.get('path'), str), 'public state source required')
        if root is not None:
            require(sha(safe(root, source['path']).read_bytes()) == source['sha256'], 'public state source changed')
        require(isinstance(item.get('evidence_ids'), list) and all(isinstance(x,str) for x in item['evidence_ids']) and len(set(item['evidence_ids'])) == len(item['evidence_ids']), 'invalid public evidence IDs')
        ops[key] = item
    require(len(ops) == 12 and Counter((v['instance_id'], v['reference_step']) for v in ops.values()) == Counter({(i,s):1 for i in instances for s in (0,4)}), 'each independent instance needs two nested states')
    for op in ops.values():
        instance = instances[op['instance_id']]
        if instance['phase'] == 'prospective':
            source = ops.get(op.get('development_op_id'))
            require(source is not None and instances[source['instance_id']]['phase'] == 'development' and instances[source['instance_id']]['family'] == instance['family'] and source['reference_step'] == op['reference_step'], 'invalid frozen development transfer map')
        else:
            require('development_op_id' not in op, 'development point cannot select prospective sources')
    for item in design.get('templates', []):
        key = identifier(item.get('id'))
        require(key not in templates and item.get('operating_point_id') in ops and item.get('semantic') in SEMANTICS and item.get('codepoints') in LENGTHS, 'invalid fixed template identity')
        require(isinstance(item.get('hypothesis'),str) and len(item['hypothesis']) == item['codepoints'], 'template codepoint length mismatch')
        require(isinstance(item.get('evidence_ids'),list) and set(item['evidence_ids']) <= set(ops[item['operating_point_id']]['evidence_ids']), 'template references unknown evidence')
        templates[key] = item
    for op in ops.values():
        group = [t for t in templates.values() if t['operating_point_id'] == op['id']]
        require(Counter((t['semantic'], t['codepoints']) for t in group) == Counter({(m,n):1 for m in SEMANTICS for n in LENGTHS}), 'each operating point needs nine frozen templates')
    for item in design.get('probes', []):
        key = identifier(item.get('id'))
        require(key not in probes and item.get('operating_point_id') in ops and item.get('branch') in {'H','E'} and item.get('role') in {'center','q_axis','confidence_axis','joint'}, 'invalid probe identity')
        op = ops[item['operating_point_id']]
        q = policy(item.get('q')); confidence = item.get('confidence'); template = templates.get(item.get('template_id'))
        if item['branch'] == 'E' or item.get('template_id') is None:
            require(item.get('template_id') is None and confidence is None, 'E/none confidence must be null')
        else:
            require(template is not None and template['operating_point_id'] == op['id'] and 0 <= number(confidence) <= 1, 'invalid probe template/confidence')
        center = [1/12]*12
        if item['role'] == 'center':
            expected = center
            require(confidence == (.5 if template else None), 'invalid center confidence')
        elif item['role'] == 'q_axis':
            axis, sign = item.get('axis'), item.get('sign')
            require(type(axis) is int and 0 <= axis < 11 and type(sign) is int and sign in (-1,1), 'invalid q axis')
            require(item['branch'] == 'E' or template and (template['semantic'],template['codepoints']) == ('correct',160), 'q Jacobian is sampled only at the reference template')
            require(confidence == (.5 if template else None), 'q axis changes confidence')
            expected = center.copy(); expected[axis] += sign*.02; expected[11] -= sign*.02
        elif item['role'] == 'confidence_axis':
            require(item['branch'] == 'H' and template and type(item.get('sign')) is int and item['sign'] in (-1,1), 'invalid confidence axis')
            require(abs(confidence-(.5+item['sign']*.1)) <= 1e-12, 'wrong confidence half step')
            expected = center
        else:
            require(any(abs(a-b)>1e-12 for a,b in zip(q,center)) and all(abs(q[i]-center[i]) <= .02+1e-12 for i in range(11)), 'joint q lies outside the declared local coordinates')
            require(item['branch'] == 'E' or template and 0 < abs(confidence-.5) <= .1+1e-12, 'joint H needs a nonempty perturbed confidence template')
            expected = q
        require(all(abs(a-b)<=1e-12 for a,b in zip(q,expected)), 'probe does not match its declared central-difference coordinate')
        probes[key] = item
    for op_id, op in ops.items():
        phase = instances[op['instance_id']]['phase']
        group = [p for p in probes.values() if p['operating_point_id'] == op_id]
        expected_counts = {('H','center'):10,('E','center'):1,('H','joint'):4 if phase=='development' else 14,('E','joint'):4 if phase=='development' else 14}
        if phase == 'development': expected_counts.update({('H','q_axis'):22,('E','q_axis'):22,('H','confidence_axis'):18})
        require(Counter((p['branch'],p['role']) for p in group) == Counter(expected_counts), 'nonrectangular probe coverage mismatch')
        local_templates = {t['id'] for t in templates.values() if t['operating_point_id']==op_id}
        require({p.get('template_id') for p in group if p['branch']=='H' and p['role']=='center'} == local_templates | {None}, 'center template coverage mismatch')
        for branch in ('H','E'):
            if phase == 'development':
                require({(p.get('axis'),p.get('sign')) for p in group if p['branch']==branch and p['role']=='q_axis'} == {(j,s) for j in range(11) for s in (-1,1)}, 'missing q direction')
        if phase == 'development':
            require({(p['template_id'],p['sign']) for p in group if p['role']=='confidence_axis'} == {(t,s) for t in local_templates for s in (-1,1)}, 'missing confidence direction')
        h_joint = {p['id']:p for p in group if p['branch']=='H' and p['role']=='joint'}
        wanted = {('correct',160):4} if phase=='development' else {('correct',160):8, **{(m,n):1 for m in ('incorrect','irrelevant') for n in LENGTHS}}
        require(Counter((templates[p['template_id']]['semantic'],templates[p['template_id']]['codepoints']) for p in h_joint.values()) == Counter(wanted), 'joint template coverage mismatch')
        if phase=='prospective':
            reference=[p for p in h_joint.values() if (templates[p['template_id']]['semantic'],templates[p['template_id']]['codepoints'])==('correct',160)]
            directions={tuple(round(q-1/12,12) for q in p['q'][:11]) for p in reference}
            require(len(directions)==8 and all(tuple(-x for x in direction) in directions for direction in directions), 'prospective reference needs four paired q directions')
            require(sum(p['confidence']>.5 for p in reference)==4, 'prospective confidence signs must be balanced')
        e_joint = [p for p in group if p['branch']=='E' and p['role']=='joint']
        require({p.get('paired_h_probe_id') for p in e_joint} == set(h_joint), 'E joint slots must correspond to H q inputs')
        for probe in e_joint:
            require(probe['q'] == h_joint[probe['paired_h_probe_id']]['q'], 'paired H/E joint q mismatch')
    slots = {f's{index:04d}-r{repeat}': {'probe_id':probe_id,'repeat_id':repeat} for index,probe_id in enumerate(probes) for repeat in range(3)}
    require(len(slots)==2160, 'expected 2160 explicitly registered nested slots')
    verified_sources=source_artifacts(design,root,require_resolved)
    return {'source_artifacts':verified_sources,'source_verification':'verified' if root is not None else 'unresolved_root','instances':instances,'ops':ops,'templates':templates,'probes':probes,'slots':slots}


def payload(design, index, probe, root):
    op=index['ops'][probe['operating_point_id']]; source=op['public_state']; path=safe(root,source['path'])
    require(sha(path.read_bytes())==source['sha256'], 'public state source changed')
    template=index['templates'].get(probe.get('template_id'))
    return {'branch':probe['branch'],'public_state':read(path),'q':dict(zip(design['coordinates']['action_ids'],probe['q'])),
            'memory':None if probe['branch']=='E' else ([] if template is None else [{'hypothesis':template['hypothesis'],'confidence':probe['confidence'],'evidence_ids':template['evidence_ids']}]),
            'model_binding':design['model_binding']}


def response_vector(design, index, probe, response):
    require(isinstance(response,dict) and set(response)==({'probabilities'} if probe['branch']=='E' else {'probabilities','memory'}), 'response schema mismatch')
    actions=design['coordinates']['action_ids']; probabilities=response['probabilities']
    require(isinstance(probabilities,dict) and set(probabilities)==set(actions), 'response action identities mismatch')
    p=policy([probabilities[a] for a in actions]); template=index['templates'].get(probe.get('template_id'))
    confidence=None
    if probe['branch']=='H':
        memory=response['memory']; require(isinstance(memory,list) and len(memory)<=4,'invalid returned memory')
        for item in memory:
            require(isinstance(item,dict) and set(item)=={'hypothesis','confidence','evidence_ids'} and isinstance(item['hypothesis'],str) and 0 < len(item['hypothesis']) <= 300, 'invalid memory schema')
            require(0<=number(item['confidence'])<=1 and isinstance(item['evidence_ids'],list) and set(item['evidence_ids']) <= set(index['ops'][probe['operating_point_id']]['evidence_ids']), 'invalid memory confidence/evidence')
        if template:
            require(len(memory)==1 and memory[0]['hypothesis']==template['hypothesis'], 'fixed H hypothesis identity changed')
            confidence=memory[0]['confidence']
    return {'policy':p,'confidence':confidence,'memory_created':probe['branch']=='H' and template is None and bool(response['memory'])}


def timestamp(value):
    require(isinstance(value,str),'receipt timestamp required')
    parsed=datetime.fromisoformat(value)
    require(parsed.tzinfo is not None,'receipt timestamp needs a timezone')
    return parsed


def validate_receipt(design,root,receipt,start,start_time,terminal_time,status,response):
    require(isinstance(receipt,dict) and receipt.get('request_id')==start['request_id'] and receipt.get('session_id')==start['session_id'],
            'receipt request/session identity mismatch')
    require(receipt.get('payload_sha256')==start['payload_sha256'],'receipt payload hash mismatch')
    captured=timestamp(receipt.get('captured_at'))
    require(timestamp(start_time)<=captured<=timestamp(terminal_time),'receipt capture chronology mismatch')
    source=receipt.get('source')
    if source=='local_unknown':
        require(status=='unknown','local unknown receipt cannot certify a response')
        return
    require(timestamp(start_time)<=timestamp(receipt.get('started_at'))<=captured,'receipt predates recorded request')
    if status!='unknown':
        require(timestamp(receipt['started_at'])<=timestamp(receipt.get('completed_at'))<=captured,'provider terminal chronology mismatch')
    else:
        require(receipt.get('completed_at') is None,'unknown outcome cannot have a certified terminal time')
    if source=='software_fixture':
        require(design.get('software_fixture') is True and isinstance(receipt.get('mock_source'),str) and receipt['mock_source'],
                'software mock receipt cannot certify scientific responses')
        require(receipt.get('raw_response_sha256')==(sha(canonical(response)) if response is not None else None),'fixture raw response hash mismatch')
        return
    require(source=='provider_receipt' and receipt.get('timestamp_source')=='provider_receipt','scientific responses need provider receipt timestamps')
    binding=design['model_binding']
    for key in ('provider','model','version'):
        require(receipt.get(key)==binding[key],'provider receipt model identity mismatch')
    require(isinstance(receipt.get('provider_request_id'),str) and receipt['provider_request_id'],'provider request identity required')
    require('usage' in receipt and (receipt['usage'] is None or isinstance(receipt['usage'],dict)),'preserve usage or explicit unknown usage')
    artifact=receipt.get('receipt_artifact',{})
    artifact_path=safe(root,artifact.get('path'))
    require(sha(artifact_path.read_bytes())==artifact.get('sha256'),'provider receipt artifact hash mismatch')
    require(read(artifact_path)=={k:v for k,v in receipt.items() if k!='receipt_artifact'},'provider receipt artifact differs from envelope')
    raw=receipt.get('raw_response')
    if status=='completed':
        require(isinstance(raw,dict),'scientific response needs raw response bytes')
    if raw is not None:
        path=safe(root,raw.get('path'))
        require(sha(path.read_bytes())==raw.get('sha256'),'raw response bytes hash mismatch')
        if status=='completed':
            try: parsed=read(path)
            except (ValueError,UnicodeError):
                require(response is None,'invalid raw JSON cannot have a repaired parsed response')
            else: require(parsed==response,'parsed response differs from provider raw bytes')


def summarize_cells(design, index, events, root):
    starts={};terminals={};probe_slots=defaultdict(list)
    for slot,item in index['slots'].items(): probe_slots[item['probe_id']].append(slot)
    for event in events:
        if event['kind']=='started': starts[event['data']['slot_id']]=event
        elif event['kind']=='terminal': terminals[event['data']['slot_id']]=event
    cells={};groups={}
    for probe_id,probe in index['probes'].items():
        slots=probe_slots[probe_id]
        counts=Counter(planned=len(slots),attempted=0,valid=0,invalid=0,failed=0,unknown=0,not_started=0)
        payload_hash=sha(canonical(payload(design,index,probe,root)))
        group=groups.setdefault(payload_hash,{'slot_ids':[],'valid_slot_ids':[],'counts':Counter(),'chronology':[],'valid_records':[]})
        group['slot_ids'].extend(slots)
        values=[];identities=[];memory_created=0
        for slot in slots:
            started=starts.get(slot);terminal=terminals.get(slot)
            state='not_started' if started is None else 'unknown' if terminal is None else terminal['data']['status']
            group['chronology'].append({'slot_id':slot,'start_sequence':started['sequence'] if started else None,
                'start_time':started['recorded_at'] if started else None,'terminal_sequence':terminal['sequence'] if terminal else None,
                'terminal_time':terminal['recorded_at'] if terminal else None,'status':state,
                'valid':terminal['data']['valid'] if terminal else False})
            if started is None: counts['not_started']+=1;continue
            counts['attempted']+=1
            if terminal is None or terminal['data']['status']=='unknown':counts['unknown']+=1;continue
            record=terminal['data']
            if record['status']=='failed':counts['failed']+=1;continue
            if not record['valid']:counts['invalid']+=1;continue
            result=response_vector(design,index,probe,record['response'])
            value=result['policy']+([] if result['confidence'] is None else [result['confidence']])
            values.append(value);identities.append(slot);counts['valid']+=1;memory_created+=int(result['memory_created'])
            group['valid_slot_ids'].append(slot);group['valid_records'].append({'slot_id':slot,'policy':result['policy'],'confidence':result['confidence']})
        group['counts'].update(counts)
        pairwise=[{'left':identities[i],'right':identities[j],'tv':tv(values[i][:12],values[j][:12])} for i,j in combinations(range(len(values)),2)]
        confidence_pairs=[{'left':identities[i],'right':identities[j],'abs_difference':abs(values[i][12]-values[j][12])} for i,j in combinations(range(len(values)),2)] if values and len(values[0])==13 else None
        mean=average(values) if values else None
        cells[probe_id]={'operating_point_id':probe['operating_point_id'],'branch':probe['branch'],'template_id':probe.get('template_id'),'counts':dict(counts),
            'valid_slot_ids':identities,'vectors':values,'mean':mean,'mean_policy':mean[:12] if mean else None,
            'mean_confidence':mean[12] if mean and len(mean)==13 else None,'memory_created_count':memory_created,
            'pairwise_tv':pairwise,'max_same_input_tv':max((p['tv'] for p in pairwise),default=None),
            'pairwise_abs_confidence':confidence_pairs,
            'max_abs_confidence':max((p['abs_difference'] for p in confidence_pairs),default=None) if confidence_pairs is not None else None,
            'estimable':counts['valid']>=2 and counts['unknown']==0 and counts['not_started']==0}
    for group in groups.values():
        rows=group.pop('valid_records')
        pairs=[{'left':a['slot_id'],'right':b['slot_id'],'abs_difference':abs(a['confidence']-b['confidence'])} for a,b in combinations(rows,2) if a['confidence'] is not None and b['confidence'] is not None]
        tv_pairs=[{'left':a['slot_id'],'right':b['slot_id'],'tv':tv(a['policy'],b['policy'])} for a,b in combinations(rows,2)]
        group.update(counts=dict(group['counts']),pairwise_tv=tv_pairs,max_tv=max((p['tv'] for p in tv_pairs),default=None),
            pairwise_abs_confidence=pairs if any(r['confidence'] is not None for r in rows) else None,
            max_abs_confidence=max((p['abs_difference'] for p in pairs),default=None))
        group['chronology'].sort(key=lambda item:(item['start_sequence'] is None,item['start_sequence'] or 0,item['slot_id']))
    return cells,groups


def coefficients(design,index,cells):
    result={}
    for op_id,op in index['ops'].items():
        if index['instances'][op['instance_id']]['phase']!='development': continue
        probes=[p for p in index['probes'].values() if p['operating_point_id']==op_id]
        require(all(cells[p['id']]['estimable'] for p in probes), 'development cells incomplete')
        point={}
        for branch in ('H','E'):
            axes={(p['axis'],p['sign']):p for p in probes if p['branch']==branch and p['role']=='q_axis'}
            columns=[finite_difference(cells[axes[(j,1)]['id']]['mean'],cells[axes[(j,-1)]['id']]['mean'],.02) for j in range(11)]
            point[branch]={'q_columns':columns,'q_half_step':.02,
                           'q_endpoints':[{'axis':j,'plus':axes[(j,1)]['id'],'minus':axes[(j,-1)]['id']} for j in range(11)]}
        confidence={};confidence_endpoints={}
        for template in index['templates'].values():
            if template['operating_point_id']!=op_id: continue
            endpoints={p['sign']:p for p in probes if p['role']=='confidence_axis' and p['template_id']==template['id']}
            confidence_endpoints[template['id']]={'plus':endpoints[1]['id'],'minus':endpoints[-1]['id']}
            confidence[template['id']]=finite_difference(cells[endpoints[1]['id']]['mean'],cells[endpoints[-1]['id']]['mean'],.1)
        point['H'].update(confidence_columns=confidence,confidence_half_step=.1,confidence_endpoints=confidence_endpoints)
        result[op_id]=point
    return {'algorithm':ALGORITHM,'operating_points':result,'transfer_map':{k:v['development_op_id'] for k,v in index['ops'].items() if 'development_op_id' in v}}


def predictions(design,index,cells,frozen):
    result={}
    centers={(p['operating_point_id'],p['branch'],p.get('template_id')):p for p in index['probes'].values() if p['role']=='center'}
    for probe in index['probes'].values():
        op=index['ops'][probe['operating_point_id']]
        if index['instances'][op['instance_id']]['phase']!='prospective' or probe['role']!='joint': continue
        center=centers[(op['id'],probe['branch'],probe.get('template_id'))]
        require(cells[center['id']]['estimable'], 'prospective centers incomplete')
        baseline=cells[center['id']]['mean']; branch=frozen['operating_points'][op['development_op_id']][probe['branch']]
        x=[q-1/12 for q in probe['q'][:11]]
        prediction=[base+math.fsum(column[i]*delta for column,delta in zip(branch['q_columns'],x)) for i,base in enumerate(baseline)]
        if probe['branch']=='H':
            template=index['templates'][probe['template_id']]
            source=next(t for t in index['templates'].values() if t['operating_point_id']==op['development_op_id'] and (t['semantic'],t['codepoints'])==(template['semantic'],template['codepoints']))
            column=branch['confidence_columns'][source['id']]
            prediction=[value+column[i]*(probe['confidence']-.5) for i,value in enumerate(prediction)]
        try:
            policy(prediction[:12])
            if probe['branch']=='H': require(0<=number(prediction[12])<=1,'predicted confidence outside domain')
            valid=True;reason=None
        except ValueError as error:
            valid=False;reason=str(error)
        result[probe['id']]={'operating_point_id':op['id'],'source_development_op_id':op['development_op_id'],'center_probe_id':center['id'],
            'policy':prediction[:12],'confidence':prediction[12] if probe['branch']=='H' else None,'valid':valid,'reason':reason}
    return {'algorithm':ALGORITHM,'points':result}


def validate_events(design,index,events,root,design_sha256):
    digest(design_sha256)
    if events: model_binding(design["model_binding"],resolved=True)
    previous='0'*64; previous_time=None; starts={};start_times={};terminal=set(); request_ids=set();session_ids=set();provider_request_ids=set();freezes={}
    for sequence,event in enumerate(events,1):
        require(isinstance(event,dict) and set(event)=={'sequence','previous_sha256','kind','data','recorded_at','event_sha256'}, 'invalid event shape')
        core={k:v for k,v in event.items() if k!='event_sha256'}
        require(event['sequence']==sequence and event['previous_sha256']==previous and sha(canonical(core))==event['event_sha256'], 'event hash chain changed')
        current_time=timestamp(event['recorded_at'])
        require(previous_time is None or current_time>=previous_time,'event timestamps must be monotone')
        previous_time=current_time
        previous=event['event_sha256'];data=event['data'];kind=event['kind']
        require(isinstance(data,dict),'invalid event data')
        if kind in {'started','terminal'}:
            slot=data.get('slot_id'); require(slot in index['slots'],'unregistered slot')
            expected=index['slots'][slot];probe=index['probes'][expected['probe_id']];op=index['ops'][probe['operating_point_id']]
            require(data.get('identity')=={'design_id':design['experiment_id'],'design_sha256':design_sha256,'probe_id':probe['id'],'repeat_id':expected['repeat_id'],'operating_point_id':op['id'],'independent_instance_id':op['instance_id'],'branch':probe['branch'],'template_id':probe.get('template_id')}, 'raw identity crossover')
            if kind=='started':
                require(slot not in starts and data.get('request_id') not in request_ids and data.get('session_id') not in session_ids,'duplicate slot/request/session; unknown attempts cannot be retried')
                identifier(data.get('request_id'));identifier(data.get('session_id'))
                admission=data.get('controller_admission')
                require(isinstance(admission,dict) and admission.get('admitted') is True and isinstance(admission.get('receipt'),str) and admission['receipt'],'missing controller admission evidence')
                require(data.get('payload')==payload(design,index,probe,root) and data.get('payload_sha256')==sha(canonical(data['payload'])),'request payload changed')
                if index['instances'][op['instance_id']]['phase']=='prospective':
                    require('coefficients' in freezes,'prospective request before coefficients freeze')
                    if probe['role']=='joint': require('predictions' in freezes,'joint request before predictions freeze')
                starts[slot]=data;start_times[slot]=event['recorded_at'];request_ids.add(data['request_id']);session_ids.add(data['session_id'])
            else:
                require(slot in starts and slot not in terminal,'terminal without unique start')
                require(data.get('status') in {'completed','failed','unknown'},'invalid terminal state')
                if data['status']=='completed':
                    try: response_vector(design,index,probe,data.get('response'));valid=True;reason=None
                    except (ValueError,TypeError,KeyError) as error: valid=False;reason=str(error)
                    require(data.get('valid') is valid and data.get('reason')==reason,'terminal response validity changed')
                else:
                    require(data.get('valid') is False and isinstance(data.get('reason'),str) and data['reason'] and data.get('response') is None,'failed/unknown cannot become numeric measurements')
                validate_receipt(design,root,data.get('receipt'),starts[slot],start_times[slot],event['recorded_at'],data['status'],data.get('response'))
                if data['receipt']['source']=='provider_receipt':
                    provider_id=data['receipt']['provider_request_id']
                    require(provider_id not in provider_request_ids,'duplicate provider request identity')
                    provider_request_ids.add(provider_id)
                terminal.add(slot)
        elif kind in {'coefficients','predictions'}:
            require(kind not in freezes,'duplicate freeze')
            cells,_=summarize_cells(design,index,events[:sequence-1],root)
            if kind=='coefficients':
                require(not any(index['instances'][index['ops'][index['probes'][index['slots'][slot]['probe_id']]['operating_point_id']]['instance_id']]['phase']=='prospective' for slot in starts),'coefficients frozen after prospective exposure')
                expected=coefficients(design,index,cells)
            else:
                require('coefficients' in freezes,'predictions need frozen coefficients')
                require(not any(index['instances'][index['ops'][index['probes'][index['slots'][slot]['probe_id']]['operating_point_id']]['instance_id']]['phase']=='prospective' and index['probes'][index['slots'][slot]['probe_id']]['role']=='joint' for slot in starts),'predictions frozen after joint exposure')
                center_ids=[p['id'] for p in index['probes'].values() if p['role']=='center' and index['instances'][index['ops'][p['operating_point_id']]['instance_id']]['phase']=='prospective']
                require(all(cells[p]['estimable'] for p in center_ids),'all prospective centers must finish before prediction freeze')
                expected=predictions(design,index,cells,freezes['coefficients'])
            require(data==expected,'frozen coefficients/predictions differ from permitted raw evidence')
            freezes[kind]=data
        else: raise ValueError('unknown local response event')
    return freezes


class LocalResponseRecorder:
    def __init__(self,root,design_path,directory,admission_check):
        require(callable(admission_check),'controller admission callback is required')
        self.root=Path(root).resolve();self.design_path=design_path;self.design=read(safe(root,design_path))
        self.index=validate_design(self.design,root)
        self.design_sha256=sha(safe(root,design_path).read_bytes());self.directory=safe(root,directory)
        self.admission_check=admission_check;self._cache=[];self._signatures={}
        self.directory.mkdir(parents=True,exist_ok=True)
        reference={'design_path':design_path,'design_sha256':self.design_sha256,'design_id':self.design['experiment_id']}
        with self._lock():
            path=self.directory/'design-reference.json'
            require(not path.is_symlink(),'recorder reference cannot be a symlink')
            if path.exists(): require(read(path)==reference,'recorder design changed')
            else: write_once(path,reference)

    @contextmanager
    def _lock(self):
        require(sha(safe(self.root,self.design_path).read_bytes())==self.design_sha256,'frozen design changed')
        require(not (self.directory/'recorder.lock').is_symlink(),'recorder lock cannot be a symlink')
        with (self.directory/'recorder.lock').open('a') as stream:
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(stream.fileno(),fcntl.LOCK_UN)

    def _load(self,full=False):
        directory=self.directory/'events'
        require(not directory.is_symlink(),'event directory cannot be a symlink')
        directory.mkdir(exist_ok=True)
        files=sorted(directory.glob('*.json'))
        require(not any(p.is_symlink() for p in files),'event files cannot be symlinks')
        signatures={}
        for path in files:
            stat=path.stat();signatures[path.name]=(stat.st_ino,stat.st_size,stat.st_mtime_ns)
        require(all(signatures.get(name)==value for name,value in self._signatures.items()),'previous event file changed; refuse further admission')
        require([p.name for p in files]==[f'{n:06d}.json' for n in range(1,len(files)+1)],'event sequence has a gap')
        require(len(files)>=len(self._cache),'events were removed')
        events=[] if full else self._cache.copy()
        for path in files[len(events):]:
            event=read(path);core={k:v for k,v in event.items() if k!='event_sha256'}
            require(event.get('sequence')==len(events)+1 and event.get('previous_sha256')==(events[-1]['event_sha256'] if events else '0'*64) and event.get('event_sha256')==sha(canonical(core)),'event hash chain changed')
            events.append(event)
        if len(events)>len(self._cache):
            validate_events(self.design,self.index,events,self.root,self.design_sha256)
        self._cache=events;self._signatures=signatures
        return events

    def _append(self,events,kind,data):
        event={'sequence':len(events)+1,'previous_sha256':events[-1]['event_sha256'] if events else '0'*64,'kind':kind,'data':data,'recorded_at':datetime.now(timezone.utc).isoformat()}
        require(not events or timestamp(event['recorded_at'])>=timestamp(events[-1]['recorded_at']),'event timestamps must be monotone')
        event['event_sha256']=sha(canonical(event))
        path=self.directory/'events'/f'{event["sequence"]:06d}.json'
        write_once(path,event)
        stat=path.stat();self._signatures[path.name]=(stat.st_ino,stat.st_size,stat.st_mtime_ns)
        self._cache=[*events,event]
        return event

    def _identity(self,slot):
        require(slot in self.index['slots'],'unregistered slot')
        item=self.index['slots'][slot];probe=self.index['probes'][item['probe_id']];op=self.index['ops'][probe['operating_point_id']]
        return {'design_id':self.design['experiment_id'],'design_sha256':self.design_sha256,'probe_id':probe['id'],'repeat_id':item['repeat_id'],'operating_point_id':op['id'],'independent_instance_id':op['instance_id'],'branch':probe['branch'],'template_id':probe.get('template_id')}

    def start(self,slot_id,request_id,session_id):
        model_binding(self.design['model_binding'],resolved=True)
        source_artifacts(self.design,self.root,require_resolved=True)
        identity=self._identity(slot_id);identifier(request_id);identifier(session_id)
        with self._lock():
            events=self._load();starts=[e['data'] for e in events if e['kind']=='started']
            require(not any(d['slot_id']==slot_id or d['request_id']==request_id or d['session_id']==session_id for d in starts),'duplicate slot/request/session; unknown attempts cannot be retried')
            probe=self.index['probes'][identity['probe_id']];op=self.index['ops'][identity['operating_point_id']]
            kinds={e['kind'] for e in events}
            if self.index['instances'][op['instance_id']]['phase']=='prospective':
                require('coefficients' in kinds,'prospective request before coefficients freeze')
                if probe['role']=='joint': require('predictions' in kinds,'joint request before predictions freeze')
            admission=self.admission_check({'design_id':self.design['experiment_id'],'design_sha256':self.design_sha256,'slot_id':slot_id,'identity':identity})
            require(isinstance(admission,dict) and admission.get('admitted') is True and isinstance(admission.get('receipt'),str) and admission['receipt'],'controller did not admit request')
            request=payload(self.design,self.index,probe,self.root)
            return self._append(events,'started',{'slot_id':slot_id,'identity':identity,'request_id':request_id,'session_id':session_id,'payload':request,'payload_sha256':sha(canonical(request)),'controller_admission':admission})

    def finish(self,slot_id,*,status='completed',response=None,receipt=None,reason=None):
        identity=self._identity(slot_id)
        with self._lock():
            events=self._load()
            require(any(e['kind']=='started' and e['data']['slot_id']==slot_id for e in events) and not any(e['kind']=='terminal' and e['data']['slot_id']==slot_id for e in events),'terminal without unique start')
            require(status in {'completed','failed','unknown'} and isinstance(receipt,dict),'terminal status and receipt required')
            if status=='completed':
                try: response_vector(self.design,self.index,self.index['probes'][identity['probe_id']],response);valid=True;reason=None
                except (ValueError,TypeError,KeyError) as error: valid=False;reason=str(error)
            else:
                require(response is None and isinstance(reason,str) and reason,'failed/unknown require reason, not measurements');valid=False
            start_event=next(e for e in events if e['kind']=='started' and e['data']['slot_id']==slot_id)
            validate_receipt(self.design,self.root,receipt,start_event['data'],start_event['recorded_at'],datetime.now(timezone.utc).isoformat(),status,response)
            if receipt['source']=='provider_receipt':
                require(not any(e['kind']=='terminal' and e['data']['receipt'].get('source')=='provider_receipt' and e['data']['receipt'].get('provider_request_id')==receipt['provider_request_id'] for e in events),'duplicate provider request identity')
            return self._append(events,'terminal',{'slot_id':slot_id,'identity':identity,'status':status,'response':response,'valid':valid,'reason':reason,'receipt':receipt})

    def _freeze(self,kind):
        with self._lock():
            events=self._load(full=True);freezes=validate_events(self.design,self.index,events,self.root,self.design_sha256)
            require(kind not in freezes,'duplicate freeze')
            cells,_=summarize_cells(self.design,self.index,events,self.root)
            if kind=='coefficients': data=coefficients(self.design,self.index,cells)
            else:
                require('coefficients' in freezes,'predictions need frozen coefficients')
                require(all(cell['estimable'] for key,cell in cells.items() if self.index['probes'][key]['role']=='center' and self.index['instances'][self.index['ops'][cell['operating_point_id']]['instance_id']]['phase']=='prospective'),'all prospective centers must finish before prediction freeze')
                data=predictions(self.design,self.index,cells,freezes['coefficients'])
            candidate={'sequence':len(events)+1,'previous_sha256':events[-1]['event_sha256'] if events else '0'*64,'kind':kind,'data':data,'recorded_at':datetime.now(timezone.utc).isoformat()}
            candidate['event_sha256']=sha(canonical(candidate));validate_events(self.design,self.index,[*events,candidate],self.root,self.design_sha256)
            return self._append(events,kind,data)

    def freeze_coefficients(self): return self._freeze('coefficients')
    def freeze_predictions(self): return self._freeze('predictions')

    def results(self):
        with self._lock():
            events=self._load(full=True)
            validate_events(self.design,self.index,events,self.root,self.design_sha256)
            files=[self.directory/'design-reference.json',*sorted((self.directory/'events').glob('*.json'))]
            external=set()
            for event in events:
                if event['kind']=='terminal':
                    receipt=event['data']['receipt']
                    for key in ('raw_response','receipt_artifact'):
                        if receipt.get(key): external.add(receipt[key]['path'])
            return {'schema_version':1,'protocol':PROTOCOL,'design_id':self.design['experiment_id'],
                    'design':self.design_path,'design_sha256':self.design_sha256,
                    'event_head_sha256':events[-1]['event_sha256'] if events else None,
                    'events':[{'path':str(path.relative_to(self.root)),'sha256':sha(path.read_bytes())} for path in files],
                    'receipt_artifacts':[{'path':name,'sha256':sha(safe(self.root,name).read_bytes())} for name in sorted(external)],
                    'software_fixture':self.design.get('software_fixture',False)}

    def analyze(self):
        with self._lock():
            events=self._load(full=True)
            return analyze(self.design,events,self.root,design_sha256=self.design_sha256)


def analyze(design,events,root,design_sha256=None):
    index=validate_design(design,root);freezes=validate_events(design,index,events,root,design_sha256)
    cells,same_input=summarize_cells(design,index,events,root);points={}
    for key,prediction in freezes.get('predictions',{}).get('points',{}).items():
        cell=cells[key];p_error=None;c_error=None
        if not cell['estimable']: verdict='incomplete'
        elif not prediction['valid']: verdict='prediction_failed'
        else:
            p_error=tv(prediction['policy'],cell['mean'][:12])
            c_error=abs(prediction['confidence']-cell['mean'][12]) if prediction['confidence'] is not None else None
            verdict='within_engineering_tolerance' if p_error<=.1 and (c_error is None or c_error<=.1) else 'prediction_failed'
        points[key]={**prediction,'counts':cell['counts'],'observed_mean':cell['mean'],'policy_tv':p_error,'confidence_abs_error':c_error,'verdict':verdict}
    counts={key:sum(c['counts'][key] for c in cells.values()) for key in ('planned','attempted','valid','invalid','failed','unknown','not_started')}
    complete=all(c['estimable'] for c in cells.values()) and 'predictions' in freezes
    noise_failed=any(g['max_tv'] is not None and g['max_tv']>.1 for g in same_input.values())
    failed=noise_failed or any(p['verdict']=='prediction_failed' for p in points.values())
    return {'schema_version':1,'protocol':PROTOCOL,'algorithm':ALGORITHM,'design_id':design['experiment_id'],'claim_id':design['claim_id'],
        'design_sha256':design_sha256,'event_head_sha256':events[-1]['event_sha256'] if events else None,'software_fixture':design.get('software_fixture',False),
        'instances':list(index['instances'].values()),'operating_points':list(index['ops'].values()),'counts':counts,'cells':cells,'same_input':same_input,
        'coefficients':freezes.get('coefficients'),'predictions':freezes.get('predictions'),'prospective_points':points,
        'acquisition_status':'incomplete' if counts['unknown'] or counts['not_started'] else 'complete',
        'response_validity':'all_valid' if counts['valid']==counts['planned'] else 'conditional_on_valid_responses',
        'assessment':'incomplete' if not complete else 'local_prediction_failed' if failed else 'within_engineering_tolerance',
        'global_stability':False,'full_text_identification':False,'limitations':['conditional_on_valid_responses','shared_template_q_slopes','finite_difference_not_certified_derivative','no_IID_or_global_CI','closure_drift_and_invariant_domain_unproved']}
