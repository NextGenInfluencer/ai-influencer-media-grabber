import copy
import io
import json
from pathlib import Path
import tempfile
import urllib.error
import urllib.request
import unittest
import creator_composition as comp


class _FakeResponse:
    def __init__(self, body: bytes, url: str = 'https://videos.pexels.com/video-files/123/123.mp4',
                 headers: dict | None = None):
        self._stream = io.BytesIO(body)
        self._url = url
        self.headers = headers or {'Content-Type': 'video/mp4', 'Content-Length': str(len(body))}

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _FakeOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def open(self, req, timeout=12):
        self.requests.append(req)
        if self.error:
            raise self.error
        return self.response


class CompositionDataTests(unittest.TestCase):
    def test_trim_shifts_words_and_flags_cut_lines_without_mutating_original(self):
        cues=[dict(start=.2,end=1,text='Bonjour hello',words=[dict(text='Bonjour',start=.2,end=.6),dict(text='hello',start=.6,end=1)]),
              dict(start=2,end=3,text='안녕',words=[])]
        original=copy.deepcopy(cues)
        shifted=comp.shift_cues(cues,.5,3)
        self.assertEqual(shifted[0]['start'],.7)
        self.assertEqual(shifted[0]['words'][0]['end'],1.1)
        self.assertEqual(shifted[1]['end'],3)
        self.assertEqual(shifted[1]['karaoke']['state'],'review')
        self.assertEqual(comp.shift_cues(cues,-1.5,2)[0]['text'],'안녕')
        self.assertEqual(cues,original)

    def test_validation_rejects_nonfinite_reversed_ranges_and_filter_injection(self):
        base={**comp.DEFAULTS,'end':5}
        for change in [dict(start=6),dict(end=0),dict(offset=float('nan')),dict(color='red;movie=secret'),dict(fit='invalid'),dict(loop='yes'),dict(fade_out=6),dict(zoom=1)]:
            with self.subTest(change=change), self.assertRaises(ValueError): comp.validate({**base,**change},5)
        self.assertEqual(comp.validate(base,5)['end'],5)

    def test_asset_paths_and_future_schema_are_rejected(self):
        folder=Path.cwd()
        for name in ('../secret','a/b','a\\b','C:\\secret'):
            with self.assertRaises(ValueError):comp.local_asset(folder,dict(file=name))
        with self.assertRaises(ValueError):comp.migrate(dict(studio=dict(version=999)),folder)

    def test_legacy_migration_and_track_offsets_are_nondestructive(self):
        artifacts=Path(__file__).resolve().parents[1]/'audit_artifacts'
        artifacts.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=artifacts) as directory:
            folder=Path(directory);(folder/'song.wav').touch();(folder/'background.png').touch()
            old=dict(duration=10,width=1080,height=1920,source='original.mp4',style={'font':'Arial'},composition={'shape':'portrait','color':'#123456','visualizer':True})
            before=copy.deepcopy(old);studio=comp.migrate(old,folder)
            self.assertEqual(old,before)
            self.assertEqual(studio['assets']['audio']['file'],'song.wav')
            self.assertEqual(studio['assets']['background']['kind'],'image')
            self.assertEqual(studio['tracks'][1]['clips'][0]['source_offset'],0)
            self.assertEqual(studio['timebase'],'seconds')

    def test_stock_url_redirect_and_provenance_validation(self):
        self.assertEqual(comp.validate_stock_url('https://videos.pexels.com/video-files/1/1.mp4', 'pexels'),
                         'https://videos.pexels.com/video-files/1/1.mp4')
        self.assertEqual(comp.validate_stock_url('https://cdn.pixabay.com/video/2024/01/01/1.mp4', 'pixabay'),
                         'https://cdn.pixabay.com/video/2024/01/01/1.mp4')
        for bad_url in [
            'http://videos.pexels.com/1.mp4',
            'https://evil.com/pexels.com/1.mp4',
            'https://user:pass@videos.pexels.com/1.mp4',
            'https://videos.pexels.com:8443/1.mp4',
            'file:///C:/Windows/System32/cmd.exe',
            'https://cdn.pixabay.com/1.mp4',  # wrong provider for pexels
        ]:
            with self.subTest(bad_url=bad_url), self.assertRaises(ValueError):
                comp.validate_stock_url(bad_url, 'pexels')

        # Redirect handler must block cross-domain redirects outside the provider allowlist
        handler = comp._SafeRedirectHandler('pexels')
        req = urllib.request.Request('https://videos.pexels.com/1.mp4')
        with self.assertRaises(ValueError):
            handler.redirect_request(req, None, 302, 'Found', {}, 'https://attacker.example.com/1.mp4')

        prov = comp.validate_provenance(dict(
            provider='pexels',
            creator='Alice Studio',
            source_url='https://www.pexels.com/video/123/',
            attribution='Video by Alice Studio on Pexels'
        ))
        self.assertEqual(prov['license'], 'Pexels License')
        self.assertEqual(prov['creator'], 'Alice Studio')

    def test_stock_search_filters_and_error_handling(self):
        with self.assertRaisesRegex(ValueError, 'API key'):
            comp.search_stock('pexels', 'neon', api_key='')

        pexels_payload = {
            'videos': [
                {
                    'id': 101,
                    'duration': 15,
                    'url': 'https://www.pexels.com/video/101/',
                    'image': 'https://images.pexels.com/videos/101/thumb.jpg',
                    'user': {'name': 'Neon Artist'},
                    'video_files': [
                        {'file_type': 'video/mp4', 'width': 1080, 'height': 1920,
                         'link': 'https://videos.pexels.com/video-files/101/hd.mp4'}
                    ]
                },
                {
                    'id': 102,
                    'duration': 95,  # exceeds max_duration=30
                    'url': 'https://www.pexels.com/video/102/',
                    'image': 'https://images.pexels.com/videos/102/thumb.jpg',
                    'user': {'name': 'Long Creator'},
                    'video_files': [
                        {'file_type': 'video/mp4', 'width': 1080, 'height': 1920,
                         'link': 'https://videos.pexels.com/video-files/102/hd.mp4'}
                    ]
                }
            ]
        }
        opener = _FakeOpener(_FakeResponse(json.dumps(pexels_payload).encode('utf-8')))
        results = comp.search_stock('pexels', 'neon city', kind='video', orientation='portrait',
                                    max_duration=30, api_key='test-key', opener=opener)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], '101')
        self.assertEqual(results[0]['creator'], 'Neon Artist')
        self.assertEqual(results[0]['license'], 'Pexels License')

        # HTTP 429 rate-limit error
        rate_err = urllib.error.HTTPError('https://api.pexels.com', 429, 'Too Many Requests', {}, None)
        with self.assertRaisesRegex(ValueError, 'rate limit'):
            comp.search_stock('pexels', 'neon', api_key='k', opener=_FakeOpener(error=rate_err))

        # HTTP 401 auth error
        auth_err = urllib.error.HTTPError('https://api.pexels.com', 401, 'Unauthorized', {}, None)
        with self.assertRaisesRegex(ValueError, 'rejected the API key'):
            comp.search_stock('pexels', 'neon', api_key='k', opener=_FakeOpener(error=auth_err))

    def test_stock_download_bounds_magic_bytes_and_cancellation(self):
        artifacts = Path(__file__).resolve().parents[1] / 'audit_artifacts'
        artifacts.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=artifacts) as directory:
            dest = Path(directory) / 'clip.mp4'
            valid_mp4 = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom' + (b'\x00' * 128)
            opener = _FakeOpener(_FakeResponse(valid_mp4))
            comp.download_stock_asset('https://videos.pexels.com/video-files/101/hd.mp4', 'pexels', 'video', dest, opener=opener)
            self.assertTrue(dest.is_file())
            self.assertEqual(dest.read_bytes(), valid_mp4)

            # Reject oversized download exceeding max_bytes
            with self.assertRaisesRegex(ValueError, 'maximum allowed download size'):
                comp.download_stock_asset('https://videos.pexels.com/video-files/101/hd.mp4', 'pexels', 'video',
                                          dest, opener=_FakeOpener(_FakeResponse(valid_mp4)), max_bytes=64)

            # Reject non-video payload disguised as MP4
            bad_payload = b'<html>not a video container at all</html>' + (b' ' * 80)
            with self.assertRaisesRegex(ValueError, 'not a supported video container'):
                comp.download_stock_asset('https://videos.pexels.com/video-files/101/hd.mp4', 'pexels', 'video',
                                          dest, opener=_FakeOpener(_FakeResponse(bad_payload)))

            # Cancellation cleans up partial file
            part = dest.with_suffix('.mp4.part')
            def cancel_now():
                raise RuntimeError('Cancelled')
            with self.assertRaisesRegex(RuntimeError, 'Cancelled'):
                comp.download_stock_asset('https://videos.pexels.com/video-files/101/hd.mp4', 'pexels', 'video',
                                          dest, check_cancel=cancel_now, opener=_FakeOpener(_FakeResponse(valid_mp4)))
            self.assertFalse(part.exists())

    def test_phase5_multitrack_overlays_keyframes_ducking_and_speed_rescaling(self):
        cues = [dict(start=1.0, end=2.0, text='Fast line', words=[dict(text='Fast', start=1.0, end=1.4), dict(text='line', start=1.4, end=2.0)])]
        rescaled = comp.shift_cues(cues, delta=0.0, duration=4.0, speed=2.0)
        self.assertAlmostEqual(rescaled[0]['start'], 0.5)
        self.assertAlmostEqual(rescaled[0]['end'], 1.0)
        self.assertAlmostEqual(rescaled[0]['words'][1]['end'], 1.0)
        self.assertEqual(rescaled[0]['karaoke']['state'], 'review')

        settings = comp.validate({
            **comp.DEFAULTS,
            'end': 4.0,
            'brightness': 0.1,
            'contrast': 1.2,
            'saturation': 1.3,
            'background_speed': 1.25,
            'transition_in': 0.5,
            'transition_out': 0.5,
            'keyframe_end_x': 80,
            'keyframe_end_y': 30,
            'title_text': 'Φταίω Εγώ · Official Video',
            'title_duration': 2.5,
            'broll_start': 0.5,
            'broll_duration': 2.0,
            'broll_scale': 50,
            'broll_opacity': 0.85,
            'broll_fade': 0.3,
            'background_volume': 0.6,
            'ducking': True,
        }, 4.0)
        assets = {
            'audio': dict(file='song.wav', kind='audio', duration=4.0),
            'background': dict(file='bg.mp4', kind='video'),
            'broll': dict(file='overlay.png', kind='image')
        }
        studio = comp.schema(assets, settings, {'font': 'Montserrat'})
        self.assertEqual(len(studio['tracks']), 4)
        self.assertEqual(studio['tracks'][3]['kind'], 'overlays')
        self.assertEqual(len(studio['tracks'][3]['clips']), 2)
        args = comp.render_args(studio, Path.cwd(), 'out.mp4', background_has_audio=True)
        joined = ' '.join(args)
        self.assertIn('eq=brightness=0.1:contrast=1.2:saturation=1.3', joined)
        self.assertIn('fade=t=in:st=0:d=0.5', joined)
        self.assertIn('overlay=x=', joined)
        self.assertIn('between(t,0.0,4.0)', joined)

    def test_video_and_audio_fx_chains_and_validation(self):
        for name, expr in comp.VIDEO_FILTERS.items():
            if name != 'none':
                self.assertIn(expr, comp.video_fx_chain({'video_filter': name}))
        for name, expr in comp.AUDIO_EFFECTS.items():
            if name != 'none':
                self.assertIn(expr, comp.audio_fx_chain({'audio_effect': name}))
        v_chain = comp.video_fx_chain({
            'video_filter': 'sepia',
            'sharpen': 1.2,
            'chromatic': 4,
            'film_grain': 10,
            'vignette': True,
        })
        self.assertEqual(len(v_chain), 5)
        self.assertIn('rgbashift=rh=-4:bh=4', v_chain)
        self.assertIn('noise=alls=10:allf=t+u', v_chain)

        a_iso = comp.audio_fx_chain({'voice_isolation': True, 'noise_cancel': True, 'audio_effect': 'echo'})
        self.assertEqual(len(a_iso), 2)
        self.assertIn('highpass=f=100', a_iso[0])
        self.assertIn('aecho=', a_iso[1])

        a_denoise = comp.audio_fx_chain({'voice_isolation': False, 'noise_cancel': True, 'audio_effect': 'none'})
        self.assertEqual(a_denoise, ['afftdn=nf=-25'])

        with self.assertRaisesRegex(ValueError, 'video filter and audio effect'):
            comp.validate({**comp.DEFAULTS, 'end': 3.0, 'video_filter': 'unknown'}, 3.0)
        with self.assertRaisesRegex(ValueError, 'video filter and audio effect'):
            comp.validate({**comp.DEFAULTS, 'end': 3.0, 'audio_effect': 'autotune99'}, 3.0)

    def test_multi_clip_sequence_scheduling_and_render_args(self):
        assets = {
            'audio': dict(file='song.wav', kind='audio', duration=12.0),
            'background': dict(file='clip1.mp4', kind='video', name='Clip 1'),
            'clip_a1b2c3d4': dict(file='clip2.png', kind='image', name='Clip 2'),
            'clip_e5f60718': dict(file='clip3.mp4', kind='video', name='Clip 3'),
        }
        seq = [
            dict(asset='background', name='Clip 1', duration=0),
            dict(asset='clip_a1b2c3d4', name='Clip 2', duration=0),
            dict(asset='clip_e5f60718', name='Clip 3', duration=0),
        ]
        settings = comp.validate({**comp.DEFAULTS, 'end': 12.0, 'sequence': seq}, 12.0)
        studio = comp.schema(assets, settings, {'font': 'Montserrat'})
        clips = studio['tracks'][0]['clips']
        self.assertEqual(len(clips), 3)
        self.assertAlmostEqual(clips[0]['start'], 0.0)
        self.assertAlmostEqual(clips[0]['duration'], 4.0)
        self.assertAlmostEqual(clips[1]['start'], 4.0)
        self.assertAlmostEqual(clips[1]['duration'], 4.0)
        self.assertAlmostEqual(clips[2]['start'], 8.0)
        self.assertAlmostEqual(clips[2]['duration'], 4.0)

        args = comp.render_args(studio, Path.cwd(), 'multi_out.mp4')
        joined = ' '.join(args)
        self.assertIn('concat=n=3:v=1:a=0', joined)
        self.assertIn('[vseg0][vseg1][vseg2]', joined)

        cycle_seq = [
            dict(asset='background', name='Clip 1', duration=3.0),
            dict(asset='clip_a1b2c3d4', name='Clip 2', duration=3.0),
        ]
        sched = comp.schedule_sequence(cycle_seq, assets, 12.0, loop=True)
        self.assertEqual(len(sched), 4)
        self.assertEqual([s['asset'] for s in sched], ['background', 'clip_a1b2c3d4', 'background', 'clip_a1b2c3d4'])

    def test_pixabay_portrait_dance_search_sorts_vertical_first_and_keeps_hd_clips(self):
        pixabay_payload = {
            'hits': [
                {
                    'id': 501,
                    'duration': 12,
                    'tags': 'street dance, hip hop',
                    'user': 'DancerA',
                    'pageURL': 'https://pixabay.com/videos/id-501/',
                    'videos': {
                        'large': {
                            'url': 'https://cdn.pixabay.com/vimeo/501/dance_1920.mp4',
                            'width': 1920,
                            'height': 1080,
                            'thumbnail': 'https://cdn.pixabay.com/vimeo/501/thumb.jpg'
                        }
                    }
                },
                {
                    'id': 502,
                    'duration': 10,
                    'tags': 'vertical dance, tiktok vibe',
                    'user': 'DancerB',
                    'pageURL': 'https://pixabay.com/videos/id-502/',
                    'videos': {
                        'large': {
                            'url': 'https://cdn.pixabay.com/vimeo/502/dance_vertical.mp4',
                            'width': 1080,
                            'height': 1920,
                            'thumbnail': 'https://cdn.pixabay.com/vimeo/502/thumb.jpg'
                        }
                    }
                }
            ]
        }
        opener = _FakeOpener(_FakeResponse(json.dumps(pixabay_payload).encode('utf-8')))
        results = comp.search_stock('pixabay', 'dance', kind='video', orientation='portrait',
                                    max_duration=60, api_key='pix-key', opener=opener)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['id'], '502')
        self.assertEqual(results[1]['id'], '501')



