"""Local caption projects, validated subtitle data and non-destructive rendering."""
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import threading
import time
import uuid

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import ImageFont
from flask import Blueprint, jsonify, request, send_file, render_template, session
import job_process as process
from ai_runtime import transcribe

DEFAULT_STYLE = dict(font='Arial', size=5, color='#ffffff', highlight='#ffdc55',
                     outline=2, position=85, background=False, karaoke=False)
FONTS = {'Arial', 'Verdana', 'Georgia', 'Impact', 'Trebuchet MS'}


def number(value, low, high):
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Value must be between {low} and {high}.')
    return value


def validate_edit(data, duration):
    if not isinstance(data, dict):
        raise ValueError('Invalid project data.')
    cues = data.get('cues', [])
    if not isinstance(cues, list) or len(cues) > 5000:
        raise ValueError('Use at most 5,000 caption lines.')
    clean = []
    for cue in cues:
        if not isinstance(cue, dict) or not isinstance(cue.get('words', []), list):
            raise ValueError('Invalid caption data.')
        start, end = number(cue['start'], 0, duration), number(cue['end'], 0, duration)
        text = str(cue['text']).strip()
        if end <= start or not text or len(text) > 1000:
            raise ValueError('Each caption needs text and an end after its start (maximum 1,000 characters).')
        words = []
        previous = start
        for word in cue.get('words', []):
            a, b = number(word['start'], start, end), number(word['end'], start, end)
            t = str(word['text']).strip()
            if b <= a or a < previous or not t or len(t) > 100:
                raise ValueError('Word timings must be ordered and inside their caption.')
            previous = b
            words.append(dict(start=a, end=b, text=t))
        if words and ' '.join(w['text'] for w in words).split() != text.split():
            raise ValueError('Word timing text must match its caption. Rebuild word timings after editing text.')
        clean.append(dict(start=start, end=end, text=text, words=words))
    clean.sort(key=lambda c: c['start'])
    for left, right in zip(clean, clean[1:]):
        if left['end'] > right['start'] + .001:
            raise ValueError('Caption lines overlap. Adjust their times before saving.')
    style = {**DEFAULT_STYLE, **data.get('style', {})}
    if style['font'] not in FONTS:
        raise ValueError('Choose a supported font.')
    style = {k: style[k] for k in DEFAULT_STYLE}
    for k in ('color', 'highlight'):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(style[k])):
            raise ValueError('Invalid caption color.')
    style['size'] = number(style['size'], 2, 12)
    style['outline'] = number(style['outline'], 0, 5)
    style['position'] = number(style['position'], 10, 95)
    style['background'] = bool(style['background'])
    style['karaoke'] = bool(style['karaoke'])
    return dict(cues=clean, style=style)


def font_scale(name):
    """ASS sizes the font's ascender+descender; CSS sizes its em square."""
    files = {'Arial':'arial.ttf', 'Verdana':'verdana.ttf', 'Georgia':'georgia.ttf',
             'Impact':'impact.ttf', 'Trebuchet MS':'trebuc.ttf'}
    try:
        font = ImageFont.truetype(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / files[name]), 1000)
        return sum(font.getmetrics()) / 1000
    except (OSError, KeyError):
        return 1.0


def timestamp(seconds, ass=False):
    scale = 100 if ass else 1000
    ticks = round(seconds * scale)
    whole, fraction = divmod(ticks, scale)
    h, rest = divmod(whole, 3600)
    m, s = divmod(rest, 60)
    return f'{h:02}:{m:02}:{s:02}' + (f'.{fraction:02}' if ass else f',{fraction:03}')


def srt_text(cues):
    return '\n\n'.join(f"{i}\n{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}" for i, c in enumerate(cues, 1)) + '\n'


def ass_text(project):
    style = project['style']
    width, height = project['width'], project['height']
    def color(hexcolor):
        return '&H00' + hexcolor[5:7] + hexcolor[3:5] + hexcolor[1:3]
    def escape(text):
        # Fullwidth lookalikes prevent user text becoming ASS override commands.
        return text.replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\r', '').replace('\n', r'\N')
    font_size = height * style['size'] / 100 * font_scale(style['font'])
    outline = height * style['outline'] / 360
    output = [f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style['font']},{font_size},{color(style['color'])},{color(style['color'])},&H00000000,&H80000000,0,0,0,0,100,100,0,0,{3 if style['background'] else 1},{outline},0,2,{round(width*.06)},{round(width*.06)},0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text''']
    for cue in project['cues']:
        pieces = [(cue['start'], cue['end'], None)]
        if style['karaoke'] and cue['words']:
            boundaries = sorted({cue['start'], cue['end'], *(w[k] for w in cue['words'] for k in ('start', 'end'))})
            pieces = [(a, b, next((i for i, w in enumerate(cue['words']) if w['start'] <= (a+b)/2 < w['end']), None)) for a, b in zip(boundaries, boundaries[1:])]
        for start, end, active in pieces:
            if round(start*100) >= round(end*100):
                continue
            body = escape(' '.join(w['text'] for w in cue['words']) if style['karaoke'] and cue['words'] else cue['text'])
            if active is not None:
                body = ' '.join((r'{\c' + color(style['highlight']).replace('&H00', '&H') + '&}' + escape(w['text']) + r'{\r}') if i == active else escape(w['text']) for i, w in enumerate(cue['words']))
            position = r'{\pos(' + f'{width/2:.1f},{height*style["position"]/100:.1f}' + ')}'
            output.append(f"Dialogue: 0,{timestamp(start, True)},{timestamp(end, True)},Default,,0,0,0,,{position}{body}")
    return '\n'.join(output) + '\n'


def parse_subtitles(text, duration):
    text = text.lstrip('\ufeff').replace('\r', '')
    cues = []
    if '-->' in text:
        pattern = r'(\d+):(\d{2}):(\d{2})[,.](\d{3})'
        def seconds(match):
            h, m, s, ms = map(int, match)
            if m > 59 or s > 59:
                raise ValueError('Invalid subtitle timestamp.')
            return h*3600+m*60+s+ms/1000
        for block in re.split(r'\n\s*\n', text.strip()):
            lines = block.splitlines()
            index = next((i for i, line in enumerate(lines) if '-->' in line), -1)
            if index < 0:
                raise ValueError('An SRT block is missing its timestamp.')
            times = re.findall(pattern, lines[index])
            if len(times) != 2:
                raise ValueError('Could not read the SRT timestamps.')
            cues.append(dict(start=seconds(times[0]), end=seconds(times[1]), text='\n'.join(lines[index+1:]), words=[]))
    else:
        entries = []
        for line in text.splitlines():
            tags = re.findall(r'\[(\d+):(\d{2})(?:[.](\d{1,3}))?\]', line)
            content = re.sub(r'\[[^]]*\]', '', line).strip()
            for m, s, f in tags:
                if int(s) > 59:
                    raise ValueError('Invalid lyric timestamp.')
                entries.append((int(m)*60+int(s)+float('0.'+(f or '0')), content))
        entries.sort()
        for i, (start, content) in enumerate(entries):
            end = entries[i+1][0] if i+1 < len(entries) else duration
            if content:
                cues.append(dict(start=start, end=end, text=content, words=[]))
    if not cues:
        raise ValueError('No timed captions found. Import SRT or LRC, or use Paste lyrics.')
    return validate_edit(dict(cues=cues), duration)['cues']


def register_captions(app, save_dir, job_started, job_finished, refresh_gallery, get_whisper, allowed_path):
    bp = Blueprint('captions', __name__)
    root = Path(save_dir) / 'Caption Projects'
    lock = threading.RLock()

    def folder(pid):
        if not re.fullmatch(r'[a-f0-9]{32}', pid):
            raise ValueError('Invalid project ID.')
        return root / pid

    def read(pid):
        with lock:
            return json.loads((folder(pid) / 'project.json').read_text(encoding='utf-8'))

    def write(data):
        with lock:
            destination = folder(data['id']) / 'project.json'
            temporary = destination.with_suffix('.tmp')
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            # Antivirus/indexers can briefly hold Windows files without delete sharing.
            for attempt in range(6):
                try:
                    os.replace(temporary, destination)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(.05 * (attempt + 1))

    def ffmpeg(args, cwd):
        result = process.run([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-y', *args], cwd=cwd, capture_output=True)
        if result.returncode:
            raise ValueError('Video processing failed: ' + result.stderr.decode('utf-8', errors='replace')[-700:])

    def launch(data, action, work):
        with lock:
            data['state'], data['status'] = 'busy', action
            write(data)
            job_started()
        def run():
            process.begin_job()
            try:
                work(data, folder(data['id']))
                process.check_cancelled()
                data['state'], data['status'] = 'ready', 'Ready'
                data['revision'] += 1
                refresh_gallery()
            except Exception as exc:
                data['state'], data['status'] = 'error', str(exc)
            finally:
                try:
                    write(data)
                finally:
                    process.end_job()
                    job_finished()
        threading.Thread(target=run, daemon=True).start()
        return jsonify(data), 202

    @bp.errorhandler(ValueError)
    @bp.errorhandler(KeyError)
    @bp.errorhandler(TypeError)
    def bad_request(exc):
        return jsonify(error=str(exc)), 400

    @bp.errorhandler(FileNotFoundError)
    def missing(exc):
        return jsonify(error='Caption project or media not found.'), 404

    @bp.get('/captions')
    def editor():
        if not session.get('authorized'):
            return 'Open Captions & Lyrics from the app first.', 403
        return render_template('captions.html', api_token=session['api_token'])

    @bp.get('/api/captions')
    def projects():
        result = []
        with lock:
            for path in root.glob('*/project.json'):
                try:
                    d = json.loads(path.read_text(encoding='utf-8'))
                    result.append(dict(id=d['id'], name=d['name']))
                except (OSError, ValueError, KeyError):
                    pass
        return jsonify(result)

    @bp.post('/api/captions')
    def create():
        pid = uuid.uuid4().hex
        destination = folder(pid)
        upload = request.files.get('video')
        path = request.form.get('path', '')
        source = Path(path) if path else None
        if not upload and (not source or not allowed_path(str(source)) or not source.is_file()):
            raise ValueError('Choose a video from your library or upload one.')
        name = upload.filename if upload else source.name
        extension = Path(name).suffix.lower()
        if extension not in {'.mp4', '.mkv', '.mov', '.webm', '.avi', '.m4v'}:
            raise ValueError('Choose a supported video file.')
        destination.mkdir(parents=True)
        media = destination / ('original' + extension)
        if upload:
            upload.save(media)
        else:
            shutil.copy2(source, media)
        data = dict(id=pid, name=name[:200], source=media.name, state='busy', status='Preparing video',
                    revision=0, cues=[], style=dict(DEFAULT_STYLE), width=0, height=0, duration=0, peaks=[], timing='manual', exports=[])
        def prepare(d, f):
            capture = cv2.VideoCapture(str(media))
            try:
                fps = capture.get(cv2.CAP_PROP_FPS)
                d['width'], d['height'] = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                d['duration'] = capture.get(cv2.CAP_PROP_FRAME_COUNT) / fps if fps else 0
            finally:
                capture.release()
            number(d['duration'], .1, 7200)
            if min(d['width'], d['height']) < 2 or max(d['width'], d['height']) > 8192:
                raise ValueError('Could not read video dimensions (maximum 8192 pixels).')
            ffmpeg(['-i', media.name, '-map', '0:v:0', '-map', '0:a:0?', '-vf', "scale=w='min(720,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2", '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', 'preview.mp4'], f)
            result = process.run([imageio_ffmpeg.get_ffmpeg_exe(), '-i', str(media), '-vn', '-ac', '1', '-ar', '1000', '-f', 'f32le', '-'], capture_output=True)
            if result.returncode == 0 and result.stdout:
                values = np.frombuffer(result.stdout, dtype='<f4')
                d['peaks'] = [round(float(np.max(np.abs(chunk))), 4) for chunk in np.array_split(values, min(4000, len(values))) if len(chunk)]
        return launch(data, 'Preparing preview and waveform…', prepare)

    @bp.get('/api/captions/<pid>')
    def project(pid):
        return jsonify(read(pid))

    @bp.put('/api/captions/<pid>')
    def save(pid):
        incoming = request.get_json()
        with lock:
            data = read(pid)
            if data['state'] == 'busy' or incoming.get('revision') != data['revision']:
                return jsonify(error='Project changed or is processing. Reload it before saving.'), 409
            data.update(validate_edit(incoming, data['duration']))
            data['revision'] += 1
            data['timing'] = incoming.get('timing', 'edited')
            if data['timing'] not in {'manual', 'estimated', 'automatic', 'imported', 'edited'}:
                data['timing'] = 'edited'
            write(data)
        return jsonify(data)

    @bp.post('/api/captions/<pid>/import')
    def import_file(pid):
        data = read(pid)
        text = request.get_json().get('text', '')
        if len(text) > 2_000_000:
            raise ValueError('Subtitle file is too large.')
        return jsonify(cues=parse_subtitles(text, data['duration']))

    @bp.post('/api/captions/<pid>/transcribe')
    def recognize(pid):
        with lock:
            data = read(pid)
            if data['state'] == 'busy':
                return jsonify(error='Wait for the current task.'), 409
            language = request.get_json().get('language', '').strip()
            if language and not re.fullmatch(r'[a-z]{2,3}', language):
                raise ValueError('Use a language code such as en or el, or leave Auto selected.')
            def work(d, f):
                ffmpeg(['-i', d['source'], '-vn', '-ac', '1', '-ar', '16000', 'speech.wav'], f)
                try:
                    model = get_whisper()
                    if model is None:
                        raise ValueError('Install the AI Pack in the main app to enable transcription. Manual editing and import work without it.')
                    result = transcribe(model, str(f / 'speech.wav'), word_timestamps=True, language=language or None)
                    cues = []
                    for segment in result.get('segments', []):
                        start = max(0, float(segment['start']))
                        end = min(d['duration'], float(segment['end']))
                        if cues:
                            start = max(start, cues[-1]['end'])
                        text = segment['text'].strip()
                        if end <= start or not text:
                            continue
                        words = []
                        previous = start
                        for w in segment.get('words', []):
                            a, b = max(previous, float(w['start'])), min(end, float(w['end']))
                            if b > a and w['word'].strip():
                                words.append(dict(start=a, end=b, text=w['word'].strip()))
                                previous = b
                        if ' '.join(w['text'] for w in words).split() != text.split():
                            words = []
                        cues.append(dict(start=start, end=end, text=text, words=words))
                    if not cues:
                        raise ValueError('No speech detected. Paste lyrics or import subtitles instead.')
                    d.update(validate_edit(dict(cues=cues, style=d['style']), d['duration']))
                    d['timing'] = 'automatic'
                finally:
                    (f / 'speech.wav').unlink(missing_ok=True)
            return launch(data, 'Transcribing audio (existing captions are kept if this fails)…', work)

    @bp.post('/api/captions/<pid>/render')
    def render(pid):
        with lock:
            data = read(pid)
            options = request.get_json()
            if data['state'] == 'busy':
                return jsonify(error='Wait for the current task.'), 409
            if not data['cues']:
                raise ValueError('Add and save captions before rendering.')
            start = number(options.get('start', 0), 0, data['duration'])
            preview = bool(options.get('preview'))
            def work(d, f):
                token = uuid.uuid4().hex[:12]
                ass = f / (token + '.ass')
                output = ('check_' if preview else 'captioned_') + token + '.mp4'
                temporary = f / ('.working_' + output)
                ass.write_text(ass_text(d), encoding='utf-8-sig')
                try:
                    args = ['-i', d['source'], '-map', '0:v:0', '-map', '0:a:0?', '-vf', f'ass={ass.name},scale=trunc(iw/2)*2:trunc(ih/2)*2']
                    if preview:
                        args += ['-ss', str(start), '-t', str(min(5, d['duration']-start))]
                    ffmpeg([*args, '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', temporary.name], f)
                    os.replace(temporary, f / output)
                    d['exports'].append(output)
                    d['last_render'] = output
                finally:
                    ass.unlink(missing_ok=True)
                    temporary.unlink(missing_ok=True)
            return launch(data, 'Rendering five-second check…' if preview else 'Exporting captioned video…', work)

    @bp.get('/api/captions/<pid>/srt')
    def export_srt(pid):
        data = read(pid)
        return send_file(io.BytesIO(srt_text(data['cues']).encode('utf-8-sig')), mimetype='application/x-subrip', as_attachment=True, download_name='captions.srt')

    @bp.get('/api/captions/<pid>/media/<name>')
    def media(pid, name):
        data = read(pid)
        if name not in ['preview.mp4', *data.get('exports', [])]:
            return jsonify(error='Media not available.'), 404
        return send_file(folder(pid) / name, conditional=True, as_attachment=request.args.get('download') == '1')

    # A stopped process cannot resume its background thread after app restart.
    for path in root.glob('*/project.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('state') == 'busy':
                data.update(state='error', status='Processing was interrupted. Saved captions are available; retry the operation.')
                write(data)
        except (OSError, ValueError):
            pass
    app.register_blueprint(bp)
