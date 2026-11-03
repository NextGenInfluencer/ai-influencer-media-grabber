"""Performance and face tools for AI Studio: references, face swap, lip-sync, portrait animation.

Inputs are the user's own media inside the Media Grabber folder (reference frames,
driving videos, caption-project audio). Generative work is delegated to
``ai_core`` and is real or raises an honest ``AIUnavailable``:

* Face Swap (image / video) → ``ai_core.face`` (InSwapper + optional GFPGAN)
* Lip-sync → LatentSync workflow; portrait animation → LivePortrait workflow
* Opt-in cloud (never an implicit fallback): Kling motion control and LivePortrait on
  fal.ai, Nano Banana identity edit on Gemini.
"""
import os
import re
import shutil
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

import imageio_ffmpeg

import characters
import job_process as subprocess
from ai_core import cloud, comfy, face
from ai_core.errors import AIUnavailable

DATA_DIR = Path(os.environ.get('MEDIA_GRABBER_DATA_DIR') or Path.home() / 'Documents' / 'Media Grabber')
REFERENCES_DIR = DATA_DIR / 'References'
MOTION_OUTPUT_DIR = DATA_DIR / 'Motion Outputs'
DRIVING_REF_DIR = DATA_DIR / 'Driving References'

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.webm', '.mkv'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac'}
AUDIO_MODES = ('original', 'mute', 'project')
_PROJECT_ID = re.compile(r'[a-f0-9]{32}')


def _ffmpeg():
    return imageio_ffmpeg.get_ffmpeg_exe()


def _ensure_dirs():
    for folder in (REFERENCES_DIR, MOTION_OUTPUT_DIR, DRIVING_REF_DIR):
        folder.mkdir(parents=True, exist_ok=True)


def _contained(path, base):
    """The resolved path if it is a file strictly inside ``base``."""
    try:
        resolved = Path(path).resolve()
        base_resolved = Path(base).resolve()
    except (OSError, ValueError):
        return None
    if base_resolved in resolved.parents and resolved.is_file():
        return resolved
    return None


def resolve_media_source(source):
    """Map an in-app media URL or a data-folder path to a local file, or None.

    Supported: ``/api/media/<relative path>``, ``/api/captions/<id>/media/<name>``,
    ``/api/motion/references/file/<name>``, ``/api/characters/<id>/image/<name>``,
    ``/api/video-studio/(images|videos)/file/<name>`` and paths inside the data folder.
    Anything else returns None; callers may additionally accept absolute paths that
    pass the app's allowed-path check.
    """
    if not source or not isinstance(source, str):
        return None
    path_part = unquote(urlsplit(source).path)
    if path_part.startswith('/api/media/'):
        return _contained(DATA_DIR / path_part[len('/api/media/'):], DATA_DIR)
    match = re.fullmatch(r'/api/captions/([^/]+)/media/([^/]+)', path_part)
    if match:
        if not _PROJECT_ID.fullmatch(match.group(1)):
            return None
        return _contained(DATA_DIR / 'Caption Projects' / match.group(1) / Path(match.group(2)).name, DATA_DIR)
    match = re.fullmatch(r'/api/characters/([^/]+)/image/([^/]+)', path_part)
    if match:
        return characters.get_image_path(match.group(1), match.group(2))
    folders = {'/api/motion/references/file/': REFERENCES_DIR, '/api/motion/outputs/file/': MOTION_OUTPUT_DIR,
               '/api/video-studio/images/file/': DATA_DIR / 'Storyboard Images',
               '/api/video-studio/videos/file/': DATA_DIR / 'Storyboard Videos'}
    for prefix, folder in folders.items():
        if path_part.startswith(prefix):
            return _contained(folder / Path(path_part[len(prefix):]).name, folder)
    if path_part.startswith('/api/'):
        return None
    candidate = Path(source)
    if not candidate.is_absolute():
        for base in (DATA_DIR, REFERENCES_DIR, DRIVING_REF_DIR):
            found = _contained(base / candidate, DATA_DIR)
            if found:
                return found
        return None
    return _contained(candidate, DATA_DIR)


def resolve_image_path(source):
    """Image variant of :func:`resolve_media_source` (also accepts a bare reference file name)."""
    found = resolve_media_source(source)
    if found is None and isinstance(source, str) and source:
        found = _contained(REFERENCES_DIR / Path(source).name, REFERENCES_DIR)
    return found if found is not None and found.suffix.lower() in IMAGE_EXTENSIONS else None


def extract_reference_frame(video_source, timestamp_sec=0.0, output_name=None):
    """Extract a lossless PNG frame at ``timestamp_sec`` into the References folder."""
    _ensure_dirs()
    video = resolve_media_source(video_source)
    if not video:
        raise FileNotFoundError(f'Video not found in the Media Grabber folder: {video_source}')
    timestamp_sec = max(0.0, float(timestamp_sec))
    stem = re.sub(r'[^\w\-]', '_', video.stem)
    name = Path(output_name).name if output_name else f'ref_{stem}_{int(timestamp_sec * 100)}_{uuid.uuid4().hex[:6]}.png'
    out_path = REFERENCES_DIR / name
    attempts = (  # fast input seek first; accurate output seek for odd containers
        [_ffmpeg(), '-nostdin', '-y', '-ss', f'{timestamp_sec:.3f}', '-i', str(video), '-frames:v', '1', str(out_path)],
        [_ffmpeg(), '-nostdin', '-y', '-i', str(video), '-ss', f'{timestamp_sec:.3f}', '-frames:v', '1', str(out_path)],
    )
    last_error = ''
    for command in attempts:
        result = subprocess.run(command, capture_output=True)
        if result.returncode == 0 and out_path.is_file():
            break
        last_error = (result.stderr or b'').decode('utf-8', errors='ignore')[-300:]
    else:
        raise RuntimeError(f'Frame extraction failed: {last_error}')
    return {'filename': out_path.name, 'path': str(out_path), 'url': f'/api/motion/references/file/{out_path.name}',
            'timestamp': timestamp_sec, 'size_bytes': out_path.stat().st_size}


def list_references():
    _ensure_dirs()
    files = sorted((p for p in REFERENCES_DIR.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return [{'name': f.name, 'path': str(f), 'url': f'/api/motion/references/file/{f.name}', 'size': f.stat().st_size,
             'modified': f.stat().st_mtime} for f in files]


def list_driving_videos():
    """Candidate driving / target videos from the Media Grabber folder."""
    _ensure_dirs()
    candidates, seen = [], set()
    for folder in (DRIVING_REF_DIR, DATA_DIR / 'Conversions', DATA_DIR):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS or path.name.startswith('.'):
                continue
            if path.name in seen:
                continue
            seen.add(path.name)
            candidates.append({'name': path.name, 'filename': path.name, 'path': str(path),
                               'size_mb': round(path.stat().st_size / (1024 * 1024), 1), 'modified': path.stat().st_mtime})
    return candidates


def _safe_upload_name(name, allowed, default_ext):
    clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', Path(name or '').name) or 'upload'
    return clean if Path(clean).suffix.lower() in allowed else clean + default_ext


def save_uploaded_driving_video(file_obj, filename=None):
    _ensure_dirs()
    name = _safe_upload_name(filename or getattr(file_obj, 'filename', ''), VIDEO_EXTENSIONS, '.mp4')
    target = DRIVING_REF_DIR / f'drive_{uuid.uuid4().hex[:6]}_{name}'
    file_obj.save(str(target))
    return {'name': target.name, 'filename': target.name, 'path': str(target),
            'size_mb': round(target.stat().st_size / (1024 * 1024), 1)}


def save_uploaded_swapped_frame(file_storage):
    """Store a user-provided reference image (e.g. an edit made in another tool)."""
    _ensure_dirs()
    ext = Path(file_storage.filename or '').suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValueError('Choose a PNG, JPG or WebP image.')
    target = REFERENCES_DIR / f'custom_swapped_{uuid.uuid4().hex[:8]}{ext}'
    file_storage.save(str(target))
    return {'success': True, 'filename': target.name, 'path': str(target),
            'url': f'/api/motion/references/file/{target.name}'}


def identity_edit_prompt(char):
    """Instruction for an identity edit of a reference frame (Nano Banana / FLUX Kontext)."""
    name = (char or {}).get('name') or 'the reference person'
    return (f'Edit Image 1, the first frame of a motion-reference video. Use Image 2 only as the identity reference '
            f'for {name}. Replace the main foreground person\'s face, facial features, skin tone and hair with that '
            'identity, adapted to the original head angle, expression, gaze and lighting. Preserve Image 1\'s pose, '
            'body placement, clothing, background and lighting. Return one edited image.')


# ---------------------------------------------------------------- outputs and audio

def _output(prefix, suffix):
    _ensure_dirs()
    return MOTION_OUTPUT_DIR / f'{prefix}_{uuid.uuid4().hex[:10]}{suffix}'


def _result(path, **extra):
    path = Path(path)
    return {'path': str(path), 'filename': path.name, 'url': f'/api/motion/outputs/file/{path.name}', **extra}


def apply_audio(video, *, mode='original', audio=None):
    """Return a video with its soundtrack kept, removed (mute) or replaced by ``audio``."""
    if mode not in AUDIO_MODES:
        raise ValueError('Choose original, mute or project audio.')
    video = Path(video)
    if mode == 'original':
        return video
    if mode == 'project' and (audio is None or not Path(audio).is_file()):
        raise FileNotFoundError('The project audio file is missing.')
    target = video.with_name(f'{video.stem}_{mode}{video.suffix}')
    command = [_ffmpeg(), '-nostdin', '-y', '-i', str(video)]
    if mode == 'mute':
        command += ['-map', '0:v:0', '-c:v', 'copy', '-an']
    else:
        command += ['-i', str(audio), '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k',
                    '-shortest']
    result = subprocess.run([*command, '-movflags', '+faststart', str(target)], capture_output=True)
    if result.returncode != 0 or not target.is_file():
        target.unlink(missing_ok=True)
        raise RuntimeError('Could not set the video audio: ' + (result.stderr or b'').decode('utf-8', 'ignore')[-300:])
    video.unlink(missing_ok=True)
    return target


# ---------------------------------------------------------------- local AI

def face_swap_image(target, source, *, restore=True):
    output = _output('swap', '.png')
    info = face.swap_image(str(target), str(source), str(output), restore=restore)
    return _result(output, provider=info.get('provider'), restored=info.get('restored'), ai=True, local=True)


def face_swap_video(video, source, *, restore=True, audio_mode='original', audio=None, progress=None):
    output = _output('motion_swap', '.mp4')
    info = face.swap_video(str(video), str(source), str(output), restore=restore, progress=progress)
    final = apply_audio(output, mode=audio_mode, audio=audio)
    return _result(final, provider=info.get('provider'), ai=True, local=True)


def _single_video(outputs):
    for path in outputs:
        if Path(path).suffix.lower() in VIDEO_EXTENSIONS:
            return Path(path)
    raise AIUnavailable('The creative engine finished without a video file.')


def lip_sync(video, audio, *, progress=None):
    outputs = comfy.run_workflow('latentsync', {'video': str(video), 'audio': str(audio)}, progress=progress)
    target = _output('motion_lipsync', '.mp4')
    shutil.move(str(_single_video(outputs)), str(target))
    return _result(target, workflow='latentsync', ai=True, local=True)


def live_portrait(image, video, *, audio_mode='original', audio=None, progress=None):
    outputs = comfy.run_workflow('liveportrait', {'image': str(image), 'video': str(video)}, progress=progress)
    target = _output('motion_liveportrait', '.mp4')
    shutil.move(str(_single_video(outputs)), str(target))
    final = apply_audio(target, mode=audio_mode, audio=audio)
    return _result(final, workflow='liveportrait', ai=True, local=True)


# ---------------------------------------------------------------- opt-in cloud

def cloud_motion(image, video, *, prompt='', orientation='video', keep_sound=True, pro=False):
    """Kling motion control on fal.ai (paid, user's key). Raises AIUnavailable when not enabled."""
    info = cloud.kling_motion_control(str(image), str(video), prompt=prompt, character_orientation=orientation,
                                      keep_original_sound=keep_sound, pro=pro)
    target = cloud.download_result(info['video_url'], _output('motion_kling', '.mp4'))
    return _result(target, provider='fal', endpoint=info.get('endpoint'), ai=True, local=False)


def cloud_live_portrait(image, video):
    info = cloud.live_portrait(str(image), str(video))
    target = cloud.download_result(info['video_url'], _output('motion_liveportrait_cloud', '.mp4'))
    return _result(target, provider='fal', endpoint=info.get('endpoint'), ai=True, local=False)


def cloud_identity_edit(target, reference, *, prompt=None, character_id=None):
    """Nano Banana (Gemini) identity edit of a reference frame (paid, user's key)."""
    char = characters.get_character(character_id) if character_id else characters.get_active_character()
    outputs = cloud.nano_banana_edit([str(target), str(reference)], prompt or identity_edit_prompt(char))
    final = REFERENCES_DIR / f'identity_{uuid.uuid4().hex[:8]}{Path(outputs[0]).suffix}'
    _ensure_dirs()
    shutil.move(str(outputs[0]), str(final))
    return {'path': str(final), 'filename': final.name, 'url': f'/api/motion/references/file/{final.name}',
            'provider': 'gemini', 'ai': True, 'local': False}
