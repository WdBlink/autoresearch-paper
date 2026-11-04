"""Small Python transport for task adapters; the public CLI owns all semantics."""
import json
from pathlib import Path
import subprocess
import sys

from .production import json_bytes, write_once
from .runtime import Refusal


def invoke(root, *args):
    command = [sys.executable, str(Path(__file__).resolve().parents[1]/'scripts/research.py'),
               '--run', str(Path(root).resolve()), *map(str, args)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise Refusal('Research CLI did not return JSON: ' + result.stderr[-1500:]) from error
    if result.returncode:
        raise Refusal(json.dumps(value, ensure_ascii=False))
    return value


def put(root, name, value):
    write_once(Path(root).resolve(), name, value if isinstance(value, str) else json_bytes(value))
    return name
