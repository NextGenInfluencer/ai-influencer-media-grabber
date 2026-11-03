"""Studio Copilot: a local agent that operates the app through real capabilities.

The agent loop runs on the helper model via ``ai_core.llm.chat(role='helper', tools=...)``:
model → tool calls → execute → results fed back as ``tool`` messages → repeat (at most
``MAX_STEPS``) → final answer. Nothing here fabricates content:

* read-only tools (audit, caption lines, gallery search, image description, Instagram
  listing, capabilities) execute immediately on real data;
* job, destructive or costly tools return a **proposal** card that the UI applies
  through the app's existing endpoints only after the user presses Apply;
* when no helper model is installed the error and its ``setup_hint`` are returned
  verbatim so the drawer can offer "Set up AI".
"""
import json
import queue
import threading
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request

import job_process
from ai_core import llm, models
from ai_core.errors import AIUnavailable

MAX_STEPS = 6
MAX_HISTORY = 20
CONTEXT_BUDGET_CHARS = 12000
TOOL_RESULT_CHARS = 6000
LINES_PER_READ = 80
PAGES = ('captions', 'downloader', 'studio')
PRESETS = ('mrbeast_bold', 'cyberpunk_neon', 'frosted_vlog', 'sunset_glow', 'neon_karaoke', 'cinematic_clean',
           'bold_pop', 'minimalist_lyric', 'clean', 'bold', 'lyrics', 'karaoke')
NAV_TARGETS = ('downloader', 'converter', 'cleaner', 'gallery', 'history', 'captions', 'video_studio', 'ai_setup')


def _schema(properties=None, required=()):
    return {'type': 'object', 'properties': properties or {}, 'required': list(required)}


STR, NUM, INT, BOOL = {'type': 'string'}, {'type': 'number'}, {'type': 'integer'}, {'type': 'boolean'}

# name → (description, parameters, kind, pages, eta_seconds, requirement)
# kind: 'instant' executes now on real data; 'proposal' needs the user's Apply.
TOOLS = {
    'list_capabilities': ('List what the Copilot and this PC can actually do right now.', _schema(), 'instant', PAGES, 0, None),
    'audit_subtitles': ('Check caption lines for reading speed, missing translations, overlaps and very short or long lines.',
                        _schema({'focus': {'type': 'string', 'enum': ['all', 'reading_speed', 'missing_translations', 'timing']}}),
                        'instant', ('captions',), 0, None),
    'read_caption_lines': ('Read caption lines by 1-based line number (use when lines were omitted from the context).',
                           _schema({'start_line': INT, 'end_line': INT}, ['start_line']), 'instant', ('captions',), 0, None),
    'search_gallery': ('Search downloaded and created media in the gallery by words in the file name, folder or uploader.',
                       _schema({'query': STR, 'kind': {'type': 'string', 'enum': ['any', 'video', 'image', 'audio']},
                                'limit': INT}, ['query']), 'instant', PAGES, 0, None),
    'describe_image': ('Describe an image from the library with the local vision model.',
                       _schema({'path': STR}, ['path']), 'instant', PAGES, 20, 'vision'),
    'list_instagram_profile': ('List recent posts of a public Instagram profile (read-only preview).',
                               _schema({'url': STR}, ['url']), 'instant', ('downloader',), 30, None),
    'download_url': ('Propose downloading a video or post URL with the downloader.',
                     _schema({'url': STR, 'format': {'type': 'string', 'enum': ['video', 'audio']}}, ['url']),
                     'proposal', ('downloader',), 30, None),
    'transcribe_project': ('Propose transcribing the open captions project with the speech model.',
                           _schema({'language': STR}), 'proposal', ('captions',), 120, 'speech'),
    'sync_lyrics': ('Propose opening lyric sync so pasted lyrics are timed to the song.', _schema(), 'proposal',
                    ('captions',), 120, 'speech'),
    'translate_project': ('Propose translating all unlocked lines into a language (ISO code such as en, el, ko).',
                          _schema({'language': STR}, ['language']), 'proposal', ('captions',), 180, 'translator'),
    'batch_fix_subtitles': ('Propose corrected original text and/or translations for specific lines; the user reviews them.',
                            _schema({'updates': {'type': 'array', 'items': _schema(
                                {'line': INT, 'text': STR, 'translation': STR, 'lang': STR}, ['line'])}}, ['updates']),
                            'proposal', ('captions',), 0, None),
    'shift_timing': ('Propose shifting all caption timings by seconds (positive = later).',
                     _schema({'seconds': NUM}, ['seconds']), 'proposal', ('captions',), 0, None),
    'apply_preset': ('Propose applying a caption style preset.', _schema({'preset': {'type': 'string', 'enum': list(PRESETS)}},
                                                                        ['preset']), 'proposal', ('captions',), 0, None),
    'set_font': ('Propose changing the caption font family.', _schema({'font': STR}, ['font']), 'proposal',
                 ('captions',), 0, None),
    'render_export': ('Propose exporting the captions project as an MP4.', _schema(), 'proposal', ('captions',), 120, None),
    'generate_storyboard': ('Propose planning a music-video storyboard with the AI Director.',
                            _schema({'concept': STR, 'num_scenes': INT}), 'proposal', ('studio',), 60, 'helper'),
    'generate_keyframe': ('Propose rendering a keyframe image for a storyboard scene.',
                          _schema({'scene': INT, 'prompt': STR}, ['prompt']), 'proposal', ('studio',), 60, 'flux_schnell_t2i'),
    'animate_keyframe': ('Propose animating a scene keyframe into a short video clip.',
                         _schema({'scene': INT, 'quality': {'type': 'string', 'enum': ['fast', 'quality']}}),
                         'proposal', ('studio',), 420, 'wan22_ti2v_5b'),
    'face_swap': ('Propose a face swap of the active persona into a video.', _schema({'video_path': STR}), 'proposal',
                  ('studio',), 300, 'face_swap'),
    'lip_sync': ('Propose lip-syncing a face video to the song audio.', _schema({'video_path': STR}), 'proposal',
                 ('studio',), 600, 'latentsync'),
    'open_in_explorer': ('Propose opening a library folder or file in File Explorer.', _schema({'path': STR}),
                         'proposal', PAGES, 0, None),
    'navigate': ('Propose switching to another part of the app.', _schema({'target': {'type': 'string', 'enum': list(NAV_TARGETS)}},
                                                                         ['target']), 'proposal', PAGES, 0, None),
}


# ---------------------------------------------------------------- availability

def _requirement_met(requirement):
    """True when the model behind a tool is installed on this PC (never claimed otherwise)."""
    if requirement is None:
        return True
    try:
        if requirement in ('helper', 'translator', 'vision'):
            if requirement == 'vision' and models.installed('blip-base'):
                return True
            return llm.cost(requirement)['available']
        if requirement == 'speech':
            from ai_core import asr
            asr.speech_item()
            return True
        if requirement == 'face_swap':
            return models.installed('inswapper-128') and models.installed('insightface-buffalo-l')
        from ai_core import comfy
        return models.installed('engine-comfyui') and not comfy.requirements_missing(requirement)
    except (AIUnavailable, KeyError, OSError):
        return False


def tool_states(page):
    """Each tool for the page with its availability, generated from the registry."""
    page = page if page in PAGES else None
    states = []
    for name, (description, _, kind, pages, eta, requirement) in TOOLS.items():
        if page and page not in pages:
            continue
        states.append({'name': name, 'description': description, 'kind': kind, 'eta_seconds': eta,
                       'available': _requirement_met(requirement)})
    return states


def capabilities(page=None):
    return {'helper': llm.cost('helper'), 'page': page, 'tools': tool_states(page)}


def tool_specs(states):
    return [{'type': 'function', 'function': {'name': s['name'], 'description': TOOLS[s['name']][0],
                                              'parameters': TOOLS[s['name']][1]}} for s in states if s['available']]


# ---------------------------------------------------------------- context

def normalize_context(raw, legacy_project=None):
    context = dict(raw) if isinstance(raw, dict) else {}
    if legacy_project and not context.get('project'):
        context.update(page='captions', project=legacy_project)
    if context.get('page') not in PAGES:
        context['page'] = 'captions' if isinstance(context.get('project'), dict) and context['project'].get('cues') else None
    return context


def _cues(context):
    project = context.get('project') if isinstance(context.get('project'), dict) else {}
    cues = project.get('cues')
    return [c for c in cues if isinstance(c, dict)] if isinstance(cues, list) else []


def _translation_language(context):
    project = context.get('project') if isinstance(context.get('project'), dict) else {}
    style = project.get('style') if isinstance(project.get('style'), dict) else {}
    return str(style.get('translation_language') or 'en')


def _cue_line(number, cue, language):
    translation = (cue.get('translations') or {}).get(language) if isinstance(cue.get('translations'), dict) else None
    text = f'#{number} [{float(cue.get("start", 0)):.2f}-{float(cue.get("end", 0)):.2f}] {cue.get("text", "")}'
    if isinstance(translation, dict) and translation.get('text'):
        text += f' || {language}: {translation["text"]} ({translation.get("status", "approved")})'
    return text


def context_text(context):
    """Page context for the system prompt; caption lines are included until the budget, the rest via a tool."""
    page = context.get('page')
    parts = [f'Current page: {page or "unknown"}.']
    if context.get('unsaved'):
        parts.append('The page has unsaved edits: never propose navigating away.')
    if page == 'captions':
        project = context.get('project') or {}
        cues, language = _cues(context), _translation_language(context)
        parts.append(f'Captions project "{project.get("name", "")}", {len(cues)} lines, duration '
                     f'{project.get("duration", 0)} s, translation language {language}.')
        lines, used, omitted = [], 0, None
        for number, cue in enumerate(cues, 1):
            line = _cue_line(number, cue, language)
            if used + len(line) > CONTEXT_BUDGET_CHARS:
                omitted = f'Lines {number}-{len(cues)} are not shown; call read_caption_lines to read them.'
                break
            lines.append(line)
            used += len(line) + 1
        parts.append('Caption lines:\n' + '\n'.join(lines))
        if omitted:
            parts.append(omitted)
    elif page in ('downloader', 'studio'):
        summary = {k: v for k, v in context.items() if k not in ('page', 'unsaved')}
        parts.append('Page state: ' + json.dumps(summary, ensure_ascii=False, default=str)[:CONTEXT_BUDGET_CHARS])
    return '\n'.join(parts)


def system_prompt(context, states):
    unavailable = [s['name'] for s in states if not s['available']]
    rules = ('You are the Studio Copilot inside AI Influencer Media Grabber, running locally. Use tools to act. '
             'Read-only tools run immediately. Other tools only create a proposal card the user must approve with Apply; '
             'say so and never claim that a proposed action already happened. Never invent translations, file names, '
             'results or features. Write translations yourself only inside batch_fix_subtitles proposals. Answer briefly.')
    if unavailable:
        rules += ' Not installed on this PC (explain that and suggest AI Setup if asked): ' + ', '.join(unavailable) + '.'
    return rules + '\n\n' + context_text(context)


# ---------------------------------------------------------------- instant tools

def audit_subtitles(context, focus='all'):
    cues, language = _cues(context), _translation_language(context)
    issues = []
    for number, cue in enumerate(cues, 1):
        start, end = float(cue.get('start', 0)), float(cue.get('end', 0))
        duration = end - start
        text = str(cue.get('text') or '')
        translation = (cue.get('translations') or {}).get(language) or {}
        if focus in ('all', 'missing_translations') and not str(translation.get('text') or '').strip():
            issues.append({'line': number, 'type': 'missing_translation', 'message': f'No {language} translation.'})
        if focus in ('all', 'reading_speed') and duration > 0 and len(text) / duration > 20:
            issues.append({'line': number, 'type': 'reading_speed', 'cps': round(len(text) / duration, 1),
                           'message': 'More than 20 characters per second.'})
        if focus in ('all', 'timing'):
            if 0 < duration < 0.7:
                issues.append({'line': number, 'type': 'too_short', 'message': f'Only {duration:.2f} s on screen.'})
            if duration > 7:
                issues.append({'line': number, 'type': 'too_long', 'message': f'{duration:.1f} s on screen.'})
            if number < len(cues) and float(cues[number].get('start', 0)) < end - 0.01:
                issues.append({'line': number, 'type': 'overlap', 'message': f'Overlaps line {number + 1}.'})
    return {'total_lines': len(cues), 'language': language, 'issues': issues[:200], 'issue_count': len(issues)}


def read_caption_lines(context, start_line=1, end_line=None):
    cues, language = _cues(context), _translation_language(context)
    start = max(1, int(start_line))
    end = min(len(cues), int(end_line or start + LINES_PER_READ - 1), start + LINES_PER_READ - 1)
    return {'lines': [_cue_line(n, cues[n - 1], language) for n in range(start, end + 1)], 'total_lines': len(cues)}


def search_gallery(services, query, kind='any', limit=10):
    words = [w for w in str(query).lower().split() if w]
    if not words:
        raise ValueError('Give words to search for.')
    matches = []
    for item in services['gallery']() or []:
        haystack = ' '.join(str(item.get(k) or '') for k in ('name', 'folder', 'uploader', 'path')).lower()
        if all(w in haystack for w in words) and (kind in (None, 'any') or item.get('type') == kind):
            matches.append({k: item.get(k) for k in ('name', 'folder', 'type', 'full_path', 'source_url')})
    return {'matches': matches[:max(1, min(50, int(limit or 10)))], 'total': len(matches)}


def describe_image(services, path):
    from ai_core import vision
    if not services['allowed_path'](str(path)) or not Path(path).is_file():
        raise ValueError('Choose an image inside your Media Grabber library.')
    return vision.describe_scene(path)


def list_instagram_profile(url):
    import download_support
    if not download_support.is_instagram_profile_url(url):
        raise ValueError('That is not an Instagram profile link.')
    listing = download_support.extract_instagram_profile(url)
    entries = listing.get('entries') or listing.get('posts') or []
    return {'username': listing.get('username') or listing.get('uploader'), 'count': len(entries),
            'posts': [{k: e.get(k) for k in ('url', 'title', 'type', 'timestamp') if k in e} for e in entries[:30]]}


# ---------------------------------------------------------------- proposals

def _proposal(name, args, context, summary, diff=None):
    eta = TOOLS[name][4]
    return {'action': name, 'args': args, 'summary': summary, 'diff': diff, 'eta_seconds': eta or None,
            'local': True, 'badge': 'Local'}


def build_proposal(name, args, context):
    """Validate a proposed action and describe exactly what Apply will do (no side effects here)."""
    cues = _cues(context)
    if name == 'batch_fix_subtitles':
        updates, diff = [], []
        for update in args.get('updates') or []:
            if not isinstance(update, dict):
                continue
            line = int(update.get('line', 0))
            if not 1 <= line <= len(cues):
                raise ValueError(f'Line {line} does not exist.')
            cue = cues[line - 1]
            clean = {'line': line, 'id': cue.get('id')}
            if isinstance(update.get('text'), str) and update['text'].strip():
                clean['text'] = update['text'].strip()
                diff.append({'line': line, 'field': 'text', 'before': cue.get('text', ''), 'after': clean['text']})
            if isinstance(update.get('translation'), str) and update['translation'].strip():
                lang = str(update.get('lang') or _translation_language(context))
                before = ((cue.get('translations') or {}).get(lang) or {}).get('text', '')
                clean.update(translation=update['translation'].strip(), lang=lang)
                diff.append({'line': line, 'field': f'translation ({lang})', 'before': before, 'after': clean['translation']})
            if len(clean) > 2:
                updates.append(clean)
        if not updates:
            raise ValueError('No valid line changes were proposed.')
        return _proposal(name, {'updates': updates}, context,
                         f'{len(updates)} line(s) will be marked for review; exports skip them until you keep them.', diff)
    if name == 'shift_timing':
        seconds = float(args.get('seconds', 0))
        if not seconds or abs(seconds) > 600:
            raise ValueError('Shift must be a non-zero number of seconds (at most 10 minutes).')
        return _proposal(name, {'seconds': seconds}, context,
                         f'Shift all {len(cues)} lines {"later" if seconds > 0 else "earlier"} by {abs(seconds):.2f} s.')
    if name == 'apply_preset':
        if args.get('preset') not in PRESETS:
            raise ValueError('Unknown preset.')
        return _proposal(name, {'preset': args['preset']}, context, f'Apply the {args["preset"]} style preset.')
    if name == 'set_font':
        font = str(args.get('font') or '').strip()[:80]
        if not font:
            raise ValueError('Name a font.')
        return _proposal(name, {'font': font}, context, f'Change the caption font to {font} (if it is installed).')
    if name == 'translate_project':
        language = str(args.get('language') or '').strip().lower()[:8]
        if not language.isalpha():
            raise ValueError('Use a language code such as en, el or ko.')
        return _proposal(name, {'language': language}, context,
                         f'Run the translation job for all unlocked lines into "{language}". Results arrive for review.')
    if name == 'navigate':
        if args.get('target') not in NAV_TARGETS:
            raise ValueError('Unknown destination.')
        if context.get('unsaved'):
            raise ValueError('The page has unsaved edits. Save first; I will not navigate away.')
        return _proposal(name, {'target': args['target']}, context, f'Open {args["target"].replace("_", " ")}.')
    if name == 'download_url':
        url = str(args.get('url') or '').strip()
        if not url.lower().startswith(('http://', 'https://')):
            raise ValueError('Give a full http(s) link.')
        return _proposal(name, {'url': url, 'format': args.get('format') or 'video'}, context, f'Download {url}.')
    summaries = {
        'transcribe_project': 'Transcribe the project audio with the local speech model (replaces unsaved draft lines).',
        'sync_lyrics': 'Open lyric sync to time your pasted lyrics to the song.',
        'render_export': 'Export the project as an MP4 with the current style.',
        'generate_storyboard': 'Plan a storyboard with the AI Director from the song timings.',
        'generate_keyframe': 'Render a keyframe image locally with FLUX.',
        'animate_keyframe': 'Animate the scene keyframe locally with Wan.',
        'face_swap': 'Swap the active persona\'s face into the chosen video locally.',
        'lip_sync': 'Lip-sync the face video to the song locally with LatentSync.',
        'open_in_explorer': 'Open the folder in File Explorer.',
    }
    clean = {k: v for k, v in args.items() if isinstance(v, (str, int, float, bool))}
    return _proposal(name, clean, context, summaries[name])


def execute_tool(name, args, context, services):
    """Run one tool call. Returns ('result', data) for instant tools or ('proposal', card)."""
    if name not in TOOLS:
        raise ValueError(f'Unknown tool: {name}')
    args = args if isinstance(args, dict) else {}
    kind = TOOLS[name][2]
    if kind == 'proposal':
        return 'proposal', build_proposal(name, args, context)
    if name == 'list_capabilities':
        return 'result', capabilities(context.get('page'))
    if name == 'audit_subtitles':
        return 'result', audit_subtitles(context, args.get('focus') or 'all')
    if name == 'read_caption_lines':
        return 'result', read_caption_lines(context, args.get('start_line', 1), args.get('end_line'))
    if name == 'search_gallery':
        return 'result', search_gallery(services, args.get('query', ''), args.get('kind'), args.get('limit', 10))
    if name == 'describe_image':
        return 'result', describe_image(services, args.get('path', ''))
    return 'result', list_instagram_profile(str(args.get('url') or ''))


def dedupe_calls(calls):
    """One call per tool name per step; batch line fixes are merged instead of dropped."""
    merged = {}
    for call in calls:
        name, arguments = call['name'], dict(call.get('arguments') or {})
        if name == 'batch_fix_subtitles' and name in merged:
            merged[name]['arguments'].setdefault('updates', []).extend(arguments.get('updates') or [])
        else:
            merged[name] = {'name': name, 'arguments': arguments}
    return list(merged.values())


# ---------------------------------------------------------------- agent loop

def _history(messages):
    clean = []
    for message in (messages or [])[-MAX_HISTORY:]:
        if isinstance(message, dict) and message.get('role') in ('user', 'assistant') and isinstance(message.get('content'), str):
            clean.append({'role': message['role'], 'content': message['content'][:8000]})
    if not clean or clean[-1]['role'] != 'user':
        raise ValueError('Send a message first.')
    return clean


def run_agent(messages, context, services, *, model=None, emit=None):
    """Agent loop; ``emit(event, data)`` receives token/tool_call/tool_result/proposal events."""
    emit = emit or (lambda event, data: None)
    states = tool_states(context.get('page'))
    specs = tool_specs(states)
    conversation = [{'role': 'system', 'content': system_prompt(context, states)}, *_history(messages)]
    proposals, results, final, used_model, backend = {}, [], '', None, None
    for step in range(MAX_STEPS):
        answer = llm.chat('helper', conversation, tools=specs or None, model=model, max_tokens=1024,
                          on_token=lambda text: emit('token', {'text': text}))
        used_model, backend = answer['model'], answer['backend']
        calls = dedupe_calls(answer['tool_calls'])
        if not calls:
            final = answer['content']
            break
        conversation.append({'role': 'assistant', 'content': answer['content'],
                             'tool_calls': [{'function': {'name': c['name'], 'arguments': c['arguments']}} for c in calls]})
        for call in calls:
            emit('tool_call', {'name': call['name'], 'arguments': call['arguments'], 'step': step + 1})
            try:
                kind, data = execute_tool(call['name'], call['arguments'], context, services)
            except AIUnavailable as exc:
                kind, data = 'error', exc.to_dict()
            except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
                kind, data = 'error', {'error': str(exc)}
            if kind == 'proposal':
                proposals[call['name']] = data
                emit('proposal', data)
                feedback = {'status': 'proposed', 'summary': data['summary'], 'note': 'Not applied until the user presses Apply.'}
            else:
                results.append({'name': call['name'], 'kind': kind, 'data': data})
                emit('tool_result', {'name': call['name'], 'ok': kind == 'result', 'data': data})
                feedback = data
            conversation.append({'role': 'tool', 'tool_name': call['name'], 'name': call['name'],
                                 'content': json.dumps(feedback, ensure_ascii=False, default=str)[:TOOL_RESULT_CHARS]})
        final = answer['content']
    else:
        final = final or f'I stopped after {MAX_STEPS} steps without a final answer.'
    return {'reply': final, 'model': used_model, 'backend': backend, 'local': True,
            'proposals': list(proposals.values()), 'tool_results': results}


def sse(event, data):
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n'


# ---------------------------------------------------------------- routes

def register_copilot_routes(app, *, gallery, allowed_path):
    """``gallery()`` returns the gallery item list; ``allowed_path(path)`` is the library allow-list."""
    bp = Blueprint('copilot', __name__)
    services = {'gallery': gallery, 'allowed_path': allowed_path}

    def parse():
        data = request.get_json(silent=True)
        data = data if isinstance(data, dict) else {}
        context = normalize_context(data.get('context'), data.get('project'))
        model = data.get('model') if isinstance(data.get('model'), str) and data.get('model') else None
        return _history(data.get('messages')), context, model

    @bp.get('/api/copilot/models')
    def copilot_models():
        listed = [m for m in llm.available_models() if 'tools' in (m.get('capabilities') or []) or m['backend'] == 'builtin']
        return jsonify(models=listed, helper=llm.cost('helper'))

    @bp.get('/api/copilot/capabilities')
    def copilot_capabilities():
        return jsonify(capabilities(request.args.get('page')))

    @bp.post('/api/copilot/chat')
    def copilot_chat():
        try:
            messages, context, model = parse()
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        try:
            return jsonify(run_agent(messages, context, services, model=model))
        except AIUnavailable as exc:
            return jsonify(exc.to_dict()), 424

    @bp.post('/api/copilot/chat/stream')
    def copilot_stream():
        try:
            messages, context, model = parse()
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        events, cancel = queue.Queue(), threading.Event()
        flask_app = current_app._get_current_object()

        def worker():
            job_process.begin_job()
            try:
                with flask_app.app_context(), job_process.cancellation_scope(cancel.is_set):
                    result = run_agent(messages, context, services, model=model,
                                       emit=lambda event, data: events.put((event, data)))
                events.put(('done', result))
            except AIUnavailable as exc:
                events.put(('error', exc.to_dict()))
            except Exception as exc:  # shown verbatim in the drawer
                events.put(('error', {'error': str(exc) or exc.__class__.__name__, 'setup_hint': None}))
            finally:
                job_process.end_job()
                events.put((None, None))

        threading.Thread(target=worker, daemon=True, name='copilot-agent').start()

        def stream():
            try:
                while True:
                    event, data = events.get()
                    if event is None:
                        return
                    yield sse(event, data)
            finally:
                cancel.set()

        return Response(stream(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    app.register_blueprint(bp)
    return bp
