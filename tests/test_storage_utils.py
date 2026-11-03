"""Crash-safe JSON persistence shared by every module."""
import tests._isolation  # Must precede application imports.
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import storage_utils
from storage_utils import atomic_write_json, atomic_write_text, read_json_with_backup, replace_with_retry


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=tests._isolation.DATA_ROOT)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_writes_utf8_json_and_leaves_no_temporary_files(self):
        path = self.root / 'nested' / 'project.json'
        atomic_write_json(path, {'title': 'Καλημέρα', 'n': 1})
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'title': 'Καλημέρα', 'n': 1})
        self.assertIn('Καλημέρα', path.read_text(encoding='utf-8'))
        self.assertEqual([p.name for p in path.parent.iterdir()], ['project.json'])

    def test_text_is_written_without_newline_translation(self):
        path = self.root / 'notes.txt'
        atomic_write_text(path, 'a\nb\n')
        self.assertEqual(path.read_bytes(), b'a\nb\n')

    def test_transient_permission_error_is_retried_with_backoff(self):
        path = self.root / 'data.json'
        real_replace = storage_utils.os.replace
        calls, sleeps = [], []
        def flaky(source, destination):
            calls.append(destination)
            if len(calls) < 3:
                raise PermissionError(5, 'Access is denied')
            return real_replace(source, destination)
        with patch.object(storage_utils.os, 'replace', side_effect=flaky), \
                patch.object(storage_utils.time, 'sleep', side_effect=sleeps.append):
            atomic_write_json(path, [1, 2])
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), [1, 2])
        self.assertEqual(sleeps, [0.05, 0.1])

    def test_persistent_permission_error_raises_after_five_retries_and_cleans_up(self):
        path = self.root / 'data.json'
        path.write_text('"old"', encoding='utf-8')
        sleeps = []
        with patch.object(storage_utils.os, 'replace', side_effect=PermissionError(5, 'denied')), \
                patch.object(storage_utils.time, 'sleep', side_effect=sleeps.append):
            with self.assertRaises(PermissionError):
                atomic_write_json(path, 'new')
        self.assertEqual(sleeps, [0.05, 0.1, 0.2, 0.4, 0.8])
        self.assertEqual(path.read_text(encoding='utf-8'), '"old"')
        self.assertEqual([p.name for p in self.root.iterdir()], ['data.json'])

    def test_other_errors_are_not_retried(self):
        sleeps = []
        with patch.object(storage_utils.os, 'replace', side_effect=FileNotFoundError('gone')):
            with self.assertRaises(FileNotFoundError):
                replace_with_retry('a', 'b', sleep=sleeps.append)
        self.assertEqual(sleeps, [])

    def test_backup_keeps_last_good_version_only(self):
        path = self.root / 'history.json'
        atomic_write_json(path, [1], backup=True)
        self.assertFalse(storage_utils.backup_path(path).exists())
        atomic_write_json(path, [1, 2], backup=True)
        self.assertEqual(json.loads(storage_utils.backup_path(path).read_text(encoding='utf-8')), [1])
        path.write_text('{broken', encoding='utf-8')
        atomic_write_json(path, [3], backup=True)
        # A damaged file never replaces the good backup.
        self.assertEqual(json.loads(storage_utils.backup_path(path).read_text(encoding='utf-8')), [1])


class ReadWithBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=tests._isolation.DATA_ROOT)
        self.root = Path(self.temp.name)
        self.path = self.root / 'history.json'

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_file_returns_copy_of_default(self):
        default = {'items': []}
        result = read_json_with_backup(self.path, default)
        result['items'].append(1)
        self.assertEqual(default, {'items': []})

    def test_valid_file_is_returned(self):
        atomic_write_json(self.path, [{'id': 1}])
        self.assertEqual(read_json_with_backup(self.path, []), [{'id': 1}])

    def test_corrupt_file_is_preserved_and_backup_restored(self):
        atomic_write_json(self.path, ['good'])
        atomic_write_json(self.path, ['newer'], backup=True)
        self.path.write_text('{"truncated', encoding='utf-8')
        self.assertEqual(read_json_with_backup(self.path, []), ['good'])
        corrupt = list(self.root.glob('history.corrupt-*.json'))
        self.assertEqual(len(corrupt), 1)
        self.assertEqual(corrupt[0].read_text(encoding='utf-8'), '{"truncated')
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), ['good'])

    def test_corrupt_file_without_backup_returns_default(self):
        self.path.write_bytes(b'\xff\xfe not json')
        self.assertEqual(read_json_with_backup(self.path, ['default']), ['default'])
        self.assertFalse(self.path.exists())
        self.assertEqual(len(list(self.root.glob('history.corrupt-*.json'))), 1)

    def test_validation_failure_counts_as_corruption(self):
        atomic_write_json(self.path, {'not': 'a list'})
        self.assertEqual(read_json_with_backup(self.path, [], validate=lambda d: isinstance(d, list)), [])
        self.assertEqual(len(list(self.root.glob('history.corrupt-*.json'))), 1)

    def test_corrupt_backup_falls_back_to_default(self):
        storage_utils.backup_path(self.path).write_text('nope', encoding='utf-8')
        self.assertEqual(read_json_with_backup(self.path, 'default'), 'default')

    def test_missing_main_file_uses_backup(self):
        storage_utils.backup_path(self.path).write_text('[7]', encoding='utf-8')
        self.assertEqual(read_json_with_backup(self.path, []), [7])
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), [7])


if __name__ == '__main__':
    unittest.main()
