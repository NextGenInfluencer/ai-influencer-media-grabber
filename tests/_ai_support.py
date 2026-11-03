"""Shared fixtures for ai_core tests: isolated paths, a fake local Ollama and a fake ComfyUI."""
import tests._isolation  # noqa: F401  (must precede application imports)
import json
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from ai_core import catalog, gpu, paths

HIGH_INFO = {'gpu_vendor': 'nvidia', 'gpu_name': 'RTX 3080', 'vram_gb': 12.0, 'ram_gb': 32.0,
             'disk_free_gb': 500.0, 'os': 'Windows 10', 'cpu_count': 16, 'gpus': [], 'ai_pack': True}
LAPTOP_INFO = {'gpu_vendor': 'intel', 'gpu_name': 'Intel UHD', 'vram_gb': 0.0, 'ram_gb': 8.0,
               'disk_free_gb': 100.0, 'os': 'Windows 11', 'cpu_count': 8, 'gpus': [], 'ai_pack': True}


class IsolatedAIMixin:
    """Points every ai_core path at a temporary folder and silences real engines."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(dir=tests._isolation.DATA_ROOT)
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.root = root
        values = {'DATA_DIR': root, 'MODELS_DIR': root / 'models', 'ENGINES_DIR': root / 'engines',
                  'SETTINGS_FILE': root / 'ai_settings.json', 'HOME_DIR': root / 'home', 'APP_DIR': root / 'app'}
        for name, value in values.items():
            patcher = patch.object(paths, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        (root / 'home').mkdir()
        (root / 'app').mkdir()
        self.addCleanup(catalog.reload)
        self.addCleanup(gpu.release_all)

    def use_catalog(self, items, **sections):
        data = catalog.data()
        data['items'] = items
        data.update(sections)
        catalog.reload()
        catalog._cache = data
        return data


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class _Server:
    def __init__(self, handler_factory):
        self.requests = []
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_factory(self))
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def _handler(owner, routes):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def _dispatch(self, method):
            length = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(length) if length else b''
            try:
                body = json.loads(raw) if raw and 'json' in (self.headers.get('Content-Type') or '') else raw
            except ValueError:
                body = raw
            owner.requests.append((method, self.path, body))
            status, headers, payload = routes(owner, method, self.path, body)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._dispatch('GET')

        def do_POST(self):
            self._dispatch('POST')

        def do_DELETE(self):
            self._dispatch('DELETE')
    return Handler


class FakeOllama(_Server):
    """Minimal local Ollama: /api/version, tags, show, ps, chat (scripted NDJSON), generate, pull, delete."""

    def __init__(self, models=None, show=None):
        self.models = list(models or [])
        self.show = dict(show or {})
        self.chat_script = []
        self.loaded = []
        self.pull_events = [{'status': 'pulling manifest'},
                            {'status': 'downloading', 'digest': 'sha256:a', 'total': 100, 'completed': 50},
                            {'status': 'downloading', 'digest': 'sha256:a', 'total': 100, 'completed': 100},
                            {'status': 'success'}]
        super().__init__(lambda owner: _handler(owner, FakeOllama._route))

    @staticmethod
    def _route(owner, method, path, body):
        if path == '/api/version':
            return 200, {}, {'version': '0.40.14'}
        if path == '/api/tags':
            return 200, {}, {'models': owner.models}
        if path == '/api/show':
            name = body.get('model') if isinstance(body, dict) else None
            return 200, {}, owner.show.get(name, {'model_info': {'general.architecture': 'qwen3'}, 'capabilities': ['completion']})
        if path == '/api/ps':
            return 200, {}, {'models': [{'name': name} for name in owner.loaded]}
        if path == '/api/generate':
            return 200, {}, {'done': True}
        if path == '/api/delete':
            return 200, {}, {}
        if path == '/api/pull':
            return 200, {'Content-Type': 'application/x-ndjson'}, ''.join(json.dumps(e) + '\n' for e in owner.pull_events).encode()
        if path == '/api/chat':
            events = owner.chat_script.pop(0) if owner.chat_script else [{'message': {'content': ''}, 'done': True}]
            return 200, {'Content-Type': 'application/x-ndjson'}, ''.join(json.dumps(e) + '\n' for e in events).encode()
        return 404, {}, {'error': 'not found'}

    def chat_requests(self):
        return [body for method, path, body in self.requests if path == '/api/chat']


class FakeComfy(_Server):
    """Minimal ComfyUI API: upload, prompt, queue, history, view, interrupt, free."""

    def __init__(self):
        self.graphs = []
        self.history_after = 1
        self.polls = 0
        self.fail_prompt = None
        self.error_history = False
        super().__init__(lambda owner: _handler(owner, FakeComfy._route))

    @staticmethod
    def _route(owner, method, path, body):
        if path == '/system_stats':
            return 200, {}, {'system': {}}
        if path == '/upload/image':
            return 200, {}, {'name': 'uploaded.png', 'subfolder': '', 'type': 'input'}
        if path == '/prompt':
            if owner.fail_prompt:
                return 400, {}, owner.fail_prompt
            owner.graphs.append(body['prompt'])
            return 200, {}, {'prompt_id': 'p1', 'number': 1}
        if path == '/queue':
            return 200, {}, {'queue_running': [[0, 'p1']], 'queue_pending': []}
        if path.startswith('/history/'):
            owner.polls += 1
            if owner.polls <= owner.history_after:
                return 200, {}, {}
            if owner.error_history:
                return 200, {}, {'p1': {'status': {'status_str': 'error', 'completed': False, 'messages': [
                    ['execution_error', {'exception_message': 'CUDA out of memory'}]]}, 'outputs': {}}}
            return 200, {}, {'p1': {'status': {'status_str': 'success', 'completed': True}, 'outputs': {
                '9': {'images': [{'filename': 'mg_00001_.png', 'subfolder': '', 'type': 'output'}]}}}}
        if path.startswith('/view'):
            return 200, {'Content-Type': 'image/png'}, b'PNGDATA'
        if path in ('/interrupt', '/free'):
            return 200, {}, {}
        return 404, {}, {'error': 'not found'}
