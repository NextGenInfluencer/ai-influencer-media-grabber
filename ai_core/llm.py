"""One router for every local LLM call: Ollama on GPU PCs, built-in llama.cpp on laptops.

Nothing here fabricates output. Any failure raises ``AIUnavailable`` so callers
can show an honest "not available" state.
"""
import atexit
import json
import os
import re
import threading
import time

import requests

from assets.lyric_translation import require_local_ollama_model
from job_process import check_cancelled

from . import catalog, engines, gpu, hardware, models, settings
from .errors import AIUnavailable, ModelMissing

ROLE_CAPABILITY = {'helper': 'tools', 'translator': None, 'vision': 'vision'}
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_SECONDS = 600
KEEP_ALIVE = '2m'
BUILTIN_CTX = 8192
_THINK = re.compile(r'<think>.*?</think>\s*', re.S)
_caps_cache = {}
_caps_lock = threading.Lock()
_builtin = {'path': None, 'model': None}


# ---------------------------------------------------------------- capabilities

def _ollama_capabilities(name, entry=None):
    with _caps_lock:
        if name in _caps_cache:
            return _caps_cache[name]
    listed = entry.get('capabilities') if isinstance(entry, dict) else None
    if isinstance(listed, list):  # recent Ollama versions report capabilities in /api/tags
        result = {c for c in listed if isinstance(c, str)}
        with _caps_lock:
            _caps_cache[name] = result
        return result
    known = None
    if catalog.exists(name):
        known = set(catalog.get(name).get('capabilities', []))
    metadata = engines.ollama.show(name) if engines.ollama.running() else {}
    caps = metadata.get('capabilities') if isinstance(metadata, dict) else None
    if isinstance(caps, list):
        result = {c for c in caps if isinstance(c, str)}
        with _caps_lock:
            _caps_cache[name] = result
        return result
    return known if known is not None else set()


def _installed_ollama():
    return {entry['name']: entry for entry in engines.ollama.tags()}


def _ollama_choice(tag, role, profile, item=None, entry=None):
    item = item or (catalog.get(tag) if catalog.exists(tag) else {})
    vram = item.get('vram_gb')
    if vram is None and entry and entry.get('size'):
        vram = round(entry['size'] / 1024 ** 3 * 1.15, 1)  # weights plus a working context
    return {'backend': 'ollama', 'model': tag, 'item_id': item.get('id'), 'local': True, 'profile': profile,
            'role': role, 'vram_gb': vram, 'prompt_format': item.get('prompt_format')
            or ('translategemma' if tag.startswith('translategemma') else None),
            'capabilities': sorted(_ollama_capabilities(tag, entry))}


def _builtin_choice(item, role, profile):
    return {'backend': 'builtin', 'model': item['id'], 'item_id': item['id'], 'local': True, 'profile': profile,
            'role': role, 'vram_gb': 0, 'prompt_format': item.get('prompt_format'),
            'capabilities': item.get('capabilities', [])}


def _choice_for(name, role, profile, installed_tags):
    """Resolve an explicit model name (catalog id or Ollama tag), or None if not installed."""
    if catalog.exists(name):
        item = catalog.get(name)
        if item.get('backend') == 'builtin':
            return _builtin_choice(item, role, profile) if models.installed(name) and engines.builtin.available() else None
        if item.get('backend') == 'ollama':
            return _ollama_choice(name, role, profile, item, installed_tags[name]) if name in installed_tags else None
        return None
    return _ollama_choice(name, role, profile, entry=installed_tags[name]) if name in installed_tags else None


def _has_capability(entry, role):
    needed = ROLE_CAPABILITY.get(role)
    caps = _ollama_capabilities(entry['name'], entry)
    if 'embedding' in caps and 'completion' not in caps:
        return False
    return needed is None or needed in caps


def resolve(role, model=None):
    """Pick the model for a role: override → recommended → capable Ollama model → built-in."""
    if role not in ROLE_CAPABILITY:
        raise AIUnavailable(f'Unknown AI role: {role}', setup_hint='ai_setup')
    profile = hardware.current_profile()
    installed_tags = _installed_ollama()
    explicit = model or settings.get_role_override(role)
    if explicit:
        choice = _choice_for(explicit, role, profile, installed_tags)
        if choice is None:
            raise ModelMissing(f'The selected model "{explicit}" is not installed on this PC.', setup_hint=explicit)
        return choice
    info = hardware.detect()
    recommended = catalog.recommended(profile, role, info)
    for item_id in recommended:
        choice = _choice_for(item_id, role, profile, installed_tags)
        if choice:
            return choice
    ranked = sorted(installed_tags.values(), key=lambda e: -(e.get('size') or 0))
    for entry in ranked:
        if _has_capability(entry, role):
            return _ollama_choice(entry['name'], role, profile, entry=entry)
    if engines.builtin.available():
        for item in catalog.items():
            if item.get('backend') == 'builtin' and role in item.get('roles', []) and models.installed(item['id']):
                return _builtin_choice(item, role, profile)
    hint = recommended[0] if recommended else 'ai_setup'
    raise AIUnavailable(f'No local model for the {role} role is installed on this PC.', setup_hint=hint)


def available_models():
    result = []
    for name, entry in _installed_ollama().items():
        result.append({'name': name, 'backend': 'ollama', 'item_id': name if catalog.exists(name) else None,
                       'capabilities': sorted(_ollama_capabilities(name, entry)), 'size_bytes': entry.get('size'),
                       'local': True})
    if engines.builtin.available():
        for item in catalog.items():
            if item.get('backend') == 'builtin' and models.installed(item['id']):
                result.append({'name': item['id'], 'backend': 'builtin', 'item_id': item['id'],
                               'capabilities': item.get('capabilities', []), 'size_bytes': item.get('size_bytes'),
                               'local': True})
    return result


# ---------------------------------------------------------------- Ollama backend

def _ollama_messages(messages, images):
    prepared = [dict(m) for m in messages]
    if images:
        for message in reversed(prepared):
            if message.get('role') == 'user':
                message['images'] = list(images)
                break
        else:
            prepared.append({'role': 'user', 'content': '', 'images': list(images)})
    return prepared


def _normalize_tool_calls(raw):
    calls = []
    for call in raw or []:
        function = call.get('function', call) if isinstance(call, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get('name'), str):
            raise AIUnavailable('The model returned a malformed tool call.')
        arguments = function.get('arguments', {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError as exc:
                raise AIUnavailable('The model returned malformed tool arguments.') from exc
        if not isinstance(arguments, dict):
            raise AIUnavailable('The model returned malformed tool arguments.')
        calls.append({'name': function['name'], 'arguments': arguments})
    return calls


def _ollama_chat(choice, messages, tools, schema, images, max_tokens, temperature, on_token):
    tag = choice['model']
    engines.ollama.ensure_running()
    try:
        require_local_ollama_model(tag)
    except ValueError as exc:
        raise AIUnavailable(str(exc), setup_hint='ai_setup') from exc
    payload = {'model': tag, 'messages': _ollama_messages(messages, images), 'stream': True, 'keep_alive': KEEP_ALIVE,
               'options': {'temperature': temperature, 'num_predict': max_tokens, 'num_ctx': 8192}}
    if schema:
        payload['format'] = schema
    if tools:
        payload['tools'] = tools
    if tag.startswith('qwen3'):
        payload['think'] = False
    parts, tool_calls = [], []
    state = {'done': False, 'received': 0}
    started = time.monotonic()

    def consume(line):
        if not line.strip():
            return
        try:
            event = json.loads(line)
        except ValueError as exc:
            raise AIUnavailable('Ollama returned an invalid response.') from exc
        if not isinstance(event, dict):
            raise AIUnavailable('Ollama returned an invalid response.')
        if event.get('error'):
            raise AIUnavailable(f'Ollama could not answer: {event["error"]}')
        message = event.get('message') or {}
        if not isinstance(message, dict):
            raise AIUnavailable('Ollama returned an invalid response.')
        content = message.get('content') or ''
        if not isinstance(content, str):
            raise AIUnavailable('Ollama returned invalid content.')
        if content:
            parts.append(content)
            if on_token:
                on_token(content)
        tool_calls.extend(_normalize_tool_calls(message.get('tool_calls')))
        state['done'] = event.get('done') is True

    with gpu.lease('ollama', choice.get('vram_gb') or 0):
        try:
            with requests.post(engines.ollama.base_url + '/api/chat', json=payload, stream=True,
                               timeout=(10, 180), allow_redirects=False) as response:
                if response.status_code != 200:
                    raise AIUnavailable(f'Ollama refused the request (HTTP {response.status_code}).')
                pending = b''
                for chunk in response.iter_content(chunk_size=4096):
                    check_cancelled()
                    if time.monotonic() - started > MAX_SECONDS:
                        raise AIUnavailable('The local model took too long to answer.')
                    state['received'] += len(chunk)
                    if state['received'] > MAX_RESPONSE_BYTES:
                        raise AIUnavailable('The local model answer exceeded the response limit.')
                    pending += chunk
                    while b'\n' in pending and not state['done']:
                        line, pending = pending.split(b'\n', 1)
                        consume(line)
                    if state['done']:
                        break
                if not state['done'] and pending:
                    consume(pending)
        except requests.RequestException as exc:
            check_cancelled()
            raise AIUnavailable('Ollama stopped responding. Check AI Engines and retry.', setup_hint='engines') from exc
    check_cancelled()
    if not state['done']:
        raise AIUnavailable('Ollama disconnected before finishing the answer.')
    return ''.join(parts), tool_calls


# ---------------------------------------------------------------- built-in backend

def _unload_builtin():
    with gpu.model_lock('builtin'):
        model = _builtin['model']
        _builtin.update(path=None, model=None)
        if model is not None and hasattr(model, 'close'):
            try:
                model.close()
            except Exception:
                pass


atexit.register(_unload_builtin)
gpu.register_evictor('builtin', _unload_builtin)


def _load_builtin(path, item):
    if _builtin['model'] is not None and _builtin['path'] == str(path):
        return _builtin['model']
    _unload_builtin()
    try:
        from llama_cpp import Llama
    except (ImportError, OSError) as exc:
        raise AIUnavailable('The built-in AI engine is not installed. Install the AI pack from AI Setup.',
                            setup_hint='ai_pack') from exc
    model = Llama(model_path=str(path), n_ctx=BUILTIN_CTX, n_threads=max(1, (os.cpu_count() or 4) - 1),
                  n_batch=512, n_gpu_layers=0, chat_format=item.get('chat_format'), verbose=False)
    _builtin.update(path=str(path), model=model)
    return model


def _tool_schema(tools):
    names = [t.get('function', t).get('name') for t in tools if isinstance(t, dict)]
    return {'type': 'object', 'properties': {
        'tool_calls': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'name': {'type': 'string', 'enum': names}, 'arguments': {'type': 'object'}},
            'required': ['name', 'arguments']}},
        'content': {'type': 'string'}}, 'required': ['tool_calls', 'content']}


def _builtin_messages(messages, tools, item):
    prepared = []
    for message in messages:
        role = message.get('role')
        content = message.get('content') or ''
        if role == 'tool':
            prepared.append({'role': 'user', 'content': f'Tool result ({message.get("name") or message.get("tool_name") or "tool"}): {content}'})
        elif role == 'assistant' and message.get('tool_calls'):
            prepared.append({'role': 'assistant', 'content': json.dumps(
                {'tool_calls': _normalize_tool_calls(message['tool_calls']), 'content': content}, ensure_ascii=False)})
        else:
            prepared.append({'role': role, 'content': content})
    if tools:
        spec = json.dumps([t.get('function', t) for t in tools], ensure_ascii=False)
        prepared.insert(0, {'role': 'system', 'content': (
            'You can call these tools. Answer with JSON {"tool_calls":[{"name":...,"arguments":{...}}],"content":"..."}; '
            'use an empty tool_calls list when no tool is needed.\nTools: ' + spec)})
    if item['id'].startswith('qwen3') and prepared and prepared[-1]['role'] == 'user':
        prepared[-1] = {**prepared[-1], 'content': prepared[-1]['content'] + ' /no_think'}
    return prepared


def _builtin_chat(choice, messages, tools, schema, images, max_tokens, temperature, on_token):
    if images:
        raise AIUnavailable('The built-in engine cannot read images. Install a vision model from AI Setup.',
                            setup_hint='blip-base')
    item = catalog.get(choice['item_id'])
    path = models.ensure(item['id'])
    response_schema = _tool_schema(tools) if tools else schema
    kwargs = {'messages': _builtin_messages(messages, tools, item), 'temperature': temperature,
              'repeat_penalty': 1.15, 'max_tokens': max_tokens, 'stream': True}
    if response_schema:
        kwargs['response_format'] = {'type': 'json_object', 'schema': response_schema}
    parts = []
    with gpu.model_lock('builtin'):
        model = _load_builtin(path, item)
        if hasattr(model, 'reset'):
            model.reset()
        check_cancelled()
        stream = model.create_chat_completion(**kwargs)
        try:
            for chunk in stream:
                check_cancelled()
                piece = chunk['choices'][0].get('delta', {}).get('content') or ''
                if piece:
                    parts.append(piece)
                    if on_token and not tools:
                        on_token(piece)
        finally:
            close = getattr(stream, 'close', None)
            if close:
                close()
    gpu.touch('builtin')
    content = _THINK.sub('', ''.join(parts)).strip()
    if not tools:
        return content, []
    try:
        data = json.loads(content)
        calls = _normalize_tool_calls(data.get('tool_calls'))
        text = data.get('content', '')
    except (ValueError, AttributeError) as exc:
        raise AIUnavailable('The built-in model returned an invalid tool answer.') from exc
    if not isinstance(text, str):
        raise AIUnavailable('The built-in model returned an invalid tool answer.')
    if on_token and text:
        on_token(text)
    return text, calls


# ---------------------------------------------------------------- public API

def chat(role, messages, *, tools=None, schema=None, images=None, max_tokens=1024, temperature=0.3,
         on_token=None, model=None):
    """Run one chat turn on the role's local model. Raises AIUnavailable; never fabricates."""
    if not isinstance(messages, list) or not messages:
        raise ValueError('messages must be a non-empty list')
    check_cancelled()
    choice = resolve(role, model=model)
    if choice['backend'] == 'ollama':
        content, calls = _ollama_chat(choice, messages, tools, schema, images, max_tokens, temperature, on_token)
    else:
        content, calls = _builtin_chat(choice, messages, tools, schema, images, max_tokens, temperature, on_token)
    content = _THINK.sub('', content).strip()
    if not content and not calls:
        raise AIUnavailable('The local model returned an empty answer. Nothing was changed.')
    if schema and not tools:
        try:
            json.loads(content)
        except ValueError as exc:
            raise AIUnavailable('The local model returned invalid structured data. Nothing was changed.') from exc
    return {'content': content, 'tool_calls': calls, 'model': choice['model'], 'backend': choice['backend']}


def eta_seconds(choice):
    """Rough per-turn estimate shown on cost chips (GPU via Ollama vs CPU built-in)."""
    return 20 if choice['backend'] == 'ollama' else 60


def cost(role):
    """Cost chip data for UI: {local, model, eta_seconds, vram_gb} or an unavailable marker."""
    try:
        choice = resolve(role)
    except AIUnavailable as exc:
        return {'available': False, 'local': True, 'model': None, 'eta_seconds': None, 'vram_gb': None,
                'error': exc.message, 'setup_hint': exc.setup_hint}
    return {'available': True, 'local': True, 'model': choice['model'], 'backend': choice['backend'],
            'eta_seconds': eta_seconds(choice), 'vram_gb': choice.get('vram_gb') or 0}
