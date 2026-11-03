"""AI installation must show a notice, pick the right pack and verify actual imports before reporting success."""
import tests._isolation
import copy
import io
import subprocess
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from assets import ai_setup

ROOT = Path(__file__).resolve().parents[1]
NVIDIA_12GB = {'vendor': 'nvidia', 'name': 'NVIDIA GeForce RTX 3080', 'vram_gb': 12.0}


class RuntimeChecks(unittest.TestCase):
    def test_missing_lazy_vision_api_is_not_reported_as_ready(self):
        with patch.object(ai_setup.importlib,'import_module',return_value=SimpleNamespace(Llama=object)):
            result=ai_setup.inspect_runtime()
        self.assertIn('BlipProcessor',result['transformers'])
        self.assertIn('align',result['lyric_alignment'])

    def test_build_tools_preparation_reports_failure(self):
        with patch.object(ai_setup.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='',stderr='offline')):
            with self.assertRaisesRegex(RuntimeError,'offline'):
                ai_setup.prepare_build_tools('python.exe','.')

    def test_native_load_failure_is_unavailable_not_status_crash(self):
        def load(name):
            if name == 'torch':
                raise OSError('Missing DLL')
            return SimpleNamespace(Llama=object)
        with patch.object(ai_setup.importlib, 'import_module', side_effect=load):
            result = ai_setup.inspect_runtime()
        self.assertIn('Missing DLL', result['torch'])
        self.assertIsNone(result['llama'])

    def test_verification_uses_new_process_and_rejects_failure(self):
        with patch.object(ai_setup.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            ai_setup.verify_runtime('python.exe', '.')
        self.assertEqual(run.call_args.args[0], ['python.exe','-m','assets.ai_setup'])
        with patch.object(ai_setup.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            ai_setup.verify_runtime('python.exe', '.', 'gpu')
        self.assertEqual(run.call_args.args[0], ['python.exe','-m','assets.ai_setup','--pack','gpu'])
        with patch.object(ai_setup.subprocess, 'run', return_value=SimpleNamespace(returncode=1,stdout='Missing DLL',stderr='')):
            with self.assertRaisesRegex(RuntimeError, 'Missing DLL'):
                ai_setup.verify_runtime('python.exe', '.')
        with patch.object(ai_setup.subprocess, 'run', side_effect=subprocess.TimeoutExpired('python',180)):
            with self.assertRaises(subprocess.TimeoutExpired):
                ai_setup.verify_runtime('python.exe', '.')

    def test_gpu_pack_verification_requires_cuda_provider(self):
        def runtime(providers, session_providers=None):
            active = providers if session_providers is None else session_providers
            session = SimpleNamespace(get_providers=lambda: active)
            module = SimpleNamespace(
                InferenceSession=lambda *args, **kwargs: session,
                get_available_providers=lambda: providers,
                preload_dlls=MagicMock(),
            )
            return lambda name: module
        with patch.object(ai_setup.importlib, 'import_module', side_effect=runtime(['CPUExecutionProvider'])):
            failure = ai_setup.inspect_runtime('gpu')['onnxruntime']
        self.assertIn('CUDAExecutionProvider is not available', failure)
        with patch.object(ai_setup.importlib, 'import_module',
                          side_effect=runtime(['CUDAExecutionProvider', 'CPUExecutionProvider'])):
            self.assertIsNone(ai_setup.inspect_runtime('gpu')['onnxruntime'])
        # If CUDAExecutionProvider is listed in get_available_providers() but session creation falls back to CPU, verification fails.
        with patch.object(ai_setup.importlib, 'import_module',
                          side_effect=runtime(['CUDAExecutionProvider', 'CPUExecutionProvider'],
                                              session_providers=['CPUExecutionProvider'])):
            fallback_failure = ai_setup.inspect_runtime('gpu')['onnxruntime']
        self.assertIn('fell back', fallback_failure)
        with patch.object(ai_setup.importlib, 'import_module', side_effect=runtime(['CPUExecutionProvider'])):
            self.assertIn('DmlExecutionProvider', ai_setup.inspect_runtime('directml')['onnxruntime'])
            self.assertIsNone(ai_setup.inspect_runtime('cpu')['onnxruntime'])

    def test_gpu_pack_requirements_pin_self_sufficient_cuda_cudnn(self):
        gpu_reqs = (ROOT / 'requirements-ai-gpu.txt').read_text(encoding='utf-8')
        self.assertIn('onnxruntime-gpu[cuda,cudnn]==1.31.1', gpu_reqs)

    def test_status_uses_find_spec_without_importing(self):
        with patch.object(ai_setup.importlib.util, 'find_spec', side_effect=lambda name: None if name == 'keyring' else object()), \
                patch.object(ai_setup.importlib, 'import_module') as load:
            status = ai_setup.installed_features()
        load.assert_not_called()
        self.assertEqual(set(status), set(ai_setup.MODULES))
        self.assertFalse(status['keyring'])
        self.assertTrue(status['torch'])

    def test_pack_choice_matrix(self):
        cases = [
            (NVIDIA_12GB, 'win32', 'gpu'),
            ({'vendor': 'nvidia', 'name': 'GTX 1650', 'vram_gb': 4.0}, 'win32', 'directml'),
            ({'vendor': 'nvidia', 'name': 'GTX 1650', 'vram_gb': 4.0}, 'linux', 'cpu'),
            ({'vendor': 'amd', 'name': 'AMD Radeon 780M', 'vram_gb': None}, 'win32', 'directml'),
            ({'vendor': 'intel', 'name': 'Intel UHD', 'vram_gb': None}, 'darwin', 'cpu'),
            (None, 'win32', 'cpu'),
        ]
        for gpu, platform, expected in cases:
            with self.subTest(gpu=gpu, platform=platform):
                pack, reason = ai_setup.choose_pack(gpu, platform=platform)
                self.assertEqual(pack, expected)
                self.assertTrue(reason)

    def test_nvidia_smi_and_adapter_detection(self):
        with patch.object(ai_setup.shutil, 'which', return_value='nvidia-smi'), \
                patch.object(ai_setup, '_run_quiet', return_value='NVIDIA GeForce GTX 1050, 2048\nNVIDIA GeForce RTX 3080, 12288\n'):
            self.assertEqual(ai_setup._nvidia_gpu(), NVIDIA_12GB)
        with patch.object(ai_setup.shutil, 'which', return_value=None):
            self.assertIsNone(ai_setup._nvidia_gpu())
        with patch.object(ai_setup.os, 'name', 'nt'), \
                patch.object(ai_setup, '_run_quiet', return_value='Microsoft Basic Display Adapter\nAMD Radeon(TM) Graphics\n'):
            self.assertEqual(ai_setup._windows_gpu()['vendor'], 'amd')

    def test_notice_itemizes_sizes_licenses_and_reason(self):
        with patch.object(ai_setup, 'detect_gpu', return_value=NVIDIA_12GB):
            info = ai_setup.notice(ROOT)
            manual = ai_setup.notice(ROOT, 'cpu')
        self.assertEqual(info['pack'], 'gpu')
        self.assertIn('RTX 3080', info['reason'])
        self.assertNotIn('NVIDIA NVIDIA', info['reason'])
        ids = {item['id'] for item in info['items']}
        self.assertIn('torch-cuda', ids)
        self.assertNotIn('torch-cpu', ids)
        self.assertEqual(info['approx_download_mb'], sum(item['approx_mb'] for item in info['items']))
        self.assertGreater(info['approx_download_mb'], 2500)
        self.assertTrue(all(item['license'] and item['source'] for item in info['items']))
        self.assertTrue(info['requires_accept'])
        self.assertEqual(info['requirements'], ['requirements-ai-gpu.txt', 'requirements-ai-nodeps.txt'])
        self.assertEqual(manual['pack'], 'cpu')
        self.assertIn('Selected manually', manual['reason'])
        self.assertLess(manual['approx_download_mb'], 500)
        with self.assertRaises(ValueError):
            ai_setup.notice(ROOT, 'quantum')

    def test_install_commands_use_pack_file_then_no_deps_file(self):
        commands = ai_setup.install_commands('python.exe', ROOT, 'directml')
        self.assertEqual(commands[0][-3:], ['--no-build-isolation', '-r', 'requirements-ai-directml.txt'])
        self.assertEqual(commands[1][-3:], ['--no-deps', '-r', 'requirements-ai-nodeps.txt'])
        with self.assertRaises(ValueError):
            ai_setup.install_commands('python.exe', ROOT, 'other')

    def test_pack_requirement_files_are_consistent(self):
        packs = ai_setup.load_packs(ROOT)
        for name, pack in packs['packs'].items():
            text = (ROOT / pack['requirements']).read_text(encoding='utf-8')
            self.assertIn('-r requirements-ai-common.txt', text, name)
        self.assertIn('-c requirements.txt', (ROOT / 'requirements-ai-common.txt').read_text(encoding='utf-8'))
        def torch_pins(filename):
            lines = (ROOT / filename).read_text(encoding='utf-8').splitlines()
            return sorted(line.split(';')[0].strip() for line in lines
                          if line.startswith('torch') and 'darwin"' not in line.replace('!= "darwin"', ''))
        self.assertEqual(torch_pins('requirements-ai-cpu.txt'), torch_pins('requirements-ai-directml.txt'))
        self.assertIn('-r requirements-ai-cpu.txt', (ROOT / 'requirements-ai.txt').read_text(encoding='utf-8'))
        for unused in ('diffusers', 'gradio', 'playwright', 'instaloader'):
            for path in ROOT.glob('requirements*.txt'):
                self.assertNotIn(unused, path.read_text(encoding='utf-8').lower(), path.name)

    def test_core_requirements_include_ytdlp_tls_impersonation(self):
        core = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
        self.assertIn('curl-cffi==0.16.3', core)
        self.assertIn('cffi==2.1.1', core)
        self.assertIn('pycparser==3.12', core)
        from yt_dlp.networking import _curlcffi
        self.assertTrue(hasattr(_curlcffi, 'CurlCFFIRH'))

    def test_cli_verify_and_install(self):
        with patch.object(ai_setup, 'inspect_runtime', return_value={name: None for name in ai_setup.MODULES}), \
                patch('builtins.print'):
            self.assertEqual(ai_setup.main([]), 0)
        with patch.object(ai_setup, 'detect_gpu', return_value=None), patch('builtins.input', return_value='no'), \
                patch.object(ai_setup.subprocess, 'run') as run, patch('builtins.print'):
            self.assertEqual(ai_setup.main(['--install']), 1)
        run.assert_not_called()
        with patch.object(ai_setup, 'detect_gpu', return_value=None), patch('builtins.input', return_value='YES'), \
                patch.object(ai_setup, 'prepare_build_tools'), patch.object(ai_setup, 'verify_runtime') as verify, \
                patch.object(ai_setup.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, \
                patch('builtins.print'):
            self.assertEqual(ai_setup.main(['--install', '--pack', 'gpu']), 0)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(verify.call_args.args[2], 'gpu')


class InstallerChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app_local
        cls.app = app_local
        cls.client = app_local.app.test_client()
        cls.client.get('/')
        with cls.client.session_transaction() as session:
            cls.headers = {'X-Media-Token': session['api_token']}

    def setUp(self):
        self.saved = copy.deepcopy(self.app.ai_installer_state)
        self.addCleanup(lambda: self.app.ai_installer_state.update(self.saved))
        for target, kwargs in ((ai_setup, {'attribute': 'prepare_build_tools'}),
                               (ai_setup, {'attribute': 'detect_gpu', 'return_value': None})):
            patcher = patch.object(target, kwargs.pop('attribute'), **kwargs)
            mock = patcher.start()
            self.addCleanup(patcher.stop)
            if not kwargs:
                self.prepare = mock

    @staticmethod
    def pip_process(output, code):
        def create(*args, **kwargs):
            process = MagicMock(stdout=io.StringIO(output))
            process.wait.return_value = code
            return process
        return create

    def test_build_tools_failure_stops_before_installation(self):
        self.prepare.side_effect=RuntimeError('Could not prepare AI installation tools')
        with patch.object(self.app.subprocess,'Popen') as process:
            self.app.run_ai_install_worker()
        process.assert_not_called()
        self.assertEqual(self.app.ai_installer_state['status'],'failed')
        self.assertFalse(self.app.ai_installer_state['is_installing'])

    def test_pip_success_requires_import_verification(self):
        for failure in (None, RuntimeError('Missing DLL')):
            with patch.object(self.app.subprocess,'Popen',side_effect=self.pip_process('Successfully installed fixture\n', 0)) as popen, \
                    patch.object(ai_setup,'verify_runtime',side_effect=failure) as verify:
                self.app.run_ai_install_worker()
            verify.assert_called_once()
            self.assertEqual(verify.call_args.args[2], 'cpu')
            self.assertEqual(popen.call_count, 2)
            self.assertIn('requirements-ai-cpu.txt', popen.call_args_list[0].args[0])
            self.assertIn('--no-deps', popen.call_args_list[1].args[0])
            self.assertFalse(self.app.ai_installer_state['is_installing'])
            self.assertEqual(self.app.ai_installer_state['status'], 'failed' if failure else 'complete')
            if failure:
                self.assertIn('Missing DLL', self.app.ai_installer_state['error'])

    def test_missing_requirements_and_pip_failure_never_report_complete(self):
        with patch.object(self.app.os.path,'exists',return_value=False):
            self.app.run_ai_install_worker()
        self.assertEqual(self.app.ai_installer_state['status'],'failed')
        self.assertIn('not found', self.app.ai_installer_state['error'])
        with patch.object(self.app.subprocess,'Popen',side_effect=self.pip_process('failed\n', 1)) as popen, \
                patch.object(ai_setup,'verify_runtime') as verify:
            self.app.run_ai_install_worker('gpu')
        verify.assert_not_called()
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(self.app.ai_installer_state['status'],'failed')

    def test_notice_route_and_accept_requirement(self):
        res = self.client.get('/api/install_ai/notice', headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json['pack'], 'cpu')
        self.assertTrue(res.json['items'])
        self.assertEqual(self.client.get('/api/install_ai/notice?pack=nope', headers=self.headers).status_code, 400)
        with patch.object(self.app, 'run_ai_install_worker') as worker:
            for body in (None, {}, {'accept': 'yes'}, {'accept': True, 'pack': 'nope'}):
                res = self.client.post('/api/install_ai', json=body, headers=self.headers)
                self.assertEqual(res.status_code, 400, body)
        worker.assert_not_called()

    def test_status_route_never_imports_ai_libraries(self):
        with patch.object(ai_setup, 'installed_features', return_value={'torch': True}) as features, \
                patch.object(ai_setup, 'inspect_runtime') as inspect:
            res = self.client.get('/api/ai_status', headers=self.headers)
        features.assert_called_once()
        inspect.assert_not_called()
        self.assertTrue(res.json['all_installed'])

    def wait_for_unlock(self):
        for _ in range(200):
            if not self.app._maintenance_lock.locked():
                return
            threading.Event().wait(0.05)
        self.fail('maintenance lock was not released')

    def test_install_and_update_share_a_lock(self):
        saved_updater = copy.deepcopy(self.app.app_updater_state)
        self.addCleanup(lambda: self.app.app_updater_state.update(saved_updater))
        # A held lock (e.g. a double click racing the busy flag) rejects both operations.
        self.assertTrue(self.app._maintenance_lock.acquire(blocking=False))
        try:
            for url, body in (('/api/install_ai', {'accept': True}), ('/api/apply_update', None)):
                res = self.client.post(url, json=body, headers=self.headers)
                self.assertEqual(res.status_code, 409, url)
                self.assertEqual(res.json['error'], self.app._MAINTENANCE_BUSY)
        finally:
            self.app._maintenance_lock.release()
        started, release = threading.Event(), threading.Event()
        def blocking_worker(*args):
            started.set()
            release.wait(10)
        for url, body, worker in (('/api/install_ai', {'accept': True, 'pack': 'cpu'}, 'run_ai_install_worker'),
                                  ('/api/apply_update', None, 'run_ota_update_worker')):
            started.clear()
            release.clear()
            with patch.object(self.app, worker, side_effect=blocking_worker):
                self.assertEqual(self.client.post(url, json=body, headers=self.headers).status_code, 200)
                self.assertTrue(started.wait(5))
                self.assertTrue(self.app._maintenance_lock.locked())
                release.set()
                self.wait_for_unlock()
            self.app.ai_installer_state['is_installing'] = False
            self.app.app_updater_state['is_updating'] = False

    def test_staging_invalidates_release_check_cache(self):
        release = {'has_update': True, 'latest_version': 'v99.0.0', 'error': None,
                   'zipball_url': f'https://api.github.com/repos/{self.app.GITHUB_REPO}/zipball/v99.0.0'}
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [b'zip-bytes']
        saved_state = copy.deepcopy(self.app.app_updater_state)
        self.addCleanup(lambda: self.app.app_updater_state.update(saved_state))
        self.app._update_check_cache.update(time=1e12, data={'has_update': True})
        with patch.object(self.app, 'fetch_latest_release', return_value=release), \
                patch('requests.get', return_value=response), patch('safe_update.stage_archive') as stage:
            self.app.run_ota_update_worker()
        stage.assert_called_once()
        self.assertEqual(self.app.app_updater_state['status'], 'complete')
        self.assertIsNone(self.app._update_check_cache['data'])
        self.assertEqual(self.app._update_check_cache['time'], 0.0)


if __name__ == '__main__':
    unittest.main()
