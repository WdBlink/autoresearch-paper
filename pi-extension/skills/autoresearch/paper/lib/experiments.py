"""Failure-complete evidence recording for the admitted paired-case adapter.

The caller owns its scientific model and scoring. This recorder owns only raw
attempt records and the frozen planned grid, never controller state or tuning.
"""
from contextlib import contextmanager
import math
from pathlib import Path

from .runtime import Refusal, file_hash, now, read_json, safe, identifier
from .production import json_bytes, require, write_once
from .science import _design


class MeasurementFailure(Exception):
    """A failure/stop explicitly defined by the frozen measurement protocol."""
    def __init__(self, reason, *, status='failed'):
        require(status in {'failed', 'stopped'} and isinstance(reason, str) and reason.strip(), 'Declare a measurement failure/stop reason')
        super().__init__(reason)
        self.status = status


class ExperimentRecorder:
    def __init__(self, root, design='experiment/design.json', results='experiment/results.json', raw_directory='experiment/raw'):
        self.root = Path(root).resolve()
        self.design_path, self.results_path = design, results
        self.design = _design(self.root, design)
        self.design_sha256 = file_hash(safe(self.root, design))
        self.started_at = now()
        self.raw_directory = raw_directory
        require(not safe(self.root, results, output=True).exists(), 'Preserve existing experiment results; use a new version')
        self.grid = [(case, seed, condition) for case in self.design['cases'] for seed in self.design['seeds'] for condition in self.design['conditions']]
        self.rows = {}
        for case, _, condition in self.grid:
            identifier(case); identifier(condition)
        for case, seed, condition in self.grid:
            require(not safe(self.root, f'{raw_directory}/{case}-{condition}-{seed}.json', output=True).exists(),
                    'Preserve prior raw attempts; choose a new raw_directory and results path')
        safe(self.root, raw_directory + '/probe.json', output=True)

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        if error is not None and not safe(self.root, self.results_path, output=True).exists():
            self.abort(error)
        elif error is None and not safe(self.root, self.results_path, output=True).exists():
            if self._measured_grid():
                self.finish()
            else:
                failure = Refusal('Experiment exited before every planned attempt completed')
                self.abort(failure)
                raise failure
        return False

    def _record(self, identity, status, value, **fields):
        require(identity in self.grid and identity not in self.rows, 'Unplanned or duplicate attempt')
        case, seed, condition = identity
        record = {'case_id': case, 'seed': seed, 'condition': condition, 'status': status, 'value': value, **fields}
        name = f'{self.raw_directory}/{case}-{condition}-{seed}.json'
        # An old raw record must never be overwritten by a rerun with the same identity.
        require(not safe(self.root, name, output=True).exists(), 'Raw attempt already exists: ' + name)
        write_once(self.root, name, json_bytes(record))
        self.rows[identity] = {k: record[k] for k in ['case_id', 'seed', 'condition', 'status', 'value']}
        self.rows[identity].update({'id': f'{case}-{condition}-{seed}', 'raw': name})
        for key in ['reason', 'failure_kind', 'attempted']:
            if key in record:
                self.rows[identity][key] = record[key]

    @contextmanager
    def attempt(self, case_id, seed, condition):
        identity = (case_id, seed, condition)
        require(identity in self.grid and identity not in self.rows, 'Unplanned or duplicate attempt')
        started = now()
        completed = False
        def complete(value, evidence=None):
            nonlocal completed
            require(not completed, 'Attempt completed twice')
            require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), 'Measurement must be finite')
            require(evidence is None or isinstance(evidence, dict), 'Attempt evidence must be an object')
            self._record(identity, 'completed', value, started_at=started, finished_at=now(), attempted=True,
                         evidence=evidence or {})
            completed = True
        try:
            yield complete
            require(completed, 'Attempt exited without a measured result')
        except MeasurementFailure as error:
            require(not completed, 'A completed attempt cannot become a measurement failure')
            self._record(identity, error.status, None, attempted=True, failure_kind='measurement',
                         reason=str(error), started_at=started, finished_at=now())
        except BaseException as error:
            if identity not in self.rows:
                self._record(identity, 'failed', None, attempted=True, failure_kind='operation',
                             reason=type(error).__name__ + ': ' + str(error), started_at=started, finished_at=now())
            raise

    def _finish(self, outcome, execution_status):
        require(file_hash(safe(self.root, self.design_path)) == self.design_sha256, 'Frozen design changed during execution')
        require(set(self.rows) == set(self.grid), 'All planned slots must have terminal records')
        document = {'design': self.design_path, 'design_sha256': self.design_sha256, 'started_at': self.started_at,
                    'finished_at': now(), 'reported_denominator': len(self.grid),
                    'attempted_count': sum(row.get('attempted', True) for row in self.rows.values()),
                    'execution_status': execution_status, 'outcome': outcome, 'runs': [self.rows[key] for key in self.grid]}
        write_once(self.root, self.results_path, json_bytes(document))
        return document

    def abort(self, error):
        reason = type(error).__name__ + ': ' + str(error)
        for identity in self.grid:
            if identity not in self.rows:
                self._record(identity, 'stopped', None, attempted=False, failure_kind='operation',
                             reason='Not started after operational failure: ' + reason, finished_at=now())
        return self._finish('inconclusive', 'failed')

    def finish(self, outcome='inconclusive'):
        require(outcome in {'positive', 'negative', 'inconclusive'}, 'Unknown scientific outcome')
        require(self._measured_grid(),
                'Incomplete/operationally failed grid is not a scientific result')
        return self._finish(outcome, 'completed')

    def _measured_grid(self):
        return len(self.rows) == len(self.grid) and all(row['status'] == 'completed' or row.get('failure_kind') == 'measurement' for row in self.rows.values())


def template(packet, root, package):
    """Emit only the stable recording envelope; the scientific operation is input."""
    design = packet.get('design', 'experiment/design.json')
    _design(root, design)
    text = f'''# Generated recording envelope. Fill the scientific operation before freezing.
import os
import sys
from pathlib import Path
sys.path.insert(0, os.environ.get('AUTORESEARCH_RUNTIME', {str(package)!r}))
from lib.experiments import ExperimentRecorder

def run(root, measure):
    # measure(case_id, seed, condition) must implement the approved experiment.
    with ExperimentRecorder(root, design={design!r}) as records:
        for case_id, seed, condition in records.grid:
            with records.attempt(case_id, seed, condition) as complete:
                value, evidence = measure(case_id, seed, condition)
                complete(value, evidence)
        return records.finish(outcome='inconclusive')
'''
    write_once(root, packet['target'], text)
    return {'path': packet['target'], 'sha256': file_hash(safe(root, packet['target'])),
            'scientific_operation': 'required from the approved task; this template does not generate results'}
