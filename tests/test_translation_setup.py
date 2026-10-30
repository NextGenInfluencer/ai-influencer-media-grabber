"""Model setup uses disposable files and mocked network responses, never user models."""
import tests._isolation
import hashlib
from contextlib import ExitStack
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from assets import lyric_translation as translation
from tests import test_lyric_tracks


class ModelSetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        self.destination = Path(self.directory.name)/'model.gguf'
        self.payload = b'isolated-model-fixture'
        self.response = MagicMock()
        self.response.__enter__.return_value = self.response
        self.response.iter_content.return_value = iter([self.payload[:8], self.payload[8:]])
        for target, value in [('EMBEDDED_MODEL', self.destination), ('MODEL_SIZE', len(self.payload)),
                              ('MODEL_SHA256', hashlib.sha256(self.payload).hexdigest())]:
            self.contexts.enter_context(patch.object(translation, target, value))
        self.contexts.enter_context(patch.object(translation, 'require_local_runtime'))
        self.get = self.contexts.enter_context(patch.object(translation.requests, 'get', return_value=self.response))
        self.progress = []

    def test_verified_download_and_existing_model_reuse(self):
        translation.install_model(self.progress.append)
        self.assertEqual(self.destination.read_bytes(), self.payload)
        self.assertIn('100%', self.progress[-1])
        self.assertFalse(list(self.destination.parent.glob('*.part')))
        translation.install_model(self.progress.append)
        self.get.assert_called_once()

    def test_corrupt_download_cleans_temporary_file(self):
        self.response.iter_content.return_value = iter([b'bad'])
        with self.assertRaisesRegex(ValueError, 'verification'):
            translation.install_model(self.progress.append)
        self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_existing_invalid_model_is_never_replaced(self):
        self.destination.write_bytes(b'user-file')
        with self.assertRaisesRegex(ValueError, 'left unchanged'):
            translation.install_model(self.progress.append)
        self.assertEqual(self.destination.read_bytes(), b'user-file')
        self.get.assert_not_called()

    def test_cancellation_cleans_partial_and_releases_lock(self):
        with patch.object(translation, 'check_cancelled', side_effect=[None, None, RuntimeError('Cancelled')]):
            with self.assertRaisesRegex(RuntimeError, 'Cancelled'):
                translation.install_model(self.progress.append)
        self.assertEqual(list(self.destination.parent.iterdir()), [])
        self.assertFalse(translation._install_lock.locked())

    def test_low_disk_and_concurrent_setup_do_not_download(self):
        with patch.object(translation.shutil, 'disk_usage', return_value=type('Disk', (), {'free':0})()):
            with self.assertRaisesRegex(ValueError, 'Free at least'):
                translation.install_model(self.progress.append)
        with translation._install_lock:
            with self.assertRaisesRegex(ValueError, 'already running'):
                translation.install_model(self.progress.append)
        self.get.assert_not_called()

    def test_oversize_and_network_failure_preserve_destination(self):
        for chunks in ([self.payload+b'x'], None):
            self.response.iter_content.return_value = iter(chunks or [])
            self.response.raise_for_status.side_effect = None if chunks else translation.requests.ConnectionError('offline')
            with self.assertRaises((ValueError, translation.requests.RequestException)):
                translation.install_model(self.progress.append)
            self.assertEqual(list(self.destination.parent.iterdir()), [])


class SetupWorkflowTests(unittest.TestCase):
    setUp = test_lyric_tracks.TrackWorkflowTests.setUp
    tearDown = test_lyric_tracks.TrackWorkflowTests.tearDown
    wait = test_lyric_tracks.TrackWorkflowTests.wait
    j = test_lyric_tracks.TrackWorkflowTests.j
    karaoke_project = test_lyric_tracks.TrackWorkflowTests.karaoke_project

    def test_setup_selects_model_without_changing_lyrics(self):
        pid, data = self.karaoke_project()
        with patch.object(translation, 'require_local_runtime'), patch.object(translation, 'install_model') as install:
            started = self.client.post(f'/api/captions/{pid}/translation-setup', json={'revision':data['revision']})
            self.assertEqual(started.status_code, 202)
            finished = self.wait(pid)
        install.assert_called_once()
        self.assertEqual(finished['cues'], data['cues'])
        self.assertEqual(finished['translation_settings']['model'], 'qwen3-4b-local')
        self.assertEqual(self.client.post(f'/api/captions/{pid}/translation-setup', json={'revision':data['revision']}).status_code, 409)

    def test_missing_runtime_is_actionable_before_job_starts(self):
        pid, data = self.karaoke_project()
        with patch.object(translation, 'require_local_runtime', side_effect=ValueError('Install the AI Engine Pack')):
            response = self.client.post(f'/api/captions/{pid}/translation-setup', json={'revision':data['revision']})
        self.assertEqual(response.status_code, 400)
        self.assertIn('AI Engine Pack', response.json['error'])
        self.assertEqual(self.client.get('/api/captions/'+pid).json['cues'], data['cues'])
