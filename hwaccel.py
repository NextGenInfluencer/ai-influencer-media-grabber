"""
Hardware-accelerated video encoding detection and arguments helper.
Supports NVIDIA NVENC, Intel QuickSync (QSV), AMD AMF, Apple VideoToolbox,
with seamless automatic fallback to software CPU encoding (libx264 / libx265).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any

logger = logging.getLogger("media_grabber.hwaccel")

_CACHED_ENCODERS: dict[str, dict[str, Any]] = {}


def _test_encoder(ffmpeg_bin: str, encoder_name: str, test_args: list[str]) -> bool:
    """Run a micro-encode test with the candidate encoder to ensure GPU drivers accept it."""
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi",
        "-i", "nullsrc=s=256x256:d=0.04",
        "-c:v", encoder_name,
        *test_args,
        "-f", "null",
        "-",
    ]
    try:
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE

        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            timeout=4,
        )
        return res.returncode == 0
    except Exception as exc:
        logger.debug("Encoder %s probe failed: %s", encoder_name, exc)
        return False


def _get_ffmpeg_bin() -> str:
    """Return the absolute path to the active FFmpeg binary."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg") or "ffmpeg"


def detect_best_encoder(preferred_codec: str = "h264", force_cpu: bool = False) -> dict[str, Any]:
    """Detect the best hardware accelerated or CPU video encoder available on the system."""
    cache_key = f"{preferred_codec}_{force_cpu}"
    if cache_key in _CACHED_ENCODERS:
        return _CACHED_ENCODERS[cache_key]

    ffmpeg_bin = _get_ffmpeg_bin()
    codec = "hevc" if preferred_codec in {"hevc", "h265", "265"} else "h264"

    if not force_cpu:
        candidates = (
            [
                ("h264_nvenc", "NVIDIA", "gpu", ["-preset", "p4", "-cq", "23"]),
                ("h264_qsv", "Intel", "gpu", ["-preset", "medium", "-global_quality", "23"]),
                ("h264_amf", "AMD", "gpu", ["-quality", "balanced"]),
                ("h264_videotoolbox", "Apple", "gpu", ["-q:v", "65"]),
            ]
            if codec == "h264"
            else [
                ("hevc_nvenc", "NVIDIA", "gpu", ["-preset", "p4", "-cq", "26"]),
                ("hevc_qsv", "Intel", "gpu", ["-preset", "medium", "-global_quality", "26"]),
                ("hevc_amf", "AMD", "gpu", ["-quality", "balanced"]),
                ("hevc_videotoolbox", "Apple", "gpu", ["-q:v", "60"]),
            ]
        )

        for enc_name, vendor, kind, test_args in candidates:
            if _test_encoder(ffmpeg_bin, enc_name, test_args):
                info: dict[str, Any] = {
                    "encoder": enc_name,
                    "codec": codec,
                    "type": kind,
                    "vendor": vendor,
                    "hardware_accelerated": True,
                    "display_name": f"{vendor} Hardware Accelerated ({enc_name})",
                }
                _CACHED_ENCODERS[cache_key] = info
                logger.info("Active video encoder: %s (%s)", enc_name, vendor)
                return info

    # CPU Software Fallback
    sw_encoder = "libx265" if codec == "hevc" else "libx264"
    info = {
        "encoder": sw_encoder,
        "codec": codec,
        "type": "cpu",
        "vendor": "Software",
        "hardware_accelerated": False,
        "display_name": f"CPU Software Encoder ({sw_encoder})",
    }
    _CACHED_ENCODERS[cache_key] = info
    return info


def get_video_encoder_args(
    codec: str = "h264",
    quality: str = "standard",
    force_cpu: bool = False,
) -> list[str]:
    """
    Return optimal FFmpeg command line arguments for the detected hardware or CPU encoder.
    Quality presets: 'draft', 'standard', 'high', 'lossless', '60fps', '4k'
    """
    info = detect_best_encoder(preferred_codec=codec, force_cpu=force_cpu)
    enc = info["encoder"]

    # 1. NVIDIA NVENC
    if "nvenc" in enc:
        if quality in {"high", "4k"}:
            return ["-c:v", enc, "-preset", "p6", "-cq", "19", "-b:v", "0"]
        elif quality == "draft":
            return ["-c:v", enc, "-preset", "p2", "-cq", "28", "-b:v", "0"]
        else:
            return ["-c:v", enc, "-preset", "p4", "-cq", "23", "-b:v", "0"]

    # 2. Intel QuickSync (QSV)
    if "qsv" in enc:
        if quality in {"high", "4k"}:
            return ["-c:v", enc, "-preset", "veryslow", "-global_quality", "20"]
        elif quality == "draft":
            return ["-c:v", enc, "-preset", "faster", "-global_quality", "28"]
        else:
            return ["-c:v", enc, "-preset", "medium", "-global_quality", "23"]

    # 3. AMD AMF
    if "amf" in enc:
        if quality in {"high", "4k"}:
            return ["-c:v", enc, "-quality", "quality", "-rc", "cqp", "-qp_p", "19"]
        elif quality == "draft":
            return ["-c:v", enc, "-quality", "speed", "-rc", "cqp", "-qp_p", "28"]
        else:
            return ["-c:v", enc, "-quality", "balanced", "-rc", "cqp", "-qp_p", "23"]

    # 4. Apple VideoToolbox
    if "videotoolbox" in enc:
        if quality in {"high", "4k"}:
            return ["-c:v", enc, "-q:v", "75"]
        elif quality == "draft":
            return ["-c:v", enc, "-q:v", "50"]
        else:
            return ["-c:v", enc, "-q:v", "65"]

    # 5. Software CPU Fallback (libx264 / libx265)
    if quality == "draft":
        return ["-c:v", enc, "-preset", "ultrafast", "-crf", "26"]
    elif quality in {"high", "4k"}:
        return ["-c:v", enc, "-preset", "medium", "-crf", "18"]
    else:
        return ["-c:v", enc, "-preset", "fast", "-crf", "22"]
