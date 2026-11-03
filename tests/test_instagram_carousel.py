"""Unit tests for Instagram carousel and photo download support."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from download_support import (
    InstagramMediaIE,
    extract_instagram_preview,
    instagram_download,
    gallery_download,
)


class TestInstagramCarousel(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("test_ig_out")
        self.test_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.test_dir.exists():
            import shutil
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

    @patch("download_support.requests.get")
    @patch("download_support.InstagramMediaIE._real_extract")
    def test_instagram_download_mixed_media(self, mock_extract, mock_get):
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
        self.assertTrue(any("Downloading slide 2/2 (MP4)" in r.get("status", "") for r in reports))

        entry_paths = [e["filepath"] for e in result["entries"]]
        self.assertTrue(entry_paths[0].endswith(".jpg"))
        self.assertTrue(entry_paths[1].endswith(".mp4"))
        for p in entry_paths:
            self.assertTrue(os.path.exists(p))

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
    def test_api_preview_fallback_for_instagram(self, mock_extract):
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

        # Mock yt_dlp extract_info to simulate failure on carousel
        with patch("yt_dlp.YoutubeDL.extract_info", side_effect=Exception("No video formats found!")):
            res = client.post("/api/preview", json={"url": "https://www.instagram.com/p/carousel123/"}, headers=headers)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json["title"], "Post by test_creator")
            self.assertEqual(res.json["uploader"], "Test Creator")
            self.assertEqual(res.json["thumbnail"], "https://cdn.example.com/preview.jpg")

    @patch("download_support.instagram_download")
    @patch("download_support.extract_instagram_profile")
    def test_instagram_profile_download_modes(self, mock_extract, mock_dl):
        from download_support import instagram_profile_download

        mock_extract.return_value = {
            "is_profile": True,
            "username": "creator_jane",
            "posts": [
                {"url": "https://www.instagram.com/p/post1/", "type": "photo", "is_video": False, "shortcode": "post1"},
                {"url": "https://www.instagram.com/reel/reel2/", "type": "video", "is_video": True, "shortcode": "reel2"},
                {"url": "https://www.instagram.com/p/post3/", "type": "photo", "is_video": False, "shortcode": "post3"},
            ]
        }
        mock_dl.side_effect = lambda post_url, *args, **kwargs: {
            "_type": "playlist",
            "entries": [{"filepath": f"/mock/{post_url.strip('/').split('/')[-1]}.jpg", "title": "post"}]
        }

        # 1. Mode: 'photos' -> should only download post1 and post3 (2 items)
        reports = []
        res = instagram_profile_download(
            "https://www.instagram.com/creator_jane/",
            str(self.test_dir),
            browser="none",
            report=lambda r: reports.append(r),
            mode="photos"
        )
        self.assertEqual(len(res["entries"]), 2)
        self.assertEqual(mock_dl.call_count, 2)

        # 2. Mode: 'videos' -> should only download reel2 (1 item)
        mock_dl.reset_mock()
        res_vids = instagram_profile_download(
            "https://www.instagram.com/creator_jane/",
            str(self.test_dir),
            browser="none",
            report=lambda r: reports.append(r),
            mode="videos"
        )
        self.assertEqual(len(res_vids["entries"]), 1)
        self.assertEqual(mock_dl.call_count, 1)

        # 3. Mode: 'selected' -> should only download specified URLs
        mock_dl.reset_mock()
        res_sel = instagram_profile_download(
            "https://www.instagram.com/creator_jane/",
            str(self.test_dir),
            browser="none",
            report=lambda r: reports.append(r),
            mode="selected",
            selected_urls=["https://www.instagram.com/reel/reel2/"]
        )
        self.assertEqual(len(res_sel["entries"]), 1)
        self.assertEqual(mock_dl.call_count, 1)


if __name__ == "__main__":
    unittest.main()
