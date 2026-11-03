#!/usr/bin/env python3
"""Run a complete offline SOFTWARE fixture. No model, network or real venue claim."""
import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.runtime import Controller, Refusal, digest, file_hash


def put(root, name, value):
    path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n' if not isinstance(value, str) else value)
    return name


def packet(stage, files, **fields):
    return {'stage': stage, 'producer': 'fixture-author', 'artifacts': list(dict.fromkeys(files)), **fields}


def make_brief():
    return {'software_fixture': True, 'question': 'Exercise a paper workflow using fixed local CPU transformations; no scientific claim',
            'venue': 'Synthetic Software Fixture', 'direction': 'software-contract testing', 'paper_type': 'original',
            'resources': {'authorization': 'offline software verification only', 'model_calls': 0, 'remote_jobs': 0, 'cpu': 'sequential local fixture'},
            'reviewers': ['fixture-reviewer'],
            'deliverable_plan': [{'id': key, 'kind': kind, 'title': title,
                                  'purpose': 'Verify ' + title + ' against the measured software fixture',
                                  'claim': 'C1', 'acceptance_criteria': ['Correctly represent the complete planned fixture outcomes'],
                                  'evidence_requirements': ['Frozen design, raw logs, numerical trace and manuscript location']}
                                 for key, kind, title in [('F1', 'figure', 'Paired fixture errors'), ('T1', 'table', 'Fixture statistics'),
                                                          ('S1', 'section', 'Results and limitations'), ('M1', 'manuscript', 'Compiled software fixture')]]}


EVALUATOR = '''import json
runs=[]
for index,case in enumerate('abcd',1):
 for seed in (0,1):
  for condition in ('baseline','candidate'):
   status='failed' if condition=='candidate' and case=='c' else 'stopped' if condition=='candidate' and case=='d' else 'completed'
   value=(index+seed*.2+(1 if condition=='candidate' else 0)) if status=='completed' else None
   runs.append(dict(case_id=case,seed=seed,condition=condition,status=status,value=value))
print(json.dumps(runs,allow_nan=False))
'''


SAMPLE_TEX = r'''\documentclass{article}
\usepackage[labelsep=period]{caption}
\title{Synthetic software venue sample}
\begin{document}\maketitle
This sample is generated for software validation. It is not an accepted research paper.
Figure 1 and Table 1 show the fixture layout.
\begin{figure}[h]\centering\fbox{Synthetic layout}\caption{Sample quantitative results.}\end{figure}
\begin{table}[h]\centering\begin{tabular}{lr}Case&Value\\A&1\\\end{tabular}\caption{Sample main results.}\end{table}
\end{document}
'''


class FixturePaused(Exception):
    pass


def run(root, *, stop_after=None):
    from lib import planning, science
    root = Path(root).resolve()
    if (root / '.paper/control.json').exists():
        raise Refusal('Fixture requires a fresh run; it never resets a historical run')
    root.mkdir(parents=True, exist_ok=True)
    ctl = Controller(root)
    brief = make_brief()
    result = ctl.init(brief)
    put(root, 'brief.json', brief)
    ctl.approve(result['brief_sha256'], 'offline software fixture')
    contexts = []
    def commit(p):
        context = ctl.context()
        assert context['stage'] == p['stage'] and context['knowledge'] and context['upstream_protocol']
        contexts.append({'stage': p['stage'], 'knowledge_sha256': context['knowledge_sha256']})
        put(root, p['stage'] + '/packet.json', p)
        receipt = ctl.commit(p, 'commit-' + p['stage'])
        if p['stage'] == stop_after:
            raise FixturePaused(p['stage'])
        return receipt

    text = 'Offline fixture: compare two fixed transformations on four cases, preserving failures and stops. Only local sequential CPU work is authorized.'
    material = put(root, 'materials/project.md', text)
    evidence = {'material_id': 'B1', 'start': 0, 'end': len(text), 'quote': text}
    intake = packet('intake', [material],
                    materials=[{'id': 'B1', 'path': material, 'sha256': file_hash(root / material), 'availability': 'readable', 'read_spans': [[0, len(text)]]}],
                    evidence=[evidence],
                    feasibility={'status': 'feasible', 'selected_option': 'fixed-cpu',
                                 'options': [{'id': 'fixed-cpu', 'implementation': 'Known fixed CPU fixture evaluator', 'selection_reason': 'No external effect', 'evidence': [evidence]},
                                             {'id': 'live-model', 'implementation': 'Paid remote model', 'selection_reason': 'Excluded by offline authorization', 'evidence': [evidence]}],
                                 'resources': {'authorization': 'offline fixture only', 'cost_basis': 'zero paid model calls; local CPU'},
                                 'experiments': [{'claim': 'C1', 'metric': 'error', 'comparison': 'baseline vs candidate', 'protocol': 'paired cases and seeds', 'completion': 'all planned attempts', 'failure_route': 'retain outcomes and frozen penalty'}]})
    ctl.read_material(material)
    commit(intake)

    rules = put(root, 'venue/rules.md', 'SOFTWARE FIXTURE official-rule stand-in. One article, one results plot and one table; no real acceptance claim.')
    template = put(root, 'venue/template.tex', SAMPLE_TEX)
    sample_source = put(root, 'venue/sample.tex', SAMPLE_TEX)
    ctl._action(ctl.load(), {'type': 'compile_tex', 'source': sample_source, 'pdf': 'venue/sample.pdf'})
    accepted = put(root, 'venue/acceptance.md', 'Synthetic software fixture acceptance stand-in, not a real accepted paper.')
    plan_items = [dict(id='F1', kind='figure', type='quantitative_results', question='How do the measured cases compare?', claim='C1', data='experiment/results.json', section='Results', priority='must'),
                  dict(id='T1', kind='table', type='main_results', question='What are the full-denominator statistics?', claim='C1', data='experiment/results.json', section='Results', priority='must')]
    plan_name = put(root, 'plan/figure_table_plan.json', {'items': plan_items, 'deviation_reason': ''})
    venue = packet('venue', [rules, template, sample_source, 'venue/sample.pdf', accepted, plan_name,
                             'venue/measurements.json', 'venue/profile.json', 'venue/check.json'],
                   software_fixture=True, venue=brief['venue'], direction=brief['direction'], paper_type=brief['paper_type'],
                   official_rules={'path': rules, 'url': 'https://example.invalid/software-fixture/rules', 'sha256': file_hash(root / rules), 'basis': 'official_requirement'},
                   template={'path': template, 'url': 'https://example.invalid/software-fixture/template', 'sha256': file_hash(root / template), 'status': 'available'},
                   samples=[{'id': 'sample1', 'pdf': 'venue/sample.pdf', 'venue_label': brief['venue'], 'year': 2026,
                             'acceptance_evidence': {'path': accepted, 'url': 'https://example.invalid/software-fixture/acceptance', 'sha256': file_hash(root / accepted)},
                             'direction_match': 'Matches software fixture only',
                             'design': {'figures': [{'type': 'quantitative_results', 'placement': 'body'}], 'tables': [{'type': 'main_results', 'placement': 'body'}]}}],
                   sampling_limitations='One synthetic software sample; no claim about real venue conventions.', figure_table_plan=plan_name,
                   measurements='venue/measurements.json', venue_profile='venue/profile.json', venue_plan_check='venue/check.json')
    calibration = planning.calibrate(venue, root)
    for field, key in [('measurements', 'measurements'), ('venue_profile', 'venue_profile'), ('venue_plan_check', 'venue_plan_check')]:
        put(root, venue[field], calibration[key])
    commit(venue)

    evaluator = put(root, 'experiment/evaluator.py', EVALUATOR)
    design = {'experiment_id': 'E1', 'claim_id': 'C1', 'hypothesis': 'Candidate reduces fixture error',
              'independent_variable': 'transformation', 'dependent_variable': 'error', 'control_variables': ['same inputs', 'same evaluator'],
              'metric': {'name': 'error', 'unit': 'points', 'direction': 'lower'}, 'statistical_unit': 'case',
              'cases': list('abcd'), 'seeds': [0, 1], 'conditions': ['baseline', 'candidate'], 'failure_policy': 'penalty', 'failure_value': 10,
              'statistics': {'estimator': 'mean', 'interval': 'sd', 'paired': True},
              'data_roles': [{'id': 'fixture-dev', 'role': 'development', 'used_for_selection': True}, {'id': 'fixture-holdout', 'role': 'holdout', 'used_for_selection': False}],
              'evaluator': {'path': evaluator, 'sha256': file_hash(root / evaluator)}, 'planned_at': '2026-11-03T00:00:00Z'}
    design_name = put(root, 'experiment/design.json', design)
    snapshot = put(root, 'plan/snapshot.json', planning.plan_snapshot(root / plan_name))
    orders = [dict(id='W-experiment', producer='fixture-author', requirement_ids=['F1', 'T1'], actions=[{'type': 'validate_packet', 'packet': 'experiment/packet.json'}]),
              dict(id='W-figures', producer='fixture-author', requirement_ids=['F1', 'T1'], actions=[{'type': 'render_statistics', 'input': 'experiment/results.json', 'table': 'figures/summary.tex', 'figure': 'figures/results.pdf'}]),
              dict(id='W-writing', producer='fixture-author', requirement_ids=['S1', 'M1'], actions=[{'type': 'compile_tex', 'source': 'manuscript/main.tex', 'pdf': 'manuscript/main.pdf'}])]
    plan = packet('plan', [plan_name, snapshot, design_name, evaluator], figure_table_plan=plan_name, plan_snapshot=snapshot,
                  experiment_design_sha256=file_hash(root / design_name), work_orders=orders)
    commit(plan)

    source = put(root, 'literature/source.txt', 'Synthetic method source for software testing. Its unit is the case, with repeated seeds averaged within case.')
    verification = put(root, 'literature/verification.txt', 'Local synthetic metadata verified against this generated fixture; not a real publication.')
    catalog = {'question_formed_at': '2026-11-03T00:00:00Z',
               'searches': [{'query': 'software fixture AND case means', 'method': 'keyword', 'result_ids': ['L1', 'L2']}],
               'naive_baseline_ids': ['L1'], 'hard_negative_ids': ['L2'],
               'candidates': [{'id': 'L1', 'title': 'Synthetic method record (software fixture)', 'url': 'https://example.invalid/synthetic-L1',
                               'published_at': '2026-10-01T00:00:00Z', 'exposure': 'prospective', 'purpose': 'A naive comparison for software fixture checking',
                               'decision': 'include', 'read_status': 'read', 'read_path': source, 'verification': {'status': 'primary_checked', 'evidence': verification},
                               'evidence_spans': [{'path': source, 'quote': 'Its unit is the case, with repeated seeds averaged within case.'}]},
                              {'id': 'L2', 'title': 'Synthetic hard negative (software fixture)', 'url': 'https://example.invalid/synthetic-L2',
                               'published_at': '2026-10-01T00:00:00Z', 'exposure': 'prospective', 'purpose': 'Identify a topically related incompatible unit',
                               'decision': 'exclude', 'exclusion_reason': 'Treats repeated seeds as independent cases', 'read_status': 'registered'}]}
    catalog_name = put(root, 'literature/catalog.json', catalog)
    commit(packet('literature', [catalog_name, source, verification], catalog=catalog_name))

    observed = json.loads(subprocess.check_output([sys.executable, str(root / evaluator)], text=True))
    runs = []
    for record in observed:
        key = record['case_id'] + '-' + record['condition'] + '-' + str(record['seed'])
        row = dict(id=key, **record, raw='experiment/raw/' + key + '.json')
        if row['status'] != 'completed':
            row['reason'] = 'Explicit simulated software-fixture ' + row['status']
            row['failure_kind'] = 'measurement'
        put(root, row['raw'], {k: v for k, v in row.items() if k not in {'id', 'raw'}})
        runs.append(row)
    results = {'design': design_name, 'design_sha256': file_hash(root / design_name), 'started_at': '2026-11-03T01:00:00Z',
               'outcome': 'negative', 'reported_denominator': len(runs), 'runs': runs}
    results_name = put(root, 'experiment/results.json', results)
    summary = put(root, 'experiment/summary.md', 'SOFTWARE FIXTURE. Candidate is worse on observed cases. All failures/stops retained:\n' + '\n'.join(r['id'] for r in runs if r['status'] != 'completed'))
    experiment = packet('experiment', [design_name, evaluator, results_name, summary, *[r['raw'] for r in runs]], design=design_name, results=results_name, summary=summary)
    put(root, 'experiment/packet.json', experiment)
    ctl.execute('W-experiment', 'execute-experiment')
    commit(experiment)

    rendered = ctl.execute('W-figures', 'execute-figures')['effects'][0]['effect']
    statistics_name, trace_name = 'figures/summary.tex.stats.json', 'figures/results.pdf.trace.json'
    figures = packet('figures', [design_name, evaluator, results_name, *[r['raw'] for r in runs], statistics_name, 'figures/summary.tex', 'figures/results.pdf', trace_name],
                     design=design_name, results=results_name, statistics=statistics_name, table='figures/summary.tex', figure='figures/results.pdf', trace=trace_name, caption=rendered['caption'])
    commit(figures)

    stats = json.loads((root / statistics_name).read_text())
    mean = stats['conditions']['candidate']['mean']
    sentence = f'The candidate mean error was {mean:.6f} points.'
    limitations = [{'kind': 'scope', 'text': 'These software measurements describe only the planned fixture cases.'},
                   {'kind': 'small_sample', 'text': 'Four independent cases do not establish a population effect.'},
                   {'kind': 'failure', 'text': 'All simulated failed and stopped attempts remain in the denominator with the frozen penalty.'},
                   {'kind': 'adverse', 'text': 'The candidate was worse on these paired fixture cases; the negative outcome is retained.'}]
    assertions = {'assertions': [{'id': 'A1', 'claim_id': 'C1', 'text': sentence, 'statistics': statistics_name, 'measure': 'candidate.mean', 'value': mean,
                                 'unit': 'points', 'denominator': 4, 'condition': 'all-planned-cases', 'strength': 'descriptive', 'kind': 'numeric'}],
                  'limitations': limitations, 'prose_review': {'problem': 'Compare fixture transformations', 'choice': 'Fixed full-denominator pairing', 'finding': sentence, 'scope': 'Software fixture only'}, 'revisions': []}
    facts = put(root, 'manuscript/assertions.json', assertions)
    bibliography = put(root, 'manuscript/references.bib', '@misc{fixture, title={Synthetic method record, software fixture only}, author={Offline Fixture}, year={2026}}\n')
    manuscript = r'''\documentclass{article}
\usepackage{graphicx}
\usepackage[labelsep=period]{caption}
\title{Offline workflow fixture}
\begin{document}\maketitle
\begin{abstract}This is a software fixture, not a research paper or evidence of scientific readiness.\end{abstract}
\section{Question and method}We compare two fixed transformations using a frozen local evaluator. Repeated seeds are averaged within each of four cases. The synthetic source is a software record~\cite{fixture}.
\section{Results}
''' + sentence + '\n' + '\n'.join(x['text'] for x in limitations) + r'''
Figure 1 and Table 1 report the same full-denominator observations.
\begin{figure}[ht]\centering\includegraphics[width=.65\linewidth]{../figures/results.pdf}\caption{Paired software fixture errors with case-level standard deviations.}\label{fig:F1}\end{figure}
\begin{table}[ht]\centering\input{../figures/summary.tex}\caption{Full-denominator fixture statistics.}\label{tab:T1}\end{table}
\begin{thebibliography}{1}\bibitem{fixture} Offline Fixture. Synthetic method record. Software testing only, 2026.\end{thebibliography}
\end{document}
'''
    tex = put(root, 'manuscript/main.tex', manuscript)
    ctl.execute('W-writing', 'execute-writing')
    write = packet('write', [tex, 'manuscript/main.pdf', facts, bibliography, statistics_name, template], manuscript=tex, manuscript_tex=tex,
                   manuscript_pdf='manuscript/main.pdf', assertions=facts, bibliography=bibliography, template_source=template, template_sha256=file_hash(root / template))
    commit(write)

    for key, work, asset, location in [('F1', 'W-figures', 'figures/results.pdf', r'\label{fig:F1}'),
                                       ('T1', 'W-figures', 'figures/summary.tex', r'\label{tab:T1}'),
                                       ('S1', 'W-writing', tex, r'\section{Results}'),
                                       ('M1', 'W-writing', 'manuscript/main.pdf', r'\title{Offline workflow fixture}')]:
        ctl.bind({'requirement_id': key, 'work_id': work, 'assets': [asset], 'evidence': [results_name, statistics_name],
                  'manuscript': tex, 'location': location}, 'bind-' + key)
    bindings = ctl.load()['bindings']
    review_report = put(root, 'review/report.md', 'SOFTWARE FIXTURE reviewer packet. These are scripted checks, not an independent model review. All planned items and negative outcomes are preserved.')
    review = packet('review', [review_report, plan_name, snapshot, tex, 'manuscript/main.pdf'], reviewer='fixture-reviewer',
                    figure_table_plan=plan_name, plan_snapshot=snapshot, manuscript_pdf='manuscript/main.pdf',
                    r6_reviews=[{'id': i['id'], 'verdict': 'fulfilled', 'reason': 'Present in compiled software fixture with raw evidence', 'evidence_locations': [r'Figure 1' if i['kind'] == 'figure' else 'Table 1']} for i in plan_items],
                    gates={key: {'verdict': 'pass', 'evidence': [review_report]} for key in ['G1', 'G2', 'G3', 'G4', 'G5', 'R6']},
                    requirement_checks=[{'requirement_id': key, 'binding_sha256': val['binding_sha256'], 'evidence_hashes': val['hashes'],
                                         'verdict': 'fulfilled', 'rationale': 'Scripted software fixture correspondence check; no independent scientific review claim'} for key, val in bindings.items()])
    commit(review)
    delivery_context = ctl.context()
    assert delivery_context['stage'] == 'delivery' and delivery_context['knowledge']
    contexts.append({'stage': 'delivery', 'knowledge_sha256': delivery_context['knowledge_sha256']})
    exported = ctl.finalize('export-fixture')
    ctl.verify_export(exported['manifest'])
    put(root, 'fixture-report.json', {'status': exported['status'], 'contexts': contexts,
                                     'negative_results_retained': True, 'model_calls': 0, 'remote_jobs': 0,
                                     'export': exported, 'independent_model_review': 'not performed'})
    return exported


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--run', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.run), indent=2))
