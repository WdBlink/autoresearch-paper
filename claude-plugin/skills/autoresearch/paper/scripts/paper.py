#!/usr/bin/env python3
"""Deterministic paper subcommand. See --help and references/runtime-contract.md."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.runtime import Controller, Refusal, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='New-format run directory, never a legacy active run')
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init'); init.add_argument('--brief', required=True)
    approve = sub.add_parser('approve'); approve.add_argument('--brief-sha256', required=True); approve.add_argument('--actor', required=True)
    sub.add_parser('context'); sub.add_parser('status')
    rd = sub.add_parser('read-material'); rd.add_argument('--path', required=True); rd.add_argument('--start', type=int, default=0); rd.add_argument('--end', type=int)
    prep = sub.add_parser('prepare-round'); prep.add_argument('--evidence', nargs='+', required=True)
    rnd = sub.add_parser('apply-round'); rnd.add_argument('--request', required=True); rnd.add_argument('--decision', required=True); rnd.add_argument('--operation-id', required=True)
    revise = sub.add_parser('revise-orders'); revise.add_argument('--packet', required=True); revise.add_argument('--reason', required=True); revise.add_argument('--operation-id', required=True)
    for name in ('commit', 'bind'):
        item = sub.add_parser(name); item.add_argument('--packet', required=True); item.add_argument('--operation-id', required=True)
    execute = sub.add_parser('execute'); execute.add_argument('--work-id', required=True); execute.add_argument('--operation-id', required=True)
    rewind = sub.add_parser('rewind'); rewind.add_argument('--stage', required=True); rewind.add_argument('--reason', required=True); rewind.add_argument('--operation-id', required=True)
    reconcile = sub.add_parser('reconcile'); reconcile.add_argument('--attempt', required=True); reconcile.add_argument('--outcome', required=True); reconcile.add_argument('--evidence', required=True); reconcile.add_argument('--operation-id', required=True)
    final = sub.add_parser('finalize'); final.add_argument('--operation-id', required=True)
    verify = sub.add_parser('verify-export'); verify.add_argument('--manifest', required=True)
    for name in ('fork-trigger', 'fork-plan'):
        fork = sub.add_parser(name); fork.add_argument('--config', required=True)
    create = sub.add_parser('fork-create'); create.add_argument('--repo', required=True); create.add_argument('--plan', required=True); create.add_argument('--destination', required=True)
    select = sub.add_parser('fork-select'); select.add_argument('--plan', required=True); select.add_argument('--candidates', required=True); select.add_argument('--incumbent-metric', type=float, required=True); select.add_argument('--promote-repo')
    args = parser.parse_args()
    ctl = Controller(args.run)
    try:
        if args.command.startswith('fork-'):
            from lib import exploration
            if args.command == 'fork-trigger': result = exploration.trigger(**read_json(args.config))
            elif args.command == 'fork-plan': result = exploration.request(**read_json(args.config))
            elif args.command == 'fork-create':
                repo = Path(args.repo).resolve()
                if ctl.root == repo or ctl.root.is_relative_to(repo):
                    raise Refusal('Keep the authoritative paper run outside an exploration checkout')
                result = exploration.create_worktrees(repo, read_json(args.plan), args.destination)
            elif args.promote_repo:
                repo = Path(args.promote_repo).resolve()
                if ctl.root == repo or ctl.root.is_relative_to(repo):
                    raise Refusal('Keep paper state outside the exploration checkout')
                result = exploration.promote(repo, read_json(args.plan), read_json(args.candidates), args.incumbent_metric)
            else: result = exploration.select(read_json(args.plan), read_json(args.candidates), args.incumbent_metric)
        elif args.command == 'init': result = ctl.init(read_json(args.brief))
        elif args.command == 'approve': result = ctl.approve(args.brief_sha256, args.actor)
        elif args.command == 'context': result = ctl.context()
        elif args.command == 'read-material': result = ctl.read_material(args.path, args.start, args.end)
        elif args.command == 'prepare-round': result = ctl.prepare_round(args.evidence)
        elif args.command == 'apply-round': result = ctl.apply_round(read_json(args.request), read_json(args.decision), args.operation_id)
        elif args.command == 'status':
            state = ctl.load(); result = {'stage': len(state['receipts']), 'stale': ctl.stale(state), 'approval': state['approval'], 'attempts': state['attempts'], 'delivery': state['delivery']}
        elif args.command == 'commit': result = ctl.commit(read_json(args.packet), args.operation_id)
        elif args.command == 'revise-orders': result = ctl.revise_orders(read_json(args.packet), args.reason, args.operation_id)
        elif args.command == 'bind': result = ctl.bind(read_json(args.packet), args.operation_id)
        elif args.command == 'execute': result = ctl.execute(args.work_id, args.operation_id)
        elif args.command == 'rewind': result = ctl.rewind(args.stage, args.reason, args.operation_id)
        elif args.command == 'reconcile': result = ctl.reconcile(args.attempt, args.outcome, args.evidence, args.operation_id)
        elif args.command == 'finalize': result = ctl.finalize(args.operation_id)
        else: result = ctl.verify_export(args.manifest)
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'refused', 'reason': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
