import os
import re
import sys
import string
import subprocess
import threading
import traceback
import uuid
from collections import deque
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, send_file, send_from_directory, abort
from werkzeug.utils import secure_filename
import queue
import json
import imageio_ffmpeg
import asyncio
import tempfile
import shutil
from shazamio import Shazam
import time
import yt_dlp
from typing import Any, Optional, cast

# --- Constants ---
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB
UPDATE_CHECK_INTERVAL = 86400  # 24 hours in seconds
MODEL_UNLOAD_TIMEOUT = 600  # 10 minutes before unloading AI models
GALLERY_CACHE_TTL = 2  # seconds

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
DEFAULT_SAVE_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Media Grabber")
os.makedirs(DEFAULT_SAVE_DIR, exist_ok=True)
for sub in ['YouTube', 'Instagram', 'TikTok', 'Twitter', 'Other', 'Conversions', 'AI Cleaned']:
    os.makedirs(os.path.join(DEFAULT_SAVE_DIR, sub), exist_ok=True)

_gallery_cache: dict[str, Any] = {"time": 0.0, "data": []}

def invalidate_gallery_cache():
    global _gallery_cache
    _gallery_cache = {"time": 0.0, "data": []}

HISTORY_FILE = os.path.join(DEFAULT_SAVE_DIR, "history.json")
history_lock = threading.RLock()

def reconcile_download_history(data):
    """Scan download directories for any media files not yet recorded in history and add them."""
    try:
        known_paths = {os.path.normpath(x.get('file_path', '')).lower() for x in data if x.get('file_path')}
        new_entries = []
        scan_folders = ['YouTube', 'Instagram', 'TikTok', 'Twitter', 'Other']
        for folder in scan_folders:
            fdir = os.path.join(DEFAULT_SAVE_DIR, folder)
            if not os.path.exists(fdir):
                continue
            for root, _, files in os.walk(fdir):
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in ['.mp4', '.mov', '.mkv', '.webm', '.avi', '.mp3']:
                        fp = os.path.normpath(os.path.join(root, file))
                        if fp.lower() not in known_paths:
                            source_url, uploader = resolve_source_url(fp, data)
                            if not uploader:
                                rel = os.path.relpath(root, fdir)
                                if rel != '.':
                                    uploader = rel.replace('\\', '/')
                                else:
                                    uploader = 'Unknown'
                            base_title = os.path.splitext(file)[0]
                            clean_t = re.sub(r'_[a-zA-Z0-9_-]{11}$', '', base_title)
                            new_entries.append({
                                "id": str(uuid.uuid4()),
                                "url": source_url or "",
                                "title": clean_t,
                                "uploader": uploader,
                                "file_path": fp,
                                "platform": folder,
                                "timestamp": os.path.getmtime(fp)
                            })
                            known_paths.add(fp.lower())
        if new_entries:
            data.extend(new_entries)
            save_history(data)
    except Exception as e:
        print(f"Reconcile history error: {e}")
    return data

def load_history(reconcile=True):
    with history_lock:
        data = []
        # Check workspace root history.json first
        local_h = os.path.join(os.path.dirname(__file__), "history.json")
        if os.path.exists(local_h):
            try:
                with open(local_h, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass
        # Check Documents/Media Grabber history.json
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    doc_data = json.load(f)
                    seen_ids = {x.get('id') for x in doc_data if x.get('id')}
                    for item in data:
                        if item.get('id') not in seen_ids:
                            doc_data.append(item)
                    data = doc_data
            except Exception:
                pass
        if reconcile:
            data = reconcile_download_history(data)
        data.sort(key=lambda x: float(x.get('timestamp', 0)), reverse=True)
        return data

def save_history(data):
    with history_lock:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)

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
    with history_lock:
        h = load_history(reconcile=False)
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


def resolve_source_url(file_path, history_data=None):
    """Attempt to find or infer the source post URL and influencer info for a media file."""
    if not file_path:
        return None, None
        
    base, _ = os.path.splitext(file_path)
    url_candidates = [base + ".url"]
    if base.endswith("_first_frame"):
        url_candidates.append(base[:-12] + ".url")
    if base.endswith("_subbed"):
        url_candidates.append(base[:-7] + ".url")
    if base.endswith("_h264_temp"):
        url_candidates.append(base[:-10] + ".url")
        
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
    clean_name = file_name.lower()
    for sfx in ["_first_frame.jpg", "_first_frame.png", "_subbed.mp4", "_prompt.txt", "_song.txt"]:
        if clean_name.endswith(sfx):
            clean_name = clean_name[:-len(sfx)]
            break

    if history_data:
        norm_path = os.path.normpath(file_path).lower()
        for item in history_data:
            item_path = item.get("file_path")
            if item_path:
                item_norm = os.path.normpath(item_path).lower()
                item_name = os.path.basename(item_path).lower()
                if item_norm == norm_path or item_norm.startswith(norm_path) or norm_path.startswith(item_norm):
                    return item.get("url"), item.get("uploader")
                if clean_name and (clean_name in item_name or item_name in clean_name):
                    return item.get("url"), item.get("uploader")

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

import gc
whisper_model = None
_whisper_timer = None

def unload_whisper():
    global whisper_model, _whisper_timer
    if whisper_model is not None:
        print("Unloading Whisper model to free memory...")
        whisper_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception: pass
        gc.collect()
    _whisper_timer = None

def get_whisper():
    global whisper_model, _whisper_timer
    if _whisper_timer is not None:
        _whisper_timer.cancel()
    if whisper_model is None:
        try:
            import whisper
        except ImportError:
            print("Whisper is not installed. AI Pack required.")
            return None
        print("Loading Whisper model (this may take a moment)...")
        whisper_model = whisper.load_model("base")
    _whisper_timer = threading.Timer(MODEL_UNLOAD_TIMEOUT, unload_whisper)
    _whisper_timer.daemon = True
    _whisper_timer.start()
    return whisper_model

llm_model = None
_llm_timer = None
_current_llm_id = None

def unload_llm():
    global llm_model, _llm_timer, _current_llm_id
    if llm_model is not None:
        del llm_model
        llm_model = None
        _current_llm_id = None
        gc.collect()
    _llm_timer = None

def get_llm(model_id="llama-3.2-1b"):
    global llm_model, _llm_timer, _current_llm_id
    if _llm_timer is not None:
        _llm_timer.cancel()
        
    if llm_model is None or _current_llm_id != model_id:
        if llm_model is not None: unload_llm()
        
        try:
            from llama_cpp import Llama
            from huggingface_hub import hf_hub_download
        except ImportError:
            print("llama-cpp-python or huggingface_hub not installed. AI Pack required.")
            return None
        
        models_dir = os.path.join(app.root_path, "ai_models")
        os.makedirs(models_dir, exist_ok=True)
        
        print(f"Loading Local LLM ({model_id})...")
        if model_id == "llama-3-8b":
            repo_id = "QuantFactory/Meta-Llama-3-8B-Instruct-GGUF"
            filename = "Meta-Llama-3-8B-Instruct.Q4_K_M.gguf"
        else: # Default: Llama 3.2 1B
            repo_id = "bartowski/Llama-3.2-1B-Instruct-GGUF"
            filename = "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
            
        model_path = os.path.join(models_dir, filename)
        if not os.path.exists(model_path):
            print(f"Downloading {filename} from HuggingFace (First time only)...")
            hf_hub_download(repo_id=repo_id, filename=filename, local_dir=models_dir)
            
        # Initialize Llama model
        llm_model = Llama(
            model_path=model_path,
            n_gpu_layers=-1, # Auto-detect GPU if possible
            n_ctx=4096,
            verbose=False
        )
        _current_llm_id = model_id
        
    _llm_timer = threading.Timer(MODEL_UNLOAD_TIMEOUT, unload_llm)
    _llm_timer.daemon = True
    _llm_timer.start()
    return llm_model

def llm_generate(prompt, system_prompt="You are a helpful AI assistant.", model_id="llama-3.2-1b"):
    llm = get_llm(model_id)
    if not llm:
        return "AI Engine pack required for local LLM generation."
    response = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=1024
    )
    if isinstance(response, dict):
        content = response.get('choices', [{}])[0].get('message', {}).get('content')
        return (content or "").strip()
    return ""

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
        
        cmd = [
            ffmpeg_exe, '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
            '-s', f'{target_width}x{height}', '-pix_fmt', 'bgr24', '-r', str(fps),
            '-i', '-', '-i', input_path, '-map', '0:v', '-map', '1:a?', 
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '17', '-pix_fmt', 'yuv420p', '-c:a', 'copy',
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
        
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"[dynamic_auto_crop error] {e}")
        return False

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_BYTES

# Auto-update yt-dlp once per day
update_flag_file = os.path.join(DEFAULT_SAVE_DIR, ".last_update")
should_update = True
if os.path.exists(update_flag_file):
    last_update = os.path.getmtime(update_flag_file)
    if time.time() - last_update < UPDATE_CHECK_INTERVAL:
        should_update = False

if should_update:
    print("Checking for yt-dlp updates...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp", "-q"])
    with open(update_flag_file, 'w') as f:
        f.write(str(time.time()))
else:
    print("yt-dlp update check skipped (already checked today).")

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
        abs_path = os.path.abspath(path)
        win_dir = os.environ.get('WINDIR', 'C:\\Windows')
        if os.name == 'nt' and abs_path.lower().startswith(win_dir.lower()):
            return False
        return True
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

APP_VERSION = "2.2"

@app.route('/')
def index():
    return render_template('index.html', version=APP_VERSION)


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
    format_opt = request.form.get('format')
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
    llm_model = request.form.get('llmModel', 'none')
    trim_start = request.form.get('trimStart')
    trim_end = request.form.get('trimEnd')
    compress_opt = request.form.get('compress')
    
    if not files or files[0].filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    output_dir = os.path.join(os.path.expanduser("~"), "Documents", "Media Grabber", "Conversions")
    os.makedirs(output_dir, exist_ok=True)
    
    # Save files synchronously before background thread
    saved_files = []
    # uuid is imported at the top of the file
    shared_temp_dir = tempfile.mkdtemp()
    for f in files:
        if f.filename:
            input_ext = os.path.splitext(f.filename)[1].lower()
            base_name = os.path.splitext(f.filename)[0]
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
        
        def run_conv():
            total = len(saved_files)
            failed_count = 0
            
            for idx, file_data in enumerate(saved_files, 1):
                prefix = f"[{idx}/{total}] " if total > 1 else ""
                q.put({"status": f"{prefix}Processing {file_data['original_name']}..."})
                
                input_ext = file_data['input_ext']
                base_name = file_data['base_name']
                input_path = file_data['path']
                
                output_name = f"{base_name}_converted.{format_opt}"
                output_path = os.path.join(output_dir, output_name)
                
                # Prevent overwriting existing files in bulk directory
                counter = 1
                while os.path.exists(output_path):
                    output_name = f"{base_name}_converted_{counter}.{format_opt}"
                    output_path = os.path.join(output_dir, output_name)
                    counter += 1
                
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                
                try:
                    # 0. Frame-Accurate Clip Trimming (Calculates exact duration from start to end)
                    if total == 1 and (trim_start or trim_end):
                        start_s = parse_time_seconds(trim_start)
                        end_s = parse_time_seconds(trim_end)
                        if (start_s is not None and start_s > 0) or end_s is not None:
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
                            
                            trim_cmd.extend(["-i", input_path, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "17", "-c:a", "aac", trimmed_temp_path])
                            
                            res = subprocess.run(trim_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                            if res.returncode == 0 and os.path.exists(trimmed_temp_path) and os.path.getsize(trimmed_temp_path) > 0:
                                input_path = trimmed_temp_path
                            else:
                                print(f"Trim notice: {res.stderr}")
                    vf_filters = []
                    crf_val = "23" # Default standard quality
                    
                    # 1. Smart Auto-Crop or Aspect Ratio Crop/Pad
                    if autocrop and format_opt not in ["mp3", "wav"] and input_ext not in [".mp3", ".wav", ".jpg", ".png", ".webp"]:
                        temp_crop_path = os.path.join(shared_temp_dir, f"{uuid.uuid4().hex}_precrop.mp4")
                        if dynamic_auto_crop(input_path, temp_crop_path, q, prefix, tracking_mode=tracking_mode, target_x=target_x):
                            input_path = temp_crop_path
                            # dynamic_auto_crop already crops to 9:16
                        else:
                            vf_filters.append("crop=trunc(ih*9/16/2)*2:trunc(ih/2)*2")
                    elif resize and resize != "none" and format_opt not in ["mp3", "wav"]:
                        if resize == "crop_9_16":
                            vf_filters.append("crop=trunc(ih*9/16/2)*2:trunc(ih/2)*2")
                        elif resize == "pad_9_16":
                            vf_filters.append("scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2")
                        elif resize == "crop_16_9":
                            vf_filters.append("crop=trunc(iw/2)*2:trunc(iw*9/16/2)*2")
                        elif resize == "pad_16_9":
                            vf_filters.append("scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2")
                        elif resize == "crop_1_1":
                            vf_filters.append("crop=trunc(min(iw\\,ih)/2)*2:trunc(min(iw\\,ih)/2)*2")
                        elif resize == "crop_4_5":
                            vf_filters.append("crop=trunc(ih*4/5/2)*2:trunc(ih/2)*2")
                        elif resize == "pad_blur_9_16":
                            vf_filters.append("split[original][copy];[copy]scale=-2:1920,crop=1080:1920,boxblur=20:5[bg];[original]scale=1080:1920:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")

                    # 2. File Size & Resolution Scaling (MB Reduction)
                    if compress_opt and compress_opt != "none" and format_opt not in ["mp3", "wav"]:
                        if compress_opt == "scale_1080p":
                            vf_filters.append("scale='min(1080,iw)':'min(1920,ih)':force_original_aspect_ratio=decrease")
                        elif compress_opt == "scale_720p":
                            vf_filters.append("scale='min(720,iw)':'min(1280,ih)':force_original_aspect_ratio=decrease")
                            crf_val = "26"
                        elif compress_opt == "scale_480p":
                            vf_filters.append("scale='min(480,iw)':'min(854,ih)':force_original_aspect_ratio=decrease")
                            crf_val = "28"
                        elif compress_opt == "scale_50":
                            vf_filters.append("scale=iw*0.5:ih*0.5")
                            crf_val = "26"
                        elif compress_opt == "scale_25":
                            vf_filters.append("scale=iw*0.25:ih*0.25")
                            crf_val = "28"
                        elif compress_opt == "compress_high":
                            crf_val = "28" # ~50% MB size reduction
                            if format_opt == "gif":
                                vf_filters.append("scale=iw*0.5:ih*0.5")
                        elif compress_opt == "compress_web":
                            crf_val = "32" # ~75% MB size reduction (Web/Discord)
                            if format_opt == "gif":
                                vf_filters.append("scale=iw*0.33:ih*0.33")
                        elif compress_opt == "compress_80":
                            crf_val = "33" # ~80% MB size reduction
                            if format_opt == "gif":
                                vf_filters.append("scale=iw*0.27:ih*0.27")
                        elif compress_opt == "compress_85":
                            crf_val = "34" # ~85% MB size reduction
                            if format_opt == "gif":
                                vf_filters.append("scale=iw*0.21:ih*0.21")
                        elif compress_opt == "compress_extreme":
                            crf_val = "36" # ~90% MB size reduction
                            if format_opt == "gif":
                                vf_filters.append("scale=iw*0.15:ih*0.15")
                    
                    # Audio formats (ignore video filters)
                    if format_opt in ["mp3", "wav"]:
                        cmd = [ffmpeg_exe, "-y", "-i", input_path]
                        if format_opt == "mp3":
                            cmd.extend(["-vn", "-acodec", "libmp3lame", "-q:a", "2"])
                        else:
                            cmd.extend(["-vn", "-acodec", "pcm_s16le"])
                    else:
                        # Video or Image formats
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
                                    model = get_whisper()
                                    if not model:
                                        q.put({"status": f"{prefix}Whisper AI Pack not installed. Skipping subtitles."})
                                    else:
                                        result = model.transcribe(temp_audio, verbose=False)
                                    

                                         
                                        with open(temp_srt, 'w', encoding='utf-8') as f:
                                            for i, segment in enumerate(result.get('segments', [])):
                                                f.write(f"{i + 1}\n")
                                                f.write(f"{format_srt_timestamp(segment['start'])} --> {format_srt_timestamp(segment['end'])}\n")
                                                f.write(f"{segment['text'].strip()}\n\n")
                                            
                                    if translate_lang and translate_lang != 'none' and llm_model and llm_model != 'none':
                                        q.put({"status": f"{prefix}Translating Subtitles to {translate_lang}..."})
                                        try:
                                            with open(temp_srt, 'r', encoding='utf-8') as tf:
                                                srt_content = tf.read()
                                            sys_p = f"You are a professional subtitle translator. Translate the following .srt file to {translate_lang}. Maintain the exact SRT formatting and timestamps. Output ONLY the translated SRT text."
                                            translated_srt = llm_generate(srt_content, sys_p, llm_model)
                                            with open(temp_srt, 'w', encoding='utf-8') as tf:
                                                tf.write(translated_srt)
                                        except Exception as e:
                                            print(f"Translation Error: {e}")
                                            
                                    if burn_subtitles:
                                        srt_escaped = temp_srt.replace('\\', '\\\\').replace(':', '\\:')
                                        vf_filters.append(f"subtitles='{srt_escaped}':force_style='FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2'")
                                except Exception as e:
                                    print("Subtitle error:", e)

                        cmd = [ffmpeg_exe, "-y", "-i", input_path]
                        if format_opt in ["mp4", "mkv", "mov", "avi"]:
                            vf_filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
                        if vf_filters:
                            cmd.extend(["-vf", ",".join(vf_filters)])
                            
                        if format_opt in ["mp4", "mkv", "mov", "avi"]:
                            cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", crf_val, "-c:a", "aac", "-pix_fmt", "yuv420p"])
                        elif format_opt == "webm":
                            cmd.extend(["-c:v", "libvpx", "-c:a", "libvorbis", "-crf", crf_val])
                        elif format_opt == "gif":
                            cmd.extend(["-r", "15"]) 
                        elif format_opt in ["jpg", "png", "webp"]:
                            if input_ext in ['.mp4', '.mov', '.mkv', '.webm', '.avi']:
                                cmd.extend(["-vframes", "1"])
                        else:
                            raise Exception("Invalid format")
                            
                    cmd.append(output_path)
                    
                    q.put({"status": f"{prefix}Encoding..."})
                    try:
                        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
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
                    q.put({"status": f"{prefix}Error converting file."})
                    with open(os.path.join(DEFAULT_SAVE_DIR, "converter_debug.log"), "a", encoding="utf-8", errors="replace") as f:
                        f.write(f"Conversion Error:\n{traceback.format_exc()}\n")
                    time.sleep(3)
                    
            invalidate_gallery_cache()
            if failed_count == 0:
                last_path = output_path if 'output_path' in locals() and os.path.exists(output_path) else output_dir
                q.put({"status": f"Successfully saved to {output_dir}", "done": True, "file_path": last_path, "output_path": output_dir})
            else:
                q.put({"error": f"{failed_count} file(s) failed to convert. Check console logs."})
            

            try: shutil.rmtree(shared_temp_dir)
            except Exception: pass

        t = threading.Thread(target=run_conv, daemon=True)
        t.start()
        
        while True:
            try:
                msg = q.get(timeout=120)
            except queue.Empty:
                yield f"data: {json.dumps({'error': 'Task timed out.'})}\n\n"
                break
            yield f"data: {json.dumps(msg)}\n\n"
            if msg.get("done") or msg.get("error"):
                break
                
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/cancel/<task_id>', methods=['POST'])
def cancel_task(task_id):
    cancel_flags[task_id] = True
    return jsonify({"success": True})

@app.route('/api/preview', methods=['POST'])
def preview_url():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        return jsonify({"error": "Invalid URL scheme"}), 400
        
    try:
        ydl_opts: dict[str, Any] = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'dump_single_json': True,
            'skip_download': True
        }
        with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:
            info = ydl.extract_info(url, download=False)
            
            return jsonify({
                "title": info.get('title', 'Unknown Title'),
                "uploader": info.get('uploader', 'Unknown Creator'),
                "thumbnail": info.get('thumbnail', ''),
                "duration": info.get('duration', 0)
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download_video():
    data = request.json
    urls_raw = data.get('url', '')
    output_path = data.get('path')
    custom_name = data.get('filename')
    browser = data.get('browser')
    task_id = data.get('task_id', 'unknown')
    processing_options = data.get('processing_options', {})

    # Ensure task is not cancelled before starting
    cancel_flags[task_id] = False

    urls = [u.strip() for u in urls_raw.split('\n') if u.strip().startswith(('http://', 'https://'))]

    if not urls:
        return jsonify({"error": "Valid URL(s) required"}), 400
        
    url = urls[0] # keeping url for downstream variable references, but loop uses urls
    if not output_path or not output_path.strip():
        output_path = os.path.join(os.path.expanduser("~"), "Documents", "Media Grabber")
        
    url_lower = url.lower()
    if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        output_path = os.path.join(output_path, 'YouTube')
    elif 'instagram.com' in url_lower:
        output_path = os.path.join(output_path, 'Instagram')
    elif 'tiktok.com' in url_lower:
        output_path = os.path.join(output_path, 'TikTok')
    elif 'twitter.com' in url_lower or 'x.com' in url_lower:
        output_path = os.path.join(output_path, 'Twitter')
    else:
        output_path = os.path.join(output_path, 'Other')
        
    os.makedirs(output_path, exist_ok=True)

    def generate():
        yield f"data: {json.dumps({'status': 'Fetching metadata...'})}\n\n"
        
        quality = processing_options.get('quality', 'max')
        force_h264 = processing_options.get('forceH264', False)
        
        # Build format selector based on user preference
        if quality == 'audio_only':
            fmt_str = 'bestaudio/best'
        elif quality in ['2160', '1440', '1080', '720', '480']:
            h = quality
            fmt_str = f'bestvideo[height<={h}]+bestaudio[ext=m4a]/bestvideo[height<={h}]+bestaudio/best[height<={h}]/best'
        else: # 'max' / default: True maximum resolution available (4K, 1440p, 1080p60)
            fmt_str = 'bestvideo+bestaudio[ext=m4a]/bestvideo+bestaudio/best'

        ydl_opts: dict[str, Any] = {
            'format': fmt_str,
            'merge_output_format': 'mp4',
            'outtmpl': os.path.join(output_path, '%(playlist_title,uploader)s', '%(playlist_index|)s%(playlist_index& - |)s%(title)s_%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe(),
            'retries': 10,
            'fragment_retries': 10,
            'socket_timeout': 30,
            'js_runtimes': {'node': {}},
            'remote_components': ['ejs:github']
        }

        if quality == 'audio_only':
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320'
            }]
        elif force_h264:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4'
            }]

        if custom_name:
            clean_name = sanitize_filename(custom_name)
            if clean_name:
                ydl_opts['outtmpl'] = os.path.join(output_path, '%(playlist_title,uploader)s', f'%(playlist_index|)s%(playlist_index& - |)s{clean_name}_%(id)s.%(ext)s')
                
        if browser and browser != 'none':
            if browser == 'cookies.txt':
                ydl_opts['cookiefile'] = 'cookies.txt'
            else:
                ydl_opts['cookiesfrombrowser'] = (browser, None, None, None)
                
            # Add a random 5 to 15 second delay between downloads to simulate human behavior and prevent bans
            ydl_opts['sleep_interval'] = 5
            ydl_opts['max_sleep_interval'] = 15

        q = queue.Queue()

        def hook(d):
            if cancel_flags.get(task_id):
                raise Exception("Cancelled by user")
                
            if d['status'] == 'downloading':
                percent = d.get('_percent_str', '0%').strip()
                percent = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', percent)
                speed = d.get('_speed_str', '').strip()
                speed = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', speed)
                speed_text = f" at {speed}" if speed else ""
                q.put({"status": f"Downloading: {percent}{speed_text}"})
            elif d['status'] == 'finished':
                q.put({"status": "Merging files..."})
            elif d['status'] == 'error':
                q.put({"error": "Download failed inside hook"})

        ydl_opts['progress_hooks'] = [hook]

        def run_dl():
            total = len(urls)
            failed_count = 0
            last_final_path = None
            for idx, url in enumerate(urls, 1):
                prefix = f"[{idx}/{total}] " if total > 1 else ""
                q.put({"status": f"{prefix}Starting download..."})
                try:
                    with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:
                        try:
                            # Pre-flight check for file collisions to add (1) to filename
                            actual_download_path = None
                            info_dict = ydl.extract_info(url, download=False)
                            if info_dict:
                                temp_final = ydl.prepare_filename(cast(Any, info_dict))
                                base, ext = os.path.splitext(temp_final)
                                if os.path.exists(temp_final) or os.path.exists(base + ".mp4"):
                                    orig_base = base
                                    c = 1
                                    while os.path.exists(f"{orig_base} ({c}){ext}") or os.path.exists(f"{orig_base} ({c}).mp4"):
                                        c += 1
                                    
                                    local_opts: dict[str, Any] = ydl_opts.copy()
                                    local_opts['outtmpl'] = f"{orig_base} ({c}).%(ext)s"
                                    actual_download_path = f"{orig_base} ({c}).mp4"
                                    with yt_dlp.YoutubeDL(cast(Any, local_opts)) as local_ydl:
                                        info: Any = local_ydl.extract_info(url, download=True)
                                else:
                                    info: Any = ydl.extract_info(url, download=True)
                            else:
                                info: Any = ydl.extract_info(url, download=True)
                        except Exception as e:
                            err_msg = str(e)
                            err_msg = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', err_msg)
                            
                            if "Could not copy Chrome cookie database" in err_msg or "database is locked" in err_msg:
                                q.put({"status": f"{prefix}Error: Close Chrome entirely to use its cookies!"})
                                failed_count += 1
                                time.sleep(4)
                                continue
                            
                            if "No video formats found" in err_msg or "Unable to extract data" in err_msg or "HTTP Error 400" in err_msg or "Video info extraction failed" in err_msg:
                                q.put({"status": f"{prefix}Unsupported by yt-dlp. Downloading via gallery-dl..."})
                                
                                gdl_cmd = [sys.executable, "-m", "gallery_dl", "-d", output_path]
                                if browser and browser != 'none':
                                    if browser == 'cookies.txt':
                                        gdl_cmd.extend(["--cookies", "cookies.txt"])
                                    else:
                                        gdl_cmd.extend(["--cookies-from-browser", browser])
                                gdl_cmd.append(url)
                                
                                try:
                                    process = subprocess.Popen(gdl_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                                    if process.stdout:
                                        for line in iter(process.stdout.readline, ''):
                                            if cancel_flags.get(task_id):
                                                process.terminate()
                                                q.put({"status": f"{prefix}Cancelled by user"})
                                                break
                                            
                                            line = line.strip()
                                            if line:
                                                short_line = line if len(line) < 60 else "..." + line[-57:]
                                                q.put({"status": f"gallery-dl: {short_line}"})
                                                
                                        process.stdout.close()
                                    return_code = process.wait()
                                    
                                    if return_code == 0:
                                        q.put({"status": f"{prefix}Successfully downloaded images/profile!"})
                                        add_history_entry(url, url, "Unknown", output_path, "Other")
                                        save_url_shortcut(output_path, url)
                                        time.sleep(2)
                                        continue
                                    else:
                                        q.put({"status": f"{prefix}Gallery-DL failed."})
                                        failed_count += 1
                                        time.sleep(4)
                                        continue
                                except Exception as gdl_err:
                                    q.put({"status": f"{prefix}Gallery-DL Error: {str(gdl_err)}"})
                                    failed_count += 1
                                    time.sleep(4)
                                    continue

                            q.put({"status": f"{prefix}Error: {err_msg}"})
                            failed_count += 1
                            time.sleep(4)
                            continue
                            
                        if not info:
                            q.put({"status": f"{prefix}Failed. No video found."})
                            failed_count += 1
                            time.sleep(4)
                            continue
                            
                        if info.get('_type') == 'playlist' or info.get('_type') == 'multi_video':
                            continue
                            
                        # Determine the final file path
                        final_path: Optional[str] = None
                        if isinstance(info, dict) and 'requested_downloads' in info and info['requested_downloads']:
                            req_dl = info['requested_downloads'][0]
                            if isinstance(req_dl, dict) and req_dl.get('filepath'):
                                final_path = str(req_dl['filepath'])
                        if not final_path and isinstance(info, dict):
                            fn = info.get('_filename') or (actual_download_path if actual_download_path and os.path.exists(actual_download_path) else None) or ydl.prepare_filename(cast(Any, info))
                            if fn:
                                final_path = str(fn)
                            
                        # Handle edge case where file was merged to .mp4 but info holds original extension
                        if final_path:
                            base, _ = os.path.splitext(final_path)
                            if not os.path.exists(final_path) and os.path.exists(base + ".mp4"):
                                final_path = base + ".mp4"
                        elif actual_download_path and os.path.exists(actual_download_path):
                            final_path = actual_download_path

                        if final_path and os.path.exists(final_path):
                            last_final_path = final_path

                        # Add to history & save URL shortcut IMMEDIATELY (never skipped!)
                        title = info.get('title', 'Unknown Title') if isinstance(info, dict) else 'Unknown Title'
                        uploader = info.get('uploader', 'Unknown') if isinstance(info, dict) else 'Unknown'
                        platform = info.get('extractor_key', 'Other') if isinstance(info, dict) else 'Other'
                        add_history_entry(url, title, uploader, final_path or output_path, platform)
                        if final_path and os.path.exists(final_path):
                            save_url_shortcut(final_path, url)
                        invalidate_gallery_cache()
                                
                        if final_path and os.path.exists(final_path):
                            base, _ = os.path.splitext(final_path)
                            # Extract first frame
                            if processing_options.get('extractFrame', True):
                                q.put({"status": f"{prefix}Extracting frame..."})
                                frame_path = base + "_first_frame.jpg"
                                ffmpeg_cmd = [
                                    imageio_ffmpeg.get_ffmpeg_exe(),
                                    "-y", 
                                    "-i", final_path,
                                    "-vframes", "1",
                                    "-q:v", "2",
                                    frame_path
                                ]
                                subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                
                            if processing_options.get('autoExtractPrompt'):
                                q.put({"status": f"{prefix}Extracting AI Prompt (BLIP)..."})
                                try:
                                    from ai_prompter import extract_prompt_from_image
                                    target_image = frame_path if os.path.exists(frame_path) else final_path
                                    if os.path.exists(target_image):
                                        prompt_text = extract_prompt_from_image(target_image)
                                        
                                        llm_model_choice = processing_options.get('llmModel', 'none')
                                        if llm_model_choice and llm_model_choice != 'none':
                                            q.put({"status": f"{prefix}Enhancing prompt with Local LLM..."})
                                            sys_p = "You are an expert AI prompt engineer. Take the basic image description and rewrite it into a highly detailed, professional prompt optimized for Nano Banana Pro and Nano Banana 2 image generation models. Focus on lighting, mood, camera angles, and high quality keywords. Output ONLY the prompt text, nothing else."
                                            try:
                                                prompt_text = llm_generate(prompt_text, sys_p, llm_model_choice)
                                            except Exception as e:
                                                print(f"LLM Enhancement Error: {e}")
                                        
                                        prompt_txt_path = base + "_prompt.txt"
                                        with open(prompt_txt_path, "w", encoding="utf-8") as f:
                                            f.write(prompt_text)
                                except Exception as e:
                                    q.put({"status": f"{prefix}Prompt Extraction Error: {str(e)}"})
                            
                            # Audio Recognition & Metadata
                            if processing_options.get('identifySong', True):
                                q.put({"status": f"{prefix}Identifying song & metadata..."})
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
                                        f.write(f" Shazam Match:\n")
                                        f.write(f"Song: {shazam_track}\n")
                                        f.write(f"Artist: {shazam_artist}\n\n")
                                    else:
                                        f.write(f" Shazam Match: No match found.\n\n")
                                        
                                    f.write(f" Original Upload Metadata (yt-dlp):\n")
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

                            if want_transcribe or want_summarize or want_burn or want_export:
                                q.put({"status": f"{prefix}Transcribing speech..."})
                                transcript_path = base + "_transcript.txt"
                                full_audio = base + "_full_audio.mp3"
                                
                                ffmpeg_full_audio = [
                                    imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", final_path,
                                    "-vn", "-acodec", "libmp3lame", full_audio
                                ]
                                subprocess.run(ffmpeg_full_audio, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                
                                if os.path.exists(full_audio):
                                    try:
                                        model = get_whisper()
                                        transcript_text = ""
                                        result: dict[str, Any] = {}
                                        if not model:
                                            q.put({"status": f"{prefix}Whisper AI Pack not installed. Skipping transcription/subtitles."})
                                        else:
                                            result = model.transcribe(full_audio, verbose=False)
                                            transcript_text = result.get("text", "").strip()
                                        if want_transcribe and transcript_text:
                                            with open(transcript_path, "w", encoding="utf-8") as f:
                                                f.write(transcript_text)
                                            
                                        if want_summarize and transcript_text:
                                            llm_model_choice = processing_options.get('llmModel', 'none')
                                            if llm_model_choice and llm_model_choice != 'none':
                                                q.put({"status": f"{prefix}Generating AI Summary & SEO Tags..."})
                                                sys_p = "You are an expert social media manager. Read the video transcript and output: 1) A clean, bulleted summary of key points. 2) 3 viral TikTok/Reels captions. 3) SEO-optimized hashtags."
                                                try:
                                                    summary_text = llm_generate(transcript_text, sys_p, llm_model_choice)
                                                    summary_path = base + "_AI_Summary.txt"
                                                    with open(summary_path, "w", encoding="utf-8") as sf:
                                                        sf.write(summary_text)
                                                except Exception as e:
                                                    print(f"LLM Summarize Error: {e}")
                                            
                                        
                                        if (want_burn or want_export) and final_path and final_path.endswith(('.mp4', '.mkv', '.mov')) and result:
                                            srt_path = base + "_subtitles.srt"

                                                
                                            with open(srt_path, "w", encoding="utf-8") as srt_f:
                                                raw_segs = result.get("segments", [])
                                                segments = raw_segs if isinstance(raw_segs, list) else []
                                                for i, segment in enumerate(segments, start=1):
                                                    if not isinstance(segment, dict):
                                                        continue
                                                    seg_start = float(segment.get('start', 0.0))
                                                    seg_end = float(segment.get('end', 0.0))
                                                    seg_text = str(segment.get('text', '')).strip()
                                                    srt_f.write(f"{i}\n")
                                                    srt_f.write(f"{format_srt_timestamp(seg_start)} --> {format_srt_timestamp(seg_end)}\n")
                                                    srt_f.write(f"{seg_text}\n\n")
                                                    
                                            if want_burn:
                                                q.put({"status": f"{prefix}Burning subtitles into video..."})
                                                temp_sub = base + "_subbed.mp4"
                                                rel_srt = os.path.relpath(srt_path).replace('\\', '/')
                                                rel_srt = rel_srt.replace(':', '\\:').replace(',', '\\,').replace("'", "\\'")
                                                
                                                ffmpeg_sub = [
                                                    imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", final_path,
                                                    "-vf", f"subtitles='{rel_srt}'", "-c:a", "copy", temp_sub
                                                ]
                                                subprocess.run(ffmpeg_sub, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                if os.path.exists(temp_sub):
                                                    os.replace(temp_sub, final_path)
                                            
                                            if not want_export and os.path.exists(srt_path):
                                                try: os.remove(srt_path)
                                                except Exception: pass
                                                
                                    except Exception as e:
                                        print("Whisper error:", e)
                                    try:
                                        os.remove(full_audio)
                                    except Exception:
                                        pass
                                        
                            # Force H.264 Encoding (Fixes AI tool compatibility)
                            if processing_options.get('forceH264') and final_path and final_path.endswith('.mp4'):
                                q.put({"status": f"{prefix}Forcing Standard Encoding (H.264)..."})
                                temp_h264 = base + "_h264_temp.mp4"
                                ffmpeg_h264_cmd = [
                                    imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", final_path,
                                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                                    "-c:a", "aac", "-pix_fmt", "yuv420p", "-movflags", "+faststart", temp_h264
                                ]
                                subprocess.run(ffmpeg_h264_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                if os.path.exists(temp_h264):
                                    os.replace(temp_h264, final_path)
                                    
                            # AI Bypass (Clean & Scramble)
                            if processing_options.get('aiBypass') and final_path:
                                q.put({"status": f"{prefix}Applying AI Bypass (Scramble & Clean)..."})
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
                                    q.put({"status": f"{prefix}AI Bypass Failed: {msg}"})
                except Exception as e:
                    error_msg = str(e)
                    error_msg = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', error_msg)
                    q.put({"status": f"{prefix}Error: {error_msg}"})
                    
            invalidate_gallery_cache()
            if failed_count == 0:
                q.put({"status": "All Downloads Complete!", "done": True, "file_path": last_final_path, "output_path": output_path})
            else:
                q.put({"status": f"Complete! ({failed_count} failed)", "done": True, "file_path": last_final_path, "output_path": output_path})

        t = threading.Thread(target=run_dl, daemon=True)
        t.start()

        try:
            while True:
                try:
                    msg = q.get(timeout=120)
                except queue.Empty:
                    yield f"data: {json.dumps({'error': 'Task timed out.'})}\n\n"
                    break
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("done") or msg.get("error") or msg.get("action_required"):
                    break
        finally:
            if task_id in cancel_flags:
                del cancel_flags[task_id]

    return Response(generate(), mimetype='text/event-stream')




_gallery_cache: dict[str, Any] = {"time": 0.0, "data": []}

@app.route('/api/gallery', methods=['GET'])
def list_gallery():
    global _gallery_cache
    if time.time() - _gallery_cache["time"] < GALLERY_CACHE_TTL:
        return jsonify(_gallery_cache["data"])
        
    base_dir = os.path.join(os.path.expanduser("~"), "Documents", "Media Grabber")
    known_order = ['YouTube', 'Instagram', 'TikTok', 'Twitter', 'Conversions', 'AI Cleaned', 'Other']
    
    # Dynamically find all subfolders in Media Grabber
    existing_dirs = []
    if os.path.exists(base_dir):
        existing_dirs = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
        
    folders = [f for f in known_order if f in existing_dirs] + [f for f in existing_dirs if f not in known_order]
    if not folders:
        folders = known_order
    
    media = []
    history_data = load_history(reconcile=False)
    
    for folder in folders:
        folder_path = os.path.join(base_dir, folder)
        if os.path.exists(folder_path):
            for root, _, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    if os.path.isfile(file_path):
                        ext = os.path.splitext(file)[1].lower()
                        if ext in ['.mp4', '.mov', '.mkv', '.webm', '.avi', '.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp3']:
                            rel_dir = os.path.relpath(root, folder_path)
                            if rel_dir == '.':
                                item_path = file
                            else:
                                item_path = f"{rel_dir}/{file}".replace('\\', '/')
                            
                            source_url, uploader = resolve_source_url(file_path, history_data)
                            
                            media.append({
                                "name": file,
                                "folder": folder,
                                "path": f"{folder}/{item_path}",
                                "full_path": file_path,
                                "type": "video" if ext in ['.mp4', '.mov', '.mkv', '.webm', '.avi'] else "audio" if ext == ".mp3" else "image",
                                "timestamp": os.path.getmtime(file_path),
                                "size": os.path.getsize(file_path),
                                "source_url": source_url,
                                "uploader": uploader
                            })
                        
    media.sort(key=lambda x: x['timestamp'], reverse=True)
    _gallery_cache["time"] = time.time()
    _gallery_cache["data"] = media
    return jsonify(media)

@app.route('/api/media/<path:filename>')
def serve_media(filename):
    base_dir = os.path.join(os.path.expanduser("~"), "Documents", "Media Grabber")
    norm = os.path.normpath(filename)
    if norm.startswith('..') or norm.startswith('/') or norm.startswith('\\'):
        abort(403)
    full_path = os.path.join(base_dir, norm)
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        abort(404)
    return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path))

@app.route('/api/open_folder', methods=['POST'])
def open_folder():
    path = request.json.get('path') if request.json else None
    if not path or not is_safe_path(path):
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
                subprocess.Popen(f'explorer /select,"{abs_path}"')
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
    if not path or not is_safe_path(path) or not os.path.exists(path):
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

@app.route('/api/extract_prompt', methods=['POST'])
def extract_prompt():
    data = request.json
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
        from ai_prompter import extract_prompt_from_image, is_ai_vision_available
        if not is_ai_vision_available():
            return jsonify({
                "error": "ai_pack_required", 
                "message": "AI Vision Engine pack is required for prompt extraction."
            }), 400
        prompt = extract_prompt_from_image(target_image)
        return jsonify({"prompt": prompt})
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
    if not path or not os.path.exists(path) or not os.path.isfile(path) or not is_safe_path(path):
        return "Not found or forbidden", 403
    return send_file(path)

@app.route('/api/batch_clean', methods=['POST'])
def batch_clean():
    data = request.json
    target_dirs = data.get('target_dirs', [])
    inject_exif = data.get('inject_exif', False)
    
    output_dir = os.path.join(DEFAULT_SAVE_DIR, "AI Cleaned")
    
    try:
        from cleaner import run_batch_cleaner
        return Response(run_batch_cleaner(target_dirs, output_dir, is_upload=False, inject_exif=inject_exif), mimetype='text/event-stream')
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
        

    upload_folder = os.path.join(DEFAULT_SAVE_DIR, "AI Cleaned", f"Uploaded_{int(time.time())}")
    os.makedirs(upload_folder, exist_ok=True)
    
    uploaded_paths = []
    for file in files:
        if file and file.filename:
            filename = secure_filename(file.filename)
            file_path = os.path.join(upload_folder, filename)
            file.save(file_path)
            uploaded_paths.append(file_path)
            
    try:
        from cleaner import run_batch_cleaner
        return Response(run_batch_cleaner(uploaded_paths, upload_folder, is_upload=True, inject_exif=inject_exif), mimetype='text/event-stream')
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
    if not path or not os.path.exists(path) or not is_safe_path(path):
        return jsonify({"error": "File not found or forbidden"}), 403
        
    try:
        from send2trash import send2trash
        send2trash(path)
    except Exception:
        try:
            os.remove(path)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    invalidate_gallery_cache()
    return jsonify({"success": True})

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
            for item in list(log_capture.logs)[-80:]:
                yield f"data: {json.dumps(item)}\n\n"
            log_capture.subscribers.append(q)
        try:
            while True:
                item = q.get()
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
    "log": []
}

def get_ai_status():
    st = {
        "whisper": False,
        "torch": False,
        "transformers": False,
        "llama": False,
        "all_installed": False
    }
    try:
        import whisper
        st["whisper"] = True
    except ImportError: pass
    
    try:
        import torch
        st["torch"] = True
    except ImportError: pass
    
    try:
        import transformers
        st["transformers"] = True
    except ImportError: pass
    
    try:
        import llama_cpp
        st["llama"] = True
    except ImportError: pass
    
    st["all_installed"] = st["whisper"] and st["torch"] and st["transformers"]
    return st

def run_ai_install_worker():
    global ai_installer_state
    ai_installer_state["is_installing"] = True
    ai_installer_state["status"] = "Installing AI Engine pack..."
    ai_installer_state["progress"] = 10
    ai_installer_state["error"] = None
    ai_installer_state["log"] = ["Starting AI Engine installation via pip..."]
    
    req_file = os.path.join(app.root_path, "requirements-ai.txt")
    if not os.path.exists(req_file):
        ai_installer_state["error"] = "requirements-ai.txt not found!"
        ai_installer_state["is_installing"] = False
        return

    cmd = [sys.executable, "-m", "pip", "install", "-r", req_file]
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        process = subprocess.Popen(
            cmd,
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
                        ai_installer_state["progress"] = 90
                        ai_installer_state["status"] = "Unpacking and configuring AI packages..."
                    elif "Successfully installed" in line_clean:
                        ai_installer_state["progress"] = 98

            process.stdout.close()
        code = process.wait()
        
        if code == 0:
            ai_installer_state["is_installing"] = False
            ai_installer_state["status"] = "complete"
            ai_installer_state["progress"] = 100
            ai_installer_state["log"].append("AI Engine Pack installed successfully!")
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
        "install_log": ai_installer_state["log"][-8:]
    })

@app.route('/api/install_ai', methods=['POST'])
def api_install_ai():
    global ai_installer_state
    if ai_installer_state["is_installing"]:
        return jsonify({"status": "already_running"}), 400
        
    t = threading.Thread(target=run_ai_install_worker, daemon=True)
    t.start()
    return jsonify({"status": "started"})

@app.route('/api/shutdown', methods=['POST'])
def shutdown_app():
    def do_shutdown():
        time.sleep(0.5)
        print("Shutting down Media Grabber server...", flush=True)
        os._exit(0)
    threading.Thread(target=do_shutdown, daemon=True).start()
    return jsonify({"status": "App shutting down..."})

@app.route('/api/health_check', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "version": APP_VERSION})

@app.route('/api/restart', methods=['POST'])
def restart_server():
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
    global app_updater_state
    app_updater_state["is_updating"] = True
    app_updater_state["progress"] = 5
    app_updater_state["status"] = "Connecting to GitHub..."
    app_updater_state["error"] = None
    app_updater_state["log"] = ["Starting Over-The-Air Update..."]

    try:
        import requests
        import zipfile
        import io

        # 1. Fetch latest release info to get zipball URL
        rel = fetch_latest_release(force=True)
        zip_url = rel.get("zipball_url")
        if not zip_url:
            raise Exception("Could not locate release archive URL on GitHub.")

        tag_name = rel.get("latest_version", "latest")
        app_updater_state["progress"] = 15
        app_updater_state["status"] = f"Downloading update {tag_name}..."
        app_updater_state["log"].append(f"Downloading release archive: {tag_name}")

        headers = {"User-Agent": "AI-Influencer-Media-Grabber-Updater"}
        resp = requests.get(zip_url, headers=headers, timeout=60, stream=True)
        if resp.status_code != 200:
            raise Exception(f"Failed to download release zip (status {resp.status_code})")

        content_chunks = []
        total_dl = 0
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                content_chunks.append(chunk)
                total_dl += len(chunk)
                app_updater_state["progress"] = min(55, 15 + int(total_dl / (3 * 1024 * 1024) * 40))

        zip_data = b"".join(content_chunks)
        app_updater_state["log"].append(f"Download complete ({len(zip_data) // 1024} KB). Extracting files...")
        app_updater_state["progress"] = 60
        app_updater_state["status"] = "Unpacking updated application files..."

        # 2. Extract into app root
        app_root = os.path.dirname(os.path.abspath(__file__))
        z = zipfile.ZipFile(io.BytesIO(zip_data))
        
        namelist = z.namelist()
        if not namelist:
            raise Exception("Downloaded release archive is empty.")
        top_prefix = namelist[0].split('/')[0] + '/'

        protected_prefixes = (
            '.venv',
            'python_runtime',
            'dist',
            '.git',
            'downloads',
            'cache',
            '.system_generated',
            'scratch'
        )

        extracted_count = 0
        req_changed = False
        old_req_content = ""
        req_path = os.path.join(app_root, "requirements.txt")
        if os.path.exists(req_path):
            try:
                with open(req_path, "r", encoding="utf-8") as f:
                    old_req_content = f.read().strip()
            except Exception: pass

        for member in z.infolist():
            if not member.filename.startswith(top_prefix):
                continue
            rel_path = member.filename[len(top_prefix):]
            if not rel_path or rel_path.endswith('/'):
                continue
            
            first_part = rel_path.split('/')[0]
            if first_part in protected_prefixes:
                continue

            target_path = os.path.join(app_root, *rel_path.split('/'))
            os.makedirs(os.path.dirname(target_path), exist_ok=True)

            with z.open(member) as src_f, open(target_path, "wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)
            extracted_count += 1

        app_updater_state["log"].append(f"Extracted {extracted_count} updated application files.")
        app_updater_state["progress"] = 85
        app_updater_state["status"] = "Checking dependencies..."

        # 3. Check if requirements.txt changed
        if os.path.exists(req_path):
            try:
                with open(req_path, "r", encoding="utf-8") as f:
                    new_req_content = f.read().strip()
                if new_req_content and new_req_content != old_req_content:
                    req_changed = True
            except Exception: pass

        if req_changed:
            app_updater_state["log"].append("Core requirements updated. Running pip install...")
            app_updater_state["status"] = "Updating Python dependencies..."
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_path, "-q"], check=False)
            except Exception as e:
                app_updater_state["log"].append(f"Pip note: {e}")

        app_updater_state["progress"] = 100
        app_updater_state["is_updating"] = False
        app_updater_state["status"] = "complete"
        app_updater_state["current_version"] = tag_name
        app_updater_state["has_update"] = False
        app_updater_state["log"].append(f"Successfully updated application to {tag_name}!")

    except Exception as e:
        app_updater_state["is_updating"] = False
        app_updater_state["status"] = "failed"
        app_updater_state["error"] = str(e)
        app_updater_state["log"].append(f"Update failed: {str(e)}")

@app.route('/api/check_update', methods=['GET', 'POST'])
def api_check_update():
    force = request.args.get('force') == '1' or request.method == 'POST'
    result = fetch_latest_release(force=force)
    return jsonify(result)

@app.route('/api/apply_update', methods=['POST'])
def api_apply_update():
    global app_updater_state
    if app_updater_state["is_updating"]:
        return jsonify({"status": "already_updating"}), 409
    threading.Thread(target=run_ota_update_worker, daemon=True).start()
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

if __name__ == '__main__':
    from waitress import serve
    print("\n" + "="*50, flush=True)
    print(" SERVER ONLINE AND READY! http://127.0.0.1:5000 ", flush=True)
    print("="*50 + "\n", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.25, open_desktop_window).start()
    serve(app, host='127.0.0.1', port=5000, threads=8)
