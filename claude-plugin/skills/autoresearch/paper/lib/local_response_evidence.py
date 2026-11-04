"""Evidence binding and descriptive displays for the explicit local response protocol."""
from __future__ import annotations

import io
import math
from pathlib import Path

from . import local_response as local


def load(root, design_path, results_path, frozen_hash=None):
    design = local.read(local.safe(root, design_path))
    local.validate_design(design, root, require_resolved=True)
    design_hash = local.sha(local.safe(root, design_path).read_bytes())
    local.require(frozen_hash is None or frozen_hash == design_hash, 'local design differs from frozen plan')
    results = local.read(local.safe(root, results_path))
    local.require(results.get('protocol') == local.PROTOCOL and results.get('schema_version') == 1,
                  'invalid local result protocol')
    local.require(results.get('design') == design_path and results.get('design_sha256') == design_hash
                  and results.get('design_id') == design['experiment_id'], 'local result design mismatch')
    local.require(results.get('software_fixture') == design.get('software_fixture', False), 'fixture identity mismatch')
    records = results.get('events')
    local.require(isinstance(records, list) and len(records) >= 1, 'missing local event index')
    paths, hashes, events = set(), {}, []
    event_directory = None
    for i, reference in enumerate(records):
        local.require(isinstance(reference, dict) and set(reference) == {'path', 'sha256'}, 'invalid event reference')
        name = reference['path']; path = local.safe(root, name)
        local.require(path.resolve() not in paths, 'duplicate local evidence path')
        paths.add(path.resolve()); hashes[name] = local.sha(path.read_bytes())
        local.require(hashes[name] == reference['sha256'], 'local event bytes changed')
        value = local.read(path)
        if i == 0:
            local.require(path.name == 'design-reference.json' and value == {
                'design_path': design_path, 'design_sha256': design_hash, 'design_id': design['experiment_id']},
                'invalid recorder design reference')
            event_directory = path.parent / 'events'
        else:
            local.require(path.parent == event_directory and path.name == f'{i:06d}.json', 'local event sequence path mismatch')
            events.append(value)
    local.require({p.resolve() for p in event_directory.glob('*.json')} == {local.safe(root, ref['path']).resolve() for ref in records[1:]}, 'unindexed local event files')
    local.require(results.get('event_head_sha256') == (events[-1]['event_sha256'] if events else None), 'local event head mismatch')
    stats = local.analyze(design, events, root, design_sha256=design_hash)
    hashes.update(local.source_artifacts(design, root, require_resolved=True))
    # Provider receipts and original byte payloads are part of the export closure.
    receipt_hashes = {}
    for event in events:
        if event['kind'] != 'terminal':
            continue
        for key, value in event['data'].get('receipt', {}).items():
            if isinstance(value, dict) and set(value) >= {'path', 'sha256'}:
                name = value['path']; actual = local.sha(local.safe(root, name).read_bytes())
                local.require(actual == value['sha256'], 'provider receipt source changed')
                hashes[name] = actual
                receipt_hashes[name] = actual
    declared = results.get('receipt_artifacts', [])
    local.require(isinstance(declared, list) and len(declared) == len(receipt_hashes) and {r['path']: r['sha256'] for r in declared} == receipt_hashes, 'receipt export closure mismatch')
    stats['input_hashes'] = {'design': design_hash, 'results': local.sha(local.safe(root, results_path).read_bytes()), 'raw': hashes}
    stats['action_ids'] = design['coordinates']['action_ids']
    stats['templates'] = design['templates']
    stats['probes'] = design['probes']
    return design, results, stats, events


def caption(stats):
    count = stats['counts']
    prefix = 'SOFTWARE FIXTURE; not scientific observations. ' if stats['software_fixture'] else ''
    return (prefix + 'Local response diagnostics for three independent instances per phase, two nested states per instance, '
            'and three registered repeats per probe. Signed central differences use q step 0.02 and confidence step 0.1; '
            'confidence and policy rows have different output units. Other templates share the correct-160 q slopes. '
            'Each prospective center changes only the intercept. Points retain per-probe identities; lines at 0.10 are '
            'engineering tolerances, not confidence intervals. NA and failed predictions remain visible. '
            f"Planned={count['planned']}, valid={count['valid']}, invalid={count['invalid']}, failed={count['failed']}, "
            f"unknown={count['unknown']}, not_started={count['not_started']}. "
            'Estimates condition on valid responses. No cross-state mean, IID interval, full-text identification or global stability claim.')


def tex(value):
    return ''.join({'_':r'\_', '%':r'\%', '&':r'\&', '#':r'\#', '{':r'\{', '}':r'\}'}.get(c,c) for c in str(value))


def table(stats):
    lines = [r'\begin{tabular}{lllll}', r'Probe & Valid/planned & Policy TV & Confidence error & Status \\', r'\hline']
    for key, point in stats['prospective_points'].items():
        display = lambda x: 'NA' if x is None else f'{x:.6g}'
        lines.append(f"{tex(key)} & {point['counts']['valid']}/{point['counts']['planned']} & "
                     f"{display(point['policy_tv'])} & {display(point['confidence_abs_error'])} & {tex(point['verdict'])}" + r' \\')
    lines += [r'\end{tabular}', '% ' + caption(stats)]
    return '\n'.join(lines) + '\n'


def figure(stats, suffix):
    local.require(suffix in {'.pdf', '.svg'}, 'local diagnostics require PDF or SVG')
    local.require(stats['coefficients'] is not None and stats['predictions'] is not None, 'local diagnostic plot requires both recorded freezes')
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    from matplotlib.colors import TwoSlopeNorm
    import numpy as np
    points = stats['operating_points']
    dev = [point for point in points if 'development_op_id' not in point]
    prospective = [point for point in points if 'development_op_id' in point]
    # This is an evidence audit sheet. Publication selection must preserve the full data companion.
    with matplotlib.rc_context({'text.usetex': False, 'font.family':'DejaVu Sans', 'font.size':8,
                                'pdf.fonttype':42, 'svg.hashsalt':local.sha(local.canonical(stats))}):
        fig = Figure(figsize=(16, 33), layout='constrained')
        axes = fig.subplots(12, 3).ravel()
        bound = max([abs(x) for p in stats['coefficients']['operating_points'].values()
                     for branch in ('H','E') for column in p[branch]['q_columns'] for x in column] + [1e-12])
        offset = 0
        for op in dev:
            for branch in ('H','E'):
                ax=axes[offset];offset+=1
                values=np.array(stats['coefficients']['operating_points'][op['id']][branch]['q_columns']).T
                image=ax.imshow(values, cmap='RdBu_r', norm=TwoSlopeNorm(vmin=-bound,vcenter=0,vmax=bound), aspect='auto', interpolation='nearest')
                ax.set_title(op['id']+' / '+branch+' / signed q columns')
                ax.set_xticks(range(11),[f'q{i+1}-q12' for i in range(11)],rotation=90)
                ax.set_yticks(range(len(values)),[f'p{i+1}' for i in range(12)]+(['c_out'] if branch=='H' else []))
                ax.set_xlabel('Tangent coordinate; units: output per q-coordinate')
                fig.colorbar(image,ax=ax,shrink=.75,label='signed central difference')
        for op in dev:
            ax=axes[offset];offset+=1
            columns=stats['coefficients']['operating_points'][op['id']]['H']['confidence_columns']
            keys=list(columns);values=np.array([columns[key] for key in keys]).T
            limit=max(float(np.abs(values).max()),1e-12)
            image=ax.imshow(values,cmap='RdBu_r',norm=TwoSlopeNorm(vmin=-limit,vcenter=0,vmax=limit),aspect='auto',interpolation='nearest')
            ax.set_title(op['id']+' / H confidence columns; panel-specific scale')
            ax.set_xticks(range(len(keys)),[key.split(op['id'])[-1].lstrip('-') for key in keys],rotation=90,fontsize=5)
            ax.set_yticks(range(13),[f'p{i+1}' for i in range(12)]+['c_out'])
            fig.colorbar(image,ax=ax,shrink=.75,label='output per input confidence')
        for op in prospective:
            ax=axes[offset];offset+=1
            rows=[(key,p) for key,p in stats['prospective_points'].items() if p['operating_point_id']==op['id']]
            for i,(key,p) in enumerate(rows):
                if p['policy_tv'] is None:
                    ax.text(i,0,'NA',rotation=90,va='bottom',ha='center',fontsize=6)
                else:
                    ax.plot(i,p['policy_tv'],'o',color='#0072B2',markersize=3)
                if p['confidence_abs_error'] is not None:
                    ax.plot(i,p['confidence_abs_error'],'x',color='#D55E00',markersize=4)
            ax.axhline(.1,linestyle='--',color='black',linewidth=.7)
            ax.set_title(op['id']+' / prospective; circle TV, x confidence')
            ax.set_xticks(range(len(rows)),[key.split(op['id'])[-1].lstrip('-') for key,p in rows],rotation=90,fontsize=5)
            ax.set_ylim(bottom=0); ax.set_ylabel('Per-probe error; no interval')
        for op in points:
            ax=axes[offset];offset+=1
            rows=[(key,c) for key,c in stats['cells'].items() if c['operating_point_id']==op['id']]
            for i,(key,c) in enumerate(rows):
                if c['max_same_input_tv'] is None: ax.text(i,0,'NA',rotation=90,fontsize=5)
                else: ax.plot(i,c['max_same_input_tv'],'o',markersize=2,color='#333333')
            ax.axhline(.1,linestyle='--',color='black',linewidth=.7)
            ax.set_title(op['id']+' / repeated-input policy TV')
            ax.set_xticks(range(len(rows)),[str(i+1) for i in range(len(rows))],rotation=90,fontsize=4)
            ax.set_xlabel('Probe ordinal; identities and valid/planned counts in JSON');ax.set_ylim(bottom=0)
        fig.suptitle(('SOFTWARE FIXTURE — ' if stats['software_fixture'] else '')+'Local diagnostics; nested states are not independent cases',fontsize=15)
        fig.supxlabel('Full vectors, invalid slots, same-payload cross-slot TV, confidence columns and identities are retained in the data companion. No global CI.',fontsize=10)
        output=io.BytesIO()
        metadata={'Creator':'autoresearch local response audit renderer','Date':None} if suffix=='.svg' else {
            'Creator':'autoresearch local response audit renderer','CreationDate':None,'ModDate':None}
        fig.savefig(output,format=suffix[1:],metadata=metadata)
        return output.getvalue()


def assertion_value(record, stats):
    local.require('confidence' not in stats['action_ids'], 'reserved confidence coordinate collides with action ID')
    op_id=record.get('operating_point_id')
    op=next((p for p in stats['operating_points'] if p['id']==op_id),None)
    local.require(op is not None,'local assertion needs a registered operating point')
    local.require(record.get('condition')=='fixed-template-local-response' and record.get('strength')=='descriptive', 'local assertion scope is not supported')
    probe_id=record.get('probe_id');measure=record.get('measure')
    if measure in {'same_input_tv_max','prospective_policy_tv','prospective_confidence_abs_error'}:
        cell=stats['cells'].get(probe_id)
        local.require(cell is not None and cell['operating_point_id']==op_id,'local assertion probe/state mismatch')
        if measure=='same_input_tv_max': value=cell['max_same_input_tv'];unit='probability-TV'
        else:
            point=stats['prospective_points'].get(probe_id)
            local.require(point is not None,'assertion is not a prospective point')
            value=point['policy_tv'] if measure=='prospective_policy_tv' else point['confidence_abs_error']
            unit='probability-TV' if measure=='prospective_policy_tv' else 'confidence'
        denominator={'independent_instance_id':op['instance_id'],'planned':cell['counts']['planned'],'valid':cell['counts']['valid']}
    elif measure=='central_difference_entry':
        branch=record.get('branch');axis=record.get('axis_id');coordinate=record.get('output_coordinate')
        columns=(stats.get('coefficients') or {}).get('operating_points',{}).get(op_id,{})
        local.require(branch in columns and type(axis) is int and 0<=axis<11,'unmeasured local derivative axis')
        coordinates=[*stats['action_ids']]+(['confidence'] if branch=='H' else [])
        local.require(coordinate in coordinates,'unmeasured output coordinate')
        value=columns[branch]['q_columns'][axis][coordinates.index(coordinate)]
        unit='confidence-per-q-coordinate' if coordinate=='confidence' else 'probability-per-q-coordinate'
        # Endpoint-specific denominators must be provided, never a pooled pseudo-sample.
        endpoint_ids=record.get('endpoint_probe_ids')
        local.require(isinstance(endpoint_ids,list) and len(endpoint_ids)==2,'central difference needs both endpoint identities')
        endpoints={p['id']:p for p in stats['probes']}
        local.require(all(key in endpoints for key in endpoint_ids),'unregistered derivative endpoint')
        selected=[endpoints[key] for key in endpoint_ids]
        local.require(all(p['role']=='q_axis' and p['axis']==axis and p['branch']==branch and p['operating_point_id']==op_id for p in selected)
                      and [p['sign'] for p in selected]==[-1,1], 'wrong derivative endpoint direction or order')
        cells=[stats['cells'].get(key) for key in endpoint_ids]
        local.require(all(c and c['operating_point_id']==op_id and c['branch']==branch for c in cells),'endpoint state/branch mismatch')
        denominator={'independent_instance_id':op['instance_id'],'endpoints':{key:cell['counts'] for key,cell in zip(endpoint_ids,cells)}}
    else:
        raise ValueError('unsupported local assertion measure')
    local.require(value is not None and math.isfinite(value),'missing local quantity cannot support a numeric assertion')
    local.require(record.get('unit')==unit and record.get('denominator')==denominator,'local assertion unit/denominator mismatch')
    return value
