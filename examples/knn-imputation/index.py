#!/usr/bin/env python3
"""Generate an index from a supplied actual-reading packet. The implementation is in the main Skill."""
import argparse
import json
from pathlib import Path
from control import invoke

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--packet',required=True)
    args=parser.parse_args()
    print(json.dumps(invoke(args.run, *['artifact', '--name', 'reading-index'], '--packet', args.packet),ensure_ascii=False,indent=2))
