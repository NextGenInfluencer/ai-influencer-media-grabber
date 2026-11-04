"""AI Engine Pack: hardware-based pack choice, pre-install notice, pip commands and verification.

The server never imports the AI libraries itself: status uses ``importlib.util.find_spec``
and verification imports them in a fresh process (``python -m assets.ai_setup``).
"""
import argparse
from functools import lru_cache
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKS_FILE = 'ai_packs.json'
PACK_NAMES = ('cpu', 'directml', 'gpu')
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

# Feature -> module that must import for the AI Engine Pack to count as installed.
MODULES = {
    'whisper': 'whisper',
    'lyric_alignment': 'stable_whisper',
    'torch': 'torch',
    'transformers': 'transformers',
    'llama': 'llama_cpp',
    'insightface': 'insightface',
    'onnxruntime': 'onnxruntime',
    'keyring': 'keyring',
}
# Opt-in cloud clients (GPU pack only); reported, never required.
OPTIONAL_MODULES = {
    'audio_separator': 'audio_separator',
    'fal_client': 'fal_client',
    'google_genai': 'google.genai',
}
_REQUIRED_ATTRIBUTES = {
    'llama': ('Llama',),
    'whisper': ('load_model',),
    'transformers': ('BlipProcessor', 'BlipForConditionalGeneration'),
    'onnxruntime': ('InferenceSession', 'get_available_providers'),
    'keyring': ('get_password', 'set_password'),
}
_GPU_VENDORS = (('nvidia', 'nvidia'), ('geforce', 'nvidia'), ('quadro', 'nvidia'), ('amd', 'amd'),
                ('radeon', 'amd'), ('intel', 'intel'))
# Minimal 1-node Identity ONNX model (opset 13, IR v8) to verify real execution provider instantiation.
_PROBE_ONNX_MODEL = (
    b'\x08\x08:7\n\x10\n\x01X\x12\x01Y"\x08Identity\x12\x01gZ\x0f\n\x01X\x12\n\n\x08\x08\x01'
    b'\x12\x04\n\x02\x08\x01b\x0f\n\x01Y\x12\n\n\x08\x08\x01\x12\x04\n\x02\x08\x01B\x04\n\x00\x10\r'
)


def load_packs(root=ROOT):
    return json.loads((Path(root) / PACKS_FILE).read_text(encoding='utf-8'))


def prepare_build_tools(python, root):
    """Embedded Python needs its build backend on its explicit import path."""
    result = subprocess.run(
        [str(python), '-m', 'pip', 'install', '--only-binary=:all:',
         'setuptools>=77', 'wheel'], cwd=str(root),
        capture_output=True, text=True, timeout=180,
        creationflags=_NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeError('Could not prepare AI installation tools: ' +
                           (result.stdout+'\n'+result.stderr).strip()[-1500:])


# ---------------------------------------------------------------------------
# Hardware detection and pack choice
# ---------------------------------------------------------------------------

def _vendor(name):
    lowered = (name or '').lower()
    return next((vendor for token, vendor in _GPU_VENDORS if token in lowered), None)


def _run_quiet(command, timeout):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return ''
    return result.stdout if result.returncode == 0 else ''


def _nvidia_gpu():
    executable = shutil.which('nvidia-smi')
    if not executable:
        return None
    output = _run_quiet([executable, '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'], 15)
    best = None
    for line in output.splitlines():
        name, _, memory = line.rpartition(',')
        try:
            vram = round(float(memory.strip()) / 1024, 1)
        except ValueError:
            continue
        if best is None or vram > best['vram_gb']:
            best = {'vendor': 'nvidia', 'name': name.strip(), 'vram_gb': vram}
    return best


def _windows_gpu():
    if os.name != 'nt':
        return None
    output = _run_quiet(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                         '(Get-CimInstance Win32_VideoController).Name'], 20)
    for name in (line.strip() for line in output.splitlines()):
        vendor = _vendor(name)
        if vendor:
            return {'vendor': vendor, 'name': name, 'vram_gb': None}
    return None


@lru_cache(maxsize=1)
def detect_gpu():
    """Best GPU on this PC: ``{'vendor', 'name', 'vram_gb'}`` or ``None``.

    Uses ``ai_core.hardware`` when that module is available, otherwise nvidia-smi and
    the Windows display-adapter list.
    """
    try:
        from ai_core import hardware
        info = hardware.detect()
        if info.get('gpu_vendor'):
            return {'vendor': info['gpu_vendor'], 'name': info.get('gpu_name') or '', 'vram_gb': info.get('vram_gb')}
    except Exception:  # ai_core is optional here; fall back to direct probes.
        pass
    return _nvidia_gpu() or _windows_gpu()


def choose_pack(gpu=None, *, platform=sys.platform, min_vram_gb=6):
    """Recommend a pack for ``gpu`` (from ``detect_gpu``) and explain why."""
    if gpu and gpu.get('vendor') == 'nvidia':
        vram = gpu.get('vram_gb') or 0
        name = (gpu.get('name') or 'GPU').strip()
        label = name if name.lower().startswith('nvidia') else f'NVIDIA {name}'
        if vram >= min_vram_gb:
            return 'gpu', f"{label} with {vram:g} GB of video memory detected."
        reason = (f"{label} has {vram:g} GB of video memory; "
                  f"the GPU pack needs at least {min_vram_gb} GB.")
        if platform == 'win32':
            return 'directml', reason + ' Face tools will use DirectML.'
        return 'cpu', reason
    if gpu and gpu.get('vendor') in ('amd', 'intel') and platform == 'win32':
        return 'directml', f"{gpu.get('name') or 'Intel/AMD graphics'} detected: face tools can use DirectML."
    return 'cpu', 'No NVIDIA GPU with at least %d GB of video memory was found.' % min_vram_gb


def recommended_pack(root=ROOT):
    packs = load_packs(root)
    gpu = detect_gpu()
    pack, reason = choose_pack(gpu, min_vram_gb=packs.get('gpu_min_vram_gb', 6))
    return pack, reason, gpu


def notice(root=ROOT, pack=None):
    """Everything the user must see before installing: itemized packages, sizes, licenses, why."""
    root = Path(root)
    packs = load_packs(root)
    recommended, reason, gpu = recommended_pack(root)
    chosen = pack or recommended
    if chosen not in packs['packs']:
        raise ValueError(f'Unknown AI pack: {chosen}')
    if chosen != recommended:
        reason = f'Selected manually (recommended for this PC: {packs["packs"][recommended]["label"]}). ' + reason
    items = [item for item in packs['items'] if chosen in item['packs']]
    total = sum(item['approx_mb'] for item in items)
    definition = packs['packs'][chosen]
    try:
        free_mb = shutil.disk_usage(root).free // (1024 * 1024)
    except OSError:
        free_mb = None
    return {
        'pack': chosen,
        'recommended': recommended,
        'label': definition['label'],
        'summary': definition['summary'],
        'reason': reason,
        'gpu': gpu,
        'items': items,
        'approx_download_mb': total,
        'approx_disk_mb': definition['approx_disk_mb'],
        'disk_free_mb': free_mb,
        'enough_disk': free_mb is None or free_mb > definition['approx_disk_mb'],
        'licenses': sorted({item['license'] for item in items}),
        'requirements': [definition['requirements'], packs['nodeps_requirements']],
        'note': packs['note'],
        'available_packs': {name: value['label'] for name, value in packs['packs'].items()},
        'requires_accept': True,
    }


def install_commands(python, root, pack):
    """pip invocations for ``pack``: the pack file, then packages installed without dependencies."""
    packs = load_packs(root)
    if pack not in packs['packs']:
        raise ValueError(f'Unknown AI pack: {pack}')
    pip = [str(python), '-m', 'pip', 'install', '--disable-pip-version-check']
    return [
        pip + ['--no-build-isolation', '-r', packs['packs'][pack]['requirements']],
        pip + ['--no-deps', '-r', packs['nodeps_requirements']],
    ]


# ---------------------------------------------------------------------------
# Status and verification
# ---------------------------------------------------------------------------

def installed_features():
    """Cheap status for the server: which pack modules are present, without importing them."""
    status = {}
    for feature, module in MODULES.items():
        try:
            status[feature] = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            status[feature] = False
    return status


def inspect_runtime(pack=None, root=ROOT):
    """Import every pack module (run this in a fresh process) and report failures per feature."""
    expected_provider = None
    if pack:
        expected_provider = load_packs(root)['packs'][pack]['onnx_provider']
    results = {}
    for feature, module in MODULES.items():
        try:
            loaded = importlib.import_module(module)
            for name in _REQUIRED_ATTRIBUTES.get(feature, ()):
                getattr(loaded, name)
            if feature == 'lyric_alignment':
                alignment = importlib.import_module('stable_whisper.alignment')
                getattr(alignment, 'align')
                getattr(alignment, 'align_words')
            if feature == 'insightface':
                getattr(importlib.import_module('insightface.app'), 'FaceAnalysis')
                getattr(importlib.import_module('insightface.model_zoo'), 'get_model')
            if feature == 'onnxruntime' and expected_provider:
                providers = list(loaded.get_available_providers())
                if expected_provider not in providers:
                    raise RuntimeError(f'{expected_provider} is not available (found: {", ".join(providers) or "none"}). '
                                       'Update the graphics driver, then reinstall the AI Engine Pack.')
                if expected_provider == 'CUDAExecutionProvider':
                    preload = getattr(loaded, 'preload_dlls', None)
                    if callable(preload):
                        preload()
                    session = loaded.InferenceSession(_PROBE_ONNX_MODEL,
                                                      providers=[expected_provider, 'CPUExecutionProvider'])
                    active = list(session.get_providers()) if hasattr(session, 'get_providers') else [expected_provider]
                    if expected_provider not in active:
                        raise RuntimeError(
                            f'{expected_provider} session fell back to {", ".join(active) or "CPU"}. '
                            'Install onnxruntime-gpu[cuda,cudnn] or update the graphics driver.'
                        )
            results[feature] = None
        except Exception as exc:
            # Native-library load errors also mean the feature is unavailable.
            results[feature] = f'{type(exc).__name__}: {exc}'[:500]
    return results


def onnx_providers():
    try:
        return list(importlib.import_module('onnxruntime').get_available_providers())
    except Exception:
        return []


def optional_modules():
    status = {}
    for feature, module in OPTIONAL_MODULES.items():
        try:
            status[feature] = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            status[feature] = False
    return status


def verify_runtime(python, root, pack=None):
    command = [str(python), '-m', 'assets.ai_setup'] + (['--pack', pack] if pack else [])
    probe = subprocess.run(
        command, cwd=str(root),
        capture_output=True, text=True, timeout=180,
        creationflags=_NO_WINDOW,
    )
    if probe.returncode:
        detail = (probe.stdout or probe.stderr or 'AI imports could not be verified.').strip()[-1500:]
        raise RuntimeError('AI packages were installed but verification failed. ' + detail)


# ---------------------------------------------------------------------------
# Command line (install_ai.bat)
# ---------------------------------------------------------------------------

def _print_notice(info):
    print(f"\n{info['label']}\n{info['summary']}\nWhy: {info['reason']}\n")
    for item in info['items']:
        print(f"  ~{item['approx_mb']:>5} MB  {item['name']}  [{item['license']}]")
    print(f"\n  Total download: about {info['approx_download_mb']:,} MB; "
          f"disk space needed: about {info['approx_disk_mb']:,} MB.")
    print(f"  {info['note']}\n")


def _install(root, pack, assume_yes):
    info = notice(root, pack)
    _print_notice(info)
    if not info['enough_disk']:
        print('[ERROR] Not enough free disk space for this pack.')
        return 1
    if not assume_yes and input('Type YES to download and install: ').strip().lower() != 'yes':
        print('Cancelled. Nothing was downloaded.')
        return 1
    prepare_build_tools(sys.executable, root)
    for command in install_commands(sys.executable, root, info['pack']):
        if subprocess.run(command, cwd=str(root)).returncode:
            print('[ERROR] Failed to install some AI dependencies.')
            return 1
    verify_runtime(sys.executable, root, info['pack'])
    print('[SUCCESS] AI Engine Pack verified. Restart the app before using AI features.')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='AI Engine Pack setup')
    parser.add_argument('--pack', choices=PACK_NAMES, help='pack to verify or install (default: recommended)')
    parser.add_argument('--install', action='store_true', help='show the notice, then install the pack')
    parser.add_argument('--notice', action='store_true', help='print the pre-install notice as JSON')
    parser.add_argument('--yes', action='store_true', help='accept the notice without prompting')
    args = parser.parse_args(argv)
    if args.notice:
        print(json.dumps(notice(ROOT, args.pack), indent=2))
        return 0
    if args.install:
        return _install(ROOT, args.pack, args.yes)
    checks = inspect_runtime(args.pack)
    failures = {name: error for name, error in checks.items() if error}
    report = failures or {'status': 'AI runtime imports verified', 'onnx_providers': onnx_providers(),
                          'optional': optional_modules()}
    print(json.dumps(report, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
