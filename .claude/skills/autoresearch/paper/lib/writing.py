"""Load the user's complete prose guidance and only the selected case examples."""
from pathlib import Path
import hashlib
import re


def guidance(package, cases=()):
    root = Path(package) / 'references/writing'
    principles = root / 'academic-prose.md'
    examples = root / 'academic-prose-examples.md'
    text = examples.read_text()
    blocks = re.split(r'(?m)^## (E\d{2})\s*$', text)
    available = {blocks[n]: blocks[n+1].split('\n## ',1)[0] for n in range(1,len(blocks)-1,2)}
    cases = list(cases or [])
    if len(cases) > 2 or len(cases) != len(set(cases)) or not set(cases) <= set(available):
        raise ValueError('Select at most two distinct writing cases from E01–E14')
    return {'principles': principles.read_text(), 'case_index': blocks[0],
            'selected_cases': [{'id': key, 'text': available[key]} for key in cases],
            'hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (principles,examples)},
            'boundary': 'User-local teaching guidance. Examples are not facts or numeric results for this manuscript.'}
