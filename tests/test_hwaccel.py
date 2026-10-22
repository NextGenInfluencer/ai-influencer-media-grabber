import unittest
from unittest.mock import patch
import hwaccel
from app_local import app


class TestHwaccel(unittest.TestCase):
    def setUp(self):
        hwaccel._CACHED_ENCODERS.clear()

    def test_detect_best_encoder_structure(self):
        info = hwaccel.detect_best_encoder(preferred_codec="h264")
        self.assertIsInstance(info, dict)
        self.assertIn("encoder", info)
        self.assertIn("codec", info)
        self.assertEqual(info["codec"], "h264")
        self.assertIn("type", info)
        self.assertIn(info["type"], {"gpu", "cpu"})
        self.assertIn("hardware_accelerated", info)
        self.assertIsInstance(info["hardware_accelerated"], bool)
        self.assertIn("display_name", info)

    def test_detect_best_encoder_hevc(self):
        info = hwaccel.detect_best_encoder(preferred_codec="hevc")
        self.assertIsInstance(info, dict)
        self.assertEqual(info["codec"], "hevc")
        self.assertIn(info["type"], {"gpu", "cpu"})

    def test_force_cpu_fallback(self):
        info_h264 = hwaccel.detect_best_encoder(preferred_codec="h264", force_cpu=True)
        self.assertEqual(info_h264["encoder"], "libx264")
        self.assertEqual(info_h264["type"], "cpu")
        self.assertFalse(info_h264["hardware_accelerated"])

        info_hevc = hwaccel.detect_best_encoder(preferred_codec="hevc", force_cpu=True)
        self.assertEqual(info_hevc["encoder"], "libx265")
        self.assertEqual(info_hevc["type"], "cpu")
        self.assertFalse(info_hevc["hardware_accelerated"])

    def test_get_video_encoder_args(self):
        for quality in ["draft", "standard", "high", "4k"]:
            args = hwaccel.get_video_encoder_args(codec="h264", quality=quality)
            self.assertIsInstance(args, list)
            self.assertIn("-c:v", args)
            c_idx = args.index("-c:v")
            self.assertLess(c_idx + 1, len(args))
            self.assertTrue(len(args[c_idx + 1]) > 0)

    def test_get_video_encoder_args_force_cpu(self):
        args = hwaccel.get_video_encoder_args(codec="h264", quality="standard", force_cpu=True)
        self.assertEqual(args[0:2], ["-c:v", "libx264"])
        self.assertIn("-crf", args)

    def test_api_hwaccel_endpoint(self):
        client = app.test_client()
        client.get('/')
        res = client.get('/api/hwaccel')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("encoder", data)
        self.assertIn("display_name", data)
        self.assertIn("hardware_accelerated", data)

    def test_api_hwaccel_force_cpu_endpoint(self):
        client = app.test_client()
        client.get('/')
        res = client.get('/api/hwaccel?force_cpu=1')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("encoder"), "libx264")
        self.assertFalse(data.get("hardware_accelerated"))


if __name__ == "__main__":
    unittest.main()
