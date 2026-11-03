"""Locality guard: Ollama models proxied to a remote host never receive lyrics."""
import tests._isolation
import unittest
from unittest.mock import patch

from assets import lyric_translation as translation


class LocalModelGuardTests(unittest.TestCase):
    def test_remote_alias_and_unverifiable_models_never_receive_lyrics(self):
        for metadata in ({'remote_host': 'https://ollama.com', 'model_info': {'architecture': 'qwen'}},
                         {'remote_model': 'qwen-cloud'}, {}, [], {'model_info': None}):
            with self.subTest(metadata=metadata), patch.object(translation.requests, 'post') as post:
                post.return_value.status_code = 200
                post.return_value.json.return_value = metadata
                with self.assertRaisesRegex(ValueError, 'No lyrics were sent'):
                    translation.require_local_ollama_model('innocent-local-alias')
                post.assert_called_once()
                self.assertEqual(post.call_args.kwargs['json'], {'model': 'innocent-local-alias'})
                self.assertFalse(post.call_args.kwargs['allow_redirects'])

    def test_downloaded_model_is_accepted(self):
        with patch.object(translation.requests, 'post') as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {'model_info': {'general.architecture': 'qwen3'}}
            translation.require_local_ollama_model('qwen3:4b')

    def test_metadata_failure_blocks_generation(self):
        with patch.object(translation.requests, 'post', side_effect=translation.requests.Timeout()) as post:
            with self.assertRaisesRegex(ValueError, 'Cannot verify'):
                translation.require_local_ollama_model('fixture')
            post.assert_called_once()

    def test_cancelled_before_network_does_not_make_request(self):
        with patch.object(translation.requests, 'post') as post, \
                patch.object(translation, 'check_cancelled', side_effect=RuntimeError('Cancelled by user')):
            with self.assertRaisesRegex(RuntimeError, 'Cancelled'):
                translation.require_local_ollama_model('fixture')
        post.assert_not_called()

    def test_legacy_local_paths_are_gone(self):
        for name in ('local_chat', 'ollama_chat', 'models', 'translate', 'install_model', 'require_local_runtime'):
            self.assertFalse(hasattr(translation, name), name)


if __name__ == '__main__':
    unittest.main()
