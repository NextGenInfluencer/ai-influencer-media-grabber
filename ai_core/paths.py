"""Filesystem locations for AI data. Honours MEDIA_GRABBER_DATA_DIR like the app."""
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
HOME_DIR = Path.home()
DATA_DIR = Path(os.environ.get('MEDIA_GRABBER_DATA_DIR') or HOME_DIR / 'Documents' / 'Media Grabber')
MODELS_DIR = DATA_DIR / 'models'
ENGINES_DIR = DATA_DIR / 'engines'
SETTINGS_FILE = DATA_DIR / 'ai_settings.json'


def resolve_item_path(relative, root='models'):
    """Map a catalog path to an absolute path.

    ``@app/`` points inside the application folder (legacy built-in models) and
    ``@home/`` inside the user profile (read-only legacy caches such as
    ``~/.cache/whisper``). Other paths are relative to MODELS_DIR or ENGINES_DIR.
    Paths may never escape their base, so a tampered catalog cannot write elsewhere.
    """
    if relative.startswith('@app/'):
        base, rest = APP_DIR, relative[len('@app/'):]
    elif relative.startswith('@home/'):
        base, rest = HOME_DIR, relative[len('@home/'):]
    else:
        base, rest = (ENGINES_DIR if root == 'engines' else MODELS_DIR), relative
    base = Path(base).resolve()
    target = (base / rest).resolve()
    if base not in target.parents:
        raise ValueError(f'Catalog path escapes its folder: {relative}')
    return target


def is_within(path, base):
    try:
        resolved, root = Path(path).resolve(), Path(base).resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents
