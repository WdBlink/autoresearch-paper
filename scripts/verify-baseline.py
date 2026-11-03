#!/usr/bin/env python3
"""Check the complete upstream tree and explicitly recorded local modifications."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'foundation/upstream-manifest.json').read_text())
patches = json.loads((root / 'foundation/upstream-patches.json').read_text())
allowed = set(patches['paths'])
missing, modes, unexpected, changed = [], [], [], []
for entry in manifest['files']:
    path = root / entry['path']
    if not path.exists() and not path.is_symlink():
        missing.append(entry['path']); continue
    data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
    actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if actual != entry['git_blob']:
        changed.append(entry['path'])
        if entry['path'] not in allowed: unexpected.append(entry['path'])
    expected_mode = entry['mode']
    if (expected_mode == '120000') != path.is_symlink() or (expected_mode == '100755' and not os.access(path, os.X_OK)):
        modes.append(entry['path'])
result = {'upstream': manifest['revision'], 'total': len(manifest['files']), 'unchanged': len(manifest['files']) - len(changed),
          'declared_patches': len(changed), 'missing': missing, 'mode_errors': modes, 'unexpected_changes': unexpected}
print(json.dumps(result, indent=2))
raise SystemExit(bool(missing or modes or unexpected))
