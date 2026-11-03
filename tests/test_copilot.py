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

    def test_beast_pop_preset_and_pop_in_validation(self):
        import captions
        # Beast pop fallback intent
        actions = copilot.detect_fallback_intent('apply the beast pop style')
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['preset'], 'mrbeast_bold')

        # Test both 'pop' and 'pop_in' style validation
        clean_pop = captions.validate_edit({
            'cues': [{'start': 0.0, 'end': 1.0, 'text': 'Hello world'}],
            'style': {'animation': 'pop', 'color': '#ffe600'}
        }, 5.0)
        self.assertEqual(clean_pop['style']['animation'], 'pop')

        clean_pop_in = captions.validate_edit({
            'cues': [{'start': 0.0, 'end': 1.0, 'text': 'Hello world'}],
            'style': {'animation': 'pop_in', 'color': '#ffe600'}
        }, 5.0)
        self.assertEqual(clean_pop_in['style']['animation'], 'pop')

    def test_fix_translation_explicit(self):
        proj = {
            'cues': [
                {'id': 'c1', 'text': 'Intro verse', 'translations': {'en': {'text': 'Old trans'}}},
                {'id': 'c2', 'text': 'Chorus hook', 'translations': {'en': {'text': 'Previous chorus'}}}
            ],
            'style': {'translation_language': 'en'}
        }
        actions = copilot.detect_fallback_intent('change translation of line 2 to "Late night in Tokyo"', proj)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['action'], 'fix_translation')
        self.assertEqual(actions[0]['line'], 2)
        self.assertEqual(actions[0]['new_translation'], 'Late night in Tokyo')
        self.assertEqual(actions[0]['original_text'], 'Chorus hook')
        self.assertEqual(actions[0]['old_translation'], 'Previous chorus')

    def test_fix_translation_rephrase_options(self):
        proj = {
            'cues': [{'id': 'c1', 'text': 'Acoustic guitar melody', 'translations': {}}],
            'style': {'translation_language': 'en'}
        }
        actions = copilot.detect_fallback_intent('make line 1 translation poetic', proj)
        self.assertTrue(len(actions) >= 1)
        opt_action = next((a for a in actions if a['action'] == 'translation_options'), None)
        self.assertIsNotNone(opt_action)
        self.assertEqual(opt_action['line'], 1)
        self.assertTrue(len(opt_action['options']) >= 2)

    def test_fix_translation_target_language(self):
        proj = {
            'cues': [{'id': 'c1', 'text': 'Dancing in the dark', 'translations': {}}],
            'style': {'translation_language': 'en'}
        }
        actions = copilot.detect_fallback_intent('translate line 1 to greek', proj)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['action'], 'fix_translation')
        self.assertEqual(actions[0]['language'], 'el')

    def test_edit_subtitle_original_text(self):
        proj = {
            'cues': [{'id': 'c1', 'text': 'Teh night is young', 'translations': {}}],
            'style': {'translation_language': 'en'}
        }
        actions = copilot.detect_fallback_intent('fix typo in line 1: change text to "The night is young"', proj)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['action'], 'fix_subtitle_text')
        self.assertEqual(actions[0]['line'], 1)
        self.assertEqual(actions[0]['new_text'], 'The night is young')

    def test_audit_subtitles(self):
        proj = {
            'cues': [
                {'id': 'c1', 'start': 0.0, 'end': 0.5, 'text': 'Line 1', 'translations': {'en': {'text': 'This is a ridiculously long line that is impossible to read in half a second'}}},
                {'id': 'c2', 'start': 0.6, 'end': 2.0, 'text': 'Line 2', 'translations': {}}
            ],
            'style': {'translation_language': 'en'}
        }
        actions = copilot.detect_fallback_intent('audit my subtitles for issues', proj)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['action'], 'subtitle_audit')
        self.assertEqual(actions[0]['total_cues'], 2)
        # Should detect reading speed on line 1 and missing translation on line 2
        issue_types = [i['type'] for i in actions[0]['issues']]
        self.assertIn('reading_speed', issue_types)
        self.assertIn('missing_translation', issue_types)

    def test_navigation_and_folder_intents(self):
        # AI Studio assets in gallery
        act1 = copilot.detect_fallback_intent('show ai studio pictures and videos')
        self.assertEqual(act1[0]['action'], 'navigate_app')
        self.assertEqual(act1[0]['target'], 'gallery_studio')

        # Video Studio
        act2 = copilot.detect_fallback_intent('open video studio')
        self.assertEqual(act2[0]['action'], 'navigate_app')
        self.assertEqual(act2[0]['target'], 'video_studio')

        # Caption Studio
        act3 = copilot.detect_fallback_intent('go to captions')
        self.assertEqual(act3[0]['action'], 'navigate_app')
        self.assertEqual(act3[0]['target'], 'captions')

        # Open File Explorer
        act4 = copilot.detect_fallback_intent('open downloads folder in explorer')
        self.assertEqual(act4[0]['action'], 'open_downloads_folder')

        # Change font
        act5 = copilot.detect_fallback_intent('change font to Montserrat')
        self.assertEqual(act5[0]['action'], 'change_font')
        self.assertEqual(act5[0]['font'], 'Montserrat')

    def test_knowledge_base_qa_and_offline_chat(self):
        res = copilot.chat([{'role': 'user', 'content': 'what can you do on this app?'}], model='offline')
        self.assertIn('Copilot', res['reply'])
        self.assertTrue(any(a['action'] == 'show_capabilities' for a in res['actions']))

        res_ig = copilot.chat([{'role': 'user', 'content': 'how do I download an Instagram profile?'}], model='offline')
        self.assertIn('Instagram', res_ig['reply'])
        self.assertTrue(any(a['action'] == 'navigate_app' for a in res_ig['actions']))


if __name__ == '__main__':
    unittest.main()
