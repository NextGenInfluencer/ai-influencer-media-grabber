"""Consent-gated, verified, resumable installs of catalog items. ``ensure`` never downloads."""
import hashlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

import requests

from . import catalog, paths, settings
from .errors import AIUnavailable, ConsentRequired, ModelMissing

log = logging.getLogger(__name__)
CHUNK = 1024 * 1024
DISK_MARGIN = 256 * 1024 * 1024
LIVE_TIMEOUT = (3, 5)
ASSUMED_DOWNLOAD_BPS = 10 * 1024 * 1024
MARKER = '.media-grabber-item.json'
KIND_ORDER = {'engine': 0, 'comfy_node': 1}

_jobs = {}
_jobs_lock = threading.Lock()
_manifest_lock = threading.Lock()


class _Cancelled(Exception):
    pass


# ---------------------------------------------------------------- helpers

def _root(item):
    return 'engines' if item.get('install_root') == 'engines' else 'models'


def _file_path(item, entry):
    return paths.resolve_item_path(entry['path'], _root(item))


def _candidates(item, entry):
    yield _file_path(item, entry)
    for legacy in entry.get('legacy') or []:
        yield paths.resolve_item_path(legacy)


def _manifest_file():
    return paths.MODELS_DIR / '.verified.json'


def _read_manifest():
    try:
        data = json.loads(_manifest_file().read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_manifest(data):
    target = _manifest_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f'.verified-{uuid.uuid4().hex}.tmp')
    temporary.write_text(json.dumps(data, indent=1), encoding='utf-8')
    os.replace(temporary, target)


def _stat_key(path):
    stat = path.stat()
    return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def _recorded_sha(path):
    """sha256 recorded for an unchanged file, else None."""
    entry = _read_manifest().get(str(path))
    try:
        if entry and {k: entry.get(k) for k in ('size', 'mtime_ns')} == _stat_key(path):
            return entry.get('sha256')
    except OSError:
        return None
    return None


def _record_sha(path, digest):
    with _manifest_lock:
        data = _read_manifest()
        data[str(path)] = {**_stat_key(path), 'sha256': digest}
        _write_manifest(data)


def _forget(path):
    with _manifest_lock:
        data = _read_manifest()
        if data.pop(str(path), None) is not None:
            _write_manifest(data)


def sha256_file(path, cancel=None):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(CHUNK), b''):
            if cancel and cancel():
                raise _Cancelled()
            digest.update(chunk)
    return digest.hexdigest()


def _file_sha(path, cancel=None):
    recorded = _recorded_sha(path)
    if recorded:
        return recorded
    digest = sha256_file(path, cancel)
    _record_sha(path, digest)
    return digest


def _present(item, entry):
    """First existing candidate with the expected size, or None."""
    for candidate in _candidates(item, entry):
        try:
            if candidate.is_file() and (not entry.get('size_bytes') or candidate.stat().st_size == entry['size_bytes']):
                return candidate
        except OSError:
            continue
    return None


def _extract_target(item):
    extract = item.get('extract') or {}
    target = extract.get('to')
    if not target:
        return None
    if target.startswith('@comfy/'):
        from . import engines
        root = engines.comfy.root()
        if root is None:
            return None
        resolved = (root / target[len('@comfy/'):]).resolve()
        if not paths.is_within(resolved, root):
            raise ValueError(f'Extraction target escapes the engine folder: {target}')
        return resolved
    return paths.resolve_item_path(target, _root(item))


def _ollama_names():
    from . import engines
    names = set()
    for entry in engines.ollama.tags():
        names.add(entry['name'])
        if entry['name'].endswith(':latest'):
            names.add(entry['name'][:-len(':latest')])
    return names


def _item_state(item, ollama_names=None):
    """Return (installed, verified, path) without network access to the internet."""
    if item.get('backend') == 'ollama':
        names = _ollama_names() if ollama_names is None else ollama_names
        tag = item['source']['ollama_tag']
        installed = tag in names
        return installed, installed, (tag if installed else None)
    if item['id'] == 'engine-ollama':
        from . import engines
        executable = engines.ollama.executable()
        return bool(executable), bool(executable), (str(executable) if executable else None)
    if item.get('extract'):
        target = _extract_target(item)
        if item['id'] == 'engine-comfyui':
            from . import engines
            ok = engines.comfy.installed()
            return ok, ok, (str(engines.comfy.root()) if ok else None)
        ok = bool(target and target.is_dir() and any(target.iterdir()))
        return ok, ok and (target / MARKER).is_file(), (str(target) if ok else None)
    found = [_present(item, entry) for entry in item.get('files', [])]
    if not found or any(path is None for path in found):
        return False, False, None
    verified = all(not entry.get('sha256') or _recorded_sha(path) == entry['sha256']
                   for entry, path in zip(item['files'], found))
    return True, verified, str(found[0])


def status():
    try:
        names = _ollama_names()
    except Exception:  # Ollama down is a normal state
        names = set()
    result = {}
    for item in catalog.items():
        installed, verified, path = _item_state(item, names)
        result[item['id']] = {'installed': installed, 'verified': verified, 'path': path,
                              'size_bytes': item.get('size_bytes')}
    return result


# ---------------------------------------------------------------- notices

def _live_file_size(url):
    try:
        response = requests.head(url, allow_redirects=False, timeout=LIVE_TIMEOUT)
        linked = response.headers.get('X-Linked-Size')
        if linked and linked.isdigit():
            return int(linked)
        if 300 <= response.status_code < 400:
            response = requests.head(url, allow_redirects=True, timeout=LIVE_TIMEOUT)
        length = response.headers.get('Content-Length')
        if response.status_code == 200 and length and length.isdigit() and int(length) > 0:
            return int(length)
    except requests.RequestException:
        return None
    return None


def _live_ollama_size(tag):
    name, _, version = tag.partition(':')
    try:
        response = requests.get(f'https://registry.ollama.ai/v2/library/{name}/manifests/{version or "latest"}',
                                headers={'Accept': 'application/vnd.docker.distribution.manifest.v2+json'},
                                timeout=LIVE_TIMEOUT)
        response.raise_for_status()
        layers = response.json().get('layers', [])
        total = sum(int(layer.get('size', 0)) for layer in layers if isinstance(layer, dict))
        return total or None
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return None


def live_size(item):
    """(size_bytes, 'live'|'catalog') read from the source with short timeouts."""
    if item.get('backend') == 'ollama':
        size = _live_ollama_size(item['source']['ollama_tag'])
        return (size, 'live') if size else (item.get('size_bytes'), 'catalog')
    total, live = 0, True
    for entry in item.get('files', []):
        size = _live_file_size(entry['url'])
        if size is None:
            live, size = False, entry.get('size_bytes') or 0
        total += size
    return total, ('live' if live and item.get('files') else 'catalog')


def _closure(item_id):
    """Item plus companions (recursively), installation order: engines → nodes → models."""
    seen, order = set(), []

    def visit(current):
        if current in seen:
            return
        seen.add(current)
        for companion in catalog.get(current).get('companions', []):
            visit(companion)
        order.append(current)
    visit(item_id)
    main = order.pop()
    order.sort(key=lambda i: KIND_ORDER.get(catalog.get(i)['kind'], 2))
    return order + [main]


def _disk_free(path):
    target = Path(path)
    while not target.exists() and target != target.parent:
        target = target.parent
    try:
        return shutil.disk_usage(target).free
    except OSError:
        return 0


def notice(item_id):
    item = catalog.get(item_id)
    states = status()
    accepted = settings.accepted_licenses()
    size, size_source = live_size(item)
    companions = []
    download = 0 if states[item_id]['installed'] else (size or 0)
    for companion_id in _closure(item_id)[:-1]:
        companion = catalog.get(companion_id)
        installed = states[companion_id]['installed']
        companions.append({'id': companion_id, 'name': companion['name'], 'kind': companion['kind'],
                           'size_bytes': companion.get('size_bytes'), 'installed': installed,
                           'license': companion['license'], 'non_commercial': companion['license'].get('non_commercial', False)})
        if not installed:
            download += companion.get('size_bytes') or 0
    free = _disk_free(paths.ENGINES_DIR if _root(item) == 'engines' else paths.MODELS_DIR)
    nc = item['license'].get('non_commercial', False) or any(c['non_commercial'] and not c['installed'] for c in companions)
    return {
        'id': item_id, 'name': item['name'], 'kind': item['kind'], 'purpose': item.get('purpose'),
        'features': item.get('features', []), 'roles': item.get('roles', []), 'profiles': item.get('profiles', []),
        'local': item.get('local', True), 'source': item['source'], 'license': item['license'],
        'non_commercial': nc, 'license_accepted': item_id in accepted,
        'consent_required': item_id not in accepted, 'size_bytes': size, 'size_source': size_source,
        'download_bytes': download, 'companions': companions, 'disk_free_bytes': free,
        'disk_ok': free >= download + DISK_MARGIN, 'vram_gb': item.get('vram_gb', 0), 'ram_gb': item.get('ram_gb', 0),
        'eta_download_seconds': int(download / ASSUMED_DOWNLOAD_BPS), 'installed': states[item_id]['installed'],
    }


# ---------------------------------------------------------------- installs

def _new_job(item_id, plan):
    job = {'id': uuid.uuid4().hex, 'item_id': item_id, 'items': plan, 'state': 'queued', 'progress': 0.0,
           'bytes_done': 0, 'bytes_total': 0, 'current': None, 'message': 'Queued', 'error': None,
           'setup_hint': None, 'started': time.time(), 'finished': None}
    job['_cancel'] = threading.Event()
    return job


def start_install(item_id, accept_license=False):
    """Start a background install of an item and its missing companions.

    Every download needs the user's explicit acceptance of the notice
    (``accept_license=True``) unless that item's license was accepted before.
    """
    item = catalog.get(item_id)
    plan = _closure(item_id)
    states = status()
    pending = [i for i in plan if not (states[i]['installed'] and states[i]['verified'])]
    accepted = settings.accepted_licenses()
    unaccepted = [i for i in (pending or [item_id]) if i not in accepted]
    if unaccepted and not accept_license:
        nc = [i for i in unaccepted if catalog.get(i)['license'].get('non_commercial')]
        message = (f'{item["name"]} has a personal / non-commercial license. Review and accept it before downloading.'
                   if nc else f'Review the download notice for {item["name"]} and confirm before downloading.')
        raise ConsentRequired(message, setup_hint=item_id)
    if accept_license:
        for accepted_id in unaccepted:
            settings.accept_license(accepted_id)
    with _jobs_lock:
        for job in _jobs.values():
            if job['item_id'] == item_id and job['state'] in ('queued', 'running'):
                return job['id']
        job = _new_job(item_id, pending)
        _jobs[job['id']] = job
    threading.Thread(target=_run_install, args=(job,), name=f'install-{item_id}', daemon=True).start()
    return job['id']


def job(job_id):
    with _jobs_lock:
        current = _jobs.get(job_id)
        return {k: v for k, v in current.items() if not k.startswith('_')} if current else None


def jobs():
    with _jobs_lock:
        return [{k: v for k, v in j.items() if not k.startswith('_')} for j in _jobs.values()]


def cancel(job_id):
    with _jobs_lock:
        current = _jobs.get(job_id)
        if not current or current['state'] not in ('queued', 'running'):
            return False
        current['_cancel'].set()
        current['message'] = 'Cancelling…'
        return True


def _update(job_ref, **fields):
    with _jobs_lock:
        job_ref.update(fields)
        if job_ref['bytes_total']:
            job_ref['progress'] = round(min(1.0, job_ref['bytes_done'] / job_ref['bytes_total']), 4)


def _run_install(job_ref):
    import job_process
    cancelled = job_ref['_cancel'].is_set
    _update(job_ref, state='running', message='Preparing…')
    try:
        total = 0
        for item_id in job_ref['items']:
            item = catalog.get(item_id)
            total += item.get('size_bytes') or 0
        _update(job_ref, bytes_total=total)
        with job_process.cancellation_scope(cancelled):
            for item_id in job_ref['items']:
                _install_item(catalog.get(item_id), job_ref, cancelled)
        _update(job_ref, state='done', progress=1.0, message='Installed', finished=time.time(), current=None)
    except (_Cancelled, RuntimeError) as exc:
        if cancelled():
            _update(job_ref, state='cancelled', message='Cancelled. Partial downloads are kept to resume later.',
                    finished=time.time())
        else:
            _fail(job_ref, exc)
    except Exception as exc:
        _fail(job_ref, exc)


def _fail(job_ref, exc):
    log.warning('Install %s failed: %s', job_ref['item_id'], exc)
    _update(job_ref, state='error', error=str(exc), message=str(exc), finished=time.time(),
            setup_hint=getattr(exc, 'setup_hint', None))


def _install_item(item, job_ref, cancelled):
    _update(job_ref, current=item['id'], message=f'Installing {item["name"]}…')
    if item.get('backend') == 'ollama':
        _pull_ollama(item, job_ref, cancelled)
        return
    for entry in item.get('files', []):
        destination = _file_path(item, entry)
        if not item.get('extract') and _present(item, entry):
            _verify_existing(item, entry, job_ref, cancelled)
            continue
        _download(entry, destination, job_ref, cancelled)
        if item.get('extract'):
            _extract(item, destination, cancelled)
    if item.get('kind') == 'comfy_node':
        from . import engines
        engines.comfy.install_requirements(item['node_folder'])
    if item.get('comfy_links'):
        from . import engines
        if engines.comfy.installed():
            engines.comfy.link_models(item)
    if item['id'] == 'engine-comfyui':
        from . import engines
        engines.comfy.write_model_paths()


def _verify_existing(item, entry, job_ref, cancelled):
    path = _present(item, entry)
    if entry.get('sha256') and _file_sha(path, cancelled) != entry['sha256']:
        raise AIUnavailable(f'{path.name} exists but failed verification. It was left unchanged; '
                            'move it aside and install again.', setup_hint=item['id'])
    _update(job_ref, bytes_done=job_ref['bytes_done'] + (entry.get('size_bytes') or 0))


def _download(entry, destination, job_ref, cancelled):
    """Resumable download into ``.part``; replaced into place only after verification."""
    expected = entry.get('size_bytes') or 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + '.part')
    digest = hashlib.sha256()
    have = part.stat().st_size if part.is_file() else 0
    if expected and have > expected:
        part.unlink()
        have = 0
    if _disk_free(destination.parent) < max(0, expected - have) + DISK_MARGIN:
        raise AIUnavailable(f'Not enough free disk space for {destination.name}. Free at least '
                            f'{(expected - have + DISK_MARGIN) / 1024 ** 3:.1f} GB and retry.', setup_hint='storage')
    if have:
        with open(part, 'rb') as existing:
            for chunk in iter(lambda: existing.read(CHUNK), b''):
                if cancelled():
                    raise _Cancelled()
                digest.update(chunk)
    base_done = job_ref['bytes_done']
    received = have
    headers = {'Range': f'bytes={have}-'} if have else {}
    with requests.get(entry['url'], stream=True, timeout=(10, 60), headers=headers) as response:
        if have and response.status_code == 200:
            have = received = 0
            digest = hashlib.sha256()
            mode = 'wb'
        elif response.status_code == 416 and have == expected:
            mode = None
        else:
            response.raise_for_status()
            mode = 'ab' if have else 'wb'
        if mode:
            with open(part, mode) as output:
                for chunk in response.iter_content(chunk_size=CHUNK):
                    if cancelled():
                        raise _Cancelled()
                    if not chunk:
                        continue
                    received += len(chunk)
                    if expected and received > expected:
                        raise AIUnavailable(f'{destination.name} is larger than expected; download rejected.')
                    output.write(chunk)
                    digest.update(chunk)
                    _update(job_ref, bytes_done=base_done + received,
                            message=f'Downloading {destination.name}: {received / 1024 ** 2:.0f} MB')
    if expected and received != expected:
        raise AIUnavailable(f'{destination.name} download was incomplete. Retry to resume.')
    actual = digest.hexdigest()
    if entry.get('sha256') and actual != entry['sha256']:
        part.unlink(missing_ok=True)
        raise AIUnavailable(f'{destination.name} failed SHA-256 verification and was discarded. Retry the install.')
    if cancelled():
        raise _Cancelled()
    os.replace(part, destination)
    _record_sha(destination, actual)


def _safe_member(name, strip):
    parts = [p for p in PurePosixPath(name.replace('\\', '/')).parts if p not in ('', '.')]
    if any(p == '..' for p in parts) or (parts and (parts[0].endswith(':') or name.startswith('/'))):
        raise AIUnavailable('Archive contains unsafe paths; installation stopped.')
    return parts[strip:]


def _extract(item, archive, cancelled):
    extract = item['extract']
    target = _extract_target(item)
    if target is None:
        raise ModelMissing('Install the creative engine first.', setup_hint='engine-comfyui')
    strip = int(extract.get('strip_components', 0))
    staging = target.with_name(target.name + '.extracting')
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        if extract['format'] == 'zip':
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.infolist():
                    if cancelled():
                        raise _Cancelled()
                    parts = _safe_member(member.filename, strip)
                    if not parts or member.is_dir():
                        continue
                    out = staging.joinpath(*parts)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(member) as source, open(out, 'wb') as sink:
                        shutil.copyfileobj(source, sink, CHUNK)
        elif extract['format'] == '7z':
            _extract_7z(archive, staging)
        else:
            raise AIUnavailable(f'Unsupported archive format {extract["format"]}.')
        for relative in item.get('post_install_remove') or []:
            victim = (staging / relative).resolve()
            if paths.is_within(victim, staging) and victim.is_file():
                victim.unlink()
        (staging / MARKER).write_text(json.dumps({'item_id': item['id'], 'sha256': item.get('sha256')}), encoding='utf-8')
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    archive.unlink(missing_ok=True)
    _forget(archive)


def _extract_7z(archive, destination):
    """Use Windows' bundled bsdtar (libarchive reads 7z); no extra Python dependency."""
    import job_process
    tar = shutil.which('tar')
    if not tar:
        raise AIUnavailable('This PC has no archive tool to unpack the creative engine (Windows 10 1803+ includes one).',
                            setup_hint='engines')
    listing = job_process.run([tar, '-tf', str(archive)], capture_output=True, timeout=600)
    if listing.returncode:
        raise AIUnavailable('The creative engine archive could not be read. Retry the install.', setup_hint='engines')
    for name in listing.stdout.decode('utf-8', 'replace').splitlines():
        _safe_member(name, 0)
    result = job_process.run([tar, '-xf', str(archive), '-C', str(destination)], capture_output=True, timeout=3600)
    if result.returncode:
        raise AIUnavailable('Unpacking the creative engine failed. Free disk space and retry.', setup_hint='engines')


def _pull_ollama(item, job_ref, cancelled):
    from . import engines
    engines.ollama.ensure_running()
    tag = item['source']['ollama_tag']
    layers = {}
    base_done = job_ref['bytes_done']
    with requests.post(engines.ollama.base_url + '/api/pull', json={'model': tag, 'stream': True},
                       stream=True, timeout=(10, 300), allow_redirects=False) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if cancelled():
                raise _Cancelled()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError as exc:
                raise AIUnavailable('Ollama returned an invalid download response.') from exc
            if not isinstance(event, dict):
                raise AIUnavailable('Ollama returned an invalid download response.')
            if event.get('error'):
                raise AIUnavailable(f'Ollama could not download {tag}: {event["error"]}', setup_hint=item['id'])
            if event.get('digest') and event.get('total'):
                layers[event['digest']] = (int(event.get('completed') or 0), int(event['total']))
                done = sum(c for c, _ in layers.values())
                _update(job_ref, bytes_done=base_done + done, message=f'Downloading {tag}: {done / 1024 ** 3:.2f} GB')
            if event.get('status') == 'success':
                _update(job_ref, bytes_done=base_done + (item.get('size_bytes') or 0))
                return
    raise AIUnavailable(f'Ollama stopped before {tag} finished downloading. Retry to resume.', setup_hint=item['id'])


# ---------------------------------------------------------------- removal & storage

def remove(item_id):
    """Remove an installed item. Read-only legacy caches in the user profile are never deleted."""
    item = catalog.get(item_id)
    removed = []
    if item.get('backend') == 'ollama':
        from . import engines
        try:
            response = requests.delete(engines.ollama.base_url + '/api/delete', json={'model': item['source']['ollama_tag']},
                                       timeout=(3, 30), allow_redirects=False)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AIUnavailable('Ollama must be running to remove its models.', setup_hint='engines') from exc
        return {'removed': [item['source']['ollama_tag']]}
    if item.get('extract'):
        target = paths.ENGINES_DIR / 'comfyui' if item_id == 'engine-comfyui' else _extract_target(item)
        if target and target.is_dir() and paths.is_within(target, paths.ENGINES_DIR):
            if item_id == 'engine-comfyui':
                from . import engines
                engines.comfy.stop()
            shutil.rmtree(target)
            removed.append(str(target))
        return {'removed': removed}
    for entry in item.get('files', []):
        for candidate in _candidates(item, entry):
            if candidate.is_file() and not paths.is_within(candidate, paths.HOME_DIR / '.cache') \
                    and not paths.is_within(candidate, paths.HOME_DIR / '.insightface'):
                candidate.unlink()
                _forget(candidate)
                removed.append(str(candidate))
    return {'removed': removed}


def _catalog_paths():
    owned = set()
    for item in catalog.items():
        for entry in item.get('files', []):
            try:
                owned.add(str(_file_path(item, entry)))
            except ValueError:
                continue
    return owned


def reclaimable(cancel=None):
    """Duplicate files (same size + SHA-256) in MODELS_DIR, obsolete files and stale partial downloads."""
    results = []
    owned = _catalog_paths()
    by_size = {}
    if paths.MODELS_DIR.is_dir():
        for path in paths.MODELS_DIR.rglob('*'):
            if not path.is_file() or path.name.startswith('.'):
                continue
            if path.suffix == '.part':
                if time.time() - path.stat().st_mtime > 86400 and not _downloads_running():
                    results.append({'path': str(path), 'size_bytes': path.stat().st_size, 'reason': 'incomplete download'})
                continue
            size = path.stat().st_size
            if size >= CHUNK:
                by_size.setdefault(size, []).append(path)
    for group in by_size.values():
        if len(group) < 2:
            continue
        by_hash = {}
        for path in group:
            by_hash.setdefault(_file_sha(path, cancel), []).append(path)
        for same in by_hash.values():
            if len(same) < 2:
                continue
            same.sort(key=lambda p: (str(p) not in owned, str(p)))
            keep = same[0]
            for duplicate in same[1:]:
                results.append({'path': str(duplicate), 'size_bytes': duplicate.stat().st_size,
                                'reason': 'duplicate', 'duplicate_of': str(keep)})
    for obsolete in catalog.section('obsolete_files') or []:
        path = paths.resolve_item_path(obsolete['path'])
        if path.is_file():
            results.append({'path': str(path), 'size_bytes': path.stat().st_size, 'reason': obsolete['reason']})
    for entry in results:
        entry['id'] = hashlib.sha256(entry['path'].encode('utf-8')).hexdigest()[:16]
    return results


def _downloads_running():
    with _jobs_lock:
        return any(j['state'] in ('queued', 'running') for j in _jobs.values())


def remove_reclaimable(path_or_id):
    """Delete one entry, but only if it is currently listed by ``reclaimable()``."""
    for entry in reclaimable():
        if path_or_id in (entry['id'], entry['path']):
            target = Path(entry['path'])
            target.unlink()
            _forget(target)
            return entry
    raise ValueError('Only files listed under Reclaim space can be removed here.')


def storage():
    states = status()
    installed = []
    for item in catalog.items():
        state = states[item['id']]
        if state['installed']:
            installed.append({'id': item['id'], 'name': item['name'], 'kind': item['kind'], 'path': state['path'],
                              'size_bytes': item.get('size_bytes'), 'features': item.get('features', []),
                              'verified': state['verified'], 'non_commercial': item['license'].get('non_commercial', False),
                              'missing_companions': [c for c in item.get('companions', []) if not states[c]['installed']]})
    return {'installed': installed, 'reclaimable': reclaimable(), 'models_dir': str(paths.MODELS_DIR),
            'engines_dir': str(paths.ENGINES_DIR), 'disk_free_bytes': _disk_free(paths.MODELS_DIR)}


# ---------------------------------------------------------------- runtime lookup

def ensure(item_id):
    """Local path of an installed, verified item; raises ModelMissing. Never downloads.

    For Ollama items the tag must be pulled; the Ollama executable path is returned.
    """
    item = catalog.get(item_id)
    hint = item_id
    if item.get('backend') == 'ollama':
        from . import engines
        if item['source']['ollama_tag'] not in _ollama_names():
            raise ModelMissing(f'{item["name"]} is not installed in Ollama. Install it from AI Setup.', setup_hint=hint)
        executable = engines.ollama.executable()
        return Path(executable) if executable else Path(engines.ollama.base_url)
    installed, _, path = _item_state(item)
    if not installed:
        raise ModelMissing(f'{item["name"]} is not installed. Install it from AI Setup.', setup_hint=hint)
    if not item.get('extract'):
        for entry in item.get('files', []):
            found = _present(item, entry)
            if entry.get('sha256') and _file_sha(found) != entry['sha256']:
                raise ModelMissing(f'{found.name} failed verification. Remove it and install {item["name"]} again.',
                                   setup_hint=hint)
    return Path(path)


def installed(item_id):
    try:
        return _item_state(catalog.get(item_id))[0]
    except KeyError:
        return False


__all__ = ['status', 'notice', 'start_install', 'job', 'jobs', 'cancel', 'remove', 'reclaimable',
           'remove_reclaimable', 'storage', 'ensure', 'installed', 'live_size', 'sha256_file']
