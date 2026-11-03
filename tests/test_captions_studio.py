"""Captions Studio v5: storyboard bridge, disk hygiene, preview/export parity and rendering."""
import tests._isolation  # Must precede application imports.
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import imageio_ffmpeg

import creator_composition
from captions import ANIM, DEFAULT_STYLE, adopt_composition_visualizer, ass_text, prune_renders
from tests import test_captions

ROOT = Path(__file__).resolve().parents[1]


def make_clip(path, seconds=1, color='red'):
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-f', 'lavfi', '-i', f'color={color}:size=160x120:rate=10',
                    '-t', str(seconds), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], capture_output=True, check=True)


class DiskHygieneTests(unittest.TestCase):
    def test_prune_keeps_referenced_renders_last_three_checks_and_user_media(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            names = ['original.mp4', 'song.wav', 'background.png', 'asset_' + 'a' * 32 + '.mp4', 'preview.mp4',
                     'composition_aaaaaaaaaaaa.mp4', 'preview_aaaaaaaaaaaa.mp4',      # two applies ago
                     'composition_bbbbbbbbbbbb.mp4', 'preview_bbbbbbbbbbbb.mp4',      # restore point
                     'composition_cccccccccccc.mp4', 'preview_cccccccccccc.mp4',      # current
                     'captioned_dddddddddddd.mp4', 'composition_notes.mp4', 'project.json']
            checks = [f'check_{c * 12}.mp4' for c in '12345']
            for name in names + checks:
                (folder / name).write_bytes(b'x')
            project = dict(source='composition_cccccccccccc.mp4', preview='preview_cccccccccccc.mp4',
                           composition_backup=dict(source='composition_bbbbbbbbbbbb.mp4', preview='preview_bbbbbbbbbbbb.mp4'),
                           exports=[checks[0], 'captioned_dddddddddddd.mp4', *checks[1:]], last_render=checks[-1])
            removed = prune_renders(project, folder)
            self.assertEqual(sorted(removed), sorted(['composition_aaaaaaaaaaaa.mp4', 'preview_aaaaaaaaaaaa.mp4', *checks[:2]]))
            self.assertEqual(project['exports'], ['captioned_dddddddddddd.mp4', *checks[2:]])
            remaining = {p.name for p in folder.iterdir()}
            for name in names:
                if name not in removed:
                    self.assertIn(name, remaining)
            self.assertEqual(prune_renders(project, folder), [])


class PreviewExportParityTests(unittest.TestCase):
    def test_animation_constants_are_shared_by_preview_and_export(self):
        shared = json.loads((ROOT / 'static' / 'anim_constants.json').read_text(encoding='utf-8'))
        self.assertEqual(ANIM, shared)
        result = subprocess.run(['node', '-e', 'console.log(JSON.stringify(require("./static/captions.js").ANIM_DEFAULTS))'],
                                cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), shared, 'Embedded JS fallback must equal anim_constants.json')
        source = (ROOT / 'static' / 'captions.js').read_text(encoding='utf-8')
        start = source.index('function drawCaption()')
        body = source[start:source.index('function drawTitleCard(', start)]
        for legacy in ('0.32', '0.30', '0.55 + 0.59', '0.45 + 0.55', '* 0.05)', 'animElapsed/0.25'):
            self.assertNotIn(legacy, body, 'Single-line preview must use the shared export curves')

    def test_glow_is_a_halo_layer_under_sharp_text(self):
        cue = dict(start=0, end=1, text='Glow', words=[])
        style = {**DEFAULT_STYLE, 'glow': 6, 'highlight': '#ff0000', 'size': 12, 'outline': 0}
        script = ass_text(dict(cues=[cue], width=320, height=180, style=style))
        halos = [l for l in script.splitlines() if l.startswith('Dialogue: -1,') and ',Glow,' in l]
        texts = [l for l in script.splitlines() if l.startswith('Dialogue: 0,')]
        self.assertEqual(len(halos), 1)
        self.assertIn(r'\1a&HFF&\blur', halos[0])
        self.assertNotIn(r'\blur', texts[0])
        self.assertIn('Style: Glow,', script)

        def red_pixels(glow):
            with tempfile.TemporaryDirectory() as directory:
                Path(directory, 'c.ass').write_text(ass_text(dict(cues=[cue], width=320, height=180, style={**style, 'glow': glow})), encoding='utf-8')
                frame = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-f', 'lavfi', '-i',
                                        'color=black:size=320x180:rate=10:duration=0.5', '-vf', 'ass=c.ass', '-frames:v', '1', '-ss', '0.3',
                                        '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], cwd=directory, capture_output=True, check=True, timeout=30).stdout
            return sum(1 for i in range(0, len(frame), 3) if frame[i] > 60 and frame[i + 1] < 40 and frame[i + 2] < 40)
        self.assertEqual(red_pixels(0), 0)
        self.assertGreater(red_pixels(6), 200, 'Glow renders as a visible highlight halo')

    def test_title_card_has_rounded_plate_fade_and_scale_from_constants(self):
        project = dict(cues=[], width=1080, height=1920, duration=5, style=dict(DEFAULT_STYLE),
                       studio=dict(settings=dict(title_text='Intro', title_duration=3)))
        lines = ass_text(project).splitlines()
        plate = next(l for l in lines if l.startswith('Dialogue: 1,') and r'\p1' in l)
        title = next(l for l in lines if l.startswith('Dialogue: 2,'))
        self.assertIn(r'\fad(250,350)', plate)
        self.assertIn(r'\alpha&H38&', plate)
        self.assertIn(',Title,', title)
        self.assertIn(rf"\pos(540,{round(1920 * ANIM['title']['y'])})", title)
        self.assertIn(r'\fad(250,350)', title)

    def test_background_captions_use_the_shared_rounded_layout(self):
        cue = dict(start=0, end=1, text='Boxed line', words=[])
        script = ass_text(dict(cues=[cue], width=1080, height=1920, style={**DEFAULT_STYLE, 'background': True}))
        self.assertIn('Style: Row0,', script)
        self.assertTrue(any(l.startswith('Dialogue: -1,') and r'\p1' in l and r'\c&H140C0A&' in l for l in script.splitlines()))

    def test_single_visualizer(self):
        project = dict(style=dict(DEFAULT_STYLE), studio=dict(settings=dict(visualizer=True, visualizer_style='spectrum', visualizer_color='#00ff00')))
        adopt_composition_visualizer(project)
        self.assertTrue(project['style']['visualizer'])
        self.assertEqual(project['style']['visualizer_color'], '#00ff00')
        self.assertFalse(project['studio']['settings']['visualizer'])
        html = (ROOT / 'templates' / 'captions.html').read_text(encoding='utf-8')
        self.assertNotIn('comp_visualizer', html)
        self.assertIn('Animated bars', html)
        self.assertNotIn('Spectrum EQ', html)
        source = (ROOT / 'static' / 'captions.js').read_text(encoding='utf-8')
        keys = source[source.index('const compositionKeys='):source.index('let previousComposition')]
        self.assertNotIn('visualizer', keys)


class StoryboardBridgeTests(unittest.TestCase):
    setUp = test_captions.CaptionWorkflowTests.setUp
    tearDown = test_captions.CaptionWorkflowTests.tearDown
    wait = test_captions.CaptionWorkflowTests.wait
    j = test_captions.CaptionWorkflowTests.j
    karaoke_project = test_captions.CaptionWorkflowTests.karaoke_project

    def test_bridge_registers_scene_assets_and_the_sequence_actually_schedules(self):
        pid, data = self.karaoke_project()
        stock = self.root / 'library' / 'Stock Media'
        stock.mkdir(parents=True, exist_ok=True)
        scenes = []
        for index, color in enumerate(('red', 'green'), 1):
            clip = stock / f'scene_{index}.mp4'
            make_clip(clip, color=color)
            scenes.append(dict(id=f's{index}', lyric=f'Scene {index}', start=index - 1, end=index, video_path=str(clip)))
        saved = self.j(self.client.post(f'/api/captions/{pid}/storyboard', json={'storyboard': scenes}))
        self.assertEqual(saved['revision'], data['revision'], 'Storyboard metadata must not bump the revision')
        self.assertEqual(self.client.post(f'/api/captions/{pid}/bridge-storyboard', json={}).status_code, 409)
        outside = [dict(id='x', video_path=str(self.source))]
        response = self.client.post(f'/api/captions/{pid}/bridge-storyboard', json={'revision': data['revision'], 'storyboard': outside})
        self.assertEqual(response.status_code, 400)
        self.assertIn('outside your library', response.json['error'])
        response = self.client.post(f'/api/captions/{pid}/bridge-storyboard', json={'revision': data['revision']})
        self.assertEqual(response.status_code, 202, response.data)
        after = self.wait(pid)
        self.assertEqual(after['revision'], data['revision'] + 1)
        sequence = after['studio']['settings']['sequence']
        self.assertEqual([item['name'] for item in sequence], ['Scene 1', 'Scene 2'])
        folder = self.root / 'library' / 'Caption Projects' / pid
        for item in sequence:
            self.assertEqual(set(item), {'asset', 'name', 'duration', 'speed', 'source_start'})
            asset = after['studio']['assets'][item['asset']]
            self.assertTrue(item['asset'].startswith('clip_'))
            self.assertEqual(asset['kind'], 'video')
            self.assertTrue((folder / asset['file']).is_file())
        clips = after['studio']['tracks'][0]['clips']
        self.assertEqual([clip['asset'] for clip in clips], [item['asset'] for item in sequence])
        total = after['studio']['settings']['end'] - after['studio']['settings']['start'] + after['studio']['settings']['offset']
        scheduled = creator_composition.schedule_sequence(sequence, after['studio']['assets'], total, after['studio']['settings']['loop'])
        self.assertEqual(len(scheduled), 2)
        self.assertTrue(after['source'].startswith('composition_'))
        self.assertTrue((folder / after['source']).is_file())
        self.assertTrue((stock / 'scene_1.mp4').is_file(), 'Library media is copied, never moved')


if __name__ == '__main__':
    unittest.main()
