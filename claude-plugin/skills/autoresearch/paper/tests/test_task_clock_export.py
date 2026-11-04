"""Real offline exports retain the evidence needed by the logical task clock."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.runtime import Controller, Refusal, file_hash
from run_fixture import run, put


class TaskClockExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name) / 'run'
        run(cls.root)
        cls.ctl = Controller(cls.root)
        cls.sources = []
        for minutes in (60, 120):
            prior = copy.deepcopy(cls.ctl.load())
            prior.pop('task_clock', None)
            prior['created_at'] = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
            name = put(cls.root, f'inherited/clock-{minutes}.json', prior)
            cls.sources.append({'path': name, 'sha256': file_hash(cls.root / name)})
            cls.ctl.restore_task_clock({'snapshot': name, 'sha256': cls.sources[-1]['sha256']}, f'clock-{minutes}')
        cls.export = cls.ctl.finalize('clock-export')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_export_zip_and_portable_recovery_include_every_clock_source(self):
        manifest = json.loads((self.root / self.export['manifest']).read_text())
        package = (self.root / self.export['manifest']).parent
        with zipfile.ZipFile(self.export['archive']) as archive:
            for source in self.sources:
                self.assertEqual(source['sha256'], manifest['artifacts'].get(source['path']))
                self.assertEqual((self.root / source['path']).read_bytes(), archive.read('artifacts/' + source['path']))
        self.assertEqual('verified', self.ctl.verify_export(self.export['manifest'])['status'])
        with tempfile.TemporaryDirectory() as directory:
            restored = Path(directory)
            shutil.copytree(package / 'artifacts', restored, dirs_exist_ok=True)
            shutil.copytree(package, restored / Path(self.export['manifest']).parent)
            (restored / '.paper').mkdir()
            shutil.copyfile(self.root / '.paper/checkpoint.json', restored / '.paper/checkpoint.json')
            ctl = Controller(restored)
            self.assertEqual('recovered', ctl.recover(self.export['manifest'])['status'])
            self.assertEqual(self.ctl.load()['task_clock'], ctl.load()['task_clock'])
            self.assertEqual(self.ctl.load()['usage_ledger'], ctl.load()['usage_ledger'])

    def test_verify_rejects_clock_source_omitted_from_an_export(self):
        original = (self.root / self.export['manifest']).parent
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'delivery/package'
            shutil.copytree(original, target)
            manifest = json.loads((target / 'manifest.json').read_text())
            source = self.sources[0]
            manifest['artifacts'].pop(source['path'], None)
            (target / 'artifacts' / source['path']).unlink(missing_ok=True)
            (target / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(Refusal, 'Task clock'):
                Controller(directory).verify_export('delivery/package/manifest.json')


if __name__ == '__main__': unittest.main()
