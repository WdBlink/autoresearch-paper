#!/usr/bin/env python3
"""Build evidence-bearing packets for this real study, through the public CLI."""
import argparse
import hashlib
import json
from pathlib import Path

from control import invoke, put


def sha(root, name):
    return hashlib.sha256((root/name).read_bytes()).hexdigest()


def source(root, name, url, quote=None):
    return {'path':name,'url':url,'sha256':sha(root,name), **({'quote':quote} if quote else {})}


def intake(root):
    datasets=json.loads((root/'data/manifest.json').read_text())['datasets']
    if len(datasets)!=8: raise ValueError('The eight actual datasets must be available before feasible intake')
    materials=[]; evidence=[]
    for index,name in enumerate(('materials/request.md','materials/proposal.md','materials/environment.json'),1):
        read=invoke(root,'read-material','--path',name)
        text=(root/name).read_text()
        if read['text']!=text: raise ValueError('Material was not fully returned')
        material={'id':f'M{index}','path':name,'sha256':sha(root,name),'availability':'readable','read_spans':[[0,len(text)]]}
        materials.append(material); evidence.append({'material_id':material['id'],'start':0,'end':len(text),'quote':text})
    packet={'stage':'intake','producer':'research-author','artifacts':[m['path'] for m in materials]+['data/manifest.json'],
        'materials':materials,'evidence':evidence,'feasibility':{'status':'feasible','selected_option':'bounded-pipeline-study','options':[
            {'id':'bounded-pipeline-study','implementation':'Two fixed pipelines; eight accessible public datasets; five paired seeds; local CPU',
             'selection_reason':'Tests a bounded implementation-order question with finite reproducible fits','evidence':[evidence[1],evidence[2]]},
            {'id':'clinical-prediction','implementation':'Disease-specific clinical modeling','selection_reason':'Would require unavailable domain validation and change the question','evidence':[evidence[1]]},
            {'id':'broad-imputer-search','implementation':'Tune many imputers and learners','selection_reason':'Would add model-selection effects and exceed the bounded question','evidence':[evidence[1]]}],
        'resources':{'authorization':'Current user delegates the complete small real study; public data and local CPU only',
                     'cost_basis':'scikit-learn 1.9.1 installed in an isolated environment; eight actual UCI datasets downloaded and schema-checked; no paid endpoint'},
        'experiments':[{'claim':'C1','metric':'held-out balanced accuracy, percentage points','comparison':'train-fitted standardization before versus after kNN imputation',
                        'protocol':'20% MCAR; 70/30 stratification; five fixed paired seeds; all transforms fit training rows only',
                        'completion':'All 80 planned dataset × seed × pipeline attempts retained',
                        'failure_route':'Operational failures block advancement; preserve actual measurement failures and no best-seed selection'}]}}
    put(root,'intake/packet.json',packet)
    return invoke(root,'commit','--packet',root/'intake/packet.json','--operation-id','intake-real-materials')


def venue_skeleton(root):
    brief=json.loads((root/'brief-draft.json').read_text())
    rules='materials/sources/plos-guidelines.txt'
    selection={'mode':'candidate_comparison','selected_id':'PLOS','criteria':['research-scope fit','article-type and claim scale','actual recent comparator articles','official reporting and source access'],
      'rationale':'PLOS ONE explicitly considers rigorous original/replication and null-result studies. Eight recent actual imputation-comparison papers are available. This is a bounded empirical note, without the broad methodological novelty expected by JMLR.',
      'candidates':[
        {'id':'PLOS','venue':'PLOS ONE','kind':'journal','scope_fit':'Computational comparison of tabular missing-data pipelines, including negative/null outcomes',
         'article_type_fit':'Original empirical replication-style methods note; not a review or clinical validation claim',
         'constraints':'Technical validity, reproducibility, appropriate conclusions and data availability; LaTeX submission excludes embedded figure graphics',
         'cost':{'status':'unknown','basis':'No publication transaction is authorized; a current fee schedule was not established in this study'},
         'timing':{'status':'unknown','basis':'No editorial turnaround promise obtained'},
         'advantages':['Eight directly relevant recent published comparator studies with open PDFs/JATS','Official criteria include negative and null results'],
         'limitations':['Eight-dataset one-rate/one-learner study has limited scope and no novelty guarantee','Clinical comparator applications do not establish clinical relevance of this general benchmark'],
         'evidence':[source(root,'materials/sources/plos-criteria.txt','https://journals.plos.org/plosone/s/criteria-for-publication','we consider negative and null results.')]},
        {'id':'JMLR','venue':'Journal of Machine Learning Research','kind':'journal','scope_fit':'Machine-learning methods are in scope, but the present small practical comparison has narrow intended insight',
         'article_type_fit':'An empirical study would require a substantial broader methodological contribution',
         'constraints':'Novel insight and broad learning-method audience; not chosen for this bounded comparison',
         'cost':{'status':'known','basis':'Official author information states no publication fees'},
         'timing':{'status':'unknown','basis':'No specific editorial schedule applies'},
         'advantages':['Direct machine-learning methods audience','No publication fees in official author information'],
         'limitations':['The current pilot does not establish the level of broadly relevant new methodological insight sought'],
         'evidence':[source(root,'materials/sources/jmlr-scope.txt','https://www.jmlr.org/author-info.html','experimental and/or theoretical studies yielding new insight into the design'),
                     source(root,'materials/sources/jmlr-scope.txt','https://www.jmlr.org/author-info.html','There are no publication fees associated with this journal')]}]}
    catalog=json.loads((root/'venue/sample-catalog.json').read_text())
    samples=[]
    for record in catalog:
        key=record['id']
        samples.append({'id':key,'pdf':f'venue/samples/{key}/article.pdf','venue_label':'PLOS ONE','year':int(record['publication_date'][:4]),
                        'publication_date':record['publication_date'],
                        'acceptance_evidence':source(root,f'venue/samples/{key}/acceptance.txt',record['url']),
                        'direction_match':'Original computational missing-data method/evaluation: '+record['title'],
                        'comparability_limit':'Comparator provides imputation evaluation/visual-design practice; its clinical, regression or multi-method conclusions are not transferred to our classifier pipelines.'})
    items=[
      {'id':'F1','kind':'figure','type':'method_overview','question':'Which operations are trained on which rows in each compared pipeline?','claim':'C1: the two pipelines share splits, masks and learner; only transform order changes','data':'experiment/design.json and experiment/evaluator.py','section':'Methods','priority':'must'},
      {'id':'F2','kind':'figure','type':'quantitative_results','question':'How does held-out balanced accuracy change in each dataset and paired seed?','claim':'C1: performance differences are heterogeneous within the fixed dataset set','data':'experiment/results.json','section':'Results','priority':'must'},
      {'id':'F3','kind':'figure','type':'quantitative_results','question':'What is the descriptive distribution of dataset-level mean accuracies?','claim':'C1: macro summaries describe these eight dataset-level observations','data':'experiment/results.json','section':'Results','priority':'must'},
      {'id':'T1','kind':'table','type':'dataset_statistics','question':'Which real datasets and class/feature/sample dimensions define the comparison?','claim':'C1: the evaluation covers eight explicitly enumerated datasets','data':'data/manifest.json','section':'Methods','priority':'must'},
      {'id':'T2','kind':'table','type':'main_results','question':'What are the two pipeline means, repeat SDs and paired changes per dataset?','claim':'C1: all dataset-specific paired outcomes are retained','data':'experiment/results.json','section':'Results','priority':'must'},
      {'id':'T3','kind':'table','type':'main_results','question':'What are the equal-dataset-weight descriptive means and between-dataset SDs?','claim':'C1: the summary uses eight cases, not forty independent seeds','data':'experiment/results.json','section':'Results','priority':'must'}]
    deviation='This is a deliberately bounded two-pipeline comparison on eight small fixed datasets at one missing rate. Three figures and three tables cover methods, full paired outcomes and descriptive summaries; the broader multi-imputer/clinical simulation papers legitimately have more visuals. Additional plots would duplicate evidence or require unplanned experiments.'
    put(root,'plan/figure_table_plan.json',{'items':items,'deviation_reason':deviation})
    fields=['venue/measurements.json','venue/profile.json','venue/plan-check.json','venue/comparison.json']
    artifacts=[rules,'materials/sources/plos-criteria.txt','materials/sources/jmlr-scope.txt','venue/template/plos_latex_template.tex',
               'venue/template/plos2025.bst','venue/official-template.zip','plan/figure_table_plan.json',*fields]
    for s in samples: artifacts += [s['pdf'],s['acceptance_evidence']['path']]
    packet={'stage':'venue','producer':'research-author','venue':'PLOS ONE','direction':brief['direction'],'paper_type':brief['paper_type'],
            'artifacts':artifacts,'official_rules':{**source(root,rules,'https://journals.plos.org/plosone/s/submission-guidelines'),'basis':'official_requirement'},
            'template':{**source(root,'venue/template/plos_latex_template.tex','https://journals.plos.org/plosone/s/file?id=1457/PLOS_latex_template.zip'),'status':'available'},
            'venue_selection':selection,'samples':samples,'sampling_policy':{'kind':'journal','as_of':'2026-11-04',
              'measurement_warning_review':'Actual PDF counts match publisher JATS (53 figures, 54 tables). Page locators/caption boundaries and unlettered/capital-letter panels are heuristic; rendered-page records preserve all corrections. References-heading body-page counts are inclusive heuristics, never a journal limit.'},
            'page_budget':{'target':None,'limit_type':'unlimited','basis':'official_requirement','includes_references':True,'includes_appendix':True,
                'source':source(root,rules,'https://journals.plos.org/plosone/s/submission-guidelines','Manuscripts can be any length.'),
                'reason':'The current official rule has no word/figure/supporting-information quantity cap. Measured accepted-paper lengths are descriptive, not a required minimum.'},
            'figure_table_plan':'plan/figure_table_plan.json','measurements':fields[0],'venue_profile':fields[1],'venue_plan_check':fields[2],'venue_comparison':fields[3]}
    put(root,'venue/packet-draft.json',packet)
    return {'status':'venue_skeleton','samples':len(samples),'planned_visuals':len(items)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True);parser.add_argument('phase',choices=['intake','venue-skeleton'])
    args=parser.parse_args();root=args.run.resolve()
    print(json.dumps(intake(root) if args.phase=='intake' else venue_skeleton(root),ensure_ascii=False,indent=2))
