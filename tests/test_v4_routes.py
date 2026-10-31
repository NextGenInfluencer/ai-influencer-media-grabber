"""Flask route tests for v4.0.0 features: Characters, Copilot, and Motion Studio."""
import tests._isolation  # Must precede application imports
import io
import json
import os
from pathlib import Path
import shutil
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

    def test_video_studio_page(self):
        res = self.client.get('/video-studio')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'AI Video Studio', res.data)
        self.assertIn(b'Locked Creator Persona', res.data)

    def test_active_persona_routes(self):
        # 1. GET active persona
        res = self.client.get('/api/characters/active')
        self.assertEqual(res.status_code, 200)
        self.assertIn('active', res.json)
        self.assertEqual(res.json['active']['id'], 'airi')

        # 2. POST without token is 403
        res = self.client.post('/api/characters/active', json={'character_id': 'airi'})
        self.assertEqual(res.status_code, 403)

        # 3. POST with invalid character returns 404
        res = self.client.post('/api/characters/active', json={'character_id': 'nonexistent_char'}, headers=self.headers)
        self.assertEqual(res.status_code, 404)

        # 4. POST with airi is 200
        res = self.client.post('/api/characters/active', json={'character_id': 'airi'}, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json['active']['id'], 'airi')

    def test_video_studio_storyboard_generation(self):
        # Empty cues returns default starter storyboard gracefully
        res = self.client.post('/api/video-studio/storyboard/generate', json={}, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json.get('storyboard', [])), 3)

        cues = [
            {'start': 0.0, 'end': 3.5, 'text': 'Under the neon lights we dance until dawn'},
            {'start': 3.5, 'end': 7.0, 'text': 'Feel the bass drop through the concrete floor'},
            {'start': 7.0, 'end': 11.0, 'text': 'Stars shine bright over the city skyline'}
        ]
        res = self.client.post('/api/video-studio/storyboard/generate', json={'cues': cues, 'character_id': 'airi'}, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        scenes = res.json.get('storyboard', [])
        self.assertEqual(len(scenes), 3)
        self.assertIn('prompt', scenes[0])
        self.assertIn('camera_motion', scenes[0])
        self.assertIn('hand_lock', scenes[0])
        self.assertTrue('fingers' in scenes[0]['prompt'].lower())

    def test_video_studio_render_image_and_video(self):
        # 1. Render image
        img_payload = {
            'scene_id': 'scene_001',
            'prompt': 'Airi dancing under cyberpunk neon, ultra detailed 8k',
            'character_id': 'airi',
            'aspect_ratio': '9:16'
        }
        res = self.client.post('/api/video-studio/render-image', json=img_payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        img_url = res.json.get('image_url')
        self.assertTrue(img_url.startswith('/api/video-studio/images/file/'))

        # Fetch rendered image
        res_file = self.client.get(img_url)
        self.assertEqual(res_file.status_code, 200)
        self.assertEqual(res_file.content_type, 'image/png')

        # 2. Render video
        vid_payload = {
            'scene_id': 'scene_001',
            'image_path': res.json.get('image_path'),
            'motion_prompt': 'dynamic camera push in with rhythmic dance choreography',
            'duration': 3.5,
            'camera_motion': 'Push in / forward track'
        }
        res = self.client.post('/api/video-studio/render-video', json=vid_payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        vid_url = res.json.get('video_url')
        self.assertTrue(vid_url.startswith('/api/video-studio/videos/file/'))

        # Fetch rendered video
        res_vid = self.client.get(vid_url)
        self.assertEqual(res_vid.status_code, 200)
        self.assertEqual(res_vid.content_type, 'video/mp4')

    def test_storyboard_bridge_to_project(self):
        # 1. Create a dummy project in captions storage
        pid = 'b' * 32
        proj_dir = Path(app_local.DEFAULT_SAVE_DIR) / 'Caption Projects' / pid
        proj_dir.mkdir(parents=True, exist_ok=True)
        dummy_song = proj_dir / 'song.mp3'
        dummy_song.write_bytes(b'dummy-audio')
        project_data = {
            'id': pid,
            'name': 'Test AI Song',
            'source': 'song.mp3',
            'state': 'ready',
            'status': 'Ready',
            'revision': 1,
            'cues': [{'start': 0.0, 'end': 4.0, 'text': 'Verse 1'}],
            'duration': 10.0,
            'width': 1080,
            'height': 1920,
            'style': {},
            'studio': {'version': 1, 'assets': {}, 'layers': []}
        }
        (proj_dir / 'project.json').write_text(json.dumps(project_data), encoding='utf-8')

        # 2. Render mock image and video
        img_res = self.client.post('/api/video-studio/render-image', json={'scene_id': 's1', 'prompt': 'test', 'character_id': 'airi'}, headers=self.headers)
        self.assertEqual(img_res.status_code, 200)
        vid_res = self.client.post('/api/video-studio/render-video', json={'scene_id': 's1', 'image_path': img_res.json['image_path'], 'duration': 4.0}, headers=self.headers)
        self.assertEqual(vid_res.status_code, 200)

        storyboard = [{
            'id': 's1',
            'lyric': 'Verse 1',
            'start': 0.0,
            'end': 4.0,
            'duration': 4.0,
            'prompt': 'Airi singing',
            'image_url': img_res.json['image_url'],
            'image_path': img_res.json['image_path'],
            'video_url': vid_res.json['video_url'],
            'video_path': vid_res.json['video_path']
        }]

        # 3. Save storyboard
        res = self.client.post(f'/api/captions/{pid}/storyboard', json={'storyboard': storyboard}, headers=self.headers)
        self.assertEqual(res.status_code, 200)

        # 4. Bridge storyboard to timeline
        res = self.client.post(f'/api/captions/{pid}/bridge-storyboard', headers=self.headers)
        self.assertEqual(res.status_code, 200)
        bridged = res.json['project']
        self.assertTrue(bridged.get('has_composition', False))
        self.assertTrue(len(bridged.get('composition_sequence', [])) >= 1)
        self.assertEqual(bridged['composition_sequence'][0]['scene_id'], 's1')

    def test_video_studio_models_api(self):
        # 1. Test listing models & GPU detection
        res = self.client.get('/api/video-studio/models')
        self.assertEqual(res.status_code, 200)
        data = res.json
        self.assertIn('models', data)
        self.assertIn('gpu', data)
        self.assertIn('summary', data)
        self.assertTrue(any(m['id'] == 'flux-schnell-nf4' for m in data['models']))
        self.assertTrue(any(m['id'] == 'wan-2.1-1.3b' for m in data['models']))

        # 2. Test selecting active model
        sel_res = self.client.post('/api/video-studio/models/select', json={
            'active_image_model': 'sdxl-lightning',
            'active_video_model': 'wan-2.1-14b-q4'
        }, headers=self.headers)
        self.assertEqual(sel_res.status_code, 200)
        self.assertEqual(sel_res.json['config']['active_image_model'], 'sdxl-lightning')

        # 3. Test saving cloud backend config
        cloud_res = self.client.post('/api/video-studio/models/cloud-config', json={
            'enabled': True,
            'comfy_url': 'http://127.0.0.1:8188',
            'api_provider': 'huggingface',
            'api_key': 'hf_test123'
        }, headers=self.headers)
        self.assertEqual(cloud_res.status_code, 200)
        self.assertTrue(cloud_res.json['config']['cloud_backend']['enabled'])
        self.assertEqual(cloud_res.json['config']['cloud_backend']['api_key'], 'hf_test123')

        # 4. Test download validation
        bad_dl = self.client.post('/api/video-studio/models/download', json={'model_id': 'nonexistent'}, headers=self.headers)
        self.assertEqual(bad_dl.status_code, 400)

    def test_create_video_studio_freeform_project(self):
        res = self.client.post('/api/video-studio/projects/create', json={
            'title': 'Unit Test Cyberpunk Project',
            'mode': 'freeform',
            'duration': 15.0,
            'scene_count': 3,
            'concept': 'Airi cyberpunk neon night walk',
            'mood': 'dim studio booth, cinematic rim lights, atmospheric haze',
            'character_id': 'airi'
        }, headers=self.headers)
        self.assertEqual(res.status_code, 201)
        data = res.json
        self.assertIn('project', data)
        self.assertIn('storyboard', data)
        self.assertEqual(data['project']['name'], 'Unit Test Cyberpunk Project')
        self.assertEqual(len(data['storyboard']), 3)

        # Clean up
        pid = data['project']['id']
        from assets.ai_video_engine import DATA_DIR
        pdir = DATA_DIR / 'Caption Projects' / pid
        if pdir.exists():
            shutil.rmtree(pdir, ignore_errors=True)

    def test_driving_videos_route(self):
        res = self.client.get('/api/motion/driving-videos')
        self.assertEqual(res.status_code, 200)
        self.assertIn('videos', res.json)
        self.assertIsInstance(res.json['videos'], list)

    def test_video_studio_director_analyze_route(self):
        res = self.client.post('/api/video-studio/director/analyze', json={
            'lyrics': 'walking through the cold rain in tokyo late at night',
            'song_title': 'Midnight Drift',
            'character_id': 'airi'
        }, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json
        self.assertIn('analysis', data)
        self.assertIn('concepts', data)
        self.assertEqual(len(data['concepts']), 4)
        first_concept = data['concepts'][0]
        self.assertIn('name', first_concept)
        self.assertIn('palette', first_concept)
        self.assertIn('prompt_atmosphere', first_concept)
        self.assertEqual(len(first_concept['palette']), 5)

    def test_video_studio_director_chat_route(self):
        # 1. Successful directorial chat
        res = self.client.post('/api/video-studio/director/chat', json={
            'message': 'create a 90s anime retro cel aesthetic',
            'character_id': 'airi'
        }, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json
        self.assertIn('reply', data)
        self.assertIn('concept', data)
        self.assertEqual(data['concept']['icon'], '🌸')
        self.assertIn('anime', data['concept']['name'].lower())

        # 2. Missing message returns 400
        bad_res = self.client.post('/api/video-studio/director/chat', json={}, headers=self.headers)
        self.assertEqual(bad_res.status_code, 400)

    def test_motion_swap_identity_route(self):
        # 1. Missing target frame and driving video returns 400
        res = self.client.post('/api/motion/swap-identity', json={}, headers=self.headers)
        self.assertEqual(res.status_code, 400)

        # 2. Non-existent file returns 400
        res = self.client.post('/api/motion/swap-identity', json={
            'target_frame_path': 'nonexistent_frame.png',
            'character_id': 'airi'
        }, headers=self.headers)
        self.assertEqual(res.status_code, 400)

    def test_motion_reference_file_serving_with_spaces(self):
        from assets.motion_studio import REFERENCES_DIR
        REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
        test_file = REFERENCES_DIR / 'ref_Test Video with spaces_123.png'
        img = Image.new('RGB', (32, 32), color='purple')
        img.save(test_file, format='PNG')
        try:
            # 1. Access with percent-encoded spaces
            res1 = self.client.get('/api/motion/references/file/ref_Test%20Video%20with%20spaces_123.png')
            self.assertEqual(res1.status_code, 200)
            self.assertEqual(res1.content_type, 'image/png')
            res1.close()

            # 2. Access with raw spaces
            res2 = self.client.get('/api/motion/references/file/ref_Test Video with spaces_123.png')
            self.assertEqual(res2.status_code, 200)
            self.assertEqual(res2.content_type, 'image/png')
            res2.close()
        finally:
            try:
                test_file.unlink(missing_ok=True)
            except Exception:
                pass

    def test_upload_swapped_frame_route(self):
        # 1. Missing image returns 400
        res = self.client.post('/api/motion/upload-swapped-frame', headers=self.headers)
        self.assertEqual(res.status_code, 400)

        # 2. Upload valid swapped image
        data = {'image': (self._sample_png(), 'custom_swapped_test.png')}
        res = self.client.post('/api/motion/upload-swapped-frame', data=data, headers=self.headers, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.json.get('success'))
        self.assertIn('custom_swapped_', res.json.get('filename', ''))
        self.assertTrue(res.json.get('url', '').startswith('/api/motion/references/file/'))

    def test_captions_generate_backdrop_route(self):
        # 1. Missing prompt returns 400
        res = self.client.post('/api/captions/generate-backdrop', json={}, headers=self.headers)
        self.assertEqual(res.status_code, 400)

        # 2. Generate still image backdrop
        res = self.client.post('/api/captions/generate-backdrop', json={
            'prompt': 'Cyberpunk neon city street night',
            'style': 'neon',
            'motion': False
        }, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('kind'), 'image')
        self.assertTrue(data.get('path', '').endswith('.png'))
        self.assertTrue(Path(data['path']).is_file())

        # Cleanup generated test backdrop
        try:
            Path(data['path']).unlink(missing_ok=True)
        except Exception:
            pass

    def test_motion_async_jobs_and_cancel(self):
        # 1. Create dummy image for source_image
        from assets.motion_studio import REFERENCES_DIR
        REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
        dummy_img = REFERENCES_DIR / 'dummy_source_test.png'
        Image.new('RGB', (64, 64), color='green').save(dummy_img, format='PNG')

        try:
            # 2. Start async motion job
            res = self.client.post('/api/motion/render', json={
                'source_image': str(dummy_img),
                'async': True
            }, headers=self.headers)
            self.assertEqual(res.status_code, 202)
            data = res.json
            self.assertIn('job_id', data)
            job_id = data['job_id']

            # 3. Query job status
            res_stat = self.client.get(f'/api/motion/jobs/{job_id}', headers=self.headers)
            self.assertEqual(res_stat.status_code, 200)
            job = res_stat.json
            self.assertEqual(job['id'], job_id)
            self.assertIn(job['status'], ('pending', 'running', 'completed', 'cancelled'))

            # 4. Cancel job
            res_cancel = self.client.post(f'/api/motion/jobs/{job_id}/cancel', headers=self.headers)
            self.assertEqual(res_cancel.status_code, 200)
            self.assertTrue(res_cancel.json.get('success'))

            # 5. Non-existent job returns 404
            res_bad = self.client.get('/api/motion/jobs/nonexistent_job_123', headers=self.headers)
            self.assertEqual(res_bad.status_code, 404)
        finally:
            try:
                dummy_img.unlink(missing_ok=True)
            except Exception:
                pass


if __name__ == '__main__':
    unittest.main()
