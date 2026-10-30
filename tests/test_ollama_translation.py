"""Local provider streaming, cancellation and malformed-response regressions."""
import tests._isolation
import json
import unittest
from unittest.mock import MagicMock, patch

import job_process
from assets import lyric_translation as translation


class OllamaTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(translation, 'require_local_ollama_model')
        guard.start()
        self.addCleanup(guard.stop)

    def response(self, chunks):
        response = MagicMock()
        response.status_code = 200
        response.__enter__.return_value = response
        response.iter_content.return_value = iter(chunks)
        return response

    def test_unicode_stream_and_final_event_without_newline(self):
        content = json.dumps({'lines':[{'id':'one','text':'Γεια σου','note':''}]},ensure_ascii=False)
        wire = (json.dumps({'message':{'content':content},'done':False},ensure_ascii=False)+'\n'+
                json.dumps({'done':True})).encode()
        response = self.response([wire[i:i+3] for i in range(0,len(wire),3)])
        with patch.object(translation,'models',return_value=['fixture']), patch.object(translation.requests,'post',return_value=response) as post:
            result = translation.translate([{'id':'one','text':'Hello'}],'Hello','Greek','fixture')
        self.assertEqual(result['one']['text'],'Γεια σου')
        self.assertTrue(post.call_args.kwargs['stream'])
        self.assertTrue(post.call_args.kwargs['json']['stream'])
        response.__exit__.assert_called_once()

    def test_cancellation_closes_response_before_more_content_is_used(self):
        cancelled = False
        def chunks():
            nonlocal cancelled
            yield b'{"message":{"content":"partial"},"done":false}\n'
            cancelled = True
            yield b'{"done":true}\n'
        response = self.response(chunks())
        with patch.object(translation.requests,'post',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'Cancelled'):
                with job_process.cancellation_scope(lambda:cancelled):
                    translation.ollama_chat('fixture',[],{})
        response.__exit__.assert_called_once()

    def test_missing_done_malformed_and_provider_errors_are_rejected(self):
        for chunk in (b'{"message":{"content":"partial"}}\n',b'invalid\n',b'[]\n',
                      b'{"error":"model failed"}\n',b'{"message":null}\n'):
            response = self.response([chunk])
            with self.subTest(chunk=chunk), patch.object(translation.requests,'post',return_value=response):
                with self.assertRaisesRegex(ValueError,'Saved lyrics were kept'):
                    translation.ollama_chat('fixture',[],{})
            response.__exit__.assert_called_once()

    def test_network_timeout_is_actionable(self):
        with patch.object(translation.requests,'post',side_effect=translation.requests.Timeout()):
            with self.assertRaisesRegex(ValueError,'Load the model'):
                translation.ollama_chat('fixture',[],{})

    def test_size_and_total_duration_are_bounded(self):
        response = self.response([b'x'*(1024*1024+1)])
        with patch.object(translation.requests,'post',return_value=response):
            with self.assertRaisesRegex(ValueError,'response limit'):
                translation.ollama_chat('fixture',[],{})
        response = self.response([b'\n'])
        with patch.object(translation.requests,'post',return_value=response), patch.object(translation.time,'monotonic',side_effect=[0,181]):
            with self.assertRaisesRegex(ValueError,'too long'):
                translation.ollama_chat('fixture',[],{})

    def test_cancelled_before_network_does_not_make_request(self):
        with patch.object(translation.requests,'post') as post, patch.object(translation,'check_cancelled',side_effect=RuntimeError('Cancelled by user')):
            with self.assertRaisesRegex(RuntimeError,'Cancelled'):
                translation.ollama_chat('fixture',[],{})
        post.assert_not_called()


class LocalModelGuardTests(unittest.TestCase):
    def test_remote_alias_and_unverifiable_models_never_receive_lyrics(self):
        for metadata in ({'remote_host': 'https://ollama.com', 'model_info': {'architecture': 'qwen'}},
                         {'remote_model': 'qwen-cloud'}, {}, [], {'model_info': None}):
            with self.subTest(metadata=metadata), patch.object(translation.requests, 'post') as post:
                post.return_value.status_code = 200
                post.return_value.json.return_value = metadata
                with self.assertRaisesRegex(ValueError, 'No lyrics were sent'):
                    translation.ollama_chat('innocent-local-alias', [{'content': 'private lyrics'}], {})
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
                translation.ollama_chat('fixture', [{'content': 'private lyrics'}], {})
            post.assert_called_once()

    def test_model_list_filters_remote_and_malformed_entries(self):
        with patch.object(translation, 'EMBEDDED_MODEL') as model, patch.object(translation.requests, 'get') as get:
            model.is_file.return_value = False
            get.return_value.json.return_value = {'models': [None, {}, {'name': 'local'},
                {'name': 'alias', 'remote_host': 'https://ollama.com'}, {'name': 42}]}
            self.assertEqual(translation.models(), ['local'])
