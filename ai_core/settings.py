"""Persistent AI settings: profile override, role overrides, licenses, cloud opt-ins, notices."""
import copy
import json
import os
import threading
import time

from storage_utils import atomic_write_json

from . import paths

ROLES = ('helper', 'translator', 'vision', 'speech')
CLOUD_PROVIDERS = ('fal', 'gemini')
NOTICES = ('responsible_use', 'download_copyright')
DEFAULTS = {
    'profile_override': None,
    'roles': {role: None for role in ROLES},
    'accepted_licenses': [],
    'cloud': {provider: {'enabled': False} for provider in CLOUD_PROVIDERS},
    'idle_release_seconds': 300,
    'notices': {notice: False for notice in NOTICES},
    'setup_seen': False,
}
_lock = threading.RLock()


def _merge(defaults, stored):
    merged = copy.deepcopy(defaults)
    if not isinstance(stored, dict):
        return merged
    for key, value in stored.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load():
    """Return settings merged over defaults; a corrupt file is preserved, not lost."""
    with _lock:
        try:
            stored = json.loads(paths.SETTINGS_FILE.read_text(encoding='utf-8'))
        except FileNotFoundError:
            stored = {}
        except (OSError, ValueError):
            corrupt = paths.SETTINGS_FILE.with_name(f'ai_settings.corrupt-{int(time.time())}.json')
            try:
                os.replace(paths.SETTINGS_FILE, corrupt)
            except OSError:
                pass
            stored = {}
        return _merge(DEFAULTS, stored)


def save(data):
    with _lock:
        atomic_write_json(paths.SETTINGS_FILE, _merge(DEFAULTS, data))


def update(mutator):
    """Apply ``mutator(settings)`` under the lock and persist the result."""
    with _lock:
        data = load()
        mutator(data)
        save(data)
        return data


def get_role_override(role):
    value = load().get('roles', {}).get(role)
    return value if isinstance(value, str) and value.strip() else None


def accepted_licenses():
    value = load().get('accepted_licenses')
    return set(value) if isinstance(value, list) else set()


def accept_license(item_id):
    def add(data):
        accepted = data.get('accepted_licenses')
        accepted = accepted if isinstance(accepted, list) else []
        if item_id not in accepted:
            accepted.append(item_id)
        data['accepted_licenses'] = accepted
    update(add)


def cloud_enabled(provider):
    entry = load().get('cloud', {}).get(provider)
    return isinstance(entry, dict) and entry.get('enabled') is True


def idle_release_seconds():
    try:
        return max(10.0, float(load().get('idle_release_seconds', 300)))
    except (TypeError, ValueError):
        return 300.0
