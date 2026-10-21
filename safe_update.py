"""Bounded source updates with a durable rollback journal (standard library only)."""
import ast
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import uuid
import zipfile

MAX_BYTES = 100 * 1024 * 1024
FILES = {'app_local.py', 'ai_prompter.py', 'cleaner.py', 'media_safety.py', 'captions.py', 'creator_composition.py',
         'reference_prep.py', 'carousel_studio.py', 'safe_update.py', 'ai_runtime.py', 'job_process.py', 'download_support.py', 'requirements.txt', 'requirements-ai.txt',
         'README.md', 'CHANGELOG.md'}
DIRECTORIES = {'templates', 'static', 'assets', 'caption_fonts'}

def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temporary, path)

def target(root, relative):
    parts = PurePosixPath(relative).parts
    if not parts or '\\' in relative or ':' in relative or any(p in ('.', '..') for p in parts) or relative.startswith('/'):
        raise ValueError('Unsafe archive path')
    result = (root / relative).resolve()
    if root.resolve() not in result.parents:
        raise ValueError('Archive path escapes application folder')
    return result

def stage_archive(root, archive, version):
    root = Path(root).resolve()
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
                relative = member.filename.partition('/')[2]
                if not relative or member.is_dir():
                    continue
                first = relative.split('/')[0]
                if relative not in FILES and first not in DIRECTORIES:
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
        for required in ('app_local.py', 'safe_update.py', 'templates/index.html', 'requirements.txt'):
            if required not in selected:
                raise ValueError('Release is missing ' + required)
        # Never mutate a live Python environment. Dependency migrations require the installer.
        for name in ('requirements.txt', 'requirements-ai.txt'):
            if (stage / name).exists() and (root / name).exists():
                if (stage / name).read_text().strip() != (root / name).read_text().strip():
                    raise ValueError('This release changes dependencies. Install it using the release installer.')
        environment = dict(os.environ, MEDIA_GRABBER_DATA_DIR=str(stage / '.validation-data'))
        probe = subprocess.run([sys.executable, '-I', '-c',
                                'import sys; sys.path.insert(0, sys.argv[1]); import app_local', str(stage)],
                               cwd=stage, env=environment, capture_output=True, text=True, timeout=60,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if probe.returncode:
            # The app's console capture sends startup tracebacks to stdout too.
            details = (probe.stderr + '\n' + probe.stdout).strip()
            raise ValueError('Updated app failed its startup check: ' + details[-1000:])
        atomic_json(updates / 'pending.json', {'stage': stage.name, 'files': selected, 'version': version})
    except BaseException:
        shutil.rmtree(stage)
        raise

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
        rollback(json.loads(journal.read_text()))
        (updates / 'last_error.txt').write_text('An interrupted update was restored to the previous version.', encoding='utf-8')
        return True
    if not pending.exists():
        return
    plan = json.loads(pending.read_text())
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
    # Keep the backup for manual recovery after a successful installation.

    return True
