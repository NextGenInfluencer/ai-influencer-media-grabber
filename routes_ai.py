"""/api/ai/* blueprint: profile, catalog, notices, installs, storage, engines, settings, cloud keys."""
from flask import Blueprint, jsonify, request

from ai_core import catalog, cloud, engines, gpu, hardware, llm, models, settings
from ai_core.errors import AIUnavailable, ConsentRequired, ModelMissing

bp = Blueprint('ai', __name__, url_prefix='/api/ai')
LLM_ROLES = ('helper', 'translator', 'vision')


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _error(message, status, setup_hint=None, **extra):
    return jsonify(error=message, setup_hint=setup_hint, **extra), status


@bp.errorhandler(ConsentRequired)
def _consent(exc):
    return _error(exc.message, 409, exc.setup_hint, consent_required=True)


@bp.errorhandler(AIUnavailable)
def _unavailable(exc):
    return _error(exc.message, 424, exc.setup_hint)


@bp.errorhandler(KeyError)
def _unknown(exc):
    return _error(f'Unknown item: {exc.args[0] if exc.args else ""}', 404)


@bp.errorhandler(ValueError)
def _invalid(exc):
    return _error(str(exc), 400)


def _speech_resolution(profile):
    from ai_core import asr
    try:
        item = asr.speech_item()
    except AIUnavailable as exc:
        return {'available': False, 'local': True, 'model': None, 'error': exc.message, 'setup_hint': exc.setup_hint}
    return {'available': True, 'local': True, 'model': item['source']['model_name'], 'item_id': item['id'],
            'backend': 'whisper', 'vram_gb': item.get('vram_gb', 0), 'profile': profile}


def _profile_payload():
    info = hardware.detect()
    current = hardware.current_profile()
    roles = {}
    for role in LLM_ROLES:
        try:
            choice = llm.resolve(role)
            roles[role] = {**choice, 'available': True, 'eta_seconds': llm.eta_seconds(choice)}
        except AIUnavailable as exc:
            roles[role] = {'available': False, 'local': True, 'model': None, 'error': exc.message,
                           'setup_hint': exc.setup_hint}
    roles['speech'] = _speech_resolution(current)
    states = models.status()
    return {
        'hardware': info, 'profile': current, 'detected_profile': hardware.profile(info),
        'override': settings.load().get('profile_override'), 'profiles': list(hardware.PROFILES), 'roles': roles,
        'bundle': [{'id': i, 'name': catalog.get(i)['name'], 'installed': states[i]['installed'],
                    'size_bytes': catalog.get(i).get('size_bytes'),
                    'non_commercial': catalog.get(i)['license'].get('non_commercial', False)}
                   for i in catalog.bundle(current)],
    }


@bp.get('/profile')
def get_profile():
    return jsonify(_profile_payload())


@bp.post('/profile')
def set_profile():
    value = _body().get('profile')
    if value is not None and value not in hardware.PROFILES:
        raise ValueError('Unknown profile.')
    settings.update(lambda data: data.__setitem__('profile_override', value))
    return jsonify(_profile_payload())


@bp.get('/catalog')
def get_catalog():
    data = catalog.data()
    states = models.status()
    for item in data['items']:
        item['status'] = states[item['id']]
    data['workflows'] = sorted(data.get('workflows', {}))
    return jsonify(data)


@bp.get('/notice/<item_id>')
def get_notice(item_id):
    return jsonify(models.notice(item_id))


@bp.post('/install')
def install():
    body = _body()
    item_id = body.get('item_id')
    if not isinstance(item_id, str) or not catalog.exists(item_id):
        return _error('Choose a catalog item to install.', 400)
    job_id = models.start_install(item_id, accept_license=body.get('accept_license') is True)
    return jsonify(job_id=job_id, job=models.job(job_id)), 202


@bp.get('/jobs/<job_id>')
def get_job(job_id):
    current = models.job(job_id)
    return jsonify(current) if current else _error('Unknown job.', 404)


@bp.post('/jobs/<job_id>/cancel')
def cancel_job(job_id):
    if models.job(job_id) is None:
        return _error('Unknown job.', 404)
    return jsonify(cancelled=models.cancel(job_id))


@bp.get('/storage')
def get_storage():
    return jsonify(models.storage())


@bp.post('/storage/verify')
def verify_storage():
    body = _body()
    item_id = body.get('item_id')
    if item_id is not None and (not isinstance(item_id, str) or not catalog.exists(item_id)):
        return _error('Unknown item.', 404)
    return jsonify(models.verify_installed(item_id))


@bp.post('/remove')
def remove():
    body = _body()
    if isinstance(body.get('item_id'), str):
        return jsonify(models.remove(body['item_id']))
    target = body.get('id') or body.get('path')
    if not isinstance(target, str) or not target:
        return _error('Choose an installed item or a file listed under Reclaim space.', 400)
    return jsonify(removed=[models.remove_reclaimable(target)['path']])


@bp.get('/engines')
def get_engines():
    return jsonify(engines=engines.status(), gpu=gpu.status())


@bp.post('/engines/<name>/<action>')
def control_engine(name, action):
    engine = {'ollama': engines.ollama, 'comfy': engines.comfy}.get(name)
    if engine is None or action not in ('start', 'stop'):
        return _error('Unknown engine action.', 404)
    if action == 'start':
        engine.ensure_running()
    else:
        engine.stop()
    return jsonify(engine.status())


def _settings_payload():
    data = settings.load()
    return {'roles': data.get('roles', {}), 'profile_override': data.get('profile_override'),
            'idle_release_seconds': data.get('idle_release_seconds'), 'accepted_licenses': data.get('accepted_licenses', []),
            'notices': data.get('notices', {}), 'setup_seen': data.get('setup_seen') is True,
            'cloud': cloud.status()}


@bp.get('/settings')
def get_settings():
    return jsonify(_settings_payload())


@bp.post('/settings')
def post_settings():
    body = _body()
    roles = body.get('roles', {})
    cloud_flags = body.get('cloud', {})
    notices = body.get('notices', {})
    setup_seen = body.get('setup_seen')
    if not isinstance(roles, dict) or not isinstance(cloud_flags, dict) or not isinstance(notices, dict):
        raise ValueError('Invalid settings.')
    for role, value in roles.items():
        if role not in settings.ROLES or (value is not None and (not isinstance(value, str) or len(value) > 200)):
            raise ValueError(f'Invalid model for role {role}.')
    for provider, flags in cloud_flags.items():
        if provider not in settings.CLOUD_PROVIDERS or not isinstance(flags, dict) or not isinstance(flags.get('enabled'), bool):
            raise ValueError(f'Invalid cloud setting for {provider}.')
    for name, accepted in notices.items():
        if name not in settings.NOTICES or not isinstance(accepted, bool):
            raise ValueError(f'Invalid notice: {name}.')
    if setup_seen is not None and not isinstance(setup_seen, bool):
        raise ValueError('setup_seen must be true or false.')
    idle = body.get('idle_release_seconds')
    if idle is not None and (not isinstance(idle, (int, float)) or not 10 <= idle <= 86400):
        raise ValueError('Idle release must be between 10 seconds and 24 hours.')

    def apply(data):
        for role, value in roles.items():
            data['roles'][role] = value or None
        for provider, flags in cloud_flags.items():
            data['cloud'][provider] = {'enabled': flags['enabled']}
        for name, accepted in notices.items():
            data['notices'][name] = accepted
        if setup_seen is not None:
            data['setup_seen'] = setup_seen
        if idle is not None:
            data['idle_release_seconds'] = idle
    settings.update(apply)
    return jsonify(_settings_payload())


@bp.post('/cloud/key')
def cloud_key():
    body = _body()
    provider = body.get('provider')
    if provider not in cloud.PROVIDERS:
        return _error('Unknown cloud provider.', 400)
    if body.get('delete') is True:
        cloud.delete_key(provider)
        return jsonify(provider=provider, has_key=False, masked=None)
    masked = cloud.set_key(provider, body.get('key') if isinstance(body.get('key'), str) else '')
    return jsonify(provider=provider, has_key=True, masked=masked)


@bp.get('/models')
def get_models():
    return jsonify(models=llm.available_models())


def register_ai_routes(app):
    app.register_blueprint(bp)
    return bp
