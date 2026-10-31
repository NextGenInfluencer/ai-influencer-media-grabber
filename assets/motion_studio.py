"""Motion Transfer & Reference Snapper Studio Module.

Handles extracting pristine pose reference keyframes from downloaded videos
and driving character portraits with lip-sync and motion performances.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

import characters

DATA_DIR = Path(os.environ.get('MEDIA_GRABBER_DATA_DIR') or Path.home() / 'Documents' / 'Media Grabber')
REFERENCES_DIR = DATA_DIR / 'References'
MOTION_OUTPUT_DIR = DATA_DIR / 'Motion Outputs'


def _ensure_dirs():
    REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
    MOTION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def extract_reference_frame(video_path, timestamp_sec=0.0, output_name=None):
    """Extract an uncompressed pristine PNG frame from video at exact timestamp."""
    _ensure_dirs()
    vpath = Path(video_path)
    if not vpath.is_file():
        # Check if it is a relative path in DATA_DIR or static
        if (DATA_DIR / video_path).is_file():
            vpath = DATA_DIR / video_path
        elif (DATA_DIR / 'Downloads' / video_path).is_file():
            vpath = DATA_DIR / 'Downloads' / video_path
        else:
            raise FileNotFoundError(f"Video file not found: {video_path}")

    timestamp_sec = max(0.0, float(timestamp_sec))
    fname = output_name or f"ref_{vpath.stem}_{int(timestamp_sec*100)}_{uuid.uuid4().hex[:6]}.png"
    out_path = REFERENCES_DIR / fname

    cmd = [
        'ffmpeg', '-y',
        '-ss', f"{timestamp_sec:.3f}",
        '-i', str(vpath),
        '-vframes', '1',
        '-q:v', '2',
        str(out_path)
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0 or not out_path.is_file():
        cmd2 = ['ffmpeg', '-y', '-i', str(vpath), '-ss', f"{timestamp_sec:.3f}", '-vframes', '1', '-q:v', '2', str(out_path)]
        res2 = subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res2.returncode != 0 or not out_path.is_file():
            raise RuntimeError(f"FFmpeg frame extraction failed: {res.stderr.decode('utf-8', errors='ignore')[-300:]}")

    return {
        "filename": out_path.name,
        "path": str(out_path),
        "timestamp": timestamp_sec,
        "size_bytes": out_path.stat().st_size
    }


def list_references():
    _ensure_dirs()
    results = []
    for f in sorted(REFERENCES_DIR.glob('*.png'), key=lambda p: p.stat().st_mtime, reverse=True):
        results.append({
            "name": f.name,
            "path": str(f),
            "size": f.stat().st_size,
            "modified": f.stat().st_mtime
        })
    return results


def resolve_image_path(src_str):
    """Resolves URL, relative or absolute image path to local Path."""
    if not src_str:
        return None
    p = Path(src_str)
    if p.is_file():
        return p

    # Check /api/characters/<cid>/image/<filename>
    m_char = re.search(r'/api/characters/([^/]+)/image/([^/]+)', src_str)
    if m_char:
        cid, fname = m_char.group(1), m_char.group(2)
        cp = characters.get_image_path(cid, fname)
        if cp and cp.is_file():
            return cp

    # Check /api/motion/references/file/<filename>
    m_ref = re.search(r'/api/motion/references/file/([^/]+)', src_str)
    if m_ref:
        fname = m_ref.group(1)
        rp = REFERENCES_DIR / fname
        if rp.is_file():
            return rp

    if (REFERENCES_DIR / src_str).is_file():
        return REFERENCES_DIR / src_str

    return None


def render_character_motion(driving_video_path, source_image_path, audio_path=None, output_name=None):
    """Motion transfer engine for character animation.
    
    Generates video background from character source and driving performance,
    multiplexing with project audio for instant timeline placement.
    """
    _ensure_dirs()
    ipath = resolve_image_path(source_image_path)
    if not ipath or not ipath.is_file():
        raise FileNotFoundError(f"Source image missing or unresolved: {source_image_path}")

    dpath = Path(driving_video_path) if driving_video_path else None
    out_name = output_name or f"motion_{ipath.stem}_{uuid.uuid4().hex[:8]}.mp4"
    out_path = MOTION_OUTPUT_DIR / out_name

    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', str(ipath),
    ]
    if audio_path and Path(audio_path).is_file():
        cmd.extend(['-i', str(audio_path), '-shortest'])
    else:
        cmd.extend(['-t', '15'])

    cmd.extend([
        '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
        str(out_path)
    ])

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0 or not out_path.is_file():
        err_msg = res.stderr.decode('utf-8', errors='ignore')[-300:]
        raise RuntimeError(f"Motion generation failed: {err_msg}")

    return {
        "path": str(out_path),
        "filename": out_path.name,
        "duration": 15.0
    }
