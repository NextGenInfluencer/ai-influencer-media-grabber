"""Unit tests for Motion Studio & Reference Snapper."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from assets import motion_studio

class TestMotionStudio(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.orig_data_dir = motion_studio.DATA_DIR
        self.orig_ref_dir = motion_studio.REFERENCES_DIR
        self.orig_out_dir = motion_studio.MOTION_OUTPUT_DIR

        motion_studio.DATA_DIR = Path(self.temp_dir.name)
        motion_studio.REFERENCES_DIR = motion_studio.DATA_DIR / 'References'
        motion_studio.MOTION_OUTPUT_DIR = motion_studio.DATA_DIR / 'Motion Outputs'
        motion_studio._ensure_dirs()
        motion_studio._ffmpeg()

    def tearDown(self):
        motion_studio.DATA_DIR = self.orig_data_dir
        motion_studio.REFERENCES_DIR = self.orig_ref_dir
        motion_studio.MOTION_OUTPUT_DIR = self.orig_out_dir
        self.temp_dir.cleanup()

    def test_ensure_dirs_and_list_references(self):
        self.assertTrue(motion_studio.REFERENCES_DIR.is_dir())
        self.assertTrue(motion_studio.MOTION_OUTPUT_DIR.is_dir())
        refs = motion_studio.list_references()
        self.assertEqual(refs, [])

        # create a dummy png
        p = motion_studio.REFERENCES_DIR / 'sample_ref.png'
        p.write_bytes(b'\x89PNG\r\n\x1a\n')
        refs = motion_studio.list_references()
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]['name'], 'sample_ref.png')

    def test_extract_reference_frame_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            motion_studio.extract_reference_frame('non_existent_video.mp4', 1.5)

    @patch('assets.motion_studio.subprocess.run')
    def test_extract_reference_frame_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        # Create dummy video file
        dummy_vid = motion_studio.DATA_DIR / 'dummy.mp4'
        dummy_vid.write_bytes(b'fake mp4 bytes')

        # Dummy destination file so is_file() passes
        def fake_ffmpeg(*args, **kwargs):
            out_file = args[0][-1]
            Path(out_file).write_bytes(b'\x89PNG\r\n\x1a\nfake')
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg
        res = motion_studio.extract_reference_frame(str(dummy_vid), timestamp_sec=2.5)
        self.assertIn('ref_dummy_', res['filename'])
        self.assertEqual(res['timestamp'], 2.5)
        self.assertTrue(Path(res['path']).is_file())

    def test_resolve_image_path(self):
        # Direct file
        p = motion_studio.REFERENCES_DIR / 'test.png'
        p.write_bytes(b'data')
        self.assertEqual(motion_studio.resolve_image_path(str(p)), p)

        # URL path to references
        resolved = motion_studio.resolve_image_path('/api/motion/references/file/test.png')
        self.assertEqual(resolved, p)

        # Non existent
        self.assertIsNone(motion_studio.resolve_image_path('missing.png'))

    def test_render_character_motion_missing_image(self):
        with self.assertRaises(FileNotFoundError):
            motion_studio.render_character_motion('', 'missing_image.png')

    @patch('assets.motion_studio.subprocess.run')
    def test_render_character_motion_success(self, mock_run):
        # Create dummy image
        p = motion_studio.REFERENCES_DIR / 'face.png'
        p.write_bytes(b'image data')

        def fake_ffmpeg(*args, **kwargs):
            out_file = args[0][-1]
            Path(out_file).write_bytes(b'fake mp4 video')
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg
        res = motion_studio.render_character_motion('', str(p))
        self.assertIn('motion_face_', res['filename'])
        self.assertTrue(Path(res['path']).is_file())

    @patch('assets.motion_studio.subprocess.run')
    def test_motion_job_lifecycle(self, mock_run):
        # Create dummy image
        p = motion_studio.REFERENCES_DIR / 'face.png'
        p.write_bytes(b'image data')

        def fake_ffmpeg(*args, **kwargs):
            out_file = args[0][-1]
            Path(out_file).write_bytes(b'fake mp4 video')
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        job_id = motion_studio.start_motion_job('', str(p))
        self.assertTrue(job_id.startswith('motion_'))

        job = motion_studio.get_motion_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job['id'], job_id)

        # Test cancellation
        cancelled = motion_studio.cancel_motion_job(job_id)
        self.assertTrue(cancelled)


if __name__ == '__main__':
    unittest.main()
