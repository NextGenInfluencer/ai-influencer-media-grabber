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
import wave

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import ImageFont
from flask import Blueprint, jsonify, request, send_file, render_template, session
import job_process as process
from ai_runtime import transcribe, align_lyrics

DEFAULT_STYLE = dict(font='Arial', size=5, color='#ffffff', highlight='#ffdc55',
                     outline=2, position=85, background=False, karaoke=False)
FONTS = {'Arial', 'Verdana', 'Georgia', 'Impact', 'Trebuchet MS'}
BUNDLED_FONTS = {'Oswald': 'Oswald[wght].ttf', 'Lobster': 'Lobster-Regular.ttf', 'Bangers': 'Bangers-Regular.ttf'}
FONTS.update(BUNDLED_FONTS)
FONT_DIR = Path(__file__).resolve().parent / 'static' / 'fonts'


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
        path = FONT_DIR / BUNDLED_FONTS[name] if name in BUNDLED_FONTS else Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / files[name]
        font = ImageFont.truetype(str(path), 1000)
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


def lyric_lines(text):
    if not isinstance(text, str) or len(text) > 50000:
        raise ValueError('Use at most 50,000 characters of lyrics.')
    # Suno exports often include unspoken section labels.
    lines = [line.strip() for line in text.splitlines() if line.strip()
             and not re.fullmatch(r'\s*\[[^\]\n]+\]\s*', line)]
    if not lines or len(lines) > 1000 or any(len(line) > 1000 for line in lines):
        raise ValueError('Paste 1–1,000 lyric lines, with at most 1,000 characters per line.')
    if any(len(word) > 100 for line in lines for word in line.split()):
        raise ValueError('Each lyric word must be at most 100 characters.')
    return lines


def aligned_cues(result, lines, offset, duration, limit):
    """Rejoin token fragments while preserving supplied spelling and line breaks."""
    pieces = [w for s in result.get('segments', []) for w in s.get('words', [])
              if str(w.get('word', '')).strip()]
    expected = ''.join(''.join(line.split()) for line in lines)
    if ''.join(''.join(str(w['word']).split()) for w in pieces) != expected:
        raise ValueError('Some lyrics could not be aligned. Check that the pasted words match this audio range.')
    spans, cursor = [], 0
    previous = 0
    for piece in pieces:
        a = number(piece['start'], 0, limit)
        b = number(piece['end'], 0, limit)
        if b <= a or a < previous - .001:
            raise ValueError('Some words have uncertain timing. Try a shorter audio range with only its matching lyrics.')
        a = max(a, previous)
        previous = b
        length = len(''.join(piece['word'].split()))
        spans.append((cursor, cursor + length, a + offset, b + offset))
        cursor += length
    cues, cursor, index = [], 0, 0
    for line in lines:
        words = []
        for text in line.split():
            end = cursor + len(text)
            while index < len(spans) and spans[index][1] <= cursor:
                index += 1
            matches = []
            j = index
            while j < len(spans) and spans[j][0] < end:
                matches.append(spans[j])
                j += 1
            if not matches:
                raise ValueError('Missing word timings. Try a shorter section.')
            words.append(dict(text=text, start=matches[0][2], end=matches[-1][3]))
            cursor = end
        cues.append(dict(text=line, start=words[0]['start'], end=words[-1]['end'], words=words))
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
        song = request.files.get('audio')
        path = request.form.get('path', '')
        source = Path(path) if path else None
        if not song and not upload and (not source or not allowed_path(str(source)) or not source.is_file()):
            raise ValueError('Choose a video from your library or upload one.')
        name = song.filename if song else upload.filename if upload else source.name
        extension = Path(name).suffix.lower()
        if song and extension not in {'.mp3', '.wav', '.m4a', '.flac', '.ogg'}:
            raise ValueError('Choose MP3, WAV, M4A, FLAC or OGG audio.')
        if not song and extension not in {'.mp4', '.mkv', '.mov', '.webm', '.avi', '.m4v'}:
            raise ValueError('Choose a supported video file.')
        composition = None
        if song:
            shapes = {'portrait': (1080,1920), 'square': (1080,1080), 'landscape': (1920,1080)}
            shape = request.form.get('shape', 'portrait')
            if shape not in shapes:
                raise ValueError('Choose portrait, square or landscape.')
            color = request.form.get('color', '#141526')
            if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
                raise ValueError('Choose a valid background color.')
            background = request.files.get('background')
            bg_path = request.form.get('background_path', '')
            if bg_path and (not allowed_path(bg_path) or not Path(bg_path).is_file()):
                raise ValueError('Choose a background from your library.')
            bg_ext = Path(background.filename if background else bg_path).suffix.lower()
            if (background or bg_path) and bg_ext not in {'.png','.jpg','.jpeg','.webp','.mp4','.mov','.mkv','.webm'}:
                raise ValueError('Choose a photo or video background.')
            composition = dict(shape=shape, color=color, visualizer=request.form.get('visualizer') == 'true')
        destination.mkdir(parents=True)
        media = destination / ('original.mp4' if song else 'original' + extension)
        if song:
            song_file = destination / ('song' + extension)
            song.save(song_file)
            bg_file = destination / ('background' + bg_ext) if background or bg_path else None
            if background:
                background.save(bg_file)
            elif bg_path:
                shutil.copy2(bg_path, bg_file)
        elif upload:
            upload.save(media)
        else:
            shutil.copy2(source, media)
        data = dict(id=pid, name=name[:200], source=media.name, state='busy', status='Preparing video',
                    revision=0, cues=[], style=dict(DEFAULT_STYLE), width=0, height=0, duration=0, peaks=[], timing='manual', exports=[])
        def prepare(d, f):
            if song:
                # Decode a bounded audio file first: arbitrary metadata durations cannot create runaway renders.
                ffmpeg(['-i', song_file.name, '-t', '1200.1', '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', 'duration.wav'], f)
                try:
                    with wave.open(str(f / 'duration.wav'), 'rb') as audio:
                        seconds = audio.getnframes() / audio.getframerate()
                    number(seconds, .1, 1200)
                finally:
                    (f / 'duration.wav').unlink(missing_ok=True)
                width, height = shapes[shape]
                args = ['-i', song_file.name]
                if bg_file:
                    args += (['-loop','1'] if bg_ext in {'.png','.jpg','.jpeg','.webp'} else ['-stream_loop','-1']) + ['-i',bg_file.name]
                else:
                    args += ['-f','lavfi','-i',f'color=c={color}:s={width}x{height}:r=30']
                graph = f'[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps=30[bg]'
                if composition['visualizer']:
                    graph += f';[0:a]showwaves=s={width}x{height//5}:mode=cline:rate=30:colors=0xbba6ff:scale=sqrt[wave];[bg][wave]overlay=0:H-h:shortest=1[out]'
                else:
                    graph += ';[bg]null[out]'
                ffmpeg([*args,'-filter_complex',graph,'-map','[out]','-map','0:a:0','-t',str(seconds),'-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','256k','-movflags','+faststart',media.name], f)
                d['composition'] = composition
                d['style']['position'] = 65
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
            if data['timing'] not in {'manual', 'estimated', 'automatic', 'aligned', 'imported', 'edited'}:
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

    @bp.post('/api/captions/<pid>/align')
    def align(pid):
        with lock:
            data = read(pid)
            if data['state'] == 'busy':
                return jsonify(error='Wait for the current task.'), 409
            options = request.get_json()
            lines = lyric_lines(options.get('text', ''))
            language = options.get('language', '')
            if language not in {'en', 'el', 'es', 'fr', 'de'}:
                raise ValueError('Choose the lyric language: English, Greek, Spanish, French or German.')
            start = number(options.get('start', 0), 0, data['duration'])
            end = number(options.get('end', data['duration']), 0, data['duration'])
            if end - start < .1 or end - start > 1200:
                raise ValueError('Select an audio range between 0.1 seconds and 20 minutes.')
            def work(d, f):
                audio_file = f / 'alignment.wav'
                try:
                    ffmpeg(['-ss', str(start), '-i', d['source'], '-t', str(end-start),
                            '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', audio_file.name], f)
                    model = get_whisper()
                    if model is None:
                        raise ValueError('Install the AI Pack in the Studio to enable lyric timing.')
                    with wave.open(str(audio_file), 'rb') as audio:
                        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2').astype(np.float32) / 32768
                    if not samples.size or np.max(np.abs(samples)) < .0001:
                        raise ValueError('The selected audio range is silent. Choose a range with vocals.')
                    result = align_lyrics(model, samples, '\n'.join(lines), language)
                    cues = aligned_cues(result, lines, start, d['duration'], end-start)
                    process.check_cancelled()
                    d.update(cues=cues, timing='aligned')
                finally:
                    audio_file.unlink(missing_ok=True)
            return launch(data, 'Matching your lyrics to the audio (existing captions are kept if this fails)…', work)

    @bp.post('/api/captions/<pid>/render')
    def render(pid):
        with lock:
            data = read(pid)
            options = request.get_json()
            if data['state'] == 'busy':
                return jsonify(error='Wait for the current task.'), 409
            if not data['cues'] and not data.get('composition'):
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
                    fonts = f / 'caption_fonts'
                    fonts.mkdir(exist_ok=True)
                    for filename in BUNDLED_FONTS.values():
                        shutil.copy2(FONT_DIR / filename, fonts / filename)
                    args = ['-i', d['source'], '-map', '0:v:0', '-map', '0:a:0?', '-vf', f'ass={ass.name}:fontsdir=caption_fonts,scale=trunc(iw/2)*2:trunc(ih/2)*2']
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
