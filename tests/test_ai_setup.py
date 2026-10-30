"""AI installation must verify actual imports before reporting success."""
import tests._isolation
import copy
import io
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from assets import ai_setup


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
        with patch.object(ai_setup.subprocess, 'run', return_value=SimpleNamespace(returncode=1,stdout='Missing DLL',stderr='')):
            with self.assertRaisesRegex(RuntimeError, 'Missing DLL'):
                ai_setup.verify_runtime('python.exe', '.')
        with patch.object(ai_setup.subprocess, 'run', side_effect=subprocess.TimeoutExpired('python',180)):
            with self.assertRaises(subprocess.TimeoutExpired):
                ai_setup.verify_runtime('python.exe', '.')


class InstallerChecks(unittest.TestCase):
    def setUp(self):
        import app_local
        self.app = app_local
        self.saved = copy.deepcopy(self.app.ai_installer_state)
        self.addCleanup(lambda: self.app.ai_installer_state.update(self.saved))
        bootstrap = patch.object(ai_setup,'prepare_build_tools')
        self.prepare = bootstrap.start()
        self.addCleanup(bootstrap.stop)

    def test_build_tools_failure_stops_before_installation(self):
        self.prepare.side_effect=RuntimeError('Could not prepare AI installation tools')
        with patch.object(self.app.subprocess,'Popen') as process:
            self.app.run_ai_install_worker()
        process.assert_not_called()
        self.assertEqual(self.app.ai_installer_state['status'],'failed')
        self.assertFalse(self.app.ai_installer_state['is_installing'])

    def test_pip_success_requires_import_verification(self):
        for failure in (None, RuntimeError('Missing DLL')):
            process = MagicMock(stdout=io.StringIO('Successfully installed fixture\n'))
            process.wait.return_value = 0
            with patch.object(self.app.subprocess,'Popen',return_value=process), patch.object(ai_setup,'verify_runtime',side_effect=failure) as verify:
                self.app.run_ai_install_worker()
            verify.assert_called_once()
            self.assertFalse(self.app.ai_installer_state['is_installing'])
            self.assertEqual(self.app.ai_installer_state['status'], 'failed' if failure else 'complete')
            if failure:
                self.assertIn('Missing DLL', self.app.ai_installer_state['error'])

    def test_missing_requirements_and_pip_failure_never_report_complete(self):
        with patch.object(self.app.os.path,'exists',return_value=False):
            self.app.run_ai_install_worker()
        self.assertEqual(self.app.ai_installer_state['status'],'failed')
        process = MagicMock(stdout=io.StringIO('failed\n'))
        process.wait.return_value = 1
        with patch.object(self.app.subprocess,'Popen',return_value=process), patch.object(ai_setup,'verify_runtime') as verify:
            self.app.run_ai_install_worker()
        verify.assert_not_called()
        self.assertEqual(self.app.ai_installer_state['status'],'failed')
