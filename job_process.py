"""Subprocess facade with per-worker cancellation, without patching other libraries."""
import contextlib
import os
import subprocess as _subprocess
import threading

_context = threading.local()
_cancel_generation = 0

def begin_job():
    _context.generation = _cancel_generation

def end_job():
    if hasattr(_context, 'generation'):
        del _context.generation

def cancel_all():
    global _cancel_generation
    _cancel_generation += 1

def cancellation_check():
    generation = getattr(_context, 'generation', _cancel_generation)
    callback = getattr(_context, 'cancelled', None)
    return lambda: generation != _cancel_generation or bool(callback and callback())

def __getattr__(name):
    return getattr(_subprocess, name)

def check_cancelled():
    if cancellation_check()():
        raise RuntimeError('Cancelled by user')

@contextlib.contextmanager
def cancellation_scope(cancelled):
    old = getattr(_context, 'cancelled', None)
    _context.cancelled = cancelled
    try:
        check_cancelled()
        yield
        check_cancelled()
    finally:
        _context.cancelled = old

class Popen(_subprocess.Popen):
    def __init__(self, *args, **kwargs):
        check_cancelled()
        cancelled = cancellation_check() if hasattr(_context, 'generation') or getattr(_context, 'cancelled', None) else None
        if os.name == 'nt':
            kwargs['creationflags'] = kwargs.get('creationflags', 0) | _subprocess.CREATE_NO_WINDOW
        super().__init__(*args, **kwargs)
        if cancelled:
            def watch():
                while self.poll() is None:
                    if cancelled():
                        if os.name == 'nt':
                            _subprocess.run(['taskkill', '/PID', str(self.pid), '/T', '/F'], capture_output=True,
                                            creationflags=_subprocess.CREATE_NO_WINDOW)
                            if self.poll() is None:
                                self.kill()
                        else:
                            self.kill()
                        return
                    threading.Event().wait(0.2)
            threading.Thread(target=watch, daemon=True).start()

def run(args, *, input=None, capture_output=False, timeout=None, check=False, **kwargs):
    if input is not None:
        kwargs['stdin'] = _subprocess.PIPE
    if capture_output:
        kwargs['stdout'] = kwargs['stderr'] = _subprocess.PIPE
    with Popen(args, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except BaseException:
            process.kill()
            process.communicate()
            raise
        check_cancelled()
        if check and process.returncode:
            raise _subprocess.CalledProcessError(process.returncode, args, stdout, stderr)
        return _subprocess.CompletedProcess(args, process.returncode, stdout, stderr)

def media_entries(info):
    if not isinstance(info, dict):
        return
    if info.get('_type') in ('playlist', 'multi_video'):
        for child in info.get('entries') or []:
            yield from media_entries(child)
    else:
        yield info
