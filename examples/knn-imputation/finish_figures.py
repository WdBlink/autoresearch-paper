#!/usr/bin/env python3
"""Normalize actual TIFF exports and accept the real six-visual handoff."""
import hashlib
import json
from pathlib import Path
import platform
import sys

from PIL import Image
import matplotlib
import numpy
import pandas

from control import invoke, put


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(root):
    journal=root/'figures/journal';journal.mkdir(exist_ok=True);exports=[]
    for index,key in enumerate(('pipeline','paired-changes','macro-journal'),1):
        source=root/f'figures/generated-v2/{key}.tiff';target=journal/f'Fig{index}.tif'
        image=Image.open(source)
        if image.mode=='RGBA' and image.getchannel('A').getextrema()!=(255,255):
            raise ValueError('Do not discard nonopaque information')
        image.convert('RGB').save(target,compression='tiff_lzw',dpi=(300,300))
        exported=Image.open(target)
        if exported.width!=1560 or target.stat().st_size>=10*1024*1024:
            raise ValueError('Actual journal export dimensions/size differ')
        exports.append({'file':str(target.relative_to(root)),'sha256':sha(target),'source':str(source.relative_to(root)),
            'source_sha256':sha(source),'pixels':list(exported.size),'dpi':[float(v) for v in exported.info['dpi']],
            'mode':exported.mode,'transform':'Lossless removal of all-opaque alpha; no resize or enhancement','font':'Arial, 8–10pt as drawn'})
    put(root,'figures/journal/export-manifest.json',{'phase':'PLOS ONE figure assets, no submission performed','source_rules':'materials/sources/plos-figures.txt','exports':exports})
    put(root,'figures/environment.json',{'python':sys.version,'os':platform.platform(),'matplotlib':matplotlib.__version__,'numpy':numpy.__version__,'pandas':pandas.__version__})
    context=invoke(root,'context');effect=context['attempts']['render-real-macro-summary']['actions'][0]['effect']
    files=[]
    for folder in ('figures/generated','figures/generated-v2','figures/journal'):
        files.extend(str(p.relative_to(root)) for p in sorted((root/folder).iterdir()) if p.is_file())
    files+=['figures/pipeline.pdf','figures/paired-changes.pdf','figures/macro-journal.pdf','figures/datasets.tex','figures/case-results.tex',
        'figures/macro.tex','figures/summary.pdf','figures/macro.tex.stats.json','figures/summary.pdf.trace.json',
        'figures/environment.json','figures/render-revisions.json','software/assets-v2.py','software/finish_figures.py']
    packet={'stage':'figures','producer':'research-author','artifacts':list(dict.fromkeys(files)),
        'design':'experiment/design.json','results':'experiment/results.json','statistics':'figures/macro.tex.stats.json',
        'table':'figures/macro.tex','figure':'figures/summary.pdf','trace':'figures/summary.pdf.trace.json','caption':effect['caption'],
        'display_assets':{'F1':'figures/pipeline.pdf','F2':'figures/paired-changes.pdf','F3':'figures/macro-journal.pdf',
                          'T1':'figures/datasets.tex','T2':'figures/case-results.tex','T3':'figures/macro.tex'},
        'presentation_note':'The exact controller summary PDF is retained as a numeric reference. F3 is a traced same-statistics journal-typography variant. Reading/submission layout variants remain explicit.'}
    put(root,'figures/packet.json',packet)
    print(invoke(root,'commit','--packet',root/'figures/packet.json','--operation-id','accept-actual-six-visuals')['status'])
    context=invoke(root,'context','--writing-case','E07');put(root,'control/context-write.json',context)
    print('Next stage:',context['stage'],'full writing guidance characters:',len(context['writing_guidance']['principles']))


if __name__=='__main__': main(Path(sys.argv[1]).resolve())
