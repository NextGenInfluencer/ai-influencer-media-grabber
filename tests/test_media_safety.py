"""Regression tests using temporary generated media, without app startup side effects."""
import ast
import io
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
import uuid
import zipfile
from typing import Optional
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from job_process import check_cancelled
from ai_runtime import transcribe, translate_srt
import cleaner
import imageio_ffmpeg
from PIL import Image
from flask import Flask, Response, abort, jsonify, render_template, request, session, send_file, send_from_directory
from media_safety import MEDIA_EXTENSIONS, contained_path, safe_media_name, crop_filter
from reference_prep import register_reference_prep


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / 'audit_artifacts').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / 'audit_artifacts')
        cls.home = Path(cls.temp.name)
        cls.save = cls.home / 'Documents' / 'Media Grabber'
        cls.save.mkdir(parents=True)
        cls.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        cls.source = cls.home / 'sample.mp4'
        subprocess.run([cls.ffmpeg, '-y', '-f', 'lavfi', '-i', 'testsrc2=size=160x120:rate=24', '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '2', '-c:v', 'libx264', '-c:a', 'aac', str(cls.source)], check=True, capture_output=True)
        cls.app = Flask('regression', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
        cls.app.secret_key = 'test-key-only'
        cls.ns = dict(globals(), app=cls.app, DEFAULT_SAVE_DIR=str(cls.save), APP_VERSION='test', _approved_media_roots=set(), _approved_preview_files=set(), invalidate_gallery_cache=lambda: None, increment_active_job=lambda: None, decrement_active_job=lambda: None)
        class WhisperStub:
            def transcribe(self, *args, **kwargs):
                return {'segments': [{'start': 0, 'end': 0.5, 'text': 'test caption'}]}
        cls.ns['get_whisper'] = lambda: WhisperStub()
        names = {'parse_time_seconds', 'format_srt_timestamp', 'convert_media', 'is_safe_path', 'preview_file', 'serve_media', 'delete_gallery_item', 'protect_local_service', 'secure_local_response', 'index'}
        tree = ast.parse((ROOT / 'app_local.py').read_text(encoding='utf-8'))
        selected = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
        exec(compile(selected, str(ROOT / 'app_local.py'), 'exec'), cls.ns)
        register_reference_prep(cls.app, str(cls.save), lambda: None, lambda: None, lambda: None)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.client = self.app.test_client()
        with self.client.session_transaction() as s:
            s['authorized'] = True
            s['api_token'] = 'test-token'
        self.headers = {'X-Media-Token': 'test-token'}

    def convert(self, **options):
        data = {'files': (io.BytesIO(self.source.read_bytes()), options.pop('filename', 'clip.mp4')), 'resize': 'none', **options}
        with patch('os.path.expanduser', return_value=str(self.home)):
            r = self.client.post('/api/convert', data=data, headers=self.headers, buffered=True)
        events = [json.loads(line[6:]) for line in r.data.decode().splitlines() if line.startswith('data: ')]
        return r, events

    def test_trim_honors_codec_and_subtitles(self):
        r, events = self.convert(format='mp4_hevc', trimStart='0.5', trimEnd='1.5', export_subtitles='true')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(events[-1].get('done'), events)
        output = Path(events[-1]['file_path'])
        probe = subprocess.run([self.ffmpeg, '-i', str(output)], capture_output=True, text=True).stderr
        self.assertIn('Video: hevc', probe)
        self.assertIn('test caption', output.with_name(output.stem + '_subtitles.srt').read_text())

    def test_conversion_filename_stays_in_library(self):
        r, events = self.convert(filename='../outside.mp4', format='mp4', trimStart='0.2', trimEnd='0.7')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(contained_path(events[-1]['file_path'], self.save / 'Conversions'))

    def test_invalid_trim_rejected(self):
        for start, end in [('2', '1'), ('nan', '2'), ('-1', '2'), ('bad', '2')]:
            r, _ = self.convert(format='mp4', trimStart=start, trimEnd=end)
            self.assertEqual(r.status_code, 400)

    def test_invalid_format_rejected(self):
        r, _ = self.convert(format='../bad')
        self.assertEqual(r.status_code, 400)

    def test_idle_stream_stays_alive(self):
        class HeartbeatQueue(queue.Queue):
            def __init__(self):
                super().__init__()
                self.first = True
            def get(self, *args, **kwargs):
                if self.first:
                    self.first = False
                    raise queue.Empty()
                return super().get(*args, **kwargs)
        with patch.dict(self.ns, queue=SimpleNamespace(Queue=HeartbeatQueue, Empty=queue.Empty)):
            r, events = self.convert(format='mp4', trimStart='0.2', trimEnd='0.7')
        self.assertIn(b': working', r.data)
        self.assertTrue(events[-1].get('done'), events)

    def test_missing_subtitle_engine_is_failure(self):
        with patch.dict(self.ns, get_whisper=lambda: None), patch('traceback.print_exc'):
            _, events = self.convert(format='mp4', export_subtitles='true')
        self.assertIn('error', events[-1])

    def test_file_reads_restricted(self):
        outside = self.home / 'outside.txt'
        outside.write_text('fixture')
        r = self.client.get('/api/preview_file', query_string={'path': str(outside)})
        self.assertEqual(r.status_code, 403)
        r = self.client.get('/api/media/' + str(outside).replace('\\', '/'))
        self.assertIn(r.status_code, (403, 404, 308))

    def test_media_route_rejects_drive_path(self):
        r = self.client.get('/api/media/C:/outside.txt')
        self.assertIn(r.status_code, (403, 404))

    def test_external_media_requires_selection(self):
        r = self.client.get('/api/preview_file', query_string={'path': str(self.source)})
        self.assertEqual(r.status_code, 403)
        self.ns['_approved_preview_files'].add(os.path.realpath(self.source))
        try:
            r = self.client.get('/api/preview_file', query_string={'path': str(self.source)})
            self.assertEqual(r.status_code, 200)
            r.close()
        finally:
            self.ns['_approved_preview_files'].clear()

    def test_requests_require_session_and_token(self):
        r = self.app.test_client().get('/api/preview_file')
        self.assertEqual(r.status_code, 403)
        r = self.client.post('/api/convert', data={})
        self.assertEqual(r.status_code, 403)
        r = self.client.post('/api/convert', data={}, headers={**self.headers, 'Origin': 'https://evil.invalid'})
        self.assertEqual(r.status_code, 403)
        r = self.client.get('/', headers={'Host': 'evil.invalid'})
        self.assertEqual(r.status_code, 403)

    def test_homepage_bootstraps_token(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'name="media-token"', r.data)
        self.assertEqual(r.headers['X-Frame-Options'], 'DENY')

    def test_recycle_failure_preserves_file(self):
        file = self.save / 'keep.png'
        Image.new('RGB', (8, 8)).save(file)
        with patch('send2trash.send2trash', side_effect=OSError('unavailable')):
            r = self.client.post('/api/gallery/delete', json={'path': str(file)}, headers=self.headers)
        self.assertEqual(r.status_code, 500)
        self.assertTrue(file.exists())

    def test_animated_gif_is_preserved(self):
        file = self.home / 'animation.gif'
        Image.new('RGB', (20, 20), 'red').save(file, save_all=True, append_images=[Image.new('RGB', (20, 20), 'blue')], duration=100, loop=0)
        original = file.read_bytes()
        ok, message = cleaner.clean_photo(str(file))
        self.assertFalse(ok)
        self.assertIn('original preserved', message)
        self.assertEqual(file.read_bytes(), original)

    def test_orientation_applied(self):
        file = self.home / 'rotated.jpg'
        exif = Image.Exif(); exif[274] = 6
        Image.new('RGB', (120, 80), 'red').save(file, exif=exif)
        self.assertTrue(cleaner.clean_photo(str(file))[0])
        with Image.open(file) as im:
            self.assertGreater(im.height, im.width)
            self.assertIsNone(im.getexif().get(274))

    def test_small_photo(self):
        file = self.home / 'tiny.png'
        Image.new('RGB', (1, 1), 'red').save(file)
        self.assertTrue(cleaner.clean_photo(str(file))[0])

    def test_clean_webm_retains_container(self):
        file = self.home / 'sample.webm'
        subprocess.run([self.ffmpeg, '-y', '-i', str(self.source), '-c:v', 'libvpx-vp9', '-an', str(file)], check=True, capture_output=True)
        self.assertTrue(cleaner.clean_video(str(file))[0])
        self.assertEqual(file.read_bytes()[:4], bytes.fromhex('1a45dfa3'))

    def test_crop_fits_both_orientations(self):
        for size in [(100, 200), (200, 100)]:
            source = self.home / f'{size[0]}.png'
            Image.new('RGB', size).save(source)
            for w, h in [(4, 5), (9, 16), (16, 9)]:
                dest = self.home / f'crop_{size[0]}_{w}_{h}.png'
                subprocess.run([self.ffmpeg, '-y', '-i', str(source), '-vf', crop_filter(w, h), '-frames:v', '1', str(dest)], check=True, capture_output=True)
                with Image.open(dest) as im:
                    self.assertLessEqual(im.width, size[0])
                    self.assertLessEqual(im.height, size[1])

    def test_batch_same_names_preserve_sources(self):
        sources = []
        for folder, color in [('one', 'red'), ('two', 'blue')]:
            parent = self.home / folder; parent.mkdir(exist_ok=True)
            file = parent / 'same.png'; Image.new('RGB', (20, 20), color).save(file)
            sources.append(str(file))
        originals = [Path(p).read_bytes() for p in sources]
        output = self.save / 'batch'
        list(cleaner.run_batch_cleaner(sources, str(output)))
        self.assertEqual(len(list(output.rglob('*.png'))), 2)
        self.assertEqual([Path(p).read_bytes() for p in sources], originals)

    def test_unique_backups(self):
        first = cleaner.backup_file(str(self.source), str(self.save))
        second = cleaner.backup_file(str(self.source), str(self.save))
        self.assertNotEqual(first, second)
        self.assertEqual(Path(first).read_bytes(), self.source.read_bytes())

    def test_cleaner_deduplicates_content_not_paths(self):
        source = self.home / 'changing.png'
        output = self.save / 'dedup'
        Image.new('RGB', (20, 20), 'red').save(source)
        list(cleaner.run_batch_cleaner([str(source)], str(output)))
        list(cleaner.run_batch_cleaner([str(source)], str(output)))
        self.assertEqual(len(list(output.rglob('*.png'))), 1)
        Image.new('RGB', (20, 20), 'blue').save(source)
        list(cleaner.run_batch_cleaner([str(source)], str(output)))
        self.assertEqual(len(list(output.rglob('*.png'))), 2)

    def test_names(self):
        self.assertEqual(safe_media_name('../hello.mp4'), 'hello.mp4')
        self.assertEqual(safe_media_name('C:\\folder\\hello.mp4'), 'hello.mp4')
        self.assertEqual(safe_media_name('CON.mp4'), 'media.mp4')
        self.assertEqual(safe_media_name('Εικόνα.png'), 'Εικόνα.png')

    def prepare_reference(self, start='0'):
        r = self.client.post('/api/reference/prepare', data={'video': (io.BytesIO(self.source.read_bytes()), 'reference.mp4'), 'start_seconds': start}, headers=self.headers)
        self.assertEqual(r.status_code, 202, r.data)
        project_id = r.json['id']
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            data = self.client.get('/api/reference/' + project_id).json
            if data['state'] != 'processing':
                self.assertEqual(data['state'], 'ready', data)
                return data
            time.sleep(0.05)
        self.fail('Reference preparation did not finish')

    def test_first_frame_reference_preserves_video(self):
        data = self.prepare_reference()
        folder = Path(data['folder'])
        self.assertEqual((folder / data['video']).read_bytes(), self.source.read_bytes())
        self.assertEqual(data['dimensions'], [160, 120])
        expected = self.home / 'expected_frame.png'
        subprocess.run([self.ffmpeg, '-y', '-i', str(self.source), '-frames:v', '1', str(expected)], check=True, capture_output=True)
        self.assertEqual((folder / data['frame']).read_bytes(), expected.read_bytes())
        r = self.client.get('/api/media/Kling%20References/' + data['id'] + '/first_frame.png')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, expected.read_bytes())
        r.close()

    def test_later_reference_frame_matches_exported_video(self):
        data = self.prepare_reference('0.75')
        folder = Path(data['folder'])
        expected = self.home / 'expected_later.png'
        subprocess.run([self.ffmpeg, '-y', '-i', str(folder / data['video']), '-frames:v', '1', str(expected)], check=True, capture_output=True)
        self.assertEqual((folder / data['frame']).read_bytes(), expected.read_bytes())
        self.assertEqual((folder / 'original_video.mp4').read_bytes(), self.source.read_bytes())

    def test_edited_image_and_export(self):
        data = self.prepare_reference()
        url = '/api/reference/' + data['id']
        wrong = io.BytesIO(); Image.new('RGB', (80, 60), 'red').save(wrong, 'PNG')
        r = self.client.post(url + '/image', data={'image': (io.BytesIO(wrong.getvalue()), 'edited.png')}, headers=self.headers)
        self.assertEqual(r.status_code, 400)
        r = self.client.post(url + '/image', data={'image': (io.BytesIO(wrong.getvalue()), 'edited.png'), 'resize': 'true'}, headers=self.headers)
        self.assertEqual(r.status_code, 200, r.data)
        r = self.client.get(url + '/export')
        self.assertEqual(r.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(r.data)) as z:
            self.assertEqual(set(z.namelist()), {'reference_video.mp4', 'first_frame.png', 'influencer_image.png', 'README.txt'})
            with Image.open(io.BytesIO(z.read('influencer_image.png'))) as im:
                self.assertEqual(im.size, (160, 120))
        r.close()

    def test_reference_invalid_inputs(self):
        for start in ['-1', 'nan', 'Infinity']:
            r = self.client.post('/api/reference/prepare', data={'video': (io.BytesIO(b'fixture'), 'video.mp4'), 'start_seconds': start}, headers=self.headers)
            self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get('/api/reference/not-a-project').status_code, 404)


if __name__ == '__main__':
    unittest.main()
