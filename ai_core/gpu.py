"""VRAM broker: one heavy model on the GPU at a time, released after its last use.

Engines and in-process models register an *evictor* (a callable that frees the
GPU memory they hold). ``lease(name, vram_gb)`` waits for other heavy leases to
finish, evicts other resident models, and restarts the idle timer of ``name``
when the lease ends. Downloads never take these locks.
"""
import contextlib
import logging
import threading
import time
from collections import Counter

from . import settings

log = logging.getLogger(__name__)
LIGHT_VRAM_GB = 0.5  # leases at or below this never evict or wait

_cond = threading.Condition(threading.RLock())
_evictors = {}
_model_locks = {}
_active = Counter()
_resident = {}
_timers = {}


def register_evictor(name, fn):
    with _cond:
        _evictors[name] = fn


def unregister_evictor(name):
    with _cond:
        _evictors.pop(name, None)


def model_lock(name):
    """Per-model re-entrant lock for load/inference/unload of one model."""
    with _cond:
        return _model_locks.setdefault(name, threading.RLock())


def _evict(name):
    fn = _evictors.get(name)
    _resident.pop(name, None)
    timer = _timers.pop(name, None)
    if timer:
        timer.cancel()
    if fn is None:
        return
    try:
        fn()
    except Exception as exc:  # an evictor failure must never break the caller's job
        log.warning('GPU evictor %s failed: %s', name, exc)


def _heavy_conflict(name):
    return any(count and other != name and _resident.get(other, {}).get('vram_gb', 0) > LIGHT_VRAM_GB
               for other, count in _active.items())


@contextlib.contextmanager
def lease(name, vram_gb=0.0, timeout=None):
    """Hold the GPU for ``name``; raises TimeoutError if another job keeps it."""
    heavy = float(vram_gb or 0) > LIGHT_VRAM_GB
    with _cond:
        if heavy:
            if not _cond.wait_for(lambda: not _heavy_conflict(name), timeout=timeout):
                raise TimeoutError('The GPU is busy with another AI job. Try again when it finishes.')
            for other in [n for n, info in list(_resident.items())
                          if n != name and info.get('vram_gb', 0) > LIGHT_VRAM_GB and not _active[n]]:
                _evict(other)
        timer = _timers.pop(name, None)
        if timer:
            timer.cancel()
        _resident[name] = {'vram_gb': float(vram_gb or 0), 'last_used': time.monotonic()}
        _active[name] += 1
    try:
        yield
    finally:
        with _cond:
            _active[name] -= 1
            if _active[name] <= 0:
                del _active[name]
            touch(name)
            _cond.notify_all()


def touch(name, idle_seconds=None):
    """Mark ``name`` as just used and restart its idle-release timer."""
    with _cond:
        if name not in _resident:
            _resident[name] = {'vram_gb': 0.0, 'last_used': time.monotonic()}
        _resident[name]['last_used'] = time.monotonic()
        timer = _timers.pop(name, None)
        if timer:
            timer.cancel()
        delay = settings.idle_release_seconds() if idle_seconds is None else idle_seconds
        timer = threading.Timer(delay, _idle_release, args=(name, delay))
        timer.daemon = True
        _timers[name] = timer
        timer.start()


def _idle_release(name, delay):
    with _cond:
        info = _resident.get(name)
        if not info or _active[name]:
            return
        if time.monotonic() - info['last_used'] + 0.01 < delay:
            return
        _timers.pop(name, None)
        _evict(name)


def release(name):
    """Free ``name`` now (unless a job is using it)."""
    with _cond:
        if _active[name]:
            return False
        _evict(name)
        return True


def release_all():
    with _cond:
        for name in [n for n in list(_resident) if not _active[n]]:
            _evict(name)


def status():
    with _cond:
        now = time.monotonic()
        return {name: {'vram_gb': info['vram_gb'], 'active': _active[name], 'idle_seconds': round(now - info['last_used'], 1)}
                for name, info in _resident.items()}
