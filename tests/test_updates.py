import tests._isolation  # Must precede application imports.
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import safe_update
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

    def test_ai_dependency_change_requires_installer_and_preserves_live_files(self):
        (self.root / 'requirements-ai.txt').write_text('llama-cpp-python>=0.2.77\n')
        with self.assertRaisesRegex(ValueError, 'installer'):
            stage_archive(self.root, self.archive({'requirements-ai.txt':
                '-c requirements.txt\n--only-binary=llama-cpp-python\nllama-cpp-python>=0.2.77\n'}), '3.2.0')
        self.assertEqual((self.root / 'requirements-ai.txt').read_text(),'llama-cpp-python>=0.2.77\n')
        self.assertIn('old', (self.root / 'app_local.py').read_text())
        self.assertFalse((self.root / '.updates/pending.json').exists())

    def test_missing_import_rejects_update_before_activation(self):
        for source, message in [
            ('import missing_release_module_123', 'missing_release_module_123'),
            ('import sys; sys.stderr = sys.stdout; raise RuntimeError("installer required")', 'installer required'),
        ]:
            with self.assertRaisesRegex(ValueError, message):
                stage_archive(self.root, self.archive({'app_local.py': source}), 'v3')
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

    def manifest(self, **overrides):
        data = {'version': 1, 'patterns': ['*.py'], 'files': ['requirements.txt', 'release_manifest.json'],
                'directories': ['templates', 'static'], 'exclude': []}
        data.update(overrides)
        return json.dumps(data)

    def test_manifest_from_archive_installs_new_top_level_module(self):
        archive = self.archive({'app_local.py': 'import routes_new\nassert routes_new.READY',
                                'routes_new.py': 'READY = True', 'release_manifest.json': self.manifest()})
        stage_archive(self.root, archive, 'v5')
        self.assertTrue(apply_pending(self.root))
        self.assertEqual((self.root / 'routes_new.py').read_text(), 'READY = True')
        self.assertTrue((self.root / 'release_manifest.json').is_file())

    def test_manifest_is_authoritative_for_selection(self):
        archive = self.archive({'extra.py': 'X = 1', 'notes.txt': 'unlisted', 'templates/extra.html': 'x',
                                'release_manifest.json': self.manifest(patterns=[], files=[
                                    'app_local.py', 'safe_update.py', 'requirements.txt'])})
        stage_archive(self.root, archive, 'v5')
        files = json.loads((self.root / '.updates/pending.json').read_text(encoding='utf-8'))['files']
        self.assertNotIn('extra.py', files)
        self.assertNotIn('notes.txt', files)
        self.assertIn('templates/extra.html', files)

    def test_unsafe_manifest_entries_are_rejected(self):
        unsafe = [dict(files=['../escape.py']), dict(files=['/etc/passwd.txt']), dict(files=['C:/Windows/x.py']),
                  dict(files=['docs\\..\\x.md']), dict(files=['history.json']), dict(files=['tests/x.py']),
                  dict(files=['.updates/pending.json']), dict(directories=['..']), dict(directories=['tests']),
                  dict(directories=['static/../..']), dict(patterns=['../*.py']), dict(patterns=['*']),
                  dict(patterns=['*.exe']), dict(files='app_local.py'), dict(exclude=['../x'])]
        for overrides in unsafe:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    stage_archive(self.root, self.archive({'release_manifest.json': self.manifest(**overrides)}), 'v5')
                self.assertFalse((self.root / '.updates/pending.json').exists())
                self.assertEqual([p.name for p in (self.root / '.updates').iterdir()], [])
        with self.assertRaisesRegex(ValueError, 'JSON'):
            stage_archive(self.root, self.archive({'release_manifest.json': '{not json'}), 'v5')

    def test_old_archive_without_manifest_uses_built_in_list(self):
        archive = self.archive({'new_module.py': 'X = 1', 'static/app.js': 'x', 'payload.exe': 'MZ',
                                'history.json': '[]', 'static/fonts/custom/user.ttf': 'mine',
                                'carousel_studio.py': 'X = 1'})
        stage_archive(self.root, archive, 'v5')
        files = json.loads((self.root / '.updates/pending.json').read_text(encoding='utf-8'))['files']
        self.assertIn('new_module.py', files)
        self.assertIn('static/app.js', files)
        self.assertNotIn('payload.exe', files)
        self.assertNotIn('history.json', files)
        self.assertNotIn('static/fonts/custom/user.ttf', files)
        self.assertNotIn('caption_fonts', safe_update.DEFAULT_MANIFEST['directories'])

    def test_successful_updates_keep_only_two_backups(self):
        for version in range(4):
            stage_archive(self.root, self.archive({'app_local.py': f'VERSION = {version}'}), str(version))
            self.assertTrue(apply_pending(self.root))
        self.assertEqual(len(list((self.root / '.updates').glob('backup-*'))), 2)
        self.assertIn('VERSION = 3', (self.root / 'app_local.py').read_text())

    def test_concurrent_staging_is_rejected(self):
        self.assertTrue(safe_update._STAGE_LOCK.acquire(blocking=False))
        try:
            with self.assertRaises(safe_update.UpdateInProgress):
                stage_archive(self.root, self.archive(), 'v5')
        finally:
            safe_update._STAGE_LOCK.release()
        stage_archive(self.root, self.archive(), 'v5')
        self.assertTrue((self.root / '.updates/pending.json').exists())

    def test_ai_pack_dependency_files_are_compared(self):
        (self.root / 'requirements-ai-gpu.txt').write_text('torch==2.11.0+cu126\n')
        with self.assertRaisesRegex(ValueError, 'installer'):
            stage_archive(self.root, self.archive({'requirements-ai-gpu.txt': 'torch==2.12.0+cu126\n'}), 'v5')
        (self.root / 'requirements-ai-nodeps.txt').write_text('insightface==2.1\n')
        with self.assertRaisesRegex(ValueError, 'installer'):
            stage_archive(self.root, self.archive({'requirements-ai-nodeps.txt': 'insightface==2.2\n'}), 'v5')
        # Line endings alone are not a dependency change.
        stage_archive(self.root, self.archive({'requirements-ai-gpu.txt': 'torch==2.11.0+cu126\r\n'}), 'v5')

    def test_release_files_follow_repository_manifest(self):
        repo = Path(__file__).resolve().parents[1]
        files = safe_update.release_files(repo)
        for expected in ('app_local.py', 'storage_utils.py', 'safe_update.py', 'run.bat', 'install_ai.bat',
                         'launch-silent.vbs', 'ai_packs.json', 'release_manifest.json', 'templates/index.html',
                         *safe_update.DEPENDENCY_FILES):
            self.assertIn(expected, files)
        self.assertFalse(any(f.startswith(('tests/', '.git', 'static/fonts/custom/')) for f in files))
        self.assertFalse(any('__pycache__' in f for f in files))

    def test_translation_keeps_timing(self):
        source = '1\n00:00:01,000 --> 00:00:02,000\nBonjour\n\n2\n00:00:03,000 --> 00:00:04,000\nSalut\n'
        calls = []
        def translate(lines, target, **options):
            calls.extend(line['text'] for line in lines)
            return {line['id']: {'text': 'Hello', 'note': '', 'route': 'translator'} for line in lines}
        with patch('ai_core.translate.translate_lines', side_effect=translate):
            result = translate_srt(source, 'English')
        self.assertEqual(calls, ['Bonjour', 'Salut'])
        self.assertIn('00:00:03,000 --> 00:00:04,000', result)
        self.assertEqual(result.count('Hello'), 2)
