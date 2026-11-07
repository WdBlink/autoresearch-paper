#!/usr/bin/env python3
"""Frozen two-pipeline experiment on real UCI data; no tuning or remote models."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import warnings

import numpy as np
import pandas as pd
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import KNNImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists(): raise ValueError('Output already exists; preserve historical evidence: '+str(path))
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def scorer(y, prediction):
    labels=np.unique(y)
    matrix=confusion_matrix(y,prediction,labels=labels)
    value=float(np.mean(np.diag(matrix)/matrix.sum(axis=1)))
    reference=float(balanced_accuracy_score(y,prediction))
    if not np.isclose(value,reference,atol=1e-12,rtol=0): raise ValueError('Independent scorer disagreement')
    return value*100, labels, matrix


def model(condition):
    scaler=('scale',StandardScaler())
    imputer=('impute',KNNImputer(n_neighbors=5,weights='uniform',metric='nan_euclidean',keep_empty_features=True))
    learner=('classifier',LogisticRegression(C=1.0,solver='lbfgs',max_iter=2000,tol=1e-4))
    return Pipeline([imputer,scaler,learner] if condition=='baseline' else [scaler,imputer,learner])


def controls(root):
    y=np.array([0,0,0,1]);pred=np.array([0,0,1,1])
    value,_,_=scorer(y,pred)
    if not np.isclose(value,100*5/6): raise ValueError('Known balanced-accuracy example failed')
    constant,_,_=scorer(y,np.zeros(4,dtype=int))
    if constant!=50: raise ValueError('Class imbalance was not corrected')
    train=np.array([[0.,0.,0.],[1000.,10.,10.],[1100.,0.,20.]])
    test=np.array([[900.,0.,np.nan]])
    raw=float(KNNImputer(n_neighbors=1).fit(train).transform(test)[0,2])
    scaler=StandardScaler().fit(train);before=scaler.mean_.copy()
    z=KNNImputer(n_neighbors=1).fit(scaler.transform(train)).transform(scaler.transform(test))
    scaled=float(scaler.inverse_transform(z)[0,2])
    if raw!=10 or not np.isclose(scaled,20) or not np.array_equal(before,scaler.mean_):
        raise ValueError('Known scale-sensitive neighbor / train-only transform control failed')
    result={'kind':'synthetic_instrument_controls_not_research_outcomes','checked_at':now(),
            'balanced_accuracy_expected':100*5/6,'balanced_accuracy_observed':value,
            'majority_predictor_balanced_accuracy_expected':50,'majority_predictor_observed':constant,
            'scale_sensitive_neighbor_expected':[10,20],'scale_sensitive_neighbor_observed':[raw,scaled],
            'test_transform_did_not_refit_scaler':True,'sklearn':sklearn.__version__}
    dump(root/'experiment/controls.json',result)
    return result



def failure_records(root, design, rows, progress, started, error):
    completed = {(r['case_id'],r['seed'],r['condition']) for r in rows}
    active = progress.get('active')
    message = type(error).__name__ + ': ' + str(error)
    for case in design['cases']:
        for seed in design['seeds']:
            for condition in design['conditions']:
                if (case,seed,condition) in completed:
                    continue
                identity = {'case_id':case,'seed':seed,'condition':condition}
                attempted = active is not None and all(active[k] == v for k,v in identity.items())
                status = 'failed' if attempted else 'stopped'
                reason = message if attempted else 'Not started: execution stopped after an operational failure; no score was measured.'
                raw = f'experiment/raw/{case}-{condition}-{seed}.json'
                record = {**identity,'status':status,'value':None,'attempted':attempted,'failure_kind':'operation','reason':reason,
                          'started_at':active['started_at'] if attempted else None,'finished_at':now()}
                dump(root/raw,record)
                rows.append({**identity,'id':f'{case}-{condition}-{seed}','raw':raw,
                             'status':status,'value':None,'attempted':attempted,'failure_kind':'operation','reason':reason})
    attempted_count = sum(r['status']=='completed' or r.get('attempted',False) for r in rows)
    dump(root/'experiment/results.json',{'design':'experiment/design.json','design_sha256':sha(root/'experiment/design.json'),
         'started_at':started,'finished_at':now(),'outcome':'inconclusive','execution_status':'failed',
         'reported_denominator':len(rows),'attempted_count':attempted_count,'runs':rows})
    dump(root/'experiment/execution-finish.json',{'started_at':started,'finished_at':now(),'status':'failed',
         'error':message,'planned_slots':len(rows),'attempted_count':attempted_count,
         'completed_count':sum(r['status']=='completed' for r in rows),
         'scientific_penalty_applied':False,'next_action':'Blocked. Investigate and preserve this run before a new version; never treat operation failures as zero-valued measurements.'})

def run(root):
    design_path=root/'experiment/design.json'; design=json.loads(design_path.read_text())
    if design['evaluator']['sha256']!=sha(Path(__file__).resolve()): raise ValueError('Frozen evaluator changed')
    manifest_path=root/'data/manifest.json';manifest=json.loads(manifest_path.read_text())
    if sha(manifest_path)!=design['dataset_manifest_sha256']: raise ValueError('Frozen dataset manifest changed')
    for name,version in {'sklearn':sklearn.__version__,'numpy':np.__version__,'pandas':pd.__version__}.items():
        if version!=design['implementation'][name]: raise ValueError('Wrong dependency version: '+name)
    if (root/'experiment/results.json').exists(): raise ValueError('Preserve the completed run; use another output root for replication')
    started=now();rows=[];pairs=[];progress={'active':None}
    dump(root/'experiment/execution-start.json',{'started_at':started,'design_sha256':sha(design_path),'evaluator_sha256':sha(Path(__file__).resolve()),'status':'started'})
    try:
        with threadpool_limits(limits=1):
            for case_index,case in enumerate(design['cases']):
                item=next(d for d in manifest['datasets'] if d['case_id']==case)
                csv=root/item['csv']
                if sha(csv)!=item['csv_sha256']: raise ValueError('Dataset changed: '+case)
                frame=pd.read_csv(csv);X=frame[item['features']].to_numpy(dtype=float);y=frame[item['target']].astype(str).to_numpy()
                if not np.isfinite(X).all(): raise ValueError('Unexpected original missing values')
                for seed_index,seed in enumerate(design['seeds']):
                    train_rows,test_rows=train_test_split(np.arange(len(y)),test_size=.30,stratify=y,random_state=seed)
                    if set(train_rows)&set(test_rows): raise ValueError('Train/test overlap')
                    generator=np.random.default_rng(np.random.SeedSequence([seed,case_index+1,20261104]))
                    train_mask=generator.random((len(train_rows),X.shape[1]))<.20
                    test_mask=generator.random((len(test_rows),X.shape[1]))<.20
                    train=X[train_rows].copy();test=X[test_rows].copy();train[train_mask]=np.nan;test[test_mask]=np.nan
                    pair_name=f'experiment/pairs/{case}-{seed}.npz';pair=root/pair_name;pair.parent.mkdir(parents=True,exist_ok=True)
                    if pair.exists(): raise ValueError('Pair output exists without a final result; reconcile before rerunning')
                    np.savez_compressed(pair,train_rows=train_rows,test_rows=test_rows,train_mask=train_mask,test_mask=test_mask)
                    pairs.append({'case_id':case,'seed':seed,'path':pair_name,'sha256':sha(pair)})
                    sequence=design['conditions'] if (case_index+seed_index)%2==0 else list(reversed(design['conditions']))
                    for condition in sequence:
                        key=f'{case}-{condition}-{seed}'; start=now();clock=time.perf_counter()
                        progress['active']={'case_id':case,'seed':seed,'condition':condition,'started_at':start}
                        pipeline=model(condition)
                        with warnings.catch_warnings(record=True) as recorded:
                            warnings.simplefilter('always')
                            pipeline.fit(train,y[train_rows]);prediction=pipeline.predict(test)
                        if any(issubclass(w.category,ConvergenceWarning) for w in recorded):
                            raise ValueError('Learner did not converge; preserve this operation and investigate: '+key)
                        value,labels,matrix=scorer(y[test_rows],prediction)
                        predictions=f'experiment/predictions/{key}.csv';path=root/predictions;path.parent.mkdir(parents=True,exist_ok=True)
                        if path.exists(): raise ValueError('Prediction output exists: '+key)
                        pd.DataFrame({'row':test_rows,'truth':y[test_rows],'prediction':prediction}).to_csv(path,index=False)
                        record={'case_id':case,'seed':seed,'condition':condition,'status':'completed','value':value,
                                'started_at':start,'finished_at':now(),'elapsed_seconds':time.perf_counter()-clock,
                                'metric':'balanced_accuracy','unit':'percentage points','predictions':predictions,'predictions_sha256':sha(path),
                                'labels':labels.tolist(),'confusion_matrix':matrix.tolist(),'pair':pair_name,'pair_sha256':sha(pair),
                                'train_rows':len(train_rows),'test_rows':len(test_rows),'train_missing_entries':int(train_mask.sum()),
                                'test_missing_entries':int(test_mask.sum()),'test_rows_all_features_missing':int(test_mask.all(axis=1).sum()),
                                'transform_order':[name for name,_ in pipeline.steps],'training_only_scaler_mean':pipeline.named_steps['scale'].mean_.tolist(),
                                'warnings':[str(w.message) for w in recorded]}
                        raw=f'experiment/raw/{key}.json';dump(root/raw,record)
                        rows.append({'id':key,'case_id':case,'seed':seed,'condition':condition,'status':'completed','value':value,'raw':raw})
                        progress['active']=None
                        print(key,f'{value:.6f}',flush=True)
    except Exception as error:
        failure_records(root,design,rows,progress,started,error)
        raise
    means={condition:np.mean([row['value'] for row in rows if row['condition']==condition]) for condition in design['conditions']}
    delta=means['candidate']-means['baseline']
    outcome='positive' if delta>0 else 'negative' if delta<0 else 'inconclusive'
    result={'design':'experiment/design.json','design_sha256':sha(design_path),'started_at':started,'finished_at':now(),
            'outcome':outcome,'reported_denominator':len(rows),'runs':rows}
    dump(root/'experiment/results.json',result);dump(root/'experiment/pair-manifest.json',{'pairs':pairs})
    dump(root/'experiment/execution-finish.json',{'started_at':started,'finished_at':now(),'status':'completed','attempts':len(rows),'dataset_cases':len(design['cases']),'model_calls':'80 local classifier fits; no remote or paid endpoint'})
    return {'attempts':len(rows),'outcome':outcome,'macro_delta_percentage_points':float(delta)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True);parser.add_argument('--controls-only',action='store_true')
    args=parser.parse_args();print(json.dumps(controls(args.run.resolve()) if args.controls_only else run(args.run.resolve()),indent=2))
