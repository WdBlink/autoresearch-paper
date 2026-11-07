#!/usr/bin/env python3
"""Materialize the actually read source identities and bounded citation claims."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

from control import put, invoke


def sha(root,name):
    return hashlib.sha256((root/name).read_bytes()).hexdigest()


def main(root):
    now=datetime.now(timezone.utc).isoformat(); candidates=[];plan=[];checks=[];bib=[];artifacts=[]
    def add(key,identity,url,path,span,claim,taxonomy,depth,identity_evidence,published_at,date_basis):
        candidate_id='L-'+key;claim_id='LC-'+key
        candidates.append({'id':candidate_id,'title':identity['title'],'url':url,'published_at':published_at,
            'publication_date_basis':date_basis,'exposure':'prospective','purpose':claim,'decision':'include','read_status':'read',
            'read_path':path,'verification':{'status':'primary_checked','evidence':identity_evidence[0]},'evidence_spans':[{'path':path,'quote':span}]})
        record={'key':key,'candidate_id':candidate_id,**identity,'url':url,'taxonomy_cell':taxonomy,'depth':depth,'status':'verified',
                'claims':[{'id':claim_id,'text':claim,'evidence_spans':[{'path':path,'quote':span}]}], 'year_basis':date_basis}
        plan.append(record)
        checks.append({'key':key,'status':'verified','checked_at':now,'identity':identity,'source_sha256':sha(root,path),
                       'evidence':identity_evidence,'claim_checks':[{'claim_id':claim_id,'status':'supported','evidence_spans':[{'path':path,'quote':span}]}]})
        kind='article' if taxonomy in ('imputation-evaluation','software') else 'misc'
        entry='@'+kind+'{'+key+',\n'
        fields={'title':identity['title'],'author':' and '.join(identity['authors']),'year':str(identity['year']),
                'journal' if kind=='article' else 'howpublished':identity['venue'],'url':url}
        if identity['identifier'].startswith('10.'):fields['doi']=identity['identifier']
        if date_basis.startswith('source year only'):fields['note']='Citation year is supplied by the source. Exact publication day is not asserted; temporal validation uses a conservative year-end bound.'
        for name,value in fields.items():entry+='  '+name+' = {'+value+'},\n'
        bib.append(entry+'}\n');artifacts.extend([path,*identity_evidence])
    papers=json.loads((root/'venue/sample-catalog.json').read_text())
    paper_claims=[
        'The source proposes Layered Stacking to estimate continuous missing values and evaluates imputation errors.',
        'The source compares imputation methods across MCAR, MAR and MNAR conditions; its reported results are not reproduced here.',
        'The source investigates how missing-data processing affects infectious-disease prediction pipelines.',
        'The source proposes an adaptive SVR/decision-tree imputation-and-classification framework.',
        'The source evaluates imputation and feature selection in a clinical classification application.',
        'The source evaluates random-forest-based imputation strategies in heterogeneous multi-site tabular data.',
        'The source adapts imputation models for use on new observations in prediction settings.',
        'The source compares MICE subroutines for statistical estimation, a target distinct from our downstream prediction score.'
    ]
    for item,claim in zip(papers,paper_claims):
        key=item['id'].lower();path=f"venue/samples/{item['id']}/article.txt";parts=(root/path).read_text().split('\n\n');abstract=parts[6]
        identity={'title':item['title'],'authors':item['authors'],'year':int(item['publication_date'][:4]),'venue':item['journal'],'identifier':item['doi']}
        add(key,identity,item['url'],path,abstract,claim,'imputation-evaluation','B',[f"venue/samples/{item['id']}/metadata.json",path],item['publication_date']+'T23:59:59Z','publisher calendar date; UTC day-end is a conservative bound, not an observed publication time')
    for item in json.loads((root/'data/manifest.json').read_text())['datasets']:
        case=item['case_id'];path=f'data/{case}/page.txt';text=(root/path).read_text();citation=text[text.rfind('Citation\n')+9:].split('\nStyle:',1)[0]
        year=int(re.search(r'\((\d{4})\)',citation).group(1));metadata=f'data/{case}/metadata.json';m=json.loads((root/metadata).read_text())['data']
        identity={'title':m['name'],'authors':m['creators'],'year':year,'venue':'UCI Machine Learning Repository','identifier':m['dataset_doi']}
        add('uci_'+case,identity,m['repository_url'],path,citation,
            m['name']+' is attributed through its official UCI dataset identity and DOI.','data-source','C',[path,metadata],f'{year}-12-31T23:59:59Z',
            'source year only; conservative year-end upper-bound encoding for the version-1 controller, not a claim of a known month/day')
    path='literature/sklearn-paper/source.txt';text=(root/path).read_text();lines=text.splitlines()
    author_line=next(line for line in lines if line.startswith('Fabian Pedregosa,'));authors=author_line.split(', ')
    abstract=text[text.index('Abstract\n')+9:text.index('\n[abs]')]
    identity={'title':'Scikit-learn: Machine Learning in Python','authors':authors,'year':2011,'venue':'JMLR','identifier':'12(85):2825−2830'}
    add('sklearn2011',identity,'https://www.jmlr.org/papers/v12/pedregosa11a.html',path,abstract,
        'Scikit-learn provides a Python interface to supervised and unsupervised machine-learning algorithms.','software','C',[path,'literature/sklearn-paper/source.html'],
        '2011-12-31T23:59:59Z','source year only; conservative year-end upper-bound encoding, not an asserted publication day')
    raw_search=json.loads((root/'venue/search-response.json').read_text());negative=next(d for d in raw_search['response']['response']['docs'] if d['id'].endswith('0350666'))
    candidates.append({'id':'H-time-series','title':negative['title'],'url':'https://journals.plos.org/plosone/article?id='+negative['id'],
        'published_at':negative['publication_date'],'exposure':'prospective','purpose':'A keyword-near but temporally structured imputation application',
        'decision':'exclude','exclusion_reason':'The registered title concerns time-series periodic structure; it is not a primary comparator for the present fixed row-split numeric classification question. This exclusion does not judge its scientific quality.', 'read_status':'registered'})
    # Source years are known for datasets/JMLR, while exact days are not. Their
    # upper bounds preserve conservative pre-question availability checks.
    question=json.loads((root/'control/init.json').read_text())['brief']
    created=json.loads((root/'.paper/control.json').read_text())['created_at']
    catalog={'question_formed_at':created,'question_time_basis':'Earliest controller-persisted Brief, not a claim about first cognitive formation',
        'searches':[{'query':raw_search['query'],'method':'keyword','result_ids':['L-'+p['id'].lower() for p in papers]+['H-time-series']},
                    {'query':'Named UCI numeric classification dataset provenance and official dataset citation','method':'direct_metadata_lookup','result_ids':['L-uci_'+d['case_id'] for d in json.loads((root/'data/manifest.json').read_text())['datasets']]},
                    {'query':'Scikit-learn: Machine Learning in Python official JMLR record','method':'direct_publisher_lookup','result_ids':['L-sklearn2011']}],
        'naive_baseline_ids':['L-s07'],'hard_negative_ids':['H-time-series'],'candidates':candidates,
        'coverage_limit':'Targeted corpus anchored to the selected venue, public dataset identities and implementation citation; not a systematic review or proof of novelty.'}
    put(root,'literature/catalog.json',catalog);put(root,'manuscript/references.bib','\n'.join(bib))
    put(root,'literature/citation-plan.jsonl','\n'.join(json.dumps(row,ensure_ascii=False) for row in plan)+'\n')
    put(root,'literature/citation-verification.json',{'records':checks,'batches':[], 'batch_note':'17 actual references: no full twenty-reference block, all final tail items individually verified.'})
    artifacts=list(dict.fromkeys([*artifacts,'literature/catalog.json','manuscript/references.bib','literature/citation-plan.jsonl','literature/citation-verification.json','venue/search-response.json']))
    packet={'stage':'literature','producer':'research-author','artifacts':artifacts,'catalog':'literature/catalog.json','bibliography':'manuscript/references.bib',
            'citation_plan':'literature/citation-plan.jsonl','citation_verification':'literature/citation-verification.json'}
    put(root,'literature/packet.json',packet)
    check=invoke(root,'tool','--name','citation-check','--packet',root/'literature/packet.json')
    print(json.dumps(check['value'],ensure_ascii=False))
    if check['value']['status']!='pass':raise ValueError('Resolve actual citation integrity failure before commit')
    print(invoke(root,'commit','--packet',root/'literature/packet.json','--operation-id','accept-real-source-citations')['status'])
    print('Actual verified references:',len(plan))


if __name__=='__main__': main(Path(sys.argv[1]).resolve())
