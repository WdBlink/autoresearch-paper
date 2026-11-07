#!/usr/bin/env python3
"""Assemble the actual authored draft and its clearly distinct journal-format copy."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

from control import invoke, put


def main(root):
    original=(root/'venue/template/plos_latex_template.tex').read_text()
    preamble=original[original.index('\\documentclass'):original.index('\\begin{document}')]
    preamble='\n'.join(line for line in preamble.splitlines() if line.strip() and not line.lstrip().startswith('%'))+'\n'
    preamble=preamble.replace('\\lfoot{\\today}','\\lfoot{4 November 2026}')
    preamble+='\\usepackage[T1]{fontenc}\n\\usepackage[utf8]{inputenc}\n\\usepackage{setspace}\n\\doublespacing\n'
    body=(root/'manuscript/body-fragment.txt').read_text()
    wide=r'\bar a_{dc}=\frac{1}{5}\sum_{s=1}^{5}a_{dsc},\qquad \delta_d=\frac{1}{5}\sum_{s=1}^{5}(a_{ds,\mathrm{pre}}-a_{ds,\mathrm{post}}),\qquad \bar\delta=\frac{1}{8}\sum_{d=1}^{8}\delta_d.'
    aligned=r'''\begin{aligned}
\bar a_{dc}&=\frac{1}{5}\sum_{s=1}^{5}a_{dsc},\\
\delta_d&=\frac{1}{5}\sum_{s=1}^{5}(a_{ds,\mathrm{pre}}-a_{ds,\mathrm{post}}),\\
\bar\delta&=\frac{1}{8}\sum_{d=1}^{8}\delta_d.
\end{aligned}'''
    if wide not in body: raise ValueError('Expected authored aggregation equation changed; inspect before assembly')
    body=body.replace(wide,aligned)
    body=body.replace('84.85\\% for pre-imputation scaling (Table~\\ref{tab:T3}).','84.85\\% for pre-imputation scaling.')
    body=body.replace('Between-dataset SDs of mean balanced accuracy were','The fixed-set macro summaries are reported in Table~\\ref{tab:T3}.\nBetween-dataset SDs of mean balanced accuracy were')
    start=r'''\begin{document}
\title{Scaling before or after k-nearest-neighbour imputation: a paired comparison on eight public classification datasets}
\author{Internal AI-assisted research draft\\Authorship and affiliations not assigned}
\date{4 November 2026}
\maketitle
\noindent\textbf{Reading edition.} Figures are embedded for internal review. Human expert/editorial review and author declarations remain pending. No submission has occurred.
\linenumbers
'''
    end='\n\\bibliography{references}\n\\end{document}\n'
    reading=preamble+start+body+end
    if len(reading.splitlines())>300: raise ValueError('The newly authored TeX exceeds the admitted line limit')
    put(root,'manuscript/main.tex',reading)
    submission=reading.replace('\\textbf{Reading edition.} Figures are embedded for internal review.','\\textbf{Submission-format draft.} Figure files are supplied separately; this derivative has not been submitted.')
    submission=re.sub(r'\\includegraphics(?:\[[^\]]*\])?\{[^}]+\}', '', submission)
    for name in ('datasets','case-results','macro-display'):
        submission=submission.replace('\\input{../figures/'+name+'.tex}',(root/'figures'/f'{name}.tex').read_text())
    if '\\includegraphics' in submission or '\\input{' in submission:
        raise ValueError('The submission-format derivative still embeds a figure or splits the body')
    if len(submission.splitlines())>300: raise ValueError('The submission derivative exceeds the admitted line limit')
    put(root,'manuscript/submission.tex',submission)
    shutil.copyfile(root/'venue/template/plos2025.bst',root/'manuscript/plos2025.bst')
    stats=json.loads((root/'figures/macro.tex.stats.json').read_text())
    assertion='The equal-dataset-weight mean paired change was 0.130665 percentage points.'
    limitations=[{'kind':'scope','text':'This is a descriptive comparison of eight purposively chosen datasets, one learner and one artificial MCAR rate.'},
      {'kind':'adverse','text':'Glass, Seeds and Banknote had negative mean changes and remain in the comparison.'},
      {'kind':'repeated_partitions','text':'The five seeds within a dataset are repeated partitions, not five independent datasets.'},
      {'kind':'data_dependence','text':'Repeated original feature-label vectors can occur in both row partitions, so these results do not establish generalization to new entities.'}]
    for item in [assertion,*[x['text'] for x in limitations]]:
        if item not in reading: raise ValueError('Authored evidence/limitation sentence missing: '+item)
    assertions={'assertions':[{'id':'A1','claim_id':'C1','kind':'numeric','strength':'descriptive','text':assertion,
        'statistics':'figures/macro.tex.stats.json','measure':'delta.mean','value':stats['delta']['mean'],'unit':'percentage points','denominator':8,'condition':'all-planned-cases'}],
        'limitations':limitations,'prose_review':{'problem':'Compare training-only transform order under a fixed missingness intervention','choice':'Frozen paired row partitions/masks and an unchanged learner','finding':assertion,'scope':'Eight purposive raw-row datasets, five dependent repeats, one learner/rate; no population or entity generalization'},'revisions':[]}
    put(root,'manuscript/assertions.json',assertions)
    put(root,'manuscript/assembly-notes.json',{'authored_fragment':'manuscript/body-fragment.txt','authored_fragment_sha256':hashlib.sha256((root/'manuscript/body-fragment.txt').read_bytes()).hexdigest(),
      'changes':['Wrap the long aggregation equation in aligned lines without changing its formula','Keep first table references in numeric order','Use explicit study date for later reproducible builds','Use official class/options/packages and double spacing','Separate internal reading graphics from the journal-format no-embedded-graphics derivative'],
      'lines':{'reading':len(reading.splitlines()),'submission':len(submission.splitlines())},'scientific_values_changed':False})
    print(invoke(root,'execute','--work-id','W-writing','--operation-id','compile-real-reading-draft')['status'])


if __name__=='__main__': main(Path(sys.argv[1]).resolve())
