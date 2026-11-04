#!/usr/bin/env python3
"""Fix the actual R1 cross-page PDF link borders, retaining reviewed science."""
import hashlib
import json
from pathlib import Path
import sys

from control import invoke, put


def main(root):
    reports = ['review/artifact-review-r1.json', 'review/methods-manuscript-r1.json']
    for name in reports:
        if not (root/name).is_file(): raise ValueError('Actual R1 report missing: '+name)
    if (root/'manuscript/main-r2.tex').exists():
        raise ValueError('R2 already started; resume public CLI receipts instead of overwriting history')
    invoke(root, 'rewind', '--stage', 'write', '--reason',
        'Both independent R1 reviewers confirmed Poppler-visible cross-page URL annotation borders over the footer; hide borders without changing scientific text',
        '--operation-id', 'rewind-real-link-display-r2')
    replacements = {}
    changes = []
    orders = []
    for edition, ids in [('main', ['S1','S2','M1']), ('submission', ['M1'])]:
        before=f'manuscript/{edition}-r1.tex'; after=f'manuscript/{edition}-r2.tex'
        source=(root/before).read_text()
        assert source.count('\\begin{document}') == 1
        source=source.replace('\\begin{document}', '\\hypersetup{hidelinks}\n\\begin{document}')
        put(root, after, source)
        replacements[before]=after
        replacements[f'manuscript/{edition}-r1.pdf']=f'manuscript/{edition}-r2.pdf'
        changes.append({'baseline':{'path':before,'sha256':hashlib.sha256((root/before).read_bytes()).hexdigest()},
            'after':after,'reason':'R1 actual Poppler inspection: hide cross-page hyperlink annotation borders; retain all text, figures, results and bibliography.'})
        orders.append({'id':f'W-{edition}-r2','producer':'research-author','requirement_ids':ids,'supersedes':f'W-{edition}-r1',
            'actions':[{'type':'compile_tex','source':after,'pdf':f'manuscript/{edition}-r2.pdf'}]})
    put(root,'plan/writing-orders-r2.json',orders)
    invoke(root,'revise-orders','--packet','plan/writing-orders-r2.json','--reason','Confirmed PDF annotation display defect only',
        '--operation-id','orders-real-link-display-r2')
    for edition in ('main','submission'):
        result=invoke(root,'execute','--work-id',f'W-{edition}-r2','--operation-id',f'compile-real-{edition}-r2')
        if result['status'] != 'completed': raise ValueError(result)
    put(root,'review/revision-r2.json',{'status':'revised','changes':changes,'reports':reports,'scientific_values_changed':False})
    put(root,'software/revise_display.py',Path(__file__).read_text())
    def replace(value):
        if isinstance(value,str): return replacements.get(value,value)
        if isinstance(value,list): return [replace(x) for x in value]
        if isinstance(value,dict): return {k:replace(v) for k,v in value.items()}
        return value
    packet=replace(json.loads((root/'write/packet-r1.json').read_text()))
    packet['section_packets'][0]['baseline']={'path':'manuscript/main-r1.tex','sha256':hashlib.sha256((root/'manuscript/main-r1.tex').read_bytes()).hexdigest()}
    packet['artifacts'] += ['manuscript/main-r1.tex','manuscript/submission-r1.tex','review/revision-r2.json','software/revise_display.py',*reports]
    put(root,'write/packet-r2.json',packet)
    invoke(root,'commit','--packet','write/packet-r2.json','--operation-id','accept-real-write-r2')
    for path in sorted((root/'bindings/r1').glob('*.json')):
        binding=replace(json.loads(path.read_text()))
        if binding['work_id']=='W-main-r1': binding['work_id']='W-main-r2'
        name='bindings/r2/'+path.name
        put(root,name,binding)
        invoke(root,'bind','--packet',name,'--operation-id','bind-real-r2-'+path.stem)
    put(root,'control/context-review-r2.json',invoke(root,'context'))
    print('R2 compiled, write accepted, all nine bindings renewed; actual independent regression review remains required.')


if __name__=='__main__': main(Path(sys.argv[1]).resolve())
