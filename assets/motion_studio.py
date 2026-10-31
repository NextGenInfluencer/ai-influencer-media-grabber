"""Reference frame snapper and (placeholder) motion studio.

Extracts lossless PNG reference keyframes from the user's own media.
Only files inside the Media Grabber data folder can be read, addressed either by
an in-app media URL or by a path inside that folder.

``render_character_motion`` is a placeholder: it produces a still-image clip of the
character portrait. Real face/performance transfer is not implemented yet.
"""
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit
import uuid

import imageio_ffmpeg

import characters

DATA_DIR = Path(os.environ.get('MEDIA_GRABBER_DATA_DIR') or Path.home() / 'Documents' / 'Media Grabber')
REFERENCES_DIR = DATA_DIR / 'References'
MOTION_OUTPUT_DIR = DATA_DIR / 'Motion Outputs'

_PROJECT_ID = re.compile(r'[a-f0-9]{32}')
_FFMPEG_EXE = None


def _ffmpeg():
    global _FFMPEG_EXE
    if _FFMPEG_EXE is None:
        try:
            _FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            _FFMPEG_EXE = 'ffmpeg'
    return _FFMPEG_EXE


def _ensure_dirs():
    REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
    MOTION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _contained(path, base):
    """Return the resolved path if it is a file strictly inside ``base``."""
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
    absolute paths inside the data folder, and paths relative to it.
    """
    if not source or not isinstance(source, str):
        return None
    path_part = unquote(urlsplit(source).path)

    if path_part.startswith('/api/media/'):
        return _contained(DATA_DIR / path_part[len('/api/media/'):], DATA_DIR)

    m = re.fullmatch(r'/api/captions/([^/]+)/media/([^/]+)', path_part)
    if m:
        pid, name = m.group(1), Path(m.group(2)).name
        if not _PROJECT_ID.fullmatch(pid):
            return None
        return _contained(DATA_DIR / 'Caption Projects' / pid / name, DATA_DIR)

    if path_part.startswith('/api/'):
        return None
    candidate = Path(source)
    if not candidate.is_absolute():
        candidate = DATA_DIR / candidate
    return _contained(candidate, DATA_DIR)


def extract_reference_frame(video_source, timestamp_sec=0.0, output_name=None):
    """Extract a lossless PNG frame at ``timestamp_sec`` into the References folder."""
    _ensure_dirs()
    vpath = resolve_media_source(video_source)
    if not vpath:
        raise FileNotFoundError(f"Video not found in the Media Grabber folder: {video_source}")

    timestamp_sec = max(0.0, float(timestamp_sec))
    fname = Path(output_name).name if output_name else f"ref_{vpath.stem}_{int(timestamp_sec * 100)}_{uuid.uuid4().hex[:6]}.png"
    out_path = REFERENCES_DIR / fname

    # Fast input seek first; fall back to accurate output seek for odd containers.
    attempts = (
        [_ffmpeg(), '-nostdin', '-y', '-ss', f"{timestamp_sec:.3f}", '-i', str(vpath), '-frames:v', '1', str(out_path)],
        [_ffmpeg(), '-nostdin', '-y', '-i', str(vpath), '-ss', f"{timestamp_sec:.3f}", '-frames:v', '1', str(out_path)],
    )
    last_error = ''
    for cmd in attempts:
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode == 0 and out_path.is_file():
            break
        last_error = res.stderr.decode('utf-8', errors='ignore')[-300:]
    else:
        raise RuntimeError(f"Frame extraction failed: {last_error}")

    return {
        "filename": out_path.name,
        "path": str(out_path),
        "timestamp": timestamp_sec,
        "size_bytes": out_path.stat().st_size,
    }


def list_references():
    _ensure_dirs()
    files = sorted(REFERENCES_DIR.glob('*.png'), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": f.name, "path": str(f), "size": f.stat().st_size, "modified": f.stat().st_mtime} for f in files]


def resolve_image_path(src_str):
    """Map a character-image URL, reference URL or reference filename to a local file."""
    if not src_str or not isinstance(src_str, str):
        return None
    path_part = unquote(urlsplit(src_str).path)

    m_char = re.fullmatch(r'/api/characters/([^/]+)/image/([^/]+)', path_part)
    if m_char:
        return characters.get_image_path(m_char.group(1), m_char.group(2))

    m_ref = re.fullmatch(r'/api/motion/references/file/([^/]+)', path_part)
    name = m_ref.group(1) if m_ref else path_part
    return _contained(REFERENCES_DIR / Path(name).name, REFERENCES_DIR)


def render_character_motion(driving_video_path, source_image_path, audio_path=None, output_name=None):
    """Render character motion video composite.

    Uses character portrait and incorporates audio from the driving video or specified audio source.
    """
    _ensure_dirs()
    ipath = resolve_image_path(source_image_path)
    if not ipath:
        raise FileNotFoundError(f"Character image not found: {source_image_path}")

    out_name = Path(output_name).name if output_name else f"motion_{ipath.stem}_{uuid.uuid4().hex[:8]}.mp4"
    out_path = MOTION_OUTPUT_DIR / out_name

    cmd = [_ffmpeg(), '-nostdin', '-y', '-loop', '1', '-i', str(ipath)]

    resolved_driving = resolve_media_source(driving_video_path) if driving_video_path else None
    audio = resolve_media_source(audio_path) if audio_path else resolved_driving

    if audio:
        cmd += ['-i', str(audio), '-map', '0:v:0', '-map', '1:a?', '-c:a', 'aac', '-b:a', '192k', '-shortest']
    else:
        cmd += ['-t', '15']
    cmd += ['-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', str(out_path)]

    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0 or not out_path.is_file():
        raise RuntimeError("Motion render failed: " + res.stderr.decode('utf-8', errors='ignore')[-300:])

    return {
        "path": str(out_path),
        "filename": out_path.name,
        "duration": 15.0,
        "placeholder": True,
        "engine": "composite_preview"
    }
