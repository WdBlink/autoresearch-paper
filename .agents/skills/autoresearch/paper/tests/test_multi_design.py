"""SOFTWARE FIXTURES ONLY: no model, network or scientific evidence."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import science, production
from lib.experiments import ExperimentRecorder, template
from lib.runtime import Controller, file_hash
from run_fixture import run, FixturePaused, put
from test_multiarm import fixture_design
import test_science


def designs(root):
    registry = []
    for index, arms in enumerate((2, 8, 9)):
        identity = 'D' + str(index)
        design = fixture_design(['arm' + str(i) for i in range(arms)])
        design.update(experiment_id=identity, claim_id='C1', protocol='paired_case_mean')
        name = put(root, identity + '/design.json', design)
        registry.append(dict(id=identity, path=name, sha256=file_hash(root/name),
                             protocol='paired_case_mean', claim_ids=['C1']))
    return registry


def record(root, registry):
    rows = []
    for entry in registry:
        identity = entry['id']
        with ExperimentRecorder(root, design=entry['path'], results=identity+'/results.json',
                                raw_directory=identity+'/raw', design_id=identity) as recorder:
            for case, seed, arm in recorder.grid:
                with recorder.attempt(case, seed, arm) as complete:
                    complete(1 + seed + recorder.design['conditions'].index(arm), {'software_fixture': True})
        summary = put(root, identity+'/summary.md', 'SOFTWARE FIXTURE ONLY. Descriptive numbers, not scientific evidence.')
        rows.append(dict(design_id=identity, results=identity+'/results.json', summary=summary))
    return rows


def render(root, experiments, suffix="svg"):
    rows = []
    for entry in experiments:
        identity = entry['design_id']
        result = science.render_statistics(root, entry['results'], identity+'/table.tex', identity+'/figure.'+suffix)
        rows.append(dict(id='F-'+identity, design_id=identity, results=entry['results'],
                         statistics=result['statistics_path'], **{k:result[k] for k in ('table','figure','trace','caption')}))
    return rows


def paths(root):
    return [str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and '.paper' not in p.parts]


class MultiDesignTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_science.ScienceChecks(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.write, self.assertions = self.fixture.writing_packet()
        self.registry = designs(self.root)
        self.plan = {'experiment_designs':self.registry, 'artifacts':paths(self.root)}
        self.experiment = {'experiments':record(self.root,self.registry), '_plan':self.plan, 'artifacts':paths(self.root)}
        self.figures = {'evidence_sets':render(self.root,self.experiment['experiments']), '_plan':self.plan,
                        '_history':{'experiment':self.experiment}, 'artifacts':paths(self.root)}
        self.write['_plan']=self.plan
        self.write['_history'].update(plan=self.plan,experiment=self.experiment,figures=self.figures)
        self.write['artifacts']=paths(self.root)
        self.bind_assertions(self.write,self.assertions)

    def bind_assertions(self, writing, document):
        original = document['assertions'][0]
        records = []
        texts = []
        for row in self.figures['evidence_sets']:
            stats = science.strict_json(self.root,row['statistics'])
            text = row['design_id'] + ' software fixture mean was 1.500000 units.'
            records.append({**original,'id':'A-'+row['id'],'text':text,'design_id':row['design_id'],
                            'evidence_set_id':row['id'],'statistics':row['statistics'],
                            'measure':'conditions.arm0.mean','value':1.5,'unit':'units','denominator':3})
            texts.append(text)
        document['assertions']=records
        put(self.root,writing['assertions'],document)
        source=self.root/writing['manuscript']
        source.write_text(source.read_text()+'\n'+'\n'.join(texts))
        writing['section_packets'][0]['evidence']=[r['statistics'] for r in records]

    def assert_rejected(self, stage, packet, phrase):
        issues=science.validate(stage,packet,self.root)
        self.assertTrue(issues)
        self.assertIn(phrase,issues[0])

    def test_three_designs_validate_through_claims(self):
        for stage, packet in [('plan',self.plan),('experiment',self.experiment),('figures',self.figures),('write',self.write)]:
            self.assertEqual([],science.validate(stage,packet,self.root),stage)

    def test_registry_rejects_duplicate_missing_changed_or_unsupported_designs(self):
        for mutate, phrase in [
            (lambda p:p['experiment_designs'].append(p['experiment_designs'][0]),'duplicate design'),
            (lambda p:p['experiment_designs'][0].update(sha256='0'*64),'hash mismatch'),
            (lambda p:p['experiment_designs'][0].update(protocol='nested_checkpoint'),'unsupported scientific protocol'),
            (lambda p:p.update(experiment_design_sha256='0'*64),'mix legacy'),
            (lambda p:p['experiment_designs'][0].update(claim_ids=['other']),'claim identity')]:
            packet=copy.deepcopy(self.plan);mutate(packet);self.assert_rejected('plan',packet,phrase)
        packet=copy.deepcopy(self.experiment);packet['experiments'].pop()
        self.assert_rejected('experiment',packet,'omits registered')
        packet=copy.deepcopy(self.figures);packet['evidence_sets'].pop()
        self.assert_rejected('figures',packet,'omits registered')

    def test_cross_design_results_raw_and_duplicate_evidence_rejected(self):
        packet=copy.deepcopy(self.experiment);packet['experiments'][1]['results']=packet['experiments'][0]['results']
        self.assert_rejected('experiment',packet,'result design identity')
        results=science.strict_json(self.root,'D1/results.json')
        results['runs'][0]['raw']='D0/raw/a-arm0-0.json'
        put(self.root,'D1/results.json',results)
        self.assert_rejected('experiment',self.experiment,'cross-design evidence')
        # A copied foreign raw path still carries its originating design identity.
        put(self.root,'D1/raw/foreign.json',science.strict_json(self.root,'D0/raw/a-arm0-0.json'))
        results['runs'][0]['raw']='D1/raw/foreign.json';put(self.root,'D1/results.json',results)
        self.experiment['artifacts']=paths(self.root)
        self.assert_rejected('experiment',self.experiment,'raw design identity')

    def test_unaccepted_result_and_assertion_crossover_rejected(self):
        packet=copy.deepcopy(self.figures)
        put(self.root,'D0/alternate.json',science.strict_json(self.root,'D0/results.json'))
        packet['artifacts']=paths(self.root);packet['evidence_sets'][0]['results']='D0/alternate.json'
        self.assert_rejected('figures',packet,'accepted experiment results')
        self.assertions['assertions'][0]['evidence_set_id']='F-D1'
        put(self.root,self.write['assertions'],self.assertions)
        self.assert_rejected('write',self.write,'evidence/design identity')

    def test_legacy_mix_and_duplicate_figure_ids_rejected(self):
        packet=copy.deepcopy(self.experiment);packet['design']='D0/design.json'
        self.assert_rejected('experiment',packet,'mix legacy')
        packet=copy.deepcopy(self.figures);packet['evidence_sets'][1]['id']=packet['evidence_sets'][0]['id']
        self.assert_rejected('figures',packet,'duplicate evidence set')

    def test_plan_freeze_requires_empirical_design_and_rejects_alias_paths(self):
        self.assert_rejected('plan', {'_brief':{'paper_type':'original'}}, 'needs a frozen')
        packet=copy.deepcopy(self.plan)
        alias='D0/alias.json'
        (self.root/alias).symlink_to(self.root/'D0/design.json')
        packet['artifacts'].append(alias)
        packet['experiment_designs'][1].update(path=alias,sha256=packet['experiment_designs'][0]['sha256'])
        self.assert_rejected('plan',packet,'duplicate design')

    def test_accepted_tables_are_derived_sources_but_other_sections_need_ownership(self):
        source=self.root/self.write['manuscript']
        source.write_text(source.read_text()+'\n'+''.join('\\input{../'+row['table']+'}\n' for row in self.figures['evidence_sets']))
        self.assertEqual([],science.validate('write',self.write,self.root))
        put(self.root,'paper/unowned.tex','Unowned prose cannot impersonate a derived table.')
        source.write_text(source.read_text()+'\\input{unowned.tex}\n')
        self.write['artifacts']=paths(self.root)
        self.assert_rejected('write',self.write,'lack section packets')

    def test_unknown_explicit_protocol_rejected_by_state_free_tools(self):
        design=science.strict_json(self.root,'D0/design.json')
        design['protocol']='nested_checkpoint'
        put(self.root,'D0/design.json',design)
        with self.assertRaisesRegex(ValueError,'unsupported scientific protocol'):
            template({'design':'D0/design.json','target':'unknown.py'},self.root,Path(__file__).parents[1])
        with self.assertRaisesRegex(ValueError,'unsupported scientific protocol'):
            production.run('statistics',{'input':'D0/results.json','table':'unknown.tex','figure':'unknown.svg'},self.root)
        self.assertFalse((self.root/'unknown.py').exists())
        self.assertFalse((self.root/'unknown.svg').exists())

    def test_independent_template_paths_and_identity(self):
        template({'design':'D1/design.json','design_id':'D1','results':'new/results.json',
                  'raw_directory':'new/raw','target':'new/envelope.py'},self.root,Path(__file__).parents[1])
        source=(self.root/'new/envelope.py').read_text()
        self.assertIn("results='new/results.json'",source)
        self.assertIn("raw_directory='new/raw'",source)
        self.assertIn("design_id='D1'",source)


class MultiDesignControllerTests(unittest.TestCase):
    def test_actual_controller_freeze_experiment_figures_write(self):
        with tempfile.TemporaryDirectory(prefix='multi-design-software-fixture-') as temp:
            root=Path(temp)
            original_commit=Controller.commit
            def commit(ctl, packet, op):
                packet=copy.deepcopy(packet)
                if packet['stage']=='plan':
                    packet.pop('experiment_design_sha256')
                    packet['experiment_designs']=designs(root)
                    packet['artifacts'] += [entry['path'] for entry in packet['experiment_designs']]
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
            sentences=[row['design_id']+' software fixture mean was 1.500000 units.' for row in evidence]
            limitations=[{'kind':'scope','text':'Software fixture only, not scientific evidence.'},
                         {'kind':'small_sample','text':'Three independent software cases limit generalization.'},
                         {'kind':'adverse','text':'Adverse synthetic contrasts are retained.'}]
            text='\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\n'+'\n'.join(sentences+[r'Fixture source~\cite{fixture}.']+[x['text'] for x in limitations])+r'\begin{thebibliography}{1}\bibitem{fixture} Offline Fixture. Software fixture only.\end{thebibliography}\end{document}'
            visuals=(r'\begin{figure}[ht]\centering'+''.join(r'\includegraphics[width=.3\linewidth]{../'+row['figure']+'}' for row in evidence)+r'\caption{Paired software fixture errors.}\label{fig:F1}\end{figure}'+
                     r'\begin{table}[ht]\centering'+''.join(r'\resizebox{.3\linewidth}{!}{\input{../'+row['table']+'}}' for row in evidence)+r'\caption{Full-denominator fixture statistics.}\label{tab:T1}\end{table}')
            text=text.replace(r'\end{document}',visuals+r'\end{document}')
            tex=put(root,'multi/main.tex',text)
            ctl.execute('W-writing','compile-multi-writing')
            assertions=[]
            for row,sentence in zip(evidence,sentences):
                assertions.append(dict(id='A-'+row['id'],claim_id='C1',text=sentence,design_id=row['design_id'],evidence_set_id=row['id'],
                    statistics=row['statistics'],measure='conditions.arm0.mean',value=1.5,unit='units',denominator=3,
                    condition='all-planned-cases',strength='descriptive',kind='numeric'))
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
                expected.update(run['raw'] for run in science.strict_json(root,row['results'])['runs'])
            for row in evidence:
                expected.update(row[key] for key in ['statistics','table','figure','trace'])
            self.assertTrue(expected <= set(manifest['artifacts']))
            with zipfile.ZipFile(exported['archive']) as archive:
                for name in expected:
                    self.assertEqual((root/name).read_bytes(),archive.read('artifacts/'+name),name)
            self.assertEqual(8,len(ctl.load()['receipts']))


if __name__=='__main__':
    unittest.main()
