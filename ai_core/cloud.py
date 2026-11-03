"""Opt-in cloud providers (fal.ai, Google Gemini). Never called implicitly.

Keys live in the OS credential store (``keyring``), are only sent to their own
provider, and are masked in every response and error message.
"""
import mimetypes
import uuid
from pathlib import Path

import requests

from job_process import check_cancelled

from . import catalog, paths, settings
from .errors import AIUnavailable

SERVICE = 'AI Influencer Media Grabber'
PROVIDERS = {'fal': 'fal.ai', 'gemini': 'Google Gemini'}
MAX_KEY_LENGTH = 512


def _keyring():
    try:
        import keyring
    except ImportError as exc:
        raise AIUnavailable('Secure key storage is not installed. Install the AI pack to use cloud providers.',
                            setup_hint='ai_pack') from exc
    return keyring


def _check_provider(provider):
    if provider not in PROVIDERS:
        raise ValueError(f'Unknown cloud provider: {provider}')


def _get_key(provider):
    _check_provider(provider)
    try:
        return _keyring().get_password(SERVICE, provider)
    except AIUnavailable:
        return None


def has_key(provider):
    return bool(_get_key(provider))


def mask(key):
    if not key:
        return None
    return '••••' + key[-4:] if len(key) > 8 else '••••'


def masked(provider):
    return mask(_get_key(provider))


def set_key(provider, key):
    """Store a key in the credential store; returns only the masked form."""
    _check_provider(provider)
    key = (key or '').strip()
    if not key or len(key) > MAX_KEY_LENGTH or any(c.isspace() for c in key):
        raise ValueError('Enter a valid API key.')
    _keyring().set_password(SERVICE, provider, key)
    return mask(key)


def delete_key(provider):
    _check_provider(provider)
    keyring = _keyring()
    try:
        keyring.delete_password(SERVICE, provider)
    except keyring.errors.PasswordDeleteError:
        return False
    return True


def _require(provider):
    _check_provider(provider)
    if not settings.cloud_enabled(provider):
        raise AIUnavailable(f'{PROVIDERS[provider]} is turned off. Enable it in Settings → Cloud to use this paid option.',
                            setup_hint='cloud')
    key = _get_key(provider)
    if not key:
        raise AIUnavailable(f'Add your {PROVIDERS[provider]} API key in Settings → Cloud.', setup_hint='cloud')
    return key


def _scrub(error, key):
    text = str(error)
    return text.replace(key, mask(key)) if key else text


def _fal_client(key):
    try:
        import fal_client
    except ImportError as exc:
        raise AIUnavailable('The fal.ai client is not installed. Install the GPU AI pack.', setup_hint='ai_pack') from exc
    return fal_client.SyncClient(key=key, default_timeout=900)


def _fal_run(endpoint_name, image, video, extra, pro=False):
    key = _require('fal')
    endpoint = catalog.cloud_endpoint('fal', endpoint_name)
    if not endpoint:
        raise AIUnavailable('This cloud endpoint is not configured in the catalog.', setup_hint='cloud')
    endpoint_id = endpoint['pro_endpoint'] if pro and endpoint.get('pro_endpoint') else endpoint['endpoint']
    client = _fal_client(key)
    try:
        check_cancelled()
        arguments = {endpoint['image_arg']: client.upload_file(str(image)),
                     endpoint['video_arg']: client.upload_file(str(video)), **extra}
        check_cancelled()
        result = client.subscribe(endpoint_id, arguments=arguments)
    except AIUnavailable:
        raise
    except Exception as exc:  # provider SDK errors vary; surface them without the key
        raise AIUnavailable(f'{PROVIDERS["fal"]} request failed: {_scrub(exc, key)}', setup_hint='cloud') from None
    video_info = (result or {}).get('video') if isinstance(result, dict) else None
    if not isinstance(video_info, dict) or not video_info.get('url'):
        raise AIUnavailable(f'{PROVIDERS["fal"]} returned no video.')
    return {'video_url': video_info['url'], 'provider': 'fal', 'endpoint': endpoint_id, 'local': False}


def kling_motion_control(image, video, **opts):
    """Kling motion control on fal.ai: the character in ``image`` performs the motion in ``video``."""
    orientation = opts.get('character_orientation', 'video')
    if orientation not in ('video', 'image'):
        raise ValueError('character_orientation must be "video" or "image"')
    extra = {'character_orientation': orientation}
    if opts.get('prompt'):
        extra['prompt'] = str(opts['prompt'])[:2500]
    if 'keep_original_sound' in opts:
        extra['keep_original_sound'] = bool(opts['keep_original_sound'])
    return _fal_run('kling_motion_control', image, video, extra, pro=bool(opts.get('pro')))


def live_portrait(image, video):
    return _fal_run('live_portrait', image, video, {})


def nano_banana_edit(images, prompt):
    """Gemini image edit ('Nano Banana'); saves returned images and returns their paths."""
    key = _require('gemini')
    endpoint = catalog.cloud_endpoint('gemini', 'nano_banana') or {}
    if not prompt or not images:
        raise ValueError('An image and an edit instruction are required.')
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise AIUnavailable('The Google GenAI client is not installed. Install the GPU AI pack.', setup_hint='ai_pack') from exc
    parts = []
    for image in images:
        path = Path(image)
        parts.append(types.Part.from_bytes(data=path.read_bytes(),
                                           mime_type=mimetypes.guess_type(path.name)[0] or 'image/png'))
    try:
        check_cancelled()
        client = genai.Client(api_key=key)
        response = client.models.generate_content(model=endpoint.get('model', 'gemini-2.5-flash-image'),
                                                  contents=[str(prompt), *parts])
    except Exception as exc:
        raise AIUnavailable(f'{PROVIDERS["gemini"]} request failed: {_scrub(exc, key)}', setup_hint='cloud') from None
    outputs = []
    destination = paths.DATA_DIR / 'AI Studio' / 'nano_banana'
    for candidate in getattr(response, 'candidates', None) or []:
        for part in getattr(getattr(candidate, 'content', None), 'parts', None) or []:
            inline = getattr(part, 'inline_data', None)
            if inline is not None and getattr(inline, 'data', None):
                destination.mkdir(parents=True, exist_ok=True)
                extension = mimetypes.guess_extension(inline.mime_type or 'image/png') or '.png'
                target = destination / f'edit-{uuid.uuid4().hex[:10]}{extension}'
                target.write_bytes(inline.data)
                outputs.append(target)
    if not outputs:
        raise AIUnavailable(f'{PROVIDERS["gemini"]} returned no image (the request may have been blocked).')
    return outputs


def download_result(url, destination):
    """Fetch a provider result URL to a local file."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=(10, 300)) as response:
        response.raise_for_status()
        with open(destination, 'wb') as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                check_cancelled()
                output.write(chunk)
    return destination


def status():
    return {provider: {'name': name, 'enabled': settings.cloud_enabled(provider), 'has_key': has_key(provider),
                       'masked_key': masked(provider), 'local': False}
            for provider, name in PROVIDERS.items()}
