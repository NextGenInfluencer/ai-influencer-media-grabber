"""Unit and regression tests for AI Copilot Engine."""
import json
import unittest
from unittest.mock import MagicMock, patch

import copilot


class CopilotEngineTests(unittest.TestCase):
    def test_apply_style_preset_tool(self):
        res = copilot.execute_tool('apply_style_preset', {'preset': 'cyberpunk_neon'})
        self.assertEqual(res['action'], 'apply_style_preset')
        self.assertEqual(res['preset'], 'cyberpunk_neon')
        self.assertIn('Cyberpunk', res['message'])

    def test_shift_caption_timing_tool(self):
        res = copilot.execute_tool('shift_caption_timing', {'seconds': 0.35})
        self.assertEqual(res['action'], 'shift_caption_timing')
        self.assertEqual(res['seconds'], 0.35)
        self.assertIn('forward', res['message'])

    def test_generate_social_post_tool(self):
        proj = {'title': 'Late Night Vibe', 'cues': [{'text': 'Line one'}, {'text': 'Line two'}]}
        res = copilot.execute_tool('generate_social_post', {'platform': 'tiktok'}, proj)
        self.assertEqual(res['action'], 'social_metadata')
        self.assertTrue(len(res['title_hooks']) >= 1)
        self.assertIn('#', res['caption'])

    def test_generate_flow_prompt_tool_injects_character(self):
        res = copilot.execute_tool('generate_flow_prompt', {
            'character_tag': '@Airi',
            'scene_mood': 'neon rainy rooftop overlooking Tokyo skyline'
        })
        self.assertEqual(res['action'], 'flow_prompt')
        self.assertIn('Airi', res['prompt'])
        self.assertIn('Tokyo skyline', res['prompt'])
        self.assertIn('aspect ratio', res['prompt'])

    def test_models_list_includes_cpu_and_tiers(self):
        with patch.object(copilot.lyric_translation, 'models', return_value=['qwen3-4b-local', 'qwen2.5:14b']):
            models = copilot.available_models()
            self.assertEqual(len(models), 2)
            # GPU model prioritized before CPU
            self.assertEqual(models[0]['tier'], 'gpu_high')
            self.assertEqual(models[1]['tier'], 'cpu')

    def test_fallback_intent_no_misfire(self):
        # 'move to line 3' must not trigger timing shift
        actions = copilot.detect_fallback_intent('can we move to line 3 please?')
        self.assertEqual(actions, [])

        # 'vlog' in general chat must not trigger style preset
        actions = copilot.detect_fallback_intent('should I start a travel vlog?')
        self.assertEqual(actions, [])

        # explicit shift with seconds unit works
        actions = copilot.detect_fallback_intent('please shift all captions by 0.5s')
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['action'], 'shift_caption_timing')
        self.assertEqual(actions[0]['seconds'], 0.5)

        # explicit preset mention works
        actions = copilot.detect_fallback_intent('apply the cyberpunk neon preset')
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['action'], 'apply_style_preset')


if __name__ == '__main__':
    unittest.main()
