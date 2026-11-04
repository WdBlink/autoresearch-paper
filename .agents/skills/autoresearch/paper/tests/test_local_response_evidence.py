"""Full mixed-protocol SOFTWARE fixture; all provider-shaped bytes are synthetic."""
import copy
import json
import os
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib import science, local_response as local, local_response_evidence as local_evidence
from lib.runtime import Controller, Refusal, file_hash
from run_fixture import run, FixturePaused, put
from test_multi_design import designs as scalar_designs, record as scalar_record, render, paths
from test_local_response import make_design, linear_response, fixture_receipt, provider_receipt, admission


def designs(root):
    paired=scalar_designs(root)[1:]
    design=make_design(root);design.update(experiment_id='L0',claim_id='C1')
    name=put(root,'L0/design.json',design)
    return [dict(id='L0',path=name,sha256=file_hash(root/name),protocol=local.PROTOCOL,claim_ids=['C1']),*paired]


def record(root,registry):
    paired=scalar_record(root,[entry for entry in registry if entry['protocol']=='paired_case_mean'])
    recorder=local.LocalResponseRecorder(root,'L0/design.json','L0/records',admission)
    first=True
    for phase in ('development','centers','joints'):
        for slot,item in recorder.index['slots'].items():
            probe=recorder.index['probes'][item['probe_id']];op=recorder.index['ops'][probe['operating_point_id']]
            development=recorder.index['instances'][op['instance_id']]['phase']=='development'
            selected=development if phase=='development' else (not development and probe['role']==('center' if phase=='centers' else 'joint'))
            if selected:
                start=recorder.start(slot,'request-'+slot,'session-'+slot)
                response=linear_response(recorder.design,recorder.index,probe)
                receipt=provider_receipt(root,recorder.design,start,response) if first else fixture_receipt(start,response)
                first=False
                recorder.finish(slot,response=response,receipt=receipt)
        if phase=='development':recorder.freeze_coefficients()
        elif phase=='centers':recorder.freeze_predictions()
    result=put(root,'L0/results.json',recorder.results())
    summary=put(root,'L0/summary.md','SOFTWARE FIXTURE ONLY. Known-linear vectors and synthetic provider-shaped receipt bytes. Zero model requests; no scientific acceptance.')
    return [dict(design_id='L0',results=result,summary=summary),*paired]


class LocalResponseEvidenceTests(unittest.TestCase):
    def test_mixed_local_and_scalar_pipeline_and_negative_bindings(self):
        with tempfile.TemporaryDirectory(prefix='multi-design-software-fixture-') as temp:
            root=Path(temp)
            original_commit=Controller.commit
            def commit(ctl, packet, op):
                packet=copy.deepcopy(packet)
                if packet['stage']=='plan':
                    packet.pop('experiment_design_sha256')
                    packet['experiment_designs']=designs(root)
                    packet['artifacts'] += [entry['path'] for entry in packet['experiment_designs']]
                    packet['artifacts'] += [point['public_state']['path'] for point in science.strict_json(root,'L0/design.json')['operating_points']]
                    packet['work_orders'][0]['actions']=[{'type':'validate_packet','packet':'multi/experiment-packet.json'}]
                    packet['work_orders'][1]['actions']=[{'type':'validate_packet','packet':'multi/figures-packet.json'}]
                    packet['work_orders'][2]['actions']=[{'type':'compile_tex','source':'multi/main.tex','pdf':'multi/main.pdf'}]
                return original_commit(ctl,packet,op)
            with patch.object(Controller,'commit',commit),self.assertRaises(FixturePaused):
                run(root,stop_after='literature')
            ctl=Controller(root)
            history={r['stage']:r['packet'] for r in ctl.load()['receipts']}
            registry=history['plan']['experiment_designs']
            def submit(stage,**fields):
                packet={'stage':stage,'producer':'fixture-author','software_fixture':True,'artifacts':paths(root),**fields}
                put(root,'multi/'+stage+'-packet.json',packet)
                if stage in {'experiment','figures'}:
                    ctl.execute('W-'+stage,'execute-multi-'+stage)
                ctl.commit(packet,'multi-'+stage)
                return packet
            experiments=record(root,registry)
            submit('experiment',experiments=experiments)
            evidence=render(root,experiments,suffix="pdf")
            submit('figures',evidence_sets=evidence)
            sentences=[row['design_id']+' software fixture prospective error was 0.000000 probability-TV.' if row['design_id']=='L0' else row['design_id']+' software fixture mean was 1.500000 units.' for row in evidence]
            derivative_sentence='The d-f0-s0 software fixture response column was 0.200000 probability-per-q-coordinate.'
            limitations=[{'kind':'scope','text':'Software fixture only, not scientific evidence.'},
                         {'kind':'small_sample','text':'Three independent software cases limit generalization.'},
                         {'kind':'adverse','text':'Adverse synthetic contrasts are retained.'}]
            text='\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\n'+'\n'.join(sentences+[derivative_sentence,r'Fixture source~\cite{fixture}.']+[x['text'] for x in limitations])+r'\begin{thebibliography}{1}\bibitem{fixture} Offline Fixture. Software fixture only.\end{thebibliography}\end{document}'
            visuals=(r'\begin{figure}[ht]\centering'+''.join(r'\includegraphics[width=.3\linewidth]{../'+row['figure']+'}' for row in evidence)+r'\caption{Paired software fixture errors.}\label{fig:F1}\end{figure}'+
                     r'\begin{table}[ht]\centering'+''.join(r'\resizebox{.3\linewidth}{!}{\input{../'+row['table']+'}}' for row in evidence)+r'\caption{Full-denominator fixture statistics.}\label{tab:T1}\end{table}')
            text=text.replace(r'\end{document}',visuals+r'\end{document}')
            tex=put(root,'multi/main.tex',text)
            ctl.execute('W-writing','compile-multi-writing')
            assertions=[]
            for row,sentence in zip(evidence,sentences):
                assertion=dict(id='A-'+row['id'],claim_id='C1',text=sentence,design_id=row['design_id'],evidence_set_id=row['id'],
                    statistics=row['statistics'],measure='conditions.arm0.mean',value=1.5,unit='units',denominator=3,
                    condition='all-planned-cases',strength='descriptive',kind='numeric')
                if row['design_id']=='L0':
                    local_stats=science.strict_json(root,row['statistics'])
                    point=local_stats['prospective_points']['p-f0-s0-H-j-0']
                    assertion.update(operating_point_id='p-f0-s0',probe_id='p-f0-s0-H-j-0',measure='prospective_policy_tv',
                        value=point['policy_tv'],unit='probability-TV',condition='fixed-template-local-response',
                        denominator={'independent_instance_id':'p-f0','planned':3,'valid':3})
                    endpoint_ids=['d-f0-s0-H-q-0-0','d-f0-s0-H-q-0-2']
                    derivative={**assertion,'id':'A-local-derivative','text':derivative_sentence,'operating_point_id':'d-f0-s0',
                        'probe_id':None,'branch':'H','axis_id':0,'output_coordinate':'a0','endpoint_probe_ids':endpoint_ids,
                        'measure':'central_difference_entry','value':local_stats['coefficients']['operating_points']['d-f0-s0']['H']['q_columns'][0][0],
                        'unit':'probability-per-q-coordinate','denominator':{'independent_instance_id':'d-f0',
                            'endpoints':{key:local_stats['cells'][key]['counts'] for key in endpoint_ids}}}
                    assertions.append(derivative)
                assertions.append(assertion)
            facts=put(root,'multi/assertions.json',{'assertions':assertions,'limitations':limitations,
                'prose_review':dict(problem='software',choice='software',finding='software',scope='software'),'revisions':[]})
            template_info=history['venue']['template'];literature=history['literature']
            submit('write',manuscript=tex,manuscript_tex=tex,manuscript_pdf='multi/main.pdf',assertions=facts,
                bibliography=literature['bibliography'],template_source=template_info['path'],template_sha256=template_info['sha256'],
                section_packets=[dict(id='S1',path=tex,purpose='SOFTWARE FIXTURE ONLY',claim_ids=['C1'],citation_keys=['fixture'],
                                     evidence=[r['statistics'] for r in evidence],baseline=None,line_limit_exception=None)])
            state=ctl.load()
            self.assertEqual(['intake','venue','plan','literature','experiment','figures','write'],[r['stage'] for r in state['receipts']])
            self.assertTrue(state['brief']['software_fixture'])
            for receipt in state['receipts']:
                ctl.validate(state,receipt['packet'])
            all_evidence=[row['results'] for row in experiments]+[row['statistics'] for row in evidence]
            bindings=[]
            for key,work,assets,location in [
                ('F1','W-figures',[row['figure'] for row in evidence],r'\label{fig:F1}'),
                ('T1','W-figures',[row['table'] for row in evidence],r'\label{tab:T1}'),
                ('S1','W-writing',[tex],sentences[0]),
                ('M1','W-writing',['multi/main.pdf'],r'\documentclass{article}')]:
                bindings.append(dict(requirement_id=key,work_id=work,assets=assets,evidence=all_evidence,manuscript=tex,location=location))
            ctl.bind_all(bindings,'bind-multi-design')
            bound=ctl.load()['bindings']
            report=put(root,'review/multi-report.md','SOFTWARE FIXTURE scripted reviewer only. No independent model or scientific peer review was performed.')
            revision=put(root,'review/multi-revision.json',{'status':'initial_draft','changes':[]})
            prepared=ctl.prepare_review('review/multi-request.json')
            judgment=dict(reviewer='fixture-reviewer',request_sha256=prepared['request_sha256'],reports=[report],findings=[],
                reviewer_identity={'kind':'software_fixture','independent_model_review':'not performed'},
                gates={key:{'verdict':'pass','evidence':[report],'reason':'Scripted software checks only; not scientific acceptance.'} for key in ['G1','G2','G3','G4','G5','R6']},
                r6_reviews=[{'id':key,'verdict':'fulfilled','reason':'Three independent software designs are inserted in the compiled composite visual.',
                             'evidence_locations':['Figure 1' if key=='F1' else 'Table 1']} for key in ['F1','T1']],
                requirement_checks=[{'requirement_id':key,'binding_sha256':value['binding_sha256'],'evidence_hashes':value['hashes'],
                                     'verdict':'fulfilled','rationale':'Software fixture artifact correspondence only.'} for key,value in bound.items()])
            put(root,'review/multi-judgment.json',judgment)
            ctl.assemble_review({'request':'review/multi-request.json','judgment':'review/multi-judgment.json','target':'review/multi-assembled.json',
                'completion':{'revision':[revision],'snapshot':'review/multi-snapshot.json','r6_report':'review/multi-r6.json'}})
            review=science.strict_json(root,'review/multi-assembled.json')
            ctl.commit(review,'multi-review')
            request=ctl.prepare_round([report,'review/multi-snapshot.json'])
            exported=ctl.deliver({'request_sha256':request['request_sha256'],'progress':'verified_progress','reason':'Complete local software fixture; no scientific acceptance.',
                                  'status':'active','phase':'integration'},'export-multi-design')
            self.assertEqual('software_fixture_complete',exported['status'])
            self.assertEqual('verified',ctl.verify_export(exported['manifest'])['status'])
            manifest=science.strict_json(root,exported['manifest'])
            self.assertTrue(manifest['software_fixture'])
            self.assertEqual('rebuilt_from_exported_assets',manifest['rebuild']['status'])
            expected={entry['path'] for entry in registry}
            for row in experiments:
                expected.update([row['results'],row['summary']])
                document=science.strict_json(root,row['results'])
                if document.get('protocol')==local.PROTOCOL:
                    expected.update(ref['path'] for ref in document['events']+document['receipt_artifacts'])
                    expected.update(local.source_artifacts(science.strict_json(root,'L0/design.json'),root,require_resolved=True))
                else:
                    expected.update(run['raw'] for run in document['runs'])
            for row in evidence:
                expected.update(row[key] for key in ['statistics','table','figure','trace'])
            self.assertTrue(expected <= set(manifest['artifacts']))
            with zipfile.ZipFile(exported['archive']) as archive:
                for name in expected:
                    self.assertEqual((root/name).read_bytes(),archive.read('artifacts/'+name),name)
            self.assertEqual(8,len(ctl.load()['receipts']))
            self.assertTrue(any('transport/' in path for path in expected))
            preview_root=os.environ.get('LOCAL_RESPONSE_FIXTURE_PREVIEW')
            if preview_root:
                destination=Path(preview_root).resolve();destination.mkdir(parents=True,exist_ok=True)
                preview=Path(tempfile.mkdtemp(prefix='software-run-',dir=destination))
                local_set=next(row for row in evidence if row['design_id']=='L0')
                shutil.copyfile(root/local_set['figure'],preview/'local-audit.pdf')
                shutil.copyfile(root/local_set['statistics'],preview/'statistics.json')
                (preview/'local-audit.svg').write_bytes(science._figure(local_stats,'.svg'))
                (preview/'caption.txt').write_text(local_set['caption'])
                shutil.copyfile(root/exported['manifest'],preview/'export-manifest.json')
                archive=Path(exported['archive'])
                if archive.stat().st_size<=50*1024*1024:shutil.copyfile(archive,preview/'software-fixture-export.zip')
                (preview/'README.md').write_text('SOFTWARE FIXTURE ONLY. Zero actual provider/model requests. Provider-shaped receipts are synthetic. This unit test does not claim manual visual review or publication-ready figures. The ZIP and manifest preserve the checked evidence closure.\n')
                (destination/'latest.json').write_text(json.dumps({'software_fixture':True,'directory':str(preview),'model_calls':0,'export_status':exported['status'],'expected_evidence_files':len(expected)},indent=2)+'\n')

            # Semantic negatives use actual production validators, never mocked acceptance.
            with self.subTest('wrong local endpoint'):
                wrong=copy.deepcopy(derivative);wrong['endpoint_probe_ids'].reverse()
                with self.assertRaisesRegex(ValueError,'endpoint direction or order'):local_evidence.assertion_value(wrong,local_stats)
            with self.subTest('wrong operating point'):
                wrong=copy.deepcopy(next(a for a in assertions if a['measure']=='prospective_policy_tv'));wrong['operating_point_id']='p-f1-s0'
                with self.assertRaisesRegex(ValueError,'probe/state mismatch'):local_evidence.assertion_value(wrong,local_stats)
            with self.subTest('cross design result'):
                state=ctl.load();accepted=next(r['packet'] for r in state['receipts'] if r['stage']=='experiment')
                wrong=copy.deepcopy(accepted);wrong['experiments'][0]['results']='D1/results.json'
                with self.assertRaisesRegex(Refusal,'identity mismatch'):ctl.validate(state,wrong)
            with self.subTest('omitted event from index'):
                wrong=science.strict_json(root,'L0/results.json');wrong['events'].pop()
                put(root,'L0/missing-event.json',wrong)
                with self.assertRaisesRegex(ValueError,'unindexed local event'):local_evidence.load(root,'L0/design.json','L0/missing-event.json')
            with self.subTest('omitted raw response closure'):
                wrong=science.strict_json(root,'L0/results.json');wrong['receipt_artifacts']=[]
                put(root,'L0/missing-receipt.json',wrong)
                with self.assertRaisesRegex(ValueError,'receipt export closure'):local_evidence.load(root,'L0/design.json','L0/missing-receipt.json')



if __name__=='__main__':unittest.main()
