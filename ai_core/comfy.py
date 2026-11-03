"""ComfyUI API client and pinned workflow runner (upload → prompt → poll → view)."""
import copy
import json
import time
import uuid
from pathlib import Path

import requests

from job_process import check_cancelled

from . import catalog, engines, gpu, models, paths
from .errors import AIUnavailable, ModelMissing

WORKFLOWS_DIR = Path(__file__).with_name('workflows')
POLL_SECONDS = 1.0
DEFAULT_TIMEOUT = 4 * 3600
CASTS = {'int': int, 'float': float, 'string': str, 'file': str}


class ComfyClient:
    def __init__(self, base_url=None):
        self.base_url = (base_url or engines.comfy.base_url).rstrip('/')
        self.client_id = uuid.uuid4().hex

    def _post(self, path, **kwargs):
        try:
            response = requests.post(self.base_url + path, timeout=kwargs.pop('timeout', (5, 60)),
                                     allow_redirects=False, **kwargs)
        except requests.RequestException as exc:
            raise AIUnavailable('The creative engine stopped responding.', setup_hint='engines') from exc
        return response

    def _get(self, path, **kwargs):
        try:
            return requests.get(self.base_url + path, timeout=kwargs.pop('timeout', (5, 60)), allow_redirects=False, **kwargs)
        except requests.RequestException as exc:
            raise AIUnavailable('The creative engine stopped responding.', setup_hint='engines') from exc

    def upload(self, path):
        path = Path(path)
        if not path.is_file():
            raise ValueError(f'Input file not found: {path.name}')
        with open(path, 'rb') as handle:
            response = self._post('/upload/image', files={'image': (path.name, handle)},
                                  data={'overwrite': 'true', 'type': 'input'}, timeout=(5, 600))
        if response.status_code != 200:
            raise AIUnavailable(f'Uploading {path.name} to the creative engine failed (HTTP {response.status_code}).')
        data = response.json()
        return f'{data["subfolder"]}/{data["name"]}' if data.get('subfolder') else data['name']

    def queue(self, graph):
        response = self._post('/prompt', json={'prompt': graph, 'client_id': self.client_id})
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code != 200 or 'prompt_id' not in data:
            error = data.get('error') or {}
            message = error.get('message') if isinstance(error, dict) else str(error)
            nodes = data.get('node_errors') or {}
            details = '; '.join(f'{node}: {", ".join(e.get("message", "") for e in info.get("errors", []))}'
                                for node, info in nodes.items() if isinstance(info, dict))
            raise AIUnavailable(f'The creative engine rejected the workflow: {message or "invalid prompt"}'
                                + (f' ({details})' if details else ''), setup_hint='engines')
        return data['prompt_id']

    def queue_position(self, prompt_id):
        response = self._get('/queue', timeout=(3, 10))
        try:
            data = response.json()
        except ValueError:
            return None
        if any(entry[1] == prompt_id for entry in data.get('queue_running', []) if len(entry) > 1):
            return 0
        pending = [entry[1] for entry in data.get('queue_pending', []) if len(entry) > 1]
        return pending.index(prompt_id) + 1 if prompt_id in pending else None

    def history(self, prompt_id):
        response = self._get(f'/history/{prompt_id}', timeout=(3, 30))
        if response.status_code != 200:
            return None
        try:
            return response.json().get(prompt_id)
        except ValueError:
            return None

    def interrupt(self, prompt_id=None):
        self._post('/interrupt', json={'prompt_id': prompt_id} if prompt_id else {}, timeout=(3, 10))
        if prompt_id:
            self._post('/queue', json={'delete': [prompt_id]}, timeout=(3, 10))

    def free(self):
        self._post('/free', json={'unload_models': True, 'free_memory': True}, timeout=(3, 30))

    def wait(self, prompt_id, progress=None, timeout=DEFAULT_TIMEOUT):
        started = time.monotonic()
        try:
            while True:
                check_cancelled()
                entry = self.history(prompt_id)
                if entry:
                    status = entry.get('status') or {}
                    if status.get('status_str') == 'error':
                        messages = [m[1].get('exception_message') for m in status.get('messages', [])
                                    if isinstance(m, list) and len(m) > 1 and isinstance(m[1], dict)
                                    and m[1].get('exception_message')]
                        raise AIUnavailable('The creative engine failed: ' + ('; '.join(messages) or 'unknown error'))
                    if status.get('completed', True):
                        return entry.get('outputs') or {}
                if time.monotonic() - started > timeout:
                    raise AIUnavailable('The creative engine job timed out.')
                engines.comfy.touch()
                if progress:
                    position = self.queue_position(prompt_id)
                    progress({'state': 'running' if position == 0 else 'queued', 'position': position,
                              'elapsed': round(time.monotonic() - started, 1)})
                time.sleep(POLL_SECONDS)
        except RuntimeError as exc:
            if 'Cancelled' in str(exc) and not isinstance(exc, AIUnavailable):
                self.interrupt(prompt_id)
            raise

    def download(self, info, destination_dir):
        params = {'filename': info['filename'], 'subfolder': info.get('subfolder', ''), 'type': info.get('type', 'output')}
        destination_dir = Path(destination_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)
        target = destination_dir / Path(info['filename']).name
        try:
            with requests.get(self.base_url + '/view', params=params, stream=True, timeout=(5, 300),
                              allow_redirects=False) as response:
                if response.status_code != 200:
                    raise AIUnavailable(f'Could not fetch {info["filename"]} from the creative engine.')
                with open(target, 'wb') as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        check_cancelled()
                        output.write(chunk)
        except requests.RequestException as exc:
            raise AIUnavailable('The creative engine stopped responding.', setup_hint='engines') from exc
        return target


def workflow_spec(name):
    meta = catalog.workflow(name)
    data = json.loads((WORKFLOWS_DIR / meta['file']).read_text(encoding='utf-8'))
    return meta, data


def _fill(node, values):
    if isinstance(node, dict):
        return {key: _fill(value, values) for key, value in node.items()}
    if isinstance(node, list):
        return [_fill(value, values) for value in node]
    if isinstance(node, str) and node.startswith('{{') and node.endswith('}}') and node[2:-2] in values:
        return values[node[2:-2]]
    return node


def build_prompt(name, inputs, uploader=None):
    """Fill a workflow's placeholders; file inputs go through ``uploader`` (path → uploaded name)."""
    _, data = workflow_spec(name)
    values = {}
    for key, spec in data['inputs'].items():
        if key in inputs and inputs[key] is not None:
            value = inputs[key]
        elif 'default' in spec:
            value = spec['default']
        elif spec.get('required'):
            raise ValueError(f'Missing workflow input: {key}')
        else:
            continue
        if spec['type'] == 'file':
            value = uploader(value) if uploader else str(value)
        values[key] = CASTS[spec['type']](value)
    graph = _fill(copy.deepcopy(data['prompt']), values)
    leftovers = [k for k in data['inputs'] if k not in values]
    if leftovers:
        raise ValueError(f'Missing workflow inputs: {", ".join(leftovers)}')
    return graph


def requirements_missing(name):
    meta = catalog.workflow(name)
    return [item_id for item_id in meta.get('requires', []) + meta.get('custom_nodes', [])
            if not models.installed(item_id)]


def _collect_files(outputs):
    files = []
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        for key in ('images', 'videos', 'gifs', 'audio'):
            for info in node_output.get(key) or []:
                if isinstance(info, dict) and info.get('filename') and info.get('type', 'output') == 'output':
                    files.append(info)
    return files


def run_workflow(name, inputs, *, progress=None):
    """Run a pinned workflow locally; returns downloaded output paths. Raises on any failure."""
    missing = requirements_missing(name)
    if missing:
        raise ModelMissing(f'This feature needs {catalog.get(missing[0])["name"]} on this PC.', setup_hint=missing[0])
    meta = catalog.workflow(name)
    vram = max([catalog.get(i).get('vram_gb', 0) for i in meta.get('requires', [])] or [0])
    engines.comfy.ensure_running()
    client = ComfyClient()
    with gpu.lease('comfy', vram):
        graph = build_prompt(name, inputs, uploader=client.upload)
        prompt_id = client.queue(graph)
        outputs = client.wait(prompt_id, progress=progress)
        files = _collect_files(outputs)
        if not files:
            raise AIUnavailable('The creative engine finished without producing an output file.')
        destination = paths.DATA_DIR / 'AI Studio' / name
        results = [client.download(info, destination) for info in files]
    engines.comfy.touch()
    return results
