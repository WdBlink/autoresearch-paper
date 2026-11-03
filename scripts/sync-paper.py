#!/usr/bin/env python3
"""Bundle the paper subcommand into the selected upstream skill distributions."""
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
for target in sys.argv[1:]:
    destination = root / target / 'paper'
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(root / 'foundation', destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copyfile(root / 'LICENSE', root / target / 'LICENSE')
    shutil.copyfile(root / 'LICENSE', destination / 'upstream-license.txt')
    upstream = destination / 'upstream'
    upstream.mkdir()
    for name in ('plan.md', 'reason.md'):
        shutil.copyfile(root / '.claude/commands/autoresearch' / name, upstream / name)
    shutil.copyfile(root / '.claude/commands/autoresearch/iterate.md', upstream / 'iterate.md')
    shutil.copyfile(root / '.claude/commands/autoresearch/iterate.md', upstream / 'autoresearch.md')
    shutil.copyfile(root / '.claude/skills/autoresearch/references/fork-and-flush.md', upstream / 'fork-and-flush.md')
