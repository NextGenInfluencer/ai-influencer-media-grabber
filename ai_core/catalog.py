"""Pinned model/engine catalog: what can be installed, for which roles and profiles."""
import copy
import json
import threading
from pathlib import Path

CATALOG_FILE = Path(__file__).with_name('catalog.json')
_lock = threading.Lock()
_cache = None


def _load():
    global _cache
    with _lock:
        if _cache is None:
            _cache = json.loads(CATALOG_FILE.read_text(encoding='utf-8'))
        return _cache


def reload():
    """Drop the cached catalog (used after a verified catalog refresh and in tests)."""
    global _cache
    with _lock:
        _cache = None


def data():
    return copy.deepcopy(_load())


def items():
    return copy.deepcopy(_load()['items'])


def get(item_id):
    """Return a copy of one item; raises KeyError for unknown ids."""
    for item in _load()['items']:
        if item['id'] == item_id:
            return copy.deepcopy(item)
    raise KeyError(item_id)


def exists(item_id):
    return any(item['id'] == item_id for item in _load()['items'])


def section(name):
    return copy.deepcopy(_load().get(name, {}))


def recommended(profile, role, info=None):
    """Item ids for a role on a profile, ordered best → fallback.

    Items whose ``min_system_ram_gb`` exceeds the detected RAM stay in the list as
    fallbacks but move behind those that fit (e.g. Qwen3-1.7B before 4B on 8 GB).
    """
    ids = list(_load().get('recommendations', {}).get(profile, {}).get(role, []))
    if info is None:
        return ids
    ram = info.get('ram_gb') or 0

    def fits(item_id):
        need = get(item_id).get('min_system_ram_gb') or 0
        return round(ram) >= need
    return [i for i in ids if fits(i)] + [i for i in ids if not fits(i)]


def bundle(profile):
    return list(_load().get('bundles', {}).get(profile, []))


def workflow(name):
    flows = _load().get('workflows', {})
    if name not in flows:
        raise KeyError(name)
    return copy.deepcopy(flows[name])


def cloud_endpoint(provider, name):
    return copy.deepcopy(_load().get('cloud_endpoints', {}).get(provider, {}).get(name))
