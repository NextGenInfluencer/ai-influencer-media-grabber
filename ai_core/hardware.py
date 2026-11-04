"""Hardware detection and profile selection. Cheap, cached, and never imports torch."""
import importlib.util
import os
import platform
import shutil
import subprocess
import threading
import time

from . import paths, settings

PROFILES = ('essentials', 'laptop', 'gpu_mid', 'gpu_high', 'gpu_ultra')
# Thresholds in GiB of dedicated NVIDIA VRAM. Ranges follow the v5 contract
# (mid 6–10, high 10–20, ultra ≥20); a 10 GB card stays "mid" because the
# high-tier helper (qwen3:14b, ~9.3 GB) does not fit with its context.
MID_VRAM_GB = 5.75
HIGH_VRAM_GB = 10.5
ULTRA_VRAM_GB = 19.5
AI_PACK_MODULES = ('llama_cpp', 'torch', 'whisper', 'onnxruntime')
_CACHE_SECONDS = 300
_cache = {'time': 0.0, 'info': None}
_lock = threading.Lock()


def _run(args, timeout=6):
    kwargs = {'capture_output': True, 'text': True, 'timeout': timeout}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(args, **kwargs)
    except (OSError, subprocess.SubprocessError):
        return ''
    return result.stdout if result.returncode == 0 else ''


def _nvidia_gpus():
    exe = shutil.which('nvidia-smi')
    if not exe:
        return []
    output = _run([exe, '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'])
    gpus = []
    for line in output.splitlines():
        name, _, memory = line.rpartition(',')
        try:
            gpus.append({'vendor': 'nvidia', 'name': name.strip(), 'vram_gb': round(float(memory) / 1024, 2)})
        except ValueError:
            continue
    return gpus


def _vendor(name):
    lowered = name.lower()
    for key, vendor in (('nvidia', 'nvidia'), ('geforce', 'nvidia'), ('radeon', 'amd'), ('amd', 'amd'),
                        ('intel', 'intel'), ('arc', 'intel'), ('qualcomm', 'qualcomm'), ('adreno', 'qualcomm')):
        if key in lowered:
            return vendor
    return 'other'


def _display_devices():
    """Adapter names via Win32 EnumDisplayDevicesW when CIM is unavailable."""
    if os.name != 'nt':
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class _DISPLAY_DEVICEW(ctypes.Structure):
            _fields_ = [
                ('cb', wintypes.DWORD),
                ('DeviceName', wintypes.WCHAR * 32),
                ('DeviceString', wintypes.WCHAR * 128),
                ('StateFlags', wintypes.DWORD),
                ('DeviceID', wintypes.WCHAR * 128),
                ('DeviceKey', wintypes.WCHAR * 128),
            ]

        device = _DISPLAY_DEVICEW(cb=ctypes.sizeof(_DISPLAY_DEVICEW))
        adapters, seen, index = [], set(), 0
        while ctypes.windll.user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
            index += 1
            name = (device.DeviceString or '').strip()
            if name and name not in seen:
                seen.add(name)
                adapters.append({'vendor': _vendor(name), 'name': name, 'vram_gb': 0.0})
        return adapters
    except (AttributeError, OSError):
        return []


def _other_gpus():
    """Names of non-NVIDIA adapters via CIM (wmic is deprecated on Windows) or Win32 display devices."""
    if os.name != 'nt':
        return []
    output = _run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                   'Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }'], timeout=10)
    adapters = [{'vendor': _vendor(line), 'name': line.strip(), 'vram_gb': 0.0}
                for line in output.splitlines() if line.strip()]
    return adapters or _display_devices()


def _ram_gb():
    try:
        import psutil
        return round(psutil.virtual_memory().total / 1024 ** 3, 1)
    except (ImportError, OSError):
        pass
    if os.name == 'nt':
        try:
            import ctypes

            class _MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
                ]

            stat = _MEMORYSTATUSEX(dwLength=ctypes.sizeof(_MEMORYSTATUSEX))
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return round(stat.ullTotalPhys / 1024 ** 3, 1)
        except (AttributeError, OSError):
            pass
    elif hasattr(os, 'sysconf'):
        try:
            return round(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 1024 ** 3, 1)
        except (ValueError, OSError):
            pass
    return 0.0


def _disk_free_gb():
    for candidate in (paths.DATA_DIR, paths.APP_DIR):
        target = paths.Path(candidate)
        while not target.exists() and target != target.parent:
            target = target.parent
        try:
            return round(shutil.disk_usage(target).free / 1024 ** 3, 1)
        except OSError:
            continue
    return 0.0


def ai_pack_installed():
    return any(importlib.util.find_spec(name) is not None for name in AI_PACK_MODULES)


def detect(refresh=False):
    """Return GPU/RAM/disk facts; cached for a few minutes because nvidia-smi is slow."""
    with _lock:
        if not refresh and _cache['info'] and time.monotonic() - _cache['time'] < _CACHE_SECONDS:
            return dict(_cache['info'])
        gpus = _nvidia_gpus()
        others = [g for g in _other_gpus() if g['vendor'] != 'nvidia'] if not gpus else []
        primary = max(gpus, key=lambda g: g['vram_gb']) if gpus else (others[0] if others else None)
        info = {
            'gpu_vendor': primary['vendor'] if primary else 'none',
            'gpu_name': primary['name'] if primary else '',
            'vram_gb': primary['vram_gb'] if primary else 0.0,
            'ram_gb': _ram_gb(),
            'disk_free_gb': _disk_free_gb(),
            'os': f'{platform.system()} {platform.release()}'.strip(),
            'cpu_count': os.cpu_count() or 1,
            'gpus': gpus + others,
            'ai_pack': ai_pack_installed(),
        }
        _cache.update(time=time.monotonic(), info=info)
        return dict(info)


def profile(info=None):
    info = detect() if info is None else info
    if not info.get('ai_pack', True):
        return 'essentials'
    vram = float(info.get('vram_gb') or 0)
    if info.get('gpu_vendor') == 'nvidia':
        if vram >= ULTRA_VRAM_GB:
            return 'gpu_ultra'
        if vram >= HIGH_VRAM_GB:
            return 'gpu_high'
        if vram >= MID_VRAM_GB:
            return 'gpu_mid'
    return 'laptop'


def current_profile():
    override = settings.load().get('profile_override')
    return override if override in PROFILES else profile()


def directml_candidate(info=None):
    """True when an Intel/AMD adapter could accelerate ONNX via DirectML."""
    info = detect() if info is None else info
    return os.name == 'nt' and info.get('gpu_vendor') in ('amd', 'intel')
