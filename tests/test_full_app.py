"""Exercise the real Flask app with isolated data and deterministic downloader results."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

class FullAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (Path(__file__).resolve().parents[1] / 'audit_artifacts').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'audit_artifacts')
        cls.root = Path(cls.temp.name)
        with patch.dict(os.environ, MEDIA_GRABBER_DATA_DIR=str(cls.root)):
            cls.module = importlib.import_module('app_local')
        cls.client = cls.module.app.test_client()
        cls.client.get('/')
        with cls.client.session_transaction() as session:
            cls.headers = {'X-Media-Token': session['api_token']}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_real_app_health_and_local_assets(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'https://cdn.tailwindcss.com', response.data)
        self.assertEqual(self.client.get('/api/health_check').json['version'], '2.4.0')
        with self.client.get('/static/vendor/tailwind-3.4.17.js') as asset:
            self.assertEqual(asset.status_code, 200)

    def test_playlist_processes_every_video(self):
        entries = []
        for number in range(2):
            path = self.root / f'video{number}.mp4'
            subprocess.run([self.module.imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-f', 'lavfi', '-i', 'color=red:size=64x64:rate=10', '-t', '0.3', str(path)], check=True, capture_output=True)
            entries.append({'filepath': str(path), 'title': f'Video {number}'})
        info = {'_type': 'playlist', 'entries': entries}
        class Downloader:
            def __init__(self, *args): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def extract_info(self, *args, **kwargs): return info
            def prepare_filename(self, info): return str(FullAppTests.root / 'playlist.mp4')
        with patch.object(self.module.yt_dlp, 'YoutubeDL', Downloader):
            response = self.client.post('/api/download', headers=self.headers, json={
                'url': 'https://example.com/playlist', 'task_id': 'playlist-test',
                'processing_options': {'extractFrame': True, 'identifySong': False}}, buffered=True)
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        self.assertNotIn('error', events[-1], events)
        self.assertTrue(events[-1]['done'])
        for number in range(2):
            self.assertTrue((self.root / f'video{number}_first_frame.png').exists())
        self.assertEqual(len(self.module.load_history()), 2)

    def test_deleted_history_stays_deleted(self):
        self.module.save_history([])
        self.assertEqual(self.module.load_history(), [])

    def test_update_refuses_active_job(self):
        self.module.increment_active_job()
        try:
            result = self.client.post('/api/apply_update', headers=self.headers)
            self.assertEqual(result.status_code, 409)
        finally:
            self.module.decrement_active_job()

