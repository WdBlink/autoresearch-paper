#!/usr/bin/env python3
"""Deliver using an actually issued round judgment; orchestration lives in the Skill."""
import argparse
import json
from pathlib import Path
from control import invoke

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--decision',required=True)
    parser.add_argument('--export-id',default='export')
    args=parser.parse_args()
    print(json.dumps(invoke(args.run,'deliver','--decision',args.decision,'--operation-id',args.export_id),ensure_ascii=False,indent=2))
