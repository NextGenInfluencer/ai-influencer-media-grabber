"""Initialize storage before any application imports, including unittest discovery."""
import atexit
import os
from pathlib import Path
import tempfile

_parent = Path(__file__).resolve().parents[1] / 'audit_artifacts'
_parent.mkdir(exist_ok=True)
_storage = tempfile.TemporaryDirectory(prefix='test-data-', dir=_parent)
DATA_ROOT = Path(_storage.name).resolve()
os.environ['MEDIA_GRABBER_DATA_DIR'] = str(DATA_ROOT)
os.environ['TEMP'] = os.environ['TMP'] = str(DATA_ROOT)
tempfile.tempdir = str(DATA_ROOT)
atexit.register(_storage.cleanup)


def assert_isolated(path):
    resolved = Path(path).resolve()
    if resolved != DATA_ROOT and DATA_ROOT not in resolved.parents:
        raise AssertionError(f'Test attempted to use non-isolated storage: {resolved}')
