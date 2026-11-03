"""/api/ai/* blueprint behaviour through a Flask test client (no network, no real engines)."""
import tests._isolation  # noqa: F401  (must precede application imports)
import sys
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

import routes_ai
from ai_core import engines, hardware, models
from tests._ai_support import HIGH_INFO, IsolatedAIMixin
from tests.test_ai_media import FakeKeyring


class RoutesAITests(IsolatedAIMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        app = Flask(__name__)
        routes_ai.register_ai_routes(app)
        self.client = app.test_client()
        for target, attribute, value in ((hardware, 'detect', MagicMock(return_value=HIGH_INFO)),
                                         (engines.ollama, 'tags', MagicMock(return_value=[])),
                                         (engines.ollama, 'version', MagicMock(return_value=None)),
                                         (engines.comfy, 'running', MagicMock(return_value=False)),
                                         (models.requests, 'head', MagicMock(side_effect=models.requests.Timeout())),
                                         (models.requests, 'get', MagicMock(side_effect=models.requests.Timeout()))):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        keyring = patch.dict(sys.modules, {'keyring': FakeKeyring()})
        keyring.start()
        self.addCleanup(keyring.stop)

    def test_profile_reports_hardware_roles_and_bundle(self):
        data = self.client.get('/api/ai/profile').get_json()
        self.assertEqual(data['profile'], 'gpu_high')
        self.assertEqual(set(data['roles']), {'helper', 'translator', 'vision', 'speech'})
        self.assertFalse(data['roles']['helper']['available'])
        self.assertEqual(data['roles']['helper']['setup_hint'], 'qwen3:14b')
        self.assertEqual(data['roles']['speech']['setup_hint'], 'whisper-large-v3-turbo')
        self.assertIn('flux-schnell-q4', [b['id'] for b in data['bundle']])
        with patch.object(models, 'installed', side_effect=lambda i: i == 'whisper-large-v3-turbo'):
            data = self.client.get('/api/ai/profile').get_json()
        self.assertEqual(data['roles']['speech']['model'], 'large-v3-turbo')

    def test_profile_override(self):
        data = self.client.post('/api/ai/profile', json={'profile': 'laptop'}).get_json()
        self.assertEqual((data['profile'], data['detected_profile'], data['override']), ('laptop', 'gpu_high', 'laptop'))
        self.assertEqual(self.client.post('/api/ai/profile', json={'profile': None}).get_json()['profile'], 'gpu_high')
        response = self.client.post('/api/ai/profile', json={'profile': 'quantum'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.get_json())

    def test_catalog_and_notice(self):
        data = self.client.get('/api/ai/catalog').get_json()
        self.assertTrue(all('status' in item for item in data['items']))
        self.assertIn('latentsync', data['workflows'])
        notice = self.client.get('/api/ai/notice/inswapper-128').get_json()
        self.assertTrue(notice['non_commercial'])
        self.assertEqual(notice['size_source'], 'catalog')
        self.assertEqual([c['id'] for c in notice['companions']], ['insightface-buffalo-l'])
        missing = self.client.get('/api/ai/notice/nope')
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(self.client.get('/api/ai/notice/qwen3:14b').status_code, 200)

    def test_install_requires_consent_and_jobs(self):
        response = self.client.post('/api/ai/install', json={'item_id': 'inswapper-128'})
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.get_json()['consent_required'])
        self.assertEqual(response.get_json()['setup_hint'], 'inswapper-128')
        self.assertEqual(self.client.post('/api/ai/install', json={'item_id': 'nope'}).status_code, 400)
        self.assertEqual(self.client.post('/api/ai/install', data='junk').status_code, 400)
        with patch.object(models, 'start_install', return_value='job1'), \
                patch.object(models, 'job', return_value={'id': 'job1', 'state': 'running'}):
            response = self.client.post('/api/ai/install', json={'item_id': 'whisper-base', 'accept_license': True})
            self.assertEqual(response.status_code, 202)
            self.assertEqual(self.client.get('/api/ai/jobs/job1').get_json()['state'], 'running')
            with patch.object(models, 'cancel', return_value=True):
                self.assertTrue(self.client.post('/api/ai/jobs/job1/cancel').get_json()['cancelled'])
        self.assertEqual(self.client.get('/api/ai/jobs/missing').status_code, 404)
        self.assertEqual(self.client.post('/api/ai/jobs/missing/cancel').status_code, 404)

    def test_storage_and_remove_only_listed_files(self):
        storage = self.client.get('/api/ai/storage').get_json()
        self.assertEqual(storage['reclaimable'], [])
        response = self.client.post('/api/ai/remove', json={'path': str(self.root / 'precious.mp4')})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post('/api/ai/remove', json={}).status_code, 400)
        with patch.object(models, 'remove', return_value={'removed': ['x']}) as remove:
            self.assertEqual(self.client.post('/api/ai/remove', json={'item_id': 'whisper-base'}).get_json(), {'removed': ['x']})
        remove.assert_called_once_with('whisper-base')
        with patch.object(models, 'remove_reclaimable', return_value={'path': 'dup.gguf'}):
            self.assertEqual(self.client.post('/api/ai/remove', json={'id': 'abc'}).get_json(), {'removed': ['dup.gguf']})

    def test_engines(self):
        data = self.client.get('/api/ai/engines').get_json()
        self.assertEqual(set(data['engines']), {'ollama', 'builtin', 'comfy'})
        response = self.client.post('/api/ai/engines/comfy/start')
        self.assertEqual(response.status_code, 424)
        self.assertEqual(response.get_json()['setup_hint'], 'engine-comfyui')
        self.assertEqual(self.client.post('/api/ai/engines/comfy/stop').status_code, 200)
        self.assertEqual(self.client.post('/api/ai/engines/warp/start').status_code, 404)

    def test_settings_validation_and_persistence(self):
        data = self.client.post('/api/ai/settings', json={'roles': {'helper': 'qwen2.5:14b'}, 'cloud': {'fal': {'enabled': True}},
                                                          'idle_release_seconds': 120}).get_json()
        self.assertEqual(data['roles']['helper'], 'qwen2.5:14b')
        self.assertTrue(data['cloud']['fal']['enabled'])
        self.assertEqual(self.client.get('/api/ai/settings').get_json()['idle_release_seconds'], 120)
        for bad in ({'roles': {'chef': 'x'}}, {'cloud': {'fal': {'enabled': 'yes'}}}, {'idle_release_seconds': 1},
                    {'roles': []}):
            with self.subTest(bad=bad):
                self.assertEqual(self.client.post('/api/ai/settings', json=bad).status_code, 400)

    def test_cloud_key_is_never_echoed(self):
        secret = 'fal-super-secret-9876543210'
        response = self.client.post('/api/ai/cloud/key', json={'provider': 'fal', 'key': secret})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(secret, response.get_data(as_text=True))
        self.assertEqual(response.get_json()['masked'], '••••3210')
        self.assertNotIn(secret, self.client.get('/api/ai/settings').get_data(as_text=True))
        self.assertEqual(self.client.post('/api/ai/cloud/key', json={'provider': 'fal', 'key': ''}).status_code, 400)
        self.assertEqual(self.client.post('/api/ai/cloud/key', json={'provider': 'x', 'key': 'k'}).status_code, 400)
        self.assertFalse(self.client.post('/api/ai/cloud/key', json={'provider': 'fal', 'delete': True}).get_json()['has_key'])

    def test_models_list(self):
        with patch.object(engines.builtin, 'available', return_value=False):
            self.assertEqual(self.client.get('/api/ai/models').get_json(), {'models': []})


class AppRegistrationTests(unittest.TestCase):
    def test_blueprint_is_registered_and_protected(self):
        import app_local
        self.assertIn('ai', app_local.app.blueprints)
        client = app_local.app.test_client()
        self.assertEqual(client.get('/api/ai/profile').status_code, 403)


if __name__ == '__main__':
    unittest.main()
