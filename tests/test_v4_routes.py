"""Flask route tests for v4.0.0 features: Characters, Copilot, and Motion Studio."""
import tests._isolation  # Must precede application imports
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

import app_local


class TestV4Routes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (Path(__file__).resolve().parents[1] / 'audit_artifacts').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=tests._isolation.DATA_ROOT)
        cls.root = Path(cls.temp.name)
        cls.client = app_local.app.test_client()

        # Prime session and token
        cls.client.get('/')
        with cls.client.session_transaction() as session:
            cls.token = session['api_token']
            cls.headers = {'X-Media-Token': cls.token}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def _sample_png(self):
        buf = io.BytesIO()
        img = Image.new('RGB', (16, 16), color='blue')
        img.save(buf, format='PNG')
        buf.seek(0)
        return buf

    def test_characters_list_and_get(self):
        res = self.client.get('/api/characters')
        self.assertEqual(res.status_code, 200)
        data = res.json
        self.assertIn('characters', data)
        self.assertTrue(any(c['id'] == 'airi' for c in data['characters']))

    def test_character_post_requires_token(self):
        res = self.client.post('/api/characters/airi', json={'name': 'Airi Test'})
        self.assertEqual(res.status_code, 403)

        res = self.client.post('/api/characters/airi', json={'name': 'Airi Test'}, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json['character']['name'], 'Airi Test')

    def test_character_upload_validation_and_path_traversal(self):
        # 1. Disallowed image type (e.g. path traversal)
        data = {
            'type': '../../bad_dir',
            'file': (self._sample_png(), 'test.png')
        }
        res = self.client.post('/api/characters/airi/upload', data=data, headers=self.headers, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 400)
        self.assertIn('Invalid image type', res.json.get('error', ''))

        # 2. Corrupt / non-image file
        bad_data = {
            'type': 'portrait',
            'file': (io.BytesIO(b'not an image at all'), 'bad.png')
        }
        res = self.client.post('/api/characters/airi/upload', data=bad_data, headers=self.headers, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 400)
        self.assertIn('valid image', res.json.get('error', ''))

        # 3. Valid portrait upload
        good_data = {
            'type': 'portrait',
            'file': (self._sample_png(), 'portrait.png')
        }
        res = self.client.post('/api/characters/airi/upload', data=good_data, headers=self.headers, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json.get('url', '').startswith('/api/characters/airi/image/portrait'))

    def test_character_image_serving_and_traversal(self):
        # Path traversal in image name blocked
        res = self.client.get('/api/characters/airi/image/..%2f..%2fapp_local.py')
        self.assertIn(res.status_code, (400, 404))

    def test_copilot_models_route(self):
        res = self.client.get('/api/copilot/models')
        self.assertEqual(res.status_code, 200)
        self.assertIn('models', res.json)
        self.assertTrue(len(res.json['models']) >= 1)

    def test_copilot_chat_route(self):
        payload = {
            'messages': [{'role': 'user', 'content': 'apply the cyberpunk neon preset to my video'}],
            'model': 'qwen2.5:14b'
        }
        res = self.client.post('/api/copilot/chat', json=payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json
        self.assertIn('reply', data)
        self.assertTrue(len(data.get('actions', [])) >= 1)
        self.assertEqual(data['actions'][0]['action'], 'apply_style_preset')

    def test_motion_references_and_extract_routes(self):
        res = self.client.get('/api/motion/references')
        self.assertEqual(res.status_code, 200)
        self.assertIn('references', res.json)

        # Extract frame with missing file returns 400
        res = self.client.post('/api/motion/extract-frame', json={'video_path': 'nonexistent.mp4', 'timestamp': 1.0}, headers=self.headers)
        self.assertEqual(res.status_code, 400)

    def test_motion_render_validation(self):
        # Missing portrait image returns 400
        res = self.client.post('/api/motion/render', json={'source_image': 'missing.png'}, headers=self.headers)
        self.assertEqual(res.status_code, 400)


if __name__ == '__main__':
    unittest.main()
