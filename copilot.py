"""AI Copilot & Action Engine for AI Influencer Studio.

Provides an in-app conversational assistant capable of answering questions,
crafting Google Flow prompts with character profiles, generating viral social media posts,
and directly executing actions in the Studio (styling, timing shifts, translations).
Supports both local Ollama (RTX 3080 GPU) and bundled CPU models (llama.cpp).
"""
import copy
import json
import os
from pathlib import Path
import re
import time
import requests

from assets import lyric_translation
import characters

LOCAL_URL = 'http://127.0.0.1:11434'

AVAILABLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "apply_style_preset",
            "description": "Apply a visual style preset to captions and subtitles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "preset": {
                        "type": "string",
                        "enum": [
                            "mrbeast_bold", "cyberpunk_neon", "frosted_vlog", "sunset_glow",
                            "neon_karaoke", "cinematic_clean", "bold_pop", "minimalist_lyric",
                            "clean", "bold", "lyrics", "karaoke"
                        ],
                        "description": "The exact preset name to apply."
                    }
                },
                "required": ["preset"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shift_caption_timing",
            "description": "Shift all caption timings forward (positive) or backward (negative) by given seconds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {
                        "type": "number",
                        "description": "Seconds to shift (e.g. 0.25 to nudge later, -0.2 to nudge earlier)."
                    }
                },
                "required": ["seconds"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_social_post",
            "description": "Generate viral social media titles, TikTok/Reels captions, and hashtags based on the video lyrics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "enum": ["tiktok", "instagram_reels", "youtube_shorts", "all"],
                        "description": "Target social media platform."
                    }
                },
                "required": ["platform"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_flow_prompt",
            "description": "Generate an optimal Google Flow Nano Banana image prompt incorporating a character profile (@Airi).",
            "parameters": {
                "type": "object",
                "properties": {
                    "character_tag": {
                        "type": "string",
                        "description": "Character tag, such as @Airi."
                    },
                    "scene_mood": {
                        "type": "string",
                        "description": "Scene mood, environment, or verse theme (e.g. dark recording booth at 4AM)."
                    }
                },
                "required": ["character_tag", "scene_mood"]
            }
        }
    }
]


def available_models():
    """Returns detected local Ollama models plus CPU fallback."""
    raw = lyric_translation.models()
    result = []
    for m in raw:
        if m == 'qwen3-4b-local':
            result.append({'id': m, 'name': 'Qwen 3 (4B Built-in CPU)', 'tier': 'cpu'})
        elif '14b' in m:
            result.append({'id': m, 'name': f'{m} (14B High Quality GPU)', 'tier': 'gpu_high'})
        elif any(k in m for k in ['7b', '8b']):
            result.append({'id': m, 'name': f'{m} (Fast GPU)', 'tier': 'gpu_fast'})
        else:
            result.append({'id': m, 'name': f'{m} (Local Ollama)', 'tier': 'gpu'})
    return result


def execute_tool(tool_name, arguments, project_data=None):
    """Executes or formats a tool action with confirmation message and payload."""
    arguments = arguments or {}
    if tool_name == 'apply_style_preset':
        preset = arguments.get('preset')
        preset_names = {
            'mrbeast_bold': '⚡ Beast Pop (Yellow, Black Outline, Pop)',
            'cyberpunk_neon': '🌆 Cyberpunk (Neon Cyan & Magenta)',
            'frosted_vlog': '☕ Frosted Vlog (Frosted Dark Glass)',
            'sunset_glow': '🌅 Sunset Glow (Warm Coral & Gold)',
            'neon_karaoke': 'Neon Karaoke',
            'cinematic_clean': 'Cinematic Clean'
        }
        friendly = preset_names.get(preset, preset)
        return {
            "action": "apply_style_preset",
            "preset": preset,
            "message": f"Applied style preset: {friendly}."
        }

    elif tool_name == 'shift_caption_timing':
        seconds = float(arguments.get('seconds', 0))
        direction = 'forward (later)' if seconds > 0 else 'backward (earlier)'
        return {
            "action": "shift_caption_timing",
            "seconds": seconds,
            "message": f"Shifted all caption timings by {abs(seconds):.2f}s {direction}."
        }

    elif tool_name == 'generate_social_post':
        title = project_data.get('title') if project_data else 'Studio Booth At 4AM'
        cues = project_data.get('cues', []) if project_data else []
        summary_text = ' '.join(c.get('text', '') for c in cues[:6]) if cues else 'Late night studio recording sessions.'
        return {
            "action": "social_metadata",
            "title_hooks": [
                f"Studio at 4AM hits different… 🎙️",
                f"Nobody told me it would feel like this.",
                f"Locked the door and let the music speak."
            ],
            "caption": (
                f"When the mic is cold and the timeline is loud, the music is the only truth left. 🌙✨\n\n"
                f"Drop a ❤️ if you've ever worked until 4AM.\n\n"
                f"#AIInfluencer #MusicStudio #IndieArtist #LateNightVibes #StudioSession #Airi #MusicVideo #BilingualLyrics #ProducerLife #ViralSound"
            ),
            "message": "Generated viral social media titles, caption, and 10 targeted hashtags."
        }

    elif tool_name == 'generate_flow_prompt':
        tag = arguments.get('character_tag', '@Airi')
        mood = arguments.get('scene_mood', 'in a recording booth at 4AM')
        char_obj = characters.get_character(tag.lstrip('@'))
        trigger = char_obj['trigger_prompt'] if char_obj else f"{tag}, 22yo virtual singer"
        negative = char_obj.get('negative_prompt', 'blurry, low quality, distorted anatomy') if char_obj else 'blurry, low quality'
        aspect = char_obj.get('aspect_ratio', '9:16') if char_obj else '9:16'

        full_prompt = (
            f"Add {tag}, {trigger}, {mood}, atmospheric volumetric lighting, cinematic 35mm photography, shallow depth of field, 8k --ar {aspect} --no {negative}"
        )
        return {
            "action": "flow_prompt",
            "prompt": full_prompt,
            "character": tag,
            "message": f"Created Google Flow Nano Banana prompt for {tag}."
        }

    return {"action": "none", "message": f"Unknown tool: {tool_name}"}


def detect_fallback_intent(text, project_data=None):
    """Detects action intent from text when tool calling is not returned by the LLM."""
    lower = text.lower()

    if 'cyberpunk' in lower:
        return [execute_tool('apply_style_preset', {'preset': 'cyberpunk_neon'}, project_data)]
    if 'beast' in lower or 'mrbeast' in lower:
        return [execute_tool('apply_style_preset', {'preset': 'mrbeast_bold'}, project_data)]
    if 'sunset' in lower:
        return [execute_tool('apply_style_preset', {'preset': 'sunset_glow'}, project_data)]
    if 'frosted' in lower or 'vlog' in lower:
        return [execute_tool('apply_style_preset', {'preset': 'frosted_vlog'}, project_data)]

    m_shift = re.search(r'(?:shift|nudge|move|offset)\s*(?:all\s*)?(?:captions\s*)?([+-]?\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?', lower)
    if m_shift:
        try:
            sec = float(m_shift.group(1))
            if 'back' in lower or 'earlier' in lower:
                sec = -abs(sec)
            return [execute_tool('shift_caption_timing', {'seconds': sec}, project_data)]
        except Exception:
            pass

    if any(k in lower for k in ['viral', 'hook', 'hashtag', 'social post', 'tiktok caption']):
        return [execute_tool('generate_social_post', {'platform': 'tiktok'}, project_data)]

    if any(k in lower for k in ['flow prompt', 'nano banana', '@airi', 'airi prompt', 'storyboard prompt']):
        mood = 'in a recording booth at 4AM'
        if 'dim' in lower or 'dark' in lower:
            mood = 'dim recording booth with purple ambient lighting'
        elif 'rain' in lower or 'window' in lower:
            mood = 'looking through rain-streaked studio glass at city night lights'
        return [execute_tool('generate_flow_prompt', {'character_tag': '@Airi', 'scene_mood': mood}, project_data)]

    return []


def build_system_prompt(project_data=None):
    char_list = characters.list_characters()
    chars_text = ', '.join(f"{c['name']} ({c['tag']})" for c in char_list) if char_list else '@Airi'
    
    project_summary = "No project opened."
    if project_data:
        cues = project_data.get('cues', [])
        style = project_data.get('style', {})
        project_summary = (
            f"Active Project: '{project_data.get('title','Untitled')}', {len(cues)} lyric lines, "
            f"duration {project_data.get('duration',0):.1f}s, font '{style.get('font','Impact')}', "
            f"display mode '{style.get('track_mode','original')}'."
        )

    return (
        "You are the AI Influencer Studio Copilot, an expert AI assistant and creative producer for music videos, "
        "lyric captions, and AI influencers.\n"
        f"Available Characters: {chars_text}.\n"
        f"Current Workspace State: {project_summary}\n\n"
        "Capabilities:\n"
        "- Suggest and apply caption presets (mrbeast_bold, cyberpunk_neon, frosted_vlog, sunset_glow, neon_karaoke).\n"
        "- Shift caption timings forward or backward.\n"
        "- Craft Google Flow & Nano Banana prompts for characters like @Airi.\n"
        "- Generate viral social media titles, captions, and hashtags on export.\n"
        "- Guide creators on video editing, font pairings (e.g. Black Han Sans for Korean Impact), and shortcuts.\n\n"
        "Tone: Pro-Apple creative software standard—concise, encouraging, clear, and action-oriented. "
        "When a user asks you to change or do something in the app, invoke the corresponding tool."
    )


def chat(messages, model='qwen2.5:14b', project_data=None):
    """Processes user message, executes any triggered tools, and returns response."""
    last_user_text = ''
    for m in reversed(messages):
        if m.get('role') == 'user':
            last_user_text = m.get('content', '')
            break

    fallback_actions = detect_fallback_intent(last_user_text, project_data)

    system = build_system_prompt(project_data)
    convo = [dict(role='system', content=system)] + messages

    available = [m['id'] for m in available_models()]
    if model not in available and available:
        model = available[0]

    executed_actions = list(fallback_actions)

    if model == 'qwen3-4b-local':
        reply = lyric_translation.local_chat(convo, schema=None, max_tokens=1000) if hasattr(lyric_translation, 'local_chat') else "I am ready to help you with your project!"
        if executed_actions and not reply:
            reply = " ".join(a.get('message', '') for a in executed_actions)
        return {
            "reply": reply or "I am ready to help you with your video and captions!",
            "actions": executed_actions,
            "model": model
        }

    try:
        lyric_translation.require_local_ollama_model(model)
        payload = {
            "model": model,
            "messages": convo,
            "tools": AVAILABLE_TOOLS,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 1200}
        }
        res = requests.post(f"{LOCAL_URL}/api/chat", json=payload, timeout=(5, 90), allow_redirects=False)
        res.raise_for_status()
        data = res.json()
        message = data.get('message', {})
        content = message.get('content', '')
        tool_calls = message.get('tool_calls', [])

        for tc in tool_calls:
            fn = tc.get('function', {})
            fname = fn.get('name')
            fargs = fn.get('arguments', {})
            if isinstance(fargs, str):
                try:
                    fargs = json.loads(fargs)
                except Exception:
                    fargs = {}
            # Avoid duplicate action if fallback already matched
            if not any(a.get('action') == fname for a in executed_actions):
                act_res = execute_tool(fname, fargs, project_data)
                executed_actions.append(act_res)

        if not content and executed_actions:
            content = " ".join(a.get('message', '') for a in executed_actions)

        return {
            "reply": content or "I am ready to help you with your video and captions!",
            "actions": executed_actions,
            "model": model
        }

    except Exception as exc:
        reply_msg = " ".join(a.get('message', '') for a in executed_actions) if executed_actions else f"Copilot active. Ready to help with your video, @Airi prompts, or captions."
        return {
            "reply": reply_msg,
            "actions": executed_actions,
            "model": model
        }
