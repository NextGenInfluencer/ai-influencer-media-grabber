"""Real output checks for the v3.1.3 audit regressions."""
import tests._isolation
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import imageio_ffmpeg
import creator_composition as comp
import hwaccel
from safe_update import stage_archive, apply_pending


class ReleaseRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=tests._isolation.DATA_ROOT)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def ff(self, args):
        return subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y', *args],
                              cwd=self.root, capture_output=True, check=True, timeout=45).stdout

    def test_real_split_speed_audio_and_all_transitions(self):
        self.ff(['-f','lavfi','-i','sine=frequency=220:duration=4','song.wav'])
        self.ff(['-f','lavfi','-i','color=red:s=80x120:r=30:d=2','-f','lavfi','-i',
                 'color=blue:s=80x120:r=30:d=2','-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0','changing.mp4'])
        self.ff(['-f','lavfi','-i','color=green:s=120x80:r=24:d=2','-f','lavfi','-i',
                 'sine=frequency=880:duration=1','-c:a','aac','sound.mp4'])
        assets = {'audio':dict(file='song.wav',kind='audio'),
                  'background':dict(file='changing.mp4',kind='video',has_audio=False),
                  'clip_sound':dict(file='sound.mp4',kind='video',has_audio=True)}
        def render(settings):
            clean = comp.validate({**comp.DEFAULTS,'end':4,**settings},4)
            with patch.dict(comp.SHAPES, {'portrait':(80,120)}), patch('hwaccel.get_video_encoder_args',return_value=['-c:v','libx264','-preset','ultrafast','-crf','18']):
                self.ff(comp.render_args(comp.schema(assets,clean,{}),self.root,'out.mp4',True))
        def blue_at(t):
            pixel = self.ff(['-ss',str(t),'-i','out.mp4','-frames:v','1','-vf','scale=1:1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
            self.assertGreater(pixel[2],220)
            self.assertLess(pixel[0],30)
        render({'sequence':[dict(asset='background',duration=2),dict(asset='background',duration=2,source_start=2)]})
        blue_at(3)
        render({'sequence':[dict(asset='background',duration=0,speed=2)]})
        blue_at(1.5)
        for transition in sorted(comp.SEQUENCE_TRANSITIONS):
            with self.subTest(transition=transition):
                render({'background_volume':1,'sequence_transition':transition,
                        'sequence':[dict(asset='background',duration=2),dict(asset='clip_sound',duration=2)]})
                decoded = self.ff(['-i','out.mp4','-vn','-ac','1','-ar','1000','-f','s16le','pipe:1'])
                self.assertGreaterEqual(len(decoded),7900)
                blue_at_end = self.ff(['-ss','3.8','-i','out.mp4','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
                self.assertTrue(blue_at_end)

    def test_updater_installs_new_dependency_and_excludes_user_fonts(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive,'w') as z:
            for name,body in {'app_local.py':'import hwaccel\nassert hwaccel.READY',
                              'hwaccel.py':'READY=True','safe_update.py':'# fixture',
                              'templates/index.html':'ok','requirements.txt':'',
                              'static/fonts/custom/private.ttf':'private'}.items():
                z.writestr('release/'+name,body)
        archive.seek(0)
        stage_archive(self.root,archive,'3.1.4')
        self.assertTrue(apply_pending(self.root))
        self.assertTrue((self.root/'hwaccel.py').is_file())
        self.assertFalse((self.root/'static/fonts/custom/private.ttf').exists())

    def test_gpu_failure_retries_once_transactionally(self):
        calls = []
        def runner(cmd, **kwargs):
            calls.append(cmd)
            if len(calls)==1:
                return subprocess.CompletedProcess(cmd,1,b'',b'Error while opening encoder')
            Path(cmd[-1]).write_bytes(b'completed')
            return subprocess.CompletedProcess(cmd,0,b'',b'')
        result = hwaccel.run_render(['ffmpeg','-y','-i','input.mp4','-c:v','h264_nvenc','-cq','19','out.mp4'],cwd=self.root,runner=runner)
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.video_encoder,'libx264')
        self.assertEqual((self.root/'out.mp4').read_bytes(),b'completed')
        self.assertNotIn('-cq',calls[1])
        self.assertFalse(list(self.root.glob('.cpu-*')))

    def test_bad_filter_does_not_trigger_encoder_retry(self):
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],1,b'',b'No such filter')) as run:
            hwaccel.run_render(['ffmpeg','-c:v','h264_nvenc','out.mp4'],cwd=self.root,runner=run)
            self.assertEqual(run.call_count,1)

    def test_current_app_starts_with_old_updater_manifest(self):
        import safe_update
        repo = Path(__file__).resolve().parents[1]
        archive = io.BytesIO()
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
            files = [repo/name for name in safe_update.FILES if (repo/name).is_file()]
            for directory in safe_update.DIRECTORIES:
                files.extend(p for p in (repo/directory).rglob('*') if p.is_file()
                             and 'custom' not in p.parts and '__pycache__' not in p.parts)
            for path in files:
                z.write(path,'release/'+path.relative_to(repo).as_posix())
        archive.seek(0)
        # v3.1.3's allowlist dropped the new root-level encoder module.
        with patch.object(safe_update,'FILES',safe_update.FILES-{'hwaccel.py'}):
            stage_archive(self.root,archive,'3.1.4')
        self.assertTrue((self.root/'.updates/pending.json').is_file())

    def test_sticker_animation_render_and_clean_preview(self):
        from PIL import Image
        Image.new('RGBA',(20,20),(255,0,0,255)).save(self.root/'sticker.png')
        self.ff(['-f','lavfi','-i','sine=frequency=220:duration=1','song.wav'])
        assets={'audio':dict(file='song.wav',kind='audio'), 'sticker':dict(file='sticker.png',kind='image')}
        settings={**comp.DEFAULTS,'end':1,'sticker_duration':1,'sticker_x':50,'sticker_y':50,'sticker_scale':50}
        def count_red(filename,time):
            data=self.ff(['-ss',str(time),'-i',filename,'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
            return sum(data[i]>180 and data[i+1]<80 and data[i+2]<80 for i in range(0,len(data),3))
        with patch.dict(comp.SHAPES,{'portrait':(80,120)}),patch('hwaccel.get_video_encoder_args',return_value=['-c:v','libx264','-preset','ultrafast','-crf','18']):
            for anim in sorted(comp.STICKER_ANIMATIONS):
                studio=comp.schema(assets,{**settings,'sticker_anim':anim},{})
                self.ff(comp.render_args(studio,self.root,'sticker.mp4'))
                self.assertGreater(count_red('sticker.mp4',.5),100)
                if anim=='pop':
                    self.assertLess(count_red('sticker.mp4',.033),count_red('sticker.mp4',.5))
            self.ff(comp.render_args(studio,self.root,'preview.mp4',include_sticker=False))
            self.assertEqual(count_red('preview.mp4',.5),0)

    def test_correction_retains_unchanged_word_timings(self):
        from captions import match_lyrics_to_transcription
        for text in ('Hello world','Bonjour amour','Γεια σου','사랑해 hello'):
            words=text.split()
            cue=dict(start=1,end=3,text=text,words=[dict(text=w,start=1+i*.5,end=1.4+i*.5) for i,w in enumerate(words)])
            result=match_lyrics_to_transcription([cue],[text],4)
            self.assertEqual(result[0]['words'],cue['words'])
