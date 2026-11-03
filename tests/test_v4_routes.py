"""Flask route tests for personas, Copilot and AI Studio (honest engines, async jobs, path validation)."""
import tests._isolation  # Must precede application imports
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from PIL import Image

import app_local
import job_process
from ai_core.errors import AIUnavailable
from assets import ai_video_engine


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

    # ------------------------------------------------------------ helpers

    def _library_file(self, relative, data=b'data'):
        path = Path(app_local.DEFAULT_SAVE_DIR) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def _png_file(self, relative):
        path = Path(app_local.DEFAULT_SAVE_DIR) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (32, 32), color='purple').save(path, format='PNG')
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def _wait(self, job_id, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.client.get(f'/api/jobs/{job_id}').json
            if job['status'] != 'running':
                return job
            time.sleep(0.05)
        self.fail(f'job {job_id} did not finish')

    def _engines_installed(self):
        patcher = patch('routes_studio.models.installed', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    # ------------------------------------------------------------ copilot and page

    def test_copilot_models_route(self):
        models = [{'name': 'qwen3:14b', 'backend': 'ollama', 'capabilities': ['completion', 'tools']},
                  {'name': 'nomic-embed', 'backend': 'ollama', 'capabilities': ['embedding']}]
        with patch('copilot.llm.available_models', return_value=models), \
                patch('copilot.llm.cost', return_value={'available': True, 'model': 'qwen3:14b'}):
            res = self.client.get('/api/copilot/models')
        self.assertEqual(res.status_code, 200)
        self.assertEqual([m['name'] for m in res.json['models']], ['qwen3:14b'])
        self.assertEqual(res.json['helper']['model'], 'qwen3:14b')

    def test_video_studio_page(self):
        res = self.client.get('/video-studio')
        self.assertEqual(res.status_code, 200)
        page = res.get_data(as_text=True)
        self.assertIn('AI Studio', page)
        self.assertIn('Face Swap Video', page)
        self.assertIn('Performance', page)
        for fake in ('Wan 2.1 Ready', '3–5 s on any laptop', 'Motion Mimic', 'Together AI', 'facefusion'):
            self.assertNotIn(fake, page)

    def test_retired_fake_endpoints_are_gone(self):
        for path in ('/api/video-studio/models', '/api/video-studio/detect-local-engines'):
            self.assertEqual(self.client.get(path).status_code, 404)
        res = self.client.post('/api/video-studio/projects/create', json={'title': 'x'}, headers=self.headers)
        self.assertEqual(res.status_code, 404)

    def test_capabilities_report_missing_engines(self):
        res = self.client.get('/api/video-studio/capabilities')
        self.assertEqual(res.status_code, 200)
        features = res.json['features']
        self.assertFalse(features['animate_fast']['available'])
        self.assertIn('engine-comfyui', features['animate_fast']['missing'])
        self.assertGreater(features['animate_fast']['cost']['vram_gb'], 0)
        self.assertTrue(features['motion_transfer']['cloud_only'])
        self.assertEqual(features['live_portrait']['cloud']['provider'], 'fal')
        self.assertNotIn('key', json.dumps(features['live_portrait']['cloud']).replace('has_key', '').replace('masked_key', ''))

    # ------------------------------------------------------------ motion helpers

    def test_motion_references_and_extract_routes(self):
        res = self.client.get('/api/motion/references')
        self.assertEqual(res.status_code, 200)
        self.assertIn('references', res.json)
        res = self.client.post('/api/motion/extract-frame', json={'video_path': 'nonexistent.mp4', 'timestamp': 1.0}, headers=self.headers)
        self.assertEqual(res.status_code, 400)

    def test_client_paths_outside_library_are_rejected(self):
        outside = Path(__file__).resolve()
        cases = [('/api/motion/extract-frame', {'video_path': str(outside.with_suffix('.mp4'))}),
                 ('/api/video-studio/render-video', {'image_path': str(outside)}),
                 ('/api/video-studio/render-image', {'prompt': 'x', 'custom_reference': str(outside)}),
                 ('/api/video-studio/performance/lip-sync', {'video_path': '../../app_local.py', 'audio_path': 'x.mp3'}),
                 ('/api/motion/render', {'driving_video': 'C:/Windows/notepad.exe'}),
                 ('/api/motion/swap-identity', {'target_frame_path': '..\\..\\secret.png'})]
        for path, payload in cases:
            res = self.client.post(path, json=payload, headers=self.headers)
            self.assertEqual(res.status_code, 400, path)
            self.assertIn('error', res.json)

    def test_motion_render_validation(self):
        res = self.client.post('/api/motion/render', json={'source_image': 'missing.png'}, headers=self.headers)
        self.assertEqual(res.status_code, 400)

    def test_active_persona_routes(self):
        res = self.client.get('/api/characters/active')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json['active']['id'], 'airi')
        self.assertEqual(self.client.post('/api/characters/active', json={'character_id': 'airi'}).status_code, 403)
        res = self.client.post('/api/characters/active', json={'character_id': 'nonexistent_char'}, headers=self.headers)
        self.assertEqual(res.status_code, 404)
        res = self.client.post('/api/characters/active', json={'character_id': 'airi'}, headers=self.headers)
        self.assertEqual(res.json['active']['id'], 'airi')

    # ------------------------------------------------------------ Director

    def test_storyboard_requires_input_and_model(self):
        res = self.client.post('/api/video-studio/storyboard/generate', json={}, headers=self.headers)
        self.assertEqual(res.status_code, 400)
        unavailable = {'available': False, 'error': 'No local model for the helper role is installed on this PC.',
                       'setup_hint': 'qwen3:8b'}
        with patch('routes_studio.llm.cost', return_value=unavailable):
            res = self.client.post('/api/video-studio/storyboard/generate', json={'concept': 'neon', 'duration': 12},
                                   headers=self.headers)
        self.assertEqual(res.status_code, 424)
        self.assertEqual(res.json['setup_hint'], 'qwen3:8b')
        self.assertNotIn('storyboard', res.json)

    def test_storyboard_job_uses_llm_with_real_timings(self):
        cues = [{'start': 0.0, 'end': 3.5, 'text': 'Under the neon lights'}, {'start': 3.5, 'end': 7.0, 'text': 'Feel the bass'}]
        plan = {'title': 'Neon', 'scenes': [
            {'start': 0.1, 'end': 3.4, 'lyric': 'Under the neon lights', 'image_prompt': 'singer under neon', 'motion_prompt': 'sway',
             'camera': 'push in', 'use_character': True},
            {'start': 3.4, 'end': 7.0, 'lyric': 'Feel the bass', 'image_prompt': 'crowd', 'motion_prompt': 'jump',
             'camera': 'pan', 'use_character': False}]}
        reply = {'content': json.dumps(plan), 'tool_calls': [], 'model': 'qwen3:14b', 'backend': 'ollama'}
        cost = {'available': True, 'model': 'qwen3:14b', 'eta_seconds': 20}
        with patch('routes_studio.llm.cost', return_value=cost), \
                patch('assets.ai_video_engine.llm.chat', return_value=reply) as chat:
            res = self.client.post('/api/video-studio/storyboard/generate', json={'cues': cues, 'duration': 7.0, 'concept': 'club'},
                                   headers=self.headers)
            self.assertEqual(res.status_code, 202)
            job = self._wait(res.json['job_id'])
        self.assertEqual(job['status'], 'completed', job)
        scenes = job['result']['scenes']
        self.assertEqual([(s['start'], s['end']) for s in scenes], [(0.0, 3.5), (3.5, 7.0)])  # snapped to cue boundaries
        self.assertEqual(scenes[0]['id'], 'scene_001')
        self.assertFalse(scenes[1]['use_character'])
        prompt = chat.call_args.args[1][1]['content']
        self.assertIn('[0.00-3.50] Under the neon lights', prompt)
        self.assertEqual(chat.call_args.kwargs['schema'], ai_video_engine.STORYBOARD_SCHEMA)

    def test_director_routes_are_llm_backed(self):
        concepts = {'analysis': 'Bittersweet.', 'concepts': [{'name': 'Rain', 'palette': ['#000000'] * 5,
                                                               'prompt_atmosphere': 'wet asphalt', 'camera': 'slow dolly', 'why': 'mood'}]}
        with patch('assets.ai_video_engine.llm.chat', return_value={'content': json.dumps(concepts), 'model': 'qwen3:8b',
                                                                     'backend': 'ollama', 'tool_calls': []}):
            res = self.client.post('/api/video-studio/director/analyze', json={'lyrics': 'cold rain'}, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json['concepts'][0]['name'], 'Rain')
        with patch('assets.ai_video_engine.llm.chat', side_effect=AIUnavailable('No helper model.', setup_hint='qwen3:8b')):
            res = self.client.post('/api/video-studio/director/chat', json={'message': '90s anime look'}, headers=self.headers)
        self.assertEqual(res.status_code, 424)
        self.assertEqual(res.json, {'error': 'No helper model.', 'setup_hint': 'qwen3:8b'})
        self.assertEqual(self.client.post('/api/video-studio/director/chat', json={}, headers=self.headers).status_code, 400)

    # ------------------------------------------------------------ generation

    def test_render_routes_return_424_when_engines_missing(self):
        image = self._png_file('References/kf_missing_engine.png')
        for path, payload in [('/api/video-studio/render-image', {'prompt': 'neon city'}),
                              ('/api/video-studio/render-video', {'image_path': str(image)}),
                              ('/api/video-studio/render-video', {'image_path': str(image), 'quality': 'quality'})]:
            res = self.client.post(path, json=payload, headers=self.headers)
            self.assertEqual(res.status_code, 424, path)
            self.assertTrue(res.json['setup_hint'])
            self.assertNotIn('url', res.json)

    def test_keyframe_and_animation_jobs_use_comfy_workflows(self):
        self._engines_installed()
        generated = Path(app_local.DEFAULT_SAVE_DIR) / 'AI Studio' / 'tmp_out.png'
        clip = Path(app_local.DEFAULT_SAVE_DIR) / 'AI Studio' / 'tmp_out.mp4'

        def fake_workflow(name, inputs, progress=None):
            progress({'state': 'running', 'elapsed': 1})
            target = generated if name.startswith('flux') else clip
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.suffix == '.png':
                Image.new('RGB', (8, 8)).save(target)
            else:
                target.write_bytes(b'mp4')
            return [target]
        with patch('assets.ai_video_engine.comfy.run_workflow', side_effect=fake_workflow) as run:
            res = self.client.post('/api/video-studio/render-image', json={'prompt': 'neon city', 'scene_number': 2},
                                   headers=self.headers)
            self.assertEqual(res.status_code, 202)
            job = self._wait(res.json['job_id'])
            self.assertEqual(job['status'], 'completed', job)
            self.assertEqual(run.call_args.args[0], 'flux_schnell_t2i')
            image = job['result']
            served = self.client.get(image['url'])
            served.close()
            self.assertEqual(served.status_code, 200)
            res = self.client.post('/api/video-studio/render-video', json={'image_path': image['path'], 'duration': 5,
                                                                          'motion_prompt': 'slow sway'}, headers=self.headers)
            job = self._wait(res.json['job_id'])
        self.assertEqual(job['status'], 'completed', job)
        self.assertEqual(run.call_args.args[0], 'wan22_ti2v_5b')
        self.assertEqual(run.call_args.args[1]['length'], 121)
        self.assertTrue(job['result']['ai'])
        Path(image['path']).unlink(missing_ok=True)
        Path(job['result']['path']).unlink(missing_ok=True)

    def test_camera_preview_is_labelled_no_ai(self):
        image = self._png_file('References/kf_preview.png')
        res = self.client.post('/api/video-studio/render-video', json={'image_path': str(image), 'preview': True, 'duration': 1},
                               headers=self.headers)
        self.assertEqual(res.status_code, 202)
        self.assertEqual(res.json['job']['label'], 'Preview (no AI)')
        job = self._wait(res.json['job_id'], timeout=60)
        self.assertEqual(job['status'], 'completed', job)
        self.assertFalse(job['result']['ai'])
        self.assertEqual(job['result']['label'], 'Preview (no AI)')
        Path(job['result']['path']).unlink(missing_ok=True)

    def test_cloud_requires_explicit_cost_confirmation(self):
        video = self._library_file('Driving References/dance_cloud.mp4')
        portrait = self._png_file('References/portrait_cloud.png')
        payload = {'engine': 'kling', 'driving_video': str(video), 'source_image': str(portrait)}
        with patch('assets.motion_studio.cloud.kling_motion_control') as kling:
            res = self.client.post('/api/motion/render', json=payload, headers=self.headers)
        self.assertEqual(res.status_code, 409)
        self.assertTrue(res.json['needs_confirmation'])
        self.assertFalse(res.json['cost']['local'])
        kling.assert_not_called()
        res = self.client.post('/api/motion/render', json={**payload, 'confirm_cost': True}, headers=self.headers)
        job = self._wait(res.json['job_id'])
        self.assertEqual(job['status'], 'failed')  # fal.ai is off in a fresh profile: honest error, no fallback
        self.assertEqual(job['setup_hint'], 'cloud')
        self.assertFalse(job['local'])

    def test_face_swap_video_job_cancel(self):
        self._engines_installed()
        video = self._library_file('Driving References/dance_cancel.mp4')
        portrait = self._png_file('References/portrait_cancel.png')
        started = threading.Event()

        def slow_swap(*args, **kwargs):
            started.set()
            while True:
                job_process.check_cancelled()
                time.sleep(0.02)
        with patch('assets.motion_studio.face.swap_video', side_effect=slow_swap):
            res = self.client.post('/api/motion/render', json={'driving_video': str(video), 'source_image': str(portrait)},
                                   headers=self.headers)
            self.assertEqual(res.status_code, 202)
            job_id = res.json['job_id']
            self.assertTrue(started.wait(5))
            self.assertEqual(self.client.get(f'/api/motion/jobs/{job_id}').json['status'], 'running')
            res = self.client.post(f'/api/jobs/{job_id}/cancel', headers=self.headers)
            self.assertTrue(res.json['success'])
            self.assertEqual(self._wait(job_id)['status'], 'cancelled')
        self.assertEqual(self.client.get('/api/jobs/nonexistent_job_123').status_code, 404)

    def test_face_swap_video_mute_and_project_audio(self):
        self._engines_installed()
        video = self._library_file('Driving References/dance_audio.mp4')
        portrait = self._png_file('References/portrait_audio.png')
        pid = 'c' * 32
        song = self._library_file(f'Caption Projects/{pid}/song.mp3')

        def fake_swap(target, source, output, **kwargs):
            Path(output).write_bytes(b'video')
            return {'provider': 'CPUExecutionProvider'}
        for payload, mode, audio in [({'mute': True}, 'mute', None),
                                     ({'audio_mode': 'project', 'audio_path': f'/api/captions/{pid}/media/song.mp3'}, 'project', song)]:
            with patch('assets.motion_studio.face.swap_video', side_effect=fake_swap), \
                    patch('assets.motion_studio.apply_audio', side_effect=lambda path, **kw: Path(path)) as apply_audio:
                res = self.client.post('/api/motion/render', json={'driving_video': str(video), 'source_image': str(portrait),
                                                                   **payload}, headers=self.headers)
                job = self._wait(res.json['job_id'])
            self.assertEqual(job['status'], 'completed', job)
            self.assertEqual(apply_audio.call_args.kwargs['mode'], mode)
            self.assertEqual(apply_audio.call_args.kwargs['audio'], audio.resolve() if audio else None)
            Path(job['result']['path']).unlink(missing_ok=True)

    def test_motion_swap_identity_route(self):
        self.assertEqual(self.client.post('/api/motion/swap-identity', json={}, headers=self.headers).status_code, 400)
        res = self.client.post('/api/motion/swap-identity', json={'target_frame_path': 'nonexistent_frame.png'}, headers=self.headers)
        self.assertEqual(res.status_code, 400)
        frame = self._png_file('References/frame_swap.png')
        portrait = self._png_file('References/portrait_swap.png')
        res = self.client.post('/api/motion/swap-identity', json={'target_frame_path': str(frame),
                                                                  'custom_portrait_path': str(portrait)}, headers=self.headers)
        self.assertEqual(res.status_code, 424)  # InSwapper not installed: no fake "success"
        self.assertEqual(res.json['setup_hint'], 'inswapper-128')

    def test_motion_reference_file_serving_with_spaces(self):
        test_file = self._png_file('References/ref_Test Video with spaces_123.png')
        for url in ('/api/motion/references/file/ref_Test%20Video%20with%20spaces_123.png',
                    f'/api/motion/references/file/{test_file.name}'):
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.content_type, 'image/png')
            res.close()

    def test_upload_swapped_frame_route(self):
        self.assertEqual(self.client.post('/api/motion/upload-swapped-frame', headers=self.headers).status_code, 400)
        data = {'image': (self._sample_png(), 'custom_swapped_test.png')}
        res = self.client.post('/api/motion/upload-swapped-frame', data=data, headers=self.headers, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 201)
        self.assertIn('custom_swapped_', res.json.get('filename', ''))
        self.assertTrue(res.json.get('url', '').startswith('/api/motion/references/file/'))

    def test_driving_videos_route(self):
        res = self.client.get('/api/motion/driving-videos')
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json['videos'], list)

    def test_storyboard_bridge_to_project(self):
        pid = 'b' * 32
        proj_dir = Path(app_local.DEFAULT_SAVE_DIR) / 'Caption Projects' / pid
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / 'song.mp3').write_bytes(b'dummy-audio')
        clip = self._library_file('Storyboard Videos/video_scene_1_bridge.mp4')
        project_data = {'id': pid, 'name': 'Test AI Song', 'source': 'song.mp3', 'state': 'ready', 'status': 'Ready', 'revision': 1,
                        'cues': [{'start': 0.0, 'end': 4.0, 'text': 'Verse 1'}], 'duration': 10.0, 'width': 1080, 'height': 1920,
                        'style': {}, 'studio': {'version': 1, 'assets': {}, 'layers': []}}
        (proj_dir / 'project.json').write_text(json.dumps(project_data), encoding='utf-8')
        storyboard = [{'id': 's1', 'lyric': 'Verse 1', 'start': 0.0, 'end': 4.0, 'duration': 4.0, 'video_path': str(clip)}]
        res = self.client.post(f'/api/captions/{pid}/storyboard', json={'storyboard': storyboard}, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json['revision'], 1)
        res = self.client.post(f'/api/captions/{pid}/bridge-storyboard', json={}, headers=self.headers)
        self.assertEqual(res.status_code, 409)
        res = self.client.post(f'/api/captions/{pid}/bridge-storyboard', json={'revision': 1}, headers=self.headers)
        self.assertEqual(res.status_code, 400)  # This stub project has no prepared song/audio asset.
        self.assertIn('Finish preparing', res.json['error'])
        projects = self.client.get('/api/video-studio/projects').json['projects']
        listed = next(p for p in projects if p['id'] == pid)
        self.assertEqual(listed['audio_url'], f'/api/captions/{pid}/media/song.mp3')

    def test_captions_generate_backdrop_route(self):
        res = self.client.post('/api/captions/generate-backdrop', json={}, headers=self.headers)
        self.assertEqual(res.status_code, 400)
        res = self.client.post('/api/captions/generate-backdrop', json={'prompt': 'Cyberpunk neon city street night'},
                               headers=self.headers)
        self.assertEqual(res.status_code, 424)  # FLUX not installed in a fresh profile
        self.assertEqual(res.json['setup_hint'], 'flux-schnell-q4')
        out = Path(app_local.DEFAULT_SAVE_DIR) / 'AI Studio' / 'backdrop_out.png'

        def fake_workflow(name, inputs, progress=None):
            self.assertEqual(name, 'flux_schnell_t2i')  # never the persona/Kontext path by default
            self.assertNotIn('Airi', inputs['prompt'])
            out.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (8, 8)).save(out)
            return [out]
        with patch('assets.ai_video_engine.comfy.run_workflow', side_effect=fake_workflow):
            res = self.client.post('/api/captions/generate-backdrop', json={'prompt': 'Neon street', 'style': 'neon'},
                                   headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json['kind'], 'image')
        self.assertTrue(Path(res.json['path']).is_file())
        self.assertNotIn('message', res.json)
        Path(res.json['path']).unlink(missing_ok=True)

    def test_gallery_categorization_downloads_vs_studio(self):
        """Verify /api/gallery classifies studio creations vs media downloads."""
        from app_local import DEFAULT_SAVE_DIR, invalidate_gallery_cache
        from pathlib import Path

        storyboard_dir = Path(DEFAULT_SAVE_DIR) / 'Storyboard Images'
        storyboard_dir.mkdir(parents=True, exist_ok=True)
        kf_file = storyboard_dir / 'keyframe_scene_2_test999.png'
        kf_file.write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')

        ig_dir = Path(DEFAULT_SAVE_DIR) / 'Instagram'
        ig_dir.mkdir(parents=True, exist_ok=True)
        ig_file = ig_dir / 'download_test999.mp4'
        ig_file.write_bytes(b'fake-video-content')

        invalidate_gallery_cache()
        try:
            res = self.client.get('/api/gallery', headers=self.headers)
            self.assertEqual(res.status_code, 200)
            items = res.json

            kf_item = next((i for i in items if i['name'] == 'keyframe_scene_2_test999.png'), None)
            self.assertIsNotNone(kf_item)
            self.assertEqual(kf_item['section'], 'studio')
            self.assertEqual(kf_item['studio_type'], 'keyframe')
            self.assertEqual(kf_item['scene_number'], 2)

            ig_item = next((i for i in items if i['name'] == 'download_test999.mp4'), None)
            self.assertIsNotNone(ig_item)
            self.assertEqual(ig_item['section'], 'downloads')
        finally:
            kf_file.unlink(missing_ok=True)
            ig_file.unlink(missing_ok=True)
            invalidate_gallery_cache()

    def test_instagram_profile_detection_and_extraction(self):
        """Verify Instagram profile URL recognition and metadata extraction."""
        from download_support import is_instagram_profile_url, extract_instagram_username, extract_instagram_profile
        from unittest.mock import patch

        self.assertTrue(is_instagram_profile_url('https://www.instagram.com/j1aa11/'))
        self.assertTrue(is_instagram_profile_url('https://www.instagram.com/j1aa11/?hl=en'))
        self.assertTrue(is_instagram_profile_url('@_j1aa11'))
        self.assertTrue(is_instagram_profile_url('https://www.instagram.com/j1aa11/reels/'))
        self.assertFalse(is_instagram_profile_url('https://www.instagram.com/p/De6ogMclFBy/'))
        self.assertFalse(is_instagram_profile_url('https://www.instagram.com/reel/De6ogMclFBy/'))
        self.assertFalse(is_instagram_profile_url('https://www.youtube.com/watch?v=123'))

        self.assertFalse(is_instagram_profile_url('https://www.instagram.com/j1aa11/p/De6ogMclFBy/'))
        self.assertFalse(is_instagram_profile_url('https://www.instagram.com/j1aa11/reel/De6ogMclFBy/'))

        self.assertEqual(extract_instagram_username('https://www.instagram.com/j1aa11/'), 'j1aa11')
        self.assertEqual(extract_instagram_username('@_j1aa11'), '_j1aa11')
        self.assertEqual(extract_instagram_username('https://www.instagram.com/j1aa11/reels/'), 'j1aa11')

        # Listing goes through gallery-dl (mocked: no network) and returns a valid profile structure
        from types import SimpleNamespace
        completed = SimpleNamespace(returncode=0, stdout='[]', stderr='')
        with patch('download_support.subprocess.run', return_value=completed) as run:
            prof = extract_instagram_profile('https://www.instagram.com/j1aa11/', browser='firefox')
            self.assertTrue(prof.get('is_profile'))
            self.assertEqual(prof.get('username'), 'j1aa11')
            self.assertEqual(prof.get('platform'), 'instagram')
            self.assertIn('posts', prof)
            self.assertIn('--dump-json', run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
