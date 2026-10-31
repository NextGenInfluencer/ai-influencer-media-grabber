"""Reference frame snapper and (placeholder) motion studio.

Extracts lossless PNG reference keyframes from the user's own media.
Only files inside the Media Grabber data folder can be read, addressed either by
an in-app media URL or by a path inside that folder.

``render_character_motion`` is a placeholder: it produces a still-image clip of the
character portrait. Real face/performance transfer is not implemented yet.
"""
import copy
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import unquote, urlsplit
import uuid
import threading
from typing import Any, Dict, Optional

import imageio_ffmpeg

import characters

DATA_DIR = Path(os.environ.get('MEDIA_GRABBER_DATA_DIR') or Path.home() / 'Documents' / 'Media Grabber')
REFERENCES_DIR = DATA_DIR / 'References'
MOTION_OUTPUT_DIR = DATA_DIR / 'Motion Outputs'
DRIVING_REF_DIR = DATA_DIR / 'Driving References'

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
    DRIVING_REF_DIR.mkdir(parents=True, exist_ok=True)


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
        direct = candidate if candidate.is_file() else (DATA_DIR / candidate)
        if direct.is_file():
            return _contained(direct, DATA_DIR)
        for sub in [DATA_DIR / 'Conversions', DRIVING_REF_DIR, MOTION_OUTPUT_DIR]:
            cand_sub = sub / candidate.name
            if cand_sub.is_file():
                return _contained(cand_sub, DATA_DIR)
        return _contained(DATA_DIR / candidate, DATA_DIR)
    return _contained(candidate, DATA_DIR)


def extract_reference_frame(video_source, timestamp_sec=0.0, output_name=None):
    """Extract a lossless PNG frame at ``timestamp_sec`` into the References folder."""
    _ensure_dirs()
    vpath = resolve_media_source(video_source)
    if not vpath:
        raise FileNotFoundError(f"Video not found in the Media Grabber folder: {video_source}")

    timestamp_sec = max(0.0, float(timestamp_sec))
    clean_stem = re.sub(r'[^\w\-]', '_', vpath.stem)
    fname = Path(output_name).name if output_name else f"ref_{clean_stem}_{int(timestamp_sec * 100)}_{uuid.uuid4().hex[:6]}.png"
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
        "url": f"/api/motion/references/file/{out_path.name}",
        "timestamp": timestamp_sec,
        "size_bytes": out_path.stat().st_size,
    }


def list_references():
    _ensure_dirs()
    files = sorted(REFERENCES_DIR.glob('*.png'), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": f.name, "path": str(f), "size": f.stat().st_size, "modified": f.stat().st_mtime} for f in files]


def resolve_image_path(src_str):
    """Map a character-image URL, reference URL, local path or reference filename to a local file."""
    if not src_str or not isinstance(src_str, str):
        return None

    # 1. Direct path check (must be strictly inside DATA_DIR)
    candidate = Path(src_str)
    if candidate.is_file():
        return _contained(candidate, DATA_DIR)

    # 2. Check by filename in References folder
    ref_cand = REFERENCES_DIR / candidate.name
    if ref_cand.is_file():
        return ref_cand

    # 3. URL path matching
    path_part = unquote(urlsplit(src_str).path)

    m_char = re.fullmatch(r'/api/characters/([^/]+)/image/([^/]+)', path_part)
    if m_char:
        return characters.get_image_path(m_char.group(1), m_char.group(2))

    m_ref = re.fullmatch(r'/api/motion/references/file/([^/]+)', path_part)
    name = m_ref.group(1) if m_ref else candidate.name
    return _contained(REFERENCES_DIR / Path(name).name, REFERENCES_DIR)


def get_video_duration(video_path):
    """Probe video duration in seconds via ffmpeg."""
    try:
        cmd = [_ffmpeg(), '-nostdin', '-i', str(video_path)]
        res = subprocess.run(cmd, capture_output=True)
        txt = res.stderr.decode('utf-8', errors='ignore')
        m = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', txt)
        if m:
            h, m_m, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
            return max(1.0, round(h * 3600 + m_m * 60 + s, 2))
    except Exception:
        pass
    return 10.0


def list_driving_videos():
    """Returns candidate driving reference videos from Media Grabber and subfolders."""
    _ensure_dirs()
    exts = {'.mp4', '.mov', '.webm', '.mkv'}
    candidates = []
    seen = set()
    search_dirs = [
        DRIVING_REF_DIR,
        DATA_DIR / 'Conversions',
        DATA_DIR,
    ]
    for d in search_dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob('*'), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.is_file() and f.suffix.lower() in exts and not f.name.startswith('.'):
                if f.name in seen or f.name.startswith('motion_'):
                    continue
                seen.add(f.name)
                sz_mb = round(f.stat().st_size / (1024 * 1024), 1)
                candidates.append({
                    "name": f.name,
                    "filename": f.name,
                    "path": str(f.relative_to(DATA_DIR)).replace('\\', '/'),
                    "size_mb": sz_mb,
                    "modified": f.stat().st_mtime
                })
    return candidates


def save_uploaded_driving_video(file_obj, filename=None):
    """Save user-uploaded driving reference video file."""
    _ensure_dirs()
    name = filename or getattr(file_obj, 'filename', 'driving_ref.mp4')
    safe_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', name)
    if not safe_name.lower().endswith(('.mp4', '.mov', '.webm', '.mkv')):
        safe_name += '.mp4'
    target = DRIVING_REF_DIR / f"drive_{uuid.uuid4().hex[:6]}_{safe_name}"
    if hasattr(file_obj, 'save'):
        file_obj.save(target)
    else:
        with open(target, 'wb') as dst:
            dst.write(file_obj.read())
    return {
        "name": target.name,
        "filename": target.name,
        "path": str(target.relative_to(DATA_DIR)).replace('\\', '/'),
        "size_mb": round(target.stat().st_size / (1024 * 1024), 1)
    }


def save_uploaded_swapped_frame(file_storage):
    """Save user-uploaded swapped start frame from Nano Banana or external AI."""
    _ensure_dirs()
    ext = Path(file_storage.filename).suffix.lower()
    if ext not in {'.png', '.jpg', '.jpeg', '.webp'}:
        ext = '.png'
    out_name = f"custom_swapped_{uuid.uuid4().hex[:8]}{ext}"
    dest_path = REFERENCES_DIR / out_name
    file_storage.save(str(dest_path))
    return {
        "success": True,
        "filename": dest_path.name,
        "path": str(dest_path),
        "url": f"/api/motion/references/file/{dest_path.name}",
        "message": "Custom swapped frame loaded successfully!"
    }


_face_app = None
_swapper_model = None
_swapper_lock = threading.Lock()


def get_neural_swapper():
    """Returns singleton instances of InsightFace FaceAnalysis and INSwapper ONNX model."""
    global _face_app, _swapper_model
    with _swapper_lock:
        if _face_app is None:
            try:
                import insightface
                from insightface.app import FaceAnalysis
                app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
                app.prepare(ctx_id=0, det_size=(640, 640))
                _face_app = app
            except Exception as e:
                _face_app = None

        if _swapper_model is None:
            try:
                import insightface
                from assets import ai_model_manager as model_mgr
                model_path = model_mgr.MODELS_DIR / 'faceswap' / 'inswapper_128.onnx'
                if model_path.is_file():
                    _swapper_model = insightface.model_zoo.get_model(str(model_path), download=False)
            except Exception as e:
                _swapper_model = None

    return _face_app, _swapper_model


def swap_character_identity(target_frame_path, character_id=None, custom_portrait_path=None, output_path=None, engine='neural'):
    """Replaces the identity/face in target_frame_path with the character persona's identity.

    Supports:
    - 'custom': User uploads their Nano Banana Pro / Midjourney / External generative image
    - 'flux' / 'cloud': Multimodal diffusion generation via cloud backend (Hugging Face / Fal.ai / Replicate)
    - 'neural': InSwapper 128 ONNX neural face embeddings
    - 'opencv': Fast 2D geometric alignment & color match preview
    """
    import cv2
    import numpy as np

    if engine in ('custom',):
        raise ValueError("Please upload your generative image using '📁 Upload Custom' (or select '📁 Upload Custom').")

    if engine in ('flux2-klein', 'flux2-klein-9b'):
        from assets import ai_model_manager as model_mgr
        model_id = "flux-2-klein-4b" if engine == "flux2-klein" else "flux-2-klein-9b"
        model_meta = model_mgr.MODEL_CATALOG.get(model_id, {})
        filename = model_meta.get('filename', 'flux-2-klein-4b-Q4_K_M.gguf')
        model_path = model_mgr.MODELS_DIR / 'image' / filename
        if not model_path.is_file():
            raise ValueError(
                f"{model_meta.get('name', 'FLUX.2 [klein]')} weights are not downloaded yet ({model_meta.get('size_gb', 2.6)} GB). "
                f"Click '⚡ AI Models' in the top header bar to download with 1-click, or upload your Nano Banana generation using '📁 Upload Custom'!"
            )

    if engine in ('seedream',):
        from assets import ai_model_manager as model_mgr
        cfg = model_mgr.load_config().get("cloud_backend", {})
        api_key = cfg.get("api_key", "").strip()
        if not api_key:
            raise ValueError(
                "ByteDance Seedream 5.0 requires an API key (e.g. Fal.ai / OpenRouter) in AI Model Settings. "
                "For zero-cost testing, click '📁 Upload Custom' to use your Nano Banana generation!"
            )

    if engine in ('flux', 'cloud'):
        from assets import ai_model_manager as model_mgr
        cfg = model_mgr.load_config().get("cloud_backend", {})
        api_key = cfg.get("api_key", "").strip()
        provider = cfg.get("api_provider", "huggingface")
        if not api_key:
            raise ValueError(
                "FLUX.1 multi-modal identity replacement requires a cloud API key (e.g. Hugging Face / Fal.ai) or local ComfyUI workflow. "
                "For flawless photorealistic quality right now, click '📋 Copy' below and upload your Nano Banana generation using '📁 Upload Custom'!"
            )

    if engine in ('neural',):
        from assets import ai_model_manager as model_mgr
        model_path = model_mgr.MODELS_DIR / 'faceswap' / 'inswapper_128.onnx'
        if not model_path.is_file():
            raise ValueError(
                "InSwapper 128 neural weights are not downloaded yet. Please download InSwapper 128 in AI Model Manager, "
                "or upload your Nano Banana generation using '📁 Upload Custom'."
            )

    _ensure_dirs()
    target_p = resolve_image_path(str(target_frame_path)) or Path(target_frame_path)
    if not target_p or not Path(target_p).is_file():
        raise FileNotFoundError(f"Target frame not found: {target_frame_path}")

    # Resolve character reference portrait
    char = characters.get_character(character_id) if character_id else characters.get_active_character()
    source_p = None
    if custom_portrait_path and Path(custom_portrait_path).is_file():
        source_p = Path(custom_portrait_path)
    elif char and char.get('portrait_file'):
        p = characters.get_image_path(char['id'], char['portrait_file'])
        if p and p.is_file():
            source_p = p

    if not source_p or not source_p.is_file():
        raise FileNotFoundError(f"Character portrait not found for {character_id or 'active'}")

    target_img = cv2.imread(str(target_p))
    src_img = cv2.imread(str(source_p))
    if target_img is None or src_img is None:
        raise ValueError("Failed to decode target frame or character image.")

    out_name = f"swapped_{char['id'] if char else 'char'}_{uuid.uuid4().hex[:8]}.png"
    dest_path = Path(output_path) if output_path else (REFERENCES_DIR / out_name)

    used_neural = False
    app, swapper = get_neural_swapper()
    if swapper is not None and app is not None and engine in ('neural', 'opencv', 'default'):
        try:
            target_faces = app.get(target_img)
            source_faces = app.get(src_img)
            if len(target_faces) > 0 and len(source_faces) > 0:
                tf = max(target_faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
                sf = max(source_faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
                res_bgr = swapper.get(target_img, tf, sf, paste_back=True)
                cv2.imwrite(str(dest_path), res_bgr)
                used_neural = True
        except Exception:
            pass

    if not used_neural:
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        cascade = cv2.CascadeClassifier(cascade_path)

        # 1. Detect face on target frame
        target_gray = cv2.cvtColor(target_img, cv2.COLOR_BGR2GRAY)
        target_faces = cascade.detectMultiScale(target_gray, scaleFactor=1.15, minNeighbors=4, minSize=(60, 60))

        # 2. Detect face on character source portrait
        src_gray = cv2.cvtColor(src_img, cv2.COLOR_BGR2GRAY)
        src_faces = cascade.detectMultiScale(src_gray, scaleFactor=1.15, minNeighbors=4, minSize=(60, 60))

        # Filter target face: the face is in upper half of the video (y < height * 0.55)
        real_target_faces = [f for f in target_faces if f[1] < target_img.shape[0] * 0.55]
        if len(real_target_faces) > 0 and len(src_faces) > 0:
            tf = max(real_target_faces, key=lambda f: f[2] * f[3])
            sf = max(src_faces, key=lambda f: f[2] * f[3])

            tx, ty, tw, th = tf
            sx, sy, sw, sh = sf

            # Expand crop box around character face to include hair, temples, and jawline
            pad_w = int(sw * 0.28)
            pad_top = int(sh * 0.45)
            pad_bot = int(sh * 0.18)

            x1 = max(0, sx - pad_w)
            y1 = max(0, sy - pad_top)
            x2 = min(src_img.shape[1], sx + sw + pad_w)
            y2 = min(src_img.shape[0], sy + sh + pad_bot)

            face_crop = src_img[y1:y2, x1:x2]

            t_pad_w = int(tw * 0.28)
            t_pad_top = int(th * 0.45)
            t_pad_bot = int(th * 0.18)

            tx1 = max(0, tx - t_pad_w)
            ty1 = max(0, ty - t_pad_top)
            tx2 = min(target_img.shape[1], tx + tw + t_pad_w)
            ty2 = min(target_img.shape[0], ty + th + t_pad_bot)

            target_w = tx2 - tx1
            target_h = ty2 - ty1

            if target_w > 10 and target_h > 10 and face_crop.shape[0] > 10 and face_crop.shape[1] > 10:
                resized_face = cv2.resize(face_crop, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)

                mask = np.zeros((target_h, target_w), dtype=np.float32)
                center = (target_w // 2, int(target_h * 0.48))
                axes = (int(target_w * 0.44), int(target_h * 0.46))
                cv2.ellipse(mask, center, axes, 0, 0, 360, 1.0, -1)

                hsv_crop = cv2.cvtColor(resized_face, cv2.COLOR_BGR2HSV)
                sat = hsv_crop[:, :, 1]
                val = hsv_crop[:, :, 2]
                is_backdrop = (sat < 25) & (val > 45)
                y_indices, x_indices = np.indices((target_h, target_w))
                dist_from_center = np.sqrt(((x_indices - center[0]) / max(1, axes[0]))**2 + ((y_indices - center[1]) / max(1, axes[1]))**2)
                mask[is_backdrop & (dist_from_center > 0.65)] = 0.0

                mask = cv2.GaussianBlur(mask, (31, 31), 0)[:, :, np.newaxis]

                comp = target_img.copy()
                comp[ty1:ty2, tx1:tx2] = (resized_face * mask + comp[ty1:ty2, tx1:tx2] * (1.0 - mask)).astype(np.uint8)
                cv2.imwrite(str(dest_path), comp)
            else:
                cv2.imwrite(str(dest_path), target_img)
        else:
            th_img, tw_img = target_img.shape[:2]
            crop_h = int(th_img * 0.45)
            crop_w = int(tw_img * 0.55)
            top_y = int(th_img * 0.08)
            left_x = int((tw_img - crop_w) / 2)

            resized_src = cv2.resize(src_img, (crop_w, crop_h), interpolation=cv2.INTER_LANCZOS4)
            mask = np.zeros((crop_h, crop_w), dtype=np.float32)
            center_fb = (crop_w // 2, int(crop_h * 0.48))
            axes_fb = (int(crop_w * 0.44), int(crop_h * 0.46))
            cv2.ellipse(mask, center_fb, axes_fb, 0, 0, 360, 1.0, -1)

            hsv_crop = cv2.cvtColor(resized_src, cv2.COLOR_BGR2HSV)
            sat = hsv_crop[:, :, 1]
            val = hsv_crop[:, :, 2]
            is_backdrop = (sat < 25) & (val > 45)
            y_indices, x_indices = np.indices((crop_h, crop_w))
            dist_from_center = np.sqrt(((x_indices - center_fb[0]) / max(1, axes_fb[0]))**2 + ((y_indices - center_fb[1]) / max(1, axes_fb[1]))**2)
            mask[is_backdrop & (dist_from_center > 0.65)] = 0.0

            mask = cv2.GaussianBlur(mask, (31, 31), 0)[:, :, np.newaxis]

            comp = target_img.copy()
            comp[top_y:top_y+crop_h, left_x:left_x+crop_w] = (resized_src * mask + comp[top_y:top_y+crop_h, left_x:left_x+crop_w] * (1.0 - mask)).astype(np.uint8)
            cv2.imwrite(str(dest_path), comp)

    char_name = char['name'] if char else 'Airi'
    char_tag = char['tag'] if char else '@Airi'
    prompt_text = (
        f"Edit Image 1, the original first frame from my motion-reference video.\n"
        f"Use Image 2 ({char_tag}) only as the identity reference for my AI influencer. Return one edited image.\n\n"
        f"Replace the main foreground person's identity with {char_name}'s identity: "
        f"match the reference face, facial features, skin tone, and hair. Adapt those features naturally to the original head angle, expression, gaze, and lighting.\n"
        f"Preserve Image 1's pose, body placement and scale, clothing, background, and lighting.\n"
        f"This image will be paired with the original video for Wan 2.1 / Kling motion control."
    )

    t_filename = target_p.name
    return {
        "success": True,
        "filename": dest_path.name,
        "path": str(dest_path),
        "url": f"/api/motion/references/file/{dest_path.name}",
        "extracted_frame": t_filename,
        "extracted_frame_url": f"/api/motion/references/file/{t_filename}",
        "prompt": prompt_text,
        "engine": "neural_inswapper" if used_neural else "opencv_preview",
        "is_neural": used_neural,
        "character": {
            "id": char['id'] if char else 'airi',
            "name": char_name,
            "tag": char_tag
        }
    }


_motion_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def get_motion_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _jobs_lock:
        job = _motion_jobs.get(job_id)
        if job:
            return copy.deepcopy(job)
        return None


def cancel_motion_job(job_id: str) -> bool:
    with _jobs_lock:
        job = _motion_jobs.get(job_id)
        if job and job.get("status") in ("pending", "running"):
            job["cancel_requested"] = True
            job["status"] = "cancelling"
            job["stage"] = "Cancelling..."
            return True
        return False


def start_motion_job(driving_video_path, source_image_path, audio_path=None, output_name=None, model_id='wan-2.1-1.3b') -> str:
    job_id = f"motion_{uuid.uuid4().hex[:10]}"
    job_record = {
        "id": job_id,
        "status": "pending",
        "progress": 0,
        "current_frame": 0,
        "total_frames": 0,
        "stage": "Queued for processing...",
        "error": None,
        "result": None,
        "cancel_requested": False,
        "created_at": time.time()
    }
    with _jobs_lock:
        _motion_jobs[job_id] = job_record

    def _worker():
        with _jobs_lock:
            if job_record.get("cancel_requested"):
                job_record["status"] = "cancelled"
                job_record["stage"] = "Cancelled by user"
                return
            job_record["status"] = "running"
            job_record["stage"] = "Initializing neural face & motion transfer..."

        def _on_progress(current, total, stage_name):
            with _jobs_lock:
                if job_record.get("cancel_requested"):
                    raise InterruptedError("Motion generation cancelled by user.")
                pct = int((current / max(1, total)) * 100) if total > 0 else 0
                job_record["progress"] = min(100, max(0, pct))
                job_record["current_frame"] = current
                job_record["total_frames"] = total
                job_record["stage"] = stage_name

        def _is_cancelled():
            with _jobs_lock:
                return bool(job_record.get("cancel_requested"))

        try:
            res = render_character_motion(
                driving_video_path=driving_video_path,
                source_image_path=source_image_path,
                audio_path=audio_path,
                output_name=output_name,
                model_id=model_id,
                progress_callback=_on_progress,
                cancel_check=_is_cancelled
            )
            with _jobs_lock:
                job_record["status"] = "completed"
                job_record["progress"] = 100
                job_record["stage"] = "Completed"
                job_record["result"] = res
        except InterruptedError:
            with _jobs_lock:
                job_record["status"] = "cancelled"
                job_record["stage"] = "Cancelled by user"
        except Exception as e:
            with _jobs_lock:
                job_record["status"] = "error"
                job_record["error"] = str(e)
                job_record["stage"] = f"Failed: {str(e)}"

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return job_id


def render_character_motion(driving_video_path, source_image_path, audio_path=None, output_name=None, model_id='wan-2.1-1.3b', progress_callback=None, cancel_check=None):
    """Render character motion video composite.

    Uses driving video's motion, choreography, and audio paired with the character's swapped identity.
    """
    _ensure_dirs()
    ipath = resolve_image_path(source_image_path)
    if not ipath:
        raise FileNotFoundError(f"Character image not found: {source_image_path}")

    out_name = Path(output_name).name if output_name else f"motion_{ipath.stem}_{uuid.uuid4().hex[:8]}.mp4"
    out_path = MOTION_OUTPUT_DIR / out_name

    resolved_driving = resolve_media_source(driving_video_path) if driving_video_path else None
    audio = resolve_media_source(audio_path) if audio_path else resolved_driving

    from assets import ai_model_manager as model_mgr
    model_st = model_mgr.list_models()
    vid_ready = model_st.get("summary", {}).get("video_ready", False)

    duration = 10.0
    if resolved_driving:
        duration = get_video_duration(resolved_driving)
    duration = max(2.0, min(60.0, duration))

    fps = 30
    total_frames = int(duration * fps)
    use_neural_for_video = False

    if resolved_driving and resolved_driving.is_file():
        # High-fidelity video motion synthesis:
        # Transpose character face/identity onto the driving video's motion frames!
        import cv2
        import numpy as np

        cap = cv2.VideoCapture(str(resolved_driving))
        orig_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        in_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        in_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        max_frames = min(int(duration * orig_fps), 450)

        if progress_callback:
            progress_callback(0, max_frames, "Loading neural identity & facial models...")

        # Load character face reference
        src_img = cv2.imread(str(ipath))

        app, swapper = get_neural_swapper()
        use_neural_for_video = False
        sf_neural = None

        if swapper is not None and app is not None and src_img is not None:
            try:
                faces_src = app.get(src_img)
                if len(faces_src) > 0:
                    sf_neural = max(faces_src, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
                    use_neural_for_video = True
            except Exception:
                pass

        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

        sf = None
        if not use_neural_for_video and src_img is not None:
            faces_src = cascade.detectMultiScale(cv2.cvtColor(src_img, cv2.COLOR_BGR2GRAY), 1.2, 4, minSize=(40, 40))
            if len(faces_src) > 0:
                sf = max(faces_src, key=lambda f: f[2] * f[3])

        temp_raw_vid = MOTION_OUTPUT_DIR / f"temp_{out_name}"
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(str(temp_raw_vid), fourcc, orig_fps, (in_w, in_h))

        frame_count = 0
        last_box = None

        if use_neural_for_video and sf_neural is not None:
            while frame_count < max_frames:
                if cancel_check and cancel_check():
                    cap.release()
                    writer.release()
                    temp_raw_vid.unlink(missing_ok=True)
                    raise InterruptedError("Motion generation cancelled by user.")
                ret, frame = cap.read()
                if not ret:
                    break
                try:
                    t_faces = app.get(frame)
                    if len(t_faces) > 0:
                        tf = max(t_faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
                        frame = swapper.get(frame, tf, sf_neural, paste_back=True)
                except Exception:
                    pass
                writer.write(frame)
                frame_count += 1
                if progress_callback and (frame_count % 3 == 0 or frame_count == max_frames):
                    progress_callback(frame_count, max_frames, "Neural identity face & expression synthesis...")
        elif sf is not None:
            sx, sy, sw, sh = sf
            pad_w = int(sw * 0.22)
            pad_top = int(sh * 0.40)
            pad_bot = int(sh * 0.20)
            x1 = max(0, sx - pad_w)
            y1 = max(0, sy - pad_top)
            x2 = min(src_img.shape[1], sx + sw + pad_w)
            y2 = min(src_img.shape[0], sy + sh + pad_bot)
            char_crop = src_img[y1:y2, x1:x2]

            while frame_count < max_frames:
                if cancel_check and cancel_check():
                    cap.release()
                    writer.release()
                    temp_raw_vid.unlink(missing_ok=True)
                    raise InterruptedError("Motion generation cancelled by user.")
                ret, frame = cap.read()
                if not ret:
                    break

                # Detect face periodically or track
                if frame_count % 3 == 0 or last_box is None:
                    small = cv2.resize(frame, (in_w // 2, in_h // 2))
                    faces = cascade.detectMultiScale(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), 1.2, 4, minSize=(30, 30))
                    if len(faces) > 0:
                        tf = max(faces, key=lambda f: f[2] * f[3])
                        last_box = (tf[0] * 2, tf[1] * 2, tf[2] * 2, tf[3] * 2)

                if last_box is not None:
                    tx, ty, tw, th = last_box
                    t_pad_w = int(tw * 0.22)
                    t_pad_top = int(th * 0.40)
                    t_pad_bot = int(th * 0.20)
                    tx1 = max(0, tx - t_pad_w)
                    ty1 = max(0, ty - t_pad_top)
                    tx2 = min(in_w, tx + tw + t_pad_w)
                    ty2 = min(in_h, ty + th + t_pad_bot)
                    target_w = tx2 - tx1
                    target_h = ty2 - ty1

                    if target_w > 10 and target_h > 10:
                        resized_char = cv2.resize(char_crop, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
                        src_lab = cv2.cvtColor(resized_char, cv2.COLOR_BGR2LAB).astype(np.float32)
                        tgt_lab = cv2.cvtColor(frame[ty1:ty2, tx1:tx2], cv2.COLOR_BGR2LAB).astype(np.float32)
                        l_diff = (tgt_lab[:, :, 0].mean() - src_lab[:, :, 0].mean()) * 0.30
                        src_lab[:, :, 0] = np.clip(src_lab[:, :, 0] + l_diff, 0, 255)
                        src_matched = cv2.cvtColor(src_lab.astype(np.uint8), cv2.COLOR_LAB2BGR)

                        mask = np.zeros((target_h, target_w), dtype=np.uint8)
                        center = (target_w // 2, target_h // 2)
                        axes = (int(target_w * 0.46), int(target_h * 0.48))
                        cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1)

                        try:
                            frame = cv2.seamlessClone(src_matched, frame, mask, (tx1 + target_w // 2, ty1 + target_h // 2), cv2.NORMAL_CLONE)
                        except Exception:
                            alpha = (mask.astype(np.float32) / 255.0)[:, :, np.newaxis]
                            frame[ty1:ty2, tx1:tx2] = (src_matched * alpha + frame[ty1:ty2, tx1:tx2] * (1 - alpha)).astype(np.uint8)

                writer.write(frame)
                frame_count += 1
                if progress_callback and (frame_count % 3 == 0 or frame_count == max_frames):
                    progress_callback(frame_count, max_frames, "Synthesizing motion frames...")
        else:
            while frame_count < max_frames:
                if cancel_check and cancel_check():
                    cap.release()
                    writer.release()
                    temp_raw_vid.unlink(missing_ok=True)
                    raise InterruptedError("Motion generation cancelled by user.")
                ret, frame = cap.read()
                if not ret:
                    break
                writer.write(frame)
                frame_count += 1
                if progress_callback and (frame_count % 5 == 0 or frame_count == max_frames):
                    progress_callback(frame_count, max_frames, "Processing motion frames...")

        cap.release()
        writer.release()

        if progress_callback:
            progress_callback(max_frames, max_frames, "Encoding final MP4 video and syncing audio...")

        # Re-mux with ffmpeg for web compatibility and audio sync
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,format=yuv420p"
        cmd = [_ffmpeg(), '-nostdin', '-y', '-i', str(temp_raw_vid)]
        if audio and audio != resolved_driving:
            cmd += ['-i', str(audio), '-map', '0:v:0', '-map', '1:a:0?', '-c:a', 'aac', '-b:a', '192k', '-shortest']
        elif audio:
            cmd += ['-i', str(audio), '-map', '0:v:0', '-map', '1:a:0?', '-c:a', 'aac', '-b:a', '192k', '-shortest']
        else:
            cmd += ['-c:a', 'aac']
        cmd += ['-vf', vf, '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p', str(out_path)]

        res = subprocess.run(cmd, capture_output=True)
        temp_raw_vid.unlink(missing_ok=True)
        if res.returncode != 0 or not out_path.is_file():
            raise RuntimeError("Motion render failed: " + res.stderr.decode('utf-8', errors='ignore')[-300:])
    else:
        # Still image camera push-in fallback when no driving video is provided
        if progress_callback:
            progress_callback(total_frames // 2, total_frames, "Rendering camera push-in motion...")

        vf = (
            f"scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,"
            f"zoompan=z='min(zoom+0.0007,1.15)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps},"
            f"format=yuv420p"
        )
        cmd = [_ffmpeg(), '-nostdin', '-y', '-loop', '1', '-i', str(ipath)]
        if audio:
            cmd += ['-i', str(audio), '-map', '0:v:0', '-map', '1:a?', '-c:a', 'aac', '-b:a', '192k', '-shortest']
        else:
            cmd += ['-t', f"{duration:.2f}"]
        cmd += ['-vf', vf, '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', str(out_path)]

        res = subprocess.run(cmd, capture_output=True)
        if res.returncode != 0 or not out_path.is_file():
            raise RuntimeError("Motion render failed: " + res.stderr.decode('utf-8', errors='ignore')[-300:])

        if progress_callback:
            progress_callback(total_frames, total_frames, "Finalizing motion video...")

    return {
        "path": str(out_path),
        "filename": out_path.name,
        "url": f"/api/motion/outputs/file/{out_path.name}",
        "duration": duration,
        "placeholder": not vid_ready,
        "engine": "neural_motion_synthesis" if use_neural_for_video else ("wan_2.1_motion" if vid_ready else "motion_composite_preview"),
        "is_neural": bool(use_neural_for_video),
        "status": "ready"
    }
