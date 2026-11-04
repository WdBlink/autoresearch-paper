#!/usr/bin/env python3
"""Translate actual native R2 reviews into the controller's strict contract.

No scientific verdict is generated here. Both real reviewers must have passed;
every independently checked binding and current byte hash must agree first.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys

from control import invoke, put


def load(root, name):
    return json.loads((root/name).read_text())


def sha(root, name):
    return hashlib.sha256((root/name).read_bytes()).hexdigest()


def main(root):
    context=load(root,'control/context-review-r2.json')
    artifact=load(root,'review/artifact-review-r2.json')
    methods=load(root,'review/methods-manuscript-r2.json')
    assert context['stage']=='review' and len(context['bindings'])==9
    assert artifact['pass'] is True and artifact['open_major_count']==artifact['open_minor_count']==0
    assert methods['verdict']=='pass' and methods['issue_counts']=={'major':0,'minor':0}
    checks=[]
    for check in artifact['requirement_checks']:
        binding=context['bindings'][check['requirement_id']]
        assert check['verdict']=='fulfilled' and not check['hash_mismatches']
        assert check['binding_sha256']==binding['binding_sha256']
        assert check['verified_current_hashes']==binding['hashes']
        assert all(sha(root,p)==h for p,h in binding['hashes'].items())
        checks.append({'requirement_id':check['requirement_id'],'binding_sha256':check['binding_sha256'],
            'evidence_hashes':check['verified_current_hashes'],'verdict':check['verdict'],'rationale':check['reason']})
    assert {c['requirement_id'] for c in checks}==set(context['bindings'])
    gates={}
    for key,gate in artifact['gates'].items():
        assert gate['verdict']=='pass' and gate['pass'] is True
        gates[key]={'verdict':gate['verdict'],'reason':gate['reason'],
            'evidence':['review/artifact-review-r2.json','review/methods-manuscript-r2.json']}
    assert set(gates)=={'G1','G2','G3','G4','G5','R6'}
    write=load(root,'write/packet-r2.json')
    assert sha(root,write['manuscript_pdf'])==artifact['pdf_sha256']
    r6=[]
    for item in artifact['R6']['items']:
        assert item['verdict']=='fulfilled'
        r6.append({'id':item['id'],'verdict':item['verdict'],'reason':item['reason'],
            'evidence_locations':[write['manuscript_pdf']+' pages '+','.join(map(str,item['actual_location']['reading_pages'])),
                'review/artifact-review-r2.json#R6.items.'+item['id']]})
    historical_reports=[]
    for stem in ['methods-prerun','methods-prerun-r1','methods-results-r0',
                 'methods-manuscript-r0','methods-manuscript-r1','methods-manuscript-r2',
                 'artifact-review-r0','artifact-review-r1','artifact-review-r2']:
        for suffix in ['md','json']:
            name=f'review/{stem}.{suffix}'
            assert (root/name).is_file()
            historical_reports.append(name)
    literature=load(root,'literature/packet-r1.json')
    completion={'source':[write['manuscript'],write['submission_variant']['source'],
            'figures/datasets.tex','figures/case-results.tex','figures/macro-display.tex'],
        'pdf':[write['manuscript_pdf'],write['submission_variant']['pdf']],
        **{key:[literature[key]] for key in ['bibliography','citation_plan','citation_verification']},
        'review':historical_reports,
        'revision':['review/source-reading-revision.json','review/revision-r1.json','review/revision-r2.json'],
        'snapshot':['review/version-snapshot-r2.json']}
    artifacts=list(dict.fromkeys(p for role,paths in completion.items() for p in paths if role!='snapshot'))
    artifacts += ['plan/figure_table_plan.json','plan/snapshot.json','review/r6-mechanical-r2.json',
        'verification/engineering-checks.json','breakpoints.jsonl','venue/analysis/INDEX.md',
        'manuscript/main.pdf','manuscript/submission.pdf','manuscript/main-r1.pdf','manuscript/submission-r1.pdf',
        'manuscript/main.tex','manuscript/submission.tex','manuscript/main-r1.tex','manuscript/submission-r1.tex',
        'manuscript/references.bib','venue/analysis/revisions/S01-r0.json','venue/analysis/revisions/S01-r0.md',
        'control/context-review-r2.json','experiment/design.json','experiment/results.json',
        'figures/macro.tex.stats.json','figures/journal/export-manifest.json']
    for name in ['review_packet.py','deliver.py','index.py']:
        target='software/'+name
        shutil.copyfile(Path(__file__).parent/name,root/target)
        artifacts.append(target)
    audit={'figure_table_plan':'plan/figure_table_plan.json','plan_snapshot':'plan/snapshot.json',
        'manuscript_pdf':write['manuscript_pdf'],'artifacts':['plan/figure_table_plan.json','plan/snapshot.json',write['manuscript_pdf']]}
    put(root,'review/r6-audit-input-r2.json',audit)
    value=invoke(root,'tool','--name','plan-audit','--packet','review/r6-audit-input-r2.json','--out','review/r6-mechanical-r2.json')['value']
    assert all(x['verdict']=='fulfilled' for x in value['original_items']) and not value['rewrites']
    assert value['realize']['status']=='pass'
    artifacts=list(dict.fromkeys(artifacts))
    put(root,'review/version-snapshot-r2.json',{'files':{p:sha(root,p) for p in artifacts},
        'scope':'Current completion roles, preserved baselines and actual review/evidence files. Prior invalidated versions remain explicitly historical.'})
    artifacts += completion['snapshot']
    packet={'stage':'review','producer':'artifact-reviewer','reviewer':'artifact-reviewer',
        'artifacts':artifacts,'manuscript_pdf':write['manuscript_pdf'],
        'figure_table_plan':'plan/figure_table_plan.json','plan_snapshot':'plan/snapshot.json',
        'requirement_checks':checks,'gates':gates,'r6_reviews':r6,'completion':completion,
        'review_bridge':{'source':'Actual native separate-context artifact/methods R2 reviews',
            'adapter':'software/review_packet.py','verdicts_invented':False,'human_or_cross_model_review':False}}
    put(root,'review/packet-r2.json',packet)
    print('Prepared actual passed reviews: 9 requirements, 6 original visuals, 8 completion roles; no stage committed yet.')


if __name__=='__main__': main(Path(sys.argv[1]).resolve())
