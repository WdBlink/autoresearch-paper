#!/usr/bin/env python3
"""Repository entry; the installed skill carries the same self-contained module."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[1] / 'foundation/scripts/research.py'), run_name='__main__')
