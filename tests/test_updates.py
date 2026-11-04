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

    def test_ota_allows_only_download_engine_pin_bumps_in_requirements(self):
        (self.root / 'requirements.txt').write_text('Flask==3.0.0\nyt-dlp==2026.10.21\ngallery-dl==1.32.19\nyt-dlp-ejs==0.8.0\n')
        stage_archive(self.root, self.archive({
            'requirements.txt': 'Flask==3.0.0\nyt-dlp==2026.11.04\ngallery-dl==1.32.25\nyt-dlp-ejs==0.8.0\n'
        }), 'v5')
        self.assertTrue((self.root / '.updates/pending.json').exists())
        self.assertTrue(apply_pending(self.root))
        for bad_req in (
            'Flask==3.1.0\nyt-dlp==2026.11.04\ngallery-dl==1.32.25\nyt-dlp-ejs==0.8.0\n',
            'Flask==3.0.0\nyt-dlp==2026.11.04\ngallery-dl==1.32.25\nyt-dlp-ejs==0.9.0\n',
            'Flask==3.0.0\nyt-dlp==2026.11.04\n',
            'Flask==3.0.0\nyt-dlp==2026.11.04\ngallery-dl==1.32.25\nyt-dlp-ejs==0.8.0\nrequests==2.99.0\n',
        ):
            with self.assertRaisesRegex(ValueError, 'installer'):
                stage_archive(self.root, self.archive({'requirements.txt': bad_req}), 'v6')


class DownloadEngineUpdateTests(unittest.TestCase):
    def setUp(self):
        import os
        (Path(__file__).resolve().parents[1] / 'audit_artifacts').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'audit_artifacts')
        self._old_data_dir = os.environ.get('MEDIA_GRABBER_DATA_DIR')
        os.environ['MEDIA_GRABBER_DATA_DIR'] = self.temp.name

    def tearDown(self):
        import os
        if self._old_data_dir is None:
            os.environ.pop('MEDIA_GRABBER_DATA_DIR', None)
        else:
            os.environ['MEDIA_GRABBER_DATA_DIR'] = self._old_data_dir
        self.temp.cleanup()

    def test_only_yt_dlp_and_gallery_dl_are_allowed(self):
        import download_support as ds
        self.assertEqual(ds.validate_engine_packages(), ('yt-dlp', 'gallery-dl'))
        self.assertEqual(ds.validate_engine_packages(['gallery-dl']), ('gallery-dl',))
        for disallowed in ('flask', 'requests', 'torch', 'yt-dlp-ejs', 'yt-dlp==2026.10.21', '--extra-index-url', '', 123):
            with self.assertRaises(ValueError):
                ds.validate_engine_packages([disallowed])
            with self.assertRaises(ValueError):
                ds.update_download_engines([disallowed])
        with self.assertRaises(ValueError):
            ds.validate_engine_packages([])

    def test_real_verify_download_engines_dry_check(self):
        import download_support as ds
        versions = ds.verify_download_engines()
        self.assertTrue(versions.get('yt-dlp'))
        self.assertTrue(versions.get('gallery-dl'))

    def test_update_download_engines_succeeds_and_verifies(self):
        import subprocess
        import download_support as ds
        calls = []
        state = {'yt-dlp': '2026.10.21', 'gallery-dl': '1.32.19'}

        def fake_runner(cmd, **kwargs):
            calls.append(cmd)
            if '-m' in cmd and 'pip' in cmd and '--upgrade' in cmd:
                state['yt-dlp'] = '2026.11.04'
                state['gallery-dl'] = '1.32.20'
                return subprocess.CompletedProcess(cmd, 0, 'Successfully installed', '')
            if '-c' in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(state), '')
            if cmd[-2:] == ['yt_dlp', '--version']:
                return subprocess.CompletedProcess(cmd, 0, state['yt-dlp'] + '\n', '')
            if cmd[-2:] == ['gallery_dl', '--version']:
                return subprocess.CompletedProcess(cmd, 0, state['gallery-dl'] + '\n', '')
            raise AssertionError(f'Unexpected command: {cmd}')

        res = ds.update_download_engines(runner=fake_runner, now=1000.0)
        self.assertTrue(res['ok'])
        self.assertFalse(res['rolled_back'])
        self.assertEqual(res['previous_versions'], {'yt-dlp': '2026.10.21', 'gallery-dl': '1.32.19'})
        self.assertEqual(res['current_versions'], {'yt-dlp': '2026.11.04', 'gallery-dl': '1.32.20'})
        self.assertEqual(res['updated']['yt-dlp'], {'from': '2026.10.21', 'to': '2026.11.04'})
        pip_calls = [c for c in calls if 'pip' in c]
        self.assertEqual(len(pip_calls), 1)
        self.assertIn('--no-deps', pip_calls[0])
        self.assertEqual(pip_calls[0][-2:], ['yt-dlp', 'gallery-dl'])

    def test_update_rolls_back_to_previous_versions_on_verification_failure(self):
        import subprocess
        import download_support as ds
        calls = []
        state = {'yt-dlp': '2026.10.21', 'gallery-dl': '1.32.19', 'broken': False}

        def fake_runner(cmd, **kwargs):
            calls.append(cmd)
            if '-m' in cmd and 'pip' in cmd:
                if '--upgrade' in cmd:
                    state['yt-dlp'] = '2026.11.99'
                    state['broken'] = True
                else:
                    # Rollback pin install
                    assert 'yt-dlp==2026.10.21' in cmd and 'gallery-dl==1.32.19' in cmd
                    state['yt-dlp'] = '2026.10.21'
                    state['gallery-dl'] = '1.32.19'
                    state['broken'] = False
                return subprocess.CompletedProcess(cmd, 0, 'ok', '')
            if state['broken']:
                return subprocess.CompletedProcess(cmd, 1, '', 'ImportError: broken release')
            if '-c' in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps({'yt-dlp': state['yt-dlp'], 'gallery-dl': state['gallery-dl']}), '')
            if cmd[-2:] == ['yt_dlp', '--version']:
                return subprocess.CompletedProcess(cmd, 0, state['yt-dlp'] + '\n', '')
            if cmd[-2:] == ['gallery_dl', '--version']:
                return subprocess.CompletedProcess(cmd, 0, state['gallery-dl'] + '\n', '')
            raise AssertionError(f'Unexpected command: {cmd}')

        res = ds.update_download_engines(runner=fake_runner, now=2000.0)
        self.assertFalse(res['ok'])
        self.assertTrue(res['rolled_back'])
        self.assertTrue(res['rollback_ok'])
        self.assertEqual(res['current_versions'], {'yt-dlp': '2026.10.21', 'gallery-dl': '1.32.19'})
        self.assertIn('Rolled back', res['message'])

    def test_weekly_check_schedule_and_pypi_comparison(self):
        import download_support as ds
        from unittest.mock import MagicMock

        def fake_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            if 'yt-dlp' in url:
                resp.json.return_value = {'info': {'version': '2099.01.01'}, 'urls': [{'packagetype': 'bdist_wheel', 'size': 3500000}]}
            else:
                resp.json.return_value = {'info': {'version': '1.32.19'}, 'urls': [{'packagetype': 'bdist_wheel', 'size': 620000}]}
            return resp

        with patch('download_support.requests.get', side_effect=fake_get) as mock_get:
            first = ds.check_download_engines(force=False, now=10_000.0)
            self.assertTrue(first['checked_now'])
            self.assertTrue(first['has_update'])
            self.assertTrue(first['packages']['yt-dlp']['has_update'])
            self.assertEqual(mock_get.call_count, 2)

            # Within 7 days: skipped without hitting PyPI
            second = ds.check_download_engines(force=False, now=10_000.0 + 3 * 86400)
            self.assertFalse(second['checked_now'])
            self.assertFalse(second['weekly_check_due'])
            self.assertEqual(mock_get.call_count, 2)

            # After 7 days: weekly check runs again
            third = ds.check_download_engines(force=False, now=10_000.0 + 7 * 86400 + 1)
            self.assertTrue(third['checked_now'])
            self.assertEqual(mock_get.call_count, 4)

    def test_download_engine_routes_enforce_allowlist_and_return_status(self):
        import app_local
        client = app_local.app.test_client()
        client.get('/')
        with client.session_transaction() as sess:
            headers = {'X-Media-Token': sess['api_token']}
        st = client.get('/api/download_engines/status', headers=headers)
        self.assertEqual(st.status_code, 200)
        body = st.get_json()
        self.assertEqual(body['allowed_packages'], ['yt-dlp', 'gallery-dl'])

        bad = client.post('/api/download_engines/update', headers=headers, json={'packages': ['yt-dlp', 'flask']})
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(bad.get_json()['ok'])

        with patch('app_local.update_download_engines', return_value={'ok': True, 'rolled_back': False, 'message': 'Updated'}) as upd:
            ok = client.post('/api/download_engines/update', headers=headers, json={'packages': ['yt-dlp', 'gallery-dl']})
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.get_json()['ok'])
        upd.assert_called_once_with(packages=['yt-dlp', 'gallery-dl'])
