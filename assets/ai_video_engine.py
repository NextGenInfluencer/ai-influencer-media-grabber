"""AI Studio generation services: Director storyboards, keyframes and image-to-video.

Everything here is real model output or an honest error:

* the Director is the local helper LLM (``ai_core.llm``) constrained by a JSON
  schema and fed with real caption timings and audio energy onsets;
* keyframes run FLUX.1 schnell (text-to-image) or FLUX.1 Kontext (identity edit of
  the persona portrait) through the pinned ComfyUI workflows;
* animation runs Wan 2.2 TI2V 5B (fast default) or Wan 2.1 I2V 14B Q4 (quality).

When a model or engine is missing, ``ai_core`` raises ``AIUnavailable`` /
``ModelMissing`` with a ``setup_hint`` and nothing is produced. The only non-AI
output is the camera-motion preview, which is always labelled "Preview (no AI)".
"""
import json
import os
import shutil
import uuid
from pathlib import Path

import imageio_ffmpeg

import characters
import job_process as process
from ai_core import catalog, comfy, llm
from ai_core.errors import AIUnavailable

DATA_DIR = Path(os.environ.get('MEDIA_GRABBER_DATA_DIR') or Path.home() / 'Documents' / 'Media Grabber')
STORYBOARD_IMG_DIR = DATA_DIR / 'Storyboard Images'
STORYBOARD_VID_DIR = DATA_DIR / 'Storyboard Videos'

MAX_SCENES = 60
MIN_SCENE_SECONDS = 0.5
SNAP_SECONDS = 0.35
PROMPT_BUDGET_CHARS = 12000
PREVIEW_LABEL = 'Preview (no AI)'

KEYFRAME_WORKFLOWS = {'text': 'flux_schnell_t2i', 'identity': 'flux_kontext_edit'}
ANIMATE_WORKFLOWS = {
    'fast': {'workflow': 'wan22_ti2v_5b', 'fps': 24, 'max_frames': 121},
    'quality': {'workflow': 'wan21_i2v_14b_gguf', 'fps': 16, 'max_frames': 81},
}
CAMERA_PREVIEWS = {
    'push_in': "z='min(zoom+0.0015,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    'pull_out': "z='if(eq(on,0),1.25,max(zoom-0.0015,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    'pan_left': "z=1.15:x='max(0,(iw-iw/zoom)*(1-on/{frames}))':y='ih/2-(ih/zoom/2)'",
    'pan_right': "z=1.15:x='(iw-iw/zoom)*on/{frames}':y='ih/2-(ih/zoom/2)'",
}

STORYBOARD_SCHEMA = {
    'type': 'object',
    'properties': {
        'title': {'type': 'string'},
        'scenes': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'start': {'type': 'number'}, 'end': {'type': 'number'}, 'lyric': {'type': 'string'},
            'image_prompt': {'type': 'string'}, 'motion_prompt': {'type': 'string'},
            'camera': {'type': 'string'}, 'use_character': {'type': 'boolean'}},
            'required': ['start', 'end', 'image_prompt', 'motion_prompt', 'camera', 'use_character']}},
    },
    'required': ['scenes'],
}
CONCEPTS_SCHEMA = {
    'type': 'object',
    'properties': {
        'analysis': {'type': 'string'},
        'concepts': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'name': {'type': 'string'}, 'palette': {'type': 'array', 'items': {'type': 'string'}},
            'prompt_atmosphere': {'type': 'string'}, 'camera': {'type': 'string'}, 'why': {'type': 'string'}},
            'required': ['name', 'palette', 'prompt_atmosphere', 'camera', 'why']}},
    },
    'required': ['analysis', 'concepts'],
}


def _ensure_dirs():
    STORYBOARD_IMG_DIR.mkdir(parents=True, exist_ok=True)
    STORYBOARD_VID_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- persona helpers

def persona(character_id=None):
    """The requested (or active) character profile, or None."""
    return characters.get_character(character_id) if character_id else characters.get_active_character()


def persona_summary(char):
    if not char:
        return ''
    parts = [char.get('tag') or char.get('name') or '', char.get('trigger_prompt') or '']
    return ', '.join(p.strip() for p in parts if p and p.strip())[:600]


# ---------------------------------------------------------------- audio analysis

def beat_onsets(peaks, duration, *, min_gap=0.25, limit=400):
    """Energy-onset times (seconds) from the project's stored audio peak envelope.

    This is signal analysis (positive energy flux with local-maximum picking), used
    only to snap scene cuts; it is never presented as AI output.
    """
    import numpy as np
    envelope = np.asarray([p for p in (peaks or []) if isinstance(p, (int, float))], dtype=float)
    if envelope.size < 8 or not duration or duration <= 0:
        return []
    step = float(duration) / envelope.size
    width = max(1, int(round(0.05 / step)))
    smooth = np.convolve(envelope, np.ones(width) / width, mode='same')
    flux = np.maximum(0.0, np.diff(smooth, prepend=smooth[0]))
    if not flux.any():
        return []
    threshold = flux.mean() + flux.std()
    gap = max(1, int(round(min_gap / step)))
    onsets, last = [], -gap
    for i in range(1, flux.size - 1):
        if flux[i] >= threshold and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1] and i - last >= gap:
            onsets.append(round(i * step, 2))
            last = i
            if len(onsets) >= limit:
                break
    return onsets


# ---------------------------------------------------------------- Director (LLM)

def _cue_lines(cues):
    """Timed lyric lines for the prompt, merged in groups when they exceed the context budget."""
    clean = []
    for cue in cues or []:
        if not isinstance(cue, dict):
            continue
        try:
            start, end = float(cue.get('start', 0)), float(cue.get('end', 0))
        except (TypeError, ValueError):
            continue
        clean.append((start, end, ' '.join(str(cue.get('text') or '').split())[:160]))
    group = 1
    while True:
        lines = []
        for i in range(0, len(clean), group):
            chunk = clean[i:i + group]
            lines.append(f'[{chunk[0][0]:.2f}-{chunk[-1][1]:.2f}] ' + ' / '.join(c[2] for c in chunk if c[2]))
        text = '\n'.join(lines)
        if len(text) <= PROMPT_BUDGET_CHARS or group >= len(clean):
            return text
        group *= 2


def _anchors(cues, onsets):
    points = set(onsets or [])
    for cue in cues or []:
        if isinstance(cue, dict):
            for key in ('start', 'end'):
                try:
                    points.add(round(float(cue.get(key)), 2))
                except (TypeError, ValueError):
                    pass
    return sorted(points)


def _snap(value, anchors):
    if not anchors:
        return value
    nearest = min(anchors, key=lambda a: abs(a - value))
    return nearest if abs(nearest - value) <= SNAP_SECONDS else value


def normalize_scenes(raw_scenes, duration, anchors=()):
    """Validate LLM scenes: sorted, clamped to the song, snapped to cuts, contiguous, no slivers."""
    scenes = []
    for raw in raw_scenes or []:
        if not isinstance(raw, dict):
            continue
        try:
            start, end = float(raw.get('start', 0)), float(raw.get('end', 0))
        except (TypeError, ValueError):
            continue
        prompt = str(raw.get('image_prompt') or '').strip()
        if not prompt or end <= start:
            continue
        scenes.append({'start': start, 'end': end, 'lyric': str(raw.get('lyric') or '').strip()[:300],
                       'image_prompt': prompt[:1500], 'motion_prompt': str(raw.get('motion_prompt') or '').strip()[:800],
                       'camera': str(raw.get('camera') or '').strip()[:120],
                       'use_character': raw.get('use_character') is not False})
    scenes.sort(key=lambda s: s['start'])
    result = []
    for scene in scenes[:MAX_SCENES]:
        start = max(0.0, min(duration, _snap(scene['start'], anchors)))
        end = max(0.0, min(duration, _snap(scene['end'], anchors)))
        if result:
            start = result[-1]['end']
        if end - start < MIN_SCENE_SECONDS:
            continue
        result.append({**scene, 'start': round(start, 2), 'end': round(end, 2)})
    for number, scene in enumerate(result, 1):
        scene.update(number=number, id=f'scene_{number:03d}', duration=round(scene['end'] - scene['start'], 2),
                     status='draft', image_path='', video_path='')
    return result


def direct_storyboard(*, cues=None, duration=0.0, peaks=None, concept='', mood='', character_id=None,
                      num_scenes=None):
    """Plan a storyboard with the local helper model. Raises AIUnavailable; never templates."""
    duration = float(duration or 0)
    if duration <= 0:
        raise ValueError('Choose a song project or set a duration for the storyboard.')
    if not cues and not concept.strip():
        raise ValueError('Describe the video concept, or pick a captions project with lyrics.')
    onsets = beat_onsets(peaks, duration)
    char = persona(character_id)
    target = int(num_scenes) if num_scenes else max(2, min(24, round(duration / 5)))
    target = max(1, min(MAX_SCENES, target))
    sections = [
        f'Song duration: {duration:.2f} s. Target about {target} scenes (each 2-8 s; local video models make ~5 s clips).',
        f'Concept: {concept.strip()[:1000] or "(derive it from the lyrics)"}',
        f'Mood / look: {mood.strip()[:500] or "(choose one that fits)"}',
        f'Creator persona: {persona_summary(char) or "(none; describe people generically)"}',
    ]
    if cues:
        sections.append('Timed lyric lines (seconds):\n' + _cue_lines(cues))
    if onsets:
        sections.append('Audio energy onsets (good cut points, seconds): ' + ', '.join(f'{t:.2f}' for t in onsets[:200]))
    system = ('You are a music-video director. Plan contiguous scenes that cover the whole song from 0 to its '
              'duration. Cut on lyric line boundaries or energy onsets. For each scene write a concrete still-image '
              'prompt (subject, setting, lighting, lens), a short motion prompt for an image-to-video model, a camera '
              'move, and set use_character=false for scenes without the persona. Copy the lyric sung in that scene '
              'verbatim. Answer only with JSON matching the schema.')
    answer = llm.chat('helper', [{'role': 'system', 'content': system}, {'role': 'user', 'content': '\n\n'.join(sections)}],
                      schema=STORYBOARD_SCHEMA, max_tokens=4096, temperature=0.4)
    data = json.loads(answer['content'])
    scenes = normalize_scenes(data.get('scenes'), duration, _anchors(cues, onsets))
    if not scenes:
        raise AIUnavailable('The local model did not return a usable storyboard. Nothing was changed. Try again or '
                            'choose a larger helper model in AI Setup.', setup_hint='ai_setup')
    return {'title': str(data.get('title') or '')[:200], 'scenes': scenes, 'model': answer['model'],
            'backend': answer['backend'], 'beats': len(onsets), 'local': True}


def suggest_concepts(*, lyrics='', song_title='', concept='', character_id=None):
    """Visual concept options for a song from the helper model (JSON schema)."""
    if not (lyrics.strip() or song_title.strip() or concept.strip()):
        raise ValueError('Add lyrics, a song title or a concept first.')
    char = persona(character_id)
    prompt = (f'Song title: {song_title.strip()[:200]}\nConcept notes: {concept.strip()[:800]}\n'
              f'Persona: {persona_summary(char) or "(none)"}\nLyrics:\n{lyrics.strip()[:PROMPT_BUDGET_CHARS]}\n\n'
              'Give a two-sentence analysis of the song\'s emotional arc, then four distinct visual concepts. '
              'Each palette lists five hex colours.')
    answer = llm.chat('helper', [{'role': 'user', 'content': prompt}], schema=CONCEPTS_SCHEMA, max_tokens=1500)
    data = json.loads(answer['content'])
    concepts = [c for c in data.get('concepts', []) if isinstance(c, dict) and c.get('name')][:6]
    if not concepts:
        raise AIUnavailable('The local model returned no concepts. Nothing was changed.', setup_hint='ai_setup')
    return {'analysis': str(data.get('analysis') or ''), 'concepts': concepts, 'model': answer['model'], 'local': True}


def director_chat(message, *, lyrics='', character_id=None):
    """Free-form creative direction from the helper model."""
    if not str(message or '').strip():
        raise ValueError('Type a question for the Director.')
    char = persona(character_id)
    system = ('You are a concise music-video director helping a creator. Give concrete, filmable advice: '
              'setting, lighting, wardrobe, camera and pacing. Never claim to have generated images or video.')
    context = f'Persona: {persona_summary(char) or "(none)"}\nLyrics excerpt:\n{str(lyrics)[:4000]}'
    answer = llm.chat('helper', [{'role': 'system', 'content': system}, {'role': 'user', 'content': context},
                                 {'role': 'user', 'content': str(message)[:2000]}], max_tokens=700)
    return {'reply': answer['content'], 'model': answer['model'], 'local': True}


# ---------------------------------------------------------------- generation

def workflow_cost(name):
    """Cost chip data for a pinned workflow: local, VRAM, ETA and missing requirements."""
    meta = catalog.workflow(name)
    required = [catalog.get(i) for i in meta.get('requires', [])]
    return {'workflow': name, 'local': True,
            'vram_gb': max([item.get('vram_gb') or 0 for item in required] or [0]),
            'ram_gb': max([item.get('ram_gb') or 0 for item in required] or [0]),
            'eta_seconds': max([item.get('eta_seconds') or 0 for item in required] or [0]) or None,
            'models': [item['name'] for item in required]}


def _move_output(source, folder, stem):
    _ensure_dirs()
    source = Path(source)
    target = folder / f'{stem}_{uuid.uuid4().hex[:8]}{source.suffix.lower()}'
    shutil.move(str(source), str(target))
    return target


def _first(paths, suffixes):
    for path in paths:
        if Path(path).suffix.lower() in suffixes:
            return Path(path)
    raise AIUnavailable('The creative engine finished without the expected output file.')


def render_keyframe(prompt, *, character_id=None, use_character=True, reference=None, scene_number=1, seed=0,
                    width=768, height=1344, progress=None):
    """FLUX keyframe. With a reference (or persona portrait) FLUX Kontext keeps the identity."""
    prompt = str(prompt or '').strip()
    if not prompt:
        raise ValueError('Write a prompt for the keyframe.')
    char = persona(character_id) if use_character else None
    source = Path(reference) if reference else (characters.portrait_path(char) if char else None)
    if source is not None and not source.is_file():
        raise FileNotFoundError('The reference image is missing.')
    if source is not None:
        name = KEYFRAME_WORKFLOWS['identity']
        inputs = {'image': str(source), 'prompt': f'{prompt}. Keep the same person, face and identity.', 'seed': seed}
    else:
        name = KEYFRAME_WORKFLOWS['text']
        identity = persona_summary(char)
        inputs = {'prompt': f'{identity}, {prompt}' if identity else prompt, 'seed': seed,
                  'width': int(width), 'height': int(height)}
    outputs = comfy.run_workflow(name, inputs, progress=progress)
    image = _move_output(_first(outputs, {'.png', '.jpg', '.jpeg', '.webp'}), STORYBOARD_IMG_DIR,
                         f'keyframe_scene_{int(scene_number)}')
    return {'path': str(image), 'filename': image.name, 'url': f'/api/video-studio/images/file/{image.name}',
            'workflow': name, 'identity_reference': source is not None, 'ai': True, 'local': True}


def frames_for(duration, quality='fast'):
    spec = ANIMATE_WORKFLOWS[quality]
    frames = int(round(float(duration) * spec['fps'] / 4)) * 4 + 1
    return max(17, min(spec['max_frames'], frames))


def animate_keyframe(image, prompt, *, quality='fast', duration=5.0, scene_number=1, seed=0, progress=None):
    """Wan image-to-video. 'fast' = Wan 2.2 5B (default), 'quality' = Wan 2.1 14B Q4 (slow)."""
    if quality not in ANIMATE_WORKFLOWS:
        raise ValueError('Choose fast or quality animation.')
    image = Path(image)
    if not image.is_file():
        raise FileNotFoundError('Render or choose a keyframe image first.')
    spec = ANIMATE_WORKFLOWS[quality]
    inputs = {'image': str(image), 'prompt': str(prompt or 'subtle natural motion, cinematic').strip()[:800],
              'length': frames_for(duration, quality), 'seed': seed}
    outputs = comfy.run_workflow(spec['workflow'], inputs, progress=progress)
    video = _move_output(_first(outputs, {'.mp4', '.webm', '.mov'}), STORYBOARD_VID_DIR, f'video_scene_{int(scene_number)}')
    return {'path': str(video), 'filename': video.name, 'url': f'/api/video-studio/videos/file/{video.name}',
            'workflow': spec['workflow'], 'frames': inputs['length'], 'fps': spec['fps'], 'ai': True, 'local': True}


def camera_preview(image, *, motion='push_in', duration=4.0, scene_number=1):
    """Camera-move preview of a still with FFmpeg zoompan. Explicitly NOT AI output."""
    if motion not in CAMERA_PREVIEWS:
        raise ValueError('Choose push in, pull out, pan left or pan right.')
    image = Path(image)
    if not image.is_file():
        raise FileNotFoundError('Choose a keyframe image first.')
    duration = max(1.0, min(15.0, float(duration)))
    fps, frames = 30, int(duration * 30)
    _ensure_dirs()
    target = STORYBOARD_VID_DIR / f'preview_scene_{int(scene_number)}_{uuid.uuid4().hex[:8]}.mp4'
    zoom = CAMERA_PREVIEWS[motion].format(frames=frames)
    graph = (f'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,'
             f'zoompan={zoom}:d={frames}:s=1080x1920:fps={fps},format=yuv420p')
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-y', '-loop', '1', '-i', str(image), '-t', f'{duration:.2f}',
               '-vf', graph, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', str(target)]
    result = process.run(command, capture_output=True)
    if result.returncode != 0 or not target.is_file():
        target.unlink(missing_ok=True)
        raise RuntimeError('The preview could not be rendered: ' + result.stderr.decode('utf-8', 'ignore')[-300:])
    return {'path': str(target), 'filename': target.name, 'url': f'/api/video-studio/videos/file/{target.name}',
            'ai': False, 'label': PREVIEW_LABEL, 'local': True}
