"""Thin client for the public research CLI; it does not own workflow state."""
import json
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]


def put(root, name, value):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    return name


def invoke(root, *args):
    root = Path(root).resolve()
    arguments = list(map(str, args))
    # CLI JSON inputs are filesystem paths; artifact names inside those JSON
    # records are run-relative. Make the thin client's input convention explicit.
    for index in range(len(arguments)-1):
        if arguments[index] in {'--packet', '--brief', '--authorization', '--request', '--decision'}:
            path = Path(arguments[index+1])
            if not path.is_absolute(): arguments[index+1] = str(root/path)
    command = [sys.executable, str(REPO/'scripts/research.py'), '--run', str(root), *arguments]
    result = subprocess.run(command, capture_output=True, text=True)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        value = {'stdout':result.stdout,'stderr':result.stderr}
    # Output logging must not mutate the research documents whose digest a
    # prepare-round request just captured. Keep the transport trace outside it.
    log = root.parent/(root.name+'-cli'); log.mkdir(parents=True, exist_ok=True)
    (log/(str(time.time_ns())+'-'+str(args[0])+'.json')).write_text(json.dumps({'command':command,'exit_code':result.returncode,'response':value},ensure_ascii=False,indent=2)+'\n')
    if result.returncode:
        raise RuntimeError(json.dumps(value,ensure_ascii=False))
    return value
