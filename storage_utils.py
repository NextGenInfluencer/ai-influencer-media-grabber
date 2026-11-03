"""Crash-safe JSON and text persistence shared by every module (standard library only).

Writes go to a temporary file in the destination folder, are flushed to disk with
``fsync`` and then swapped in with ``os.replace``. On Windows ``os.replace`` fails
with ``PermissionError`` while another thread or process (antivirus, indexer, a
concurrent reader) briefly holds the destination open, so the swap is retried with
exponential backoff before giving up.
"""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time

# Delays between replace attempts: five retries, 50 ms doubling to 800 ms.
REPLACE_BACKOFF_SECONDS = (0.05, 0.1, 0.2, 0.4, 0.8)


def backup_path(path):
    """Location of the last-known-good copy kept by ``atomic_write_json(backup=True)``."""
    path = Path(path)
    return path.with_name(path.name + '.bak')


def replace_with_retry(source, destination, *, delays=REPLACE_BACKOFF_SECONDS, sleep=None):
    """``os.replace`` that tolerates transient Windows sharing violations."""
    sleep = sleep or time.sleep
    for delay in (*delays, None):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if delay is None:
                raise
            sleep(delay)


def atomic_write_bytes(path, payload):
    """Atomically replace ``path`` with ``payload``; the destination is never left partial."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '.', suffix='.tmp', delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_text(path, text, *, encoding='utf-8'):
    """Atomically replace ``path`` with ``text`` (no newline translation)."""
    atomic_write_bytes(path, text.encode(encoding))


def _is_valid_json(path):
    try:
        json.loads(Path(path).read_text(encoding='utf-8'))
        return True
    except (OSError, ValueError):
        return False


def atomic_write_json(path, data, *, indent=2, ensure_ascii=False, backup=False):
    """Atomically write ``data`` as UTF-8 JSON.

    With ``backup=True`` the current file is first preserved as ``<name>.bak`` when it
    is still valid JSON, so ``read_json_with_backup`` can recover from later corruption
    without ever replacing a good backup with a damaged file.
    """
    path = Path(path)
    text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    if backup and path.is_file() and _is_valid_json(path):
        atomic_write_bytes(backup_path(path), path.read_bytes())
    atomic_write_text(path, text)


def _preserve_corrupt(path):
    """Move a damaged file aside as ``<stem>.corrupt-<timestamp>.json`` and return its new path."""
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = path.with_name(f'{path.stem}.corrupt-{stamp}.json')
    replace_with_retry(path, destination)
    return destination


def _load(path, validate):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if validate is not None and not validate(data):
        raise ValueError('Unexpected JSON structure')
    return data


def read_json_with_backup(path, default, *, validate=None):
    """Read JSON, recovering from corruption instead of losing data.

    * Missing file (and no backup): a deep copy of ``default`` is returned.
    * Unreadable JSON, or data rejected by ``validate``: the damaged file is preserved
      as ``*.corrupt-<ts>.json``; the ``.bak`` copy is restored and returned when it
      is valid, otherwise ``default``.

    Operating-system errors (for example permission problems) propagate, because
    treating an unreadable file as empty would let the next save destroy user data.
    """
    path = Path(path)
    backup = backup_path(path)
    if path.is_file():
        try:
            return _load(path, validate)
        except (ValueError, UnicodeDecodeError):
            _preserve_corrupt(path)
    if backup.is_file():
        try:
            data = _load(backup, validate)
        except (ValueError, UnicodeDecodeError):
            return copy.deepcopy(default)
        atomic_write_bytes(path, backup.read_bytes())
        return data
    return copy.deepcopy(default)
