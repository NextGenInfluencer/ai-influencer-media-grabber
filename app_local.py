from pathlib import Path
# Apply staged files before importing application dependencies.
if __name__ == '__main__':
    import os as _os, sys as _sys
    from safe_update import apply_pending
    if apply_pending(_os.path.dirname(_os.path.abspath(__file__))):
        if _os.name == 'nt':
            import subprocess as _sp
            _target = _os.path.abspath(__file__)
            _cmd = [_sys.executable, _target] + _sys.argv[1:]
            _sp.Popen(_cmd, cwd=_os.path.dirname(_target))
            _sys.exit(0)
        else:
            _os.execv(_sys.executable, [_sys.executable, __file__] + _sys.argv[1:])

import os
import re
import sys
import string
import job_process as subprocess
from job_process import cancellation_scope, check_cancelled, media_entries
import threading
import traceback
import uuid
import urllib.parse
from collections import deque
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, send_file, send_from_directory, abort, session
import queue
import json
import imageio_ffmpeg
import asyncio
import tempfile
import shutil
from shazamio import Shazam
import time
import yt_dlp
import math
from media_safety import contained_path, safe_media_name, crop_filter, MEDIA_EXTENSIONS
from download_support import (MAX_COOKIE_FILE_BYTES, CookieError, LoginRequiredError, atomic_write_json,
                              browser_options, cookie_options, cookie_status, delete_cookies,
                              extract_instagram_preview, ffmpeg_filter_path, friendly_download_error,
                              gallery_download, host_matches, import_cookie_bytes, is_instagram_profile_url,
                              is_instagram_url, migrate_legacy_cookies, platform_folder,
                              read_json_with_recovery, wants_playlist, write_json_with_backup)
from ai_runtime import segments_to_srt, translate_srt
from ai_core import asr
from ai_core.errors import AIUnavailable
import creator_composition
from assets import hwaccel
from typing import Any, Optional, cast

# --- Constants ---
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB
UPDATE_CHECK_INTERVAL = 86400  # 24 hours in seconds
GALLERY_CACHE_TTL = 15  # seconds

# --- Live Server Log Capture (Tee stdout & stderr for In-App Live Console) ---
class LogCapture:
    def __init__(self, maxlen=1000):
        self.logs = deque(maxlen=maxlen)
        self.lock = threading.RLock()
        self.subscribers = []
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        self.encoding = getattr(sys.stdout, 'encoding', 'utf-8') or 'utf-8'
        self.errors = 'replace'

    def isatty(self):
        return False

    def write(self, message):
        if self._orig_stdout:
            try:
                self._orig_stdout.write(message)
                self._orig_stdout.flush()
            except Exception:
                try:
                    enc = getattr(self._orig_stdout, 'encoding', 'utf-8') or 'utf-8'
                    self._orig_stdout.write(message.encode(enc, errors='replace').decode(enc))
                    self._orig_stdout.flush()
                except Exception:
                    pass
        if message:
            text = message.strip()
            if text:
                entry = {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "text": text
                }
                with self.lock:
                    self.logs.append(entry)
                    dead = []
                    for q in self.subscribers:
                        try:
                            q.put_nowait(entry)
                        except Exception:
                            dead.append(q)
                    for q in dead:
                        if q in self.subscribers:
                            self.subscribers.remove(q)

    def flush(self):
        if self._orig_stdout:
            try:
                self._orig_stdout.flush()
            except Exception:
                pass

log_capture = LogCapture()
sys.stdout = log_capture
sys.stderr = log_capture

# Global dict to store cancel flags for download tasks
cancel_flags = {}

# Ensure the Documents/Media Grabber folder exists immediately on startup
DEFAULT_SAVE_DIR = os.environ.get("MEDIA_GRABBER_DATA_DIR") or os.path.join(os.path.expanduser("~"), "Documents", "Media Grabber")
os.makedirs(DEFAULT_SAVE_DIR, exist_ok=True)
for sub in ['YouTube', 'Instagram', 'TikTok', 'Twitter', 'Other', 'Conversions', 'AI Cleaned']:
    os.makedirs(os.path.join(DEFAULT_SAVE_DIR, sub), exist_ok=True)

_gallery_cache: dict[str, Any] = {"time": 0.0, "data": []}

def invalidate_gallery_cache():
    global _gallery_cache
    _gallery_cache = {"time": 0.0, "data": []}

HISTORY_FILE = os.path.join(DEFAULT_SAVE_DIR, "history.json")
history_lock = threading.RLock()

FAVORITES_FILE = os.path.join(DEFAULT_SAVE_DIR, "favorites.json")
favorites_lock = threading.RLock()

def load_favorites() -> set[str]:
    """Load set of favorited / liked file paths (normalized lowercase)."""
    with favorites_lock:
        if os.path.exists(FAVORITES_FILE):
            try:
                with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return {os.path.normpath(p).lower() for p in data if p}
            except Exception:
                pass
        return set()

def save_favorites(fav_set: set[str]):
    """Persist favorited / liked file paths to favorites.json."""
    with favorites_lock:
        try:
            atomic_write_json(FAVORITES_FILE, sorted(fav_set))
        except Exception as e:
            print(f"Error saving favorites: {e}")

def _is_history_list(data) -> bool:
    return isinstance(data, list)

def load_history():
    """Return history newest-first. A corrupt file is preserved and recovered from its backup."""
    with history_lock:
        if os.path.exists(HISTORY_FILE):
            data = read_json_with_recovery(HISTORY_FILE, list, _is_history_list)
        else:
            # Migrate legacy history only once. Deleted rows must stay deleted.
            legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'history.json')
            data = read_json_with_recovery(legacy, list, _is_history_list) if os.path.exists(legacy) else []
            save_history(data)
        rows = [item for item in data if isinstance(item, dict)]
        return sorted(rows, key=lambda item: float(item.get('timestamp') or 0), reverse=True)


def save_history(data):
    with history_lock:
        write_json_with_backup(HISTORY_FILE, data, _is_history_list)


def save_url_shortcut(file_path, url):
    """Write a Windows .url internet shortcut alongside the downloaded media."""
    try:
        if not file_path or not url:
            return
        base, _ = os.path.splitext(file_path)
        url_file = base + ".url"
        with open(url_file, "w", encoding="utf-8") as f:
            f.write("[InternetShortcut]\n")
            f.write(f"URL={url}\n")
    except Exception as e:
        print(f"Failed to save .url shortcut: {e}")

def add_history_entry(url, title, uploader, file_path, platform):
    """Record a finished download; a history problem never fails the download itself."""
    with history_lock:
        try:
            h = load_history()
            h.insert(0, {
                "id": str(uuid.uuid4()),
                "url": url,
                "title": title,
                "uploader": uploader,
                "file_path": file_path,
                "platform": platform,
                "timestamp": time.time()
            })
            save_history(h)
        except Exception as e:
            print(f"Could not update download history: {e}")


_DERIVED_SUFFIXES = ("_first_frame", "_subbed", "_h264_temp", "_normalized", "_prompt", "_song", "_caption", "_transcript")


def _source_stem(file_path):
    """Lower-case file stem without the suffixes the app adds to derived files."""
    stem = os.path.splitext(os.path.basename(file_path))[0].lower()
    for suffix in _DERIVED_SUFFIXES:
        if stem.endswith(suffix):
            return stem[:-len(suffix)]
    return stem


def build_history_index(history_data):
    """Index history once per gallery refresh: by exact path, by folder and by file stem."""
    index = {"path": {}, "dir": {}, "stem": {}}
    for item in history_data or []:
        item_path = item.get("file_path") if isinstance(item, dict) else None
        if not item_path:
            continue
        value = (item.get("url"), item.get("uploader"))
        norm = os.path.normpath(item_path).lower()
        index["path"].setdefault(norm, value)
        if not os.path.splitext(norm)[1]:
            index["dir"].setdefault(norm, value)
        index["stem"].setdefault(_source_stem(item_path), value)
    return index


def _lookup_history_index(file_path, index):
    norm = os.path.normpath(file_path).lower()
    if norm in index["path"]:
        return index["path"][norm]
    match = index["stem"].get(_source_stem(file_path))
    if match:
        return match
    parent = os.path.dirname(norm)
    for _ in range(4):
        if parent in index["dir"]:
            return index["dir"][parent]
        next_parent = os.path.dirname(parent)
        if next_parent == parent:
            break
        parent = next_parent
    return None


def resolve_source_url(file_path, history_index=None):
    """Attempt to find or infer the source post URL and influencer info for a media file.

    ``history_index`` comes from ``build_history_index``; a raw history list is also accepted.
    """
    if not file_path:
        return None, None

    base, _ = os.path.splitext(file_path)
    url_candidates = [base + ".url"]
    for suffix in ("_first_frame", "_subbed", "_h264_temp"):
        if base.endswith(suffix):
            url_candidates.append(base[:-len(suffix)] + ".url")

    for candidate in url_candidates:
        if os.path.exists(candidate):
            try:
                with open(candidate, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.startswith("URL="):
                            url = line[4:].strip()
                            return url, None
            except Exception:
                pass

    file_name = os.path.basename(file_path)
    if isinstance(history_index, list):
        history_index = build_history_index(history_index)
    if history_index:
        match = _lookup_history_index(file_path, history_index)
        if match:
            return match

    # Regex Auto-inference from filename
    # 1. Instagram: "Video by <user>_<shortcode>" or filename with Instagram shortcode
    ig_post_match = re.search(r'Video by ([^_]+)_([A-Za-z0-9_-]+)', file_name, re.I)
    if ig_post_match:
        user = ig_post_match.group(1).strip()
        shortcode = ig_post_match.group(2).strip()
        shortcode = re.sub(r'_first_frame.*$', '', shortcode, flags=re.I)
        return f"https://www.instagram.com/p/{shortcode}/", user

    if "Instagram" in file_path or "instagram" in file_path.lower():
        ig_code = re.search(r'([A-Za-z0-9_-]{11})', file_name)
        if ig_code:
            code = ig_code.group(1)
            return f"https://www.instagram.com/p/{code}/", None

    # 2. TikTok: 19 digit ID
    tt_match = re.search(r'(\d{18,20})', file_name)
    if tt_match and ("TikTok" in file_path or "tiktok" in file_path.lower()):
        uploader = os.path.basename(os.path.dirname(file_path))
        if uploader and uploader.lower() != "tiktok":
            return f"https://www.tiktok.com/@{uploader}/video/{tt_match.group(1)}", uploader
        return f"https://www.tiktok.com/video/{tt_match.group(1)}", None

    # 3. YouTube: 11 char ID
    if "YouTube" in file_path or "youtube" in file_path.lower():
        yt_match = re.search(r'_([A-Za-z0-9_-]{11})(?:_first_frame)?\.[a-zA-Z0-9]+$', file_name)
        if yt_match:
            return f"https://www.youtube.com/watch?v={yt_match.group(1)}", None

    return None, None

# Ensure ffmpeg is in PATH for whisper
os.environ["PATH"] += os.pathsep + os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())


def helper_generate(prompt, system_prompt):
    """One local chat turn on the helper role (Ollama or built-in engine). Raises AIUnavailable."""
    from ai_core import llm
    answer = llm.chat('helper', [{'role': 'system', 'content': system_prompt},
                                 {'role': 'user', 'content': prompt}], temperature=0.4, max_tokens=1024)
    return answer['content'].strip()


# Cache the face detection cascade globally but initialize lazily and defensively
_face_cascade = None

def _get_face_cascade():
    global _face_cascade
    if _face_cascade is not None:
        return _face_cascade
    try:
        import cv2
        try:
            import cv2.data as cv2_data # type: ignore
        except Exception:
            cv2_data = None

        cascade_cls = None
        if hasattr(cv2, 'CascadeClassifier'):
            cascade_cls = getattr(cv2, 'CascadeClassifier')
        elif hasattr(cv2, 'xobjdetect') and hasattr(getattr(cv2, 'xobjdetect'), 'CascadeClassifier'):
            cascade_cls = getattr(getattr(cv2, 'xobjdetect'), 'CascadeClassifier')

        if cascade_cls is not None:
            xml_path = None
            haarcascades_dir = getattr(cv2_data, 'haarcascades', None)
            if haarcascades_dir:
                p = os.path.join(haarcascades_dir, 'haarcascade_frontalface_default.xml')
                if os.path.isfile(p):
                    xml_path = p
            if xml_path:
                detector = cascade_cls(xml_path)
                if hasattr(detector, 'empty') and not detector.empty():
                    _face_cascade = detector
                    return _face_cascade
    except Exception as e:
        print(f"[Face Cascade Init Warning] Could not load face detector: {e}")
    return None

def dynamic_auto_crop(input_path, output_path, q=None, prefix="", tracking_mode="largest", target_x=None):
    try:
        import cv2
        import numpy as np
        face_cascade = _get_face_cascade()
        if face_cascade is None:
            if q: q.put({"status": f"{prefix}Face detector unavailable, falling back to center crop..."})
            return False

        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            return False

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0: fps = 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        target_width = int(height * (9 / 16))
        target_width = (target_width // 2) * 2  # Must be divisible by 2 for H.264
        if target_width > width: target_width = (width // 2) * 2
        height = (height // 2) * 2  # Ensure height is also divisible by 2
        if width <= height:
            cap.release()
            return False

        mode_names = {
            "largest": "Dominant Subject",
            "custom_point": "Interactive Click-to-Track",
            "left": "Left Person (Speaker 1)",
            "right": "Right Person (Speaker 2)",
            "center": "Center Framing (Both Subjects)",
            "split_screen": "Podcast Split-Screen (Stacked 9:16)"
        }
        mode_label = mode_names.get(tracking_mode, "Dominant Subject")
        if tracking_mode == "custom_point" and target_x is not None:
            mode_label += f" ({int(target_x * 100)}% X)"

        if q: q.put({"status": f"{prefix}Scanning video for {mode_label}..."})

        keyframe_interval = max(1, int(fps / 2)) # Twice a second
        frame_centers = []
        frame_centers_p1 = []
        frame_centers_p2 = []
        frame_idx = 0

        if tracking_mode == "custom_point" and target_x is not None:
            last_center = int(target_x * width)
        else:
            last_center = width // 2

        last_c1 = width // 3
        last_c2 = (2 * width) // 3

        def face_cx(f):
            return int((f[0] + f[2] / 2) * 2)

        def face_area(f):
            return f[2] * f[3]

        while cap.isOpened() and frame_idx < total_frames:
            check_cancelled()
            ret, frame = cap.read()
            if not ret: break

            if frame_idx % keyframe_interval == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                small = cv2.resize(gray, (0,0), fx=0.5, fy=0.5)
                faces = face_cascade.detectMultiScale(small, 1.1, 4)
                if len(faces) > 0:
                    if tracking_mode == "custom_point":
                        # Find face closest to last_center (or initial clicked target_x)
                        closest = min(faces, key=lambda f: abs(face_cx(f) - last_center))
                        dist = abs(face_cx(closest) - last_center)
                        # Lock on initial detection or track smoothly within reach
                        if not frame_centers or dist < width * 0.35:
                            last_center = face_cx(closest)
                    elif tracking_mode == "split_screen":
                        # Speaker 1 (Left Half / Top Panel)
                        left_candidates = [f for f in faces if face_cx(f) < width * 0.60]
                        if left_candidates:
                            best_p1 = min(left_candidates, key=lambda f: face_cx(f))
                            last_c1 = face_cx(best_p1)
                        # Speaker 2 (Right Half / Bottom Panel)
                        right_candidates = [f for f in faces if face_cx(f) > width * 0.40]
                        if right_candidates:
                            best_p2 = max(right_candidates, key=lambda f: face_cx(f))
                            last_c2 = face_cx(best_p2)
                    elif tracking_mode == "left":
                        # Only track candidates on left side to avoid jumping across the room
                        left_candidates = [f for f in faces if face_cx(f) < width * 0.65]
                        if left_candidates:
                            best_left = min(left_candidates, key=lambda f: face_cx(f))
                            last_center = face_cx(best_left)
                    elif tracking_mode == "right":
                        # Only track candidates on right side
                        right_candidates = [f for f in faces if face_cx(f) > width * 0.35]
                        if right_candidates:
                            best_right = max(right_candidates, key=lambda f: face_cx(f))
                            last_center = face_cx(best_right)
                    elif tracking_mode == "center":
                        faces_by_x = sorted(faces, key=lambda f: face_cx(f))
                        left_x = face_cx(faces_by_x[0])
                        right_x = face_cx(faces_by_x[-1])
                        last_center = (left_x + right_x) // 2
                    else:  # 'largest' (Dominant Subject)
                        faces_by_area = sorted(faces, key=face_area, reverse=True)
                        largest = faces_by_area[0]
                        # Spatial continuity: if currently locked on a subject, check if still nearby
                        nearby = [f for f in faces if abs(face_cx(f) - last_center) < width * 0.30]
                        if nearby:
                            best_nearby = max(nearby, key=face_area)
                            # Only switch if another subject is much larger (prevents rapid jitter)
                            if face_area(best_nearby) >= face_area(largest) * 0.65:
                                last_center = face_cx(best_nearby)
                            else:
                                last_center = face_cx(largest)
                        else:
                            last_center = face_cx(largest)

                if tracking_mode == "split_screen":
                    frame_centers_p1.append((frame_idx, last_c1))
                    frame_centers_p2.append((frame_idx, last_c2))
                else:
                    frame_centers.append((frame_idx, last_center))

            frame_idx += 1
        cap.release()

        def interpolate_and_smooth(centers_list, target_box_w, default_val):
            if not centers_list:
                return [default_val] * frame_idx
            all_c = [default_val] * frame_idx
            for i in range(len(centers_list) - 1):
                idx1, c1 = centers_list[i]
                idx2, c2 = centers_list[i+1]
                for j in range(idx1, idx2):
                    all_c[j] = int(c1 + (c2 - c1) * (j - idx1) / (idx2 - idx1))
            idx_last, c_last = centers_list[-1]
            for j in range(idx_last, frame_idx):
                all_c[j] = c_last

            alpha = 0.07
            curr = all_c[0]
            smoothed = []
            for c in all_c:
                curr = alpha * c + (1 - alpha) * curr
                clamped = max(target_box_w // 2, min(width - target_box_w // 2, int(curr)))
                smoothed.append(clamped)
            return smoothed

        half_h = height // 2
        crop_w = target_width
        crop_h = height
        smoothed_p1 = []
        smoothed_p2 = []
        smoothed_centers = []

        if tracking_mode == "split_screen":
            if not frame_centers_p1 or not frame_centers_p2: return False
            crop_aspect = target_width / half_h
            if width / height >= crop_aspect:
                crop_h = height
                crop_w = int(crop_h * crop_aspect)
            else:
                crop_w = width
                crop_h = int(crop_w / crop_aspect)
            crop_w = (crop_w // 2) * 2
            crop_h = (crop_h // 2) * 2
            smoothed_p1 = interpolate_and_smooth(frame_centers_p1, crop_w, width // 3)
            smoothed_p2 = interpolate_and_smooth(frame_centers_p2, crop_w, (2 * width) // 3)
        else:
            if not frame_centers: return False
            smoothed_centers = interpolate_and_smooth(frame_centers, target_width, width // 2)

        if q: q.put({"status": f"{prefix}Rendering {mode_label} video..."})

        cap = cv2.VideoCapture(input_path)
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe() if imageio_ffmpeg else "ffmpeg"

        enc_args = hwaccel.get_video_encoder_args(codec='h264', quality='high')
        cmd = [
            ffmpeg_exe, '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
            '-s', f'{target_width}x{height}', '-pix_fmt', 'bgr24', '-r', str(fps),
            '-i', '-', '-i', input_path, '-map', '0:v', '-map', '1:a?',
            *enc_args, '-pix_fmt', 'yuv420p', '-c:a', 'copy',
            output_path
        ]

        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret: break

            if tracking_mode == "split_screen":
                c1 = smoothed_p1[frame_idx] if frame_idx < len(smoothed_p1) else smoothed_p1[-1]
                c2 = smoothed_p2[frame_idx] if frame_idx < len(smoothed_p2) else smoothed_p2[-1]

                # Person 1 (Top Half)
                x1 = max(0, min(width - crop_w, c1 - crop_w // 2))
                y1 = max(0, min(height - crop_h, (height - crop_h) // 2))
                crop_top = frame[y1:y1+crop_h, x1:x1+crop_w]
                if crop_top.shape[1] != target_width or crop_top.shape[0] != half_h:
                    crop_top = cv2.resize(crop_top, (target_width, half_h))

                # Person 2 (Bottom Half)
                x2 = max(0, min(width - crop_w, c2 - crop_w // 2))
                y2 = max(0, min(height - crop_h, (height - crop_h) // 2))
                crop_bottom = frame[y2:y2+crop_h, x2:x2+crop_w]
                if crop_bottom.shape[1] != target_width or crop_bottom.shape[0] != (height - half_h):
                    crop_bottom = cv2.resize(crop_bottom, (target_width, height - half_h))

                # Clean 2px modern separator border line
                crop_top[-2:, :] = (35, 35, 42)
                crop_bottom[:1, :] = (35, 35, 42)

                rendered_frame = np.vstack([crop_top, crop_bottom])
            else:
                c = smoothed_centers[frame_idx] if frame_idx < len(smoothed_centers) else smoothed_centers[-1]
                x_start = max(0, min(width - target_width, c - target_width // 2))
                rendered_frame = frame[0:height, x_start:x_start+target_width]
                if rendered_frame.shape[1] != target_width or rendered_frame.shape[0] != height:
                    rendered_frame = cv2.resize(rendered_frame, (target_width, height))

            try:
                if process.stdin:
                    process.stdin.write(rendered_frame.tobytes())
            except Exception: break
            check_cancelled()
            frame_idx += 1
            if q and frame_idx % int(fps * 2) == 0 and total_frames > 0:
                pct = int(frame_idx/total_frames*100)
                q.put({"status": f"{prefix}Rendering {mode_label} video... ({pct}%)"})

        cap.release()
        try:
            if process.stdin:
                process.stdin.close()
            process.wait()
        except Exception: pass

        check_cancelled()
        return process.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"[dynamic_auto_crop error] {e}")
        return False

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_BYTES
app.secret_key = os.urandom(32)
app.config.update(SESSION_COOKIE_NAME='media_grabber_session', SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
from routes_ai import register_ai_routes
register_ai_routes(app)
MEDIA_ROOTS_FILE = os.path.join(DEFAULT_SAVE_DIR, 'media_roots.json')
GALLERY_MAX_DEPTH = 4
GALLERY_MAX_FILES = 20000


def _is_filesystem_root(path):
    """Drive roots (C:\\) and '/' are never approved as media folders."""
    real = os.path.realpath(path)
    return os.path.dirname(real) == real


def _load_approved_roots():
    try:
        with open(MEDIA_ROOTS_FILE, encoding='utf-8') as roots_file:
            roots = json.load(roots_file)
    except (FileNotFoundError, ValueError):
        return set()
    return {root for root in roots if isinstance(root, str) and root and not _is_filesystem_root(root)}


def approve_media_root(folder):
    """Approve exactly one platform folder created for a download so the gallery can show it."""
    real = os.path.realpath(folder)
    if _is_filesystem_root(real) or contained_path(real, DEFAULT_SAVE_DIR) or real in _approved_media_roots:
        return
    _approved_media_roots.add(real)
    with history_lock:
        atomic_write_json(MEDIA_ROOTS_FILE, sorted(_approved_media_roots))


_approved_media_roots = _load_approved_roots()
try:
    migrate_legacy_cookies()
except OSError as _cookie_migration_error:
    print(f"Legacy cookies.txt was not migrated: {_cookie_migration_error}")

_approved_preview_files = set()


@app.before_request
def protect_local_service():
    from urllib.parse import urlsplit
    if urlsplit('http://' + request.host).hostname not in {'localhost', '127.0.0.1', '::1'}:
        abort(403)
    origin = request.headers.get('Origin')
    if origin and origin != request.host_url.rstrip('/'):
        abort(403)
    if request.path.startswith('/api/') and request.path != '/api/health_check':
        if not session.get('authorized'):
            abort(403)
        if request.method not in {'GET', 'HEAD'} and request.headers.get('X-Media-Token') != session.get('api_token'):
            abort(403)
    if request.method == 'POST' and (request.path.startswith('/api/captions') or request.path in {'/api/download', '/api/convert', '/api/batch_clean', '/api/batch_clean_upload', '/api/extract_prompt', '/api/reference/prepare'}):
        if globals().get('ai_installer_state', {}).get('is_installing') or globals().get('app_updater_state', {}).get('is_updating'):
            return jsonify(error='Wait for installation or update preparation to finish.'), 409


@app.after_request
def secure_local_response(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response

# Dependency changes are explicit installation operations, never startup side effects.

def sanitize_filename(name):
    # Remove illegal characters for Windows/Linux/Mac
    return re.sub(r'[\\/*?:"<>|]', "", name)

def format_srt_timestamp(seconds: float) -> str:
    """Format seconds into SRT timestamp format: HH:MM:SS,mmm"""
    ms = int((seconds - int(seconds)) * 1000)
    s = int(seconds) % 60
    m = int(seconds / 60) % 60
    h = int(seconds / 3600)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def is_safe_path(path):
    try:
        return any(contained_path(path, root) for root in [DEFAULT_SAVE_DIR, *_approved_media_roots])
    except Exception:
        return False

def shazam_file(audio_path):
    async def recognize():
        shazam = Shazam()
        return await shazam.recognize(audio_path)
    try:
        return asyncio.run(recognize())
    except Exception as e:
        print("Shazam error:", e)
        return None

APP_VERSION = "5.0.8"
SERVER_START_TIME = time.time()

# --- Active Job & Auto-Shutdown Watchdog State ---
# Desktop applications must stay running without spontaneous timeouts or shutdowns.
# Watchdog is opt-in via --enable-watchdog or MEDIA_GRABBER_ENABLE_WATCHDOG=1.
HEARTBEAT_TIMEOUT = float(os.environ.get("MEDIA_GRABBER_HEARTBEAT_TIMEOUT", "86400.0"))  # Default: 24h if enabled
ENABLE_WATCHDOG = os.environ.get("MEDIA_GRABBER_ENABLE_WATCHDOG", "").lower() in ["1", "true", "yes"] or "--enable-watchdog" in sys.argv
_last_heartbeat = time.time()
_has_received_heartbeat = False
_active_jobs_lock = threading.Lock()
_active_jobs_count = 0

def increment_active_job():
    subprocess.begin_job()
    global _active_jobs_count
    with _active_jobs_lock:
        _active_jobs_count += 1

def decrement_active_job():
    subprocess.end_job()
    global _active_jobs_count
    with _active_jobs_lock:
        _active_jobs_count = max(0, _active_jobs_count - 1)

def is_busy():
    with _active_jobs_lock:
        installer_busy = False
        if "ai_installer_state" in globals():
            installer_busy = globals()["ai_installer_state"].get("is_installing", False)
        updater_busy = False
        if "app_updater_state" in globals():
            updater_busy = globals()["app_updater_state"].get("is_updating", False)
        return _active_jobs_count > 0 or installer_busy or updater_busy

@app.route('/')
def index():
    session['authorized'] = True
    if not session.get('api_token'):
        session['api_token'] = uuid.uuid4().hex
    return render_template('index.html', version=APP_VERSION, api_token=session['api_token'])


@app.route('/api/list_drives', methods=['GET'])
def list_drives():
    """List available drive letters on Windows, or root on Unix."""
    drives = []
    if os.name == 'nt':
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                drives.append(drive)
    else:
        drives = ['/']
    return jsonify({"drives": drives})

@app.route('/api/list_dirs', methods=['POST'])
def list_dirs():
    """List subdirectories of a given path."""
    data = request.get_json() or {}
    path = data.get('path', '')
    if not path:
        path = os.path.expanduser('~')

    try:
        entries = []
        for entry in sorted(os.scandir(path), key=lambda e: e.name.lower()):
            if entry.is_dir() and not entry.name.startswith('.'):
                try:
                    # Check if we can access it
                    os.listdir(entry.path)
                    entries.append({"name": entry.name, "path": entry.path.replace('\\', '/')})
                except PermissionError:
                    pass
        return jsonify({"path": path.replace('\\', '/'), "dirs": entries})
    except Exception as e:
        return jsonify({"error": str(e), "path": path, "dirs": []}), 200

@app.route('/api/list_files', methods=['POST'])
def list_files_endpoint():
    """List media files in a given path."""
    data = request.get_json() or {}
    path = data.get('path', '')
    if not path:
        path = os.path.expanduser('~')

    media_exts = {'.mp4', '.mov', '.m4v', '.webm', '.avi', '.mkv', '.jpg', '.png', '.jpeg', '.webp'}
    try:
        files = []
        dirs = []
        for entry in sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.is_dir() and not entry.name.startswith('.'):
                try:
                    os.listdir(entry.path)
                    dirs.append({"name": entry.name, "path": entry.path.replace('\\', '/'), "is_dir": True})
                except PermissionError:
                    pass
            elif entry.is_file():
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in media_exts:
                    _approved_preview_files.add(os.path.realpath(entry.path))
                    files.append({"name": entry.name, "path": entry.path.replace('\\', '/'), "is_dir": False})
        return jsonify({"path": path.replace('\\', '/'), "entries": dirs + files})
    except Exception as e:
        return jsonify({"error": str(e), "path": path, "entries": []}), 200

def parse_time_seconds(time_str: Optional[str]) -> Optional[float]:
    if not time_str or not time_str.strip():
        return None
    parts = time_str.strip().split(':')
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 1:
            return float(parts[0])
    except ValueError:
        return None
    return None

@app.route('/api/convert', methods=['POST'])
def convert_media():
    if 'files' not in request.files:
        return jsonify({"error": "No files provided"}), 400

    files = request.files.getlist('files')
    resize = request.form.get('resize')
    format_opt = request.form.get('format') or "mp4"
    autocrop = request.form.get('autocrop') == 'true'
    tracking_mode = request.form.get('tracking_mode', 'largest')
    target_x_raw = request.form.get('target_x')
    target_x = None
    if target_x_raw:
        try:
            target_x_val = float(target_x_raw)
            if 0.0 <= target_x_val <= 1.0:
                target_x = target_x_val
        except ValueError:
            target_x = None
    burn_subtitles = request.form.get('burn_subtitles') == 'true'
    export_subtitles = request.form.get('export_subtitles') == 'true'
    translate_lang = request.form.get('translate_lang', 'none')
    trim_start = request.form.get('trimStart')
    trim_end = request.form.get('trimEnd')
    compress_opt = request.form.get('compress')
    video_filter = request.form.get('video_filter', 'none') or 'none'
    vignette = request.form.get('vignette') == 'true'
    noise_cancel = request.form.get('noise_cancel') == 'true'
    voice_isolation = request.form.get('voice_isolation') == 'true'
    audio_effect = request.form.get('audio_effect', 'none') or 'none'
    try:
        film_grain = float(request.form.get('film_grain') or 0)
        sharpen = float(request.form.get('sharpen') or 0)
        chromatic = float(request.form.get('chromatic') or 0)
    except ValueError:
        return jsonify({'error': 'Invalid effect slider value.'}), 400
    if video_filter not in creator_composition.VIDEO_FILTERS or audio_effect not in creator_composition.AUDIO_EFFECTS:
        return jsonify({'error': 'Unsupported video filter or audio effect.'}), 400
    if not (0 <= film_grain <= 30 and 0 <= sharpen <= 2 and 0 <= chromatic <= 10):
        return jsonify({'error': 'Effect slider values are out of range.'}), 400
    fx_cfg = dict(
        video_filter=video_filter, vignette=vignette, film_grain=film_grain,
        sharpen=sharpen, chromatic=chromatic, noise_cancel=noise_cancel,
        voice_isolation=voice_isolation, audio_effect=audio_effect
    )

    if format_opt not in {'mp4', 'mp4_hevc', 'mov_prores', 'mov', 'mkv', 'avi', 'webm', 'gif', 'mp3', 'wav', 'png', 'jpg', 'webp'}:
        return jsonify({'error': 'Unsupported output format'}), 400
    for value in (trim_start, trim_end):
        if value and value.strip():
            seconds = parse_time_seconds(value)
            if seconds is None or not math.isfinite(seconds) or seconds < 0:
                return jsonify({'error': 'Enter a valid, non-negative trim time.'}), 400
    if trim_end and trim_end.strip() and parse_time_seconds(trim_end) <= (parse_time_seconds(trim_start) or 0):
        return jsonify({'error': 'Trim end must be after trim start.'}), 400
    if len(files) > 1 and (trim_start or trim_end):
        return jsonify({'error': 'Trim one video at a time.'}), 400
    if translate_lang != 'none':
        export_subtitles = True

    if not files or files[0].filename == '':
        return jsonify({"error": "No selected file"}), 400

    output_dir = os.path.join(DEFAULT_SAVE_DIR, "Conversions")
    os.makedirs(output_dir, exist_ok=True)

    # Save files synchronously before background thread
    saved_files = []
    # uuid is imported at the top of the file
    shared_temp_dir = tempfile.mkdtemp(prefix='.working-', dir=output_dir)
    for f in files:
        if f.filename:
            input_ext = os.path.splitext(f.filename)[1].lower()
            base_name = os.path.splitext(safe_media_name(f.filename))[0]
            input_path = os.path.join(shared_temp_dir, f"{uuid.uuid4().hex}{input_ext}")
            f.save(input_path)
            saved_files.append({
                "original_name": f.filename,
                "base_name": base_name,
                "input_ext": input_ext,
                "path": input_path
            })

    def generate():
        yield f"data: {json.dumps({'status': 'Starting conversion...'})}\n\n"
        q = queue.Queue()

        def _run_conv_worker():
            total = len(saved_files)
            failed_count = 0
            failure_messages = []
            output_path = None

            for idx, file_data in enumerate(saved_files, 1):
                check_cancelled()
                prefix = f"[{idx}/{total}] " if total > 1 else ""
                q.put({"status": f"{prefix}Processing {file_data['original_name']}..."})
                input_path = file_data['path']
                input_ext = file_data['input_ext']
                base_name = file_data['base_name']
                ext_map = {
                    "mp4": "mp4",
                    "mp4_hevc": "mp4",
                    "mov_prores": "mov",
                    "mov": "mov",
                    "mkv": "mkv",
                    "gif": "gif",
                    "mp3": "mp3",
                    "wav": "wav",
                    "png": "png",
                    "jpg": "jpg",
                    "webp": "webp"
                }
                target_ext = ext_map.get(format_opt, format_opt or "mp4")
                output_name = f"{base_name}_converted_{uuid.uuid4().hex[:10]}.{target_ext}"
                output_path = os.path.join(output_dir, output_name)
                working_output = os.path.join(shared_temp_dir, f'{uuid.uuid4().hex}.{target_ext}')

                # Prevent overwriting existing files in bulk directory
                counter = 1
                while os.path.exists(output_path):
                    output_name = f"{base_name}_converted_{counter}.{target_ext}"
                    output_path = os.path.join(output_dir, output_name)
                    counter += 1

                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

                try:
                    # 0. Check for 100% Automatic Lossless Stream-Copy
                    start_s = parse_time_seconds(trim_start) if (total == 1 and (trim_start or trim_end)) else None
                    end_s = parse_time_seconds(trim_end) if (total == 1 and (trim_start or trim_end)) else None
                    is_trim_requested = (start_s is not None and start_s > 0) or (end_s is not None)

                    # If re-encoding is needed (crop/subtitles/format/compress), perform high-fidelity intermediate trim
                    if is_trim_requested:
                        trimmed_temp_path = os.path.join(shared_temp_dir, f"{uuid.uuid4().hex}_trimmed.mp4")
                        q.put({"status": f"{prefix}Trimming clip ({trim_start or '00:00:00'} to {trim_end or 'End'})..."})

                        trim_cmd = [ffmpeg_exe, "-y"]
                        if start_s is not None and start_s > 0:
                            trim_cmd.extend(["-ss", str(start_s)])
                        if end_s is not None:
                            if start_s is not None and start_s > 0:
                                duration_s = max(0.1, end_s - start_s)
                                trim_cmd.extend(["-t", str(duration_s)])
                            else:
                                trim_cmd.extend(["-t", str(end_s)])

                        # High-quality intermediate CRF 12 so subsequent crop never degrades
                        trim_enc = hwaccel.get_video_encoder_args(codec="h264", quality="high")
                        trim_cmd.extend(["-i", input_path, *trim_enc, "-c:a", "aac", "-b:a", "320k", trimmed_temp_path])

                        res = subprocess.run(trim_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                        if res.returncode == 0 and os.path.exists(trimmed_temp_path) and os.path.getsize(trimmed_temp_path) > 0:
                            input_path = trimmed_temp_path
                        else:
                            raise RuntimeError(f'Trim failed: {res.stderr[-1000:]}')
                    vf_filters = []
                    crf_val = "14" # Default studio master quality (visually lossless)

                    # 1. Smart Auto-Crop or Aspect Ratio Crop/Pad
                    if autocrop and format_opt not in ["mp3", "wav"] and input_ext not in [".mp3", ".wav", ".jpg", ".png", ".webp"]:
                        temp_crop_path = os.path.join(shared_temp_dir, f"{uuid.uuid4().hex}_precrop.mp4")
                        if dynamic_auto_crop(input_path, temp_crop_path, q, prefix, tracking_mode=tracking_mode, target_x=target_x):
                            input_path = temp_crop_path
                            # dynamic_auto_crop already crops to 9:16
                        else:
                            vf_filters.append(crop_filter(9, 16))
                    elif resize and resize != "none" and format_opt not in ["mp3", "wav"]:
                        if resize == "crop_9_16":
                            vf_filters.append(crop_filter(9, 16))
                        elif resize == "pad_9_16":
                            vf_filters.append("scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2")
                        elif resize == "crop_16_9":
                            vf_filters.append(crop_filter(16, 9))
                        elif resize == "pad_16_9":
                            vf_filters.append("scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2")
                        elif resize == "crop_1_1":
                            vf_filters.append("crop=trunc(min(iw\\,ih)/2)*2:trunc(min(iw\\,ih)/2)*2")
                        elif resize == "crop_4_5":
                            vf_filters.append(crop_filter(4, 5))
                        elif resize == "pad_blur_9_16":
                            vf_filters.append("split[original][copy];[copy]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bg];[original]scale=1080:1920:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")

                    # 2. File Size & Resolution Scaling (MB Reduction or Master Quality)
                    if compress_opt == "quality_lossless":
                        crf_val = "0" # Maximum encoder quality; edits and pixel conversion can still change source pixels
                    elif compress_opt in ["quality_master", "none", "", None]:
                        crf_val = "14" # Studio Master / Visually Lossless (Pristine 4K & AI detail)
                    elif compress_opt == "quality_standard":
                        crf_val = "22" # Standard Web (Balanced)
                    elif compress_opt == "compress_high":
                        crf_val = "28" # ~50% MB size reduction
                    elif compress_opt == "compress_web":
                        crf_val = "32" # ~75% MB size reduction
                    elif compress_opt == "compress_80":
                        crf_val = "33" # ~80% MB size reduction
                    elif compress_opt == "compress_85":
                        crf_val = "34" # ~85% MB size reduction
                    elif compress_opt == "compress_extreme":
                        crf_val = "36" # ~90% MB size reduction

                    if compress_opt in ["scale_1080p", "scale_720p", "scale_480p", "scale_50", "scale_25"]:
                        if compress_opt == "scale_1080p":
                            vf_filters.append("scale='if(gte(iw,ih),min(iw,1920),min(iw,1080))':'if(gte(iw,ih),min(ih,1080),min(ih,1920))':force_original_aspect_ratio=decrease:force_divisible_by=2")
                            crf_val = "16"
                        elif compress_opt == "scale_720p":
                            vf_filters.append("scale='if(gte(iw,ih),min(iw,1280),min(iw,720))':'if(gte(iw,ih),min(ih,720),min(ih,1280))':force_original_aspect_ratio=decrease:force_divisible_by=2")
                            crf_val = "20"
                        elif compress_opt == "scale_480p":
                            vf_filters.append("scale='if(gte(iw,ih),min(iw,854),min(iw,480))':'if(gte(iw,ih),min(ih,480),min(ih,854))':force_original_aspect_ratio=decrease:force_divisible_by=2")
                            crf_val = "24"
                        elif compress_opt == "scale_50":
                            vf_filters.append("scale=iw*0.5:ih*0.5")
                            crf_val = "18"
                        elif compress_opt == "scale_25":
                            vf_filters.append("scale=iw*0.25:ih*0.25")
                            crf_val = "22"

                    if format_opt == "gif":
                        if compress_opt == "compress_high": vf_filters.append("scale=iw*0.5:ih*0.5")
                        elif compress_opt == "compress_web": vf_filters.append("scale=iw*0.33:ih*0.33")
                        elif compress_opt == "compress_80": vf_filters.append("scale=iw*0.27:ih*0.27")
                        elif compress_opt == "compress_85": vf_filters.append("scale=iw*0.21:ih*0.21")
                        elif compress_opt == "compress_extreme": vf_filters.append("scale=iw*0.15:ih*0.15")

                    # Audio formats (ignore video filters)
                    af_filters = creator_composition.audio_fx_chain(fx_cfg)
                    if format_opt in ["mp3", "wav"]:
                        cmd = [ffmpeg_exe, "-y", "-i", input_path]
                        if af_filters:
                            cmd.extend(["-af", ",".join(af_filters)])
                        if format_opt == "mp3":
                            cmd.extend(["-vn", "-acodec", "libmp3lame", "-b:a", "320k"])
                        else:
                            cmd.extend(["-vn", "-acodec", "pcm_s16le"])
                    else:
                        # Video or Image formats
                        vf_filters.extend(creator_composition.video_fx_chain(fx_cfg))
                        if burn_subtitles or export_subtitles:
                            q.put({"status": f"{prefix}Generating Subtitles..."})
                            temp_audio = os.path.join(shared_temp_dir, f"{uuid.uuid4().hex}.mp3")

                            # For export, we should place the SRT next to the output video
                            final_srt_path = os.path.splitext(output_path)[0] + "_subtitles.srt"
                            temp_srt = final_srt_path if export_subtitles else os.path.join(shared_temp_dir, f"{uuid.uuid4().hex}.srt")

                            audio_cmd = [ffmpeg_exe, "-y", "-i", input_path, "-vn", "-acodec", "libmp3lame", temp_audio]
                            subprocess.run(audio_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                            if os.path.exists(temp_audio):
                                try:
                                    result = asr.transcribe(temp_audio, word_timestamps=False)
                                    with open(temp_srt, 'w', encoding='utf-8') as f:
                                        f.write(segments_to_srt(result.get('segments', []), format_srt_timestamp))

                                    if translate_lang and translate_lang != 'none':
                                        q.put({"status": f"{prefix}Translating Subtitles to {translate_lang}..."})
                                        try:
                                            with open(temp_srt, 'r', encoding='utf-8') as tf:
                                                srt_content = tf.read()
                                            translated_srt = translate_srt(srt_content, translate_lang)
                                            with open(temp_srt, 'w', encoding='utf-8') as tf:
                                                tf.write(translated_srt)
                                        except Exception as e:
                                            raise RuntimeError(f"Translation failed: {e}") from e

                                    if burn_subtitles:
                                        srt_escaped = temp_srt.replace('\\', '\\\\').replace(':', '\\:')
                                        vf_filters.append(f"subtitles='{srt_escaped}':force_style='FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2'")
                                except Exception as e:
                                    raise RuntimeError(f'Subtitle generation failed: {e}') from e
                            else:
                                raise RuntimeError('Could not extract audio for subtitles. Check that the video has an audio track.')

                        cmd = [ffmpeg_exe, "-y", "-i", input_path]
                        if format_opt in ["mp4", "mp4_hevc", "mov_prores", "mov", "mkv", "avi"]:
                            vf_filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
                        if vf_filters:
                            cmd.extend(["-vf", ",".join(vf_filters)])
                        if af_filters and format_opt in ["mp4", "mp4_hevc", "mov_prores", "mov", "mkv", "avi", "webm"]:
                            cmd.extend(["-af", ",".join(af_filters)])

                        if format_opt in ["mp4", "mkv", "avi"]:
                            enc_args = hwaccel.get_video_encoder_args(codec="h264", quality="high" if crf_val in ["0", "14"] else "standard")
                            cmd.extend([*enc_args, "-c:a", "aac", "-b:a", "320k", "-pix_fmt", "yuv420p"])
                        elif format_opt == "mp4_hevc":
                            # 4K HEVC Master with Apple/Windows compatible hvc1 tag
                            enc_args = hwaccel.get_video_encoder_args(codec="hevc", quality="high" if crf_val in ["0", "14"] else "standard")
                            cmd.extend([*enc_args, "-tag:v", "hvc1", "-c:a", "aac", "-b:a", "320k", "-pix_fmt", "yuv420p"])
                        elif format_opt == "mov_prores":
                            # Apple ProRes 422 Studio Master (HQ)
                            cmd.extend(["-c:v", "prores_ks", "-profile:v", "3", "-c:a", "pcm_s16le"])
                        elif format_opt == "mov":
                            enc_args = hwaccel.get_video_encoder_args(codec="h264", quality="high" if crf_val in ["0", "14"] else "standard")
                            cmd.extend([*enc_args, "-c:a", "aac", "-b:a", "320k", "-pix_fmt", "yuv420p"])
                        elif format_opt == "webm":
                            cmd.extend(["-c:v", "libvpx-vp9", "-crf", crf_val, "-b:v", "0", "-c:a", "libopus"])
                        elif format_opt == "gif":
                            cmd.extend(["-r", "15"])

                        elif format_opt in ["jpg", "png", "webp"]:
                            cmd.extend(["-frames:v", "1"])
                        else:
                            raise Exception(f"Invalid format: {format_opt}")

                    cmd.append(working_output)

                    q.put({"status": f"{prefix}Encoding..."})
                    try:
                        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                        if not os.path.exists(working_output) or os.path.getsize(working_output) == 0:
                            raise RuntimeError('Encoder produced no output.')
                        shutil.move(working_output, output_path)
                    except subprocess.CalledProcessError as e:
                        print(f"FFmpeg Error:\n{e.stderr}")
                        raise e

                    # Cleanup temp for this file immediately
                    try: os.remove(input_path)
                    except Exception: pass

                except Exception as e:
                    traceback.print_exc()
                    failed_count += 1
                    err_msg = str(e)
                    failure_messages.append(f"{file_data['original_name']}: {err_msg[:500]}")
                    q.put({"status": f"{prefix}{err_msg[:500]}"})
                    with open(os.path.join(DEFAULT_SAVE_DIR, "converter_debug.log"), "a", encoding="utf-8", errors="replace") as f:
                        f.write(f"Conversion Error:\n{traceback.format_exc()}\n")

            invalidate_gallery_cache()
            if failed_count == 0:
                last_path = output_path if output_path and os.path.exists(output_path) else output_dir
                q.put({"status": f"Successfully saved to {output_dir}", "done": True, "file_path": last_path, "output_path": output_dir})
            else:
                q.put({"error": f"{failed_count} file(s) failed. " + '; '.join(failure_messages)})


            try: shutil.rmtree(shared_temp_dir)
            except Exception: pass

        def run_conv():
            increment_active_job()
            try:
                _run_conv_worker()
            except Exception as e:
                q.put({'error': str(e)})
            finally:
                shutil.rmtree(shared_temp_dir, ignore_errors=True)
                decrement_active_job()

        t = threading.Thread(target=run_conv, daemon=True)
        t.start()

        while True:
            try:
                msg = q.get(timeout=10)
            except queue.Empty:
                yield ': working\n\n'
                continue
            yield f"data: {json.dumps(msg)}\n\n"
            if msg.get("done") or msg.get("error"):
                break

    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/cancel_all', methods=['POST'])
def cancel_all_jobs():
    subprocess.cancel_all()
    for task_id in list(cancel_flags):
        cancel_flags[task_id] = True
    return jsonify(status='Stopping jobs. An AI inference already running must finish its current step.')

@app.route('/api/cancel/<task_id>', methods=['POST'])
def cancel_task(task_id):
    if task_id in cancel_flags:
        cancel_flags[task_id] = True
    return jsonify({"success": True})

@app.route('/api/cookies/options', methods=['GET'])
def api_cookie_options():
    """Login-session choices that work on this operating system."""
    return jsonify(browser_options())


@app.route('/api/cookies/status', methods=['GET'])
def api_cookie_status():
    """Metadata about the imported cookies.txt (never names or values)."""
    return jsonify(cookie_status())


@app.route('/api/cookies/import', methods=['POST'])
def api_cookie_import():
    upload = request.files.get('file')
    if upload is None or not upload.filename:
        return jsonify(error='Choose a cookies.txt file to import.'), 400
    try:
        raw = upload.stream.read(MAX_COOKIE_FILE_BYTES + 1)
    finally:
        upload.close()
    try:
        status = import_cookie_bytes(raw)
    except CookieError as e:
        return jsonify(error=str(e)), 400
    return jsonify(success=True, status=status)


@app.route('/api/cookies', methods=['DELETE'])
def api_cookie_delete():
    return jsonify(success=True, deleted=delete_cookies())


@app.route('/api/preview', methods=['POST'])
def preview_url():
    data = request.get_json(silent=True) or {}
    url = str(data.get('url') or '').strip()
    browser = data.get('browser')
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    if not url.startswith(('http://', 'https://')) and not url.startswith('@'):
        return jsonify({"error": "Invalid URL scheme"}), 400

    try:
        ydl_patch, _ = cookie_options(browser)
    except CookieError as e:
        return jsonify({"error": str(e)}), 400

    try:
        if is_instagram_profile_url(url):
            return jsonify(extract_instagram_preview(url, browser=browser))
        if is_instagram_url(url):
            ig_info = extract_instagram_preview(url, browser=browser)
            if not ig_info:
                return jsonify({"error": "Instagram returned no data for this post"}), 502
            return jsonify(ig_info)
        ydl_opts: dict[str, Any] = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
            'noplaylist': not wants_playlist(url),
            **ydl_patch,
        }
        with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:
            info = ydl.extract_info(url, download=False) or {}
        return jsonify({
            "title": info.get('title', 'Unknown Title'),
            "uploader": info.get('uploader', 'Unknown Creator'),
            "thumbnail": info.get('thumbnail', ''),
            "duration": info.get('duration', 0)
        })
    except LoginRequiredError as e:
        return jsonify({"error": str(e), "login_required": True}), 401
    except Exception as e:
        return jsonify({"error": friendly_download_error(strip_ansi(e), url)}), 500

@app.route('/api/download', methods=['POST'])
def download_video():
    data = request.get_json(silent=True) or {}
    urls_raw = str(data.get('url') or '')
    output_root = str(data.get('path') or '').strip() or DEFAULT_SAVE_DIR
    custom_name = data.get('filename')
    browser = data.get('browser')
    task_id = str(data.get('task_id') or uuid.uuid4().hex)
    processing_options = data.get('processing_options')
    if not isinstance(processing_options, dict):
        processing_options = {}

    if task_id in cancel_flags:
        return jsonify(error='This task is already running.'), 409

    urls = [u.strip() for u in urls_raw.split('\n') if u.strip().startswith(('http://', 'https://'))]
    if not urls:
        return jsonify({"error": "Valid URL(s) required"}), 400
    try:
        cookie_patch, _ = cookie_options(browser)
    except CookieError as e:
        return jsonify({"error": str(e)}), 400

    cancel_flags[task_id] = False
    quality = processing_options.get('quality', 'max')
    profile_mode = processing_options.get('profile_mode') or data.get('profile_mode', 'all')
    selected_urls = processing_options.get('selected_urls') or data.get('selected_urls')

    # Build format selector based on user preference
    if quality == 'audio_only':
        fmt_str = 'bestaudio/best'
    elif quality in ['2160', '1440', '1080', '720', '480']:
        h = quality
        fmt_str = f'bestvideo[height<={h}]+bestaudio[ext=m4a]/bestvideo[height<={h}]+bestaudio/best[height<={h}]/best'
    else:  # 'max' / default: True maximum resolution available (4K, 1440p, 1080p60)
        fmt_str = 'bestvideo+bestaudio[ext=m4a]/bestvideo+bestaudio/best'

    postprocessors = []
    if quality == 'audio_only':
        postprocessors = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}]
    elif processing_options.get('forceH264', False):
        postprocessors = [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}]

    clean_name = sanitize_filename(custom_name) if custom_name else ''
    name_template = f'{clean_name}_%(id)s.%(ext)s' if clean_name else '%(title)s_%(id)s.%(ext)s'
    node_exe = os.path.join(app.root_path, 'node_runtime', 'node.exe')

    def generate():
        yield f"data: {json.dumps({'status': 'Fetching metadata...'})}\n\n"
        q = queue.Queue()

        def hook(d):
            if cancel_flags.get(task_id):
                raise Exception("Cancelled by user")
            if d['status'] == 'downloading':
                percent = strip_ansi(d.get('_percent_str', '0%').strip())
                speed = strip_ansi(d.get('_speed_str', '').strip())
                speed_text = f" at {speed}" if speed else ""
                q.put({"status": f"Downloading: {percent}{speed_text}"})
            elif d['status'] == 'finished':
                q.put({"status": "Merging files..."})
            elif d['status'] == 'error':
                # The worker receives the exception and reports the final outcome; keep the stream open.
                q.put({"status": "A download step failed; finishing up..."})

        common_opts: dict[str, Any] = {
            'format': fmt_str,
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
            'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe(),
            'retries': 10,
            'fragment_retries': 10,
            'socket_timeout': 30,
            'progress_hooks': [hook],
        }
        if postprocessors:
            common_opts['postprocessors'] = postprocessors

        def ydl_options(target_dir, url):
            opts: dict[str, Any] = {
                **common_opts,
                **cookie_patch,
                'outtmpl': os.path.join(target_dir, '%(playlist_title,uploader)s', '%(playlist_index|)s%(playlist_index& - |)s' + name_template),
                'noplaylist': not wants_playlist(url),
                'js_runtimes': {'node': {'path': node_exe}} if os.path.isfile(node_exe) else {'node': {}},
            }
            if cookie_patch:
                # A random 5 to 15 second delay between requests avoids account bans when logged in.
                opts['sleep_interval'] = 5
                opts['max_sleep_interval'] = 15
            return opts

        def download_with_ytdlp(url, target_dir, prefix):
            """One extraction per URL; a name collision gets a ' (n)' suffix without re-extracting."""
            opts = ydl_options(target_dir, url)
            try:
                with yt_dlp.YoutubeDL(cast(Any, opts)) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        raise RuntimeError('No downloadable media found at this URL')
                    unique_base = None
                    if info.get('_type', 'video') == 'video':
                        base, ext = os.path.splitext(ydl.prepare_filename(cast(Any, info)))
                        if os.path.exists(base + ext) or os.path.exists(base + '.mp4'):
                            c = 1
                            while os.path.exists(f"{base} ({c}){ext}") or os.path.exists(f"{base} ({c}).mp4"):
                                c += 1
                            unique_base = f"{base} ({c})"
                    if unique_base:
                        with yt_dlp.YoutubeDL(cast(Any, {**opts, 'outtmpl': unique_base + '.%(ext)s'})) as unique_ydl:
                            return unique_ydl.process_ie_result(info, download=True), unique_ydl
                    return ydl.process_ie_result(info, download=True), ydl
            except Exception as e:
                err_msg = strip_ansi(e)
                check_cancelled()
                unsupported = any(message in err_msg for message in UNSUPPORTED_BY_YTDLP)
                if unsupported or host_matches(url, 'pinterest.com', 'pin.it'):
                    q.put({"status": f"{prefix}Unsupported by yt-dlp. Downloading via gallery-dl..."})
                    return gallery_download(url, target_dir, browser, q.put, custom_name=custom_name), None
                raise RuntimeError(friendly_download_error(err_msg, url)) from e

        def _run_dl_worker():
            total = len(urls)
            failed_count = 0
            failure_messages = []
            login_required = False
            last_final_path = None
            last_target_dir = None
            for idx, url in enumerate(urls, 1):
                check_cancelled()
                prefix = f"[{idx}/{total}] " if total > 1 else ""
                q.put({"status": f"{prefix}Starting download..."})
                target_dir = os.path.join(output_root, platform_folder(url))
                try:
                    os.makedirs(target_dir, exist_ok=True)
                    approve_media_root(target_dir)
                    last_target_dir = target_dir
                    namer = None
                    if is_instagram_url(url):
                        if is_instagram_profile_url(url):
                            q.put({"status": f"{prefix}Instagram Profile detected. Downloading {profile_mode} media..."})
                        info = gallery_download(url, target_dir, browser, q.put, custom_name=custom_name,
                                                profile_mode=profile_mode, selected_urls=selected_urls,
                                                download_opts=common_opts)
                    else:
                        info, namer = download_with_ytdlp(url, target_dir, prefix)

                    entries = list(media_entries(info))
                    if not entries:
                        raise RuntimeError('Nothing was downloaded from this URL')
                    if isinstance(info, dict) and info.get('failed_items'):
                        failed_count += int(info['failed_items'])
                        failure_messages.append(f"{prefix}{info['failed_items']} post(s) could not be downloaded")
                    for entry in entries:
                        check_cancelled()
                        final_path, problems = postprocess_download(entry, url, processing_options, q.put, prefix, namer)
                        last_final_path = final_path
                        failed_count += len(problems)
                        failure_messages.extend(problems)
                except LoginRequiredError as e:
                    login_required = True
                    failed_count += 1
                    failure_messages.append(f"{prefix}{e}")
                    q.put({"status": f"{prefix}{e}"})
                except Exception as e:
                    failed_count += 1
                    error_msg = friendly_download_error(strip_ansi(e), url)
                    failure_messages.append(f"{prefix}{error_msg[:300]}")
                    q.put({"status": f"{prefix}Error: {error_msg}"})

            invalidate_gallery_cache()
            if failed_count == 0:
                q.put({"status": "All Downloads Complete!", "done": True, "file_path": last_final_path, "output_path": last_target_dir})
            else:
                summary = '; '.join(failure_messages[:5]) or 'Check the activity log.'
                q.put({"error": f"Finished with {failed_count} failed item(s): {summary}", "done": True,
                       "login_required": login_required, "file_path": last_final_path, "output_path": last_target_dir})

        def run_dl():
            increment_active_job()
            try:
                with cancellation_scope(lambda: cancel_flags.get(task_id, False)):
                    _run_dl_worker()
            except Exception as exc:
                q.put({'error': str(exc), 'done': True})
            finally:
                cancel_flags.pop(task_id, None)
                decrement_active_job()

        t = threading.Thread(target=run_dl, daemon=True)
        t.start()

        finished = False
        try:
            while True:
                try:
                    msg = q.get(timeout=10)
                except queue.Empty:
                    yield ': working\n\n'
                    continue
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("done") or msg.get("error"):
                    finished = True
                    break
        except GeneratorExit:
            # The client disconnected (tab closed / fetch aborted): stop the worker instead of orphaning it.
            if t.is_alive():
                cancel_flags[task_id] = True
            raise
        finally:
            if finished and not t.is_alive():
                cancel_flags.pop(task_id, None)

    return Response(generate(), mimetype='text/event-stream')


UNSUPPORTED_BY_YTDLP = ('Unsupported URL', 'No video formats found', 'Unable to extract data', 'HTTP Error 400',
                        'Video info extraction failed', 'There is no video in this post', "There's no video",
                        'no video', 'empty media response', 'does not contain any video', 'only images')


def strip_ansi(text):
    return re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', str(text))


def _resolve_final_path(entry, namer=None):
    """Locate the file yt-dlp/gallery-dl produced for one entry."""
    final_path = None
    for item in entry.get('requested_downloads') or []:
        if isinstance(item, dict) and item.get('filepath'):
            final_path = str(item['filepath'])
            break
    if not final_path:
        final_path = entry.get('filepath') or entry.get('_filename')
        if not final_path and namer is not None:
            final_path = namer.prepare_filename(cast(Any, entry))
    if final_path and not os.path.exists(final_path):
        merged = os.path.splitext(final_path)[0] + '.mp4'
        if os.path.exists(merged):
            final_path = merged
    return str(final_path) if final_path else None


def extract_first_frame(video_path, frame_path):
    """Save the first frame as PNG. Returns False (never raises) when ffmpeg cannot decode it."""
    try:
        result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", video_path, "-vframes", "1", "-q:v", "2", frame_path],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except OSError as exc:
        print(f"First frame extraction could not start: {exc}")
        return False
    return result.returncode == 0 and os.path.isfile(frame_path) and os.path.getsize(frame_path) > 0


def postprocess_download(info, url, processing_options, report, prefix='', namer=None):
    """History, sidecars and the optional AI/encoding steps for one downloaded file.

    Returns ``(final_path, problems)`` where problems are failures of steps the user asked for.
    Raises only when the downloaded file itself cannot be found.
    """
    problems = []
    final_path = _resolve_final_path(info, namer)
    if not final_path or not os.path.isfile(final_path):
        raise RuntimeError('Downloaded media file could not be located')
    media_extension = os.path.splitext(final_path)[1].lower()
    is_video = media_extension in {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}
    has_audio_media = is_video or media_extension in {'.mp3', '.m4a', '.wav', '.ogg'}

    # Add to history & save URL shortcut IMMEDIATELY (never skipped!)
    title = info.get('title') or 'Unknown Title'
    uploader = info.get('uploader') or 'Unknown'
    platform = info.get('extractor_key') or 'Other'
    add_history_entry(url, title, uploader, final_path, platform)
    save_url_shortcut(final_path, url)
    invalidate_gallery_cache()

    base, _ = os.path.splitext(final_path)
    frame_path = None
    # Extract first frame (a convenience: failure is a warning, never a failed download)
    if is_video and (processing_options.get('extractFrame', True) or processing_options.get('autoExtractPrompt')):
        report({"status": f"{prefix}Extracting frame..."})
        frame_path = base + "_first_frame.png"
        if not extract_first_frame(final_path, frame_path):
            frame_path = None
            report({"status": f"{prefix}Warning: could not extract the first frame; the video itself was saved."})

    if processing_options.get('autoExtractPrompt'):
        report({"status": f"{prefix}Describing the first frame with the local vision model..."})
        try:
            from ai_prompter import extract_prompt_from_image
            target_image = frame_path if frame_path and os.path.exists(frame_path) else final_path
            if os.path.exists(target_image):
                prompt_text = extract_prompt_from_image(target_image)
                prompt_txt_path = base + "_prompt.txt"
                with open(prompt_txt_path, "w", encoding="utf-8") as f:
                    f.write(prompt_text)
        except Exception as e:
            problems.append(f"{prefix}Prompt extraction failed: {e}")
            report({"status": f"{prefix}Prompt Extraction Error: {str(e)}"})

    # Audio Recognition & Metadata
    if processing_options.get('identifySong', True) and has_audio_media:
        report({"status": f"{prefix}Identifying song & metadata..."})
        song_txt_path = base + "_song.txt"
        temp_audio = base + "_temp_audio.mp3"

        # Extract 15 seconds of audio
        ffmpeg_audio_cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-i", final_path,
            "-t", "15",
            "-vn",
            "-acodec", "libmp3lame",
            temp_audio
        ]
        subprocess.run(ffmpeg_audio_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        shazam_track = None
        shazam_artist = None

        if os.path.exists(temp_audio):
            shazam_res = shazam_file(temp_audio)
            if shazam_res and 'track' in shazam_res:
                shazam_track = shazam_res['track'].get('title')
                shazam_artist = shazam_res['track'].get('subtitle')
            try:
                os.remove(temp_audio)
            except Exception:
                pass

        # Write metadata to files
        yt_track = info.get('track') or info.get('alt_title')
        yt_artist = info.get('artist') or info.get('creator')
        yt_desc = info.get('description', '')

        with open(song_txt_path, "w", encoding="utf-8") as f:
            f.write("--- VIDEO AUDIO INFO ---\n\n")
            if shazam_track:
                f.write(" Shazam Match:\n")
                f.write(f"Song: {shazam_track}\n")
                f.write(f"Artist: {shazam_artist}\n\n")
            else:
                f.write(" Shazam Match: No match found.\n\n")

            f.write(" Original Upload Metadata (yt-dlp):\n")
            f.write(f"Track: {yt_track or 'Unknown'}\n")
            f.write(f"Artist/Creator: {yt_artist or 'Unknown'}\n")

        if yt_desc:
            caption_txt_path = base + "_caption.txt"
            with open(caption_txt_path, "w", encoding="utf-8") as f:
                f.write(yt_desc)

    # Transcribe Video (Whisper) if transcript, summary, or subtitles are requested
    want_transcribe = processing_options.get('transcribeAudio')
    want_summarize = processing_options.get('aiSummarize')
    want_burn = processing_options.get('burn_subtitles')
    want_export = processing_options.get('export_subtitles')

    if has_audio_media and (want_transcribe or want_summarize or want_burn or want_export):
        report({"status": f"{prefix}Transcribing speech..."})
        transcript_path = base + "_transcript.txt"
        full_audio = base + "_full_audio.mp3"
        try:
            ffmpeg_full_audio = [
                imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", final_path,
                "-vn", "-acodec", "libmp3lame", full_audio
            ]
            subprocess.run(ffmpeg_full_audio, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            result: dict[str, Any] = asr.transcribe(full_audio, word_timestamps=False)
            transcript_text = result.get("text", "").strip()
            if want_transcribe and transcript_text:
                with open(transcript_path, "w", encoding="utf-8") as f:
                    f.write(transcript_text)

            if want_summarize and transcript_text:
                report({"status": f"{prefix}Generating AI Summary & SEO Tags (local helper model)..."})
                sys_p = "You are an expert social media manager. Read the video transcript and output: 1) A clean, bulleted summary of key points. 2) 3 viral TikTok/Reels captions. 3) SEO-optimized hashtags."
                try:
                    summary_text = helper_generate(transcript_text[:12000], sys_p)
                    summary_path = base + "_AI_Summary.txt"
                    with open(summary_path, "w", encoding="utf-8") as sf:
                        sf.write(summary_text)
                except AIUnavailable as e:
                    problems.append(f"{prefix}AI summary skipped: {e.message}")
                    report({"status": f"{prefix}AI summary skipped: {e.message}"})

            if (want_burn or want_export) and final_path.endswith(('.mp4', '.mkv', '.mov')) and result:
                srt_path = base + "_subtitles.srt"
                with open(srt_path, "w", encoding="utf-8") as srt_f:
                    srt_f.write(segments_to_srt(result.get("segments", []), format_srt_timestamp))

                if want_burn:
                    report({"status": f"{prefix}Burning subtitles into video..."})
                    temp_sub = base + "_subbed" + os.path.splitext(final_path)[1]
                    sub_enc = hwaccel.get_video_encoder_args(codec="h264", quality="high")
                    ffmpeg_sub = [
                        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", final_path,
                        "-vf", f"subtitles={ffmpeg_filter_path(srt_path)}", *sub_enc, "-c:a", "aac", temp_sub
                    ]
                    subprocess.run(ffmpeg_sub, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    if os.path.exists(temp_sub):
                        os.replace(temp_sub, final_path)

                if not want_export and os.path.exists(srt_path):
                    try: os.remove(srt_path)
                    except Exception: pass
        except Exception as e:
            problems.append(f"{prefix}Transcription failed: {e}")
            report({"status": f"{prefix}Transcription failed: {e}"})
        finally:
            try:
                os.remove(full_audio)
            except OSError:
                pass

    # Force H.264 Encoding (Fixes AI tool compatibility)
    if processing_options.get('forceH264') and final_path.endswith('.mp4'):
        report({"status": f"{prefix}Forcing Standard Encoding (H.264)..."})
        temp_h264 = base + "_h264_temp.mp4"
        force_enc = hwaccel.get_video_encoder_args(codec="h264", quality="standard")
        ffmpeg_h264_cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", final_path,
            *force_enc,
            "-c:a", "aac", "-pix_fmt", "yuv420p", "-movflags", "+faststart", temp_h264
        ]
        subprocess.run(ffmpeg_h264_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if os.path.exists(temp_h264) and os.path.getsize(temp_h264) > 0:
            os.replace(temp_h264, final_path)

    # AI Bypass (Clean & Scramble)
    if processing_options.get('aiBypass'):
        report({"status": f"{prefix}Applying AI Bypass (Scramble & Clean)..."})
        from cleaner import clean_video, clean_photo, backup_file

        # Backup first
        backup_file(final_path, DEFAULT_SAVE_DIR)

        ext = final_path.split('.')[-1].lower()
        is_vid = ext in ['mp4', 'mov', 'm4v', 'webm', 'avi', 'mkv']

        if is_vid:
            success, msg = clean_video(final_path, imageio_ffmpeg.get_ffmpeg_exe())
        else:
            success, msg = clean_photo(final_path)

        if not success:
            problems.append(f"{prefix}Metadata cleanup failed: {msg}")
            report({"status": f"{prefix}Metadata cleanup failed: {msg}"})

    return final_path, problems


GALLERY_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp3'}
GALLERY_SKIP_FOLDERS = {'cookies'}


def iter_gallery_files(folder_path, budget, max_depth=GALLERY_MAX_DEPTH):
    """Yield (directory, filename) for media under ``folder_path`` with depth and file-count caps.

    ``budget`` is a one-element list holding the remaining number of files for the whole scan.
    """
    for root, dirs, files in os.walk(folder_path):
        relative = os.path.relpath(root, folder_path)
        depth = 0 if relative == '.' else relative.count(os.sep) + 1
        if depth >= max_depth:
            dirs[:] = []
        else:
            dirs[:] = [name for name in dirs if not name.startswith('.')]
        for file in files:
            if budget[0] <= 0:
                return
            if os.path.splitext(file)[1].lower() in GALLERY_EXTENSIONS:
                budget[0] -= 1
                yield root, file


@app.route('/api/gallery', methods=['GET'])
def list_gallery():
    global _gallery_cache
    if time.time() - _gallery_cache["time"] < GALLERY_CACHE_TTL:
        return jsonify(_gallery_cache["data"])

    base_dir = DEFAULT_SAVE_DIR
    known_order = ['YouTube', 'Instagram', 'TikTok', 'Twitter', 'Conversions', 'AI Cleaned', 'Other']

    # Dynamically find all subfolders in Media Grabber
    existing_dirs = []
    if os.path.exists(base_dir):
        existing_dirs = [d for d in os.listdir(base_dir)
                         if os.path.isdir(os.path.join(base_dir, d)) and not d.startswith('.') and d not in GALLERY_SKIP_FOLDERS]

    folders = [f for f in known_order if f in existing_dirs] + [f for f in existing_dirs if f not in known_order]
    if not folders:
        folders = known_order

    media = []
    try:
        history_index = build_history_index(load_history())
    except Exception as e:
        print(f"Gallery: history unavailable ({e}); continuing without source links")
        history_index = build_history_index([])
    fav_set = load_favorites()
    budget = [GALLERY_MAX_FILES]
    quote = urllib.parse.quote

    locations = [(folder, os.path.join(base_dir, folder)) for folder in folders]
    locations.extend(('Other', root) for root in sorted(_approved_media_roots)
                     if not contained_path(root, base_dir) and not _is_filesystem_root(root))
    for folder, folder_path in locations:
        if not os.path.isdir(folder_path):
            continue
        for root, file in iter_gallery_files(folder_path, budget):
            file_path = os.path.join(root, file)
            try:
                stat = os.stat(file_path)
            except OSError:
                continue
            ext = os.path.splitext(file)[1].lower()
            rel_dir = os.path.relpath(root, folder_path)
            if rel_dir == '.':
                item_path = file
            else:
                item_path = f"{rel_dir}/{file}".replace('\\', '/')

            source_url, uploader = resolve_source_url(file_path, history_index)
            norm_fp = os.path.normpath(file_path).lower()

            is_studio = (
                folder in ['Storyboard Images', 'Storyboard Videos', 'Motion Outputs', 'AI Creations'] or
                file.startswith(('keyframe_scene_', 'video_scene_', 'motion_')) or
                'storyboard' in folder.lower()
            )
            section = "studio" if is_studio else "downloads"
            studio_type = "other"
            scene_num = None
            if is_studio:
                if folder == 'Storyboard Images' or file.startswith('keyframe_scene_'):
                    studio_type = "keyframe"
                elif folder == 'Storyboard Videos' or file.startswith('video_scene_'):
                    studio_type = "scene_video"
                elif folder == 'Motion Outputs' or file.startswith('motion_'):
                    studio_type = "motion_swap"
                else:
                    studio_type = "studio_asset"

                scene_match = re.search(r'scene_(\d+)', file, re.IGNORECASE)
                if scene_match:
                    scene_num = int(scene_match.group(1))

            media.append({
                "name": file,
                "url": '/api/preview_file?path=' + quote(file_path),
                "folder": folder,
                "path": f"{folder}/{item_path}",
                "full_path": file_path,
                "type": "video" if ext in ['.mp4', '.mov', '.mkv', '.webm', '.avi'] else "audio" if ext == ".mp3" else "image",
                "section": section,
                "studio_type": studio_type,
                "scene_number": scene_num,
                "timestamp": stat.st_mtime,
                "size": stat.st_size,
                "source_url": source_url,
                "uploader": uploader,
                "liked": norm_fp in fav_set
            })

    if budget[0] <= 0:
        print(f"Gallery scan stopped at {GALLERY_MAX_FILES} files")
    media.sort(key=lambda x: x['timestamp'], reverse=True)
    _gallery_cache["time"] = time.time()
    _gallery_cache["data"] = media
    return jsonify(media)

@app.route('/api/media/<path:filename>')
def serve_media(filename):
    base_dir = DEFAULT_SAVE_DIR
    norm = os.path.normpath(filename)
    if os.path.isabs(filename) or os.path.splitdrive(filename)[0] or norm.startswith('..'):
        abort(403)
    full_path = os.path.join(base_dir, norm)
    if not contained_path(full_path, base_dir):
        abort(403)
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        abort(404)
    return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path))

@app.route('/api/open_folder', methods=['POST'])
def open_folder():
    path = (request.get_json(silent=True) or {}).get('path')
    if not path:
        path = DEFAULT_SAVE_DIR
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
    if not is_safe_path(path):
        return jsonify({"error": "Path not found or forbidden"}), 403

    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        # Fall back to parent folder if available
        parent = os.path.dirname(abs_path)
        if os.path.exists(parent):
            abs_path = parent
        else:
            return jsonify({"error": "Path not found"}), 404

    try:
        if sys.platform == 'win32':
            if os.path.isfile(abs_path):
                subprocess.Popen(['explorer', '/select,', abs_path])
            else:
                os.startfile(abs_path)
        elif sys.platform == 'darwin':
            if os.path.isfile(abs_path):
                subprocess.Popen(['open', '-R', abs_path])
            else:
                subprocess.Popen(['open', abs_path])
        else:
            # Linux
            dir_to_open = os.path.dirname(abs_path) if os.path.isfile(abs_path) else abs_path
            subprocess.Popen(['xdg-open', dir_to_open])
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error opening folder: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/open_file', methods=['POST'])
def open_file():
    path = request.json.get('path') if request.json else None
    if not path or not is_safe_path(path) or not os.path.isfile(path) or os.path.splitext(path)[1].lower() not in MEDIA_EXTENSIONS:
        return jsonify({"error": "File not found or forbidden"}), 404
    abs_path = os.path.abspath(path)
    try:
        if sys.platform == 'win32':
            os.startfile(abs_path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', abs_path])
        else:
            subprocess.Popen(['xdg-open', abs_path])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/hwaccel', methods=['GET'])
def api_hwaccel():
    try:
        force_cpu = request.args.get('force_cpu', '').lower() in ['1', 'true', 'yes']
        info = hwaccel.detect_best_encoder(force_cpu=force_cpu)
        return jsonify({
            "success": True,
            "encoder": info.get("encoder"),
            "display_name": info.get("display_name"),
            "vendor": info.get("vendor"),
            "type": info.get("type"),
            "hardware_accelerated": info.get("hardware_accelerated", False),
            "codec": info.get("codec")
        })
    except Exception as exc:
        return jsonify({
            "success": False,
            "encoder": "libx264",
            "display_name": "CPU Software Encoder (libx264)",
            "vendor": "Software",
            "type": "cpu",
            "hardware_accelerated": False,
            "error": str(exc)
        })

@app.route('/api/extract_prompt', methods=['POST'])
def extract_prompt():
    data = request.get_json(silent=True) or {}
    path = data.get('path')
    if not path or not os.path.exists(path) or not is_safe_path(path):
        return jsonify({"error": "File not found or forbidden"}), 404

    ext = os.path.splitext(path)[1].lower()
    is_video = ext in ['.mp4', '.mov', '.mkv', '.webm', '.avi']

    target_image = path
    temp_frame = None

    if is_video:
        temp_frame = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}.jpg")
        try:
            # Extract middle frame
            subprocess.run([
                imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", path,
                "-vf", "select=eq(n\\,0)", "-vframes", "1", temp_frame
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if os.path.exists(temp_frame):
                target_image = temp_frame
            else:
                return jsonify({"error": "Failed to extract frame from video"}), 500
        except Exception as e:
            return jsonify({"error": f"Video extraction error: {str(e)}"}), 500

    try:
        from ai_prompter import extract_prompt_from_image
        increment_active_job()
        try:
            prompt = extract_prompt_from_image(target_image)
        finally:
            decrement_active_job()
        return jsonify({"prompt": prompt})
    except AIUnavailable as e:
        return jsonify({"error": e.message, "setup_hint": e.setup_hint}), 424
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if temp_frame and os.path.exists(temp_frame):
            try:
                os.remove(temp_frame)
            except Exception:
                pass

@app.route('/api/preview_file')
def preview_file():
    # send_file is imported at the top of the file
    path = request.args.get('path')
    if not path or not os.path.isfile(path) or os.path.splitext(path)[1].lower() not in MEDIA_EXTENSIONS or not (is_safe_path(path) or os.path.realpath(path) in _approved_preview_files):
        return "Not found or forbidden", 403
    return send_file(path)


def tracked_cleaner(targets, output_dir, **options):
    from cleaner import run_batch_cleaner
    increment_active_job()
    try:
        yield from run_batch_cleaner(targets, output_dir, **options)
    finally:
        invalidate_gallery_cache()
        decrement_active_job()

@app.route('/api/batch_clean', methods=['POST'])
def batch_clean():
    data = request.json
    target_dirs = data.get('target_dirs', [])
    inject_exif = data.get('inject_exif', False)

    output_dir = os.path.join(DEFAULT_SAVE_DIR, "AI Cleaned")

    try:
        from cleaner import run_batch_cleaner
        return Response(tracked_cleaner(target_dirs, output_dir, is_upload=False, inject_exif=inject_exif), mimetype='text/event-stream')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/batch_clean_upload', methods=['POST'])
def batch_clean_upload():
    if 'files' not in request.files:
        return jsonify({"error": "No files uploaded"}), 400

    files = request.files.getlist('files')
    if not files or not files[0].filename:
        return jsonify({"error": "No selected files"}), 400

    inject_exif = request.form.get('inject_exif', 'false').lower() == 'true'


    upload_folder = os.path.join(DEFAULT_SAVE_DIR, "AI Cleaned", f"Uploaded_{uuid.uuid4().hex}")
    os.makedirs(upload_folder, exist_ok=True)

    uploaded_paths = []
    for file in files:
        if file and file.filename:
            filename = uuid.uuid4().hex[:10] + '_' + safe_media_name(file.filename)
            file_path = os.path.join(upload_folder, filename)
            file.save(file_path)
            uploaded_paths.append(file_path)

    try:
        from cleaner import run_batch_cleaner
        return Response(tracked_cleaner(uploaded_paths, upload_folder, is_upload=True, inject_exif=inject_exif), mimetype='text/event-stream')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/history', methods=['GET'])
def get_history():
    return jsonify(load_history())

@app.route('/api/history', methods=['DELETE'])
def clear_history():
    save_history([])
    return jsonify({"success": True})

@app.route('/api/history/<history_id>', methods=['DELETE'])
def delete_history_item(history_id):
    h = load_history()
    h = [item for item in h if item.get('id') != history_id]
    save_history(h)
    return jsonify({"success": True})

@app.route('/api/gallery/delete', methods=['POST'])
def delete_gallery_item():
    path = request.json.get('path')
    if not path or not os.path.isfile(path) or not is_safe_path(path) or os.path.splitext(path)[1].lower() not in MEDIA_EXTENSIONS:
        return jsonify({"error": "File not found or forbidden"}), 403

    try:
        from send2trash import send2trash
        send2trash(path)
    except Exception as e:
        return jsonify({'error': f'Could not move file to the recycle bin. File preserved: {e}'}), 500

    norm_path = os.path.normpath(path).lower()
    fav_set = load_favorites()
    if norm_path in fav_set:
        fav_set.discard(norm_path)
        save_favorites(fav_set)

    invalidate_gallery_cache()
    return jsonify({"success": True})

@app.route('/api/gallery/like', methods=['POST'])
def toggle_gallery_like():
    data = request.json or {}
    path = data.get('path')
    if not path or not os.path.exists(path) or not is_safe_path(path):
        return jsonify({"error": "File not found or forbidden"}), 400

    norm = os.path.normpath(path).lower()
    fav_set = load_favorites()

    explicit_liked = data.get('liked')
    if explicit_liked is not None:
        want_liked = bool(explicit_liked)
    else:
        want_liked = norm not in fav_set

    if want_liked:
        fav_set.add(norm)
    else:
        fav_set.discard(norm)

    save_favorites(fav_set)

    # Invalidate or sync memory cache
    global _gallery_cache
    if _gallery_cache.get("data"):
        for item in _gallery_cache["data"]:
            if os.path.normpath(item.get("full_path", "")).lower() == norm:
                item["liked"] = want_liked

    return jsonify({"success": True, "path": path, "liked": want_liked, "total_liked": len(fav_set)})

@app.route('/api/gallery/set_url', methods=['POST'])
def set_gallery_url():
    data = request.json or {}
    path = data.get('path')
    url = data.get('url', '').strip()
    if not path or not os.path.exists(path) or not is_safe_path(path):
        return jsonify({"error": "Invalid or unsafe path"}), 400
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    save_url_shortcut(path, url)
    global _gallery_cache
    _gallery_cache["time"] = 0
    return jsonify({"success": True, "url": url})

@app.route('/api/logs', methods=['GET'])
def get_logs():
    with log_capture.lock:
        return jsonify(list(log_capture.logs))

@app.route('/api/logs/stream')
def stream_logs():
    def event_generator():
        q = queue.Queue(maxsize=200)
        with log_capture.lock:
            recent = list(log_capture.logs)[-80:]
            log_capture.subscribers.append(q)
        try:
            for item in recent:
                yield f"data: {json.dumps(item)}\n\n"
            while True:
                try:
                    item = q.get(timeout=10)
                except queue.Empty:
                    yield ': keepalive\n\n'
                    continue
                yield f"data: {json.dumps(item)}\n\n"
        except GeneratorExit:
            with log_capture.lock:
                if q in log_capture.subscribers:
                    log_capture.subscribers.remove(q)

    return Response(event_generator(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    })

# AI Status and Installer State
ai_installer_state: dict[str, Any] = {
    "is_installing": False,
    "progress": 0,
    "status": "idle",
    "error": None,
    "pack": None,
    "log": []
}

# One maintenance job (AI pack install or app update) at a time; double clicks get a 409.
_maintenance_lock = threading.Lock()
_MAINTENANCE_BUSY = 'Another installation or update is already running. Wait for it to finish.'


def _run_maintenance(worker, *args):
    try:
        worker(*args)
    finally:
        _maintenance_lock.release()


def get_ai_status():
    # find_spec only: AI libraries are never imported into the server process.
    from assets.ai_setup import installed_features
    st = installed_features()
    st['all_installed'] = all(st.values())
    return st


def _run_pip(cmd):
    """Stream one pip command into the installer log; returns its exit code."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    process = subprocess.Popen(
        cmd,
        cwd=app.root_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        creationflags=flags
    )
    if process.stdout:
        for line in iter(process.stdout.readline, ''):
            line_clean = line.strip()
            if line_clean:
                ai_installer_state["log"].append(line_clean)
                if len(ai_installer_state["log"]) > 40:
                    ai_installer_state["log"].pop(0)
                if "Downloading" in line_clean:
                    ai_installer_state["progress"] = min(85, ai_installer_state["progress"] + 2)
                    ai_installer_state["status"] = f"Downloading AI packages: {line_clean[:55]}..."
                elif "Installing collected packages" in line_clean:
                    ai_installer_state["progress"] = max(ai_installer_state["progress"], 90)
                    ai_installer_state["status"] = "Unpacking and configuring AI packages..."
                elif "Successfully installed" in line_clean:
                    ai_installer_state["progress"] = max(ai_installer_state["progress"], 95)
        process.stdout.close()
    return process.wait()


def run_ai_install_worker(pack=None):
    global ai_installer_state
    from assets import ai_setup
    ai_installer_state["is_installing"] = True
    ai_installer_state["status"] = "Installing AI Engine pack..."
    ai_installer_state["progress"] = 10
    ai_installer_state["error"] = None
    ai_installer_state["log"] = ["Starting AI Engine installation via pip..."]

    try:
        pack = pack or ai_setup.recommended_pack(app.root_path)[0]
        commands = ai_setup.install_commands(sys.executable, app.root_path, pack)
        missing = [cmd[-1] for cmd in commands if not os.path.exists(os.path.join(app.root_path, cmd[-1]))]
        if missing:
            raise FileNotFoundError(f"{', '.join(missing)} not found. Reinstall the app with the release installer.")
        ai_installer_state["pack"] = pack
        ai_installer_state["log"].append(f"Selected pack: {pack}")
        ai_installer_state['status'] = 'Preparing AI installation tools...'
        ai_setup.prepare_build_tools(sys.executable, app.root_path)
        code = 0
        for cmd in commands:
            code = _run_pip(cmd)
            if code:
                break

        if code == 0:
            ai_installer_state["status"] = "Verifying AI libraries..."
            ai_installer_state["progress"] = 99
            ai_setup.verify_runtime(sys.executable, app.root_path, pack)
            ai_installer_state["is_installing"] = False
            ai_installer_state["status"] = "complete"
            ai_installer_state["progress"] = 100
            ai_installer_state["log"].append("AI Engine Pack verified. Restart the app before using AI features; model files are downloaded separately.")
        else:
            ai_installer_state["is_installing"] = False
            ai_installer_state["status"] = "failed"
            ai_installer_state["error"] = f"Installation exited with code {code}"
            ai_installer_state["log"].append(f"Installation failed with code {code}")
    except Exception as e:
        ai_installer_state["is_installing"] = False
        ai_installer_state["status"] = "failed"
        ai_installer_state["error"] = str(e)
        ai_installer_state["log"].append(f"Error: {str(e)}")

@app.route('/api/ai_status', methods=['GET'])
def api_ai_status():
    st = get_ai_status()
    return jsonify({
        **st,
        "is_installing": ai_installer_state["is_installing"],
        "install_status": ai_installer_state["status"],
        "install_progress": ai_installer_state["progress"],
        "install_error": ai_installer_state["error"],
        "install_pack": ai_installer_state.get("pack"),
        "install_log": ai_installer_state["log"][-8:]
    })

@app.route('/api/install_ai/notice', methods=['GET'])
def api_install_ai_notice():
    """Itemized download notice (packages, sizes, licenses, chosen pack and why) shown before install."""
    from assets.ai_setup import notice
    try:
        return jsonify(notice(app.root_path, request.args.get('pack') or None))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

@app.route('/api/install_ai', methods=['POST'])
def api_install_ai():
    global ai_installer_state
    from assets.ai_setup import load_packs
    data = request.get_json(silent=True) or {}
    if data.get('accept') is not True:
        return jsonify({"error": "Review the download notice (GET /api/install_ai/notice) and accept it first.",
                        "requires_accept": True}), 400
    pack = data.get('pack') or None
    if pack is not None and pack not in load_packs(app.root_path)['packs']:
        return jsonify({"error": f"Unknown AI pack: {pack}"}), 400
    if is_busy():
        return jsonify({"error": "Finish active jobs before installing AI packages."}), 409
    if not _maintenance_lock.acquire(blocking=False):
        return jsonify({"error": _MAINTENANCE_BUSY}), 409
    ai_installer_state["is_installing"] = True

    t = threading.Thread(target=_run_maintenance, args=(run_ai_install_worker, pack), daemon=True)
    t.start()
    return jsonify({"status": "started", "pack": pack})

@app.route('/api/heartbeat', methods=['GET', 'POST'])
def heartbeat():
    global _last_heartbeat, _has_received_heartbeat
    _last_heartbeat = time.time()
    _has_received_heartbeat = True
    return jsonify({"status": "alive", "busy": is_busy()})

def _watchdog_loop():
    if not ENABLE_WATCHDOG:
        return
    time.sleep(120)  # Initial grace period for desktop window launch
    while True:
        time.sleep(15)
        if _has_received_heartbeat:
            elapsed = time.time() - _last_heartbeat
            if elapsed > HEARTBEAT_TIMEOUT:
                if not is_busy():
                    print(f"[Watchdog] No client heartbeat for {int(elapsed)}s (timeout={int(HEARTBEAT_TIMEOUT)}s). Shutting down cleanly...", flush=True)
                    os._exit(0)

if ENABLE_WATCHDOG:
    threading.Thread(target=_watchdog_loop, daemon=True).start()

@app.route('/api/shutdown', methods=['POST'])
def shutdown_app():
    if is_busy():
        return jsonify(error='Work is still running. Wait for it to finish before exiting.'), 409
    def do_shutdown():
        time.sleep(0.5)
        print("Shutting down Media Grabber server...", flush=True)
        os._exit(0)
    threading.Thread(target=do_shutdown, daemon=True).start()
    return jsonify({"status": "App shutting down..."})

@app.route('/api/health_check', methods=['GET'])
def health_check():
    needs_restart = False
    try:
        root = Path(__file__).resolve().parent
        paths = [*root.glob('*.py'), *root.glob('assets/*.py'), *root.glob('templates/*.html'),
                 *root.glob('static/*.js'), *root.glob('static/*.css')]
        needs_restart = any(os.path.getmtime(path) > SERVER_START_TIME + 2 for path in paths)
    except Exception:
        pass

    return jsonify({
        "status": "ok",
        "version": APP_VERSION,
        "started_at": int(SERVER_START_TIME),
        "needs_restart": needs_restart
    })

@app.route('/api/restart', methods=['POST'])
def restart_server():
    if is_busy():
        return jsonify(error='Work is still running. Wait for it to finish before restarting.'), 409
    def restart_task():
        time.sleep(0.5)
        print("Restarting server from UI...", flush=True)
        try:
            script_path = os.path.abspath(__file__)
            python_exe = sys.executable
            extra_args = ["--no-browser"] if "--no-browser" in sys.argv else []

            helper_cmd = (
                "import time, subprocess\n"
                "time.sleep(1.2)\n"
                f"subprocess.Popen([{repr(python_exe)}, {repr(script_path)}] + {repr(extra_args)}, cwd={repr(os.path.dirname(script_path))})\n"
            )

            if os.name == 'nt':
                subprocess.Popen(
                    [python_exe, "-c", helper_cmd],
                    cwd=os.path.dirname(script_path),
                    creationflags=0x00000008 | 0x00000200
                )
            else:
                subprocess.Popen(
                    [python_exe, "-c", helper_cmd],
                    cwd=os.path.dirname(script_path),
                    start_new_session=True
                )
        except Exception as e:
            print(f"Failed to schedule server restart: {e}", flush=True)
        finally:
            time.sleep(0.2)
            os._exit(0)
    threading.Thread(target=restart_task, daemon=True).start()
    return jsonify({"status": "Server restarting..."})

# ====================================================================
# In-App GitHub OTA Auto-Updater Engine
# ====================================================================

GITHUB_REPO = "NextGenInfluencer/ai-influencer-media-grabber"
_update_check_cache: dict[str, Any] = {"time": 0.0, "data": None}

app_updater_state: dict[str, Any] = {
    "is_checking": False,
    "has_update": False,
    "current_version": APP_VERSION,
    "latest_version": APP_VERSION,
    "release_title": "",
    "release_notes": "",
    "published_at": "",
    "zipball_url": "",
    "html_url": "",
    "is_updating": False,
    "progress": 0,
    "status": "idle",
    "error": None,
    "log": []
}

def parse_semver(v_str: str) -> tuple:
    """Extract (major, minor, patch, ...) integer tuple from a version string."""
    clean = re.sub(r'^[vV]', '', v_str.strip())
    parts = []
    for piece in clean.split('.'):
        match = re.match(r'^\d+', piece)
        if match:
            parts.append(int(match.group(0)))
        else:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)

def fetch_latest_release(force=False) -> dict[str, Any]:
    global _update_check_cache, app_updater_state
    now = time.time()
    if not force and _update_check_cache["data"] and (now - _update_check_cache["time"] < 300):
        return _update_check_cache["data"]

    app_updater_state["is_checking"] = True
    try:
        import requests
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        headers = {"User-Agent": "AI-Influencer-Media-Grabber-Updater"}
        resp = requests.get(url, headers=headers, timeout=6)
        if resp.status_code == 200:
            rel = resp.json()
            tag = rel.get("tag_name", "")
            title = rel.get("name") or tag
            body = rel.get("body", "")
            zip_url = rel.get("zipball_url") or f"https://api.github.com/repos/{GITHUB_REPO}/zipball/{tag}"
            html_url = rel.get("html_url", f"https://github.com/{GITHUB_REPO}/releases")
            pub_at = rel.get("published_at", "")

            curr_v = parse_semver(APP_VERSION)
            latest_v = parse_semver(tag)
            has_update = latest_v > curr_v

            result: dict[str, Any] = {
                "has_update": has_update,
                "update_available": has_update,
                "current_version": APP_VERSION,
                "latest_version": tag,
                "release_title": title,
                "release_name": title,
                "release_notes": body,
                "published_at": pub_at,
                "zipball_url": zip_url,
                "html_url": html_url,
                "error": None
            }
            _update_check_cache["time"] = now
            _update_check_cache["data"] = result

            app_updater_state.update({
                "has_update": has_update,
                "update_available": has_update,
                "latest_version": tag,
                "release_title": title,
                "release_name": title,
                "release_notes": body,
                "published_at": pub_at,
                "zipball_url": zip_url,
                "html_url": html_url,
                "error": None
            })
            return result
        else:
            err = f"GitHub API returned status {resp.status_code}"
            app_updater_state["error"] = err
            return {"has_update": False, "update_available": False, "error": err, "current_version": APP_VERSION}
    except Exception as e:
        err = str(e)
        app_updater_state["error"] = err
        return {"has_update": False, "error": err, "current_version": APP_VERSION}
    finally:
        app_updater_state["is_checking"] = False

def run_ota_update_worker():
    app_updater_state.update(progress=5, status="Checking release...", error=None,
                             log=["Preparing a staged update."])
    archive = None
    try:
        import requests
        from safe_update import stage_archive, MAX_BYTES
        rel = fetch_latest_release(force=True)
        if rel.get('error'):
            raise RuntimeError(rel['error'])
        if not rel.get('has_update'):
            raise RuntimeError('You already have the latest published release.')
        url = rel.get('zipball_url', '')
        if not url.startswith(f'https://api.github.com/repos/{GITHUB_REPO}/zipball/'):
            raise ValueError('Unexpected release archive address')
        root = os.path.dirname(os.path.abspath(__file__))
        with tempfile.NamedTemporaryFile(dir=root, suffix='.update.zip', delete=False) as out:
            archive = out.name
            with requests.get(url, timeout=(10, 60), stream=True) as response:
                response.raise_for_status()
                total = 0
                for chunk in response.iter_content(65536):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValueError('Release archive exceeds download limit')
                    out.write(chunk)
        app_updater_state.update(progress=70, status="Validating application files...")
        stage_archive(root, archive, rel['latest_version'])
        # The cached release check would still offer the update that is now staged.
        _update_check_cache.update(time=0.0, data=None)
        app_updater_state.update(progress=100, status='complete', has_update=False)
        app_updater_state['log'].append('Update staged. Restart to apply it. Recovery copies will be kept.')
    except Exception as exc:
        app_updater_state.update(status='failed', error=str(exc))
        app_updater_state['log'].append(f'Update failed: {exc}')
    finally:
        if archive and os.path.exists(archive):
            os.remove(archive)
        app_updater_state['is_updating'] = False

@app.route('/api/check_update', methods=['GET', 'POST'])
def api_check_update():
    force = request.args.get('force') == '1' or request.method == 'POST'
    result = fetch_latest_release(force=force)
    return jsonify(result)

@app.route('/api/apply_update', methods=['POST'])
def api_apply_update():
    global app_updater_state
    if is_busy():
        return jsonify({"error": "Finish active jobs before updating."}), 409
    if not _maintenance_lock.acquire(blocking=False):
        return jsonify({"error": _MAINTENANCE_BUSY}), 409
    app_updater_state["is_updating"] = True
    threading.Thread(target=_run_maintenance, args=(run_ota_update_worker,), daemon=True).start()
    return jsonify({"status": "Update started"})

@app.route('/api/update_status', methods=['GET'])
def api_update_status():
    global app_updater_state
    resp = dict(app_updater_state)
    resp["completed"] = (app_updater_state.get("status") == "complete")
    return jsonify(resp)

def open_desktop_window(url="http://127.0.0.1:5000"):
    candidates = [
        os.path.expandvars(r'%ProgramFiles%\Google\Chrome\Application\chrome.exe'),
        os.path.expandvars(r'%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe'),
        os.path.expandvars(r'%ProgramFiles%\Microsoft\Edge\Application\msedge.exe'),
        os.path.expandvars(r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe'),
        os.path.expandvars(r'%LocalAppData%\Google\Chrome\Application\chrome.exe'),
    ]
    for exe in candidates:
        if os.path.exists(exe):
            try:
                subprocess.Popen([
                    exe,
                    f"--app={url}",
                    "--window-size=1380,880",
                    "--app-id=AiriStudioMediaGrabber"
                ])
                return
            except Exception:
                pass
    import webbrowser
    webbrowser.open(url)

from reference_prep import register_reference_prep
register_reference_prep(app, DEFAULT_SAVE_DIR, increment_active_job, decrement_active_job, invalidate_gallery_cache)
try:
    from captions import register_captions
except ModuleNotFoundError as exc:
    if exc.name != 'captions':
        raise
    raise RuntimeError('Captions & Lyrics requires the new application component. Upgrade from v2.4.x using the Windows installer on the GitHub release page.') from None
register_captions(app, DEFAULT_SAVE_DIR, increment_active_job, decrement_active_job, invalidate_gallery_cache, is_safe_path)
from routes_studio import register_studio_routes
register_studio_routes(app, save_dir=DEFAULT_SAVE_DIR, allowed_path=is_safe_path, app_version=APP_VERSION,
                       job_started=increment_active_job, job_finished=decrement_active_job)
from copilot import register_copilot_routes
register_copilot_routes(app, gallery=lambda: list_gallery().get_json(), allowed_path=is_safe_path)


if __name__ == '__main__':
    from waitress import serve
    print("\n" + "="*50, flush=True)
    print(" SERVER ONLINE AND READY! http://127.0.0.1:5000 ", flush=True)
    print("="*50 + "\n", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.25, open_desktop_window).start()
    # Long-lived SSE streams and polling each hold a worker thread.
    serve(app, host='127.0.0.1', port=5000, threads=24)
