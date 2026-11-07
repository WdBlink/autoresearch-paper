"""Cross-design guard regression; single-design validation is separately tested."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import science


class SharedReceiptTests(unittest.TestCase):
    def check_collection(self, request_ids):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            registry = {}; rows = []; verified = []
            for i, provider_id in enumerate(request_ids):
                name = f'D{i}'
                registry[name] = {'id': name, 'path': name + '-design.json', 'sha256': '0'*64,
                                  'protocol': 'local_response_identification'}
                (root/(name + '-results.json')).write_text(json.dumps({'design_id':name, 'events':[]}))
                rows.append({'design_id': name, 'results': name + '-results.json', 'summary': name + '-summary.md'})
                verified.append([{'kind':'terminal', 'data':{'receipt':{'source':'provider_receipt',
                    'provider':'provider', 'model':'model', 'version':'v1', 'provider_request_id':provider_id}}}])
            packet = {'_plan':{'experiment_designs':[]}, 'experiments':rows}
            with patch.object(science, '_design_registry', return_value=registry), \
                 patch.object(science, '_validate_single_experiment', side_effect=verified):
                science._validate_experiment(packet, root)

    def test_distinct_paths_do_not_hide_reused_provider_response(self):
        with self.assertRaisesRegex(ValueError, 'cross-design provider request reuse'):
            self.check_collection(['provider-response-1', 'provider-response-1'])

    def test_distinct_provider_responses_remain_accepted(self):
        self.check_collection(['provider-response-1', 'provider-response-2'])
