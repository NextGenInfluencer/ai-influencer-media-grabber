"""Verify optional AI imports in a fresh process, without downloading models."""
import importlib
import json
import os
import subprocess

MODULES = {
    'whisper': 'whisper',
    'lyric_alignment': 'stable_whisper',
    'torch': 'torch',
    'transformers': 'transformers',
    'llama': 'llama_cpp',
}


def prepare_build_tools(python, root):
    """Embedded Python needs its build backend on its explicit import path."""
    result = subprocess.run(
        [str(python), '-m', 'pip', 'install', '--only-binary=:all:',
         'setuptools>=77', 'wheel'], cwd=str(root),
        capture_output=True, text=True, timeout=180,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    if result.returncode:
        raise RuntimeError('Could not prepare AI installation tools: ' +
                           (result.stdout+'\n'+result.stderr).strip()[-1500:])


def inspect_runtime():
    results = {}
    for feature, module in MODULES.items():
        try:
            loaded = importlib.import_module(module)
            required = {
                'llama': ('Llama',),
                'whisper': ('load_model',),
                'transformers': ('BlipProcessor', 'BlipForConditionalGeneration'),
            }.get(feature, ())
            for name in required:
                getattr(loaded, name)
            if feature == 'lyric_alignment':
                alignment = importlib.import_module('stable_whisper.alignment')
                getattr(alignment, 'align')
                getattr(alignment, 'align_words')
            results[feature] = None
        except Exception as exc:
            # Native-library load errors also mean the feature is unavailable.
            results[feature] = f'{type(exc).__name__}: {exc}'[:500]
    return results


def verify_runtime(python, root):
    probe = subprocess.run(
        [str(python), '-m', 'assets.ai_setup'], cwd=str(root),
        capture_output=True, text=True, timeout=180,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    if probe.returncode:
        detail = (probe.stdout or probe.stderr or 'AI imports could not be verified.').strip()[-1500:]
        raise RuntimeError('AI packages were installed but verification failed. ' + detail)


if __name__ == '__main__':
    checks = inspect_runtime()
    failures = {name: error for name, error in checks.items() if error}
    print(json.dumps(failures or {'status': 'AI runtime imports verified'}, ensure_ascii=True))
    raise SystemExit(1 if failures else 0)
