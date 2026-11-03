"""AI Copilot & Action Engine for AI Influencer Studio.

Provides an in-app conversational assistant capable of answering questions,
crafting Google Flow prompts with character profiles, generating viral social media posts,
and directly executing actions in the Studio (styling, timing shifts, translations, navigation).
Supports local Ollama (RTX 3080 GPU), bundled CPU models, and zero-offline fallback.
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

APP_KNOWLEDGE = {
    "capabilities": {
        "title": "AI Influencer Studio Copilot - Capabilities",
        "description": (
            "I am your AI Influencer Studio Copilot, an expert AI assistant and creative producer. Here is what I can do for you:\n\n"
            "• **Subtitle & Lyric Translation Editor**: Fix awkward translations, change tone (poetic, viral, rhyming), correct typos, and audit reading speeds (CPS).\n"
            "• **1-Click Caption Styling**: Apply visual presets (*Beast Pop*, *Cyberpunk Neon*, *Frosted Vlog*, *Sunset Glow*, *Neon Karaoke*, etc.) and change fonts.\n"
            "• **Autonomous AI Video Studio**: Direct song concepts, generate multi-scene Storyboard prompts, animate with Wan 2.1 Motion Mimic, and control camera movements.\n"
            "• **Media Downloader & Profile Scraper**: Download Instagram profiles, carousels, reels, stories, TikToks without watermark, 4K YouTube videos, and extract high-fidelity audio with automated Shazam track recognition.\n"
            "• **Media Manager & Gallery**: Open downloads directly in Windows File Explorer, switch between All Downloads and AI Studio assets, and filter favorites.\n"
            "• **Format Converter & Privacy Cleaner**: Scrub tracking EXIF/GPS metadata, convert video formats, and apply CapCut-style video filters (VHS, Cyber Glow) and audio FX (8D Audio, Bass Boost)."
        )
    },
    "subtitles": {
        "title": "Caption & Subtitle Studio Guide",
        "description": (
            "The Caption Studio is a pro-grade subtitle and kinetic typography engine:\n\n"
            "• **Conversational Subtitle Fixing**: Just tell me: *'Change line 3 translation to...'*, *'Make line 2 translation poetic'*, or *'Check subtitles for errors'*.\n"
            "• **Reading Speed (CPS)**: Viewer-friendly captions should stay under 22 characters per second. I can audit your lines and flag any that move too fast.\n"
            "• **Styling Presets**: Choose from Beast Pop, Cyberpunk Neon, Frosted Vlog, Sunset Glow, Neon Karaoke, Cinematic Clean, Bold Pop, and Minimalist Lyric.\n"
            "• **Word-Level Kinetic Animation**: Supports word-pop, karaoke fill, glow effects, and WebGL dynamic audio visualizers.\n"
            "• **Export Options**: Export 60fps MP4, Apple ProRes 422 Studio Master, SRT subtitles, or bilingual dual-language SRTs."
        )
    },
    "downloader": {
        "title": "Media Downloader & Instagram Scraper Guide",
        "description": (
            "The Downloader supports high-speed media extraction across major platforms:\n\n"
            "• **Instagram Profiles & Carousels**: Paste `@username` or any Instagram profile URL to download all posts, or filter photos vs videos. Full carousel multi-slide posts are supported.\n"
            "• **TikTok Watermark-Free**: Paste any TikTok video or sound URL to download clean, full-resolution video.\n"
            "• **YouTube & 4K**: Download up to 4K Ultra HD video, or extract MP3, WAV, FLAC, or M4A audio with Shazam music recognition.\n"
            "• **Other Supported Sites**: Twitter/X, Pinterest, Facebook, SoundCloud, and Vimeo.\n"
            "• **Clipboard Auto-Detection**: Click '📋 Paste URL' to instantly paste and auto-detect media from your clipboard."
        )
    },
    "ai_studio": {
        "title": "AI Video Studio & Wan 2.1 Guide",
        "description": (
            "The AI Video Studio is an autonomous directing and motion generation environment:\n\n"
            "• **AI Song Director**: Analyzes lyrics, emotional arc, rhythm, and tone to generate 4 distinct directorial themes.\n"
            "• **Multi-Scene Storyboards**: Automatically generates visual keyframe prompts for each verse and chorus.\n"
            "• **Wan 2.1 Motion Mimic**: Generates dynamic camera motions (Pan Left/Right, Tilt Up/Down, Zoom In/Out, Dolly, Roll, Orbit) with frame continuity.\n"
            "• **3-Tier Neural Architecture**: Runs built-in local ONNX (lightweight, zero cloud cost), local GPU engines (Ollama, Wan 2.1, ComfyUI), or Cloud API fallback.\n"
            "• **Character Personas**: Lock personas like `@Airi` with LoRAs and reference images to ensure consistent faces across every scene."
        )
    },
    "shortcuts": {
        "title": "Pro Keyboard Shortcuts",
        "description": (
            "Master your studio workflow with these keyboard shortcuts:\n\n"
            "• `Ctrl+K` (or `Cmd+K`): Toggle AI Copilot assistant from anywhere.\n"
            "• `Space`: Play or pause video and audio playback.\n"
            "• `Ctrl+Z`: Undo last subtitle, caption, or storyboard edit.\n"
            "• `Ctrl+Shift+Z`: Redo last action.\n"
            "• `Ctrl+B`: Split caption or clip at the current playhead position.\n"
            "• `Delete` / `Backspace`: Delete selected caption cue or media asset.\n"
            "• `←` / `→`: Step backward or forward frame-by-frame.\n"
            "• `Escape`: Close Copilot drawer or open modals."
        )
    },
    "gallery": {
        "title": "Media Gallery & Assets Guide",
        "description": (
            "The Gallery organizes all your downloaded and generated media:\n\n"
            "• **All Downloads**: View all saved videos, music, and social media clips.\n"
            "• **AI Studio Tab**: Dedicated gallery tab for all AI-generated Storyboard Keyframe Images and Wan 2.1 Videos.\n"
            "• **Liked / Favorites**: Heart any item to quickly filter your best assets.\n"
            "• **Open in Explorer**: Click the button or tell Copilot *'Open downloads folder'* to reveal the directory in Windows File Explorer."
        )
    }
}

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
    },
    {
        "type": "function",
        "function": {
            "name": "fix_translation",
            "description": "Update or improve the translated text of a specific subtitle line.",
            "parameters": {
                "type": "object",
                "properties": {
                    "line": {
                        "type": "integer",
                        "description": "1-based subtitle line number."
                    },
                    "new_translation": {
                        "type": "string",
                        "description": "The revised, polished translation text."
                    },
                    "language": {
                        "type": "string",
                        "description": "Language code (e.g. 'en', 'es', 'el', 'ja', 'ko')."
                    },
                    "style": {
                        "type": "string",
                        "description": "Style of translation (e.g. 'poetic', 'viral', 'casual', 'literal')."
                    },
                    "explanation": {
                        "type": "string",
                        "description": "Brief explanation of why this translation is improved."
                    }
                },
                "required": ["line", "new_translation"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rephrase_translation_options",
            "description": "Provide multiple creative translation options (viral, poetic, loyal) for a specific line.",
            "parameters": {
                "type": "object",
                "properties": {
                    "line": {
                        "type": "integer",
                        "description": "1-based subtitle line number."
                    },
                    "language": {
                        "type": "string",
                        "description": "Target language code."
                    },
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "style": {"type": "string"},
                                "text": {"type": "string"},
                                "note": {"type": "string"}
                            },
                            "required": ["style", "text"]
                        },
                        "description": "List of translation style options."
                    }
                },
                "required": ["line", "options"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_subtitle_text",
            "description": "Modify the original lyric or subtitle text of a specific line (e.g. fix typos).",
            "parameters": {
                "type": "object",
                "properties": {
                    "line": {
                        "type": "integer",
                        "description": "1-based subtitle line number."
                    },
                    "new_text": {
                        "type": "string",
                        "description": "The corrected original text."
                    },
                    "explanation": {
                        "type": "string",
                        "description": "Brief explanation of the correction."
                    }
                },
                "required": ["line", "new_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "audit_subtitles",
            "description": "Audit active subtitles for reading speed (CPS), missing translations, or timing issues.",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "enum": ["all", "reading_speed", "missing_translations", "timing"],
                        "description": "Audit focus area."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_app",
            "description": "Navigate to a specific workspace, tab, or section within the application.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": [
                            "downloader", "converter", "cleaner",
                            "gallery_downloads", "gallery_studio",
                            "captions", "video_studio"
                        ],
                        "description": "Target view or workspace."
                    }
                },
                "required": ["target"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_downloads_folder",
            "description": "Reveal the application downloads directory in Windows File Explorer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Optional subfolder name."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "change_font_family",
            "description": "Change the caption typography font for the active video project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "font": {
                        "type": "string",
                        "description": "Font family name (e.g. Impact, Montserrat, Arial, Roboto, Black Han Sans)."
                    }
                },
                "required": ["font"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "show_capabilities",
            "description": "Display an interactive capability and feature directory for the Studio Copilot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional capability category (all, subtitles, downloader, studio, shortcuts)."
                    }
                }
            }
        }
    }
]


def available_models():
    """Returns detected local Ollama models plus CPU fallback.
    GPU models are prioritized first so NVIDIA RTX users get GPU by default."""
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

    tier_order = {'gpu_high': 0, 'gpu_fast': 1, 'gpu': 2, 'cpu': 3}
    result.sort(key=lambda x: tier_order.get(x.get('tier', 'gpu'), 9))
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
        title = project_data.get('title') if project_data else 'New Music Video'
        cues = project_data.get('cues', []) if project_data else []
        lead_line = cues[0].get('text', '') if cues else ''
        second_line = cues[1].get('text', '') if len(cues) > 1 else ''

        tag = arguments.get('character_tag') or '@Airi'
        char_name = tag.lstrip('@')
        hooks = [
            f"{lead_line or title} hits different… 🎙️",
            f"Locked the studio door and let the sound take over.",
            f"When the mic is live, the music is the only truth left."
        ]
        if second_line:
            hooks[1] = f"\"{second_line}\" — listen closely."

        caption = (
            f"\"{lead_line or 'Late night studio recording session'}\" 🌙✨\n\n"
            f"From the new session '{title}'. Drop a ❤️ if you feel this.\n\n"
            f"#{char_name} #AIInfluencer #MusicVideo #StudioSession #IndieArtist #ProducerLife #ViralSound"
        )
        return {
            "action": "social_metadata",
            "title_hooks": hooks,
            "caption": caption,
            "message": f"Generated viral social media titles and caption for #{char_name}."
        }

    elif tool_name == 'generate_flow_prompt':
        tag = arguments.get('character_tag', '@Airi')
        mood = arguments.get('scene_mood', 'in a recording booth at 4AM')
        char_obj = characters.get_character(tag.lstrip('@'))
        trigger = char_obj['trigger_prompt'] if char_obj else f"{tag}, 22yo virtual singer"
        aspect = char_obj.get('aspect_ratio', '9:16') if char_obj else '9:16'

        full_prompt = (
            f"Add {tag}, {trigger}, {mood}. "
            f"Cinematic 35mm photography, volumetric studio lighting, shallow depth of field, photorealistic 8k, aspect ratio {aspect}."
        )
        return {
            "action": "flow_prompt",
            "prompt": full_prompt,
            "character": tag,
            "message": f"Created Google Flow Nano Banana prompt for {tag}."
        }

    elif tool_name == 'fix_translation':
        line = int(arguments.get('line', 1))
        new_tr = str(arguments.get('new_translation', '')).strip()
        lang = str(arguments.get('language', 'en')).strip().lower()
        style = str(arguments.get('style', 'improved')).strip()
        explanation = str(arguments.get('explanation', '')).strip()

        cues = project_data.get('cues', []) if project_data else []
        idx = line - 1 if 0 < line <= len(cues) else 0
        target_cue = cues[idx] if (0 <= idx < len(cues)) else {}
        orig_text = target_cue.get('text', '')
        old_tr = target_cue.get('translations', {}).get(lang, {}).get('text', '') if isinstance(target_cue.get('translations'), dict) else ''

        return {
            "action": "fix_translation",
            "line": line,
            "cue_id": target_cue.get('id'),
            "language": lang,
            "original_text": orig_text,
            "old_translation": old_tr,
            "new_translation": new_tr,
            "style": style,
            "explanation": explanation,
            "message": f"Prepared Line {line} translation update: \"{new_tr}\"."
        }

    elif tool_name == 'rephrase_translation_options':
        line = int(arguments.get('line', 1))
        lang = str(arguments.get('language', 'en')).strip().lower()
        options = arguments.get('options', [])

        cues = project_data.get('cues', []) if project_data else []
        idx = line - 1 if 0 < line <= len(cues) else 0
        target_cue = cues[idx] if (0 <= idx < len(cues)) else {}
        orig_text = target_cue.get('text', '')

        return {
            "action": "translation_options",
            "line": line,
            "cue_id": target_cue.get('id'),
            "language": lang,
            "original_text": orig_text,
            "options": options,
            "message": f"Generated {len(options)} translation options for Line {line}."
        }

    elif tool_name == 'edit_subtitle_text':
        line = int(arguments.get('line', 1))
        new_text = str(arguments.get('new_text', '')).strip()
        explanation = str(arguments.get('explanation', '')).strip()

        cues = project_data.get('cues', []) if project_data else []
        idx = line - 1 if 0 < line <= len(cues) else 0
        target_cue = cues[idx] if (0 <= idx < len(cues)) else {}
        old_text = target_cue.get('text', '')

        return {
            "action": "fix_subtitle_text",
            "line": line,
            "cue_id": target_cue.get('id'),
            "old_text": old_text,
            "new_text": new_text,
            "explanation": explanation,
            "message": f"Updated Line {line} original text to: \"{new_text}\"."
        }

    elif tool_name == 'batch_fix_subtitles':
        updates = arguments.get('updates', [])
        return {
            "action": "batch_fix_subtitles",
            "updates": updates,
            "message": f"Prepared batch edits across {len(updates)} subtitle lines."
        }

    elif tool_name == 'audit_subtitles':
        cues = project_data.get('cues', []) if project_data else []
        lang = project_data.get('style', {}).get('translation_language', 'en') if project_data else 'en'
        issues = []
        for i, c in enumerate(cues):
            line_num = i + 1
            dur = c.get('end', 0) - c.get('start', 0)
            text = c.get('text', '')
            tr = c.get('translations', {}).get(lang, {}).get('text', '') if isinstance(c.get('translations'), dict) else ''
            if not tr.strip():
                issues.append({
                    "line": line_num,
                    "cue_id": c.get('id'),
                    "type": "missing_translation",
                    "severity": "warning",
                    "message": f"Line {line_num} has no translation.",
                    "text": text
                })
            elif dur > 0 and len(tr) / dur > 24:
                issues.append({
                    "line": line_num,
                    "cue_id": c.get('id'),
                    "type": "reading_speed",
                    "severity": "warning",
                    "cps": round(len(tr) / dur),
                    "duration": round(dur, 2),
                    "message": f"Line {line_num} is fast to read ({round(len(tr) / dur)} chars/s).",
                    "text": text,
                    "translation": tr
                })
        return {
            "action": "subtitle_audit",
            "total_cues": len(cues),
            "language": lang,
            "issues": issues,
            "message": f"Subtitles audit completed: {len(issues)} issue(s) detected across {len(cues)} lines."
        }

    elif tool_name == 'navigate_app':
        target = arguments.get('target', 'downloader')
        target_labels = {
            'downloader': 'Media Downloader',
            'converter': 'Format Converter & FX Suite',
            'cleaner': 'Metadata & Privacy Cleaner',
            'gallery_downloads': 'Gallery (All Downloads)',
            'gallery_studio': 'Gallery (AI Studio Assets)',
            'captions': 'Caption & Subtitle Studio',
            'video_studio': 'AI Video Studio'
        }
        return {
            "action": "navigate_app",
            "target": target,
            "label": target_labels.get(target, target),
            "message": f"Navigating to {target_labels.get(target, target)}."
        }

    elif tool_name == 'open_downloads_folder':
        folder = arguments.get('folder', 'downloads')
        return {
            "action": "open_downloads_folder",
            "folder": folder,
            "message": "Opening downloads directory in Windows File Explorer."
        }

    elif tool_name == 'change_font_family':
        font = arguments.get('font', 'Impact')
        return {
            "action": "change_font",
            "font": font,
            "message": f"Applied typography font: {font}."
        }

    elif tool_name == 'show_capabilities':
        category = arguments.get('category', 'all')
        return {
            "action": "show_capabilities",
            "category": category,
            "message": "Here is what I can do for you across the entire Studio."
        }

    return {"action": "none", "message": f"Unknown tool: {tool_name}"}


def answer_from_knowledge_base(query):
    """Returns structured knowledge answer and relevant action triggers based on query keywords."""
    lower = query.lower()

    if any(k in lower for k in ['what can you do', 'what can i do', 'capabilities', 'features', 'help me', 'show capabilities', 'what are your features']):
        return APP_KNOWLEDGE["capabilities"]["description"], [execute_tool('show_capabilities', {'category': 'all'})]

    if any(k in lower for k in ['shortcut', 'hotkey', 'keyboard', 'keys']):
        return APP_KNOWLEDGE["shortcuts"]["description"], [execute_tool('show_capabilities', {'category': 'shortcuts'})]

    if any(k in lower for k in ['instagram', 'profile', 'carousel', 'download', 'tiktok', 'youtube', 'soundcloud', 'shazam']) and not any(w in lower for w in ['subtitle', 'caption', 'timing', 'preset']):
        return APP_KNOWLEDGE["downloader"]["description"], [execute_tool('navigate_app', {'target': 'downloader'})]

    if any(k in lower for k in ['wan', 'motion', 'video studio', 'ai studio', 'storyboard', 'director', 'concept', 'camera']):
        return APP_KNOWLEDGE["ai_studio"]["description"], [execute_tool('navigate_app', {'target': 'video_studio'})]

    if any(k in lower for k in ['subtitle', 'caption', 'translation', 'cps', 'reading speed', 'prores', 'srt']) and not any(w in lower for w in ['shift', 'offset', 'line', 'cue', 'preset']):
        return APP_KNOWLEDGE["subtitles"]["description"], [execute_tool('navigate_app', {'target': 'captions'})]

    if any(k in lower for k in ['gallery', 'downloads folder', 'ai studio assets', 'explorer', 'where are my files']):
        return APP_KNOWLEDGE["gallery"]["description"], [execute_tool('open_downloads_folder', {})]

    return None, []


def detect_fallback_intent(text, project_data=None):
    """Detects action intent from text when tool calling is not returned by the LLM."""
    lower = text.lower()

    # 1. Subtitle & Translation Audit
    if any(w in lower for w in ['audit subtitle', 'audit caption', 'check subtitle', 'check caption', 'check translation', 'subtitles problem', 'translation problem', 'review subtitle', 'reading speed', 'audit my subtitle']):
        return [execute_tool('audit_subtitles', {'focus': 'all'}, project_data)]

    # 2. Open Directory / File Explorer
    if any(w in lower for w in ['open folder', 'open in explorer', 'open directory', 'show in folder', 'reveal in explorer', 'where are my files', 'open downloads folder']):
        return [execute_tool('open_downloads_folder', {'folder': 'downloads'}, project_data)]

    # 3. App Navigation
    if any(w in lower for w in ['go to video studio', 'open video studio', 'go to ai studio', 'open ai studio', 'motion studio']):
        return [execute_tool('navigate_app', {'target': 'video_studio'}, project_data)]
    if any(w in lower for w in ['go to captions', 'open caption studio', 'subtitle studio', 'open captions', 'go to subtitle']):
        return [execute_tool('navigate_app', {'target': 'captions'}, project_data)]
    if any(w in lower for w in ['show ai studio', 'ai studio assets', 'storyboard pictures', 'storyboard videos', 'studio gallery', 'gallery studio']):
        return [execute_tool('navigate_app', {'target': 'gallery_studio'}, project_data)]
    if any(w in lower for w in ['go to gallery', 'open gallery', 'show gallery', 'my downloads', 'all downloads']):
        return [execute_tool('navigate_app', {'target': 'gallery_downloads'}, project_data)]
    if any(w in lower for w in ['go to converter', 'open converter', 'format converter']):
        return [execute_tool('navigate_app', {'target': 'converter'}, project_data)]
    if any(w in lower for w in ['go to cleaner', 'open cleaner', 'exif cleaner']):
        return [execute_tool('navigate_app', {'target': 'cleaner'}, project_data)]
    if any(w in lower for w in ['go to downloader', 'open downloader', 'main downloader']):
        return [execute_tool('navigate_app', {'target': 'downloader'}, project_data)]

    # 4. Capabilities / Help
    if any(w in lower for w in ['what can you do', 'what can i do', 'show capabilities', 'features', 'what are your features', 'copilot help']):
        return [execute_tool('show_capabilities', {'category': 'all'}, project_data)]

    # 5. Font Styling
    m_font = re.search(r'\b(?:change|set|switch)\s+font\s+(?:to\s+)?([a-zA-Z0-9\s]+)\b', text, re.IGNORECASE)
    if m_font and not any(w in lower for w in ['style', 'preset', 'color']):
        font_name = m_font.group(1).strip()
        if font_name and font_name.lower() not in ['to', 'the']:
            return [execute_tool('change_font_family', {'font': font_name}, project_data)]

    # 6. Style Presets: require explicit style/preset context to avoid false positives (e.g. 'vlog')
    if 'cyberpunk' in lower and any(w in lower for w in ['preset', 'style', 'neon', 'look', 'theme']):
        return [execute_tool('apply_style_preset', {'preset': 'cyberpunk_neon'}, project_data)]
    if ('mrbeast' in lower or 'beast' in lower) and any(w in lower for w in ['pop', 'bold', 'preset', 'style', 'yellow', 'look']):
        return [execute_tool('apply_style_preset', {'preset': 'mrbeast_bold'}, project_data)]
    if 'sunset' in lower and any(w in lower for w in ['glow', 'preset', 'style', 'warm', 'look', 'theme']):
        return [execute_tool('apply_style_preset', {'preset': 'sunset_glow'}, project_data)]
    if 'frosted' in lower and any(w in lower for w in ['vlog', 'preset', 'style', 'glass', 'dark', 'look']):
        return [execute_tool('apply_style_preset', {'preset': 'frosted_vlog'}, project_data)]

    # 7. Timing Shift: require explicit seconds unit and timing verb so e.g. "move to line 3" does not fire
    m_shift = re.search(r'\b(?:shift|nudge|offset)\s+(?:all\s+)?(?:captions?\s+)?(?:by\s+)?([+-]?\d+(?:\.\d+)?)\s*(?:s|sec|seconds)\b', lower)
    if m_shift:
        try:
            sec = float(m_shift.group(1))
            if 'back' in lower or 'earlier' in lower:
                sec = -abs(sec)
            return [execute_tool('shift_caption_timing', {'seconds': sec}, project_data)]
        except Exception:
            pass

    # 8. Line-Specific Subtitle & Translation Editing
    m_line = re.search(r'\b(?:line|cue)\s*(\d+)\b', lower)
    line_num = int(m_line.group(1)) if m_line else None
    if not line_num:
        word_map = {'first': 1, '1st': 1, 'second': 2, '2nd': 2, 'third': 3, '3rd': 3, 'fourth': 4, '4th': 4, 'fifth': 5, '5th': 5}
        for w, n in word_map.items():
            if re.search(rf'\b{w}\s+(?:line|cue)\b', lower):
                line_num = n
                break

    if line_num is not None:
        cues = project_data.get('cues', []) if project_data else []
        cue_idx = line_num - 1 if 0 < line_num <= len(cues) else None
        target_cue = cues[cue_idx] if (cue_idx is not None and 0 <= cue_idx < len(cues)) else {}
        orig_text = target_cue.get('text', '')
        lang = project_data.get('style', {}).get('translation_language', 'en') if project_data else 'en'

        is_trans_intent = any(w in lower for w in ['translation', 'translate', 'meaning', 'in greek', 'in spanish', 'in japanese', 'in french', 'in korean', 'in german', 'poetic', 'viral', 'casual', 'formal', 'natural', 'rhyme'])
        has_edit_verb = any(w in lower for w in ['change', 'fix', 'replace', 'set', 'make', 'update', 'translate', 'edit', 'typo'])

        # Specific target language translation
        target_lang_match = None
        langs_dict = {
            'greek': 'el', 'spanish': 'es', 'japanese': 'ja', 'korean': 'ko',
            'french': 'fr', 'german': 'de', 'italian': 'it', 'english': 'en'
        }
        for lang_name, code in langs_dict.items():
            if lang_name in lower:
                target_lang_match = (lang_name, code)
                break

        m_quotes = re.search(r'["\']([^"\']+)["\']', text)
        replacement_text = m_quotes.group(1).strip() if m_quotes else None

        if not replacement_text and is_trans_intent and has_edit_verb:
            m_to = re.search(r'\b(?:to|should be|is|as)\s+([^?.!]+)', text, re.IGNORECASE)
            if m_to:
                cand = m_to.group(1).strip()
                if not any(cand.lower() == k for k in ['poetic', 'viral', 'casual', 'natural', 'rhyming', 'shorter', 'formal'] + list(langs_dict.keys())):
                    replacement_text = cand

        if target_lang_match and (is_trans_intent or has_edit_verb):
            lang_name, code = target_lang_match
            new_tr = replacement_text or f"[{lang_name.capitalize()} translation: {orig_text or f'Line {line_num}'}]"
            return [execute_tool('fix_translation', {
                'line': line_num,
                'new_translation': new_tr,
                'language': code,
                'style': 'translated',
                'explanation': f'Translated Line {line_num} into {lang_name.capitalize()}.'
            }, project_data)]

        # Explicit translation replacement
        if is_trans_intent and replacement_text:
            return [execute_tool('fix_translation', {
                'line': line_num,
                'new_translation': replacement_text,
                'language': lang,
                'style': 'user_specified',
                'explanation': f'Manually updated Line {line_num} translation.'
            }, project_data)]

        # Rephrasing request (poetic, viral, casual, rhyming)
        if is_trans_intent and any(w in lower for w in ['poetic', 'viral', 'casual', 'natural', 'emotional', 'rhyme', 'options', 'alternatives', 'ways to translate', 'make', 'sound']):
            base_phrase = orig_text or f"Line {line_num} verse"
            options = [
                {
                    "style": "Viral & Punchy (TikTok / Reels)",
                    "text": f"{base_phrase} — locked in 🌙⚡",
                    "note": "Short, energetic, optimized for vertical social video."
                },
                {
                    "style": "Poetic & Emotive (Soulful)",
                    "text": f"Lost in the sound of {base_phrase.lower()}",
                    "note": "Atmospheric, evocative, and melodically flowing."
                },
                {
                    "style": "Loyal & Fluent (Natural Speech)",
                    "text": f"{base_phrase}",
                    "note": "True to the artist's original phrasing and meter."
                }
            ]
            return [
                execute_tool('rephrase_translation_options', {
                    'line': line_num,
                    'language': lang,
                    'options': options
                }, project_data),
                execute_tool('fix_translation', {
                    'line': line_num,
                    'new_translation': options[0]['text'],
                    'language': lang,
                    'style': 'viral',
                    'explanation': 'Viral & Punchy option prepared.'
                }, project_data)
            ]


        # Original text / Typo correction
        if any(w in lower for w in ['typo', 'text', 'original', 'lyrics', 'change line', 'edit line']) and not is_trans_intent:
            if replacement_text:
                return [execute_tool('edit_subtitle_text', {
                    'line': line_num,
                    'new_text': replacement_text,
                    'explanation': f'Corrected original text for Line {line_num}.'
                }, project_data)]

    # 9. Persona Resolution
    char_list = characters.list_characters()
    matched_tag = None
    for c in char_list:
        c_tag = c.get('tag', '').lower()
        c_name = c.get('name', '').lower()
        if (c_tag and c_tag in lower) or (c_name and c_name in lower):
            matched_tag = c.get('tag')
            break
    target_tag = matched_tag or (char_list[0]['tag'] if char_list else '@Airi')

    if any(k in lower for k in ['viral', 'hook', 'hashtag', 'social post', 'tiktok caption']):
        return [execute_tool('generate_social_post', {'platform': 'tiktok', 'character_tag': target_tag}, project_data)]

    if any(k in lower for k in ['flow prompt', 'nano banana', 'prompt', 'storyboard prompt']) or (matched_tag and 'prompt' in lower):
        mood = 'in a recording booth at 4AM'
        if 'dim' in lower or 'dark' in lower:
            mood = 'dim recording booth with purple ambient lighting'
        elif 'rain' in lower or 'window' in lower:
            mood = 'looking through rain-streaked studio glass at city night lights'
        elif 'stage' in lower or 'live' in lower:
            mood = 'on stage under energetic violet spotlights with subtle stage haze'
        return [execute_tool('generate_flow_prompt', {'character_tag': target_tag, 'scene_mood': mood}, project_data)]

    return []


def build_system_prompt(project_data=None):
    char_list = characters.list_characters()
    chars_text = ', '.join(f"{c['name']} ({c['tag']})" for c in char_list) if char_list else '@Airi'

    project_summary = "No project opened."
    cues_summary = ""
    if project_data:
        cues = project_data.get('cues', [])
        style = project_data.get('style', {})
        lang = style.get('translation_language', 'en')
        project_summary = (
            f"Active Project: '{project_data.get('title','Untitled')}', {len(cues)} lyric lines, "
            f"duration {project_data.get('duration',0):.1f}s, font '{style.get('font','Impact')}', "
            f"display mode '{style.get('track_mode','original')}', translation language '{lang}'."
        )
        if cues:
            cue_samples = []
            for i, c in enumerate(cues[:15]):
                t = c.get('text', '')
                tr = c.get('translations', {}).get(lang, {}).get('text', '') if isinstance(c.get('translations'), dict) else ''
                cue_samples.append(f"Line {i+1}: \"{t}\"" + (f" -> ({lang}): \"{tr}\"" if tr else ""))
            cues_summary = "\nCurrent Project Lines:\n" + "\n".join(cue_samples)

    return (
        "You are the AI Influencer Studio Copilot, an expert AI assistant and creative producer for music videos, "
        "lyric captions, and AI influencers.\n"
        f"Available Characters: {chars_text}.\n"
        f"Current Workspace State: {project_summary}\n"
        f"{cues_summary}\n\n"
        "Capabilities & Responsibilities:\n"
        "- Subtitle & Translation Editing: When asked to fix, refine, or translate any subtitle line, invoke `fix_translation` or `rephrase_translation_options`.\n"
        "- Original Lyric Editing: If the user points out a typo or wording change in the original text, invoke `edit_subtitle_text`.\n"
        "- Subtitle Audits: When asked to check for reading speed (CPS) or missing translations, invoke `audit_subtitles`.\n"
        "- App Navigation: When asked to switch tabs, show AI Studio assets, or go to Downloader/Gallery, invoke `navigate_app`.\n"
        "- File Explorer: When asked to open downloads or files, invoke `open_downloads_folder`.\n"
        "- Visual Caption Presets: Suggest and apply caption presets (mrbeast_bold, cyberpunk_neon, frosted_vlog, sunset_glow, neon_karaoke).\n"
        "- Typography: Invoke `change_font_family` when asked to change fonts.\n"
        "- Google Flow & Nano Banana Prompts: Craft 8K visual prompts for characters like @Airi.\n"
        "- Social Media: Generate viral hooks and captions on export.\n\n"
        "Tone: Pro-Apple creative software standard—concise, encouraging, clear, and action-oriented. "
        "When a user asks you to change, translate, or do something in the app, always invoke the corresponding tool."
    )


def chat(messages, model='qwen2.5:14b', project_data=None):
    """Processes user message, executes any triggered tools, and returns response."""
    last_user_text = ''
    for m in reversed(messages):
        if m.get('role') == 'user':
            last_user_text = m.get('content', '')
            break

    fallback_actions = detect_fallback_intent(last_user_text, project_data)
    kb_reply, kb_actions = answer_from_knowledge_base(last_user_text)

    executed_actions = list(fallback_actions)
    for act in kb_actions:
        if not any(a.get('action') == act.get('action') for a in executed_actions):
            executed_actions.append(act)

    system = build_system_prompt(project_data)
    convo = [dict(role='system', content=system)] + messages

    available = [m['id'] for m in available_models()]

    # Offline / Zero-dependency fallback
    if model == 'offline' or not available:
        reply_msg = kb_reply
        if not reply_msg:
            reply_msg = " ".join(a.get('message', '') for a in executed_actions) if executed_actions else (
                "👋 I am your AI Influencer Studio Copilot. How can I help with your video, character prompts, captions, or social media today?"
            )
        return {
            "reply": reply_msg,
            "actions": executed_actions,
            "model": "offline"
        }

    if model not in available and available:
        model = available[0]

    if model == 'qwen3-4b-local':
        try:
            reply = lyric_translation.local_chat(convo, schema=None, max_tokens=1000) if hasattr(lyric_translation, 'local_chat') else ""
        except Exception:
            reply = ""
        if executed_actions and not reply:
            reply = kb_reply or " ".join(a.get('message', '') for a in executed_actions)
        return {
            "reply": reply or kb_reply or "Local assistant ready! How can I help with your video or captions today?",
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
            if not any(a.get('action') == fname for a in executed_actions):
                act_res = execute_tool(fname, fargs, project_data)
                executed_actions.append(act_res)

        if not content and executed_actions:
            content = " ".join(a.get('message', '') for a in executed_actions)

        return {
            "reply": content or kb_reply or "I am ready to help you with your video and captions!",
            "actions": executed_actions,
            "model": model
        }

    except Exception:
        reply_msg = kb_reply or (" ".join(a.get('message', '') for a in executed_actions) if executed_actions else "Copilot active. Ready to help with your video, @Airi prompts, or captions.")
        return {
            "reply": reply_msg,
            "actions": executed_actions,
            "model": model
        }
