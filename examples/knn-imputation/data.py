#!/usr/bin/env python3
"""Download the eight named real datasets from their UCI metadata/data endpoints."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
import requests


DATASETS = [('iris',53), ('wine',109), ('wdbc',17), ('ionosphere',52),
            ('sonar',151), ('glass',42), ('seeds',236), ('banknote',267)]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(root, case):
    record = json.loads((root/'data/manifest.json').read_text())['datasets']
    item = next(row for row in record if row['case_id'] == case)
    frame = pd.read_csv(root/item['csv'])
    return frame[item['features']].to_numpy(dtype=float), frame[item['target']].astype(str).to_numpy(), item


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--run',type=Path,required=True)
    root=parser.parse_args().run.resolve(); records=[]
    for case,identifier in DATASETS:
        folder=root/'data'/case; folder.mkdir(parents=True,exist_ok=True)
        url=f'https://archive.ics.uci.edu/api/dataset?id={identifier}'
        metadata_path=folder/'metadata.json'
        if not metadata_path.exists():
            response=requests.get(url,timeout=45);response.raise_for_status();metadata_path.write_bytes(response.content)
        meta=json.loads(metadata_path.read_text())['data']
        targets=meta['target_col']
        features=[v['name'] for v in meta['variables'] if v['role']=='Feature']
        if case == 'seeds':
            # UCI's summary currently has no target/feature schema; its original
            # variable_info specifies these seven columns in this order.
            features=['area','perimeter','compactness','kernel_length','kernel_width','asymmetry','groove_length']
            targets=['class']
        csv=folder/'data.csv'
        if not csv.exists():
            if meta['data_url']:
                response=requests.get(meta['data_url'],timeout=45);response.raise_for_status();csv.write_bytes(response.content)
            elif case == 'seeds':
                url_zip='https://archive.ics.uci.edu/static/public/236/seeds.zip'
                if not (folder/'source.zip').exists():
                    response=requests.get(url_zip,timeout=45);response.raise_for_status()
                    (folder/'source.zip').write_bytes(response.content)
                with zipfile.ZipFile(folder/'source.zip') as archive:
                    raw=archive.read('seeds_dataset.txt')
                (folder/'seeds_dataset.txt').write_bytes(raw)
                parsed=pd.read_csv(io.BytesIO(raw),sep=r'\s+',header=None,names=features+targets)
                parsed.to_csv(csv,index=False)
            else:
                raise ValueError('UCI has no standardized CSV; inspect the original source archive: '+case)
        frame=pd.read_csv(csv)
        if len(targets)!=1: raise ValueError('Expected single target: '+case)
        target=targets[0]
        values=frame[features].to_numpy(dtype=float)
        if not np.isfinite(values).all() or frame[target].isna().any(): raise ValueError('Original missing/nonfinite values: '+case)
        expected_features=7 if case=='seeds' else meta['num_features']
        if values.shape!=(meta['num_instances'],expected_features): raise ValueError('UCI dimensions differ: '+case)
        record={'case_id':case,'uci_id':identifier,'name':meta['name'],'source_url':url,'repository_url':meta['repository_url'],
                'doi':meta['dataset_doi'],'csv_url':meta['data_url'],'csv':str(csv.relative_to(root)),'csv_sha256':sha(csv),
                'metadata':str(metadata_path.relative_to(root)),'metadata_sha256':sha(metadata_path),'target':target,'features':features,
                'rows':len(frame),'n_features':len(features),'class_counts':{str(k):int(v) for k,v in frame[target].value_counts().items()},
                'selection':'Named small complete numeric classification dataset, selected before model outcomes; purposive, not representative sampling.'}
        if (folder/'source.zip').exists():
            record.update(original_archive='data/seeds/source.zip',original_archive_sha256=sha(folder/'source.zip'),
                          original_url='https://archive.ics.uci.edu/static/public/236/seeds.zip',
                          derivation='Parse original seeds_dataset.txt whitespace-separated columns in UCI variable_info order; last column is class. No row filtering.',
                          metadata_limitation='UCI summary reports num_features=0, target_col=null; original variable_info describes seven real-valued features and three varieties. The actual archive has seven features plus its class column.')
        records.append(record)
        print(case,record['rows'],record['n_features'],len(record['class_counts']),flush=True)
    (root/'data/manifest.json').write_text(json.dumps({'datasets':records},indent=2)+'\n')


if __name__=='__main__': main()
