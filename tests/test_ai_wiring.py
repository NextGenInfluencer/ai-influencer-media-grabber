"""v5 AI wiring: every AI feature goes through ai_core (no silent downloads), plus the setup UI hooks."""
import tests._isolation  # Must precede application imports.
import ast
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_prompter
import ai_runtime
from ai_core import llm, settings
from ai_core import translate as ai_translate
from ai_core.errors import AIUnavailable, ModelMissing
from flask import Flask
from routes_ai import register_ai_routes
from tests import test_lyric_tracks
from tests._ai_support import IsolatedAIMixin

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCES = [p for p in [*ROOT.glob('*.py'), *(ROOT / 'assets').glob('*.py'), *(ROOT / 'ai_core').glob('*.py')]]
SCENE = {'summary': 'A woman dancing in a kitchen', 'subject': 'young woman, long dark hair', 'setting': 'home kitchen',
         'lighting': 'warm window light from the left', 'camera': 'medium shot, eye level', 'mood': 'playful',
         'colors': ['beige', 'white'], 'wardrobe': 'white t-shirt and jeans', 'action': 'mid-spin, arms raised',
         'source': 'qwen2.5vl:7b'}


def read(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


def absent(test, needle, text, where):
    test.assertFalse(needle in text, f'{needle!r} must not appear in {where}')


def present(test, needle, text, where):
    test.assertTrue(needle in text, f'{needle!r} missing from {where}')


class NoSilentDownloadTests(unittest.TestCase):
    def test_legacy_download_paths_are_gone_from_app_code(self):
        patterns = {'whisper.load_model(': re.compile(r'(?<![\w.])whisper\.load_model\('),
                    'hf_hub_download(': re.compile(r'hf_hub_download\('),
                    'BLIP-large': re.compile(r'blip-image-captioning-large')}
        for source in APP_SOURCES:
            text = source.read_text(encoding='utf-8')
            for name, pattern in patterns.items():
                with self.subTest(file=source.name, pattern=name):
                    self.assertIsNone(pattern.search(text))

    def test_legacy_llama_stack_is_removed(self):
        app = read('app_local.py')
        for name in ('def get_llm', 'def llm_generate', 'def get_whisper', 'llama-3.2-1b', 'llama-3-8b', 'Llama('):
            absent(self, name, app, 'app')
        index = read('templates/index.html')
        absent(self, 'llama-3.2-1b', index, 'index')
        absent(self, 'llama-3-8b', index, 'index')
        absent(self, 'llmModelDownloader', index, 'index')

    def test_captions_use_ai_core_speech_and_translation(self):
        captions = read('captions.py')
        present(self, 'from ai_core import asr', captions, 'captions')
        absent(self, 'get_whisper', captions, 'captions')
        absent(self, 'lyric_translation', captions, 'captions')
        absent(self, 'translation-setup', captions, 'captions')


class PromptBuilderTests(unittest.TestCase):
    def test_structured_description_fills_prompt_and_keeps_preservation_rules(self):
        prompt = ai_prompter.build_prompt(SCENE)
        self.assertTrue(prompt.startswith(ai_prompter.PRESERVATION_PROMPT))
        for expected in ('white t-shirt and jeans', 'mid-spin, arms raised', 'medium shot, eye level',
                         'warm window light from the left', 'Kling motion control', 'may be inaccurate'):
            self.assertIn(expected, prompt)

    def test_blip_summary_only_and_empty_description(self):
        prompt = ai_prompter.build_prompt({'summary': 'a person standing', 'subject': None, 'colors': [], 'source': 'blip-base'})
        self.assertIn('- Summary: a person standing', prompt)
        self.assertNotIn('Outfit to keep', prompt)
        self.assertEqual(ai_prompter.build_prompt({}), ai_prompter.PRESERVATION_PROMPT)

    def test_extract_prompt_uses_local_vision_and_surfaces_missing_model(self):
        with patch.object(ai_prompter.vision, 'describe_scene', return_value=SCENE) as describe:
            self.assertIn('home kitchen', ai_prompter.extract_prompt_from_image('frame.png'))
        describe.assert_called_once_with('frame.png')
        with patch.object(ai_prompter.vision, 'describe_scene', side_effect=ModelMissing('No vision model', setup_hint='blip-base')):
            with self.assertRaises(AIUnavailable) as raised:
                ai_prompter.extract_prompt_from_image('frame.png')
        self.assertEqual(raised.exception.setup_hint, 'blip-base')


class HelperAndSubtitleTests(unittest.TestCase):
    def helper_generate(self):
        tree = ast.parse(read('app_local.py'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'helper_generate')
        namespace = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'app_local.py', 'exec'), namespace)
        return namespace['helper_generate']

    def test_smart_seo_uses_helper_role(self):
        with patch.object(llm, 'chat', return_value={'content': ' Summary \n', 'model': 'qwen3:14b'}) as chat:
            self.assertEqual(self.helper_generate()('transcript', 'You are an expert.'), 'Summary')
        self.assertEqual(chat.call_args.args[0], 'helper')
        self.assertEqual(chat.call_args.args[1][0], {'role': 'system', 'content': 'You are an expert.'})

    def test_translate_srt_keeps_cue_numbers_and_times_out_of_the_model(self):
        srt = '1\n00:00:00,000 --> 00:00:01,000\nΓεια σου\n\n2\n00:00:01,000 --> 00:00:02,000\nHello\n\n'
        def translate(lines, target, **options):
            self.assertEqual(target, 'English')
            self.assertNotIn('-->', json.dumps(lines))
            return {line['id']: {'text': f'T{line["id"]}', 'note': '', 'route': 'translator'} for line in lines}
        with patch.object(ai_translate, 'translate_lines', side_effect=translate):
            result = ai_runtime.translate_srt(srt, 'English')
        self.assertEqual(result, '1\n00:00:00,000 --> 00:00:01,000\nT0\n\n2\n00:00:01,000 --> 00:00:02,000\nT1\n\n')
        with patch.object(ai_translate, 'translate_lines', return_value={'0': {'text': '00:01 --> 00:02'}, '1': {'text': 'x'}}):
            with self.assertRaises(RuntimeError):
                ai_runtime.translate_srt(srt, 'English')

    def test_segments_to_srt(self):
        stamp = lambda s: f'{s:.1f}'
        text = ai_runtime.segments_to_srt([{'start': 0, 'end': 1, 'text': ' Hi '}, {'text': ' '}, 'bad'], stamp)
        self.assertEqual(text, '1\n0.0 --> 1.0\nHi\n\n')


class CompareLineTests(unittest.TestCase):
    def test_translator_and_helper_side_by_side(self):
        def resolve(role, model=None):
            return {'model': 'translategemma:12b' if role == 'translator' else 'qwen3:14b', 'backend': 'ollama',
                    'prompt_format': 'translategemma' if role == 'translator' else None}
        def chat(role, messages, **options):
            if role == 'translator':
                return {'content': 'Hello you', 'model': 'translategemma:12b'}
            return {'content': json.dumps({'lines': [{'id': '1', 'text': 'Hi there', 'note': ''}]}), 'model': 'qwen3:14b'}
        with patch.object(ai_translate.llm, 'resolve', side_effect=resolve), patch.object(ai_translate.llm, 'chat', side_effect=chat):
            result = ai_translate.compare_line('Γεια σου', 'en')
        self.assertEqual(result['translator']['text'], 'Hello you')
        self.assertEqual(result['helper']['text'], 'Hi there')
        self.assertEqual(result['source_language'], 'el')

    def test_one_side_missing_is_reported_and_both_missing_raises(self):
        def resolve(role, model=None):
            if role == 'translator':
                raise ModelMissing('No translator', setup_hint='translategemma:12b')
            return {'model': 'qwen3:14b', 'backend': 'ollama', 'prompt_format': None}
        answer = {'content': json.dumps({'lines': [{'id': '1', 'text': 'Hi', 'note': ''}]}), 'model': 'qwen3:14b'}
        with patch.object(ai_translate.llm, 'resolve', side_effect=resolve), patch.object(ai_translate.llm, 'chat', return_value=answer):
            result = ai_translate.compare_line('Γεια', 'en')
        self.assertEqual(result['translator'], {'error': 'No translator', 'setup_hint': 'translategemma:12b'})
        with patch.object(ai_translate.llm, 'resolve', side_effect=ModelMissing('Nothing installed', setup_hint='qwen3-4b')):
            with self.assertRaises(AIUnavailable):
                ai_translate.compare_line('Γεια', 'en')


class CaptionsAIWorkflowTests(unittest.TestCase):
    setUp = test_lyric_tracks.TrackWorkflowTests.setUp
    tearDown = test_lyric_tracks.TrackWorkflowTests.tearDown
    wait = test_lyric_tracks.TrackWorkflowTests.wait
    j = test_lyric_tracks.TrackWorkflowTests.j
    karaoke_project = test_lyric_tracks.TrackWorkflowTests.karaoke_project

    def test_translation_models_list_roles_auto_choice_and_setup_item(self):
        models = [{'name': 'qwen3:14b', 'backend': 'ollama', 'item_id': 'qwen3:14b', 'capabilities': ['tools'], 'local': True},
                  {'name': 'custom:7b', 'backend': 'ollama', 'item_id': None, 'capabilities': ['completion', 'vision'], 'local': True}]
        with patch('captions.ai_llm.available_models', return_value=models), \
                patch('captions.ai_llm.resolve', return_value={'model': 'qwen3:14b', 'backend': 'ollama'}), \
                patch('captions.ai_hardware.current_profile', return_value='gpu_high'), \
                patch('captions.ai_hardware.detect', return_value={}):
            data = self.client.get('/api/captions/translation-models').json
        self.assertEqual(data['models'][0]['roles'], ['helper', 'translator'])
        self.assertEqual(data['models'][1]['roles'], ['translator', 'vision'])
        self.assertEqual(data['auto'], {'available': True, 'model': 'qwen3:14b', 'backend': 'ollama', 'local': True})
        self.assertEqual(data['setup']['item_id'], 'translategemma:12b')

    def test_legacy_setup_route_is_gone_and_legacy_model_maps_to_catalog(self):
        pid, data = self.karaoke_project()
        self.assertEqual(self.client.post(f'/api/captions/{pid}/translation-setup', json={'revision': data['revision']}).status_code, 404)
        data['translation_settings'] = dict(model='qwen3-4b-local')
        data = self.client.put('/api/captions/' + pid, json=data).json
        with patch('captions.ai_translate.translate_lines',
                   side_effect=lambda lines, *a, **k: {l['id']: dict(text='x', note='', route='translator') for l in lines}) as model:
            self.client.post(f'/api/captions/{pid}/translate', json=dict(revision=data['revision'], language='en'))
            proposed = self.wait(pid)
        self.assertEqual(model.call_args.kwargs['model'], 'qwen3-4b')
        self.assertIn('Hello\nworld', model.call_args.kwargs['context'])  # whole song fits
        self.assertEqual(next(iter(proposed['translation_proposal']['lines'].values()))['route'], 'translator')

    def test_translate_ab_returns_both_sides_without_saving(self):
        pid, data = self.karaoke_project()
        cue = data['cues'][1]
        result = {'kind': 'single', 'source_language': 'el', 'translator': {'text': 'A'}, 'helper': {'text': 'B'}}
        with patch('captions.ai_translate.compare_line', return_value=result) as compare:
            response = self.client.post(f'/api/captions/{pid}/translate-ab', json={'cue_id': cue['id'], 'language': 'en'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json['translator']['text'], response.json['helper']['text']), ('A', 'B'))
        self.assertEqual(compare.call_args.kwargs['before'], data['cues'][0]['text'])
        self.assertEqual(self.client.get('/api/captions/' + pid).json['cues'], data['cues'])
        self.assertEqual(self.client.post(f'/api/captions/{pid}/translate-ab', json={'cue_id': 'nope'}).status_code, 400)
        with patch('captions.ai_translate.compare_line', side_effect=ModelMissing('No local model', setup_hint='qwen3-4b')):
            missing = self.client.post(f'/api/captions/{pid}/translate-ab', json={'cue_id': cue['id']})
        self.assertEqual((missing.status_code, missing.json['setup_hint']), (424, 'qwen3-4b'))

    def test_missing_speech_model_fails_job_with_setup_hint(self):
        pid, data = self.karaoke_project()
        with patch('captions.asr.align_words', side_effect=ModelMissing('No speech model is installed.', setup_hint='whisper-small')):
            self.client.post(f'/api/captions/{pid}/karaoke', json={'revision': data['revision'], 'language': 'en'})
            failed = self.wait(pid, 'error')
        self.assertIn('No speech model', failed['status'])
        self.assertEqual(failed['setup_hint'], 'whisper-small')
        self.assertEqual(failed['cues'], data['cues'])


class SettingsNoticeTests(IsolatedAIMixin, unittest.TestCase):
    def test_notices_and_setup_flag_persist_atomically(self):
        app = Flask('ai')
        register_ai_routes(app)
        client = app.test_client()
        response = client.post('/api/ai/settings', json={'notices': {'responsible_use': True}, 'setup_seen': True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['notices']['responsible_use'])
        self.assertFalse(response.json['notices']['download_copyright'])
        self.assertTrue(settings.load()['setup_seen'])
        self.assertEqual(client.post('/api/ai/settings', json={'notices': {'other': True}}).status_code, 400)
        self.assertEqual(client.post('/api/ai/settings', json={'setup_seen': 'yes'}).status_code, 400)


class SetupUIStaticTests(unittest.TestCase):
    def test_setup_assets_are_included_on_every_page(self):
        for page in ('templates/index.html', 'templates/captions.html', 'templates/video_studio.html'):
            html = read(page)
            with self.subTest(page=page):
                present(self, '/static/ai_setup.js', html, 'html')
                present(self, '/static/ai_setup.css', html, 'html')

    def test_engine_pack_install_reviews_notice_and_accepts(self):
        script = read('static/ai_setup.js')
        for expected in ('/api/install_ai/notice', 'accept: true', '/api/ai/install', 'accept_license',
                         '/api/ai/notice/', '/api/ai/storage', '/api/ai/remove', '/api/ai/engines', '/api/ai/cloud/key',
                         'window.openAISetup', 'window.openAIStorage', 'window.openAIEngines', 'window.ensureNoticeAccepted',
                         'Personal / non-commercial use only'):
            present(self, expected, script, 'script')
        index = read('templates/index.html')
        trigger = index[index.index('function triggerAiInstall'):]
        present(self, 'openAISetup', trigger[:400], 'trigger[:400]')
        absent(self, "fetch('/api/install_ai', { method: 'POST' })", index, 'index')

    def test_sync_tracking_ui_is_hoisted_and_ctrl_k_listed(self):
        index = read('templates/index.html')
        absent(self, "typeof syncTrackingUI === 'function'", index, 'index')
        present(self, 'Ctrl+K', index, 'index')
        absent(self, 'Characters (@Airi)', index, 'index')

    def test_face_tools_ask_for_responsible_use_notice(self):
        for page in ('static/video_studio.js', 'static/motion_studio.js'):
            with self.subTest(page=page):
                present(self, "ensureNoticeAccepted('responsible_use')", read(page), page)


if __name__ == '__main__':
    unittest.main()
