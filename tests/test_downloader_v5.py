"""v5 downloader regressions: Instagram, cookies, history, gallery and the download pipeline (no network)."""
import tests._isolation  # Must precede application imports.
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import download_support as ds

ROOT = Path(__file__).resolve().parents[1]
VALID_COOKIES = (
    "# Netscape HTTP Cookie File\n"
    ".instagram.com\tTRUE\t/\tTRUE\t1893456000\tsessionid\tSECRET-SESSION-VALUE\n"
    "#HttpOnly_.instagram.com\tTRUE\t/\tTRUE\t1893456000\tcsrftoken\tSECRET-CSRF\n"
    ".youtube.com\tTRUE\t/\tFALSE\t0\tPREF\tf1=1\n"
)


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='v5-dl-'))
        self.env = patch.dict(os.environ, MEDIA_GRABBER_DATA_DIR=str(self.tmp / 'data'))
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class UrlClassificationTests(unittest.TestCase):
    def test_profile_vs_post_detection(self):
        profiles = ['https://www.instagram.com/creator/', 'https://instagram.com/creator/?hl=en', '@creator',
                    'https://www.instagram.com/creator/reels/', 'https://www.instagram.com/creator/tagged/']
        posts = ['https://www.instagram.com/p/ABC123/', 'https://www.instagram.com/reel/ABC123/',
                 'https://www.instagram.com/creator/p/ABC123/', 'https://www.instagram.com/creator/reel/ABC123/',
                 'https://www.instagram.com/creator/reels/ABC123/', 'https://www.instagram.com/creator/tv/ABC123/',
                 'https://www.instagram.com/stories/creator/1/', 'https://notinstagram.com/creator/']
        for url in profiles:
            self.assertTrue(ds.is_instagram_profile_url(url), url)
        for url in posts:
            self.assertFalse(ds.is_instagram_profile_url(url), url)

    def test_platform_detection_uses_hostname(self):
        self.assertEqual(ds.platform_folder('https://x.com/user/status/1'), 'Twitter')
        self.assertEqual(ds.platform_folder('https://mobile.twitter.com/u/status/1'), 'Twitter')
        self.assertEqual(ds.platform_folder('https://m.youtube.com/watch?v=abc'), 'YouTube')
        self.assertEqual(ds.platform_folder('https://youtu.be/abc'), 'YouTube')
        self.assertEqual(ds.platform_folder('https://www.netflix.com/title/x.com'), 'Other')
        self.assertEqual(ds.platform_folder('https://box.com/instagram.com/p/1'), 'Other')
        self.assertEqual(ds.platform_folder('https://notyoutube.com/watch?v=1'), 'Other')
        self.assertEqual(ds.platform_folder('https://www.tiktok.com/@a/video/1'), 'TikTok')

    def test_noplaylist_only_off_for_playlist_pages(self):
        self.assertTrue(ds.wants_playlist('https://www.youtube.com/playlist?list=PL123'))
        self.assertFalse(ds.wants_playlist('https://www.youtube.com/watch?v=abc&list=PL123'))
        self.assertFalse(ds.wants_playlist('https://youtu.be/abc?list=PL123'))
        self.assertFalse(ds.wants_playlist('https://www.youtube.com/watch?v=abc'))
        self.assertFalse(ds.wants_playlist('https://www.tiktok.com/@a/video/1'))

    def test_login_errors_are_recognised(self):
        self.assertTrue(ds.is_login_error('ERROR: [Instagram] x: Requested content is not available, rate-limit reached or login required. Use --cookies'))
        self.assertTrue(ds.is_login_error("[instagram][error] AbortExtraction: HTTP redirect to login page (https://www.instagram.com/accounts/login/)"))
        self.assertFalse(ds.is_login_error('HTTP Error 404: Not Found'))
        self.assertEqual(ds.friendly_download_error('ERROR: Could not copy Chrome cookie database'), ds.CHROMIUM_WINDOWS_NOTE)


class GalleryDlListingTests(TempDirTestCase):
    SAMPLE = json.dumps([
        [2, {'post_shortcode': 'AAA', 'post_url': 'https://www.instagram.com/p/AAA/', 'type': 'post', 'count': 2,
             'description': 'Sunset\nsecond line', 'user': {'profile_pic_url': 'https://cdn/avatar.jpg'}}],
        [3, 'https://cdn/a1.jpg', {'post_shortcode': 'AAA', 'display_url': 'https://cdn/a1.jpg', 'video_url': None, 'extension': 'jpg'}],
        [3, 'https://cdn/a2.mp4', {'post_shortcode': 'AAA', 'display_url': 'https://cdn/a2.jpg', 'video_url': 'https://cdn/a2.mp4', 'extension': 'mp4'}],
        [2, {'post_shortcode': 'BBB', 'post_url': 'https://www.instagram.com/reel/BBB/', 'type': 'reel', 'count': 1}],
        [3, 'https://cdn/b.mp4', {'post_shortcode': 'BBB', 'display_url': 'https://cdn/b.jpg', 'video_url': 'https://cdn/b.mp4', 'extension': 'mp4'}],
        [2, {'post_shortcode': 'CCC', 'type': 'post', 'count': 1}],
        [3, 'https://cdn/c.jpg', {'post_shortcode': 'CCC', 'display_url': 'https://cdn/c.jpg', 'extension': 'jpg'}],
    ])

    def test_listing_is_parsed_into_posts(self):
        posts, avatar, errors = ds.parse_gallery_dl_listing(self.SAMPLE, 'creator')
        self.assertEqual(errors, [])
        self.assertEqual(avatar, 'https://cdn/avatar.jpg')
        self.assertEqual([p['id'] for p in posts], ['AAA', 'BBB', 'CCC'])
        self.assertEqual(posts[0]['title'], 'Sunset')
        self.assertEqual(posts[0]['type'], 'video')  # carousel containing a video
        self.assertEqual(posts[0]['thumbnail'], 'https://cdn/a1.jpg')
        self.assertEqual(posts[1]['url'], 'https://www.instagram.com/reel/BBB/')
        self.assertEqual(posts[2]['type'], 'photo')
        self.assertEqual(posts[2]['title'], 'Post by @creator')

    def test_profile_listing_command_and_cookies(self):
        stored = ds.stored_cookie_path()
        stored.parent.mkdir(parents=True)
        stored.write_text(VALID_COOKIES, encoding='utf-8')
        completed = SimpleNamespace(returncode=0, stdout=self.SAMPLE, stderr='')
        with patch('download_support.subprocess.run', return_value=completed) as run:
            profile = ds.extract_instagram_profile('https://www.instagram.com/creator/', browser='cookies.txt')
        command = run.call_args.args[0]
        self.assertIn('--dump-json', command)
        self.assertEqual(command[command.index('--post-range') + 1], ds.PROFILE_LISTING_RANGE)
        self.assertEqual(command[command.index('--cookies') + 1], str(stored))
        self.assertTrue(os.path.isabs(command[command.index('--cookies') + 1]))
        self.assertEqual(command[-1], 'https://www.instagram.com/creator/posts/')
        self.assertEqual(profile['post_count'], 3)

    def test_login_wall_is_an_honest_error(self):
        output = json.dumps([[-1, {'error': 'AbortExtraction', 'message': 'HTTP redirect to login page (https://www.instagram.com/accounts/login/)'}]])
        completed = SimpleNamespace(returncode=0, stdout=output, stderr='')
        with patch('download_support.subprocess.run', return_value=completed):
            with self.assertRaises(ds.LoginRequiredError) as caught:
                ds.extract_instagram_profile('https://www.instagram.com/creator/', browser='none')
        self.assertIn('requires login', str(caught.exception))


class ProfileDownloadTests(TempDirTestCase):
    def test_empty_profile_download_is_an_error_not_success(self):
        with patch('download_support._run_gallery_dl', return_value=(0, ['nothing'], 0)):
            with self.assertRaises(RuntimeError) as caught:
                ds.instagram_profile_download('https://www.instagram.com/creator/', str(self.tmp), 'firefox', lambda r: None)
        self.assertIn('No media were saved', str(caught.exception))

    def test_anonymous_failure_is_login_error(self):
        with patch('download_support._run_gallery_dl', return_value=(4, ['[instagram][error] HttpError'], 0)):
            with self.assertRaises(ds.LoginRequiredError):
                ds.instagram_profile_download('https://www.instagram.com/creator/', str(self.tmp), 'none', lambda r: None)

    def test_already_downloaded_profile_is_explained(self):
        with patch('download_support._run_gallery_dl', return_value=(0, ['# old.jpg', '# old2.jpg'], 2)):
            with self.assertRaises(RuntimeError) as caught:
                ds.instagram_profile_download('https://www.instagram.com/creator/', str(self.tmp), 'firefox', lambda r: None)
        self.assertIn('already in your library', str(caught.exception))

    def test_only_new_files_are_counted(self):
        target = self.tmp / 'creator'
        target.mkdir()
        (target / 'old.jpg').write_bytes(b'old')

        def run(command, report):
            (target / 'new.mp4').write_bytes(b'new')
            return 0, ['saved'], 1

        with patch('download_support._run_gallery_dl', side_effect=run):
            result = ds.instagram_profile_download('https://www.instagram.com/creator/', str(self.tmp), 'firefox', lambda r: None)
        self.assertEqual([Path(e['filepath']).name for e in result['entries']], ['new.mp4'])
        self.assertEqual(result['entries'][0]['uploader'], 'creator')

    def test_gallery_dl_uses_absolute_stored_cookie_path(self):
        stored = ds.stored_cookie_path()
        stored.parent.mkdir(parents=True)
        stored.write_text(VALID_COOKIES, encoding='utf-8')
        process = MagicMock()
        process.stdout = []
        process.wait.return_value = 1
        with patch('download_support.subprocess.Popen') as popen:
            popen.return_value.__enter__.return_value = process
            with self.assertRaises(RuntimeError):
                ds.gallery_download('https://example.org/gallery/1', str(self.tmp), 'cookies.txt', lambda r: None)
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index('--cookies') + 1], str(stored))

    def test_selected_posts_fail_fast_on_login_wall(self):
        with patch('download_support.instagram_download', side_effect=ds.LoginRequiredError()) as download:
            with self.assertRaises(ds.LoginRequiredError):
                ds.instagram_profile_download('https://www.instagram.com/creator/', str(self.tmp), 'none', lambda r: None,
                                              selected_urls=['https://www.instagram.com/p/A/', 'https://www.instagram.com/p/B/'])
        self.assertEqual(download.call_count, 1)

    def test_post_login_wall_does_not_cascade_to_gallery_dl(self):
        with patch('download_support.instagram_download', side_effect=ds.LoginRequiredError()), \
                patch('download_support._run_gallery_dl') as gallery:
            with self.assertRaises(ds.LoginRequiredError):
                ds.gallery_download('https://www.instagram.com/p/ABC/', str(self.tmp), 'none', lambda r: None)
        gallery.assert_not_called()


class InstagramMediaTests(TempDirTestCase):
    def test_video_slide_uses_audio_bearing_format_via_merge(self):
        captured = {}

        class FakeYDL:
            def __init__(self, params):
                captured.update(params)
                self.params = params
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def process_ie_result(self, entry, download=True):
                captured['entry'] = entry
                path = self.params['outtmpl'].replace('%(ext)s', 'mp4')
                Path(path).write_bytes(b'av')
                return {'requested_downloads': [{'filepath': path}]}

        entry = {'id': 'v1', 'formats': [{'url': 'https://cdn/v.mp4', 'vcodec': 'avc1', 'acodec': 'none'},
                                         {'url': 'https://cdn/a.m4a', 'vcodec': 'none', 'acodec': 'mp4a'}]}
        with patch('download_support.yt_dlp.YoutubeDL', FakeYDL):
            result = ds._download_video_entry(entry, 'https://www.instagram.com/reel/v1/', 'none', self.tmp / 'clip', None)
        self.assertEqual(captured['format'], 'bv*+ba/b')
        self.assertEqual(captured['merge_output_format'], 'mp4')
        self.assertEqual(captured['entry']['webpage_url'], 'https://www.instagram.com/reel/v1/')
        self.assertEqual(result, self.tmp / 'clip.mp4')

    def test_photos_are_stored_byte_exact(self):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('RGB', (1081, 1349), (200, 30, 90)).save(buffer, 'JPEG', quality=77)
        original = buffer.getvalue()
        info = {'_type': 'playlist', 'uploader': 'Shooter', 'entries': [
            {'id': 'p1', 'title': 'Photo', 'formats': [], 'thumbnails': [{'url': 'https://cdn/p1.jpg'}]}]}
        response = MagicMock()
        response.iter_content.return_value = [original[:1000], original[1000:]]
        with patch('download_support._instagram_extract', return_value=info), \
                patch('download_support.requests.get', return_value=response):
            result = ds.instagram_download('https://www.instagram.com/p/p1/', str(self.tmp), 'none', lambda r: None)
        saved = Path(result['entries'][0]['filepath'])
        self.assertEqual(saved.read_bytes(), original)
        with Image.open(saved) as image:
            self.assertEqual(image.size, (1081, 1349))

    def test_normalized_copy_is_derived_and_leaves_original(self):
        from PIL import Image
        source = self.tmp / 'photo.png'
        Image.new('RGB', (1081, 1349), (1, 2, 3)).save(source)
        before = source.read_bytes()
        copy = ds.normalized_copy(source, dest_dir=self.tmp / 'derived')
        self.assertNotEqual(copy, source)
        self.assertEqual(copy.parent, self.tmp / 'derived')
        self.assertIn('_normalized', copy.name)
        with Image.open(copy) as image:
            self.assertEqual(image.size, (1080, 1344))
        self.assertEqual(source.read_bytes(), before)
        aligned = self.tmp / 'aligned.png'
        Image.new('RGB', (64, 64)).save(aligned)
        self.assertEqual(ds.normalized_copy(aligned), aligned)


class CookieTests(TempDirTestCase):
    def test_options_per_platform(self):
        windows = ds.browser_options('win32')
        self.assertEqual([o['value'] for o in windows['options']], ['none', 'firefox', 'cookies.txt'])
        self.assertIn('App-Bound Encryption', windows['note'])
        self.assertIn("Get cookies.txt LOCALLY", windows['note'])
        mac = [o['value'] for o in ds.browser_options('darwin')['options']]
        self.assertTrue({'chrome', 'edge', 'safari', 'firefox', 'cookies.txt'} <= set(mac))
        linux = [o['value'] for o in ds.browser_options('linux')['options']]
        self.assertTrue({'chrome', 'edge', 'firefox'} <= set(linux))
        self.assertNotIn('safari', linux)
        with patch('download_support.sys.platform', 'darwin'):
            self.assertEqual(ds.browser_options()['platform'], 'darwin')

    def test_cookie_options_translation(self):
        self.assertEqual(ds.cookie_options('none'), ({}, []))
        self.assertEqual(ds.cookie_options('firefox', platform='win32'),
                         ({'cookiesfrombrowser': ('firefox', None, None, None)}, ['--cookies-from-browser', 'firefox']))
        with self.assertRaises(ds.CookieError) as caught:
            ds.cookie_options('chrome', platform='win32')
        self.assertIn('App-Bound', str(caught.exception))
        self.assertEqual(ds.cookie_options('chrome', platform='darwin')[1], ['--cookies-from-browser', 'chrome'])
        with self.assertRaises(ds.CookieError):
            ds.cookie_options('cookies.txt')
        ds.import_cookie_bytes(VALID_COOKIES.encode())
        patch_opts, args = ds.cookie_options('cookies.txt')
        stored = str(ds.stored_cookie_path())
        self.assertEqual(patch_opts, {'cookiefile': stored})
        self.assertEqual(args, ['--cookies', stored])
        self.assertTrue(os.path.isabs(stored))
        self.assertTrue(stored.startswith(str(self.tmp / 'data')))

    def test_validation(self):
        summary = ds.parse_cookie_text(VALID_COOKIES)
        self.assertEqual(summary['cookies'], 3)
        self.assertEqual(summary['domains'], ['instagram.com', 'youtube.com'])
        headerless = VALID_COOKIES.split('\n', 1)[1]
        self.assertTrue(ds.parse_cookie_text(headerless)['cookies'])
        for bad in ('', 'hello world', '{"cookies": []}', 'a\tb\tc'):
            with self.assertRaises(ds.CookieError):
                ds.parse_cookie_text(bad)
        with self.assertRaises(ds.CookieError):
            ds.import_cookie_bytes(b'#' * (ds.MAX_COOKIE_FILE_BYTES + 1))
        status = ds.import_cookie_bytes(headerless.encode())
        self.assertTrue(ds.stored_cookie_path().read_text().startswith(ds.NETSCAPE_HEADER))
        self.assertEqual(status['domains'], 2)
        self.assertTrue(status['has_instagram'])

    def test_legacy_migration_copies_without_deleting(self):
        legacy_dir = self.tmp / 'app'
        legacy_dir.mkdir()
        (legacy_dir / 'cookies.txt').write_text(VALID_COOKIES, encoding='utf-8')
        with patch('download_support.APP_DIR', legacy_dir):
            self.assertTrue(ds.migrate_legacy_cookies())
            self.assertFalse(ds.migrate_legacy_cookies())
        self.assertTrue((legacy_dir / 'cookies.txt').exists())
        self.assertEqual(ds.stored_cookie_path().read_text(encoding='utf-8'), VALID_COOKIES)


class AppRouteTests(TempDirTestCase):
    @classmethod
    def setUpClass(cls):
        import app_local
        cls.app_module = app_local
        cls.client = app_local.app.test_client()
        cls.client.get('/')
        with cls.client.session_transaction() as session:
            cls.headers = {'X-Media-Token': session['api_token']}

    def events(self, response):
        return [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines() if line.startswith('data: ')]

    def test_cookie_endpoints(self):
        client, headers = self.client, self.headers
        self.assertFalse(client.get('/api/cookies/status').json['exists'])
        with patch('download_support.sys.platform', 'win32'):
            options = client.get('/api/cookies/options').json
        self.assertEqual([o['value'] for o in options['options']], ['none', 'firefox', 'cookies.txt'])

        bad = client.post('/api/cookies/import', headers=headers, data={'file': (io.BytesIO(b'not cookies'), 'c.txt')},
                          content_type='multipart/form-data')
        self.assertEqual(bad.status_code, 400)
        too_big = client.post('/api/cookies/import', headers=headers,
                              data={'file': (io.BytesIO(b'#' * (2 * 1024 * 1024 + 10)), 'c.txt')},
                              content_type='multipart/form-data')
        self.assertEqual(too_big.status_code, 400)

        ok = client.post('/api/cookies/import', headers=headers, data={'file': (io.BytesIO(VALID_COOKIES.encode()), 'cookies.txt')},
                         content_type='multipart/form-data')
        self.assertEqual(ok.status_code, 200, ok.json)
        self.assertNotIn('SECRET', ok.get_data(as_text=True))
        status = client.get('/api/cookies/status')
        self.assertEqual(status.json['domains'], 2)
        self.assertEqual(status.json['age_days'], 0)
        self.assertNotIn('SECRET', status.get_data(as_text=True))
        self.assertTrue(client.delete('/api/cookies', headers=headers).json['deleted'])
        self.assertFalse(client.get('/api/cookies/status').json['exists'])

    def test_preview_passes_cookie_choice(self):
        captured = {}

        class FakeYDL:
            def __init__(self, params):
                captured.update(params)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def extract_info(self, url, download=False):
                return {'title': 'Clip', 'uploader': 'Me'}

        with patch('download_support.sys.platform', 'win32'), patch.object(self.app_module.yt_dlp, 'YoutubeDL', FakeYDL):
            res = self.client.post('/api/preview', headers=self.headers,
                                   json={'url': 'https://www.youtube.com/watch?v=abc&list=PL1', 'browser': 'firefox'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(captured['cookiesfrombrowser'][0], 'firefox')
        self.assertTrue(captured['noplaylist'])
        with patch.object(self.app_module, 'extract_instagram_preview', return_value={'is_profile': True, 'posts': []}) as ig:
            self.client.post('/api/preview', headers=self.headers, json={'url': 'https://www.instagram.com/creator/', 'browser': 'firefox'})
        self.assertEqual(ig.call_args.kwargs['browser'], 'firefox')
        with patch('download_support.sys.platform', 'win32'):
            res = self.client.post('/api/preview', headers=self.headers, json={'url': 'https://youtu.be/x', 'browser': 'chrome'})
        self.assertEqual(res.status_code, 400)
        self.assertIn('App-Bound', res.json['error'])
        self.assertEqual(self.client.post('/api/preview', headers=self.headers, data='not json').status_code, 400)

    def fake_downloader(self, info, on_process=None):
        class FakeYDL:
            def __init__(self, params):
                self.params = params
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def extract_info(self, url, download=False):
                return info
            def process_ie_result(self, result, download=True):
                if on_process:
                    on_process(self.params)
                return result
            def prepare_filename(self, result):
                return str(Path(self.params['outtmpl']).with_name('fallback.mp4'))
        return FakeYDL

    def test_first_frame_failure_is_a_warning_and_hook_error_keeps_stream(self):
        broken = self.tmp / 'broken.mp4'
        broken.write_bytes(b'this is not a video')
        info = {'_type': 'video', 'id': 'x', 'title': 'Broken', 'filepath': str(broken)}

        def fire_error_hook(params):
            for hook in params['progress_hooks']:
                hook({'status': 'error'})

        fake = self.fake_downloader(info, fire_error_hook)
        with patch.object(self.app_module.yt_dlp, 'YoutubeDL', fake):
            response = self.client.post('/api/download', headers=self.headers, json={
                'url': 'https://www.youtube.com/watch?v=x', 'path': str(self.tmp / 'lib'),
                'processing_options': {'extractFrame': True, 'identifySong': False}}, buffered=True)
        events = self.events(response)
        self.assertTrue(events[-1].get('done'), events)
        self.assertNotIn('error', events[-1], events)
        self.assertFalse(any('error' in e for e in events[:-1]), events)
        self.assertTrue(any('Warning: could not extract the first frame' in e.get('status', '') for e in events), events)

    def test_download_without_task_id_and_bad_json(self):
        self.assertEqual(self.client.post('/api/download', headers=self.headers, data='nope').status_code, 400)
        media = self.tmp / 'clip.mp3'
        media.write_bytes(b'ID3')
        fake = self.fake_downloader({'_type': 'video', 'id': 'a', 'title': 'Song', 'filepath': str(media)})
        with patch.object(self.app_module.yt_dlp, 'YoutubeDL', fake), \
                patch.object(self.app_module, 'add_history_entry'):
            response = self.client.post('/api/download', headers=self.headers, json={
                'url': 'https://example.com/song', 'path': str(self.tmp / 'lib'),
                'processing_options': {'identifySong': False}}, buffered=True)
        self.assertTrue(self.events(response)[-1].get('done'))
        self.assertNotIn('unknown', self.app_module.cancel_flags)

    def test_profile_download_with_no_files_reports_failure(self):
        with patch.object(self.app_module, 'gallery_download', side_effect=RuntimeError('No media were saved from @creator')):
            response = self.client.post('/api/download', headers=self.headers, json={
                'url': 'https://www.instagram.com/creator/', 'path': str(self.tmp / 'lib'), 'task_id': 'ig-empty'}, buffered=True)
        final = self.events(response)[-1]
        self.assertIn('error', final)
        self.assertIn('No media were saved', final['error'])

    def test_login_wall_sets_flag(self):
        with patch.object(self.app_module, 'gallery_download', side_effect=ds.LoginRequiredError()):
            response = self.client.post('/api/download', headers=self.headers, json={
                'url': 'https://www.instagram.com/p/ABC/', 'path': str(self.tmp / 'lib'), 'task_id': 'ig-login'}, buffered=True)
        final = self.events(response)[-1]
        self.assertTrue(final['login_required'])
        self.assertIn('Instagram requires login', final['error'])

    def test_profile_entries_get_post_processing(self):
        photo = self.tmp / 'lib' / 'Instagram' / 'creator' / 'p1.jpg'
        photo.parent.mkdir(parents=True)
        photo.write_bytes(b'jpg')
        result = {'_type': 'playlist', 'entries': [{'filepath': str(photo), 'title': 'p1', 'extractor_key': 'Instagram'}]}
        with patch.object(self.app_module, 'gallery_download', return_value=result), \
                patch.object(self.app_module, 'add_history_entry') as history:
            response = self.client.post('/api/download', headers=self.headers, json={
                'url': 'https://www.instagram.com/creator/', 'path': str(self.tmp / 'lib'), 'task_id': 'ig-ok'}, buffered=True)
        final = self.events(response)[-1]
        self.assertTrue(final.get('done'))
        self.assertNotIn('error', final)
        self.assertEqual(final['file_path'], str(photo))
        history.assert_called_once()
        self.assertTrue(photo.with_suffix('.url').exists())

    def test_only_platform_folder_is_approved(self):
        module = self.app_module
        roots_file = self.tmp / 'media_roots.json'
        with patch.object(module, 'MEDIA_ROOTS_FILE', str(roots_file)), \
                patch.object(module, 'DEFAULT_SAVE_DIR', str(self.tmp / 'library')), \
                patch.object(module, '_approved_media_roots', set()) as roots:
            module.approve_media_root(str(self.tmp / 'Custom' / 'YouTube'))
            module.approve_media_root(os.path.abspath(os.sep))
            module.approve_media_root(os.path.join(module.DEFAULT_SAVE_DIR, 'YouTube'))
            self.assertEqual(roots, {os.path.realpath(self.tmp / 'Custom' / 'YouTube')})
            roots_file.write_text(json.dumps([os.path.abspath(os.sep), str(self.tmp / 'ok')]))
            self.assertEqual(module._load_approved_roots(), {str(self.tmp / 'ok')})

    def test_gallery_walk_has_depth_and_count_caps(self):
        module = self.app_module
        deep = self.tmp / 'walk'
        current = deep
        for level in range(7):
            (current / f'file{level}.jpg').parent.mkdir(parents=True, exist_ok=True)
            (current / f'file{level}.jpg').write_bytes(b'x')
            current = current / f'level{level + 1}'
        found = [name for _, name in module.iter_gallery_files(str(deep), [1000], max_depth=4)]
        self.assertEqual(sorted(found), [f'file{i}.jpg' for i in range(5)])
        self.assertEqual(len(list(module.iter_gallery_files(str(deep), [2]))), 2)

    def test_history_corruption_recovery(self):
        module = self.app_module
        history = self.tmp / 'history.json'
        with patch.object(module, 'HISTORY_FILE', str(history)):
            module.save_history([{'id': '1', 'timestamp': 1}])
            module.save_history([{'id': '1', 'timestamp': 1}, {'id': '2', 'timestamp': 2}])
            self.assertEqual(len(json.loads((self.tmp / 'history.json.bak').read_text())), 1)
            history.write_text('{ broken', encoding='utf-8')
            restored = module.load_history()
            self.assertEqual([row['id'] for row in restored], ['1'])
            self.assertEqual(len(list(self.tmp.glob('history.corrupt-*.json'))), 1)

            history.write_text('[1, 2', encoding='utf-8')
            (self.tmp / 'history.json.bak').write_text('also broken', encoding='utf-8')
            self.assertEqual(module.load_history(), [])
            self.assertEqual(len(list(self.tmp.glob('history.corrupt-*.json'))), 2)
            module.invalidate_gallery_cache()
            history.write_text('not json', encoding='utf-8')
            self.assertEqual(self.client.get('/api/gallery').status_code, 200)
            self.assertEqual(self.client.get('/api/history').status_code, 200)

    def test_gallery_index_attribution(self):
        module = self.app_module
        folder = self.tmp / 'Instagram' / 'creator'
        history = [
            {'file_path': str(folder / 'Video by creator_ABC.mp4'), 'url': 'https://www.instagram.com/p/ABC/', 'uploader': 'creator'},
            {'file_path': str(self.tmp / 'Gallery'), 'url': 'https://example.org/g', 'uploader': 'gal'},
        ]
        index = module.build_history_index(history)
        self.assertEqual(module.resolve_source_url(str(folder / 'Video by creator_ABC.mp4'), index),
                         ('https://www.instagram.com/p/ABC/', 'creator'))
        self.assertEqual(module.resolve_source_url(str(folder / 'Video by creator_ABC_first_frame.png'), index),
                         ('https://www.instagram.com/p/ABC/', 'creator'))
        self.assertEqual(module.resolve_source_url(str(self.tmp / 'Gallery' / 'sub' / 'x.jpg'), index),
                         ('https://example.org/g', 'gal'))
        # A short name must not be attributed by substring to an unrelated longer file.
        self.assertEqual(module.resolve_source_url(str(self.tmp / 'Other' / 'by.mp4'), index), (None, None))


class StaticChecks(unittest.TestCase):
    def test_srt_path_escaping_is_absolute_and_drive_safe(self):
        escaped = ds.ffmpeg_filter_path(r'D:\Media Grabber\clip\subs.srt' if os.name == 'nt' else '/media/clip/subs.srt')
        if os.name == 'nt':
            self.assertEqual(escaped, "'D\\:/Media Grabber/clip/subs.srt'")
        self.assertTrue(escaped.startswith("'") and escaped.endswith("'"))
        self.assertNotIn('\\\\', escaped)
        self.assertIn("'\\\\\\''", ds.ffmpeg_filter_path("it's.srt"))

    def test_burn_in_uses_absolute_filter_path(self):
        source = (ROOT / 'app_local.py').read_text(encoding='utf-8')
        self.assertNotIn('os.path.relpath(srt_path)', source)
        self.assertIn('subtitles={ffmpeg_filter_path(srt_path)}', source)
        self.assertNotIn("explorer /select,\"", source)

    def test_retry_uses_generate_uuid_with_fresh_task_id(self):
        html = (ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('uuidv4(', html)
        retry = html[html.index('function retryDownloadTask'):html.index('async function initHwaccelTelemetry')]
        self.assertIn('generateUUID()', retry)
        self.assertIn('task_id: newTaskId', retry)
        self.assertIn("browser: document.getElementById('browser').value", html[html.index("fetch('/api/preview'"):][:400])
        self.assertNotIn('<option value="chrome">', html)


class BurnInIntegration(unittest.TestCase):
    def test_ffmpeg_accepts_escaped_absolute_srt_path(self):
        import imageio_ffmpeg
        import subprocess
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        if ' subtitles ' not in subprocess.run([ffmpeg, '-hide_banner', '-filters'], capture_output=True, text=True).stdout:
            self.skipTest('ffmpeg build without libass')
        folder = Path(tempfile.mkdtemp(prefix="burn it's ["))
        try:
            srt = folder / 'subs, final.srt'
            srt.write_text('1\n00:00:00,000 --> 00:00:00,400\nHello\n\n', encoding='utf-8')
            out = folder / 'out.mp4'
            result = subprocess.run([ffmpeg, '-y', '-f', 'lavfi', '-i', 'color=black:size=64x64:rate=10', '-t', '0.5',
                                     '-vf', f'subtitles={ds.ffmpeg_filter_path(srt)}', str(out)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr[-800:])
            self.assertTrue(out.exists())
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
