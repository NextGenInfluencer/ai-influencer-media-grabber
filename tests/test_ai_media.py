"""Face swap, ComfyUI client, cloud providers, speech and vision (all mocked; no weights, no network)."""
import tests._isolation  # noqa: F401  (must precede application imports)
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

import job_process
from ai_core import asr, catalog, cloud, comfy, engines, face, hardware, models, settings, vision
from ai_core.errors import AIUnavailable, ModelMissing
from tests._ai_support import HIGH_INFO, FakeComfy, IsolatedAIMixin


class FakeFace(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def make_face(x=10, embedding=(1.0, 0.0, 0.0)):
    return FakeFace(bbox=np.array([x, 10, x + 20, 30], dtype=np.float32),
                    kps=np.array([[x + 5, 15], [x + 15, 15], [x + 10, 20], [x + 6, 25], [x + 14, 25]], dtype=np.float32),
                    normed_embedding=np.array(embedding, dtype=np.float32))


class FakeAnalyzer:
    def __init__(self, faces):
        self.faces = faces

    def get(self, frame):
        return list(self.faces)


class FakeSwapper:
    def get(self, frame, target, source, paste_back=True):
        return 255 - frame


def fake_ort(providers, preload=True):
    module = types.ModuleType('onnxruntime')
    module.get_available_providers = lambda: providers
    if preload:
        module.preload_dlls = MagicMock()
    return module


class FaceTests(IsolatedAIMixin, unittest.TestCase):
    def test_provider_selection_cuda_directml_cpu(self):
        cuda = fake_ort(['CUDAExecutionProvider', 'CPUExecutionProvider'])
        fake_torch = types.ModuleType('torch')
        with patch.dict(sys.modules, {'onnxruntime': cuda, 'torch': fake_torch}):
            self.assertEqual(face.select_providers(), ['CUDAExecutionProvider', 'CPUExecutionProvider'])
        cuda.preload_dlls.assert_called_once()
        failing = fake_ort(['CUDAExecutionProvider'])
        failing.preload_dlls.side_effect = OSError('missing cudnn')
        with patch.dict(sys.modules, {'onnxruntime': failing, 'torch': fake_torch}):
            self.assertEqual(face.select_providers()[0], 'CUDAExecutionProvider')
        with patch.dict(sys.modules, {'onnxruntime': fake_ort(['DmlExecutionProvider', 'CPUExecutionProvider'], preload=False)}):
            self.assertEqual(face.select_providers(), ['DmlExecutionProvider', 'CPUExecutionProvider'])
        with patch.dict(sys.modules, {'onnxruntime': fake_ort(['AzureExecutionProvider', 'CPUExecutionProvider'], preload=False)}):
            self.assertEqual(face.select_providers(), ['CPUExecutionProvider'])
        with patch.dict(sys.modules, {'onnxruntime': None}):
            with self.assertRaises(AIUnavailable):
                face.select_providers()
        # When local nvidia runtime wheels are present, preload_dlls() is called directly without querying ComfyUI.
        nv_root = self.root / 'site-packages' / 'nvidia'
        nv_bin = nv_root / 'cu13' / 'bin' / 'x86_64'
        nv_bin.mkdir(parents=True)
        (nv_bin / 'cublasLt64_13.dll').write_bytes(b'dll')
        nv_spec = types.SimpleNamespace(submodule_search_locations=[str(nv_root)])
        cuda13_local = fake_ort(['CUDAExecutionProvider', 'CPUExecutionProvider'])
        cuda13_local.cuda_version = '13.0'
        with patch('importlib.util.find_spec', return_value=nv_spec), \
                patch.object(engines.comfy, 'python', side_effect=AssertionError('should not query ComfyUI')), \
                patch.dict(sys.modules, {'onnxruntime': cuda13_local}):
            self.assertEqual(face.select_providers(), ['CUDAExecutionProvider', 'CPUExecutionProvider'])
        cuda13_local.preload_dlls.assert_called_once_with()
        # Only as a last resort when neither local torch nor local nvidia wheels have the DLL, fallback to ComfyUI.
        comfy_py = self.root / 'comfy' / 'python_embeded' / 'python.exe'
        torch_lib = comfy_py.parent / 'Lib' / 'site-packages' / 'torch' / 'lib'
        torch_lib.mkdir(parents=True)
        (torch_lib / 'cublasLt64_13.dll').write_bytes(b'dll')
        cuda13 = fake_ort(['CUDAExecutionProvider', 'CPUExecutionProvider'])
        cuda13.cuda_version = '13.0'
        with patch('importlib.util.find_spec', return_value=None), \
                patch.object(engines.comfy, 'python', return_value=comfy_py), \
                patch.dict(sys.modules, {'onnxruntime': cuda13}):
            self.assertEqual(face.select_providers(), ['CUDAExecutionProvider', 'CPUExecutionProvider'])
        cuda13.preload_dlls.assert_called_once_with(directory=str(torch_lib))

    def test_cuda_session_fallback_surfaces_cpu_warning(self):
        cpu_session = MagicMock()
        cpu_session.get_providers.return_value = ['CPUExecutionProvider']
        cuda_session = MagicMock()
        cuda_session.get_providers.return_value = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        analyzer = types.SimpleNamespace(models={'det': types.SimpleNamespace(session=cuda_session)})
        swapper = types.SimpleNamespace(session=cpu_session)
        active_provider, warning = face._verify_session_providers(
            analyzer, swapper, None, ['CUDAExecutionProvider', 'CPUExecutionProvider']
        )
        self.assertEqual(active_provider, 'CPUExecutionProvider')
        self.assertIn('running on CPU – slower', warning)
        active_ok, warning_ok = face._verify_session_providers(
            analyzer, types.SimpleNamespace(session=cuda_session), cuda_session,
            ['CUDAExecutionProvider', 'CPUExecutionProvider']
        )
        self.assertEqual(active_ok, 'CUDAExecutionProvider')
        self.assertIsNone(warning_ok)
        source, target = self._images()
        output = self.root / 'out' / 'warn.png'
        face._state['providers'] = ['CPUExecutionProvider']
        face._state['warning'] = warning
        self.addCleanup(face._release)
        with patch.object(face, '_load', return_value=(FakeAnalyzer([make_face()]), FakeSwapper(), None)):
            res = face.swap_image(target, source, output, restore=False)
        self.assertIn('running on CPU – slower', res['warning'])

    def test_restore_requested_without_gfpgan_raises_model_missing(self):
        with patch.object(models, 'installed', return_value=False):
            with self.assertRaises(ModelMissing) as raised:
                face.swap_image('t.png', 's.png', 'o.png', restore=True)
        self.assertEqual(raised.exception.setup_hint, 'gfpgan-1.4')

    def test_models_are_never_downloaded(self):
        with patch.object(engines.ollama, 'tags', return_value=[]):
            with self.assertRaises(ModelMissing) as raised:
                face.swap_image('t.png', 's.png', 'o.png', restore=False)
        self.assertEqual(raised.exception.setup_hint, 'insightface-buffalo-l')

    def _images(self):
        import cv2
        source = self.root / 'source.png'
        target = self.root / 'target.png'
        cv2.imwrite(str(source), np.full((40, 40, 3), 100, np.uint8))
        cv2.imwrite(str(target), np.full((40, 40, 3), 50, np.uint8))
        return source, target

    def test_swap_image_and_no_face_errors(self):
        source, target = self._images()
        output = self.root / 'out' / 'swapped.png'
        face._state['providers'] = ['CPUExecutionProvider']
        self.addCleanup(face._release)
        with patch.object(face, '_load', return_value=(FakeAnalyzer([make_face()]), FakeSwapper(), None)):
            result = face.swap_image(target, source, output, restore=False)
        self.assertEqual((result['faces_swapped'], result['restored']), (1, False))
        import cv2
        self.assertEqual(int(cv2.imread(str(output))[0, 0, 0]), 205)
        with patch.object(face, '_load', return_value=(FakeAnalyzer([]), FakeSwapper(), None)):
            with self.assertRaisesRegex(AIUnavailable, 'reference image'):
                face.swap_image(target, source, output, restore=False)

    def test_restore_face_feathered_paste_back(self):
        frame = np.full((120, 120, 3), 80, np.uint8)
        session = MagicMock()
        session.get_inputs.return_value = [MagicMock(name='input')]
        session.run.side_effect = lambda _, feeds: [np.ones_like(next(iter(feeds.values())))]
        restored = face.restore_face(frame, make_face(x=40), session)
        self.assertEqual(restored.shape, frame.shape)
        self.assertGreater(int(restored.max()), 80)
        self.assertEqual(int(restored[0, 0, 0]), 80)

    def _video(self, frames=12, size=(64, 48)):
        import imageio_ffmpeg
        path = self.root / 'clip.mp4'
        writer = imageio_ffmpeg.write_frames(str(path), size, fps=12, codec='libx264', pix_fmt_in='bgr24',
                                             macro_block_size=1)
        writer.send(None)
        for index in range(frames):
            writer.send(np.full((size[1], size[0], 3), 20 + index, np.uint8).tobytes())
        writer.close()
        return path

    def test_swap_video_keeps_size_has_no_frame_cap_and_tracks_identity(self):
        source, _ = self._images()
        video = self._video()
        output = self.root / 'out' / 'swapped.mp4'
        progress = []
        stranger = make_face(x=30, embedding=(0.0, 1.0, 0.0))
        face._state['providers'] = ['CPUExecutionProvider']
        self.addCleanup(face._release)
        analyzer = FakeAnalyzer([make_face(), stranger])
        with patch.object(face, '_load', return_value=(analyzer, FakeSwapper(), None)), \
                patch.object(face, '_source_face', return_value=make_face()):
            result = face.swap_video(video, source, output, restore=False, progress=lambda d, t: progress.append((d, t)))
        self.assertTrue(output.is_file())
        self.assertEqual((result['width'], result['height']), (64, 48))
        self.assertEqual(result['frames_swapped'], result['frames_total'])
        self.assertEqual(result['frames_total'], 12)
        self.assertEqual(progress[-1][0], 12)

    def test_swap_video_without_any_face_is_honest(self):
        source, _ = self._images()
        video = self._video(frames=3)
        face._state['providers'] = ['CPUExecutionProvider']
        self.addCleanup(face._release)
        with patch.object(face, '_load', return_value=(FakeAnalyzer([]), FakeSwapper(), None)), \
                patch.object(face, '_source_face', return_value=make_face()):
            with self.assertRaisesRegex(AIUnavailable, 'No face was found in the video'):
                face.swap_video(video, source, self.root / 'o.mp4', restore=False)
        reference = make_face()
        with patch.object(face, '_load', return_value=(FakeAnalyzer([make_face(embedding=(0, 1, 0))]), FakeSwapper(), None)), \
                patch.object(face, '_source_face', return_value=make_face()), \
                patch.object(face, '_sample_reference', return_value=reference):
            with self.assertRaisesRegex(AIUnavailable, 'not found in any frame'):
                face.swap_video(video, source, self.root / 'o.mp4', restore=False)
        self.assertFalse((self.root / 'o.mp4').exists())

    def test_swap_video_cancellation(self):
        source, _ = self._images()
        video = self._video(frames=6)
        face._state['providers'] = ['CPUExecutionProvider']
        self.addCleanup(face._release)
        swapped = []

        class CountingSwapper(FakeSwapper):
            def get(self, frame, target, source_face, paste_back=True):
                swapped.append(1)
                return super().get(frame, target, source_face, paste_back)
        with patch.object(face, '_load', return_value=(FakeAnalyzer([make_face()]), CountingSwapper(), None)), \
                patch.object(face, '_source_face', return_value=make_face()), \
                patch.object(face, '_sample_reference', return_value=make_face()):
            with self.assertRaisesRegex(RuntimeError, 'Cancelled'):
                with job_process.cancellation_scope(lambda: len(swapped) >= 2):
                    face.swap_video(video, source, self.root / 'o.mp4', restore=False)
        self.assertFalse((self.root / 'o.mp4').exists())


class ComfyTests(IsolatedAIMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.server = FakeComfy().start()
        self.addCleanup(self.server.stop)
        for target, attribute, value in ((engines.comfy, 'base_url', self.server.url),
                                         (engines.comfy, 'ensure_running', MagicMock(return_value=True)),
                                         (engines.comfy, 'touch', MagicMock()),
                                         (comfy, 'requirements_missing', MagicMock(return_value=[])),
                                         (comfy, 'POLL_SECONDS', 0.01)):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_run_workflow_uploads_queues_polls_and_downloads(self):
        image = self.root / 'ref.png'
        image.write_bytes(b'png')
        updates = []
        outputs = comfy.run_workflow('flux_kontext_edit', {'image': image, 'prompt': 'make it night', 'seed': 7},
                                     progress=updates.append)
        self.assertEqual([p.read_bytes() for p in outputs], [b'PNGDATA'])
        graph = self.server.graphs[0]
        self.assertEqual(graph['10']['inputs']['image'], 'uploaded.png')
        self.assertEqual(graph['4']['inputs']['text'], 'make it night')
        self.assertEqual(graph['6']['inputs']['seed'], 7)
        self.assertEqual(graph['14']['inputs']['guidance'], 2.5)
        self.assertEqual(updates[0]['state'], 'running')
        prompt_posts = [body for method, path, body in self.server.requests if path == '/prompt']
        self.assertTrue(prompt_posts[0]['client_id'])

    def test_rejected_prompt_and_execution_errors_are_reported(self):
        self.server.fail_prompt = {'error': {'message': 'Prompt outputs failed validation'},
                                   'node_errors': {'1': {'errors': [{'message': 'Value not in list'}]}}}
        with self.assertRaisesRegex(AIUnavailable, 'Value not in list'):
            comfy.run_workflow('flux_schnell_t2i', {'prompt': 'cat'})
        self.server.fail_prompt = None
        self.server.error_history = True
        with self.assertRaisesRegex(AIUnavailable, 'CUDA out of memory'):
            comfy.run_workflow('flux_schnell_t2i', {'prompt': 'cat'})

    def test_cancel_interrupts_the_engine(self):
        self.server.history_after = 1000
        with self.assertRaisesRegex(RuntimeError, 'Cancelled'):
            with job_process.cancellation_scope(lambda: self.server.polls >= 2):
                comfy.run_workflow('flux_schnell_t2i', {'prompt': 'cat'})
        paths_hit = [path for method, path, body in self.server.requests]
        self.assertIn('/interrupt', paths_hit)

    def test_build_prompt_validation_and_requirements(self):
        with self.assertRaisesRegex(ValueError, 'Missing workflow input: prompt'):
            comfy.build_prompt('flux_schnell_t2i', {})
        for name in catalog.section('workflows'):
            _, data = comfy.workflow_spec(name)
            inputs = {k: ('x.png' if s['type'] == 'file' else 'text' if s['type'] == 'string' else 1)
                      for k, s in data['inputs'].items()}
            graph = comfy.build_prompt(name, inputs)
            self.assertNotIn('{{', json.dumps(graph))
        comfy.requirements_missing.side_effect = None
        comfy.requirements_missing.return_value = ['flux-schnell-q4']
        with self.assertRaises(ModelMissing) as raised:
            comfy.run_workflow('flux_schnell_t2i', {'prompt': 'cat'})
        self.assertEqual(raised.exception.setup_hint, 'flux-schnell-q4')

    def test_upload_missing_file(self):
        with self.assertRaises(ValueError):
            comfy.ComfyClient().upload(self.root / 'missing.png')


class RequirementsTests(unittest.TestCase):
    def test_workflow_requirements(self):
        with patch.object(models, 'installed', side_effect=lambda i: i == 'latentsync-1.5'):
            self.assertEqual(comfy.requirements_missing('latentsync'), ['node-latentsync'])


class FakeKeyring(types.ModuleType):
    def __init__(self):
        super().__init__('keyring')
        self.store = {}
        self.errors = types.SimpleNamespace(PasswordDeleteError=KeyError)

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, value):
        self.store[(service, user)] = value

    def delete_password(self, service, user):
        del self.store[(service, user)]


class CloudTests(IsolatedAIMixin, unittest.TestCase):
    KEY = 'fal-secret-key-1234567890'

    def setUp(self):
        super().setUp()
        self.keyring = FakeKeyring()
        patcher = patch.dict(sys.modules, {'keyring': self.keyring})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_keys_are_stored_masked_and_deletable(self):
        self.assertFalse(cloud.has_key('fal'))
        self.assertEqual(cloud.set_key('fal', f'  {self.KEY} '), '••••7890')
        self.assertEqual(self.keyring.store[(cloud.SERVICE, 'fal')], self.KEY)
        self.assertEqual(cloud.masked('fal'), '••••7890')
        self.assertNotIn(self.KEY, json.dumps(cloud.status()))
        self.assertTrue(cloud.delete_key('fal'))
        self.assertFalse(cloud.delete_key('fal'))
        for bad in ('', 'has space', 'x' * 600):
            with self.assertRaises(ValueError):
                cloud.set_key('fal', bad)
        with self.assertRaises(ValueError):
            cloud.set_key('openai', 'k')
        self.assertEqual(cloud.mask('short'), '••••')

    def test_missing_keyring_is_reported(self):
        with patch.dict(sys.modules, {'keyring': None}):
            self.assertFalse(cloud.has_key('fal'))
            with self.assertRaises(AIUnavailable):
                cloud.set_key('fal', self.KEY)

    def test_cloud_refuses_when_disabled_or_without_key(self):
        fal = MagicMock()
        with patch.dict(sys.modules, {'fal_client': fal}):
            with self.assertRaisesRegex(AIUnavailable, 'turned off'):
                cloud.kling_motion_control('a.png', 'b.mp4')
            with self.assertRaisesRegex(AIUnavailable, 'turned off'):
                cloud.live_portrait('a.png', 'b.mp4')
            with self.assertRaisesRegex(AIUnavailable, 'turned off'):
                cloud.nano_banana_edit(['a.png'], 'edit')
            settings.update(lambda d: d['cloud'].__setitem__('fal', {'enabled': True}))
            with self.assertRaisesRegex(AIUnavailable, 'API key'):
                cloud.kling_motion_control('a.png', 'b.mp4')
        fal.SyncClient.assert_not_called()

    def _enable_fal(self):
        settings.update(lambda d: d['cloud'].__setitem__('fal', {'enabled': True}))
        cloud.set_key('fal', self.KEY)
        client = MagicMock()
        client.upload_file.side_effect = lambda path: f'https://fal.media/{Path(path).name}'
        client.subscribe.return_value = {'video': {'url': 'https://fal.media/out.mp4'}}
        module = MagicMock()
        module.SyncClient.return_value = client
        return module, client

    def test_kling_and_live_portrait_request_shapes(self):
        module, client = self._enable_fal()
        with patch.dict(sys.modules, {'fal_client': module}):
            result = cloud.kling_motion_control('char.png', 'motion.mp4', character_orientation='image', prompt='dance')
            portrait = cloud.live_portrait('face.png', 'drive.mp4')
            cloud.kling_motion_control('char.png', 'motion.mp4', pro=True)
            with self.assertRaises(ValueError):
                cloud.kling_motion_control('char.png', 'motion.mp4', character_orientation='sideways')
        module.SyncClient.assert_called_with(key=self.KEY, default_timeout=900)
        endpoint, kwargs = client.subscribe.call_args_list[0].args[0], client.subscribe.call_args_list[0].kwargs
        self.assertEqual(endpoint, 'fal-ai/kling-video/v2.6/standard/motion-control')
        self.assertEqual(kwargs['arguments'], {'image_url': 'https://fal.media/char.png', 'video_url': 'https://fal.media/motion.mp4',
                                               'character_orientation': 'image', 'prompt': 'dance'})
        self.assertEqual(client.subscribe.call_args_list[1].args[0], 'fal-ai/live-portrait')
        self.assertEqual(set(client.subscribe.call_args_list[1].kwargs['arguments']), {'image_url', 'video_url'})
        self.assertEqual(client.subscribe.call_args_list[2].args[0], 'fal-ai/kling-video/v2.6/pro/motion-control')
        self.assertEqual(result, {'video_url': 'https://fal.media/out.mp4', 'provider': 'fal',
                                  'endpoint': 'fal-ai/kling-video/v2.6/standard/motion-control', 'local': False})
        self.assertFalse(portrait['local'])

    def test_provider_errors_never_leak_the_key(self):
        module, client = self._enable_fal()
        client.subscribe.side_effect = RuntimeError(f'401 invalid key {self.KEY}')
        with patch.dict(sys.modules, {'fal_client': module}):
            with self.assertRaises(AIUnavailable) as raised:
                cloud.kling_motion_control('char.png', 'motion.mp4')
        self.assertNotIn(self.KEY, raised.exception.message)
        self.assertIn('••••7890', raised.exception.message)
        client.subscribe.side_effect = None
        client.subscribe.return_value = {}
        with patch.dict(sys.modules, {'fal_client': module}), self.assertRaisesRegex(AIUnavailable, 'no video'):
            cloud.live_portrait('a.png', 'b.mp4')

    def test_nano_banana_saves_returned_images(self):
        settings.update(lambda d: d['cloud'].__setitem__('gemini', {'enabled': True}))
        cloud.set_key('gemini', 'gemini-key-abcdef123456')
        image = self.root / 'in.png'
        image.write_bytes(b'png')
        part = types.SimpleNamespace(inline_data=types.SimpleNamespace(data=b'edited', mime_type='image/png'))
        response = types.SimpleNamespace(candidates=[types.SimpleNamespace(content=types.SimpleNamespace(parts=[part]))])
        client = MagicMock()
        client.models.generate_content.return_value = response
        genai = types.ModuleType('google.genai')
        genai.Client = MagicMock(return_value=client)
        genai_types = types.ModuleType('google.genai.types')
        genai_types.Part = MagicMock()
        genai.types = genai_types
        google = types.ModuleType('google')
        google.genai = genai
        with patch.dict(sys.modules, {'google': google, 'google.genai': genai, 'google.genai.types': genai_types}):
            outputs = cloud.nano_banana_edit([image], 'make it sunset')
            self.assertEqual(outputs[0].read_bytes(), b'edited')
            genai.Client.assert_called_with(api_key='gemini-key-abcdef123456')
            self.assertEqual(client.models.generate_content.call_args.kwargs['model'], 'gemini-2.5-flash-image')
            client.models.generate_content.return_value = types.SimpleNamespace(candidates=[])
            with self.assertRaisesRegex(AIUnavailable, 'no image'):
                cloud.nano_banana_edit([image], 'x')
            with self.assertRaises(ValueError):
                cloud.nano_banana_edit([], 'x')

    def test_download_result(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [b'abc']
        with patch.object(cloud.requests, 'get', return_value=response):
            target = cloud.download_result('https://fal.media/out.mp4', self.root / 'dl' / 'out.mp4')
        self.assertEqual(target.read_bytes(), b'abc')


class SpeechTests(IsolatedAIMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        for target, attribute, value in ((hardware, 'detect', MagicMock(return_value=HIGH_INFO)),
                                         (engines.ollama, 'tags', MagicMock(return_value=[]))):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(asr.release)

    def test_model_choice_and_missing_hint(self):
        with self.assertRaises(ModelMissing) as raised:
            asr.whisper_model_name()
        self.assertEqual(raised.exception.setup_hint, 'whisper-large-v3-turbo')
        with patch.object(models, 'installed', side_effect=lambda i: i == 'whisper-base'):
            self.assertEqual(asr.whisper_model_name(), 'base')
        settings.update(lambda d: d['roles'].__setitem__('speech', 'small'))
        with self.assertRaises(ModelMissing) as raised:
            asr.whisper_model_name()
        self.assertEqual(raised.exception.setup_hint, 'whisper-small')
        settings.update(lambda d: d['roles'].__setitem__('speech', 'nonsense'))
        with self.assertRaises(ModelMissing):
            asr.whisper_model_name()

    def test_loads_from_local_download_root_only(self):
        local = self.root / 'models' / 'whisper' / 'large-v3-turbo.pt'
        fake_model = MagicMock()
        stable = types.ModuleType('stable_whisper')
        stable.load_model = MagicMock(return_value=fake_model)
        with patch.object(models, 'installed', side_effect=lambda i: i == 'whisper-large-v3-turbo'), \
                patch.object(models, 'ensure', return_value=local), patch.dict(sys.modules, {'stable_whisper': stable}), \
                patch.object(asr, '_device', return_value='cpu'):
            self.assertIs(asr.get_model(), fake_model)
            self.assertIs(asr.get_model(), fake_model)
        stable.load_model.assert_called_once_with('large-v3-turbo', device='cpu', download_root=str(local.parent))

    def test_transcribe_uses_vad_only_when_cached_and_never_conditions(self):
        model = MagicMock()
        model.transcribe.return_value.to_dict.return_value = {'segments': [], 'text': ''}
        asr._state.update(name='base', model=model, device='cpu')
        with patch.object(asr, 'get_model', return_value=model), patch.object(asr, '_silero_cached', return_value=False):
            result = asr.transcribe('a.wav', language='el')
        kwargs = model.transcribe.call_args.kwargs
        self.assertFalse(kwargs['vad'])
        self.assertFalse(kwargs['condition_on_previous_text'])
        self.assertIn('vad_note', result['meta'])
        with patch.object(asr, 'get_model', return_value=model), patch.object(asr, '_silero_cached', return_value=True):
            result = asr.transcribe('a.wav')
        self.assertTrue(model.transcribe.call_args.kwargs['vad'])
        self.assertNotIn('vad_note', result['meta'])
        with self.assertRaisesRegex(RuntimeError, 'Cancelled'):
            with job_process.cancellation_scope(lambda: True):
                asr._progress(1, 2)

    def test_most_voiced_window_and_candidate_language(self):
        samples = np.zeros(16000 * 90, dtype=np.float32)
        samples[16000 * 50:16000 * 80] = 0.5
        self.assertEqual(asr.most_voiced_window(samples), 16000 * 50)
        self.assertEqual(asr.most_voiced_window(np.zeros(100)), 0)
        model = MagicMock()
        model.dims.n_mels = 80
        model.detect_language.return_value = (None, {'en': 0.6, 'el': 0.3, 'ko': 0.1})
        whisper = types.ModuleType('whisper')
        whisper.log_mel_spectrogram = MagicMock()
        whisper.pad_or_trim = MagicMock(side_effect=lambda clip: clip)
        with patch.object(asr, 'get_model', return_value=model), patch.dict(sys.modules, {'whisper': whisper}):
            self.assertEqual(asr.detect_language(samples), 'en')
            self.assertEqual(asr.detect_language(samples, candidates=['el', 'ko']), 'el')
            with self.assertRaises(AIUnavailable):
                asr.detect_language(samples, candidates=['zz'])
        clip = whisper.pad_or_trim.call_args.args[0]
        self.assertEqual(len(clip), 16000 * 30)
        self.assertGreater(float(clip.mean()), 0.4)

    def test_alignment_wrappers(self):
        model = MagicMock()
        alignment = types.ModuleType('stable_whisper.alignment')
        alignment.align = MagicMock(return_value=MagicMock(to_dict=lambda: {'segments': [1]}))
        alignment.align_words = MagicMock(return_value=MagicMock(to_dict=lambda: {'segments': [2]}))
        stable = types.ModuleType('stable_whisper')
        stable.alignment = alignment
        with patch.object(asr, 'get_model', return_value=model), \
                patch.dict(sys.modules, {'stable_whisper': stable, 'stable_whisper.alignment': alignment}):
            self.assertEqual(asr.align('a.wav', 'text', 'el'), {'segments': [1]})
            self.assertEqual(asr.align_words(np.zeros(32000), 'text', 'el'), {'segments': [2]})
            self.assertEqual(alignment.align_words.call_args.args[2][0]['end'], 2.0)
            alignment.align.return_value = None
            with self.assertRaises(AIUnavailable):
                asr.align('a.wav', 'text', 'el')

    def test_vocal_isolation_requires_pack_and_model(self):
        with patch.object(asr.importlib.util, 'find_spec', return_value=None):
            with self.assertRaises(AIUnavailable) as raised:
                asr.isolate_vocals('song.wav')
        self.assertEqual(raised.exception.setup_hint, 'ai_pack')
        with patch.object(asr.importlib.util, 'find_spec', return_value=object()):
            with self.assertRaises(ModelMissing) as raised:
                asr.isolate_vocals('song.wav')
        self.assertEqual(raised.exception.setup_hint, 'uvr-kim-vocal-2')

    def test_vocal_isolation_runs_separator(self):
        model_path = self.root / 'models' / 'separator' / 'Kim_Vocal_2.onnx'
        separator_cls = MagicMock()

        def separate(path):
            out_dir = Path(separator_cls.call_args.kwargs['output_dir'])
            (out_dir / 'song_(Vocals).wav').write_bytes(b'v')
            return ['song_(Vocals).wav']
        separator_cls.return_value.separate.side_effect = separate
        module = types.ModuleType('audio_separator.separator')
        module.Separator = separator_cls
        with patch.object(asr.importlib.util, 'find_spec', return_value=object()), \
                patch.object(models, 'ensure', return_value=model_path), \
                patch.dict(sys.modules, {'audio_separator': types.ModuleType('audio_separator'), 'audio_separator.separator': module}):
            result = asr.isolate_vocals('song.wav')
        self.assertEqual(result.read_bytes(), b'v')
        separator_cls.return_value.load_model.assert_called_once_with(model_filename='Kim_Vocal_2.onnx')


class VisionTests(IsolatedAIMixin, unittest.TestCase):
    def _image(self, name, blur=False):
        import cv2
        rng = np.random.default_rng(1)
        image = (rng.random((96, 96, 3)) * 255).astype(np.uint8)
        if blur:
            image = cv2.GaussianBlur(image, (21, 21), 8)
        path = self.root / name
        cv2.imwrite(str(path), image)
        return path

    def test_caption_falls_back_to_blip_and_reports_missing(self):
        image = self._image('a.png')
        with patch.object(vision, '_vlm_available', return_value=False), patch.object(vision, '_blip_caption', return_value='a cat'):
            self.assertEqual(vision.caption(image), 'a cat')
            scene = vision.describe_scene(image)
            self.assertEqual((scene['summary'], scene['source'], scene['subject']), ('a cat', 'blip-base', None))
            self.assertEqual(vision.profile_from_portrait(image)['summary'], 'a cat')
        with patch.object(vision, '_vlm_available', return_value=False), patch.object(engines.ollama, 'tags', return_value=[]):
            with self.assertRaises(ModelMissing) as raised:
                vision.caption(image)
        self.assertEqual(raised.exception.setup_hint, 'blip-base')

    def test_vlm_structured_descriptions(self):
        image = self._image('a.png')
        answer = {'content': json.dumps({'summary': 's', 'subject': 'woman'}), 'model': 'qwen2.5vl:7b'}
        with patch.object(vision, '_vlm_available', return_value=True), patch.object(vision.llm, 'chat', return_value=answer) as chat:
            scene = vision.describe_scene(image)
            vision.profile_from_portrait(image)
        self.assertEqual((scene['subject'], scene['source']), ('woman', 'qwen2.5vl:7b'))
        self.assertEqual(chat.call_args_list[0].kwargs['schema'], vision.SCENE_SCHEMA)
        self.assertEqual(chat.call_args_list[1].kwargs['schema'], vision.PORTRAIT_SCHEMA)
        self.assertTrue(chat.call_args.kwargs['images'][0])
        with patch.object(vision, '_vlm_available', return_value=True), \
                patch.object(vision.llm, 'chat', return_value={'content': ' A photo. ', 'model': 'm'}):
            self.assertEqual(vision.caption(image), 'A photo.')
        with self.assertRaises(ValueError):
            vision._encode(self.root / 'missing.png')

    def test_rank_frames_sharpness_fallback_and_vlm(self):
        sharp, blurry = self._image('sharp.png'), self._image('blurry.png', blur=True)
        with patch.object(vision, '_vlm_available', return_value=False):
            self.assertEqual(vision.rank_frames([blurry, sharp]), [1, 0])
            self.assertEqual(vision.rank_frames([]), [])
        scores = iter([{'content': json.dumps({'score': 9, 'has_clear_face': True, 'reason': ''}), 'model': 'm'},
                       {'content': json.dumps({'score': 1, 'has_clear_face': False, 'reason': ''}), 'model': 'm'}])
        with patch.object(vision, '_vlm_available', return_value=True), patch.object(vision.llm, 'chat', side_effect=lambda *a, **k: next(scores)):
            self.assertEqual(vision.rank_frames([sharp, blurry]), [0, 1])

    def test_vlm_availability_and_blip_loading(self):
        with patch.object(vision.llm, 'resolve', side_effect=AIUnavailable('no')):
            self.assertFalse(vision._vlm_available())
        with patch.object(vision.llm, 'resolve', return_value={}):
            self.assertTrue(vision._vlm_available())
        image = self._image('a.png')
        processor, model = MagicMock(), MagicMock()
        processor.decode.return_value = ' a red car '
        transformers = types.ModuleType('transformers')
        transformers.BlipProcessor = MagicMock(from_pretrained=MagicMock(return_value=processor))
        transformers.BlipForConditionalGeneration = MagicMock(from_pretrained=MagicMock(return_value=model))
        with patch.object(models, 'ensure', return_value=self.root / 'blip' / 'model.safetensors'), \
                patch.dict(sys.modules, {'transformers': transformers}):
            self.assertEqual(vision._blip_caption(image), 'a red car')
        self.assertTrue(transformers.BlipProcessor.from_pretrained.call_args.kwargs['local_files_only'])
        vision._release_blip()


if __name__ == '__main__':
    unittest.main()
