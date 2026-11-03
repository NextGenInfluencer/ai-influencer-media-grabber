"""AI Studio services: media resolution, audio handling, real engine calls and the Director math."""
import tests._isolation  # Must precede application imports
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from assets import ai_video_engine, motion_studio
from ai_core.errors import AIUnavailable


class MotionStudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=tests._isolation.DATA_ROOT)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        patches = {'DATA_DIR': root, 'REFERENCES_DIR': root / 'References', 'MOTION_OUTPUT_DIR': root / 'Motion Outputs',
                   'DRIVING_REF_DIR': root / 'Driving References'}
        for name, value in patches.items():
            patcher = patch.object(motion_studio, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = root
        motion_studio._ensure_dirs()

    def test_resolve_media_source_stays_inside_library(self):
        pid = 'a' * 32
        song = self.root / 'Caption Projects' / pid / 'song.mp3'
        song.parent.mkdir(parents=True)
        song.write_bytes(b'x')
        self.assertEqual(motion_studio.resolve_media_source(f'/api/captions/{pid}/media/song.mp3'), song.resolve())
        self.assertIsNone(motion_studio.resolve_media_source('/api/captions/not-a-project/media/song.mp3'))
        self.assertIsNone(motion_studio.resolve_media_source('../../app_local.py'))
        self.assertIsNone(motion_studio.resolve_media_source(str(Path(__file__).resolve())))
        ref = motion_studio.REFERENCES_DIR / 'face.png'
        ref.write_bytes(b'png')
        self.assertEqual(motion_studio.resolve_image_path('/api/motion/references/file/face.png'), ref.resolve())
        self.assertEqual(motion_studio.resolve_image_path('face.png'), ref.resolve())
        self.assertIsNone(motion_studio.resolve_image_path('missing.png'))

    def test_extract_reference_frame(self):
        with self.assertRaises(FileNotFoundError):
            motion_studio.extract_reference_frame('non_existent_video.mp4', 1.5)
        video = self.root / 'clip.mp4'
        video.write_bytes(b'video')

        def fake_run(command, capture_output=True):
            Path(command[-1]).write_bytes(b'png')
            return SimpleNamespace(returncode=0, stderr=b'')
        with patch('assets.motion_studio.subprocess.run', side_effect=fake_run) as run:
            result = motion_studio.extract_reference_frame(str(video), timestamp_sec=2.5)
        self.assertIn('2.500', run.call_args.args[0])
        self.assertTrue(result['url'].startswith('/api/motion/references/file/ref_clip_250_'))

    def test_apply_audio_modes(self):
        video = motion_studio.MOTION_OUTPUT_DIR / 'out.mp4'
        audio = self.root / 'song.mp3'
        audio.write_bytes(b'a')
        self.assertEqual(motion_studio.apply_audio(video, mode='original'), video)
        with self.assertRaises(ValueError):
            motion_studio.apply_audio(video, mode='louder')
        with self.assertRaises(FileNotFoundError):
            motion_studio.apply_audio(video, mode='project', audio=self.root / 'missing.mp3')
        for mode, expected in (('mute', '-an'), ('project', str(audio))):
            video.write_bytes(b'v')

            def fake_run(command, capture_output=True):
                Path(command[-1]).write_bytes(b'v2')
                return SimpleNamespace(returncode=0, stderr=b'')
            with patch('assets.motion_studio.subprocess.run', side_effect=fake_run) as run:
                final = motion_studio.apply_audio(video, mode=mode, audio=audio)
            self.assertIn(expected, run.call_args.args[0])
            self.assertTrue(final.is_file())
            self.assertFalse(video.exists())
            final.unlink()

    def test_lip_sync_and_live_portrait_use_pinned_workflows(self):
        produced = self.root / 'AI Studio' / 'mg.mp4'
        produced.parent.mkdir()

        def fake_workflow(name, inputs, progress=None):
            produced.write_bytes(b'mp4')
            return [produced]
        with patch('assets.motion_studio.comfy.run_workflow', side_effect=fake_workflow) as run:
            result = motion_studio.lip_sync('face.mp4', 'song.mp3')
            self.assertEqual(run.call_args.args, ('latentsync', {'video': 'face.mp4', 'audio': 'song.mp3'}))
            self.assertTrue(result['url'].startswith('/api/motion/outputs/file/motion_lipsync_'))
            motion_studio.live_portrait('face.png', 'drive.mp4')
            self.assertEqual(run.call_args.args[0], 'liveportrait')

    def test_missing_engines_raise_instead_of_faking(self):
        with self.assertRaises(AIUnavailable):
            motion_studio.lip_sync('face.mp4', 'song.mp3')  # LatentSync is not installed in a fresh profile
        with self.assertRaises(AIUnavailable) as caught:
            motion_studio.cloud_motion('face.png', 'drive.mp4')
        self.assertEqual(caught.exception.setup_hint, 'cloud')  # cloud is opt-in and off by default
        self.assertEqual(list(motion_studio.MOTION_OUTPUT_DIR.iterdir()), [])

    def test_face_swap_video_passes_audio_choice(self):
        def fake_swap(target, source, output, **kwargs):
            Path(output).write_bytes(b'v')
            return {'provider': 'CUDAExecutionProvider'}
        with patch('assets.motion_studio.face.swap_video', side_effect=fake_swap), \
                patch('assets.motion_studio.apply_audio', side_effect=lambda path, **kw: Path(path)) as apply_audio:
            result = motion_studio.face_swap_video('in.mp4', 'face.png', audio_mode='mute')
        self.assertEqual(apply_audio.call_args.kwargs, {'mode': 'mute', 'audio': None})
        self.assertEqual(result['provider'], 'CUDAExecutionProvider')


class DirectorMathTests(unittest.TestCase):
    def test_beat_onsets_find_energy_jumps(self):
        peaks = ([0.05] * 50 + [0.9] + [0.3] * 49) * 4  # four hits in 4 s
        onsets = ai_video_engine.beat_onsets(peaks, 4.0)
        self.assertEqual(len(onsets), 4)
        self.assertAlmostEqual(onsets[1] - onsets[0], 1.0, places=1)
        self.assertEqual(ai_video_engine.beat_onsets([], 4.0), [])

    def test_normalize_scenes_snaps_and_drops_slivers(self):
        raw = [{'start': 0.2, 'end': 3.9, 'image_prompt': 'a'}, {'start': 3.9, 'end': 4.1, 'image_prompt': 'b'},
               {'start': 4.0, 'end': 99, 'image_prompt': 'c', 'use_character': False}, {'start': 5, 'end': 6, 'image_prompt': ''}]
        scenes = ai_video_engine.normalize_scenes(raw, 10.0, anchors=[0.0, 4.0])
        self.assertEqual([(s['start'], s['end']) for s in scenes], [(0.0, 4.0), (4.0, 10.0)])
        self.assertEqual([s['id'] for s in scenes], ['scene_001', 'scene_002'])
        self.assertFalse(scenes[1]['use_character'])

    def test_frames_follow_model_limits(self):
        self.assertEqual(ai_video_engine.frames_for(5, 'fast'), 121)
        self.assertEqual(ai_video_engine.frames_for(5, 'quality'), 81)
        self.assertEqual(ai_video_engine.frames_for(2, 'fast') % 4, 1)

    def test_director_requires_real_model(self):
        with patch('assets.ai_video_engine.llm.chat', side_effect=AIUnavailable('No helper.', setup_hint='qwen3:8b')):
            with self.assertRaises(AIUnavailable):
                ai_video_engine.direct_storyboard(concept='neon', duration=10)
        with self.assertRaises(ValueError):
            ai_video_engine.direct_storyboard(duration=10)

    def test_no_procedural_generators_remain(self):
        for name in ('infer_lyric_atmosphere', 'generate_storyboard', 'render_keyframe_image', 'render_scene_video',
                     'analyze_song_and_suggest_styles', 'create_video_studio_project'):
            self.assertFalse(hasattr(ai_video_engine, name), name)
        for name in ('detect_facefusion', 'cloud_swap_identity', 'get_neural_swapper', 'render_character_motion'):
            self.assertFalse(hasattr(motion_studio, name), name)


if __name__ == '__main__':
    unittest.main()
