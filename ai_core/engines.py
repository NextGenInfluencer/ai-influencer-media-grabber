"""Background engines: Ollama, the built-in llama.cpp engine, and headless ComfyUI.

Engines are started hidden when needed and never installed implicitly: missing
engines raise ``ModelMissing`` with the catalog id that installs them.
"""
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import requests

from . import gpu, paths, settings
from .errors import AIUnavailable, ModelMissing

log = logging.getLogger(__name__)
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def _spawn(args, *, cwd=None, env=None):
    return subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)


def _terminate(process):
    if process is None or process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=_NO_WINDOW)
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def _wait_until(check, timeout, interval=0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(interval)
    return check()


class OllamaEngine:
    """Local Ollama server. Always 127.0.0.1 so lyrics cannot be routed elsewhere."""

    base_url = 'http://127.0.0.1:11434'

    def __init__(self):
        self._process = None
        self._lock = threading.Lock()

    def executable(self):
        candidates = [shutil.which('ollama')]
        local_app_data = os.environ.get('LOCALAPPDATA')
        if local_app_data:
            candidates.append(str(Path(local_app_data) / 'Programs' / 'Ollama' / 'ollama.exe'))
        candidates.append(str(paths.ENGINES_DIR / 'ollama' / ('ollama.exe' if os.name == 'nt' else 'ollama')))
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return Path(candidate)
        return None

    def version(self):
        try:
            response = requests.get(self.base_url + '/api/version', timeout=2, allow_redirects=False)
            if response.status_code == 200:
                return response.json().get('version') or 'unknown'
        except (requests.RequestException, ValueError, AttributeError):
            pass
        return None

    def running(self):
        return self.version() is not None

    def status(self):
        executable = self.executable()
        version = self.version()
        return {'name': 'ollama', 'installed': bool(executable) or version is not None, 'running': version is not None,
                'version': version, 'executable': str(executable) if executable else None,
                'managed': self._process is not None and self._process.poll() is None,
                'base_url': self.base_url, 'setup_hint': None if executable or version else 'engine-ollama'}

    def ensure_running(self, timeout=30):
        if self.running():
            return True
        with self._lock:
            if self.running():
                return True
            executable = self.executable()
            if not executable:
                raise ModelMissing('Ollama is not installed on this PC. Install it from AI Setup to use GPU models.',
                                   setup_hint='engine-ollama')
            env = dict(os.environ, OLLAMA_HOST='127.0.0.1:11434')
            self._process = _spawn([str(executable), 'serve'], env=env)
        if not _wait_until(self.running, timeout):
            raise AIUnavailable('Ollama did not start. Open AI Engines to retry or restart the PC.', setup_hint='engines')
        return True

    def stop(self):
        """Stop only a server this app started; never an Ollama the user runs."""
        with self._lock:
            _terminate(self._process)
            self._process = None

    def tags(self):
        """Locally installed, non-remote model entries.

        Uses the running server; when it is stopped, reads the on-disk manifests so
        the app can still show what is installed without starting anything.
        """
        try:
            response = requests.get(self.base_url + '/api/tags', timeout=3, allow_redirects=False)
            response.raise_for_status()
            entries = response.json().get('models', [])
        except (requests.RequestException, ValueError, AttributeError):
            return self.disk_tags()
        if not isinstance(entries, list):
            return []
        return [entry for entry in entries if isinstance(entry, dict) and isinstance(entry.get('name'), str)
                and entry['name'] and not entry.get('remote_host') and not entry.get('remote_model')]

    def models_dir(self):
        configured = os.environ.get('OLLAMA_MODELS')
        return Path(configured) if configured else paths.HOME_DIR / '.ollama' / 'models'

    def disk_tags(self):
        library = self.models_dir() / 'manifests' / 'registry.ollama.ai' / 'library'
        if not library.is_dir():
            return []
        entries = []
        for manifest in library.glob('*/*'):
            if not manifest.is_file():
                continue
            try:
                layers = json.loads(manifest.read_text(encoding='utf-8')).get('layers', [])
                size = sum(int(layer.get('size', 0)) for layer in layers if isinstance(layer, dict))
            except (OSError, ValueError, TypeError, AttributeError):
                continue
            entries.append({'name': f'{manifest.parent.name}:{manifest.name}', 'size': size, 'source': 'disk'})
        return entries

    def show(self, model):
        try:
            response = requests.post(self.base_url + '/api/show', json={'model': model}, timeout=(3, 10), allow_redirects=False)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def loaded_models(self):
        try:
            response = requests.get(self.base_url + '/api/ps', timeout=3, allow_redirects=False)
            response.raise_for_status()
            entries = response.json().get('models', [])
        except (requests.RequestException, ValueError, AttributeError):
            return []
        return [entry.get('name') or entry.get('model') for entry in entries if isinstance(entry, dict)
                and (entry.get('name') or entry.get('model'))]

    def unload(self, model):
        requests.post(self.base_url + '/api/generate', json={'model': model, 'keep_alive': 0},
                      timeout=(3, 30), allow_redirects=False)

    def unload_all(self):
        for model in self.loaded_models():
            try:
                self.unload(model)
            except requests.RequestException as exc:
                log.warning('Could not unload Ollama model %s: %s', model, exc)


class BuiltinEngine:
    """llama.cpp CPU wheel from the AI pack; models are GGUF files from the catalog."""

    def available(self):
        return importlib.util.find_spec('llama_cpp') is not None

    def status(self):
        available = self.available()
        return {'name': 'builtin', 'installed': available, 'running': available,
                'setup_hint': None if available else 'ai_pack'}


class ComfyEngine:
    """Headless ComfyUI with its own embedded Python, bound to 127.0.0.1."""

    port = 8188
    base_url = f'http://127.0.0.1:{port}'

    def __init__(self):
        self._process = None
        self._lock = threading.Lock()
        self._idle_timer = None

    def install_dir(self):
        return paths.ENGINES_DIR / 'comfyui'

    def root(self):
        for candidate in (self.install_dir() / 'ComfyUI_windows_portable' / 'ComfyUI', self.install_dir() / 'ComfyUI'):
            if (candidate / 'main.py').is_file():
                return candidate
        return None

    def python(self):
        for candidate in (self.install_dir() / 'ComfyUI_windows_portable' / 'python_embeded' / 'python.exe',
                          self.install_dir() / 'venv' / 'Scripts' / 'python.exe',
                          self.install_dir() / 'venv' / 'bin' / 'python'):
            if candidate.is_file():
                return candidate
        return None

    def home(self):
        """Isolated profile dir so custom nodes cannot drop caches into the user's home."""
        return self.install_dir() / 'home'

    def installed(self):
        return self.root() is not None and self.python() is not None

    def running(self):
        try:
            response = requests.get(self.base_url + '/system_stats', timeout=2, allow_redirects=False)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def custom_nodes(self):
        root = self.root()
        if not root or not (root / 'custom_nodes').is_dir():
            return []
        return sorted(p.name for p in (root / 'custom_nodes').iterdir() if p.is_dir() and not p.name.startswith('__'))

    def status(self):
        installed = self.installed()
        return {'name': 'comfy', 'installed': installed, 'running': self.running(),
                'managed': self._process is not None and self._process.poll() is None,
                'root': str(self.root()) if installed else None, 'custom_nodes': self.custom_nodes(),
                'base_url': self.base_url, 'setup_hint': None if installed else 'engine-comfyui'}

    def model_paths_file(self):
        return self.install_dir() / 'extra_model_paths.yaml'

    def write_model_paths(self):
        """Point ComfyUI at the shared models folder instead of duplicating files."""
        base = paths.MODELS_DIR.as_posix()
        text = (
            'media_grabber:\n'
            f'  base_path: "{base}"\n'
            '  diffusion_models: |\n    image\n    video\n'
            '  unet: |\n    image\n    video\n'
            '  text_encoders: text_encoders\n'
            '  clip: text_encoders\n'
            '  vae: vae\n'
            '  clip_vision: clip_vision\n'
        )
        target = self.model_paths_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        return target

    def link_destination(self, relative):
        if relative.startswith('@home/'):
            return self.home() / relative[len('@home/'):]
        root = self.root()
        if root is None:
            raise ModelMissing('Install the creative engine first.', setup_hint='engine-comfyui')
        target = (root / relative).resolve()
        if not paths.is_within(target, root):
            raise ValueError(f'Link escapes the engine folder: {relative}')
        return target

    def link_models(self, item):
        """Hard-link model files where custom nodes expect them (same volume, no copy)."""
        legacy_by_path = {entry['path']: entry.get('legacy') or [] for entry in item.get('files') or []}
        for link in item.get('comfy_links') or []:
            candidates = [link['from'], *legacy_by_path.get(link['from'], [])]
            source = next((p for c in candidates if (p := paths.resolve_item_path(c)).is_file()), None)
            if source is None:
                continue
            target = self.link_destination(link['to'])
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)

    _CORE_PACKAGES = {'numpy', 'torch', 'torchvision', 'torchaudio'}
    _EXTRA_NODE_PACKAGES = {
        'ComfyUI-LatentSyncWrapper': ['accelerate', 'pytorch-lightning', 'scikit-image'],
        'ComfyUI-LivePortraitKJ': ['onnxruntime-gpu'],
    }
    _NO_DEPS_NODE_PACKAGES = {
        'ComfyUI-LatentSyncWrapper': ['insightface==2.1'],
    }

    @classmethod
    def _filter_requirements(cls, text):
        import re
        specs = []
        for raw in (text or '').splitlines():
            line = raw.split('#', 1)[0].strip()
            if not line or line.startswith('-'):
                continue
            pkg = re.split(r'[<>=!~\[\s;]', line, maxsplit=1)[0].strip().lower().replace('_', '-')
            if pkg and pkg not in cls._CORE_PACKAGES:
                specs.append(line)
        return specs

    def _patch_custom_nodes(self):
        """Apply idempotent Python 3.13 / PyTorch 2.14 / MediaPipe compatibility patches to custom nodes."""
        root = self.root()
        if not root:
            return
        custom = root / 'custom_nodes'
        # 1. ComfyUI-LivePortraitKJ: MediaPipe >= 0.10.14 removed internal mediapipe.framework; use vision.FaceLandmarker
        mp_utils = custom / 'ComfyUI-LivePortraitKJ' / 'media_pipe' / 'mp_utils.py'
        if mp_utils.is_file():
            text = mp_utils.read_text(encoding='utf-8', errors='replace')
            updated = text.replace('from . import face_landmark', '# face_landmark unused on modern mediapipe')
            updated = updated.replace(
                'self.detector = face_landmark.FaceLandmarker.create_from_options(options)',
                'self.detector = vision.FaceLandmarker.create_from_options(options)',
            )
            updated = updated.replace(
                'detection_result, _ = self.detector.detect(image)',
                '_res = self.detector.detect(image); detection_result = _res[0] if isinstance(_res, tuple) else _res',
            )
            if updated != text:
                mp_utils.write_text(updated, encoding='utf-8')
        lmk_runner = custom / 'ComfyUI-LivePortraitKJ' / 'liveportrait' / 'utils' / 'landmark_runner.py'
        if lmk_runner.is_file():
            text = lmk_runner.read_text(encoding='utf-8', errors='replace')
            target_block = (
                "        if onnx_provider.lower() == 'cuda':\n"
                "            self.session = onnxruntime.InferenceSession(\n"
                "                ckpt_path, providers=[\n"
                "                    ('CUDAExecutionProvider', {'device_id': device_id})\n"
                "                ]\n"
                "            )"
            )
            replacement_block = (
                "        if onnx_provider.lower() == 'cuda':\n"
                "            getattr(onnxruntime, 'preload_dlls', lambda: None)()\n"
                "            self.session = onnxruntime.InferenceSession(\n"
                "                ckpt_path, providers=[\n"
                "                    ('CUDAExecutionProvider', {'device_id': device_id}),\n"
                "                    'CPUExecutionProvider',\n"
                "                ]\n"
                "            )"
            )
            updated = text.replace(target_block, replacement_block)
            if updated != text:
                lmk_runner.write_text(updated, encoding='utf-8')
        # 2. ComfyUI-LatentSyncWrapper: TorchAudio 2.11+ / TorchVision 0.29+ / offline Whisper & InsightFace
        ls_dir = custom / 'ComfyUI-LatentSyncWrapper'
        ls_nodes = ls_dir / 'nodes.py'
        if ls_nodes.is_file():
            text = ls_nodes.read_text(encoding='utf-8', errors='replace')
            updated = text.replace(
                'torchaudio.save(audio_path, waveform_cpu, sample_rate)',
                'import soundfile as _sf; _sf.write(audio_path, waveform_cpu.t().cpu().numpy(), sample_rate)',
            )
            updated = updated.replace('except TypeError as e:', 'except (TypeError, AttributeError) as e:')
            updated = updated.replace(
                "processed_frames = io.read_video(output_video_path, pts_unit='sec')[0]",
                'from decord import VideoReader as _VR; _vr = _VR(output_video_path); '
                'processed_frames = torch.from_numpy(_vr[:].asnumpy()); del _vr',
            )
            updated = updated.replace(
                'torch.cuda.set_per_process_memory_fraction(0.8)',
                '# memory fraction cap removed to avoid throttling shared ComfyUI process',
            )
            if updated != text:
                ls_nodes.write_text(updated, encoding='utf-8')
        ls_inf = ls_dir / 'scripts' / 'inference.py'
        if ls_inf.is_file():
            text = ls_inf.read_text(encoding='utf-8', errors='replace')
            updated = text.replace(
                '        model_path=whisper_model_name,',
                '        model_path=args.whisper_ckpt_path if getattr(args, "whisper_ckpt_path", None) '
                'and os.path.isfile(args.whisper_ckpt_path) else whisper_model_name,',
            )
            if updated != text:
                ls_inf.write_text(updated, encoding='utf-8')
        ls_fd = ls_dir / 'latentsync' / 'utils' / 'face_detector.py'
        if ls_fd.is_file():
            text = ls_fd.read_text(encoding='utf-8', errors='replace')
            target_fd = (
                '        self.app = FaceAnalysis(\n'
                '            allowed_modules=["detection", "landmark_2d_106"],\n'
                '            root="checkpoints/auxiliary",\n'
                '            providers=["CUDAExecutionProvider"],\n'
                '        )'
            )
            replacement_fd = (
                '        import os as _os, onnxruntime as _ort\n'
                '        getattr(_ort, "preload_dlls", lambda: None)()\n'
                '        _aux_root = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname('
                '_os.path.abspath(__file__)))), "checkpoints", "auxiliary")\n'
                '        self.app = FaceAnalysis(\n'
                '            allowed_modules=["detection", "landmark_2d_106"],\n'
                '            root=_aux_root,\n'
                '            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],\n'
                '        )'
            )
            updated = text.replace(target_fd, replacement_fd)
            if updated != text:
                ls_fd.write_text(updated, encoding='utf-8')
        ls_pipe = ls_dir / 'latentsync' / 'pipelines' / 'lipsync_pipeline.py'
        if ls_pipe.is_file():
            text = ls_pipe.read_text(encoding='utf-8', errors='replace')
            updated = text.replace(
                '-q:v 0 -q:a 0 {video_out_path}"',
                '-q:v 0 -q:a 0 \\"{video_out_path}\\""',
            )
            if updated != text:
                ls_pipe.write_text(updated, encoding='utf-8')
        ls_util = ls_dir / 'latentsync' / 'utils' / 'util.py'
        if ls_util.is_file():
            text = ls_util.read_text(encoding='utf-8', errors='replace')
            updated = text.replace(
                '-nostdin -i {video_path} -r 25',
                '-nostdin -i \\"{video_path}\\" -r 25',
            )
            updated = updated.replace(
                'def write_video(video_output_path: str, video_frames: np.ndarray, fps: int):\n'
                '    with imageio.get_writer(',
                'def write_video(video_output_path: str, video_frames: np.ndarray, fps: int):\n'
                '    return write_video_cv2(video_output_path, video_frames, fps)\n'
                '    with imageio.get_writer(',
            )
            if updated != text:
                ls_util.write_text(updated, encoding='utf-8')

    def install_requirements(self, folder):
        """Install a custom node's pinned requirements into the engine's own Python."""
        import job_process
        root, python = self.root(), self.python()
        if not root or not python:
            raise ModelMissing('Install the creative engine first.', setup_hint='engine-comfyui')
        requirements = root / 'custom_nodes' / folder / 'requirements.txt'
        if not requirements.is_file():
            return
        specs = self._filter_requirements(requirements.read_text(encoding='utf-8', errors='replace'))
        for extra in self._EXTRA_NODE_PACKAGES.get(folder, ()):
            if extra not in specs:
                specs.append(extra)
        if not specs:
            return
        result = job_process.run([str(python), '-s', '-m', 'pip', 'install', '--disable-pip-version-check',
                                  *specs], capture_output=True, timeout=3600)
        if result.returncode:
            tail = (result.stderr or b'')[-400:].decode('utf-8', 'replace') if isinstance(result.stderr, bytes) else str(result.stderr)[-400:]
            raise AIUnavailable(f'Installing requirements for {folder} failed: {tail.strip()}', setup_hint='engines')
        for no_deps_pkg in self._NO_DEPS_NODE_PACKAGES.get(folder, ()):
            res2 = job_process.run([str(python), '-s', '-m', 'pip', 'install', '--disable-pip-version-check',
                                    '--no-deps', no_deps_pkg], capture_output=True, timeout=1800)
            if res2.returncode:
                tail = (res2.stderr or b'')[-400:].decode('utf-8', 'replace') if isinstance(res2.stderr, bytes) else str(res2.stderr)[-400:]
                raise AIUnavailable(f'Installing {no_deps_pkg} for {folder} failed: {tail.strip()}', setup_hint='engines')
        self._patch_custom_nodes()

    def _prepare_home_env(self):
        home = self.home()
        home.mkdir(parents=True, exist_ok=True)
        (home / '.latentsync16_dependencies_installed').write_text('ok\n', encoding='utf-8')
        env = dict(
            os.environ,
            USERPROFILE=str(home),
            HOME=str(home),
            PYTHONNOUSERSITE='1',
            PYTHONIOENCODING='utf-8',
            PYTHONUTF8='1',
        )
        try:
            import imageio_ffmpeg
            ffmpeg_src = Path(imageio_ffmpeg.get_ffmpeg_exe())
            if ffmpeg_src.is_file():
                bin_dir = home / 'bin'
                bin_dir.mkdir(parents=True, exist_ok=True)
                ffmpeg_dst = bin_dir / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
                if not ffmpeg_dst.is_file():
                    try:
                        os.link(ffmpeg_src, ffmpeg_dst)
                    except OSError:
                        shutil.copy2(ffmpeg_src, ffmpeg_dst)
                env['PATH'] = str(bin_dir) + os.pathsep + env.get('PATH', '')
        except Exception as exc:
            log.debug('Could not link imageio_ffmpeg into ComfyUI home: %s', exc)
        return env

    def ensure_running(self, timeout=180):
        if self.running():
            self.touch()
            return True
        with self._lock:
            if self.running():
                return True
            if not self.installed():
                raise ModelMissing('The creative engine (ComfyUI) is not installed. Install it from AI Setup.',
                                   setup_hint='engine-comfyui')
            from . import catalog
            for item in catalog.items():
                if item.get('comfy_links'):
                    self.link_models(item)
            self._patch_custom_nodes()
            config = self.write_model_paths()
            env = self._prepare_home_env()
            self._process = _spawn([str(self.python()), '-s', str(self.root() / 'main.py'),
                                    '--listen', '127.0.0.1', '--port', str(self.port), '--disable-auto-launch',
                                    '--extra-model-paths-config', str(config)], cwd=str(self.root()), env=env)
        if not _wait_until(self.running, timeout, interval=1.0):
            self.stop()
            raise AIUnavailable('The creative engine did not start. Open AI Engines for details.', setup_hint='engines')
        self.touch()
        return True

    def free(self):
        try:
            requests.post(self.base_url + '/free', json={'unload_models': True, 'free_memory': True},
                          timeout=(3, 30), allow_redirects=False)
        except requests.RequestException as exc:
            log.warning('ComfyUI /free failed: %s', exc)

    def _idle_stop(self):
        if gpu.status().get('comfy', {}).get('active'):
            self.touch()
            return
        self.stop()

    def touch(self):
        """Restart the idle-stop timer after the last use."""
        if self._idle_timer:
            self._idle_timer.cancel()
        self._idle_timer = threading.Timer(settings.idle_release_seconds() * 3, self._idle_stop)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def stop(self):
        with self._lock:
            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
            _terminate(self._process)
            self._process = None


ollama = OllamaEngine()
builtin = BuiltinEngine()
comfy = ComfyEngine()
ENGINES = {'ollama': ollama, 'builtin': builtin, 'comfy': comfy}


def _evict_ollama():
    if ollama.running():
        ollama.unload_all()


def _evict_comfy():
    if comfy.running():
        comfy.free()


gpu.register_evictor('ollama', _evict_ollama)
gpu.register_evictor('comfy', _evict_comfy)


def status():
    return {name: engine.status() for name, engine in ENGINES.items()}
