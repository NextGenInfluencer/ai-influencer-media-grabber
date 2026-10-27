"""Regression checks for the Creator Studio audit fixes; isolated data only."""
import tests._isolation  # Must precede application imports.
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
import creator_composition as comp
from captions import register_captions
import job_process
import imageio_ffmpeg
import socket
from social_worker import public_destination


class StabilityTests(unittest.TestCase):
    def setUp(self):
        artifacts = Path(__file__).resolve().parents[1] / 'audit_artifacts'
        artifacts.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=artifacts)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.jobs = 0
        app = Flask('stability')
        register_captions(app, self.root, self.started, self.finished,
                          lambda: None, lambda: None, lambda p: False)
        self.client = app.test_client()

    def started(self):
        self.jobs += 1

    def finished(self):
        self.jobs -= 1

    def test_social_grab_uses_managed_worker_and_publishes_only_completed_file(self):
        def worker(args, **kwargs):
            self.assertEqual(self.jobs, 1)
            self.assertEqual(kwargs['timeout'], 180)
            self.assertIn('--ignore-config', args)
            self.assertIn('--max-filesize', args)
            self.assertNotIn('generic', args[args.index('--use-extractors')+1])
            dest = Path(args[args.index('-o')+1].replace('%(ext)s', 'mp4'))
            dest.write_bytes(b'fixture video')
            return subprocess.CompletedProcess(args, 0, b'', b'')
        with patch('captions.process.run', side_effect=worker):
            response = self.client.post('/api/captions/stock/grab-url', json={'url':'https://youtu.be/abcdefghijk'})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertTrue(Path(response.json['path']).is_file())
        self.assertEqual(self.jobs, 0)
        self.assertFalse(list((self.root/'Stock Media').glob('.grab-*')))

    def test_social_grab_rejects_untrusted_hosts_and_credentials_before_worker(self):
        with patch('captions.process.run') as worker:
            for url in ['http://youtube.com/a','https://127.0.0.2/a','https://192.168.1.1/a',
                        'https://169.254.169.254/a','https://youtube.com.evil.test/a',
                        'https://user:pass@youtube.com/a','https://youtube.com:8080/a']:
                response = self.client.post('/api/captions/stock/grab-url',json={'url':url})
                self.assertEqual(response.status_code,400,(url,response.json))
            worker.assert_not_called()

    def test_cancelled_download_discards_files_and_releases_job(self):
        def worker(args, **kwargs):
            Path(args[args.index('-o')+1].replace('%(ext)s','mp4')).write_bytes(b'partial')
            job_process.cancel_all()
            return subprocess.CompletedProcess(args,0,b'',b'')
        with patch('captions.process.run', side_effect=worker):
            response = self.client.post('/api/captions/stock/grab-url',json={'url':'https://youtu.be/abcdefghijk'})
        self.assertEqual(response.status_code,400)
        self.assertIn('Cancelled',response.json['error'])
        self.assertEqual(self.jobs,0)
        self.assertEqual(list((self.root/'Stock Media').iterdir()),[])

    def test_failed_download_discards_partial_files(self):
        with patch('captions.process.run',side_effect=subprocess.TimeoutExpired('yt-dlp',180)):
            response=self.client.post('/api/captions/stock/grab-url',json={'url':'https://www.tiktok.com/@example/video/123'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.jobs,0)
        self.assertEqual(list((self.root/'Stock Media').iterdir()),[])

    def test_worker_rejects_private_redirect_and_dns_destinations(self):
        for ip in ['127.0.0.2','192.168.1.1','169.254.169.254','10.1.2.3','::1','fd00::1']:
            with patch('social_worker.socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443))]):
                with self.assertRaisesRegex(OSError,'Private or reserved'):
                    public_destination(('cdn.example',443),socket.AF_INET,socket.SOCK_STREAM)
        with patch('social_worker.socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]):
            self.assertEqual(public_destination(('cdn.example',443),socket.AF_INET,socket.SOCK_STREAM),('8.8.8.8',443))

    def test_search_worker_obeys_duration_filter(self):
        import json
        payload={'entries':[dict(id='abcdefghijk',duration=20),dict(id='mnopqrstuvw',duration=50)]}
        with patch('creator_composition.process.run',return_value=subprocess.CompletedProcess([],0,json.dumps(payload).encode(),b'')) as worker:
            results=comp._search_youtube('dance','portrait',30)
        self.assertEqual([r['id'] for r in results],['abcdefghijk'])
        self.assertEqual(worker.call_args.kwargs['timeout'],45)

    def test_long_song_cycles_without_stretching_and_reuses_inputs(self):
        assets={'audio':dict(file='song.wav',kind='audio'),
                'background':dict(file='one.mp4',kind='video'),
                'clip_aabbccdd':dict(file='two.mp4',kind='video')}
        seq=[dict(asset='background',duration=1),dict(asset='clip_aabbccdd',duration=1)]
        schedule=comp.schedule_sequence(seq,assets,213)
        self.assertEqual(len(schedule),213)
        self.assertTrue(all(s['duration']==1 for s in schedule))
        self.assertEqual(schedule[-1]['start'],212)
        settings={**comp.DEFAULTS,'end':213,'sequence':seq}
        args=comp.render_args(comp.schema(assets,settings,{}),self.root,'out.mp4')
        self.assertEqual(args.count('-i'),3)
        self.assertIn('concat=n=213',args[args.index('-filter_complex')+1])
        with self.assertRaisesRegex(ValueError,'600 cuts'):
            comp.schedule_sequence(seq,assets,1200)
        with self.assertRaisesRegex(ValueError,'0.05'):
            comp.schedule_sequence([dict(asset='background',duration=0.01)],assets,10)
        self.assertEqual(len(comp.schedule_sequence(seq[:1],assets,4)),4)

    def test_real_render_repeated_short_mixed_clips(self):
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        def run(args):
            return subprocess.run([ff,'-hide_banner','-loglevel','error','-y',*args],
                                  cwd=self.root,capture_output=True,check=True,timeout=60).stdout
        run(['-f','lavfi','-i','sine=frequency=440:duration=4','song.wav'])
        for filename,size,color in [('one.mp4','120x200','red'),('two.mp4','320x180','blue')]:
            run(['-f','lavfi','-i',f'color={color}:s={size}:r=15','-t','0.4','-c:v','libx264',filename])
        assets={'audio':dict(file='song.wav',kind='audio'),
                'background':dict(file='one.mp4',kind='video'),
                'clip_aabbccdd':dict(file='two.mp4',kind='video')}
        settings={**comp.DEFAULTS,'end':4,'sequence':[
            dict(asset='background',duration=1),dict(asset='clip_aabbccdd',duration=1)]}
        with patch.dict(comp.SHAPES,{'portrait':(180,320)}):
            run(comp.render_args(comp.schema(assets,settings,{}),self.root,'render.mp4'))
        for time,channel in [(0.5,0),(1.5,2),(2.5,0),(3.5,2)]:
            pixel=run(['-ss',str(time),'-i','render.mp4','-frames:v','1','-vf','scale=1:1',
                       '-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
            self.assertEqual(len(pixel),3)
            self.assertGreater(pixel[channel],220)


if __name__ == '__main__':
    unittest.main()
