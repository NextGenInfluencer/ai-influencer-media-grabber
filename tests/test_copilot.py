"""Copilot agent: real tool loop, proposals, dedupe, SSE and no fabricated output."""
import tests._isolation  # Must precede application imports
import json
import unittest
from unittest.mock import patch

import app_local
import copilot
from ai_core.errors import AIUnavailable

PROJECT = {'id': 'p1', 'name': 'Song', 'duration': 12, 'style': {'translation_language': 'en'}, 'cues': [
    {'id': 'c1', 'start': 0.0, 'end': 0.4, 'text': 'Καλή μέρα', 'translations': {}},
    {'id': 'c2', 'start': 0.3, 'end': 3.0, 'text': 'Hello world',
     'translations': {'en': {'text': 'Hello world', 'status': 'approved'}}},
]}
CONTEXT = {'page': 'captions', 'project': PROJECT}
HELPER = {'available': True, 'local': True, 'model': 'qwen3:14b', 'backend': 'ollama', 'eta_seconds': 20, 'vram_gb': 9}
SERVICES = {'gallery': lambda: [{'name': 'neon_dance.mp4', 'folder': 'TikTok', 'type': 'video', 'full_path': 'x'},
                                {'name': 'beach.jpg', 'folder': 'Instagram', 'type': 'image', 'full_path': 'y'}],
            'allowed_path': lambda path: False}
FABRICATIONS = ('translation:', 'locked in', '🌙', 'Copilot active', '#fyp', 'aspect ratio 9:16')


def answer(content='', calls=()):
    return {'content': content, 'tool_calls': list(calls), 'model': 'qwen3:14b', 'backend': 'ollama'}


class CopilotAgentTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(copilot, '_requirement_met', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_agent(self, responses, context=CONTEXT, events=None):
        with patch.object(copilot.llm, 'chat', side_effect=list(responses)) as chat:
            result = copilot.run_agent([{'role': 'user', 'content': 'help'}], dict(context), SERVICES,
                                       emit=(lambda e, d: events.append((e, d))) if events is not None else None)
        return result, chat

    def test_final_answer_without_tools(self):
        result, chat = self.run_agent([answer('Your captions look fine.')])
        self.assertEqual(result['reply'], 'Your captions look fine.')
        self.assertEqual(result['model'], 'qwen3:14b')
        self.assertEqual(chat.call_args.args[0], 'helper')
        self.assertTrue(chat.call_args.kwargs['tools'])

    def test_tool_loop_feeds_results_back(self):
        result, chat = self.run_agent([answer('', [{'name': 'audit_subtitles', 'arguments': {'focus': 'all'}}]),
                                       answer('Line 1 is too short and has no translation.')])
        self.assertEqual(chat.call_count, 2)
        second_messages = chat.call_args_list[1].args[1]
        tool_messages = [m for m in second_messages if m['role'] == 'tool']
        self.assertEqual(tool_messages[0]['tool_name'], 'audit_subtitles')
        audit = json.loads(tool_messages[0]['content'])
        types = {(i['line'], i['type']) for i in audit['issues']}
        self.assertIn((1, 'missing_translation'), types)
        self.assertIn((1, 'too_short'), types)
        self.assertIn((1, 'overlap'), types)
        self.assertEqual(result['tool_results'][0]['name'], 'audit_subtitles')

    def test_loop_stops_after_max_steps(self):
        call = answer('', [{'name': 'list_capabilities', 'arguments': {}}])
        with patch.object(copilot, 'capabilities', return_value={'tools': []}):
            result, chat = self.run_agent([call] * copilot.MAX_STEPS)
        self.assertEqual(chat.call_count, copilot.MAX_STEPS)
        self.assertIn('stopped after', result['reply'])

    def test_costly_tools_become_proposals_not_actions(self):
        calls = [{'name': 'batch_fix_subtitles', 'arguments': {'updates': [{'line': 1, 'translation': 'Good morning'}]}},
                 {'name': 'batch_fix_subtitles', 'arguments': {'updates': [{'line': 2, 'text': 'Hello, world'}]}},
                 {'name': 'shift_timing', 'arguments': {'seconds': 0.2}},
                 {'name': 'shift_timing', 'arguments': {'seconds': 0.25}}]
        result, _ = self.run_agent([answer('', calls), answer('Review the proposals below.')])
        proposals = {p['action']: p for p in result['proposals']}
        self.assertEqual(set(proposals), {'batch_fix_subtitles', 'shift_timing'})  # deduped by tool name
        self.assertEqual(proposals['shift_timing']['args'], {'seconds': 0.25})
        fixes = proposals['batch_fix_subtitles']
        self.assertEqual([u['line'] for u in fixes['args']['updates']], [1, 2])  # merged, not dropped
        self.assertEqual(fixes['diff'][0], {'line': 1, 'field': 'translation (en)', 'before': '', 'after': 'Good morning'})
        self.assertEqual(fixes['badge'], 'Local')

    def test_invalid_proposal_is_reported_to_the_model(self):
        result, chat = self.run_agent([answer('', [{'name': 'batch_fix_subtitles', 'arguments': {'updates': [{'line': 9, 'text': 'x'}]}}]),
                                       answer('Line 9 does not exist.')])
        self.assertEqual(result['proposals'], [])
        feedback = [m for m in chat.call_args_list[1].args[1] if m['role'] == 'tool'][0]
        self.assertIn('does not exist', feedback['content'])

    def test_navigate_refused_with_unsaved_edits(self):
        with self.assertRaisesRegex(ValueError, 'unsaved'):
            copilot.build_proposal('navigate', {'target': 'downloader'}, {**CONTEXT, 'unsaved': True})
        self.assertEqual(copilot.build_proposal('navigate', {'target': 'downloader'}, CONTEXT)['args'], {'target': 'downloader'})

    def test_gallery_search_and_page_tools(self):
        self.assertEqual(copilot.search_gallery(SERVICES, 'neon', 'video')['matches'][0]['name'], 'neon_dance.mp4')
        names = {s['name'] for s in copilot.tool_states('downloader')}
        self.assertIn('download_url', names)
        self.assertNotIn('batch_fix_subtitles', names)

    def test_unavailable_tools_are_not_offered(self):
        with patch.object(copilot, '_requirement_met', side_effect=lambda req: req != 'wan22_ti2v_5b'):
            states = copilot.tool_states('studio')
            specs = {s['function']['name'] for s in copilot.tool_specs(states)}
            prompt = copilot.system_prompt({'page': 'studio'}, states)
        self.assertNotIn('animate_keyframe', specs)
        self.assertIn('Not installed on this PC', prompt)
        self.assertIn('animate_keyframe', prompt)

    def test_all_cues_reach_the_model_or_a_chunk_tool(self):
        cues = [{'id': f'c{i}', 'start': i, 'end': i + 1, 'text': f'line number {i} ' + 'x' * 120} for i in range(400)]
        context = {'page': 'captions', 'project': {'name': 'Long', 'cues': cues, 'style': {}}}
        text = copilot.context_text(context)
        self.assertIn('#1 ', text)
        self.assertIn('call read_caption_lines', text)
        chunk = copilot.read_caption_lines(context, 390, 400)
        self.assertEqual(len(chunk['lines']), 11)
        self.assertIn('#400 ', chunk['lines'][-1])

    def test_unavailable_raises_without_fabricated_text(self):
        with patch.object(copilot.llm, 'chat', side_effect=AIUnavailable('No local model for the helper role is installed on this PC.',
                                                                         setup_hint='qwen3:14b')):
            with self.assertRaises(AIUnavailable) as caught:
                copilot.run_agent([{'role': 'user', 'content': 'translate line 1 to greek'}], dict(CONTEXT), SERVICES)
        self.assertEqual(caught.exception.setup_hint, 'qwen3:14b')

    def test_removed_fabrication_paths(self):
        for name in ('detect_fallback_intent', 'answer_from_knowledge_base', 'APP_KNOWLEDGE'):
            self.assertFalse(hasattr(copilot, name))
        self.assertNotIn('generate_social_post', copilot.TOOLS)
        self.assertNotIn('generate_flow_prompt', copilot.TOOLS)


class CopilotRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app_local.app.test_client()
        cls.client.get('/')
        with cls.client.session_transaction() as session:
            cls.headers = {'X-Media-Token': session['api_token']}

    def post(self, path, payload):
        return self.client.post(path, json=payload, headers=self.headers)

    def test_offline_returns_424_with_setup_hint_and_no_reply(self):
        error = AIUnavailable('No local model for the helper role is installed on this PC.', setup_hint='qwen3:8b')
        with patch.object(copilot.llm, 'chat', side_effect=error), patch.object(copilot, '_requirement_met', return_value=False):
            res = self.post('/api/copilot/chat', {'messages': [{'role': 'user', 'content': 'Translate line 1 to Greek'}],
                                                  'context': CONTEXT})
        self.assertEqual(res.status_code, 424)
        self.assertEqual(res.json, {'error': error.message, 'setup_hint': 'qwen3:8b'})
        body = res.get_data(as_text=True)
        for marker in FABRICATIONS:
            self.assertNotIn(marker, body)

    def test_chat_requires_token_and_message(self):
        self.assertEqual(self.client.post('/api/copilot/chat', json={}).status_code, 403)
        self.assertEqual(self.post('/api/copilot/chat', {'messages': []}).status_code, 400)

    def test_non_stream_chat_returns_proposals(self):
        responses = [answer('', [{'name': 'apply_preset', 'arguments': {'preset': 'cyberpunk_neon'}}]),
                     answer('I prepared the Cyberpunk preset. Press Apply to use it.')]
        with patch.object(copilot.llm, 'chat', side_effect=responses), patch.object(copilot, '_requirement_met', return_value=True):
            res = self.post('/api/copilot/chat', {'messages': [{'role': 'user', 'content': 'cyberpunk style'}], 'project': PROJECT})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json['proposals'][0]['action'], 'apply_preset')
        self.assertEqual(res.json['model'], 'qwen3:14b')

    def test_stream_event_format(self):
        def fake_chat(role, messages, **kwargs):
            if not any(m['role'] == 'tool' for m in messages):
                return answer('', [{'name': 'shift_timing', 'arguments': {'seconds': -0.2}}])
            kwargs['on_token']('Done')
            return answer('Done')
        with patch.object(copilot.llm, 'chat', side_effect=fake_chat), patch.object(copilot, '_requirement_met', return_value=True):
            res = self.post('/api/copilot/chat/stream', {'messages': [{'role': 'user', 'content': 'earlier'}], 'context': CONTEXT})
            body = res.get_data(as_text=True)
        self.assertEqual(res.mimetype, 'text/event-stream')
        events = [block.split('\n')[0][len('event: '):] for block in body.strip().split('\n\n')]
        self.assertEqual(events, ['tool_call', 'proposal', 'token', 'done'])
        done = json.loads(body.strip().split('\n\n')[-1].split('\ndata: ', 1)[1])
        self.assertEqual(done['proposals'][0]['action'], 'shift_timing')

    def test_stream_error_event_when_offline(self):
        with patch.object(copilot.llm, 'chat', side_effect=AIUnavailable('Ollama stopped responding.', setup_hint='engines')), \
                patch.object(copilot, '_requirement_met', return_value=False):
            body = self.post('/api/copilot/chat/stream', {'messages': [{'role': 'user', 'content': 'hi'}]}).get_data(as_text=True)
        self.assertTrue(body.startswith('event: error\n'))
        self.assertIn('"setup_hint": "engines"', body)

    def test_capabilities_reflect_installed_models(self):
        with patch.object(copilot.llm, 'cost', return_value={'available': False, 'error': 'none', 'setup_hint': 'qwen3:8b'}), \
                patch.object(copilot, '_requirement_met', side_effect=lambda req: req is None):
            data = self.client.get('/api/copilot/capabilities?page=studio').json
        tools = {t['name']: t['available'] for t in data['tools']}
        self.assertFalse(data['helper']['available'])
        self.assertFalse(tools['generate_keyframe'])
        self.assertTrue(tools['navigate'])


if __name__ == '__main__':
    unittest.main()
