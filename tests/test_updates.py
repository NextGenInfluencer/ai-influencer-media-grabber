import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from safe_update import stage_archive, apply_pending
from ai_runtime import translate_srt

class UpdateTests(unittest.TestCase):
    def setUp(self):
        (Path(__file__).resolve().parents[1] / 'audit_artifacts').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'audit_artifacts')
        self.root = Path(self.temp.name)
        (self.root / 'requirements.txt').write_text('Flask==3.0.0')
        (self.root / 'app_local.py').write_text('VERSION = "old"')

    def tearDown(self):
        self.temp.cleanup()

    def archive(self, extras=None):
        data = {'app_local.py': 'VERSION = "new"', 'safe_update.py': '# fixture',
                'templates/index.html': 'new UI', 'requirements.txt': 'Flask==3.0.0'}
        data.update(extras or {})
        result = io.BytesIO()
        with zipfile.ZipFile(result, 'w') as archive:
            for name, content in data.items():
                archive.writestr('release/' + name, content)
        result.seek(0)
        return result

    def test_stage_does_not_change_live_files(self):
        stage_archive(self.root, self.archive(), 'v3')
        self.assertIn('old', (self.root / 'app_local.py').read_text())
        self.assertTrue(apply_pending(self.root))
        self.assertIn('new', (self.root / 'app_local.py').read_text())
        self.assertEqual(len(list((self.root / '.updates').glob('backup-*'))), 1)

    def test_rejects_traversal_and_invalid_code(self):
        for extra in ({'../escape.py': 'bad'}, {'app_local.py': 'not valid python!'}, {'static/../../escape': 'bad'}):
            with self.assertRaises((ValueError, SyntaxError)):
                stage_archive(self.root, self.archive(extra), 'v3')
            self.assertIn('old', (self.root / 'app_local.py').read_text())

    def test_dependency_change_requires_installer(self):
        with self.assertRaisesRegex(ValueError, 'installer'):
            stage_archive(self.root, self.archive({'requirements.txt': 'Flask==99'}), 'v3')
        self.assertFalse((self.root / '.updates/pending.json').exists())

    def test_missing_import_rejects_update_before_activation(self):
        with self.assertRaisesRegex(ValueError, 'startup check'):
            stage_archive(self.root, self.archive({'app_local.py': 'import missing_release_module_123'}), 'v3')
        self.assertIn('old', (self.root / 'app_local.py').read_text())

    def test_failed_activation_restores_previous_files(self):
        stage_archive(self.root, self.archive(), 'v3')
        import safe_update
        original = safe_update.os.replace
        def fail(source, destination):
            if str(destination).endswith('safe_update.py'):
                raise OSError('simulated disk failure')
            return original(source, destination)
        with patch('safe_update.os.replace', side_effect=fail):
            with self.assertRaises(OSError):
                apply_pending(self.root)
        self.assertIn('old', (self.root / 'app_local.py').read_text())
        self.assertFalse((self.root / 'safe_update.py').exists())

    def test_interrupted_activation_recovers(self):
        updates = self.root / '.updates'
        (updates / 'backup').mkdir(parents=True)
        (updates / 'backup/app_local.py').write_text('VERSION = "old"')
        (self.root / 'app_local.py').write_text('partial')
        (updates / 'journal.json').write_text(json.dumps({'backup': 'backup', 'files': [['app_local.py', True]]}))
        self.assertTrue(apply_pending(self.root))
        self.assertIn('old', (self.root / 'app_local.py').read_text())

    def test_translation_keeps_timing(self):
        source = '1\n00:00:01,000 --> 00:00:02,000\nBonjour\n\n2\n00:00:03,000 --> 00:00:04,000\nSalut\n'
        calls = []
        def generate(text, prompt, model):
            calls.append(text)
            return 'Hello'
        result = translate_srt(source, generate, 'test')
        self.assertEqual(calls, ['Bonjour', 'Salut'])
        self.assertIn('00:00:03,000 --> 00:00:04,000', result)
        self.assertEqual(result.count('Hello'), 2)
