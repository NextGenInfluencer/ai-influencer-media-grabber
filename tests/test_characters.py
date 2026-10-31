"""Unit and regression tests for Universal Character Library."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import characters


class CharacterLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix='mg_test_chars_'))
        self.dir_patch = patch.object(characters, 'CHARACTERS_DIR', self.temp_dir)
        self.file_patch = patch.object(characters, 'CHARACTERS_FILE', self.temp_dir / 'characters.json')
        self.dir_patch.start()
        self.file_patch.start()

    def tearDown(self):
        self.file_patch.stop()
        self.dir_patch.stop()
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_seed_contains_airi(self):
        chars = characters.list_characters()
        self.assertTrue(len(chars) >= 1)
        airi = chars[0]
        self.assertEqual(airi['id'], 'airi')
        self.assertEqual(airi['tag'], '@Airi')
        self.assertIn('Airi', airi['name'])

    def test_create_and_retrieve_custom_character(self):
        new_char = {
            "name": "Luna Star",
            "tag": "@Luna",
            "bio": "Cyberpunk anime pop idol",
            "trigger_prompt": "Luna, blue twin tails, glowing cyber visor",
            "aspect_ratio": "9:16"
        }
        saved = characters.save_character(new_char)
        self.assertEqual(saved['name'], 'Luna Star')
        self.assertEqual(saved['tag'], '@Luna')

        fetched = characters.get_character('luna_star')
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched['trigger_prompt'], new_char['trigger_prompt'])

    def test_tag_lookup_case_insensitive(self):
        char = characters.get_character('@airi')
        self.assertIsNotNone(char)
        self.assertEqual(char['id'], 'airi')

    def test_delete_character(self):
        custom = characters.save_character({"name": "Test Delete", "tag": "@DeleteMe"})
        cid = custom['id']
        self.assertIsNotNone(characters.get_character(cid))
        deleted = characters.delete_character(cid)
        self.assertTrue(deleted)
        self.assertIsNone(characters.get_character(cid))


if __name__ == '__main__':
    unittest.main()
