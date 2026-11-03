"""Role router (Ollama + built-in) and translation routing against a fake local Ollama."""
import tests._isolation  # noqa: F401  (must precede application imports)
import json
import unittest
from unittest.mock import MagicMock, patch

import job_process
from assets import lyric_translation
from ai_core import engines, hardware, llm, models, settings, translate
from ai_core.errors import AIUnavailable, ModelMissing
from tests._ai_support import HIGH_INFO, LAPTOP_INFO, FakeOllama, IsolatedAIMixin

TOOLS = [{'type': 'function', 'function': {'name': 'shift_timing', 'description': 'Shift captions',
                                           'parameters': {'type': 'object', 'properties': {'seconds': {'type': 'number'}}}}}]


class OllamaRouterTests(IsolatedAIMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.server = FakeOllama(models=[
            {'name': 'qwen3:14b', 'size': 9_000_000_000, 'capabilities': ['completion', 'tools', 'thinking']},
            {'name': 'qwen2.5:14b', 'size': 8_900_000_000, 'capabilities': ['completion', 'tools']},
            {'name': 'nomic-embed-text:latest', 'size': 1_000, 'capabilities': ['embedding']},
        ]).start()
        self.addCleanup(self.server.stop)
        llm._caps_cache.clear()
        self.addCleanup(llm._caps_cache.clear)
        for target, attribute, value in ((engines.ollama, 'base_url', self.server.url),
                                         (lyric_translation, 'LOCAL_URL', self.server.url)):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        detect = patch.object(hardware, 'detect', return_value=HIGH_INFO)
        detect.start()
        self.addCleanup(detect.stop)

    def script(self, *events):
        self.server.chat_script.append(list(events))

    def test_resolve_prefers_recommended_then_capable_fallback(self):
        choice = llm.resolve('helper')
        self.assertEqual((choice['backend'], choice['model'], choice['local']), ('ollama', 'qwen3:14b', True))
        self.server.models = [m for m in self.server.models if m['name'] != 'qwen3:14b']
        fallback = llm.resolve('helper')
        self.assertEqual(fallback['model'], 'qwen2.5:14b')
        self.assertGreater(fallback['vram_gb'], 8)
        with self.assertRaises(AIUnavailable) as raised:
            llm.resolve('vision')
        self.assertEqual(raised.exception.setup_hint, 'qwen2.5vl:7b')
        with self.assertRaises(AIUnavailable):
            llm.resolve('speech')

    def test_override_and_missing_override(self):
        settings.update(lambda d: d['roles'].__setitem__('translator', 'qwen2.5:14b'))
        self.assertEqual(llm.resolve('translator')['model'], 'qwen2.5:14b')
        settings.update(lambda d: d['roles'].__setitem__('translator', 'translategemma:12b'))
        with self.assertRaises(ModelMissing) as raised:
            llm.resolve('translator')
        self.assertEqual(raised.exception.setup_hint, 'translategemma:12b')
        self.assertEqual(llm.cost('translator')['available'], False)

    def test_streaming_chat_with_schema_think_false_and_keep_alive(self):
        self.script({'message': {'content': '{"ok":'}, 'done': False}, {'message': {'content': ' true}'}, 'done': True})
        tokens = []
        schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}}
        result = llm.chat('helper', [{'role': 'user', 'content': 'hi'}], schema=schema, on_token=tokens.append)
        self.assertEqual(result, {'content': '{"ok": true}', 'tool_calls': [], 'model': 'qwen3:14b', 'backend': 'ollama'})
        self.assertEqual(tokens, ['{"ok":', ' true}'])
        body = self.server.chat_requests()[0]
        self.assertEqual(body['format'], schema)
        self.assertIs(body['think'], False)
        self.assertTrue(body['stream'])
        self.assertEqual(body['keep_alive'], llm.KEEP_ALIVE)
        shows = [b for m, p, b in self.server.requests if p == '/api/show']
        self.assertIn({'model': 'qwen3:14b'}, shows)
        self.assertEqual(llm.cost('helper')['model'], 'qwen3:14b')

    def test_native_tool_calls_are_normalized(self):
        self.script({'message': {'content': '', 'tool_calls': [
            {'function': {'name': 'shift_timing', 'arguments': {'seconds': 1.5}}}]}, 'done': True})
        result = llm.chat('helper', [{'role': 'user', 'content': 'shift'}], tools=TOOLS)
        self.assertEqual(result['tool_calls'], [{'name': 'shift_timing', 'arguments': {'seconds': 1.5}}])
        self.assertEqual(self.server.chat_requests()[0]['tools'], TOOLS)
        self.script({'message': {'tool_calls': [{'function': {'name': 'x', 'arguments': '{bad'}}]}, 'done': True})
        with self.assertRaises(AIUnavailable):
            llm.chat('helper', [{'role': 'user', 'content': 'shift'}], tools=TOOLS)

    def test_images_attach_to_last_user_message(self):
        self.server.models.append({'name': 'qwen2.5vl:7b', 'size': 6_000_000_000, 'capabilities': ['completion', 'vision']})
        self.script({'message': {'content': 'a cat'}, 'done': True})
        result = llm.chat('vision', [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'what?'}], images=['QUJD'])
        self.assertEqual(result['model'], 'qwen2.5vl:7b')
        messages = self.server.chat_requests()[0]['messages']
        self.assertEqual(messages[-1]['images'], ['QUJD'])
        self.assertNotIn('think', self.server.chat_requests()[0])

    def test_locality_guard_blocks_remote_alias_before_chat(self):
        self.server.show['qwen3:14b'] = {'remote_host': 'https://ollama.com', 'model_info': {'a': 1}}
        with self.assertRaisesRegex(AIUnavailable, 'No lyrics were sent'):
            llm.chat('helper', [{'role': 'user', 'content': 'private lyrics'}])
        self.assertEqual(self.server.chat_requests(), [])

    def test_failures_never_fabricate_content(self):
        cases = [
            [{'error': 'model failed'}],
            [{'message': {'content': 'partial'}, 'done': False}],
            [{'message': {'content': ''}, 'done': True}],
            [{'message': {'content': 42}, 'done': True}],
            [{'message': 'bad', 'done': True}],
        ]
        for events in cases:
            self.script(*events)
            with self.subTest(events=events), self.assertRaises(AIUnavailable):
                llm.chat('helper', [{'role': 'user', 'content': 'hi'}])
        self.script({'message': {'content': 'not json'}, 'done': True})
        with self.assertRaisesRegex(AIUnavailable, 'structured'):
            llm.chat('helper', [{'role': 'user', 'content': 'hi'}], schema={'type': 'object'})
        with self.assertRaises(ValueError):
            llm.chat('helper', [])

    def test_cancellation_stops_streaming(self):
        self.script({'message': {'content': 'x'}, 'done': True})
        with self.assertRaisesRegex(RuntimeError, 'Cancelled'):
            with job_process.cancellation_scope(lambda: True):
                llm.chat('helper', [{'role': 'user', 'content': 'hi'}])

    def test_unreachable_ollama_is_reported(self):
        with patch.object(llm, 'require_local_ollama_model'), \
                patch.object(llm.requests, 'post', side_effect=llm.requests.ConnectionError()):
            with self.assertRaisesRegex(AIUnavailable, 'stopped responding'):
                llm.chat('helper', [{'role': 'user', 'content': 'hi'}])

    def test_available_models_lists_capabilities(self):
        names = {m['name']: m for m in llm.available_models()}
        self.assertEqual(names['qwen3:14b']['capabilities'], ['completion', 'thinking', 'tools'])
        self.assertTrue(all(m['local'] for m in names.values()))

    def test_show_capabilities_used_when_tags_lack_them(self):
        self.server.models = [{'name': 'mystery:7b', 'size': 4_000_000_000}]
        self.server.show['mystery:7b'] = {'model_info': {'a': 1}, 'capabilities': ['completion', 'vision']}
        self.assertEqual(llm.resolve('vision')['model'], 'mystery:7b')


class FakeLlama:
    def __init__(self, pieces):
        self.pieces = pieces
        self.kwargs = None

    def create_chat_completion(self, **kwargs):
        self.kwargs = kwargs
        return iter([{'choices': [{'delta': {'content': piece}}]} for piece in self.pieces])


class BuiltinRouterTests(IsolatedAIMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        for target, attribute, value in ((engines.ollama, 'tags', MagicMock(return_value=[])),
                                         (engines.builtin, 'available', MagicMock(return_value=True)),
                                         (hardware, 'detect', MagicMock(return_value=LAPTOP_INFO)),
                                         (models, 'installed', MagicMock(side_effect=lambda i: i == 'qwen3-1.7b')),
                                         (models, 'ensure', MagicMock(return_value='qwen.gguf'))):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_laptop_uses_builtin_with_schema_and_no_think(self):
        fake = FakeLlama(['<think>hmm</think>', '{"a": 1}'])
        with patch.object(llm, '_load_builtin', return_value=fake):
            result = llm.chat('helper', [{'role': 'user', 'content': 'hi'}], schema={'type': 'object'})
        self.assertEqual(result, {'content': '{"a": 1}', 'tool_calls': [], 'model': 'qwen3-1.7b', 'backend': 'builtin'})
        self.assertEqual(fake.kwargs['response_format'], {'type': 'json_object', 'schema': {'type': 'object'}})
        self.assertTrue(fake.kwargs['messages'][-1]['content'].endswith('/no_think'))

    def test_tool_calls_are_emulated_with_json_schema(self):
        fake = FakeLlama([json.dumps({'tool_calls': [{'name': 'shift_timing', 'arguments': {'seconds': 2}}], 'content': 'ok'})])
        history = [{'role': 'user', 'content': 'shift'},
                   {'role': 'assistant', 'content': '', 'tool_calls': [{'function': {'name': 'shift_timing', 'arguments': {}}}]},
                   {'role': 'tool', 'name': 'shift_timing', 'content': 'done'}]
        with patch.object(llm, '_load_builtin', return_value=fake):
            result = llm.chat('helper', history, tools=TOOLS)
        self.assertEqual(result['tool_calls'], [{'name': 'shift_timing', 'arguments': {'seconds': 2}}])
        schema = fake.kwargs['response_format']['schema']
        self.assertEqual(schema['properties']['tool_calls']['items']['properties']['name']['enum'], ['shift_timing'])
        self.assertTrue(any(m['content'].startswith('Tool result (shift_timing)') for m in fake.kwargs['messages']))
        bad = FakeLlama(['not json'])
        with patch.object(llm, '_load_builtin', return_value=bad), self.assertRaises(AIUnavailable):
            llm.chat('helper', history, tools=TOOLS)

    def test_builtin_refuses_images_and_empty_answers(self):
        with self.assertRaises(AIUnavailable):
            llm._builtin_chat(llm.resolve('helper'), [{'role': 'user', 'content': 'x'}], None, None, ['img'], 10, 0.1, None)
        with patch.object(llm, '_load_builtin', return_value=FakeLlama(['  '])), self.assertRaises(AIUnavailable):
            llm.chat('helper', [{'role': 'user', 'content': 'hi'}])

    def test_nothing_installed_gives_setup_hint(self):
        with patch.object(models, 'installed', return_value=False):
            with self.assertRaises(AIUnavailable) as raised:
                llm.resolve('helper')
        self.assertEqual(raised.exception.setup_hint, 'qwen3-1.7b')

    def test_load_builtin_is_cached_and_unloaded(self):
        fake_module = MagicMock()
        with patch.dict('sys.modules', {'llama_cpp': fake_module}):
            first = llm._load_builtin('a.gguf', {'chat_format': None})
            self.assertIs(llm._load_builtin('a.gguf', {'chat_format': None}), first)
        self.assertEqual(fake_module.Llama.call_count, 1)
        self.assertEqual(fake_module.Llama.call_args.kwargs['n_gpu_layers'], 0)
        llm._unload_builtin()
        first.close.assert_called_once()


class TranslationRoutingTests(unittest.TestCase):
    def test_classify_lines(self):
        cases = [
            ('Σ\' αγαπώ baby tonight', 'en', ('mixed', 'el')),
            ('I love you so much', 'English', ('same', 'en')),
            ('Σ\' αγαπώ', 'en', ('single', 'el')),
            ('Σ\' αγαπώ', 'Greek', ('same', 'el')),
            ('사랑해', 'en', ('single', 'ko')),
            ('Te quiero mi amor', 'en', ('single', 'es')),
            ('Bonjour', 'en', ('single', None)),
            ('oh oh yeah', 'en', ('same', 'en')),
            ('♪ ... 123', 'en', ('same', None)),
            ('Я люблю тебя', 'en', ('single', 'ru')),
            ('愛してる', 'ja', ('same', 'ja')),
            ('I love you', 'el', ('single', 'en')),
        ]
        for text, target, expected in cases:
            with self.subTest(text=text, target=target):
                self.assertEqual(translate.classify_line(text, target), expected)
        self.assertEqual(translate.language_name('ko'), 'Korean')
        self.assertEqual(translate.language_name('Klingon'), 'Klingon')

    def _fake_chat(self, calls, *, translategemma=False):
        def chat(role, messages, **kwargs):
            calls.append((role, messages, kwargs))
            if kwargs.get('schema'):
                payload = json.loads(messages[-1]['content'])
                lines = [{'id': line['id'], 'text': f'{role}:{line["text"]}', 'note': ''} for line in payload['lines']]
                return {'content': json.dumps({'lines': lines}), 'tool_calls': [], 'model': 'm', 'backend': 'ollama'}
            return {'content': 'I love you', 'tool_calls': [], 'model': 'tg', 'backend': 'ollama'}
        choice = {'backend': 'ollama', 'model': 'translategemma:12b' if translategemma else 'qwen3:14b',
                  'prompt_format': 'translategemma' if translategemma else None}
        return patch.object(translate.llm, 'chat', side_effect=chat), patch.object(translate.llm, 'resolve', return_value=choice)

    def test_routes_same_single_and_mixed(self):
        lines = [{'id': 'a', 'text': 'I love you'}, {'id': 'b', 'text': 'Σ\' αγαπώ'},
                 {'id': 'c', 'text': 'Σ\' αγαπώ baby'}, {'id': 'd', 'text': 'Σ\' αγαπώ'}]
        calls = []
        chat_patch, resolve_patch = self._fake_chat(calls)
        with chat_patch, resolve_patch:
            result = translate.translate_lines(lines, 'en', context='song', glossary='αγαπώ=love')
        self.assertEqual(result['a'], {'text': 'I love you', 'note': 'Same as original', 'route': 'same'})
        self.assertEqual(result['b']['route'], 'translator')
        self.assertEqual(result['d'], result['b'])  # chorus reuse
        self.assertEqual(result['c']['route'], 'helper')
        self.assertEqual([role for role, _, _ in calls], ['translator', 'helper'])
        translator_payload = json.loads(calls[0][1][-1]['content'])
        self.assertEqual(len(translator_payload['lines']), 1)
        self.assertEqual(translator_payload['glossary'], 'αγαπώ=love')
        self.assertIn('ONLY the parts that are not in the target language', calls[1][1][0]['content'])

    def test_translategemma_uses_native_prompt_one_line_with_context(self):
        lines = [{'id': 'a', 'text': 'Πού είσαι'}, {'id': 'b', 'text': 'Σ\' αγαπώ'}, {'id': 'c', 'text': 'Bonjour'}]
        calls = []
        chat_patch, resolve_patch = self._fake_chat(calls, translategemma=True)
        with chat_patch, resolve_patch:
            result = translate.translate_lines(lines, 'English')
        self.assertEqual(result['b'], {'text': 'I love you', 'note': '', 'route': 'translator'})
        self.assertEqual(result['c']['route'], 'helper')  # unknown source language
        prompt = calls[1][1][0]['content']
        self.assertIn('Greek (el) to English (en) translator', prompt)
        self.assertIn('previous line: "Πού είσαι"', prompt)
        self.assertTrue(prompt.endswith('Σ\' αγαπώ'))
        self.assertNotIn('schema', calls[1][2])

    def test_invalid_model_answers_raise(self):
        def unknown_id(role, messages, **kwargs):
            return {'content': json.dumps({'lines': [{'id': '99', 'text': 'x', 'note': ''}]}), 'tool_calls': [], 'model': 'm', 'backend': 'o'}
        with patch.object(translate.llm, 'resolve', return_value={'prompt_format': None}), \
                patch.object(translate.llm, 'chat', side_effect=unknown_id):
            with self.assertRaises(AIUnavailable):
                translate.translate_lines([{'id': 'a', 'text': 'Σ\' αγαπώ'}], 'en')
        with patch.object(translate.llm, 'resolve', return_value={'prompt_format': None}), \
                patch.object(translate.llm, 'chat', return_value={'content': 'nope'}):
            with self.assertRaises(AIUnavailable):
                translate.translate_lines([{'id': 'a', 'text': 'Σ\' αγαπώ'}], 'en')
        with self.assertRaises(AIUnavailable):
            translate._clean_plain('   ')
        with self.assertRaises(ValueError):
            translate.translate_lines('nope', 'en')

    def test_omitted_lines_are_split_and_retried(self):
        state = {'calls': 0}

        def chat(role, messages, **kwargs):
            state['calls'] += 1
            ids = [line['id'] for line in json.loads(messages[-1]['content'])['lines']]
            keep = ids if len(ids) == 1 else ids[:1]
            return {'content': json.dumps({'lines': [{'id': i, 'text': 'x', 'note': ''} for i in keep]})}
        lines = [{'id': 'a', 'text': 'Σ\' αγαπώ'}, {'id': 'b', 'text': 'Πού είσαι'}]
        with patch.object(translate.llm, 'resolve', return_value={'prompt_format': None}), \
                patch.object(translate.llm, 'chat', side_effect=chat):
            result = translate.translate_lines(lines, 'en')
        self.assertEqual(set(result), {'a', 'b'})
        self.assertEqual(state['calls'], 3)

    def test_classify_english_lines_with_indefinite_article_and_negation(self):
        english_lines = [
            'Cutting through sadness like a knife',
            'Living in a time where a man gets zero rest',
            'Nobody cares about the way a broken man feels',
            'Turned a simple peace into misery and strife',
            'Surrounded by a million people feeling so alone',
            'No turning back',
        ]
        for line in english_lines:
            with self.subTest(line=line):
                self.assertEqual(translate.classify_line(line, 'en'), ('same', 'en'))


if __name__ == '__main__':
    unittest.main()
