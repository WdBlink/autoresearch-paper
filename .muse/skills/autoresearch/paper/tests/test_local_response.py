"""Known-linear SOFTWARE fixtures. Zero model calls, no research evidence."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib import local_response as local


def put(root,name,value):
    path=Path(root)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(local.canonical(value));return name


def make_design(root):
    design=dict(schema_version=1,protocol=local.PROTOCOL,experiment_id='local-fixture',claim_id='fixture-only',
        statistical_unit='independent_instance_with_nested_states_probes_repeats',software_fixture=True,source_snapshot_sha256='1'*64,
        model_binding=dict(status='resolved',provider='software-fixture',model='known-linear-fixture',version='1',fresh_session=True,
                           response_representation='probabilities',prompt_sha256='2'*64,response_schema_sha256='3'*64,settings={'temperature':None,'seed':None}),
        coordinates=dict(action_ids=['a'+str(i) for i in range(12)],q_step=.02,confidence_center=.5,confidence_step=.1),
        thresholds=dict(same_input_tv=.1,prediction_policy_tv=.1,prediction_confidence_abs=.1,min_valid_repeats=2),
        repeat_ids=[0,1,2],none_memory_policy='policy_only_diagnostic',instances=[],operating_points=[],templates=[],probes=[])
    for phase,prefix in [('development','d'),('prospective','p')]:
        for family in range(3):
            instance=f'{prefix}-f{family}';design['instances'].append(dict(id=instance,family=f'f{family}',phase=phase))
            reference=put(root,instance+'/reference.json',{'instance_id':instance,'steps':[0,4],'software_fixture':True})
            reference_descriptor={'path':reference,'sha256':local.sha((Path(root)/reference).read_bytes())}
            for step in (0,4):
                op=f'{instance}-s{step}';source=put(root,op+'/state.json',{'instance_id':instance,'reference_step':step,'facts':['SOFTWARE FIXTURE ONLY'],'evidence_ids':['e0'],'evidence':[{'id':'e0','text':'SOFTWARE FIXTURE ONLY'}],'action_space':list(reversed(design['coordinates']['action_ids']))})
                point=dict(id=op,instance_id=instance,reference_step=step,public_state={'path':source,'sha256':local.sha((Path(root)/source).read_bytes())},evidence_ids=['e0'],reference_path=reference_descriptor)
                if phase=='prospective':point['development_op_id']=f'd-f{family}-s{step}'
                design['operating_points'].append(point)
                templates={}
                for semantic in local.SEMANTICS:
                    for length in local.LENGTHS:
                        key=f'{op}-{semantic}-{length}';text='SOFTWARE FIXTURE '+key+' '
                        design['templates'].append(dict(id=key,operating_point_id=op,semantic=semantic,codepoints=length,hypothesis=text+'x'*(length-len(text)),evidence_ids=['e0']))
                        templates[(semantic,length)]=key
                def probe(name,branch,role,template=None,axis=None,sign=None,dc=0,paired=None):
                    q=[1/12]*12
                    if axis is not None:q[axis]+=.02*sign;q[11]-=.02*sign
                    row=dict(id=op+'-'+name,operating_point_id=op,branch=branch,role=role,template_id=template,q=q,confidence=.5+dc if template else None)
                    if role=='q_axis':row.update(axis=axis,sign=sign)
                    if role=='confidence_axis':row['sign']=1 if dc>0 else -1
                    if paired is not None:row['paired_h_probe_id']=paired
                    design['probes'].append(row);return row
                for n,template in enumerate([None,*templates.values()]):probe(f'H-center-{n}','H','center',template)
                probe('E-center','E','center')
                reference=templates[('correct',160)]
                if phase=='development':
                    for branch in ('H','E'):
                        for axis in range(11):
                            for sign in (-1,1):probe(f'{branch}-q-{axis}-{sign+1}',branch,'q_axis',reference if branch=='H' else None,axis,sign)
                    for n,template in enumerate(templates.values()):
                        for sign in (-1,1):probe(f'H-c-{n}-{sign+1}','H','confidence_axis',template,dc=.1*sign)
                    joints=[(reference,0,qs,.1*cs) for qs in (-1,1) for cs in (-1,1)]
                else:
                    joints=[(reference,axis,sign,.1*sign) for axis in range(4) for sign in (-1,1)]
                    joints += [(templates[(semantic,length)],4+i,sign,-.1*sign) for semantic,sign in [('incorrect',1),('irrelevant',-1)] for i,length in enumerate(local.LENGTHS)]
                for n,(template,axis,sign,dc) in enumerate(joints):
                    row=probe(f'H-j-{n}','H','joint',template,axis,sign,dc)
                    probe(f'E-j-{n}','E','joint',axis=axis,sign=sign,paired=row['id'])
    for template in design['templates']:
        template['hypothesis_sha256']=local.sha(template['hypothesis'].encode('utf-8'))
    code=put(root,'sources/software-fixture.json',{'description':'Known linear fixture; zero model calls'})
    exposure=put(root,'sources/exposure.json',{'software_fixture':True,'scientific_exposure_review':'not performed'})
    snapshot=put(root,'sources/snapshot.json',{'files':[{'path':code,'sha256':local.sha((Path(root)/code).read_bytes())}],
        'exposure_audit':{'path':exposure,'sha256':local.sha((Path(root)/exposure).read_bytes())}})
    design['source_snapshot']={'path':snapshot,'sha256':local.sha((Path(root)/snapshot).read_bytes())}
    design['source_snapshot_sha256']=design['source_snapshot']['sha256']
    return design


def linear_response(design,index,probe):
    op=index['ops'][probe['operating_point_id']];instance=index['instances'][op['instance_id']]
    family=int(instance['family'][1:]);prospective=instance['phase']=='prospective'
    baseline=.001*family+.0002*op['reference_step']+(.005 if prospective else 0)
    slope=(.2 if probe['branch']=='H' else .3)+.01*op['reference_step']+.02*family
    p=[1/12+slope*(q-1/12) for q in probe['q']];p[0]+=baseline;p[1]-=baseline
    template=index['templates'].get(probe.get('template_id'));memory=[]
    if template:
        confidence_slope=.05+.01*local.LENGTHS.index(template['codepoints'])
        shift=confidence_slope*(probe['confidence']-.5);p[0]+=shift;p[1]-=shift
        confidence=.4+.01*family+(.03 if prospective else 0)+.25*(probe['confidence']-.5)+.1*(probe['q'][0]-1/12)
        memory=[{'hypothesis':template['hypothesis'],'confidence':confidence,'evidence_ids':['e0']}]
    result={'probabilities':dict(zip(design['coordinates']['action_ids'],p))}
    if probe['branch']=='H':result['memory']=memory
    return result


def admission(request):
    return {'admitted':True,'receipt':'SOFTWARE-FIXTURE-controller-admission-'+request['slot_id']}


def fixture_receipt(start,response,status='completed'):
    now=datetime.now(timezone.utc).isoformat()
    data=start['data']
    if status=='unknown':
        return {'source':'local_unknown','request_id':data['request_id'],'session_id':data['session_id'],'payload_sha256':data['payload_sha256'],'captured_at':now}
    return {'source':'software_fixture','mock_source':'known-linear-zero-model-calls','request_id':data['request_id'],'session_id':data['session_id'],
            'payload_sha256':data['payload_sha256'],'started_at':start['recorded_at'],'completed_at':now,'captured_at':now,
            'raw_response_sha256':local.sha(local.canonical(response)) if response is not None else None}


def provider_receipt(root,design,start,response):
    # Entirely synthetic provider-shaped receipt, never a live request.
    slot=start['data']['slot_id'];raw=put(root,'transport/'+slot+'-raw.json',response)
    now=datetime.now(timezone.utc).isoformat()
    receipt={'source':'provider_receipt','timestamp_source':'provider_receipt','request_id':start['data']['request_id'],
        'session_id':start['data']['session_id'],'payload_sha256':start['data']['payload_sha256'],'provider_request_id':'SYNTHETIC-'+slot,'started_at':start['recorded_at'],
        'completed_at':now,'captured_at':now,'usage':{'fixture_tokens':0},
        'raw_response':{'path':raw,'sha256':local.sha((root/raw).read_bytes())},
        **{key:design['model_binding'][key] for key in ('provider','model','version')}}
    name=put(root,'transport/'+slot+'-receipt.json',receipt)
    return {**receipt,'receipt_artifact':{'path':name,'sha256':local.sha((root/name).read_bytes())}}


def record_part(recorder,predicate):
    for slot,item in recorder.index['slots'].items():
        probe=recorder.index['probes'][item['probe_id']];op=recorder.index['ops'][probe['operating_point_id']]
        phase=recorder.index['instances'][op['instance_id']]['phase']
        if predicate(phase,probe):
            start=recorder.start(slot,'request-'+slot,'session-'+slot)
            response=linear_response(recorder.design,recorder.index,probe)
            recorder.finish(slot,response=response,receipt=fixture_receipt(start,response))


def rechain(events):
    previous='0'*64
    for n,event in enumerate(events,1):
        event['sequence']=n;event['previous_sha256']=previous
        event['event_sha256']=local.sha(local.canonical({k:v for k,v in event.items() if k!='event_sha256'}));previous=event['event_sha256']
    return events


class LocalResponseSchemaTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.design=make_design(self.root)

    def test_explicit_nested_counts_and_phase_transfer(self):
        index=local.validate_design(self.design,self.root)
        self.assertEqual((6,12,108,720,2160),tuple(len(index[key]) for key in ('instances','ops','templates','probes','slots')))
        for field in ('cases','seeds','conditions'):self.assertNotIn(field,self.design)
        bad=copy.deepcopy(self.design);bad['operating_points'][-1]['development_op_id']='d-f0-s0'
        with self.assertRaisesRegex(ValueError,'transfer map'):local.validate_design(bad)

    def test_missing_direction_duplicate_template_and_wrong_coordinates(self):
        variants=[]
        bad=copy.deepcopy(self.design);bad['probes'].pop();variants.append(bad)
        bad=copy.deepcopy(self.design);bad['templates'][0]['hypothesis']='wrong length';variants.append(bad)
        bad=copy.deepcopy(self.design);next(p for p in bad['probes'] if p['role']=='q_axis')['q']=[1/12]*12;variants.append(bad)
        bad=copy.deepcopy(self.design);next(p for p in bad['probes'] if p['branch']=='E')['confidence']=0;variants.append(bad)
        bad=copy.deepcopy(self.design)
        reference=[p for p in bad['probes'] if p['operating_point_id']=='p-f0-s0' and p['branch']=='H' and p['role']=='joint' and p['template_id']=='p-f0-s0-correct-160']
        reference[2]['q']=reference[0]['q'].copy()
        next(p for p in bad['probes'] if p.get('paired_h_probe_id')==reference[2]['id'])['q']=reference[2]['q'].copy()
        variants.append(bad)
        for bad in variants:
            with self.subTest(variant=variants.index(bad)),self.assertRaises(ValueError):local.validate_design(bad)

    def test_draft_is_readable_but_formal_recording_is_refused(self):
        self.design['model_binding']={'status':'draft'};local.validate_design(self.design,self.root)
        put(self.root,'design.json',self.design)
        recorder=local.LocalResponseRecorder(self.root,'design.json','records',admission)
        with self.assertRaisesRegex(ValueError,'resolved model binding'):recorder.start('s0000-r0','r','s')
        self.assertEqual([],list((self.root/'records/events').glob('*')) if (self.root/'records/events').exists() else [])

    def test_controller_admission_unknown_replay_and_session_identity(self):
        put(self.root,'design.json',self.design)
        denied=local.LocalResponseRecorder(self.root,'design.json','denied',lambda request:{'admitted':False})
        with self.assertRaisesRegex(ValueError,'did not admit'):denied.start('s0000-r0','r','s')
        recorder=local.LocalResponseRecorder(self.root,'design.json','records',admission)
        start=recorder.start('s0000-r0','r','s');recorder.finish('s0000-r0',status='unknown',receipt=fixture_receipt(start,None,'unknown'),reason='lost terminal outcome')
        with self.assertRaisesRegex(ValueError,'cannot be retried'):recorder.start('s0000-r0','r2','s2')
        with self.assertRaisesRegex(ValueError,'duplicate'):recorder.start('s0000-r1','r2','s')
        summary=recorder.analyze();self.assertEqual(1,summary['counts']['unknown']);self.assertEqual(2159,summary['counts']['not_started']);self.assertEqual('incomplete',summary['assessment'])
        prospective=next(slot for slot,item in recorder.index['slots'].items() if item['probe_id'].startswith('p-'))
        with self.assertRaisesRegex(ValueError,'before coefficients'):recorder.start(prospective,'r3','s3')

    def test_provider_receipt_identity_bytes_and_export_closure(self):
        self.design['software_fixture']=False
        put(self.root,'design.json',self.design)
        recorder=local.LocalResponseRecorder(self.root,'design.json','records',admission)
        start=recorder.start('s0000-r0','r','s');probe=recorder.index['probes'][start['data']['identity']['probe_id']]
        response=linear_response(self.design,recorder.index,probe)
        with self.assertRaisesRegex(ValueError,'request/session'):recorder.finish('s0000-r0',response=response,receipt={})
        with self.assertRaisesRegex(ValueError,'cannot certify scientific'):recorder.finish('s0000-r0',response=response,receipt=fixture_receipt(start,response))
        receipt=provider_receipt(self.root,self.design,start,response)
        wrong=copy.deepcopy(receipt);wrong['session_id']='foreign-session'
        with self.assertRaisesRegex(ValueError,'request/session'):recorder.finish('s0000-r0',response=response,receipt=wrong)
        wrong=copy.deepcopy(response);wrong['probabilities']['a0']+=.01;wrong['probabilities']['a1']-=.01
        with self.assertRaisesRegex(ValueError,'parsed response differs'):recorder.finish('s0000-r0',response=wrong,receipt=receipt)
        recorder.finish('s0000-r0',response=response,receipt=receipt)
        self.assertEqual(2,len(recorder.results()['receipt_artifacts']))
        (self.root/receipt['raw_response']['path']).write_text('{}')
        with self.assertRaisesRegex(ValueError,'raw response bytes hash'):recorder.analyze()

    def test_provider_request_reuse_and_wrong_payload_rejected(self):
        self.design['software_fixture']=False;put(self.root,'design.json',self.design)
        recorder=local.LocalResponseRecorder(self.root,'design.json','records',admission)
        first=recorder.start('s0000-r0','r0','s0');probe=recorder.index['probes'][first['data']['identity']['probe_id']]
        response=linear_response(self.design,recorder.index,probe);receipt=provider_receipt(self.root,self.design,first,response)
        wrong=copy.deepcopy(receipt);wrong['payload_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'payload hash'):recorder.finish('s0000-r0',response=response,receipt=wrong)
        recorder.finish('s0000-r0',response=response,receipt=receipt)
        second=recorder.start('s0000-r1','r1','s1');duplicate=provider_receipt(self.root,self.design,second,response)
        duplicate['provider_request_id']=receipt['provider_request_id']
        path=duplicate['receipt_artifact']['path'];put(self.root,path,{k:v for k,v in duplicate.items() if k!='receipt_artifact'})
        duplicate['receipt_artifact']['sha256']=local.sha((self.root/path).read_bytes())
        with self.assertRaisesRegex(ValueError,'duplicate provider request'):recorder.finish('s0000-r1',response=response,receipt=duplicate)

    def test_reserved_coordinate_and_rehashed_time_reversal_rejected(self):
        bad=copy.deepcopy(self.design);bad['coordinates']['action_ids'][-1]='confidence'
        with self.assertRaisesRegex(ValueError,'reserved'):local.validate_design(bad)
        put(self.root,'design.json',self.design);recorder=local.LocalResponseRecorder(self.root,'design.json','records',admission)
        start=recorder.start('s0000-r0','r','s');probe=recorder.index['probes'][start['data']['identity']['probe_id']]
        response=linear_response(self.design,recorder.index,probe);recorder.finish('s0000-r0',response=response,receipt=fixture_receipt(start,response))
        events=copy.deepcopy(recorder._load(full=True));events[1]['recorded_at']=(datetime.fromisoformat(events[0]['recorded_at'])-timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(ValueError,'timestamps must be monotone'):local.analyze(self.design,rechain(events),self.root,design_sha256=recorder.design_sha256)

    def test_confidence_pairwise_diagnostics_do_not_add_a_threshold(self):
        put(self.root,'design.json',self.design);recorder=local.LocalResponseRecorder(self.root,'design.json','records',admission)
        probe=next(p for p in recorder.index['probes'].values() if p['branch']=='H' and p['role']=='center' and p['template_id'])
        slots=[slot for slot,item in recorder.index['slots'].items() if item['probe_id']==probe['id']]
        for index,slot in enumerate(slots):
            start=recorder.start(slot,'r'+str(index),'s'+str(index));response=linear_response(self.design,recorder.index,probe)
            response['memory'][0]['confidence']=.4+index*.1
            recorder.finish(slot,response=response,receipt=fixture_receipt(start,response))
        result=recorder.analyze();cell=result['cells'][probe['id']]
        self.assertTrue(cell['estimable']);self.assertEqual(3,len(cell['pairwise_abs_confidence']))
        self.assertAlmostEqual(.2,cell['max_abs_confidence']);self.assertEqual(0,cell['max_same_input_tv'])
        self.assertAlmostEqual(.2,next(group for group in result['same_input'].values() if slots[0] in group['slot_ids'])['max_abs_confidence'])
        self.assertNotIn('same_input_confidence',self.design['thresholds'])

    def test_source_closure_and_formal_block_are_verified(self):
        sources=local.source_artifacts(self.design,self.root)
        self.assertIn('sources/software-fixture.json',sources);self.assertIn('sources/exposure.json',sources)
        self.assertIn('d-f0/reference.json',sources)
        for mutation,phrase in [
            (lambda d:d['source_snapshot'].update(sha256='0'*64),'source artifact hash'),
            (lambda d:d['operating_points'][0]['reference_path'].update(sha256='0'*64),'source artifact hash'),
            (lambda d:d['templates'][0].update(hypothesis_sha256='0'*64),'hypothesis byte hash')]:
            bad=copy.deepcopy(self.design);mutation(bad)
            with self.subTest(phrase=phrase),self.assertRaisesRegex(ValueError,phrase):local.validate_design(bad,self.root)
        bad=copy.deepcopy(self.design);bad['software_fixture']=False;del bad['source_snapshot']
        with self.assertRaisesRegex(ValueError,'needs source_snapshot'):local.validate_design(bad,self.root)
        bad=copy.deepcopy(self.design);bad['software_fixture']=False;del bad['operating_points'][0]['reference_path']
        with self.assertRaisesRegex(ValueError,'need reference_path'):local.validate_design(bad,self.root)
        blocked=copy.deepcopy(self.design);blocked['formal_collection_blocked']=True;put(self.root,'blocked.json',blocked)
        recorder=local.LocalResponseRecorder(self.root,'blocked.json','blocked-records',admission)
        with self.assertRaisesRegex(ValueError,'explicitly blocked'):recorder.start('s0000-r0','r','s')
        (self.root/'sources/software-fixture.json').write_text('changed dependency bytes')
        with self.assertRaisesRegex(ValueError,'source artifact hash'):local.validate_design(self.design,self.root)

    def test_public_state_identity_and_declared_dependencies_cannot_be_invented(self):
        op=self.design['operating_points'][0];path=self.root/op['public_state']['path'];original=path.read_bytes()
        for field,value,phrase in [('instance_id','foreign','instance identity'),('evidence',[{'id':'foreign'}],'evidence identity'),('action_space',['unknown'],'action space')]:
            document=json.loads(original);document[field]=value;path.write_bytes(local.canonical(document))
            bad=copy.deepcopy(self.design);bad['operating_points'][0]['public_state']['sha256']=local.sha(path.read_bytes())
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,phrase):local.validate_design(bad,self.root)
            path.write_bytes(original)
        # Different enumeration order is valid: coordinates remain bound by stable IDs.
        self.assertEqual('verified',local.validate_design(self.design,self.root)['source_verification'])
        bad=copy.deepcopy(self.design);bad['model_binding']={'status':'draft'}
        name=put(self.root,'sources/missing-snapshot.json',{'files':[{'path':'not-copied.py','sha256':'0'*64}]})
        bad['source_snapshot']={'path':name,'sha256':local.sha((self.root/name).read_bytes())};bad['source_snapshot_sha256']=bad['source_snapshot']['sha256']
        self.assertEqual('unresolved_root',local.validate_design(bad)['source_verification'])
        with self.assertRaisesRegex(ValueError,'artifact is missing'):local.validate_design(bad,self.root)

    def test_same_input_groups_keep_unstarted_unknown_and_chronology(self):
        put(self.root,'design.json',self.design);recorder=local.LocalResponseRecorder(self.root,'design.json','records',admission)
        start=recorder.start('s0000-r0','r','s')
        recorder.finish('s0000-r0',status='unknown',receipt=fixture_receipt(start,None,'unknown'),reason='SOFTWARE unknown')
        group=recorder.analyze()['same_input'][start['data']['payload_sha256']]
        self.assertEqual({'planned':3,'attempted':1,'valid':0,'invalid':0,'failed':0,'unknown':1,'not_started':2},group['counts'])
        self.assertEqual(3,len(group['slot_ids']));self.assertEqual([],group['valid_slot_ids'])
        self.assertEqual(1,group['chronology'][0]['start_sequence']);self.assertEqual(2,group['chronology'][0]['terminal_sequence'])
        self.assertIsNone(group['max_tv']);self.assertEqual([],group['pairwise_tv'])

    def test_cached_prior_event_change_refuses_new_admission(self):
        put(self.root,'design.json',self.design)
        recorder=local.LocalResponseRecorder(self.root,'design.json','records',admission)
        recorder.start('s0000-r0','r','s')
        path=self.root/'records/events/000001.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'previous event file changed'):recorder.start('s0000-r1','r1','s1')

    def test_invalid_vectors_memory_and_structural_null(self):
        index=local.validate_design(self.design,self.root)
        h=next(p for p in index['probes'].values() if p['branch']=='H' and p['template_id'])
        response=linear_response(self.design,index,h);response['memory'][0]['hypothesis']+='changed'
        with self.assertRaisesRegex(ValueError,'identity changed'):local.response_vector(self.design,index,h,response)
        response=linear_response(self.design,index,h);response['probabilities']['a0']=-1
        with self.assertRaisesRegex(ValueError,'simplex'):local.response_vector(self.design,index,h,response)
        for probe in [p for p in index['probes'].values() if p['template_id'] is None][:4]:
            observed=local.response_vector(self.design,index,probe,linear_response(self.design,index,probe));self.assertIsNone(observed['confidence'])
        for actual,expected in zip(local.finite_difference([.14,.06],[.06,.14],.02),(2.,-2.)):self.assertAlmostEqual(expected,actual)


class LocalResponseLinearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory(prefix='local-response-SOFTWARE-fixture-');cls.addClassCleanup(cls.temporary.cleanup)
        cls.root=Path(cls.temporary.name);cls.design=make_design(cls.root);put(cls.root,'design.json',cls.design)
        cls.recorder=local.LocalResponseRecorder(cls.root,'design.json','records',admission)
        record_part(cls.recorder,lambda phase,probe:phase=='development')
        cls.recorder.freeze_coefficients()
        record_part(cls.recorder,lambda phase,probe:phase=='prospective' and probe['role']=='center')
        cls.recorder.freeze_predictions()
        record_part(cls.recorder,lambda phase,probe:phase=='prospective' and probe['role']=='joint')
        cls.events=cls.recorder._load(full=True)
        cls.summary=cls.recorder.analyze()

    def analyze(self,events):
        return local.analyze(self.design,events,self.root,design_sha256=self.recorder.design_sha256)

    def test_full_2160_slot_known_linear_coefficients_and_predictions(self):
        result=self.summary
        self.assertEqual({'planned':2160,'attempted':2160,'valid':2160,'invalid':0,'failed':0,'unknown':0,'not_started':0},result['counts'])
        self.assertEqual('within_engineering_tolerance',result['assessment'])
        self.assertEqual(168,len(result['prospective_points']))
        for op_id,point in result['coefficients']['operating_points'].items():
            op=self.recorder.index['ops'][op_id];family=int(self.recorder.index['instances'][op['instance_id']]['family'][1:])
            for branch in ('H','E'):
                slope=(.2 if branch=='H' else .3)+.01*op['reference_step']+.02*family
                for axis,column in enumerate(point[branch]['q_columns']):
                    for coordinate,value in enumerate(column[:12]):self.assertAlmostEqual(slope if coordinate==axis else -slope if coordinate==11 else 0.,value)
                    if branch=='H':self.assertAlmostEqual(.1 if axis==0 else 0.,column[12])
            for column in point['H']['confidence_columns'].values():self.assertAlmostEqual(.25,column[12])
        for probe_id,cell in result['cells'].items():
            if self.recorder.index['probes'][probe_id]['template_id'] is None:self.assertIsNone(cell['mean_confidence'])
        for point in result['prospective_points'].values():
            self.assertLess(point['policy_tv'],1e-12)
            if point['confidence_abs_error'] is not None:self.assertLess(point['confidence_abs_error'],1e-12)
        self.assertFalse(result['global_stability']);self.assertFalse(result['full_text_identification']);self.assertNotIn('mean',result)
        snapshot=self.recorder.results();self.assertEqual(4323,len(snapshot['events']))
        self.assertEqual(result['event_head_sha256'],snapshot['event_head_sha256'])

    def test_same_payload_across_probe_slots_is_not_hidden(self):
        groups=self.summary['same_input']
        self.assertTrue(any(len(group['slot_ids'])>3 for group in groups.values()))
        events=copy.deepcopy(self.events)
        # Change one prospective E joint response so the group detects repeated-payload noise.
        target=next(e for e in events if e['kind']=='terminal' and e['data']['identity']['probe_id']=='p-f0-s0-E-j-0')
        probabilities=target['data']['response']['probabilities']
        # Move mass from three coordinates to a0; preserve exact simplex.
        for action in ('a3','a4','a5'):probabilities['a0']+=probabilities[action];probabilities[action]=0
        target['data']['receipt']['raw_response_sha256']=local.sha(local.canonical(target['data']['response']))
        changed=self.analyze(rechain(events))
        self.assertEqual('local_prediction_failed',changed['assessment'])
        self.assertTrue(any(group['max_tv'] is not None and group['max_tv']>.1 for group in changed['same_input'].values()))
        self.assertEqual(2160,changed['counts']['valid'])

    def test_freeze_content_leakage_identity_and_hash_tampering_refused(self):
        tests=[]
        bad=copy.deepcopy(self.events);bad[1]['data']['identity']['repeat_id']=1;tests.append((rechain(bad),'identity crossover'))
        bad=copy.deepcopy(self.events);next(e for e in bad if e['kind']=='coefficients')['data']['operating_points']['d-f0-s0']['H']['q_columns'][0][0]=123;tests.append((rechain(bad),'frozen coefficients'))
        bad=copy.deepcopy(self.events);index=next(i for i,e in enumerate(bad) if e['kind']=='predictions');bad.pop(index);tests.append((rechain(bad),'before predictions'))
        bad=copy.deepcopy(self.events);bad[0]['data']['payload']['q']['a0']=.5;tests.append((rechain(bad),'payload changed'))
        bad=copy.deepcopy(self.events);bad[0]['data']['request_id']='tampered';tests.append((bad,'hash chain'))
        for events,phrase in tests:
            with self.subTest(phrase=phrase),self.assertRaisesRegex(ValueError,phrase):self.analyze(events)

    def test_invalid_and_incomplete_denominators_are_not_penalties(self):
        events=copy.deepcopy(self.events)
        targets=[e for e in events if e['kind']=='terminal' and e['data']['identity']['probe_id']=='p-f0-s0-H-j-0']
        for event in targets[:2]:
            event['data'].update(status='failed',response=None,valid=False,reason='SOFTWARE provider failure')
            event['data']['receipt']['raw_response_sha256']=None
        result=self.analyze(rechain(events));point=result['prospective_points']['p-f0-s0-H-j-0']
        self.assertEqual('incomplete',result['assessment']);self.assertEqual('incomplete',point['verdict']);self.assertIsNone(point['policy_tv'])
        self.assertEqual((1,2),(point['counts']['valid'],point['counts']['failed']))
        self.assertEqual(3,point['counts']['planned']);self.assertEqual(2160,result['counts']['planned'])

    def test_illegal_prediction_is_not_projected(self):
        # Pure prediction test: valid center and coefficients can extrapolate outside the simplex.
        index=self.recorder.index;cells=copy.deepcopy(self.summary['cells']);frozen=copy.deepcopy(self.summary['coefficients'])
        frozen['operating_points']['d-f0-s0']['H']['q_columns'][0][0]=100
        frozen['operating_points']['d-f0-s0']['H']['q_columns'][0][1]=-100
        predicted=local.predictions(self.design,index,cells,frozen)
        bad=predicted['points']['p-f0-s0-H-j-0']
        self.assertFalse(bad['valid']);self.assertTrue(any(value<0 or value>1 for value in bad['policy']))


if __name__=='__main__':unittest.main()
