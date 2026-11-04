#!/usr/bin/env python3
"""Render the preplanned method/paired-detail assets from complete real evidence."""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch
import numpy as np
import pandas as pd


NAMES={'iris':'Iris','wine':'Wine','wdbc':'WDBC','ionosphere':'Ionosphere','sonar':'Sonar','glass':'Glass','seeds':'Seeds','banknote':'Banknote'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(fig, folder, key):
    fig.savefig(folder/(key+'.pdf'),metadata={'CreationDate':None,'ModDate':None})
    fig.savefig(folder/(key+'.tiff'),dpi=300,pil_kwargs={'compression':'tiff_lzw'})
    plt.close(fig)


def main(root):
    results=json.loads((root/'experiment/results.json').read_text());design=json.loads((root/'experiment/design.json').read_text())
    rows=results['runs'];cases=design['cases'];seeds=design['seeds']
    expected={(c,s,k) for c in cases for s in seeds for k in ('baseline','candidate')}
    observed={(r['case_id'],r['seed'],r['condition']) for r in rows}
    if len(rows)!=len(expected) or observed!=expected or any(r['status']!='completed' for r in rows):
        raise ValueError('Detailed figures require the complete successful primary grid; do not drop failures')
    values={(r['case_id'],r['seed'],r['condition']):r['value'] for r in rows}
    out=root/'figures/generated-v2';out.mkdir(parents=True,exist_ok=True)
    if (out/'asset-trace.json').exists(): raise ValueError('Preserve the previously generated version')
    font=font_manager.findfont('Arial',fallback_to_default=False)
    style={'font.family':'Arial','font.size':9,'axes.labelsize':9,'axes.titlesize':10,'xtick.labelsize':8,'ytick.labelsize':9,
           'pdf.fonttype':42,'ps.fonttype':42,'axes.spines.top':False,'axes.spines.right':False}
    with plt.rc_context(style):
        fig,ax=plt.subplots(figsize=(5.2,4.2));ax.set(xlim=(0,1),ylim=(0,1));ax.axis('off')
        def box(x,y,text,width=.40,color='#E4F1F8'):
            ax.add_patch(FancyBboxPatch((x-width/2,y-.045),width,.09,boxstyle='round,pad=.012',facecolor=color,edgecolor='#333333',linewidth=.8))
            ax.text(x,y,text,ha='center',va='center',fontsize=9)
        ax.text(.5,.98,'Same 8 datasets and 5 seeds per dataset',ha='center',va='top',weight='bold')
        box(.5,.86,'Stratified row split; shared 20% MCAR masks',.93,'#F2F2F2')
        ax.text(.5,.76,'All fits use training rows; test rows are transformed only',ha='center',fontsize=8)
        ax.text(.24,.685,'Post-imputation scaling',ha='center',weight='bold')
        ax.text(.76,.685,'Pre-imputation scaling',ha='center',weight='bold')
        for x,labels in ((.24,['KNN imputation','StandardScaler','Logistic regression']),(.76,['StandardScaler','KNN imputation','Logistic regression'])):
            for y,label in zip((.60,.44,.28),labels):box(x,y,label)
            for a,b in ((.55,.49),(.39,.33)):
                ax.annotate('',xy=(x,b),xytext=(x,a),arrowprops={'arrowstyle':'->','color':'#333333'})
        ax.text(.5,.13,'Held-out balanced accuracy → paired seed differences',ha='center',fontsize=9)
        ax.text(.5,.07,'Average seeds within dataset; summarize 8 dataset means',ha='center',fontsize=9)
        fig.subplots_adjust(left=.015,right=.985,top=.98,bottom=.01)
        save(fig,out,'pipeline')
        detail=[]
        fig,ax=plt.subplots(figsize=(5.2,3.7),layout='constrained');ax.axvline(0,color='#777777',linestyle='--',linewidth=.9)
        for index,case in enumerate(cases):
            baseline=np.array([values[case,s,'baseline'] for s in seeds]);candidate=np.array([values[case,s,'candidate'] for s in seeds]);delta=candidate-baseline
            ax.scatter(delta,index+np.linspace(-.14,.14,len(seeds)),color='#0072B2',s=23,marker='o',label='Paired seed' if index==0 else None)
            ax.scatter([delta.mean()],[index],color='black',s=38,marker='D',label='Dataset mean' if index==0 else None,zorder=4)
            detail.append({'case_id':case,'baseline_mean':float(baseline.mean()),'baseline_seed_sd':float(baseline.std(ddof=1)),
                           'candidate_mean':float(candidate.mean()),'candidate_seed_sd':float(candidate.std(ddof=1)),
                           'paired_delta_mean':float(delta.mean()),'paired_delta_seed_sd':float(delta.std(ddof=1))})
        ax.set_yticks(range(len(cases)),[NAMES[c] for c in cases]);ax.invert_yaxis()
        ax.set_xlabel('Pre-imputation minus post-imputation\n(percentage points)');ax.grid(axis='x',alpha=.2);ax.legend(loc='best',fontsize=8)
        save(fig,out,'paired-changes')
        fig,ax=plt.subplots(figsize=(5.2,3.4),layout='constrained')
        for index,key in enumerate(('baseline','candidate')):
            values_case=np.array([row[key+'_mean'] for row in detail]);color=('#0072B2','#D55E00')[index]
            ax.scatter(np.full(len(cases),index)+np.linspace(-.1,.1,len(cases)),values_case,color=color,marker=('o','s')[index],s=25)
            ax.errorbar([index],[values_case.mean()],yerr=[values_case.std(ddof=1)],fmt='_',markersize=20,color='black',capsize=6)
        ax.set_xticks([0,1],['Post-imputation scaling','Pre-imputation scaling']);ax.set_xlim(-.45,1.45)
        ax.set_ylabel('Balanced accuracy (percentage points)');ax.set_title('Eight dataset means; bar = sample SD, not CI');ax.grid(axis='y',alpha=.2)
        save(fig,out,'macro-journal')
    data=json.loads((root/'data/manifest.json').read_text())['datasets'];dataset_lines=[]
    for item in data:
        frame=pd.read_csv(root/item['csv']);dupes=int(frame[item['features']+[item['target']]].duplicated().sum())
        dataset_lines.append(f"{NAMES[item['case_id']]} & {item['rows']} & {item['n_features']} & {len(item['class_counts'])} & {dupes} & \\cite{{uci_{item['case_id']}}} \\\\")
    (out/'datasets.tex').write_text('\\begin{tabular}{lrrrrl}\nDataset & Rows & Features & Classes & Repeat rows & Source \\\\\n\\hline\n'+'\n'.join(dataset_lines)+'\n\\end{tabular}\n')
    lines=[]
    for row in detail:
        lines.append(f"{NAMES[row['case_id']]} & {row['baseline_mean']:.2f} $\\pm$ {row['baseline_seed_sd']:.2f} & {row['candidate_mean']:.2f} $\\pm$ {row['candidate_seed_sd']:.2f} & {row['paired_delta_mean']:+.2f} \\\\")
    (out/'case-results.tex').write_text('\\begin{tabular}{lrrr}\nDataset & Post-impute scale & Pre-impute scale & Paired change \\\\\n\\hline\n'+'\n'.join(lines)+'\n\\end{tabular}\n')
    (out/'case-results.json').write_text(json.dumps({'unit':'percentage points','repeat_sd':'sample SD over five seeds within dataset','cases':detail},indent=2)+'\n')
    inputs={'experiment/results.json':sha(root/'experiment/results.json'),'experiment/design.json':sha(root/'experiment/design.json'),'data/manifest.json':sha(root/'data/manifest.json')}
    files={str(p.relative_to(root)):sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    trace={'inputs':inputs,'outputs':files,'generator_sha256':sha(Path(__file__)),'matplotlib':matplotlib.__version__,'font':font,
           'tiff_export':{'dpi':300,'font':'Arial 8–10pt','width_inches':5.2,'compression':'LZW','source':'fresh rendering from vector artists/data; no raster upsampling'},
           'statistical_scope':'All 40 paired seed changes displayed, eight dataset means, descriptive SD definitions; no significance stars or confidence intervals.',
           'macro_variant':'macro-journal has the same case means and SD meaning as the controller summary PDF, with journal typography/export; presentation variants are distinct files.'}
    (out/'asset-trace.json').write_text(json.dumps(trace,indent=2)+'\n')
    print(json.dumps({'datasets':len(detail),'paired_changes':len(cases)*len(seeds),'artifacts':list(files)},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True);main(parser.parse_args().run.resolve())
