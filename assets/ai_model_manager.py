"""AI Model Manager - Hugging Face Downloads, Quantized 12GB Weights & Cloud Backends.

Manages FLUX.1, SDXL Lightning, and Wan 2.1 models optimized for 12GB NVIDIA GPUs
(RTX 3080/4070) with background chunked downloads, progress streaming, and ComfyUI integration.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from typing import Any, Dict, List, Optional
import urllib.request

try:
    import torch
    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False

try:
    from huggingface_hub import hf_hub_download
    _HAS_HF_HUB = True
except ImportError:
    _HAS_HF_HUB = False


DATA_DIR = Path(os.environ.get('MEDIA_GRABBER_DATA_DIR') or Path.home() / 'Documents' / 'Media Grabber')
MODELS_DIR = DATA_DIR / 'models'
CONFIG_FILE = MODELS_DIR / 'models_config.json'

# Catalog of curated models tested for 12GB VRAM
MODEL_CATALOG = {
    "flux-schnell-nf4": {
        "id": "flux-schnell-nf4",
        "name": "FLUX.1 Schnell (4-Bit NF4)",
        "category": "image",
        "format": "safetensors",
        "size_gb": 6.5,
        "vram_req": "8GB - 12GB",
        "recommended_for": "Photorealistic character keyframes, 5-finger anatomy, accurate styling",
        "repo_id": "sayakpaul/flux.1-schnell-nf4-pkg",
        "filename": "flux1-schnell-nf4.safetensors",
        "url": "https://huggingface.co/sayakpaul/flux.1-schnell-nf4-pkg/resolve/main/flux1-schnell-nf4.safetensors",
        "default_steps": 4
    },
    "sdxl-lightning": {
        "id": "sdxl-lightning",
        "name": "SDXL Lightning 4-Step",
        "category": "image",
        "format": "safetensors",
        "size_gb": 3.8,
        "vram_req": "6GB - 8GB",
        "recommended_for": "Ultra-fast generation (3s per photo), sharp realistic portraiture",
        "repo_id": "ByteDance/SDXL-Lightning",
        "filename": "sdxl_lightning_4step_unet.safetensors",
        "url": "https://huggingface.co/ByteDance/SDXL-Lightning/resolve/main/sdxl_lightning_4step_unet.safetensors",
        "default_steps": 4
    },
    "wan-2.1-1.3b": {
        "id": "wan-2.1-1.3b",
        "name": "Wan 2.1 - 1.3B Video",
        "category": "video",
        "format": "safetensors",
        "size_gb": 4.2,
        "vram_req": "8GB - 12GB",
        "recommended_for": "Lightweight motion diffusion, fast dance and lip-sync rhythm, fits comfortably in 12GB",
        "repo_id": "Wan-AI/Wan2.1-T2V-1.3B",
        "filename": "diffusion_pytorch_model.safetensors",
        "url": "https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B/resolve/main/diffusion_pytorch_model.safetensors",
        "default_frames": 81
    },
    "wan-2.1-14b-q4": {
        "id": "wan-2.1-14b-q4",
        "name": "Wan 2.1 - 14B Q4 (12GB Edition)",
        "category": "video",
        "format": "gguf",
        "size_gb": 9.5,
        "vram_req": "12GB (Quantized)",
        "recommended_for": "Pro cinematic camera motion, stable hand gestures, 720p vertical video cuts",
        "repo_id": "city96/Wan2.1-I2V-14B-480P-GGUF",
        "filename": "wan2.1-i2v-14b-480p-Q4_K.gguf",
        "url": "https://huggingface.co/city96/Wan2.1-I2V-14B-480P-GGUF/resolve/main/wan2.1-i2v-14b-480p-Q4_K.gguf",
        "default_frames": 81
    }
}

_active_downloads: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def _ensure_dirs():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    (MODELS_DIR / 'image').mkdir(parents=True, exist_ok=True)
    (MODELS_DIR / 'video').mkdir(parents=True, exist_ok=True)


def get_gpu_info() -> Dict[str, Any]:
    """Detects available NVIDIA GPU, CUDA status, and VRAM capacity."""
    info = {
        "has_cuda": False,
        "device_name": "CPU (No CUDA GPU detected)",
        "vram_gb": 0.0,
        "recommended_preset": "Cloud API / Distilled"
    }
    if not _HAS_TORCH:
        return info

    try:
        if torch.cuda.is_available():
            info["has_cuda"] = True
            info["device_name"] = torch.cuda.get_device_name(0)
            vram_bytes = torch.cuda.get_device_properties(0).total_memory
            vram_gb = round(vram_bytes / (1024 ** 3), 1)
            info["vram_gb"] = vram_gb

            if vram_gb >= 15.0:
                info["recommended_preset"] = "Full 14B / FLUX Pro"
            elif vram_gb >= 11.5:
                info["recommended_preset"] = "12GB Quantized (Wan 2.1 Q4 / FLUX NF4)"
            elif vram_gb >= 7.5:
                info["recommended_preset"] = "8GB Fast (Wan 1.3B / SDXL Lightning)"
            else:
                info["recommended_preset"] = "Cloud Backend / SDXL Fast"
    except Exception:
        pass
    return info


def load_config() -> Dict[str, Any]:
    """Loads active model selections and cloud backend settings."""
    _ensure_dirs()
    if not CONFIG_FILE.is_file():
        default_cfg = {
            "active_image_model": "sdxl-lightning",
            "active_video_model": "wan-2.1-1.3b",
            "cloud_backend": {
                "enabled": False,
                "comfy_url": "http://127.0.0.1:8188",
                "api_provider": "huggingface",
                "api_key": ""
            }
        }
        save_config(default_cfg)
        return default_cfg

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {
            "active_image_model": "sdxl-lightning",
            "active_video_model": "wan-2.1-1.3b",
            "cloud_backend": {"enabled": False, "comfy_url": "", "api_provider": "huggingface", "api_key": ""}
        }


def save_config(cfg: Dict[str, Any]):
    """Persists model selections."""
    _ensure_dirs()
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)


def get_model_path(model_id: str) -> Optional[Path]:
    """Returns local path to model weights if file exists and has size."""
    meta = MODEL_CATALOG.get(model_id)
    if not meta:
        return None
    cat = meta["category"]
    fname = meta["filename"]
    p = MODELS_DIR / cat / fname
    if p.is_file() and p.stat().st_size > 1024 * 1024:
        return p
    return None


def get_model_status(model_id: str) -> Dict[str, Any]:
    """Returns real-time status of model: ready, downloading, or not_installed."""
    meta = MODEL_CATALOG.get(model_id)
    if not meta:
        return {"error": "Unknown model"}

    res = dict(meta)
    lp = get_model_path(model_id)
    if lp:
        res["status"] = "ready"
        res["local_path"] = str(lp)
        res["installed_size_gb"] = round(lp.stat().st_size / (1024 ** 3), 2)
        res["progress"] = 100
    else:
        with _lock:
            dl = _active_downloads.get(model_id)
        if dl:
            res["status"] = dl.get("status", "downloading")
            res["progress"] = dl.get("progress", 0)
            res["speed"] = dl.get("speed", "0 MB/s")
            res["downloaded_bytes"] = dl.get("downloaded_bytes", 0)
            res["total_bytes"] = dl.get("total_bytes", 0)
            res["error"] = dl.get("error", None)
        else:
            res["status"] = "not_installed"
            res["progress"] = 0

    return res


def list_models() -> Dict[str, Any]:
    """Lists all catalog models, their statuses, GPU info, and active selections."""
    cfg = load_config()
    gpu = get_gpu_info()

    models = []
    for mid in MODEL_CATALOG:
        st = get_model_status(mid)
        st["is_active"] = (mid == cfg.get("active_image_model") or mid == cfg.get("active_video_model"))
        models.append(st)

    ready_image = any(m["category"] == "image" and m["status"] == "ready" for m in models)
    ready_video = any(m["category"] == "video" and m["status"] == "ready" for m in models)

    return {
        "models": models,
        "gpu": gpu,
        "config": cfg,
        "summary": {
            "image_ready": ready_image,
            "video_ready": ready_video,
            "cloud_enabled": bool(cfg.get("cloud_backend", {}).get("enabled")),
            "active_image_model": cfg.get("active_image_model"),
            "active_video_model": cfg.get("active_video_model")
        }
    }


def _download_worker(model_id: str):
    """Background streaming downloader for model weights."""
    meta = MODEL_CATALOG.get(model_id)
    if not meta:
        return

    _ensure_dirs()
    target_dir = MODELS_DIR / meta["category"]
    target_file = target_dir / meta["filename"]
    temp_file = target_dir / f"{meta['filename']}.part"

    with _lock:
        _active_downloads[model_id] = {
            "status": "downloading",
            "progress": 0,
            "speed": "Connecting...",
            "downloaded_bytes": 0,
            "total_bytes": int(meta["size_gb"] * 1024 * 1024 * 1024),
            "cancel_requested": False,
            "error": None
        }

    try:
        # Check if already partially downloaded
        resumed_bytes = 0
        if temp_file.is_file():
            resumed_bytes = temp_file.stat().st_size

        url = meta["url"]
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "MediaGrabberPro/4.0.0 (AI-Video-Studio)",
            }
        )
        if resumed_bytes > 0:
            req.add_header("Range", f"bytes={resumed_bytes}-")

        with urllib.request.urlopen(req, timeout=30) as resp:
            content_length = resp.headers.get("Content-Length")
            total = int(content_length) + resumed_bytes if content_length else int(meta["size_gb"] * (1024**3))
            
            with _lock:
                if model_id in _active_downloads:
                    _active_downloads[model_id]["total_bytes"] = total

            mode = "ab" if resumed_bytes > 0 else "wb"
            downloaded = resumed_bytes
            start_time = time.time()
            last_calc_time = start_time
            last_bytes = downloaded

            chunk_size = 1024 * 1024  # 1MB chunks
            with open(temp_file, mode) as f:
                while True:
                    with _lock:
                        if _active_downloads.get(model_id, {}).get("cancel_requested"):
                            break

                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break

                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    if now - last_calc_time >= 0.5:
                        speed_bps = (downloaded - last_bytes) / (now - last_calc_time)
                        speed_mb = speed_bps / (1024 * 1024)
                        prog = min(99.9, round((downloaded / total) * 100, 1)) if total > 0 else 0.0

                        with _lock:
                            if model_id in _active_downloads:
                                _active_downloads[model_id]["progress"] = prog
                                _active_downloads[model_id]["speed"] = f"{speed_mb:.1f} MB/s"
                                _active_downloads[model_id]["downloaded_bytes"] = downloaded

                        last_calc_time = now
                        last_bytes = downloaded

        with _lock:
            cancelled = _active_downloads.get(model_id, {}).get("cancel_requested", False)

        if cancelled:
            with _lock:
                _active_downloads.pop(model_id, None)
            return

        # Atomic rename part to final file
        if temp_file.is_file() and temp_file.stat().st_size > 1024 * 1024:
            if target_file.is_file():
                target_file.unlink()
            shutil.move(str(temp_file), str(target_file))

        with _lock:
            _active_downloads.pop(model_id, None)

    except Exception as e:
        with _lock:
            if model_id in _active_downloads:
                _active_downloads[model_id]["status"] = "error"
                _active_downloads[model_id]["error"] = str(e)


def start_download(model_id: str) -> Dict[str, Any]:
    """Starts background download worker for model."""
    if model_id not in MODEL_CATALOG:
        return {"error": f"Unknown model id: {model_id}"}

    if get_model_path(model_id):
        return {"status": "already_installed", "message": "Model is already downloaded and ready."}

    with _lock:
        if model_id in _active_downloads:
            return {"status": "already_downloading", "message": "Download is already in progress."}

    t = threading.Thread(target=_download_worker, args=(model_id,), daemon=True)
    t.start()
    return {"status": "started", "model_id": model_id, "message": f"Download started for {MODEL_CATALOG[model_id]['name']}"}


def cancel_download(model_id: str) -> Dict[str, Any]:
    """Signals active download worker to halt."""
    with _lock:
        if model_id in _active_downloads:
            _active_downloads[model_id]["cancel_requested"] = True
            return {"status": "cancelled", "model_id": model_id}
    return {"status": "not_running", "message": "No active download found for this model."}


def delete_model(model_id: str) -> Dict[str, Any]:
    """Removes downloaded model file from disk to reclaim storage."""
    p = get_model_path(model_id)
    if not p:
        return {"status": "not_found", "message": "Model file not found on disk."}

    try:
        p.unlink(missing_ok=True)
        return {"status": "deleted", "model_id": model_id, "message": "Model file removed successfully."}
    except Exception as e:
        return {"error": f"Failed to delete model file: {e}"}
