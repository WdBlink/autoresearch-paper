"""Compatibility import for this case; transport and file rules live in the Skill."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'foundation'))
from lib.client import invoke, put
