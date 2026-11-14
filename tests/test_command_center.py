"""Integration tests for v5.3.0 Command Center endpoints (/api/pipeline/config and /api/lineage)."""
import tests._isolation  # Must precede application imports.
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class CommandCenterEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=tests._isolation.DATA_ROOT)
        cls.root = Path(cls.temp.name)
        with patch.dict(os.environ, MEDIA_GRABBER_DATA_DIR=str(cls.root)):
            cls.module = importlib.import_module("app_local")
        tests._isolation.assert_isolated(cls.module.DEFAULT_SAVE_DIR)
        cls.client = cls.module.app.test_client()
        cls.client.get("/")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_pipeline_config_returns_v53_telemetry_with_zero_vram(self):
        response = self.client.get("/api/pipeline/config")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["app"]["version"], "5.3.0")
        for key in ("yt_dlp", "gallery_dl", "ffmpeg", "whisper", "kokoro_tts"):
            self.assertIn(key, data["binaries"])
        self.assertTrue(data["binaries"]["yt_dlp"]["installed"])
        self.assertTrue(bool(data["binaries"]["yt_dlp"]["version"]))
        ai = data["ai"]
        self.assertIn("profile", ai)
        self.assertIn("hardware", ai)
        self.assertIn("engines", ai)
        self.assertIn("vram_guard", ai)
        self.assertEqual(ai["vram_guard"]["allocated_gb"], 0.0)

    def test_lineage_links_source_raw_derived_and_studio_exports(self):
        with tempfile.TemporaryDirectory(dir=tests._isolation.DATA_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            tiktok_dir = root / "TikTok"
            conv_dir = root / "Conversions"
            proj_dir = root / "Caption Projects" / ("a" * 32)
            tiktok_dir.mkdir(parents=True)
            conv_dir.mkdir(parents=True)
            proj_dir.mkdir(parents=True)

            raw_clip = tiktok_dir / "demo_clip.mp4"
            raw_clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
            cover_frame = tiktok_dir / "demo_clip_first_frame.jpg"
            cover_frame.write_bytes(b"\xff\xd8\xff\xe0cover")
            sub_clip = conv_dir / "demo_clip_subbed.mp4"
            sub_clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")

            history_file = root / "history.json"
            history_file.write_text(json.dumps([{
                "file_path": str(raw_clip),
                "url": "https://www.tiktok.com/@creator/video/123456",
                "uploader": "@creator",
                "timestamp": 1700000000.0,
            }]), encoding="utf-8")

            (proj_dir / "project.json").write_text(json.dumps({
                "id": "a" * 32,
                "name": "Demo Studio Edit",
                "origin_path": str(raw_clip),
                "cues": [{"id": "c1", "start": 0.0, "end": 1.5, "text": "Hello"}],
                "exports": ["exports/demo_clip_captioned.mp4"],
                "studio": {"assets": {"music": "music.mp3"}},
            }), encoding="utf-8")

            with patch.object(self.module, "DEFAULT_SAVE_DIR", str(root)), \
                 patch.object(self.module, "HISTORY_FILE", str(history_file)):
                self.module.invalidate_gallery_cache()
                try:
                    response = self.client.get("/api/lineage")
                finally:
                    self.module.invalidate_gallery_cache()

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["with_source_url"], 1)
            self.assertEqual(payload["summary"]["studio_projects"], 1)
            self.assertEqual(payload["summary"]["rendered_exports"], 1)

            matched = [c for c in payload["chains"] if (c.get("raw") or {}).get("name") == "demo_clip.mp4"]
            self.assertEqual(len(matched), 1)
            chain = matched[0]
            self.assertEqual(chain["source"]["url"], "https://www.tiktok.com/@creator/video/123456")
            self.assertEqual(chain["source"]["uploader"], "@creator")
            derived_names = {d["name"] for d in chain["derived"]}
            self.assertIn("demo_clip_first_frame.jpg", derived_names)
            self.assertIn("demo_clip_subbed.mp4", derived_names)
            self.assertEqual(len(chain["exports"]), 1)
            self.assertTrue(chain["exports"][0]["has_music"])
            self.assertEqual(chain["exports"][0]["kind"], "rendered_export")
