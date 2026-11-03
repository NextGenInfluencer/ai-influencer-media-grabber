"""Unit tests for Instagram carousel and photo download support."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import yt_dlp

from download_support import (
    InstagramMediaIE,
    extract_instagram_preview,
    instagram_download,
    gallery_download,
)


def fake_process_ie_result(ydl, entry, download=True):
    """Stand-in for yt-dlp's download step: writes the merged file where outtmpl points."""
    template = ydl.params['outtmpl']
    template = template.get('default') if isinstance(template, dict) else template
    target = template.replace('%(ext)s', 'mp4')
    Path(target).write_bytes(b'merged-video-with-audio')
    return {**entry, 'requested_downloads': [{'filepath': target}]}


class TestInstagramCarousel(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_ig_out_'))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_instagram_media_ie_does_not_raise_on_no_formats(self):
        ie = InstagramMediaIE(MagicMock())
        # raise_no_formats should pass silently without throwing
        try:
            ie.raise_no_formats("There is no video in this post")
        except Exception as e:
            self.fail(f"raise_no_formats raised unexpectedly: {e}")

    @patch("download_support.InstagramMediaIE._real_extract")
    def test_extract_instagram_preview(self, mock_extract):
        mock_extract.return_value = {
            "_type": "playlist",
            "title": "Post by test_creator",
            "uploader": "Test Creator",
            "entries": [
                {
                    "title": "Slide 1",
                    "thumbnails": [
                        {"url": "https://cdn.example.com/small.jpg", "width": 150},
                        {"url": "https://cdn.example.com/large.jpg", "width": 1080},
                    ],
                    "duration": 0,
                }
            ],
        }

        preview = extract_instagram_preview("https://www.instagram.com/p/test123/")
        self.assertIsNotNone(preview)
        self.assertEqual(preview["title"], "Post by test_creator")
        self.assertEqual(preview["uploader"], "Test Creator")
        self.assertEqual(preview["thumbnail"], "https://cdn.example.com/large.jpg")
        self.assertEqual(preview["duration"], 0)
        self.assertEqual(mock_extract.call_count, 1)

    @patch.object(yt_dlp.YoutubeDL, "process_ie_result", autospec=True, side_effect=fake_process_ie_result)
    @patch("download_support.requests.get")
    @patch("download_support.InstagramMediaIE._real_extract")
    def test_instagram_download_mixed_media(self, mock_extract, mock_get, mock_process):
        mock_extract.return_value = {
            "_type": "playlist",
            "title": "Post by photographer",
            "uploader": "Photographer",
            "entries": [
                {
                    "id": "item1",
                    "title": "Photo Slide",
                    "formats": [],
                    "thumbnails": [{"url": "https://cdn.example.com/photo.jpg"}],
                },
                {
                    "id": "item2",
                    "title": "Video Slide",
                    "formats": [
                        {
                            "url": "https://cdn.example.com/video.mp4",
                            "vcodec": "h264",
                            "acodec": "none",
                            "width": 1080,
                            "height": 1920,
                        }
                    ],
                    "thumbnails": [],
                },
            ],
        }

        # Mock requests.get streaming response
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"chunk1", b"chunk2"]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        reports = []
        result = instagram_download(
            "https://www.instagram.com/p/testmixed/",
            str(self.test_dir),
            "none",
            lambda r: reports.append(r),
        )

        self.assertEqual(result["_type"], "playlist")
        self.assertEqual(len(result["entries"]), 2)
        self.assertTrue(any("Downloading slide 1/2 (JPG)" in r.get("status", "") for r in reports))
        self.assertTrue(any("Downloading slide 2/2 (VIDEO)" in r.get("status", "") for r in reports))
        self.assertEqual(mock_extract.call_count, 1, "a post must be extracted exactly once")

        entry_paths = [e["filepath"] for e in result["entries"]]
        self.assertTrue(entry_paths[0].endswith(".jpg"))
        self.assertTrue(entry_paths[1].endswith(".mp4"))
        for p in entry_paths:
            self.assertTrue(os.path.exists(p))
        self.assertEqual(Path(entry_paths[0]).read_bytes(), b"chunk1chunk2")

    @patch("download_support.subprocess.Popen")
    def test_gallery_download_cleans_empty_folder_on_failure(self, mock_popen):
        # Mock gallery-dl failing
        mock_proc = MagicMock()
        mock_proc.stdout = ["error line"]
        mock_proc.wait.return_value = 1
        mock_popen.return_value.__enter__.return_value = mock_proc

        with self.assertRaises(RuntimeError):
            gallery_download(
                "https://other-site.com/gallery/123",
                str(self.test_dir),
                "none",
                lambda r: None,
            )

        # Ensure no empty Gallery-* folders were left behind
        leftovers = list(self.test_dir.glob("Gallery-*"))
        self.assertEqual(leftovers, [])

    @patch("download_support.InstagramMediaIE._real_extract")
    def test_api_preview_for_instagram_post_uses_native_extractor(self, mock_extract):
        mock_extract.return_value = {
            "_type": "playlist",
            "title": "Post by test_creator",
            "uploader": "Test Creator",
            "entries": [
                {
                    "title": "Slide 1",
                    "thumbnails": [{"url": "https://cdn.example.com/preview.jpg"}],
                }
            ],
        }

        import app_local
        client = app_local.app.test_client()
        client.get("/")
        with client.session_transaction() as session:
            headers = {"X-Media-Token": session.get("api_token", "")}

        res = client.post("/api/preview", json={"url": "https://www.instagram.com/p/carousel123/"}, headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json["title"], "Post by test_creator")
        self.assertEqual(res.json["uploader"], "Test Creator")
        self.assertEqual(res.json["thumbnail"], "https://cdn.example.com/preview.jpg")
        self.assertEqual(mock_extract.call_count, 1)

    @patch("download_support._run_gallery_dl")
    @patch("download_support.instagram_download")
    def test_instagram_profile_download_modes(self, mock_dl, mock_run):
        from download_support import instagram_profile_download

        target = self.test_dir / "creator_jane"
        commands = []

        def run(command, report):
            commands.append(command)
            target.mkdir(parents=True, exist_ok=True)
            (target / f"new_{len(commands)}.jpg").write_bytes(b"img")
            return 0, ["saved"], 0

        mock_run.side_effect = run
        mock_dl.side_effect = lambda post_url, *args, **kwargs: {
            "_type": "playlist",
            "entries": [{"filepath": f"/mock/{post_url.strip('/').split('/')[-1]}.jpg", "title": "post"}]
        }

        # 1. Mode: 'photos' -> one gallery-dl run filtered to image extensions
        res = instagram_profile_download("https://www.instagram.com/creator_jane/", str(self.test_dir),
                                         browser="none", report=lambda r: None, mode="photos")
        self.assertEqual(len(res["entries"]), 1)
        self.assertIn("--filter", commands[-1])
        self.assertIn("jpg", commands[-1][commands[-1].index("--filter") + 1])
        self.assertEqual(commands[-1][-1], "https://www.instagram.com/creator_jane/posts/")

        # 2. Mode: 'videos' -> filter on video extensions; only the file created by this run counts
        res_vids = instagram_profile_download("https://www.instagram.com/creator_jane/", str(self.test_dir),
                                              browser="none", report=lambda r: None, mode="videos")
        self.assertEqual(len(res_vids["entries"]), 1)
        self.assertIn("mp4", commands[-1][commands[-1].index("--filter") + 1])
        mock_dl.assert_not_called()

        # 3. Mode: 'selected' -> only the specified URLs, one native download each
        res_sel = instagram_profile_download("https://www.instagram.com/creator_jane/", str(self.test_dir),
                                             browser="none", report=lambda r: None, mode="selected",
                                             selected_urls=["https://www.instagram.com/reel/reel2/"])
        self.assertEqual(len(res_sel["entries"]), 1)
        self.assertEqual(mock_dl.call_count, 1)


if __name__ == "__main__":
    unittest.main()
