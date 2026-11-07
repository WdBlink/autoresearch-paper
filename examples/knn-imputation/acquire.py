#!/usr/bin/env python3
"""Acquire publisher evidence for the real, bounded imputation study."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.parse
import xml.etree.ElementTree as ET

import requests


SAMPLES = ['0359843', '0359577', '0320105', '0343619', '0339580', '0335852', '0334125', '0319784']
SOURCES = {
    'plos-criteria': 'https://journals.plos.org/plosone/s/criteria-for-publication',
    'plos-guidelines': 'https://journals.plos.org/plosone/s/submission-guidelines',
    'plos-latex': 'https://journals.plos.org/plosone/s/latex',
    'plos-start': 'https://journals.plos.org/plosone/s/getting-started',
    'plos-figures': 'https://journals.plos.org/plosone/s/figures',
    'peerj-scope': 'https://peerj.com/about/aims-and-scope/',
    'peerj-author': 'https://peerj.com/about/author-instructions/',
    'jmlr-scope': 'https://www.jmlr.org/author-info.html',
    'sklearn-impute': 'https://scikit-learn.org/stable/modules/impute.html',
    'sklearn-scale': 'https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html',
    'sklearn-pitfalls': 'https://scikit-learn.org/stable/common_pitfalls.html',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fetch(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_bytes()
    response = requests.get(url, timeout=75, headers={'User-Agent': 'Research workflow reproducibility study; public publisher materials'})
    response.raise_for_status()
    path.write_bytes(response.content)
    return response.content


def flat(node):
    return ' '.join(''.join(node.itertext()).split()) if node is not None else ''


def sample(root, item):
    number, suffix = item
    identifier = 'S%02d' % number
    doi = '10.1371/journal.pone.' + suffix
    url = 'https://journals.plos.org/plosone/article?id=' + doi
    base = root / 'venue/samples' / identifier
    xml_url = 'https://journals.plos.org/plosone/article/file?' + urllib.parse.urlencode({'id': doi, 'type': 'manuscript'})
    pdf_url = 'https://journals.plos.org/plosone/article/file?' + urllib.parse.urlencode({'id': doi, 'type': 'printable'})
    xml = fetch(xml_url, base / 'article.xml')
    pdf = fetch(pdf_url, base / 'article.pdf')
    if not pdf.startswith(b'%PDF-'):
        raise ValueError('Publisher did not return PDF: ' + doi)
    tree = ET.fromstring(xml)
    meta = tree.find('.//article-meta')
    date = next(n for n in meta.findall('pub-date') if n.get('pub-type') == 'epub')
    pub_date = '-'.join(flat(date.find(k)).zfill(2) for k in ('year','month','day'))
    authors = []
    for person in meta.findall('.//contrib[@contrib-type="author"]'):
        name = person.find('name')
        if name is not None:
            authors.append(flat(name.find('given-names')) + ' ' + flat(name.find('surname')))
        elif person.find('collab') is not None:
            authors.append(flat(person.find('collab')))
    visuals = []
    for tag in ('fig', 'table-wrap'):
        for node in tree.findall('.//' + tag):
            visuals.append({'id': node.get('id'), 'kind': 'figure' if tag == 'fig' else 'table',
                            'label': flat(node.find('label')), 'caption': flat(node.find('caption')),
                            'content': flat(node),
                            'graphic': next((n.get('{http://www.w3.org/1999/xlink}href') for n in node.iter('graphic')), None)})
    metadata = {'id': identifier, 'doi': doi, 'url': url, 'title': flat(meta.find('.//article-title')),
                'authors': authors, 'publication_date': pub_date, 'accepted': flat(meta.find('.//date[@date-type="accepted"]')),
                'journal': flat(tree.find('.//journal-title')), 'license': flat(meta.find('.//license')),
                'xml_url': xml_url, 'pdf_url': pdf_url, 'xml_sha256': sha(xml), 'pdf_sha256': sha(pdf), 'visuals': visuals}
    (base / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    body = [metadata['title'], '; '.join(authors), pub_date, doi, metadata['journal'], metadata['license']]
    for node in tree.findall('.//abstract') + tree.findall('./body'):
        body.append(flat(node))
    (base / 'article.txt').write_text('\n\n'.join(body) + '\n')
    acceptance = '\n'.join([metadata['title'], doi, metadata['journal'], 'Published: ' + pub_date,
                              'Accepted: ' + metadata['accepted'], metadata['license'], 'Publisher JATS: ' + xml_url])
    (base / 'acceptance.txt').write_text(acceptance + '\n')
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args(); root = args.run.resolve()
    with ThreadPoolExecutor(max_workers=3) as pool:
        records = list(pool.map(lambda item: sample(root,item), enumerate(SAMPLES, 1)))
    (root/'venue/sample-catalog.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
    sources = []
    # Save HTML bytes and visible source text. Failed alternatives remain failures.
    from bs4 import BeautifulSoup
    for key, url in SOURCES.items():
        try:
            data = fetch(url, root/'materials/sources'/f'{key}.html')
            soup = BeautifulSoup(data, 'html.parser')
            for node in soup(['script','style','nav','footer']): node.decompose()
            text = soup.get_text('\n', strip=True)
            text_path = root/'materials/sources'/f'{key}.txt'; text_path.write_text(text+'\n')
            sources.append({'id':key,'url':url,'status':'retrieved','path':str(text_path.relative_to(root)), 'sha256':sha(text_path.read_bytes())})
        except (requests.RequestException,ValueError) as error:
            sources.append({'id':key,'url':url,'status':'unavailable','error':str(error)})
    (root/'materials/source-catalog.json').write_text(json.dumps({'retrieved_at':datetime.now(timezone.utc).isoformat(),'sources':sources},indent=2)+'\n')
    print(json.dumps([{'id':r['id'],'title':r['title'],'publication_date':r['publication_date'],'figures':sum(v['kind']=='figure' for v in r['visuals']),'tables':sum(v['kind']=='table' for v in r['visuals'])} for r in records],indent=2))


if __name__ == '__main__':
    main()
