"""Captions Studio v5: storyboard bridge, disk hygiene, preview/export parity and rendering."""
import tests._isolation  # Must precede application imports.
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import imageio_ffmpeg

import creator_composition
from captions import prune_renders
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
