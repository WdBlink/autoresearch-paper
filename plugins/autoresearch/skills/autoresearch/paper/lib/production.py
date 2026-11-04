"""State-free research artifacts. Task facts come from packets, never examples."""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import zipfile

from .runtime import Refusal, file_hash, now, read_json, safe, tex_without_comments


def require(condition, message):
    if not condition:
        raise Refusal(message)


def write_once(root, name, content):
    """A retry may reuse identical bytes, but cannot replace a prior artifact."""
    target = safe(root, name, output=True)
    data = content.encode('utf-8') if isinstance(content, str) else content
    if target.exists():
        require(target.read_bytes() == data, 'Output differs; use a new versioned path: ' + name)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)
    return file_hash(target)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def observed(root, paths, **fields):
    return {**fields, 'artifacts': list(paths), 'hashes': {name: file_hash(safe(root, name)) for name in paths}}


def validate_options(kind, options):
    require(isinstance(options, dict), 'Production options must be an object')
    if kind == 'prepare_tex':
        require(set(options) <= {'graphics', 'inline_inputs', 'link_borders', 'flush_before', 'captions_after_first_reference'}, 'Unknown TeX preparation policy')
        for key in ['inline_inputs', 'captions_after_first_reference']:
            require(key not in options or type(options[key]) is bool, key + ' must be a boolean')
        require(options.get('graphics', 'keep') in {'keep', 'omit'}, 'graphics must be keep or omit')
        require(options.get('link_borders', 'template') in {'template', 'hidden'}, 'Unknown link border policy')
        markers = options.get('flush_before', [])
        require(isinstance(markers, list) and all(isinstance(x, str) and x for x in markers), 'flush_before needs literal markers')
    else:
        require(kind == 'export_image' and set(options) <= {'mode', 'dpi', 'min_dpi', 'width_pixels', 'height_pixels', 'max_bytes', 'background'}, 'Unknown image export policy')
        require(options.get('mode', 'preserve') in {'preserve', 'RGB', 'L'}, 'Unknown output color mode')
        for key in ['width_pixels', 'height_pixels', 'max_bytes']:
            require(key not in options or type(options[key]) is int and options[key] > 0, key + ' must be a positive integer')
        dpi = options.get('dpi', [])
        if type(dpi) in (float, int): dpi = [dpi, dpi]
        require(isinstance(dpi, (tuple, list)) and (len(dpi) == 2 or 'dpi' not in options) and
                all(type(x) in (float, int) and math.isfinite(x) and x > 0 for x in dpi), 'dpi must be a positive number or numeric pair')
        minimum = options.get('min_dpi', 1)
        require(type(minimum) in (float, int) and math.isfinite(minimum) and minimum > 0, 'min_dpi must be positive')


def environment(packet, root):
    executable = packet.get('python', sys.executable)
    dependencies = packet.get('dependencies', [])
    require(isinstance(dependencies, list), 'dependencies must be an array of distribution names')
    for item in dependencies:
        require(isinstance(item, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', item), 'Invalid distribution name')
    code = ('import importlib.metadata,json,sys\n'
            'out={"python":sys.version,"executable":sys.executable,"packages":{},"missing":[]}\n'
            'for name in json.loads(sys.argv[1]):\n'
            ' try: out["packages"][name]=importlib.metadata.version(name)\n'
            ' except importlib.metadata.PackageNotFoundError: out["missing"].append(name)\n'
            'print(json.dumps(out))\n')
    result = subprocess.run([str(executable), '-c', code, json.dumps(dependencies)], capture_output=True, text=True, timeout=30)
    require(result.returncode == 0, 'Environment probe failed: ' + result.stderr[-1500:])
    value = json.loads(result.stdout)
    value['status'] = 'missing_dependencies' if value['missing'] else 'available'
    value['checked_at'] = now()
    return value


def fetch_sources(packet, root):
    sources = packet.get('sources')
    require(isinstance(sources, list) and sources, 'sources must be a nonempty array')
    records = []
    for source in sources:
        name, url, kind = source['path'], source['url'], source['kind']
        require(urlsplit(url).scheme == 'https', 'Source acquisition requires an explicit HTTPS URL')
        require(kind in {'pdf', 'xml', 'json', 'zip', 'text', 'html'}, 'Unknown source kind')
        target = safe(root, name, output=True)
        record_name = source.get('record', name + '.source.json')
        record_path = safe(root, record_name, output=True)
        if target.exists():
            require(record_path.is_file(), 'Existing source lacks acquisition provenance: ' + name)
            record = read_json(record_path)
            require(record.get('url') == url and record.get('kind') == kind and record.get('sha256') == file_hash(target),
                    'Source/cache identity changed; use new versioned paths: ' + name)
            if source.get('sha256'):
                require(source['sha256'] == record['sha256'], 'Expected source hash differs')
            records.append({**record, 'reused': True})
            continue
        limit = source.get('max_bytes', 50 * 1024 * 1024)
        require(type(limit) is int and 0 < limit <= 512 * 1024 * 1024, 'Invalid source byte limit')
        request = urllib.request.Request(url, headers={'User-Agent': 'Autoresearch/ResearchWorkflow'})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(limit + 1)
            final_url = response.url
            content_type = response.headers.get('Content-Type')
        require(urlsplit(final_url).scheme == 'https' and len(data) <= limit and bool(data), 'Invalid or oversized source response')
        if kind == 'pdf':
            require(data.startswith(b'%PDF-'), 'PDF URL returned a non-PDF response')
        elif kind == 'xml':
            ET.fromstring(data)
        elif kind == 'json':
            json.loads(data)
        elif kind == 'zip':
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                require(archive.testzip() is None, 'Source ZIP CRC failed')
        else:
            data.decode('utf-8')
        sha = hashlib.sha256(data).hexdigest()
        require(not source.get('sha256') or source['sha256'] == sha, 'Expected source hash differs')
        record = {'path': name, 'url': url, 'resolved_url': final_url, 'kind': kind, 'sha256': sha,
                  'fetched_at': now(), 'content_type': content_type, 'bytes': len(data)}
        write_once(root, name, data)
        write_once(root, record_name, json_bytes(record))
        records.append({**record, 'reused': False})
    return {'sources': records, 'meaning': 'Acquired bytes and provenance; content relevance and source authority require host review'}


def reading_index(packet, root, *, check=False):
    samples = packet.get('samples')
    require(isinstance(samples, list) and samples, 'reading-index needs actual samples')
    target = packet.get('reading_index', packet.get('target'))
    require(isinstance(target, str), 'Declare reading_index or target')
    index_directory = safe(root, target, output=True).parent
    lines = ['# Representative-paper reading index', '',
             'Counts describe the supplied records. Visual reading and semantic judgments remain attributed declarations.', '']
    totals = {'papers': len(samples), 'figures': 0, 'tables': 0, 'facets_or_blocks': 0}
    seen = set()
    for sample in samples:
        identity = sample['id']
        require(isinstance(identity, str) and identity not in seen, 'Duplicate or invalid sample ID')
        seen.add(identity)
        design = read_json(safe(root, sample['analysis'])) if sample.get('analysis') else sample.get('design')
        require(isinstance(design, dict), 'Sample needs its actual design or analysis path: ' + identity)
        figures, tables = design.get('figures'), design.get('tables')
        require(isinstance(figures, list) and isinstance(tables, list), 'Missing per-visual records: ' + identity)
        for item in figures + tables:
            require(isinstance(item, dict), 'Visual record must be an object: ' + identity)
            require(isinstance(item.get('panels', []), list), 'Visual panels must be an array')
        facets = sum(len(item.get('panels', [])) for item in figures + tables)
        totals['figures'] += len(figures); totals['tables'] += len(tables); totals['facets_or_blocks'] += facets
        pdf = safe(root, sample['pdf'])
        lines += [f'## {identity}: {sample.get("title", identity)}', '',
                  f'{len(figures)} figures; {len(tables)} tables; {facets} facets or semantic blocks.', '',
                  f'[Source PDF]({Path(os.path.relpath(pdf, index_directory)).as_posix()})', '']
        for kind, items in [('figure', figures), ('table', tables)]:
            for item in items:
                require(all(isinstance(item.get(key), str) and item[key].strip() for key in
                            ['id', 'question', 'claim', 'evidence', 'design_takeaway', 'limitations']),
                        'Incomplete per-visual reading: ' + identity)
                lines += [f'### {item["id"]} ({kind})', '', item['question'], '', item['claim'], '',
                          'Evidence: ' + item['evidence'], '', 'Design: ' + item['design_takeaway'], '',
                          'Limitations: ' + item['limitations'], '']
                page = item.get('page')
                if page is not None:
                    require(type(page) is int and page > 0, 'Invalid visual page: ' + item['id'])
                    relative_pdf = Path(os.path.relpath(pdf, index_directory)).as_posix()
                    lines += [f'[PDF page {page}]({relative_pdf}#page={page})', '']
                observed_page = item.get('observed_page')
                if observed_page is not None:
                    require(type(observed_page) is int and observed_page > 0, 'Invalid observed visual page')
                    relative_pdf = Path(os.path.relpath(pdf, index_directory)).as_posix()
                    lines += [f'[Observed PDF page {observed_page}]({relative_pdf}#page={observed_page})', '']
                for field, label in [('observed_caption', 'Observed caption'),
                                     ('caption_measurement_note', 'Caption measurement correction'),
                                     ('measurement_revision', 'Measurement revision')]:
                    if field in item:
                        require(isinstance(item[field], str), label + ' must be text')
                        lines += [label + ': ' + item[field], '']
                if 'locator' in item:
                    require(isinstance(item['locator'], str), 'Visual locator must be text')
                    lines += ['Locator: ' + item['locator'], '']
                if 'panel_measurement_note' in item:
                    require(isinstance(item['panel_measurement_note'], str), 'Panel correction must be text')
                    lines += ['Panel measurement correction: ' + item['panel_measurement_note'], '']
                panels = item.get('panels', [])
                require(isinstance(panels, list), 'Visual panels must be an array')
                labels = set()
                for panel in panels:
                    require(isinstance(panel, dict) and all(isinstance(panel.get(key), str) and panel[key].strip()
                            for key in ['label', 'question', 'claim', 'evidence', 'design_takeaway', 'limitations']),
                            'Incomplete per-panel reading: ' + item['id'])
                    require(panel['label'] not in labels, 'Duplicate panel label: ' + item['id'])
                    labels.add(panel['label'])
                    lines += [f'#### {item["id"]} / {panel["label"]}', '', panel['question'], '', panel['claim'], '',
                              'Evidence: ' + panel['evidence'], '', 'Design: ' + panel['design_takeaway'], '',
                              'Limitations: ' + panel['limitations'], '']
                    if 'locator' in panel:
                        require(isinstance(panel['locator'], str), 'Panel locator must be text')
                        lines += ['Locator: ' + panel['locator'], '']
        declaration = sample.get('visual_read', design.get('visual_read'))
        lines += ['Reading declaration: ' + json.dumps(declaration, ensure_ascii=False, sort_keys=True), '']
    lines[2:2] = [f"{totals['papers']} papers, {totals['figures']} figures, {totals['tables']} tables, "
                  f"{totals['facets_or_blocks']} facets or semantic blocks.", '']
    content = '\n'.join(lines) + '\n'
    if check:
        require(safe(root, target).read_bytes() == content.encode(), 'Reading index differs from actual per-visual records')
    else:
        write_once(root, target, content)
    return observed(root, [target], counts=totals)


def image_bytes(root, source, target, options):
    try:
        from PIL import Image
    except ImportError as error:
        raise Refusal('Image export needs installed Pillow') from error
    validate_options('export_image', options)
    path = safe(root, source)
    suffix = Path(target).suffix.lower()
    require(suffix in {'.tif', '.tiff', '.png'}, 'Export images as TIFF or PNG')
    with Image.open(path) as original:
        original.load()
        image = original.copy()
        original_dpi = original.info.get('dpi')
    mode = options.get('mode', 'preserve')
    require(mode in {'preserve', 'RGB', 'L'}, 'Unknown output color mode')
    transforms = []
    if mode != 'preserve' and 'A' in image.getbands():
        if image.getchannel('A').getextrema() != (255, 255):
            require('background' in options, 'Nonopaque alpha requires an explicit background; do not discard information')
            background = Image.new('RGBA', image.size, options['background'])
            background.alpha_composite(image.convert('RGBA')); image = background
            transforms.append('composite on the declared background')
        else:
            transforms.append('remove all-opaque alpha')
    if mode != 'preserve' and mode != image.mode:
        image = image.convert(mode); transforms.append('convert to ' + mode)
    dpi = options.get('dpi', original_dpi)
    if isinstance(dpi, (float, int)):
        dpi = [dpi, dpi]
    require(dpi is not None and len(dpi) == 2, 'Declare positive DPI when the source has no resolution metadata')
    try:
        dpi = tuple(float(x) for x in dpi)
    except (ValueError, TypeError) as error:
        raise Refusal('Invalid source resolution metadata') from error
    require(all(math.isfinite(x) and x > 0 for x in dpi), 'Invalid source resolution metadata')
    output = io.BytesIO()
    image.save(output, format='PNG' if suffix == '.png' else 'TIFF', dpi=dpi,
               **({'compression': 'tiff_lzw'} if suffix != '.png' else {}))
    data = output.getvalue()
    with Image.open(io.BytesIO(data)) as encoded:
        encoded.load()
        measured = {'pixels': list(encoded.size), 'mode': encoded.mode,
                    'dpi': [float(x) for x in encoded.info['dpi']], 'bytes': len(data)}
        require(encoded.tobytes() == image.tobytes(), 'Lossless export changed pixel values')
    for key, index in [('width_pixels', 0), ('height_pixels', 1)]:
        if key in options:
            require(measured['pixels'][index] == options[key], key + ' differs from the declared policy')
    if 'min_dpi' in options:
        require(min(measured['dpi']) + .01 >= options['min_dpi'], 'Export resolution is below the declared minimum')
    if 'max_bytes' in options:
        require(len(data) <= options['max_bytes'], 'Export exceeds the declared byte limit')
    return data, {'source': source, 'source_sha256': file_hash(path), 'target': target, 'observed': measured,
                  'transforms': transforms, 'resized': False, 'font_inspection': 'not inferred from raster pixels'}


def export_image(packet, root):
    data, record = image_bytes(root, packet['source'], packet['target'], packet.get('options', {}))
    write_once(root, packet['target'], data)
    return observed(root, [packet['target']], **record)


def tex_bytes(root, source, options):
    validate_options('prepare_tex', options)
    seen = set()
    inputs = {}
    def live(text):
        # Preserve offsets, so inline comments cannot become executable inputs.
        result = []
        for line in text.splitlines(keepends=True):
            for match in re.finditer('%', line):
                backslashes = len(line[:match.start()]) - len(line[:match.start()].rstrip('\\'))
                if backslashes % 2 == 0:
                    line = line[:match.start()] + ''.join('\n' if c == '\n' else ' ' for c in line[match.start():])
                    break
            result.append(line)
        return ''.join(result)
    def rewrite(pattern, transform, text):
        for match in reversed(list(re.finditer(pattern, live(text), re.S))):
            text = text[:match.start()] + transform(match) + text[match.end():]
        return text
    def expand(name):
        require(name not in seen, 'Cyclic TeX input')
        seen.add(name)
        path = safe(root, name)
        text = path.read_text()
        inputs[name] = file_hash(path)
        if options.get('inline_inputs') or options.get('graphics') == 'omit':
            require(not re.search(r'\\verb\b|\\begin\{(?:verbatim|lstlisting|minted)\}', live(text)),
                    'Materialize verbatim/code environments before literal TeX transformations')
        if options.get('inline_inputs', False):
            pattern = r'\\(?:input|include)(?![A-Za-z])\s*\{([^{}\\]+)\}'
            clean = tex_without_comments(text)
            require(len(re.findall(pattern, clean)) == len(re.findall(r'\\(?:input|include)(?![A-Za-z])', clean)),
                    'Materialize dynamic or unbraced TeX inputs before preparing a variant')
            def replace(match):
                child = (path.parent / match.group(1)).with_suffix('.tex') if not Path(match.group(1)).suffix else path.parent / match.group(1)
                require(child.resolve().is_relative_to(root.resolve()), 'TeX input escapes run')
                return expand(child.resolve().relative_to(root.resolve()).as_posix())
            text = rewrite(pattern, replace, text)
        seen.remove(name)
        return text
    text = expand(source)
    policy = options.get('graphics', 'keep')
    require(policy in {'keep', 'omit'}, 'graphics must be keep or omit')
    if policy == 'omit':
        text = rewrite(r'\\includegraphics\*?(?:\[[^\]]*\])?\s*\{[^{}\\]+\}', lambda match: '', text)
        require('\\includegraphics' not in tex_without_comments(text), 'Dynamic graphics must be materialized before omission')
    if options.get('captions_after_first_reference', False):
        require(policy == 'omit', 'Caption relocation is for an explicitly selected no-graphics variant')
        pattern = r'\\begin\{figure\*?\}(?:\[[^\]]*\])?.*?\\end\{figure\*?\}'
        blocks = []
        for match in re.finditer(pattern, live(text), re.S):
            block = text[match.start():match.end()]
            labels = re.findall(r'\\label\{([^{}\\]+)\}', live(block))
            require(len(labels) == 1, 'Each relocated figure needs exactly one literal label')
            blocks.append((labels[0], block))
        require(len(blocks) == len(re.findall(r'\\begin\{figure\*?\}', live(text))), 'Unsupported figure environment')
        text = rewrite(pattern, lambda match: '', text)
        insertions = {}
        for label, block in blocks:
            reference = re.search(r'\\(?:ref|autoref)\{'+re.escape(label)+r'\}', live(text))
            require(reference is not None, 'Relocated figure has no literal reference: ' + label)
            ending = re.search(r'\n[ \t]*\n', text[reference.end():])
            require(ending is not None, 'Use an explicit paragraph break after the first figure reference')
            position = reference.end() + ending.end()
            insertions.setdefault(position, []).append(block)
        for position, blocks_at_position in sorted(insertions.items(), reverse=True):
            text = text[:position] + '\n\n'.join(blocks_at_position) + '\n\n' + text[position:]
    borders = options.get('link_borders', 'template')
    require(borders in {'template', 'hidden'}, 'Unknown link border policy')
    if borders == 'hidden':
        require(text.count('\\begin{document}') == 1, 'Need one explicit document start')
        text = text.replace('\\begin{document}', '\\ifdefined\\hypersetup\\hypersetup{hidelinks}\\fi\n\\begin{document}')
    markers = options.get('flush_before', [])
    require(isinstance(markers, list), 'flush_before must be literal source markers')
    for marker in markers:
        require(isinstance(marker, str) and marker and text.count(marker) == 1, 'Float boundary marker must occur exactly once')
        text = text.replace(marker, '\\clearpage\n' + marker)
    return text.encode(), inputs


def prepare_tex(packet, root):
    data, inputs = tex_bytes(root, packet['source'], packet.get('options', {}))
    require(packet['source'] != packet['target'], 'Keep the source and create a versioned TeX variant')
    write_once(root, packet['target'], data)
    return observed(root, [packet['target']], input_hashes=inputs, policy=packet.get('options', {}),
                    meaning='Mechanical source transformation; compile and inspect the actual PDF separately')


def inspect_pdf(packet, root):
    source = safe(root, packet['source'])
    require(source.read_bytes().startswith(b'%PDF-'), 'Expected an actual PDF')
    executable = shutil.which('pdftoppm')
    require(executable, 'PDF page inspection needs pdftoppm (Poppler), including visible annotations')
    dpi = packet.get('dpi', 120)
    require(type(dpi) is int and 36 <= dpi <= 600, 'Inspection DPI must be between 36 and 600')
    pages = packet.get('pages')
    if pages is not None:
        require(isinstance(pages, list) and pages and len(pages) == len(set(pages)) and all(type(p) is int and p > 0 for p in pages), 'Invalid page selection')
    directory = packet['directory']
    safe(root, directory + '/report.json', output=True)
    artifacts = []
    with tempfile.TemporaryDirectory(prefix='research-pdf-') as temp:
        if pages is None:
            subprocess.run([executable, '-r', str(dpi), '-png', str(source), str(Path(temp)/'page')], check=True, capture_output=True, timeout=120)
        else:
            for page in pages:
                subprocess.run([executable, '-f', str(page), '-l', str(page), '-r', str(dpi), '-png', str(source), str(Path(temp)/'page')],
                               check=True, capture_output=True, timeout=60)
        for path in sorted(Path(temp).glob('*.png')):
            name = directory + '/' + path.name
            write_once(root, name, path.read_bytes()); artifacts.append(name)
    require(artifacts, 'PDF rendering produced no selected pages')
    details = {'font_spans': 'unavailable: optional PyMuPDF is not installed', 'links': []}
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            fitz = None
    if fitz is not None:
        spans, links = [], []
        with fitz.open(source) as document:
            selected = pages or list(range(1, len(document)+1))
            for number in selected:
                require(number <= len(document), 'Requested page exceeds PDF length')
                page = document[number-1]
                for block in page.get_text('dict')['blocks']:
                    for line in block.get('lines', []):
                        for span in line['spans']:
                            spans.append({'page': number, **{k: span[k] for k in ['text', 'font', 'size', 'flags', 'bbox']}})
                for link in page.get_links():
                    links.append({'page': number, 'xref': link.get('xref'), 'rect': list(link['from']),
                                  'uri': link.get('uri'), 'border': document.xref_get_key(link['xref'], 'Border') if link.get('xref') else None})
        details = {'font_spans': spans, 'links': links}
    report = {'source': packet['source'], 'source_sha256': file_hash(source), 'renderer': 'Poppler pdftoppm with annotations',
              'dpi': dpi, 'pages_requested': pages or 'all', 'rendered_files': artifacts,
              'visual_review': 'not performed by this program; the host must actually view these pages', **details}
    name = directory + '/report.json'
    write_once(root, name, json_bytes(report)); artifacts.append(name)
    return observed(root, artifacts, report=name, visual_review='required')


def bibliography(packet, root):
    """Use given/family components when known; never infer a compound surname."""
    entries = packet['entries']; seen = set(); rendered = []; identities = []; source_hashes = {}
    require(isinstance(entries, list) and entries, 'bibliography needs actual entries')
    fields = {'title', 'year', 'journal', 'booktitle', 'howpublished', 'url', 'doi', 'volume', 'number', 'pages', 'note', 'publisher'}
    for entry in entries:
        require(isinstance(entry, dict) and set(entry) <= fields | {'key', 'kind', 'authors', 'jats', 'metadata'},
                'Unknown bibliography field; keep internal data in metadata')
        key = entry['key']; kind = entry.get('kind', 'article')
        require(isinstance(key, str) and re.fullmatch(r'[A-Za-z0-9_.:-]+', key) and key not in seen, 'Invalid or duplicate citation key')
        require(kind in {'article', 'inproceedings', 'book', 'misc', 'techreport'}, 'Unknown bibliography entry kind')
        seen.add(key)
        authors = []
        if entry.get('jats'):
            xml = ET.fromstring(safe(root, entry['jats']).read_bytes())
            source_hashes[entry['jats']] = file_hash(safe(root, entry['jats']))
            authors = [{'family': item.findtext('name/surname'), 'given': item.findtext('name/given-names', '')}
                       for item in xml.findall('.//article-meta/contrib-group/contrib') if item.get('contrib-type') == 'author']
        else:
            authors = entry['authors']
        names = []
        for author in authors:
            if isinstance(author, str):
                require(author.strip(), 'Empty author'); names.append(author)
            else:
                require(set(author) == {'family', 'given'} and isinstance(author['family'], str) and author['family'].strip() and isinstance(author['given'], str),
                        'Authors need literal family/given components from source evidence')
                names.append(author['family'] + (', ' + author['given'] if author['given'] else ''))
        require(names and entry.get('title') and type(entry.get('year')) is int, 'Missing bibliography identity')
        values = {'author': ' and '.join(names), **{k: v for k, v in entry.items() if k in fields}}
        for value in values.values():
            require(type(value) in (str, int) and '\n' not in str(value) and '\r' not in str(value), 'Invalid multiline BibTeX field')
        def field_value(key, value):
            text = str(value)
            if key in {'url', 'doi'}:
                require(not re.search(r'[\\{}\s]', text), 'URL/DOI must be a literal identifier, not TeX')
                return text
            escaped = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}', '%': r'\%', '&': r'\&',
                       '_': r'\_', '#': r'\#', '$': r'\$', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
            return ''.join(escaped.get(character, character) for character in text)
        rendered.append('@' + kind + '{' + key + ',\n' + ''.join(f'  {k} = {{{field_value(k, v)}}},\n' for k, v in values.items()) + '}\n')
        identities.append({'key': key, 'authors': names, 'title': entry['title'], 'year': entry['year']})
    write_once(root, packet['target'], '\n'.join(rendered))
    return observed(root, [packet['target']], identities=identities, source_hashes=source_hashes,
                    meaning='Formatting and explicit name components only; source verification and citation support remain separate')


def revision_record(packet, root):
    changes = packet.get('changes', [])
    require(isinstance(changes, list) and (changes or packet.get('initial_draft') is True), 'Declare actual changes or an explicit initial_draft')
    records = []
    for change in changes:
        require(change['before'] != change['after'] and isinstance(change.get('reason'), str) and change['reason'].strip(),
                'A revision needs a preserved baseline, distinct output and actual reason')
        before = safe(root, change['before']); safe(root, change['after'])
        records.append({'baseline': {'path': change['before'], 'sha256': file_hash(before)},
                        'after': change['after'], 'reason': change['reason']})
    write_once(root, packet['target'], json_bytes({'status': 'revised' if records else 'initial_draft', 'changes': records}))
    return observed(root, [packet['target']], changes=len(records))


TOOLS = {'environment': environment, 'source-fetch': fetch_sources, 'reading-index': reading_index,
         'image-export': export_image, 'tex-prepare': prepare_tex, 'pdf-inspect': inspect_pdf, 'bibliography': bibliography,
         'revision-record': revision_record}


def run(name, packet, root):
    if name == 'statistics':
        from .science import render_statistics
        root = Path(root).resolve()
        safe(root, packet['input'])
        for field in ['table', 'figure']:
            safe(root, packet[field], output=True)
        safe(root, packet['table'] + '.stats.json', output=True)
        safe(root, packet['figure'] + '.trace.json', output=True)
        return render_statistics(root, packet['input'], packet['table'], packet['figure'])
    require(name in TOOLS, 'Unknown artifact tool')
    require(isinstance(packet, dict), 'Artifact packet must be an object')
    try:
        return TOOLS[name](packet, Path(root).resolve())
    except (zipfile.BadZipFile, ET.ParseError) as error:
        raise Refusal('Invalid source document: ' + str(error)) from error
