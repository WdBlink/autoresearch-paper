#!/usr/bin/env python3
"""Close a genuinely reviewed run; judgments must be supplied by the host.

This helper does not generate reviews or decide that a manuscript is ready.
It preserves the actual request/decision outside the research document digest.
"""
import argparse
import json
from pathlib import Path

from control import invoke, put


def main(root, packet_path, decision_path, export_id):
    packet=json.loads((root/packet_path).read_text())
    decision=json.loads((root/decision_path).read_text())
    if decision.get('progress') != 'verified_progress' or not decision.get('reason'):
        raise ValueError('Supply the actual final host progress judgment and evidence-based reason')
    receipt=invoke(root,'commit','--packet',packet_path,'--operation-id','accept-real-review-final')
    if receipt.get('stage') != 'review': raise ValueError(receipt)
    evidence=[packet_path,packet['manuscript_pdf'],*packet['completion']['review'],*packet['completion']['revision'],*packet['completion']['snapshot']]
    request=invoke(root,'prepare-round','--evidence',*dict.fromkeys(evidence))
    request_path='control/round-decisions/final-request.json'
    put(root,request_path,request)
    decision['request_sha256']=request['request_sha256']
    output='control/round-decisions/final-decision.json'
    put(root,output,decision)
    # No ordinary research file is written between prepare and apply.
    print(invoke(root,'apply-round','--request',request_path,'--decision',output,
        '--operation-id','close-real-final-review-round')['status'])
    result=invoke(root,'finalize','--operation-id',export_id)
    verified=invoke(root,'verify-export','--manifest',result['manifest'])
    print(json.dumps({'delivery':result,'verification':verified},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--packet',required=True,help='Run-relative actual independent review packet')
    parser.add_argument('--decision',required=True,help='Run-relative actual host round judgment')
    parser.add_argument('--export-id',default='export-real-knn')
    args=parser.parse_args()
    main(args.run.resolve(),args.packet,args.decision,args.export_id)
