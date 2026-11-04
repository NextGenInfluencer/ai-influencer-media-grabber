"""Bounded source updates with a durable rollback journal (standard library only).

The set of files an update may touch comes from ``release_manifest.json`` inside the
downloaded release archive, so a release can ship new modules without first updating
the client. Every manifest entry is validated against a fixed client-side allow-list
(no absolute paths, no ``..``, only known roots). Archives without a manifest fall back
to ``DEFAULT_MANIFEST``.
"""
import ast
from dataclasses import dataclass
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import threading
import uuid
import zipfile

from storage_utils import atomic_write_json

MAX_BYTES = 100 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MANIFEST_NAME = 'release_manifest.json'
BACKUPS_TO_KEEP = 2

# Roots a release manifest may reference. Anything else requires the installer.
ALLOWED_DIRECTORIES = frozenset({'assets', 'static', 'templates', 'docs', 'ai_core'})
ALLOWED_TOP_LEVEL_SUFFIXES = frozenset({'.py', '.bat', '.sh', '.vbs', '.txt', '.json', '.md'})
# User data that lives next to the code in portable installs; never overwritten.
PROTECTED_NAMES = frozenset({'history.json', 'cookies.txt'})
NEVER_UPDATED_PREFIXES = ('static/fonts/custom/',)  # User uploads are never part of an update.
DEPENDENCY_FILES = ('requirements.txt', 'requirements-ai.txt', 'requirements-ai-common.txt', 'requirements-ai-cpu.txt',
                    'requirements-ai-directml.txt', 'requirements-ai-gpu.txt', 'requirements-ai-nodeps.txt')
REQUIRED_FILES = ('app_local.py', 'safe_update.py', 'templates/index.html', 'requirements.txt')

# Built-in manifest for archives that do not carry release_manifest.json.
DEFAULT_MANIFEST = {
    'version': 1,
    'patterns': ['*.py'],
    'files': ['run.bat', 'run.sh', 'launch-silent.vbs', 'install_ai.bat', *DEPENDENCY_FILES, 'ai_packs.json',
              MANIFEST_NAME, 'README.md', 'CHANGELOG.md', 'RELEASE_NOTES.md', 'THIRD_PARTY_NOTICES.md'],
    'directories': ['templates', 'static', 'assets', 'docs', 'ai_core'],
    'exclude': [],
}

_PATTERN = re.compile(r'^\*\.[A-Za-z0-9]+$')
_STAGE_LOCK = threading.Lock()


class UpdateInProgress(ValueError):
    """Raised when a second update is started while one is being prepared."""


def atomic_json(path, value):
    """Compatibility wrapper used by older call sites; see ``storage_utils``."""
    atomic_write_json(path, value, indent=None, ensure_ascii=True)


def target(root, relative):
    parts = PurePosixPath(relative).parts
    if not parts or '\\' in relative or ':' in relative or any(p in ('.', '..') for p in parts) or relative.startswith('/'):
        raise ValueError('Unsafe archive path')
    result = (root / relative).resolve()
    if root.resolve() not in result.parents:
        raise ValueError('Archive path escapes application folder')
    return result


def _clean_entry(entry):
    """Normalise one manifest path, rejecting anything that could escape the app folder."""
    if not isinstance(entry, str) or not entry.strip():
        raise ValueError(f'Unsafe release manifest entry: {entry!r}')
    text = entry.strip()
    parts = PurePosixPath(text).parts
    if ('\\' in text or ':' in text or text.startswith('/') or not parts
            or any(p in ('.', '..') or p.startswith('.') for p in parts)):
        raise ValueError(f'Unsafe release manifest entry: {entry!r}')
    return '/'.join(parts)


def _allowed(relative):
    first, _, rest = relative.partition('/')
    if rest:
        return first in ALLOWED_DIRECTORIES
    return (PurePosixPath(first).suffix.lower() in ALLOWED_TOP_LEVEL_SUFFIXES
            and first.lower() not in PROTECTED_NAMES)


@dataclass(frozen=True)
class Manifest:
    files: frozenset
    patterns: tuple
    directories: frozenset
    exclude: tuple

    def selects(self, relative):
        if not _allowed(relative) or any(relative.startswith(prefix) for prefix in self.exclude):
            return False
        if relative in self.files:
            return True
        first, _, rest = relative.partition('/')
        if rest:
            return first in self.directories
        return any(fnmatch.fnmatchcase(relative, pattern) for pattern in self.patterns)


def parse_manifest(data):
    """Validate a manifest mapping and return a ``Manifest``; raises ``ValueError`` on any unsafe entry."""
    if not isinstance(data, dict):
        raise ValueError('Release manifest must be a JSON object')
    lists = {}
    for key in ('files', 'patterns', 'directories', 'exclude'):
        value = data.get(key, [])
        if not isinstance(value, list):
            raise ValueError(f'Release manifest "{key}" must be a list')
        lists[key] = value
    files = set()
    for entry in lists['files']:
        relative = _clean_entry(entry)
        if not _allowed(relative):
            raise ValueError(f'Release manifest entry outside allowed roots: {entry!r}')
        files.add(relative)
    directories = set()
    for entry in lists['directories']:
        relative = _clean_entry(entry.rstrip('/') if isinstance(entry, str) else entry)
        if '/' in relative or relative not in ALLOWED_DIRECTORIES:
            raise ValueError(f'Release manifest directory not allowed: {entry!r}')
        directories.add(relative)
    patterns = []
    for entry in lists['patterns']:
        if not isinstance(entry, str) or not _PATTERN.match(entry) or entry[1:].lower() not in ALLOWED_TOP_LEVEL_SUFFIXES:
            raise ValueError(f'Release manifest pattern not allowed: {entry!r}')
        patterns.append(entry)
    exclude = list(NEVER_UPDATED_PREFIXES)
    for entry in lists['exclude']:
        relative = _clean_entry(entry)
        exclude.append(relative + '/' if isinstance(entry, str) and entry.strip().endswith('/') else relative)
    return Manifest(frozenset(files), tuple(patterns), frozenset(directories), tuple(exclude))


def load_manifest(path):
    """Read and validate a manifest file (used by the staging builder)."""
    return parse_manifest(json.loads(Path(path).read_text(encoding='utf-8-sig')))


def release_files(root, manifest=None):
    """Relative paths under ``root`` that a release built from this tree would contain."""
    root = Path(root).resolve()
    manifest = manifest or load_manifest(root / MANIFEST_NAME)
    candidates = [path for path in root.iterdir() if path.is_file()]
    for directory in sorted(manifest.directories):
        if (root / directory).is_dir():
            candidates.extend(path for path in (root / directory).rglob('*') if path.is_file())
    candidates.extend(root / name for name in manifest.files if '/' in name and (root / name).is_file())
    selected = set()
    for path in candidates:
        relative = path.relative_to(root).as_posix()
        if '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
            continue
        if any(part.startswith('.') for part in PurePosixPath(relative).parts):
            continue
        if manifest.selects(relative):
            selected.add(relative)
    return sorted(selected)


def _archive_manifest(source, prefix):
    """Manifest shipped inside the archive, or the built-in list for older releases."""
    try:
        info = source.getinfo(prefix + '/' + MANIFEST_NAME)
    except KeyError:
        return parse_manifest(DEFAULT_MANIFEST)
    if info.file_size > MAX_MANIFEST_BYTES:
        raise ValueError('Release manifest is too large')
    try:
        data = json.loads(source.read(info).decode('utf-8-sig'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f'Release manifest is not valid JSON: {exc}') from None
    return parse_manifest(data)


def _normalised_text(path):
    return path.read_text(encoding='utf-8-sig').replace('\r\n', '\n').strip()


ALLOWED_ENGINE_PACKAGES = ('yt-dlp', 'gallery-dl')
_ENGINE_PIN_RE = re.compile(r'^(yt-dlp|gallery-dl)==[A-Za-z0-9._+-]+$')


def _normalised_dependency_text(name, path):
    text = _normalised_text(path)
    if name != 'requirements.txt':
        return text
    return '\n'.join(_ENGINE_PIN_RE.sub(r'\1==<download-engine>', line.strip()) for line in text.split('\n'))


def _check_dependencies(root, stage):
    """Never mutate a live Python environment. Dependency migrations require the installer."""
    for name in DEPENDENCY_FILES:
        staged, live = stage / name, root / name
        if staged.exists() and live.exists() and _normalised_dependency_text(name, staged) != _normalised_dependency_text(name, live):
            raise ValueError('This release changes dependencies. Install it using the release installer.')


def stage_archive(root, archive, version):
    if not _STAGE_LOCK.acquire(blocking=False):
        raise UpdateInProgress('An update is already being prepared.')
    try:
        _stage_archive(Path(root).resolve(), archive, version)
    finally:
        _STAGE_LOCK.release()


def _stage_archive(root, archive, version):
    updates = root / '.updates'
    updates.mkdir(exist_ok=True)
    if (updates / 'pending.json').exists():
        raise ValueError('An update is already staged. Restart the app first.')
    stage = updates / uuid.uuid4().hex
    stage.mkdir()
    try:
        selected = []
        seen = set()
        with zipfile.ZipFile(archive) as source:
            members = source.infolist()
            if len(members) > 10000 or sum(m.file_size for m in members) > MAX_BYTES:
                raise ValueError('Update archive exceeds size limits')
            prefixes = {m.filename.split('/')[0] for m in members}
            if len(prefixes) != 1:
                raise ValueError('Expected one release archive root')
            for member in members:
                target(stage, member.filename)
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError('Archive links are not supported')
            manifest = _archive_manifest(source, prefixes.pop())
            for member in members:
                relative = member.filename.partition('/')[2]
                if not relative or member.is_dir() or not manifest.selects(relative):
                    continue
                if relative.lower() in seen:
                    raise ValueError('Duplicate archive file')
                seen.add(relative.lower())
                destination = target(stage, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read(member))
                if destination.suffix == '.py':
                    ast.parse(destination.read_text(encoding='utf-8-sig'))
                selected.append(relative)
        for required in REQUIRED_FILES:
            if required not in selected:
                raise ValueError('Release is missing ' + required)
        _check_dependencies(root, stage)
        environment = dict(os.environ, MEDIA_GRABBER_DATA_DIR=str(stage / '.validation-data'))
        probe = subprocess.run([sys.executable, '-I', '-c',
                                'import sys; sys.path.insert(0, sys.argv[1]); import app_local', str(stage)],
                               cwd=stage, env=environment, capture_output=True, text=True, timeout=60,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if probe.returncode:
            # The app's console capture sends startup tracebacks to stdout too.
            details = (probe.stderr + '\n' + probe.stdout).strip()
            raise ValueError('Updated app failed its startup check: ' + details[-1000:])
        shutil.rmtree(stage / '.validation-data', ignore_errors=True)
        atomic_json(updates / 'pending.json', {'stage': stage.name, 'files': selected, 'version': version})
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def prune_backups(updates, keep=BACKUPS_TO_KEEP):
    """Delete all but the newest ``keep`` recovery copies under ``.updates``."""
    updates = Path(updates)
    backups = sorted((p for p in updates.glob('backup-*') if p.is_dir()),
                     key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    for stale in backups[keep:]:
        shutil.rmtree(stale, ignore_errors=True)


def _read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def apply_pending(root):
    root = Path(root).resolve()
    updates = root / '.updates'
    journal = updates / 'journal.json'
    pending = updates / 'pending.json'
    def rollback(record):
        backup = target(updates, record['backup'])
        for relative, existed in reversed(record['files']):
            destination = target(root, relative)
            if existed:
                shutil.copy2(target(backup, relative), destination)
            else:
                destination.unlink(missing_ok=True)
        journal.unlink()
        pending.unlink(missing_ok=True)
    if journal.exists():
        rollback(_read_json(journal))
        (updates / 'last_error.txt').write_text('An interrupted update was restored to the previous version.', encoding='utf-8')
        return True
    if not pending.exists():
        return
    plan = _read_json(pending)
    stage = target(updates, plan['stage'])
    backup = updates / ('backup-' + uuid.uuid4().hex)
    backup.mkdir()
    record = {'backup': backup.name, 'files': []}
    for relative in plan['files']:
        destination = target(root, relative)
        saved = target(backup, relative)
        if destination.exists():
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, saved)
        record['files'].append([relative, destination.exists()])
    atomic_json(journal, record)
    try:
        for relative in plan['files']:
            destination = target(root, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + '.update-tmp')
            shutil.copy2(target(stage, relative), temporary)
            os.replace(temporary, destination)
        pending.unlink()
        journal.unlink()
    except BaseException:
        rollback(record)
        raise
    shutil.rmtree(stage)
    # Keep recent backups for manual recovery after a successful installation.
    prune_backups(updates)
    return True
