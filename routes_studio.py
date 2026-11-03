"""AI Studio blueprint: /video-studio page, /api/video-studio/*, /api/motion/*, /api/jobs/*, characters.

Every generative action runs as a background job with progress and cancel. Jobs
call ``ai_core`` through ``assets.ai_video_engine`` / ``assets.motion_studio`` and
either produce real model output or end with the honest ``AIUnavailable`` message
and ``setup_hint``. Paid cloud actions run only when the request explicitly
confirms the cost (``confirm_cost: true``); there is never an implicit fallback.
Every client-supplied path is resolved to a file inside the user's library.
"""
import json
import threading
import time
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, session
from werkzeug.utils import secure_filename

import characters
import job_process
from ai_core import catalog, cloud, hardware, llm, models
from ai_core.errors import AIUnavailable, ConsentRequired
from assets import ai_video_engine as video_engine
from assets import motion_studio as motion

JOB_LIMIT = 200
CANCELLED = 'Cancelled by user'

# Local features and what they need. ``cloud`` names the opt-in alternative.
FEATURES = {
    'director': {'label': 'AI Director', 'role': 'helper'},
    'keyframe': {'label': 'Keyframe · FLUX.1 schnell', 'workflow': 'flux_schnell_t2i', 'cloud': 'gemini'},
    'identity_keyframe': {'label': 'Persona keyframe · FLUX.1 Kontext', 'workflow': 'flux_kontext_edit', 'cloud': 'gemini'},
    'animate_fast': {'label': 'Animate · Wan 2.2 5B (fast)', 'workflow': 'wan22_ti2v_5b'},
    'animate_quality': {'label': 'Animate · Wan 2.1 14B (quality, slow)', 'workflow': 'wan21_i2v_14b_gguf'},
    'lip_sync': {'label': 'Lip-sync · LatentSync', 'workflow': 'latentsync'},
    'live_portrait': {'label': 'Portrait animation · LivePortrait', 'workflow': 'liveportrait', 'cloud': 'fal'},
    'face_swap': {'label': 'Face Swap · InSwapper', 'items': ['inswapper-128', 'insightface-buffalo-l']},
    'motion_transfer': {'label': 'Motion transfer · Kling (cloud only)', 'items': [], 'cloud': 'fal', 'cloud_only': True},
}
CLOUD_SERVICES = {
    'kling': {'provider': 'fal', 'endpoint': 'kling_motion_control', 'label': 'Kling motion control (fal.ai)'},
    'live_portrait': {'provider': 'fal', 'endpoint': 'live_portrait', 'label': 'LivePortrait (fal.ai)'},
    'nano_banana': {'provider': 'gemini', 'endpoint': 'nano_banana', 'label': 'Nano Banana image edit (Google Gemini)'},
}


class CostConfirmationRequired(Exception):
    def __init__(self, service):
        super().__init__(service)
        self.service = service


# ---------------------------------------------------------------- jobs

class JobRegistry:
    """In-memory background jobs with progress, ETA and cooperative cancel."""

    def __init__(self, limit=JOB_LIMIT):
        self._jobs = {}
        self._lock = threading.Lock()
        self._limit = limit
        self.on_start = None
        self.on_finish = None

    def _public(self, job):
        return {k: v for k, v in job.items() if not k.startswith('_')}

    def start(self, kind, work, *, label='', eta_seconds=None, local=True):
        job_id = uuid.uuid4().hex
        job = {'id': job_id, 'kind': kind, 'label': label, 'status': 'running', 'progress': 0.0, 'message': 'Starting…',
               'eta_seconds': eta_seconds, 'local': local, 'created': time.time(), 'result': None, 'error': None,
               'setup_hint': None, '_cancel': threading.Event()}
        with self._lock:
            self._jobs[job_id] = job
            finished = [j for j in self._jobs.values() if j['status'] != 'running']
            for old in sorted(finished, key=lambda j: j['created'])[:max(0, len(self._jobs) - self._limit)]:
                self._jobs.pop(old['id'], None)
        threading.Thread(target=self._run, args=(job, work), daemon=True, name=f'studio-{kind}').start()
        return self._public(job)

    def _report(self, job, progress=None, message=None):
        with self._lock:
            if progress is not None:
                job['progress'] = round(max(0.0, min(1.0, float(progress))), 3)
            if message:
                job['message'] = str(message)[:300]

    def _finish(self, job, **fields):
        with self._lock:
            job.update(fields, finished=time.time())

    def _run(self, job, work):
        if self.on_start:
            self.on_start()
        job_process.begin_job()
        try:
            with job_process.cancellation_scope(job['_cancel'].is_set):
                result = work(lambda progress=None, message=None: self._report(job, progress, message))
            warning = result.get('warning') if isinstance(result, dict) else None
            done_msg = f'Done ({warning})' if warning else 'Done'
            self._finish(job, status='completed', progress=1.0, message=done_msg, result=result,
                         **({'warning': warning} if warning else {}))
        except AIUnavailable as exc:
            cancelled = job['_cancel'].is_set()
            self._finish(job, status='cancelled' if cancelled else 'failed', error=exc.message,
                         setup_hint=None if cancelled else exc.setup_hint, message='Cancelled' if cancelled else exc.message)
        except Exception as exc:  # surfaced verbatim to the UI; nothing is reported as success
            if job['_cancel'].is_set() or str(exc) == CANCELLED:
                self._finish(job, status='cancelled', message='Cancelled', error=None)
            else:
                self._finish(job, status='failed', error=str(exc) or exc.__class__.__name__, message='Failed')
        finally:
            job_process.end_job()
            if self.on_finish:
                self.on_finish()

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return self._public(job) if job else None

    def cancel(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if job['status'] != 'running':
                return False
            job['_cancel'].set()
            job['message'] = 'Cancelling…'
            return True


jobs = JobRegistry()


def comfy_progress(report, eta_seconds):
    """Map ComfyUI queue/elapsed updates to a progress fraction based on the catalog ETA."""
    def update(info):
        if info.get('state') == 'queued':
            report(0.02, f'Queued in the creative engine (position {info.get("position")})')
            return
        elapsed = float(info.get('elapsed') or 0)
        fraction = min(0.95, elapsed / eta_seconds) if eta_seconds else 0.5
        report(fraction, f'Generating locally… {int(elapsed)} s')
    return update


def frame_progress(report):
    def update(done, total):
        suffix = ' (running on CPU – slower)' if motion.face.active_warning() else ''
        report(done / total if total else None, f'Swapping faces{suffix}… frame {done} of {total}')
    return update


# ---------------------------------------------------------------- capabilities

def _requirements(feature):
    spec = FEATURES[feature]
    if 'role' in spec:
        cost = llm.cost(spec['role'])
        return {'available': cost['available'], 'missing': [] if cost['available'] else [cost.get('setup_hint')],
                'cost': cost, 'setup_hint': cost.get('setup_hint')}
    if 'workflow' in spec:
        meta = catalog.workflow(spec['workflow'])
        # Primary model first: its install notice brings the engine and companions along.
        items = [*meta.get('requires', []), *meta.get('custom_nodes', []), 'engine-comfyui']
        cost = video_engine.workflow_cost(spec['workflow'])
    else:
        items = list(spec['items'])
        primary = [catalog.get(i) for i in items]
        cost = {'local': True, 'vram_gb': max([i.get('vram_gb') or 0 for i in primary] or [0]),
                'ram_gb': max([i.get('ram_gb') or 0 for i in primary] or [0]), 'eta_seconds': None,
                'models': [i['name'] for i in primary]}
    missing = [i for i in items if not models.installed(i)]
    return {'available': bool(items) and not missing, 'missing': missing, 'cost': cost,
            'setup_hint': missing[0] if missing else None}


def capabilities():
    profile = hardware.current_profile()
    cloud_state = cloud.status()
    features = {}
    for feature, spec in FEATURES.items():
        state = _requirements(feature)
        recommended = True
        first = (catalog.workflow(spec['workflow']).get('requires') or [None])[0] if 'workflow' in spec else (
            spec.get('items') or [None])[0]
        if first:
            recommended = profile in catalog.get(first).get('profiles', [])
        provider = spec.get('cloud')
        features[feature] = {
            'label': spec['label'], **state, 'recommended_for_profile': recommended,
            'missing_names': [catalog.get(i)['name'] if catalog.exists(i) else i for i in state['missing'] if i],
            'cloud': {'provider': provider, **cloud_state[provider]} if provider else None,
            'cloud_only': bool(spec.get('cloud_only')),
        }
    return {'profile': profile, 'features': features}


def _cloud_guard(service, body):
    """Cloud runs need explicit opt-in per request; raises CostConfirmationRequired otherwise."""
    if body.get('confirm_cost') is not True:
        raise CostConfirmationRequired(service)
    return CLOUD_SERVICES[service]


# ---------------------------------------------------------------- registration

def register_studio_routes(app, *, save_dir, allowed_path, app_version, job_started=None, job_finished=None):
    """Register the studio blueprint. ``allowed_path`` is the app's library allow-list check."""
    bp = Blueprint('studio', __name__)
    jobs.on_start, jobs.on_finish = job_started, job_finished
    projects_root = Path(save_dir) / 'Caption Projects'

    def body():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def media(value, kinds, label):
        """Resolve a client path/URL to a library file of the expected type, or raise ValueError."""
        if not value or not isinstance(value, str):
            raise ValueError(f'Choose {label}.')
        path = motion.resolve_media_source(value)
        if path is None:
            candidate = Path(value)
            if candidate.is_absolute() and allowed_path(str(candidate)) and candidate.is_file():
                path = candidate.resolve()
        if path is None or not allowed_path(str(path)):
            raise ValueError(f'The {label} must be a file in your Media Grabber library.')
        if path.suffix.lower() not in kinds:
            raise ValueError(f'The {label} is not a supported file type.')
        return path

    def portrait(data):
        if data.get('custom_portrait_path'):
            return media(data['custom_portrait_path'], motion.IMAGE_EXTENSIONS, 'portrait image')
        char = video_engine.persona(data.get('character_id'))
        found = characters.portrait_path(char)
        if found is None:
            name = (char or {}).get('name') or 'the active persona'
            raise ValueError(f'Upload a portrait for {name} in the Persona editor first.')
        return found

    def audio_options(data):
        mode = data.get('audio_mode') or ('mute' if data.get('mute') is True else 'original')
        if mode not in motion.AUDIO_MODES:
            raise ValueError('Choose original, mute or project audio.')
        audio = media(data.get('audio_path'), motion.AUDIO_EXTENSIONS | motion.VIDEO_EXTENSIONS, 'project audio') \
            if mode == 'project' else None
        return mode, audio

    def read_project(pid):
        if not isinstance(pid, str) or len(pid) != 32 or not all(c in '0123456789abcdef' for c in pid):
            raise ValueError('Choose a captions project.')
        path = projects_root / pid / 'project.json'
        if not path.is_file():
            raise FileNotFoundError('Captions project not found.')
        return json.loads(path.read_text(encoding='utf-8'))

    def accepted(job):
        return jsonify(job_id=job['id'], job=job, poll_url=f'/api/jobs/{job["id"]}'), 202

    def serve_from(folder, filename, label):
        target = (Path(folder) / Path(filename).name).resolve()
        if Path(folder).resolve() not in target.parents or not target.is_file():
            target = (Path(folder) / secure_filename(filename)).resolve()
            if Path(folder).resolve() not in target.parents or not target.is_file():
                return jsonify(error=f'{label} not found'), 404
        return send_file(str(target))

    # ------------------------------------------------------------ errors

    @bp.errorhandler(ConsentRequired)
    def consent_required(exc):
        return jsonify(exc.to_dict()), 409

    @bp.errorhandler(AIUnavailable)
    def unavailable(exc):
        return jsonify(exc.to_dict()), 424

    @bp.errorhandler(CostConfirmationRequired)
    def needs_confirmation(exc):
        service = CLOUD_SERVICES[exc.service]
        endpoint = catalog.cloud_endpoint(service['provider'], service['endpoint']) or {}
        return jsonify(error=f'{service["label"]} is a paid cloud service billed to your own account. Confirm to continue.',
                       needs_confirmation=True, cost={'service': exc.service, 'label': service['label'], 'local': False,
                                                      'provider': service['provider'], 'docs': endpoint.get('docs')}), 409

    @bp.errorhandler(ValueError)
    @bp.errorhandler(TypeError)
    def bad_request(exc):
        return jsonify(error=str(exc)), 400

    @bp.errorhandler(FileNotFoundError)
    def not_found(exc):
        return jsonify(error=str(exc) or 'File not found.'), 404

    # ------------------------------------------------------------ page and capabilities

    @bp.get('/video-studio')
    def video_studio_page():
        session['authorized'] = True
        if not session.get('api_token'):
            session['api_token'] = uuid.uuid4().hex
        return render_template('video_studio.html', api_token=session['api_token'], version=app_version)

    @bp.get('/api/video-studio/capabilities')
    def get_capabilities():
        return jsonify(capabilities())

    @bp.get('/api/video-studio/projects')
    def list_projects():
        """Captions projects the Director can use (real cue timings and audio)."""
        result = []
        for path in sorted(projects_root.glob('*/project.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                result.append({'id': data['id'], 'name': data.get('name', ''), 'duration': data.get('duration', 0),
                               'cues': len(data.get('cues') or []), 'revision': data.get('revision'),
                               'audio_url': f'/api/captions/{data["id"]}/media/{data.get("source", "")}'})
            except (OSError, ValueError, KeyError):
                continue
        return jsonify(projects=result)

    # ------------------------------------------------------------ jobs

    @bp.get('/api/jobs/<job_id>')
    @bp.get('/api/motion/jobs/<job_id>')
    def get_job(job_id):
        job = jobs.get(job_id)
        return jsonify(job) if job else (jsonify(error='Job not found'), 404)

    @bp.post('/api/jobs/<job_id>/cancel')
    @bp.post('/api/motion/jobs/<job_id>/cancel')
    def cancel_job(job_id):
        result = jobs.cancel(job_id)
        if result is None:
            return jsonify(error='Job not found'), 404
        return jsonify(success=result, cancelled=result)

    # ------------------------------------------------------------ Director

    @bp.post('/api/video-studio/storyboard/generate')
    def generate_storyboard():
        data = body()
        cues, duration, peaks = data.get('cues'), data.get('duration'), None
        if data.get('project_id'):
            project = read_project(data['project_id'])
            cues, duration, peaks = project.get('cues') or [], project.get('duration'), project.get('peaks')
        if cues is not None and not isinstance(cues, list):
            raise ValueError('Invalid caption lines.')
        options = {'cues': cues or [], 'duration': float(duration or 0), 'peaks': peaks,
                   'concept': str(data.get('concept') or ''), 'mood': str(data.get('mood') or ''),
                   'character_id': data.get('character_id'), 'num_scenes': data.get('num_scenes')}
        if options['duration'] <= 0:
            raise ValueError('Choose a song project or set a duration for the storyboard.')
        if not options['cues'] and not options['concept'].strip():
            raise ValueError('Describe the video concept, or pick a captions project with lyrics.')
        cost = llm.cost('helper')
        if not cost['available']:
            raise AIUnavailable(cost['error'], setup_hint=cost['setup_hint'])

        def work(report):
            report(0.1, f'Planning scenes with {cost["model"]}…')
            return video_engine.direct_storyboard(**options)
        return accepted(jobs.start('storyboard', work, label='AI Director storyboard', eta_seconds=cost['eta_seconds']))

    @bp.post('/api/video-studio/director/analyze')
    def director_analyze():
        data = body()
        return jsonify(video_engine.suggest_concepts(lyrics=str(data.get('lyrics') or ''),
                                                     song_title=str(data.get('song_title') or ''),
                                                     concept=str(data.get('concept') or ''),
                                                     character_id=data.get('character_id')))

    @bp.post('/api/video-studio/director/chat')
    def director_chat():
        data = body()
        if not str(data.get('message') or '').strip():
            raise ValueError('message required')
        return jsonify(video_engine.director_chat(data['message'], lyrics=str(data.get('lyrics') or ''),
                                                  character_id=data.get('character_id')))

    # ------------------------------------------------------------ keyframes and animation

    @bp.post('/api/video-studio/render-image')
    def render_image():
        data = body()
        prompt = str(data.get('prompt') or '').strip()
        if not prompt:
            raise ValueError('Write a prompt for the keyframe.')
        scene = int(data.get('scene_number') or 1)
        use_character = data.get('use_character') is True
        reference = media(data['custom_reference'], motion.IMAGE_EXTENSIONS, 'reference image') \
            if data.get('custom_reference') else None
        if data.get('cloud') == 'nano_banana':
            _cloud_guard('nano_banana', data)
            source = reference or portrait(data)

            def cloud_work(report):
                report(0.1, 'Sending to Google Gemini (your key)…')
                outputs = cloud.nano_banana_edit([str(source)], prompt)
                image = video_engine._move_output(outputs[0], video_engine.STORYBOARD_IMG_DIR, f'keyframe_scene_{scene}')
                return {'path': str(image), 'filename': image.name, 'url': f'/api/video-studio/images/file/{image.name}',
                        'provider': 'gemini', 'ai': True, 'local': False}
            return accepted(jobs.start('keyframe', cloud_work, label='Keyframe (Nano Banana, cloud)', local=False))
        feature = 'identity_keyframe' if (reference or (use_character and characters.portrait_path(
            video_engine.persona(data.get('character_id'))))) else 'keyframe'
        state = _requirements(feature)
        if not state['available']:
            raise AIUnavailable(f'{FEATURES[feature]["label"]} is not installed on this PC.', setup_hint=state['setup_hint'])
        eta = state['cost'].get('eta_seconds') or 60

        def work(report):
            return video_engine.render_keyframe(prompt, character_id=data.get('character_id'), use_character=use_character,
                                                reference=reference, scene_number=scene, seed=int(data.get('seed') or 0),
                                                progress=comfy_progress(report, eta))
        return accepted(jobs.start('keyframe', work, label=FEATURES[feature]['label'], eta_seconds=eta))

    @bp.post('/api/video-studio/render-video')
    def render_video():
        data = body()
        image = media(data.get('image_path'), motion.IMAGE_EXTENSIONS, 'keyframe image')
        scene = int(data.get('scene_number') or 1)
        duration = max(1.0, min(15.0, float(data.get('duration') or 5.0)))
        if data.get('preview') is True:
            def preview(report):
                report(0.2, 'Rendering camera preview (no AI)…')
                return video_engine.camera_preview(image, motion=data.get('camera_motion') or 'push_in',
                                                   duration=duration, scene_number=scene)
            return accepted(jobs.start('preview', preview, label=video_engine.PREVIEW_LABEL, eta_seconds=10))
        quality = data.get('quality') or 'fast'
        if quality not in video_engine.ANIMATE_WORKFLOWS:
            raise ValueError('Choose fast or quality animation.')
        feature = 'animate_fast' if quality == 'fast' else 'animate_quality'
        state = _requirements(feature)
        if not state['available']:
            raise AIUnavailable(f'{FEATURES[feature]["label"]} is not installed on this PC.', setup_hint=state['setup_hint'])
        eta = state['cost'].get('eta_seconds') or 600

        def work(report):
            return video_engine.animate_keyframe(image, data.get('motion_prompt') or '', quality=quality, duration=duration,
                                                 scene_number=scene, seed=int(data.get('seed') or 0),
                                                 progress=comfy_progress(report, eta))
        return accepted(jobs.start('animate', work, label=FEATURES[feature]['label'], eta_seconds=eta))

    @bp.get('/api/video-studio/images/file/<path:filename>')
    def storyboard_image(filename):
        return serve_from(video_engine.STORYBOARD_IMG_DIR, filename, 'Image')

    @bp.get('/api/video-studio/videos/file/<path:filename>')
    def storyboard_video(filename):
        return serve_from(video_engine.STORYBOARD_VID_DIR, filename, 'Video')

    # ------------------------------------------------------------ performance and face tools

    @bp.post('/api/video-studio/performance/lip-sync')
    def lip_sync():
        data = body()
        video = media(data.get('video_path'), motion.VIDEO_EXTENSIONS, 'face video')
        audio = media(data.get('audio_path'), motion.AUDIO_EXTENSIONS | motion.VIDEO_EXTENSIONS, 'song audio')
        state = _requirements('lip_sync')
        if not state['available']:
            raise AIUnavailable('LatentSync lip-sync is not installed on this PC.', setup_hint=state['setup_hint'])
        eta = state['cost'].get('eta_seconds') or 600
        return accepted(jobs.start('lip_sync', lambda report: motion.lip_sync(video, audio, progress=comfy_progress(report, eta)),
                                   label=FEATURES['lip_sync']['label'], eta_seconds=eta))

    @bp.post('/api/motion/render')
    def render_motion():
        """Async motion job: engine face_swap (local), live_portrait (local or cloud) or kling (cloud)."""
        data = body()
        engine_name = data.get('engine') or 'face_swap'
        video = media(data.get('driving_video') or data.get('video_path'), motion.VIDEO_EXTENSIONS, 'driving video')
        source = media(data['source_image'], motion.IMAGE_EXTENSIONS, 'source image') if data.get('source_image') \
            else portrait(data)
        mode, audio = audio_options(data)
        if engine_name == 'kling' or (engine_name == 'live_portrait' and data.get('cloud') is True):
            service = 'kling' if engine_name == 'kling' else 'live_portrait'
            _cloud_guard(service, data)

            def cloud_work(report):
                report(0.1, f'Uploading to {CLOUD_SERVICES[service]["label"]} (your key)…')
                if service == 'kling':
                    result = motion.cloud_motion(source, video, prompt=str(data.get('prompt') or ''),
                                                 keep_sound=mode == 'original', pro=data.get('pro') is True)
                else:
                    result = motion.cloud_live_portrait(source, video)
                if mode != 'original':
                    final = motion.apply_audio(result['path'], mode=mode, audio=audio)
                    result = motion._result(final, **{k: v for k, v in result.items() if k not in ('path', 'filename', 'url')})
                return result
            return accepted(jobs.start(engine_name, cloud_work, label=CLOUD_SERVICES[service]['label'], local=False))
        if engine_name == 'live_portrait':
            state = _requirements('live_portrait')
            if not state['available']:
                raise AIUnavailable('LivePortrait is not installed on this PC.', setup_hint=state['setup_hint'])
            eta = state['cost'].get('eta_seconds') or 120
            return accepted(jobs.start('live_portrait', lambda report: motion.live_portrait(
                source, video, audio_mode=mode, audio=audio, progress=comfy_progress(report, eta)),
                label=FEATURES['live_portrait']['label'], eta_seconds=eta))
        if engine_name != 'face_swap':
            raise ValueError('Choose Face Swap Video, LivePortrait or Kling.')
        state = _requirements('face_swap')
        if not state['available']:
            raise AIUnavailable('Face swap models are not installed on this PC.', setup_hint=state['setup_hint'])
        restore = data.get('restore') is not False
        return accepted(jobs.start('face_swap_video', lambda report: motion.face_swap_video(
            video, source, restore=restore, audio_mode=mode, audio=audio, progress=frame_progress(report)),
            label='Face Swap Video'))

    @bp.post('/api/motion/swap-identity')
    def swap_identity():
        """Swap the persona into a still frame (local InSwapper, or opt-in Nano Banana)."""
        data = body()
        if data.get('target_frame_path'):
            target = media(data['target_frame_path'], motion.IMAGE_EXTENSIONS, 'target frame')
        elif data.get('driving_video_path'):
            video = media(data['driving_video_path'], motion.VIDEO_EXTENSIONS, 'driving video')
            target = Path(motion.extract_reference_frame(str(video), float(data.get('timestamp') or 0))['path'])
        else:
            raise ValueError('target_frame_path or driving_video_path required')
        source = portrait(data)
        frame = {'extracted_frame': target.name, 'extracted_frame_url': f'/api/motion/references/file/{target.name}'}
        if data.get('engine') == 'nano_banana':
            _cloud_guard('nano_banana', data)
            return accepted(jobs.start('identity_edit', lambda report: {**motion.cloud_identity_edit(
                target, source, character_id=data.get('character_id')), **frame}, label='Identity edit (Nano Banana, cloud)',
                local=False))
        state = _requirements('face_swap')
        if not state['available']:
            raise AIUnavailable('Face swap models are not installed on this PC.', setup_hint=state['setup_hint'])
        restore = data.get('restore') is not False
        return accepted(jobs.start('face_swap_image', lambda report: {
            **motion.face_swap_image(target, source, restore=restore), **frame}, label='Face Swap (image)', eta_seconds=20))

    @bp.post('/api/motion/extract-frame')
    def extract_frame():
        data = body()
        video = media(data.get('video_path'), motion.VIDEO_EXTENSIONS, 'video')
        return jsonify(motion.extract_reference_frame(str(video), float(data.get('timestamp') or 0)))

    @bp.post('/api/motion/upload-swapped-frame')
    def upload_swapped_frame():
        upload = request.files.get('image')
        if not upload or not upload.filename:
            return jsonify(error='No image file uploaded'), 400
        return jsonify(motion.save_uploaded_swapped_frame(upload)), 201

    @bp.get('/api/motion/references')
    def list_references():
        return jsonify(references=motion.list_references())

    @bp.get('/api/motion/references/file/<path:filename>')
    def reference_file(filename):
        return serve_from(motion.REFERENCES_DIR, filename, 'Reference file')

    @bp.get('/api/motion/driving-videos')
    def driving_videos():
        return jsonify(videos=motion.list_driving_videos())

    @bp.post('/api/motion/upload-driving-video')
    def upload_driving_video():
        upload = request.files.get('video')
        if not upload or not upload.filename:
            return jsonify(error='No video file uploaded'), 400
        return jsonify(motion.save_uploaded_driving_video(upload)), 201

    @bp.get('/api/motion/outputs/file/<path:filename>')
    def motion_output(filename):
        return serve_from(motion.MOTION_OUTPUT_DIR, filename, 'Motion output file')

    # ------------------------------------------------------------ characters (personas)

    @bp.get('/api/characters')
    def list_characters():
        return jsonify(characters=characters.list_characters())

    @bp.get('/api/characters/active')
    def get_active_character():
        return jsonify(active=characters.get_active_character())

    @bp.post('/api/characters/active')
    def set_active_character():
        data = body()
        cid = data.get('id') or data.get('character_id')
        if not cid:
            return jsonify(error='id required'), 400
        if not characters.get_character(cid):
            return jsonify(error=f"Character '{cid}' not found"), 404
        characters.set_active_character_id(cid)
        return jsonify(active=characters.get_active_character())

    @bp.get('/api/characters/<cid>')
    def get_character(cid):
        char = characters.get_character(cid)
        return jsonify(char) if char else (jsonify(error='Character not found'), 404)

    @bp.post('/api/characters')
    @bp.post('/api/characters/<cid>')
    def save_character(cid=None):
        data = body()
        if cid and not data.get('id'):
            data['id'] = cid
        char = characters.save_character(data)
        return jsonify({**char, 'character': char})

    @bp.delete('/api/characters/<cid>')
    def delete_character(cid):
        return jsonify(success=characters.delete_character(cid))

    @bp.post('/api/characters/<cid>/upload')
    def upload_character_image(cid):
        image_type = request.form.get('type', 'portrait')
        if image_type not in ('portrait', 'triptych'):
            return jsonify(error="Invalid image type; must be 'portrait' or 'triptych'"), 400
        upload = request.files.get('file')
        if upload is None:
            return jsonify(error='No file provided'), 400
        if not characters.get_character(cid):
            return jsonify(error=f"Character '{cid}' not found"), 404
        dest = characters.save_character_image(cid, image_type, secure_filename(upload.filename or 'image.png'), upload.read())
        return jsonify(success=True, filename=dest, url=f'/api/characters/{cid}/image/{dest}')

    @bp.get('/api/characters/<cid>/image/<filename>')
    def character_image(cid, filename):
        path = characters.get_image_path(cid, filename)
        if not path or not path.is_file():
            return jsonify(error='Image not found'), 404
        return send_file(str(path))

    app.register_blueprint(bp)
    return bp
