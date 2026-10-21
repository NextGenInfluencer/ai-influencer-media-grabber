"""Local caption projects, validated subtitle data and non-destructive rendering."""
import io
import copy
import json
import math
import os
from pathlib import Path
import re
import shutil
import threading
import time
import urllib.parse
import uuid
import wave
from typing import Any

import unicodedata
from difflib import SequenceMatcher

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import ImageFont
from flask import Blueprint, jsonify, request, send_file, render_template, session
import job_process as process
from ai_runtime import transcribe, align_lyrics, align_caption_words, detect_caption_language
import creator_composition as composition_model

DEFAULT_STYLE = dict(font='Arial', size=5, color='#ffffff', highlight='#ffdc55',
                     outline=2, position=85, background=False, karaoke=False,
                     cumulative=False, word_pop=False,
                     visualizer=False, visualizer_style='spectrum', visualizer_position='bottom',
                     visualizer_height=18, visualizer_sensitivity=1, visualizer_color='#bba6ff')
FONTS = {'Arial', 'Verdana', 'Georgia', 'Impact', 'Trebuchet MS'}
BUNDLED_FONTS = {
    'Oswald': 'Oswald[wght].ttf',
    'Lobster': 'Lobster-Regular.ttf',
    'Bangers': 'Bangers-Regular.ttf',
    'Montserrat': 'Montserrat[wght].ttf',
    'Roboto': 'Roboto[wdth,wght].ttf',
    'Noto Sans KR': 'NotoSansKR[wght].ttf',
}
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
        item: dict[str, Any] = dict(start=start, end=end, text=text, words=words)
        if isinstance(cue.get('karaoke'), dict):
            info = cue['karaoke']
            state = info.get('state')
            if state in {'aligned', 'review', 'estimated', 'edited', 'checked'}:
                item['karaoke'] = dict(state=state, note=str(info.get('note', ''))[:300],
                                       language=str(info.get('language', ''))[:3])
        clean.append(item)
    clean.sort(key=lambda c: c['start'])
    for left, right in zip(clean, clean[1:]):
        if left['end'] > right['start'] + .001:
            raise ValueError('Caption lines overlap. Adjust their times before saving.')
    style = {**DEFAULT_STYLE, **data.get('style', {})}
    if style['font'] not in FONTS:
        raise ValueError('Choose a supported font.')
    style = {k: style[k] for k in DEFAULT_STYLE}
    for k in ('color', 'highlight', 'visualizer_color'):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(style[k])):
            raise ValueError('Invalid caption color.')
    if style['visualizer_style'] not in {'waveform', 'spectrum'} or style['visualizer_position'] not in {'bottom', 'center', 'top'}:
        raise ValueError('Choose a supported visualizer style and position.')
    style['size'] = number(style['size'], 2, 12)
    style['outline'] = number(style['outline'], 0, 5)
    style['position'] = number(style['position'], 10, 95)
    style['visualizer_height'] = number(style['visualizer_height'], 10, 40)
    style['visualizer_sensitivity'] = number(style['visualizer_sensitivity'], .5, 3)
    style['background'] = bool(style['background'])
    style['karaoke'] = bool(style['karaoke'])
    style['cumulative'] = bool(style['cumulative'])
    style['word_pop'] = bool(style['word_pop'])
    style['visualizer'] = bool(style['visualizer'])
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


def visualizer_bars(peaks, duration, time_sec, width, height, style):
    """Compute deterministic audio-reactive visualizer bar rectangles (x1, y1, x2, y2).
    Uses identical visual math to static/captions.js CaptionTiming.visualizerBars().
    """
    def rint(val):
        return int(math.floor(val + 0.5))
    mode = style.get('visualizer_style', 'spectrum')
    pos = style.get('visualizer_position', 'bottom')
    vis_h = float(style.get('visualizer_height', 18))
    sens = float(style.get('visualizer_sensitivity', 1.0))
    count = 36 if mode == 'spectrum' else 48

    pts = peaks if (isinstance(peaks, list) and len(peaks) > 0) else [0.25] * 64
    n = len(pts)
    max_p = max(0.01, max(float(p) for p in pts))
    dur = max(0.1, float(duration or 1.0))
    t = max(0.0, min(dur, float(time_sec)))
    center = (t / dur) * (n - 1)

    band_h = height * (vis_h / 100.0)
    start_x = width * 0.06
    usable_w = width * 0.88
    step_x = usable_w / count
    bar_w = max(2.0, step_x * (0.65 if mode == 'spectrum' else 0.75))

    rects = []
    for i in range(count):
        if mode == 'spectrum':
            idx0 = max(0, min(n - 1, rint(center)))
            idx1 = max(0, min(n - 1, rint(center + (i - count / 2.0) * 0.5)))
            idx2 = max(0, min(n - 1, rint(center + ((i % 7) - 3) * 1.5)))
            p0 = float(pts[idx0]) / max_p
            p1 = float(pts[idx1]) / max_p
            p2 = float(pts[idx2]) / max_p
            u = i / max(1, count - 1)
            arch = 0.55 + 0.45 * math.sin(u * math.pi)
            ripple = 0.72 + 0.28 * math.sin(t * (7.0 + (i % 5) * 1.3) + i * 0.65)
            raw = (0.5 * p0 + 0.3 * p1 + 0.2 * p2) * arch * ripple * sens
            level = 0.04 if p0 < 0.005 else min(1.0, max(0.04, math.sqrt(max(0.0, raw))))
        else:
            span = max(8.0, n * 0.04)
            offset = ((i / max(1, count - 1)) - 0.5) * span
            idx = max(0, min(n - 1, rint(center + offset)))
            p = float(pts[idx]) / max_p
            wave_mod = 0.8 + 0.2 * math.cos(t * 8.0 + i * 0.4)
            raw = p * wave_mod * sens
            level = 0.04 if p < 0.005 else min(1.0, max(0.04, math.sqrt(max(0.0, raw))))

        bh = max(2.0, level * band_h)
        x1 = rint(start_x + i * step_x)
        x2 = rint(x1 + bar_w)
        if mode == 'waveform' or pos == 'center':
            mid_y = (height - band_h * 0.5 - height * 0.02) if pos == 'bottom' else (band_h * 0.5 + height * 0.02) if pos == 'top' else (height * 0.5)
            y1 = rint(mid_y - bh * 0.5)
            y2 = rint(mid_y + bh * 0.5)
        elif pos == 'top':
            y1 = 0
            y2 = rint(bh)
        else:
            y1 = rint(height - bh)
            y2 = rint(height)
        rects.append((x1, y1, x2, y2))
    return rects


def ass_text(project):
    style = {**DEFAULT_STYLE, **project.get('style', {})}
    width, height = project['width'], project['height']
    def color(hexcolor, alpha='00'):
        return f'&H{alpha}' + hexcolor[5:7] + hexcolor[3:5] + hexcolor[1:3]
    def escape(text):
        # Fullwidth lookalikes prevent user text becoming ASS override commands.
        return text.replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\r', '').replace('\n', r'\N')
    font_size = height * style['size'] / 100 * font_scale(style['font'])
    outline = height * style['outline'] / 360
    border_style = 3 if style['background'] else 1
    box_outline = max(outline, height * 0.012) if style['background'] else outline
    outline_col = '&H38140C0A' if style['background'] else '&H00000000'
    vis_col = color(style.get('visualizer_color', '#bba6ff'), '28')
    output = [f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style['font']},{font_size},{color(style['color'])},{color(style['color'])},{outline_col},&H80000000,0,0,0,0,100,100,0,0,{border_style},{box_outline},0,2,{round(width*.06)},{round(width*.06)},0,1
Style: Vis,Arial,20,{vis_col},{vis_col},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text''']
    if style.get('visualizer'):
        dur = float(project.get('duration') or (project['cues'][-1]['end'] if project.get('cues') else 0))
        if dur > 0:
            fps = 15
            steps = max(1, int(math.ceil(dur * fps)))
            peaks = project.get('peaks', [])
            for step in range(steps):
                t0 = step / fps
                t1 = min(dur, (step + 1) / fps)
                if round(t0 * 100) >= round(t1 * 100):
                    continue
                rects = visualizer_bars(peaks, dur, (t0 + t1) / 2, width, height, style)
                drawing = ' '.join(f'm {x1} {y1} l {x2} {y1} {x2} {y2} {x1} {y2}' for x1, y1, x2, y2 in rects)
                output.append(f"Dialogue: -1,{timestamp(t0, True)},{timestamp(t1, True)},Vis,,0,0,0,,{{\\pos(0,0)\\p1}}{drawing}{{\\p0}}")
    studio_settings = (project.get('studio') or {}).get('settings') or project.get('composition') or {}
    title_text = str(studio_settings.get('title_text') or '').strip()
    title_dur = float(studio_settings.get('title_duration') or 0)
    if title_text and title_dur > 0:
        t_end = min(float(project.get('duration') or title_dur), title_dur)
        if round(t_end * 100) > 0:
            title_size = round(font_size * 1.25, 1)
            output.append(f"Dialogue: 1,{timestamp(0, True)},{timestamp(t_end, True)},Default,,0,0,0,,{{\\an5\\pos({width/2:.0f},{height*.28:.0f})\\fs{title_size}\\fad(250,350)}}{escape(title_text)}")
    for cue in project['cues']:
        use_words = bool((style.get('karaoke') or style.get('cumulative') or style.get('word_pop')) and cue['words'])
        pieces = [(cue['start'], cue['end'], None)]
        if use_words:
            boundaries = sorted({cue['start'], cue['end'], *(w[k] for w in cue['words'] for k in ('start', 'end'))})
            pieces = [(a, b, next((i for i, w in enumerate(cue['words']) if w['start'] <= (a+b)/2 < w['end']), None)) for a, b in zip(boundaries, boundaries[1:])]
        for start, end, active in pieces:
            if round(start*100) >= round(end*100):
                continue
            body = escape(cue['text'])
            if use_words:
                mid = (start + end) / 2
                separators = re.findall(r'\s+', cue['text'])
                hl = color(style['highlight']).replace('&H00', '&H')
                parts = []
                for i, w in enumerate(cue['words']):
                    sep = escape(separators[i-1]) if i else ''
                    is_active = (i == active)
                    is_lit = (w['start'] <= mid) if style.get('cumulative') else (is_active and bool(style.get('karaoke')))
                    is_pop = is_active and bool(style.get('word_pop'))
                    w_esc = escape(w['text'])
                    if is_lit and is_pop:
                        parts.append(sep + r'{\c' + hl + r'&\fscx115\fscy115}' + w_esc + r'{\r}')
                    elif is_lit:
                        parts.append(sep + r'{\c' + hl + '&}' + w_esc + r'{\r}')
                    elif is_pop:
                        parts.append(sep + r'{\fscx115\fscy115}' + w_esc + r'{\r}')
                    else:
                        parts.append(sep + w_esc)
                body = ''.join(parts)
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


def aligned_cues(result, lines, offset, duration, limit, recover=False):
    """Rejoin token fragments while preserving supplied spelling and line breaks."""
    pieces = [w for s in result.get('segments', []) for w in s.get('words', [])
              if str(w.get('word', '')).strip()]
    expected = ''.join(''.join(line.split()) for line in lines)
    actual = ''.join(''.join(str(w['word']).split()) for w in pieces)
    if unicodedata.normalize('NFC', actual) != unicodedata.normalize('NFC', expected):
        raise ValueError('Some lyrics could not be aligned. Check that the pasted words match this audio range.')
    repaired = set()
    if recover:
        # Retain valid anchors. Only uncertain runs are estimated between anchors,
        # and any line touching those runs is explicitly flagged for listening review.
        pieces = copy.deepcopy(pieces)
        anchors, pending = [], []
        previous = 0.0
        a: float = 0.0
        b: float = 0.0
        for i, piece in enumerate(pieces):
            try:
                raw_s = float(piece.get('start', 0))
                raw_e = float(piece.get('end', 0))
                a = max(0.0, min(limit, raw_s))
                b = max(0.0, min(limit, raw_e))
                valid = b > a and a >= previous and (not pending or a - previous >= .01 * len(pending))
            except (ValueError, TypeError, KeyError):
                valid = False
            if not valid:
                pending.append(i)
                continue
            if pending:
                step = (a - previous) / len(pending)
                for n, index in enumerate(pending):
                    pieces[index].update(start=previous + n * step, end=previous + (n + 1) * step)
                    repaired.add(index)
                pending = []
            anchors.append(i)
            previous = b
        if pending:
            while anchors and limit - previous < .01 * len(pending):
                index = anchors.pop()
                pending = list(range(index, len(pieces)))
                previous = pieces[index]['start']
            if not anchors or limit - previous < .01 * len(pending):
                raise ValueError('Too few reliable timing anchors. Try syncing a shorter section; your saved captions were kept.')
            step = (limit - previous) / len(pending)
            for n, index in enumerate(pending):
                pieces[index].update(start=previous + n * step, end=limit if n == len(pending) - 1 else previous + (n + 1) * step)
                repaired.add(index)
        if not anchors:
            raise ValueError('No reliable lyric timing was found. Try a shorter section; your saved captions were kept.')
    spans, cursor = [], 0
    previous = 0.0
    for piece_index, piece in enumerate(pieces):
        raw_s = float(piece.get('start', 0))
        raw_e = float(piece.get('end', 0))
        a = max(0.0, min(limit, raw_s))
        b = max(0.0, min(limit, raw_e))
        if b <= a or a < previous - .001:
            if recover:
                a = max(a, previous)
                b = max(a + .01, b)
                repaired.add(piece_index)
            else:
                raise ValueError('Some words have uncertain timing. Try a shorter audio range with only its matching lyrics.')
        a = max(a, previous)
        previous = b
        length = len(''.join(piece['word'].split()))
        spans.append((cursor, cursor + length, a + offset, b + offset, piece_index in repaired))
        cursor += length
    cues, cursor, index = [], 0, 0
    for line in lines:
        words = []
        estimated = False
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
            estimated = estimated or any(span[4] for span in matches)
            words.append(dict(text=text, start=matches[0][2], end=matches[-1][3]))
            cursor = end
        prev_w = words[0]['start']
        for w in words:
            if w['start'] < prev_w:
                w['start'] = prev_w
            if w['end'] <= w['start']:
                w['end'] = w['start'] + 0.01
            prev_w = w['end']
        cue = dict(text=line, start=words[0]['start'], end=words[-1]['end'], words=words)
        if estimated:
            cue['karaoke'] = dict(state='review', note='Some uncertain word timings were estimated between audio anchors. Listen and adjust or retry this line.')
        cues.append(cue)
    for k in range(len(cues) - 1):
        if cues[k]['end'] > cues[k+1]['start']:
            cues[k]['end'] = cues[k+1]['start']
            if cues[k]['words'] and cues[k]['words'][-1]['end'] > cues[k]['end']:
                cues[k]['words'][-1]['end'] = cues[k]['end']
    return validate_edit(dict(cues=cues), duration)['cues']


def normalize_lyric_text(text):
    """Normalize text for cross-script, multilingual phonetic matching."""
    text = unicodedata.normalize('NFD', str(text).lower())
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = unicodedata.normalize('NFC', text)
    text = re.sub(r'[^\w\s]', '', text)
    return ' '.join(text.split())


def distribute_words_in_cue(words_text: list[str], cue_start: float, cue_end: float) -> list[dict[str, Any]]:
    if not words_text:
        return []
    n = len(words_text)
    cue_start = round(cue_start, 3)
    cue_end = round(cue_end, 3)
    if cue_end <= cue_start:
        cue_end = round(cue_start + max(0.05, 0.005 * n), 3)
    total = cue_end - cue_start

    char_lens = [max(1, len(w)) for w in words_text]
    total_chars = sum(char_lens)

    words = []
    curr = cue_start
    for i, (wt, clen) in enumerate(zip(words_text, char_lens)):
        if i == n - 1:
            w_start = curr
            w_end = cue_end
        else:
            fraction = clen / total_chars
            w_start = curr
            rem_words = n - 1 - i
            max_end = cue_end - (rem_words * 0.001)
            raw_end = curr + fraction * total
            w_end = min(max_end, max(w_start + 0.001, raw_end))
            w_end = round(w_end, 3)

        w_start = max(cue_start, min(cue_end - 0.001, round(w_start, 3)))
        w_end = max(w_start + 0.001, min(cue_end, round(w_end, 3)))
        words.append(dict(text=wt, start=w_start, end=w_end))
        curr = w_end

    return words


def match_lyrics_to_transcription(cues, lyrics, duration, language=None, model=None, audio_samples=None, generate_fn=None, llm_model_id='llama-3.2-1b'):
    """Match user's supplied lyrics to existing timed transcription cues using global sequence alignment.

    Replaces transcription text using ONLY supplied lyrics, preserves valid line timings,
    and flags unmatched or uncertain lines for listening review.
    """
    if not cues:
        raise ValueError('No existing transcription lines to match against. Transcribe the audio first.')
    if not lyrics:
        raise ValueError('Paste your correct lyrics first.')

    N = len(lyrics)
    M = len(cues)

    # Compute similarity matrix between supplied lyrics and transcribed cues
    sim = [[0.0] * M for _ in range(N)]
    for i in range(N):
        l_norm = normalize_lyric_text(lyrics[i])
        l_words = set(l_norm.split())
        for j in range(M):
            c_norm = normalize_lyric_text(cues[j]['text'])
            c_words = set(c_norm.split())
            ratio = SequenceMatcher(None, l_norm, c_norm).ratio()
            jaccard = len(l_words & c_words) / max(1, len(l_words | c_words))
            sim[i][j] = max(ratio, jaccard)

    # Needleman-Wunsch global sequence alignment to preserve chronological ordering
    dp = [[-1e9] * (M + 1) for _ in range(N + 1)]
    back: list[list[Any]] = [[None] * (M + 1) for _ in range(N + 1)]
    dp[0][0] = 0.0

    gap_lyric = -0.15
    gap_cue = -0.10

    for i in range(N + 1):
        for j in range(M + 1):
            if i == 0 and j == 0:
                continue
            best = -1e9
            move = None
            if i > 0 and j > 0:
                score = dp[i-1][j-1] + (sim[i-1][j-1] * 2.0 - 0.5)
                if score > best:
                    best = score
                    move = ('match', i-1, j-1)
            if i > 0:
                score = dp[i-1][j] + gap_lyric
                if score > best:
                    best = score
                    move = ('skip_lyric', i-1, j)
            if j > 0:
                score = dp[i][j-1] + gap_cue
                if score > best:
                    best = score
                    move = ('skip_cue', i, j-1)
            dp[i][j] = best
            back[i][j] = move

    # Traceback
    i, j = N, M
    pairs = []
    while i > 0 or j > 0:
        move = back[i][j]
        if move is None:
            break
        kind = move[0]
        if kind == 'match':
            pairs.append((i-1, j-1, sim[i-1][j-1]))
            i -= 1
            j -= 1
        elif kind == 'skip_lyric':
            pairs.append((i-1, None, 0.0))
            i -= 1
        else:
            pairs.append((None, j-1, 0.0))
            j -= 1

    pairs.reverse()

    # Build intermediate cue list
    items: list[dict[str, Any]] = []
    for l_idx, c_idx, score in pairs:
        if l_idx is not None and c_idx is not None:
            c = cues[c_idx]
            items.append({
                'text': lyrics[l_idx],
                'start': c['start'],
                'end': c['end'],
                'score': score,
                'matched': True
            })
        elif l_idx is not None:
            items.append({
                'text': lyrics[l_idx],
                'start': None,
                'end': None,
                'score': 0.0,
                'matched': False
            })

    # Step 1: Assign valid line timing windows to all items
    k = 0
    while k < len(items):
        if items[k]['start'] is not None:
            k += 1
            continue
        k_start = k
        while k < len(items) and items[k]['start'] is None:
            k += 1
        k_end = k
        run_len = k_end - k_start

        prev_idx = k_start - 1 if k_start > 0 else None
        next_idx = k_end if k_end < len(items) else None

        prev_end = items[prev_idx]['end'] if prev_idx is not None else 0.0
        next_start = items[next_idx]['start'] if next_idx is not None else duration

        gap = next_start - prev_end
        if gap >= 0.5 * run_len:
            step = gap / run_len
            for r_i in range(k_start, k_end):
                items[r_i]['start'] = prev_end + (r_i - k_start) * step
                items[r_i]['end'] = prev_end + (r_i - k_start + 1) * step
        elif prev_idx is not None and (items[prev_idx]['end'] - items[prev_idx]['start']) >= 1.5 * (run_len + 1):
            span_start = items[prev_idx]['start']
            span_end = next_start
            total_span = span_end - span_start
            all_lines = [items[prev_idx]] + [items[r] for r in range(k_start, k_end)]
            lens = [max(1, len(it['text'])) for it in all_lines]
            tot_lens = sum(lens)
            curr = span_start
            for l_i, it in enumerate(all_lines):
                fraction = lens[l_i] / tot_lens
                it['start'] = curr
                it['end'] = span_end if l_i == len(all_lines) - 1 else curr + fraction * total_span
                curr = it['end']
        elif next_idx is not None and (items[next_idx]['end'] - items[next_idx]['start']) >= 1.5 * (run_len + 1):
            span_start = prev_end
            span_end = items[next_idx]['end']
            total_span = span_end - span_start
            all_lines = [items[r] for r in range(k_start, k_end)] + [items[next_idx]]
            lens = [max(1, len(it['text'])) for it in all_lines]
            tot_lens = sum(lens)
            curr = span_start
            for l_i, it in enumerate(all_lines):
                fraction = lens[l_i] / tot_lens
                it['start'] = curr
                it['end'] = span_end if l_i == len(all_lines) - 1 else curr + fraction * total_span
                curr = it['end']
        else:
            slice_dur = 0.5
            total_needed = slice_dur * run_len
            avail = max(0.0, next_start - prev_end)
            if avail >= total_needed:
                step = avail / run_len
                for r_i in range(k_start, k_end):
                    items[r_i]['start'] = prev_end + (r_i - k_start) * step
                    items[r_i]['end'] = prev_end + (r_i - k_start + 1) * step
            else:
                step = max(0.05, avail / run_len) if avail > 0 else 0.1
                for r_i in range(k_start, k_end):
                    items[r_i]['start'] = prev_end + (r_i - k_start) * step
                    items[r_i]['end'] = prev_end + (r_i - k_start + 1) * step

    # Step 2: Strict monotonicity and non-overlapping pass on all cue line boundaries
    prev = 0.0
    for it in items:
        s = round(max(prev, min(duration - 0.05, it['start'])), 2)
        e = round(max(s + 0.05, min(duration, it['end'])), 2)
        it['start'] = s
        it['end'] = e
        prev = e

    # Backwards pass if any cue exceeded duration
    if items and items[-1]['end'] > duration:
        overflow = items[-1]['end'] - duration
        for it in reversed(items):
            it['end'] = max(0.05, it['end'] - overflow)
            it['start'] = max(0.0, min(it['end'] - 0.05, it['start'] - overflow))

    # Step 3: Now that all cue boundaries are 100% final and non-overlapping, generate word timings
    final_cues: list[dict[str, Any]] = []
    for it in items:
        words_text = it['text'].strip().split()
        if not words_text:
            continue
        words = distribute_words_in_cue(words_text, it['start'], it['end'])

        if not it['matched']:
            karaoke = dict(state='review', note='Unmatched lyric line — timing estimated between surrounding cues. Listen and adjust.')
        elif it['score'] < 0.45:
            karaoke = dict(state='review', note=f'Low confidence match ({int(it["score"]*100)}%). Verify line timing.')
        else:
            karaoke = dict(state='review', note='Lyrics matched to transcription. Listen and adjust word timings if needed.')

        final_cues.append(dict(
            start=it['start'],
            end=it['end'],
            text=it['text'],
            words=words,
            karaoke=karaoke
        ))

    return validate_edit(dict(cues=final_cues), duration)['cues']


def register_captions(app, save_dir, job_started, job_finished, refresh_gallery, get_whisper, allowed_path):
    bp = Blueprint('captions', __name__)
    root = Path(save_dir) / 'Caption Projects'
    stock_dir = Path(save_dir) / 'Stock Media'
    lock = threading.RLock()

    def is_allowed_media(path_str: str) -> bool:
        if not path_str:
            return False
        if allowed_path(path_str):
            return True
        try:
            target = Path(path_str).resolve()
            return target.parent == stock_dir.resolve() and target.is_file()
        except OSError:
            return False

    def read_stock_keys() -> dict[str, str]:
        key_file = root / 'stock_keys.json'
        stored: dict[str, str] = {}
        if key_file.is_file():
            try:
                raw = json.loads(key_file.read_text(encoding='utf-8'))
                if isinstance(raw, dict):
                    stored = {k: str(raw.get(k, '')).strip() for k in ('pexels', 'pixabay') if raw.get(k)}
            except (OSError, ValueError):
                pass
        for prov, env_name in (('pexels', 'PEXELS_API_KEY'), ('pixabay', 'PIXABAY_API_KEY')):
            if not stored.get(prov) and os.environ.get(env_name):
                stored[prov] = os.environ[env_name].strip()
        return stored

    def folder(pid):
        if not re.fullmatch(r'[a-f0-9]{32}', pid):
            raise ValueError('Invalid project ID.')
        return root / pid

    def read(pid):
        with lock:
            data = json.loads((folder(pid) / 'project.json').read_text(encoding='utf-8'))
            if data.get('duration'):
                data['studio'] = composition_model.migrate(data, folder(pid))
                data['missing_assets'] = [key for key, asset in data['studio']['assets'].items() if not composition_model.local_asset(folder(pid), asset).is_file()]
            return data

    def write(data):
        with lock:
            destination = folder(data['id']) / 'project.json'
            if destination.exists() and data.get('studio') and not (destination.parent / 'pre-studio-project.json').exists():
                old = json.loads(destination.read_text(encoding='utf-8'))
                if old.get('duration') and not old.get('studio'):
                    shutil.copy2(destination, destination.parent / 'pre-studio-project.json')
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
            original = copy.deepcopy(data)
            try:
                work(data, folder(data['id']))
                process.check_cancelled()
                data['state'], data['status'] = 'ready', data.pop('_completion_notice', 'Ready')
                data['revision'] += 1
                refresh_gallery()
            except Exception as exc:
                data.clear()
                data.update(original)
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
        return render_template('captions.html', api_token=session['api_token'], languages=composition_model.LANGUAGES)

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
        if song and song.filename:
            name = song.filename
        elif upload and upload.filename:
            name = upload.filename
        elif source is not None and allowed_path(str(source)) and source.is_file():
            name = source.name
        else:
            raise ValueError('Choose a video from your library or upload one.')
        extension = Path(name).suffix.lower()
        if song and extension not in {'.mp3', '.wav', '.m4a', '.flac', '.ogg'}:
            raise ValueError('Choose MP3, WAV, M4A, FLAC or OGG audio.')
        if not song and extension not in {'.mp4', '.mkv', '.mov', '.webm', '.avi', '.m4v'}:
            raise ValueError('Choose a supported video file.')
        composition = None
        background = None
        bg_path = ''
        bg_ext = ''
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
            if bg_path and (not is_allowed_media(bg_path) or not Path(bg_path).is_file()):
                raise ValueError('Choose a background from your library.')
            bg_name = (background.filename if background and background.filename else bg_path) or ''
            bg_ext = Path(bg_name).suffix.lower() if bg_name else ''
            if (background or bg_path) and bg_ext not in {'.png','.jpg','.jpeg','.webp','.mp4','.mov','.mkv','.webm'}:
                raise ValueError('Choose a photo or video background.')
            composition = dict(shape=shape, color=color, visualizer=request.form.get('visualizer') == 'true')
            if (background or bg_path) and request.form.get('stock_provenance'):
                composition['provenance'] = composition_model.validate_provenance(
                    json.loads(request.form.get('stock_provenance', '{}'))
                )
        destination.mkdir(parents=True)
        media = destination / ('original.mp4' if song else 'original' + extension)
        if song:
            song_file = destination / ('song' + extension)
            song.save(song_file)
            bg_file = destination / ('background' + bg_ext) if background or bg_path else None
            if background and bg_file is not None:
                background.save(bg_file)
            elif bg_path and bg_file is not None:
                shutil.copy2(bg_path, bg_file)
        elif upload:
            upload.save(media)
        elif source is not None:
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
                if composition and composition.get('visualizer'):
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
            d['studio'] = composition_model.migrate(d, f)
        return launch(data, 'Preparing preview and waveform…', prepare)

    def preview_and_peaks(d, f, source, preview):
        ffmpeg(['-i', source, '-map', '0:v:0', '-map', '0:a:0?', '-vf',
                "scale=w='min(720,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                '-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p',
                '-c:a','aac','-movflags','+faststart',preview], f)
        result = process.run([imageio_ffmpeg.get_ffmpeg_exe(),'-i',str(f/source),'-vn','-ac','1','-ar','1000','-f','f32le','-'], capture_output=True)
        if result.returncode:
            raise ValueError('Could not prepare the composition audio waveform.')
        values = np.frombuffer(result.stdout, dtype='<f4')
        d['peaks'] = [round(float(np.max(np.abs(c))),4) for c in np.array_split(values,min(4000,len(values))) if len(c)] if len(values) else []

    def composition_snapshot(d):
        keys = ('studio','source','preview','duration','width','height','peaks','cues','style','timing','karaoke_backup','composition')
        return {key:copy.deepcopy(d[key]) for key in keys if key in d}

    @bp.post('/api/captions/<pid>/composition')
    def update_composition(pid):
        with lock:
            data = read(pid)
            if data['state'] == 'busy' or request.form.get('revision') != str(data['revision']):
                return jsonify(error='Project changed or is processing. Reload before applying composition changes.'),409
            if not data.get('studio'):
                raise ValueError('Finish preparing the project first.')
            settings = json.loads(request.form.get('settings','{}'))
            if not isinstance(settings,dict): raise ValueError('Invalid composition settings.')
            # Validate all numeric controls before saving media; replacement duration is checked in the worker.
            composition_model.validate(settings, 7200)
            assets = copy.deepcopy(data['studio']['assets'])
            f = folder(pid)
            added = []
            try:
                for key, field in [('audio','audio'),('background','background'),('broll','broll')]:
                    upload = request.files.get(field)
                    library = request.form.get(field+'_path','') if not upload else ''
                    if not upload and not library: continue
                    if library and (not is_allowed_media(library) or not Path(library).is_file()):
                        raise ValueError('Choose media from your library or upload it.')
                    media_name = (upload.filename if upload and upload.filename else library) or ''
                    ext = Path(media_name).suffix.lower()
                    supported = composition_model.AUDIO | composition_model.VIDEOS if key=='audio' else composition_model.IMAGES | composition_model.VIDEOS
                    if ext not in supported: raise ValueError('Unsupported composition media type.')
                    name = 'asset_'+uuid.uuid4().hex+ext
                    target = f/name
                    if upload: upload.save(target)
                    else: shutil.copy2(library,target)
                    added.append(target)
                    entry: dict[str, Any] = dict(file=name,kind='audio' if key=='audio' else 'image' if ext in composition_model.IMAGES else 'video')
                    if key == 'background' and request.form.get('stock_provenance'):
                        entry['provenance'] = composition_model.validate_provenance(
                            json.loads(request.form.get('stock_provenance', '{}'))
                        )
                    assets[key] = entry
                if request.form.get('clear_background') == 'true': assets.pop('background',None)
                if request.form.get('clear_broll') == 'true': assets.pop('broll',None)
                for key,asset in assets.items():
                    if not composition_model.local_asset(f,asset).is_file():
                        raise ValueError('Missing '+key+' media. Choose its original file to relink it.')
            except Exception:
                for path in added: path.unlink(missing_ok=True)
                raise
            def work(d, f):
                token = uuid.uuid4().hex[:12]
                output, preview = 'composition_'+token+'.mp4','preview_'+token+'.mp4'
                audio_probe = 'duration_'+token+'.wav'
                success = False
                try:
                    # Bounded decode verifies the real replacement duration, not its filename or metadata.
                    ffmpeg(['-i',assets['audio']['file'],'-t','1200.1','-vn','-ac','1','-ar','1000','-c:a','pcm_s16le',audio_probe], f)
                    with wave.open(str(f/audio_probe),'rb') as audio:
                        source_duration = audio.getnframes()/audio.getframerate()
                    number(source_duration,.1,1200)
                    if 0 < float(settings.get('end',0))-source_duration <= .05:
                        settings['end'] = source_duration  # Legacy video frame rounding.
                    clean = composition_model.validate(settings,source_duration)
                    assets['audio']['duration'] = source_duration
                    studio = composition_model.schema(assets,clean,d['style'])
                    bg = assets.get('background')
                    has_audio = False
                    if bg and bg['kind']=='video' and clean['background_volume']:
                        probe = process.run([imageio_ffmpeg.get_ffmpeg_exe(),'-i',str(f/bg['file'])],capture_output=True)
                        has_audio = b'Audio:' in probe.stderr
                        if not has_audio: raise ValueError('This background has no audio. Set Background volume to 0.')
                    d['status'] = 'Applying background and audio settings…'
                    write(d)
                    ffmpeg(composition_model.render_args(studio,f,output,has_audio),f)
                    preview_and_peaks(d,f,output,preview)
                    process.check_cancelled()
                    old_settings = d['studio']['settings']
                    duration = clean['end']-clean['start']+clean['offset']
                    delta = old_settings['start']-clean['start']+clean['offset']-old_settings['offset']
                    cues = composition_model.shift_cues(d['cues'],delta,duration)
                    validate_edit(dict(cues=cues,style=d['style']),duration)
                    # Read the saved pre-job peaks: preview generation only modified the worker copy.
                    backup = composition_snapshot(read(pid))
                    d.update(studio=studio,source=output,preview=preview,duration=duration,
                             width=composition_model.SHAPES[clean['shape']][0],height=composition_model.SHAPES[clean['shape']][1],
                             cues=cues,composition=clean,composition_backup=backup,missing_assets=[])
                    if delta or duration != backup['duration']:
                        d.pop('karaoke_backup',None)
                    if any(p.name == assets['audio']['file'] for p in added):
                        for cue in d['cues']:
                            cue['karaoke'] = dict(state='review',note='Audio replaced or relinked. Check lyric synchronization.')
                    success = True
                finally:
                    (f/audio_probe).unlink(missing_ok=True)
                    if not success:
                        for path in [f/output,f/preview,*added]: path.unlink(missing_ok=True)
            return launch(data,'Preparing editable composition…',work)

    @bp.post('/api/captions/<pid>/restore-composition')
    def restore_composition(pid):
        with lock:
            d = read(pid)
            if d['state']=='busy' or request.get_json().get('revision') != d['revision']:
                return jsonify(error='Reload the project before restoring.'),409
            backup = d.get('composition_backup')
            if not backup: raise ValueError('No previous composition is available.')
            old = composition_snapshot(d)
            for key in old: d.pop(key,None)
            d.update(copy.deepcopy(backup),composition_backup=old,state='ready',status='Previous composition restored')
            d['revision'] += 1
            write(d)
            return jsonify(d)

    @bp.post('/api/captions/<pid>/duplicate')
    def duplicate(pid):
        with lock:
            d = read(pid)
            if d['state']=='busy' or request.get_json().get('revision') != d['revision']:
                return jsonify(error='Reload the project before duplicating.'),409
            old_folder = folder(pid)
            d['id'] = uuid.uuid4().hex
            target = folder(d['id'])
            target.mkdir(parents=True)
            names = {d['source'],d.get('preview','preview.mp4')}
            names.update(a['file'] for a in d['studio']['assets'].values())
            try:
                for name in names:
                    source = composition_model.local_asset(old_folder,dict(file=name))
                    if source.is_file(): shutil.copy2(source,target/name)
                d.update(name=(d['name']+' — copy')[:200],revision=0,exports=[],state='ready',status='Project duplicated')
                for key in ('composition_backup','last_render'): d.pop(key,None)
                write(d)
            except Exception:
                shutil.rmtree(target)
                raise
            return jsonify(d),201

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
            if data.get('studio'):
                data['studio'] = composition_model.schema(data['studio']['assets'], data['studio']['settings'], data['style'])
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

    @bp.post('/api/captions/<pid>/karaoke')
    def karaoke(pid):
        with lock:
            data = read(pid)
            options = request.get_json()
            if data['state'] == 'busy' or options.get('revision') != data['revision']:
                return jsonify(error='Project changed or is processing. Reload before syncing.'), 409
            if not data['cues']:
                raise ValueError('Import subtitles or add caption lines first.')
            language = options.get('language', 'auto')
            if language not in {'auto', *composition_model.LANGUAGES, *composition_model.MIXED}:
                raise ValueError('Choose a supported alignment language.')
            index = options.get('index')
            if index is not None and (type(index) is not int or not 0 <= index < len(data['cues'])):
                raise ValueError('Select a valid caption line.')
            indices = list(range(len(data['cues']))) if index is None else [index]
            def work(d, f):
                model = get_whisper()
                if model is None:
                    raise ValueError('Install the AI Pack in the Studio to add karaoke timing.')
                # Decode once, then read bounded cue slices rather than loading a full song into RAM.
                audio_file = f / 'karaoke.wav'
                pending = copy.deepcopy(d['cues'])
                try:
                    ffmpeg(['-i', d['source'], '-t', str(d['duration']), '-vn', '-ac', '1',
                            '-ar', '16000', '-c:a', 'pcm_s16le', audio_file.name], f)
                    with wave.open(str(audio_file), 'rb') as audio:
                        for count, i in enumerate(indices):
                            process.check_cancelled()
                            cue = pending[i]
                            greek = bool(re.search(r'[\u0370-\u03ff\u1f00-\u1fff]', cue['text']))
                            latin = bool(re.search(r'[a-zA-Z]', cue['text']))
                            korean = bool(re.search(r'[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]', cue['text']))
                            chosen = language if language in composition_model.LANGUAGES else ('ko' if korean else 'el' if greek else 'en')
                            try:
                                if cue['end'] - cue['start'] > 60:
                                    raise ValueError('Line exceeds 60 seconds. Split it before retrying.')
                                audio.setpos(min(audio.getnframes(), round(cue['start']*16000)))
                                samples = np.frombuffer(audio.readframes(round((cue['end']-cue['start'])*16000)), dtype='<i2').astype(np.float32)/32768
                                if not len(samples) or np.max(np.abs(samples)) < .0001:
                                    raise ValueError('No audible audio in this line.')
                                if language == 'auto' or language in composition_model.MIXED:
                                    candidates = composition_model.MIXED.get(language)
                                    if not greek and not korean:
                                        chosen = detect_caption_language(model, samples, candidates)
                                result = align_caption_words(model, samples, cue['text'], chosen)
                                words = aligned_cues(result, [cue['text']], cue['start'], d['duration'], cue['end']-cue['start'], recover=True)[0]['words']
                                notes = []
                                if any(w['end']-w['start'] < .06 for w in words):
                                    notes.append('Very short word timings; check against the vocals.')
                                if (greek or korean) and latin or language in composition_model.MIXED:
                                    notes.append('Mixed-language selection; check timing or retry this line with a language override.')
                                cue['words'] = words
                                cue['karaoke'] = dict(state='review' if notes else 'aligned', note=' '.join(notes), language=chosen)
                            except (ValueError, KeyError, TypeError) as exc:
                                process.check_cancelled()
                                note = str(exc)[:220] + (' Existing word timings were kept.' if cue['words'] else ' No word timings were added.')
                                cue['karaoke'] = dict(state='review', note=note, language=chosen)
                            d['status'] = f'Adding karaoke timing: {count+1}/{len(indices)} lines. Changes apply when the job finishes.'
                            write(d)
                    validate_edit(dict(cues=pending, style=d['style']), d['duration'])
                    process.check_cancelled()
                    d['karaoke_backup'] = dict(cues=copy.deepcopy(d['cues']), timing=d['timing'])
                    d['cues'] = pending
                finally:
                    audio_file.unlink(missing_ok=True)
            return launch(data, 'Adding karaoke timing while preserving subtitle lines…', work)

    @bp.post('/api/captions/<pid>/restore-karaoke')
    def restore_karaoke(pid):
        with lock:
            d = read(pid)
            if d['state'] == 'busy' or request.get_json().get('revision') != d['revision']:
                return jsonify(error='Project changed or is processing. Reload before restoring.'), 409
            backup = d.get('karaoke_backup')
            if not backup:
                raise ValueError('No previous karaoke version is available.')
            old = dict(cues=d['cues'], timing=d['timing'])
            d.update(cues=backup['cues'], timing=backup['timing'], karaoke_backup=old)
            d['revision'] += 1
            d.update(state='ready', status='Previous caption version restored')
            write(d)
            return jsonify(d)

    @bp.post('/api/captions/<pid>/align')
    def align(pid):
        with lock:
            data = read(pid)
            if data['state'] == 'busy':
                return jsonify(error='Wait for the current task.'), 409
            options = request.get_json()
            lines = lyric_lines(options.get('text', ''))
            language = options.get('language', '')
            if language not in composition_model.LANGUAGES:
                raise ValueError('Choose a lyric language. For mixed songs, sync matching sections or use imported subtitles with per-line karaoke timing.')
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
                    cues = aligned_cues(result, lines, start, d['duration'], end-start, recover=True)
                    process.check_cancelled()
                    d['karaoke_backup'] = dict(cues=copy.deepcopy(d['cues']), timing=d['timing'])
                    d.update(cues=cues, timing='aligned')
                    flagged = sum(c.get('karaoke',{}).get('state') == 'review' for c in cues)
                    if flagged:
                        d['_completion_notice'] = f'Lyrics updated. {flagged} lines contain estimated word timings — use Next line to review.'
                finally:
                    audio_file.unlink(missing_ok=True)
            return launch(data, 'Matching your lyrics to the audio (existing captions are kept if this fails)…', work)

    @bp.post('/api/captions/<pid>/correct-lyrics')
    def correct_lyrics(pid):
        with lock:
            data = read(pid)
            if data['state'] == 'busy':
                return jsonify(error='Wait for the current task.'), 409
            if not data.get('cues'):
                raise ValueError('Auto-transcribe the audio or import subtitles first so we have line timings to match.')
            options = request.get_json() or {}
            lines = lyric_lines(options.get('text', ''))
            language = options.get('language', '')
            def work(d, f):
                process.check_cancelled()
                matched = match_lyrics_to_transcription(
                    d['cues'], lines, d['duration'], language=language
                )
                process.check_cancelled()
                d['karaoke_backup'] = dict(cues=copy.deepcopy(d['cues']), timing=d['timing'])
                d.update(cues=matched, timing='aligned')
                flagged = sum(c.get('karaoke', {}).get('state') == 'review' for c in matched)
                d['_completion_notice'] = f'Transcription updated with your lyrics ({len(matched)} lines). {flagged} lines contain estimated word timings — use Next line to review.'
            return launch(data, 'Matching your lyrics to the existing transcription timings…', work)

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
            quality = str(options.get('quality', 'standard')).strip().lower()
            if quality not in composition_model.RENDER_QUALITIES:
                raise ValueError('Choose a supported render quality preset.')
            q_spec = composition_model.RENDER_QUALITIES[quality]
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
                    scale_vf = "scale=w='min(720,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2" if q_spec['max_side'] else 'scale=trunc(iw/2)*2:trunc(ih/2)*2'
                    args = ['-i', d['source'], '-map', '0:v:0', '-map', '0:a:0?', '-vf', f'ass={ass.name}:fontsdir=caption_fonts,{scale_vf}']
                    if preview:
                        args += ['-ss', str(start), '-t', str(min(5, d['duration']-start))]
                    ffmpeg([*args, '-c:v', 'libx264', '-preset', q_spec['preset'], '-crf', q_spec['crf'], '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', q_spec['audio_bitrate'], '-movflags', '+faststart', temporary.name], f)
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
        if name not in ['preview.mp4', data.get('preview'), *data.get('exports', [])]:
            return jsonify(error='Media not available.'), 404
        return send_file(folder(pid) / name, conditional=True, as_attachment=request.args.get('download') == '1')

    @bp.route('/api/captions/stock/keys', methods=['GET', 'POST'])
    def stock_keys():
        with lock:
            keys = read_stock_keys()
            if request.method == 'POST':
                payload = request.get_json() or {}
                if not isinstance(payload, dict):
                    raise ValueError('Invalid API key payload.')
                for prov in ('pexels', 'pixabay'):
                    if prov in payload:
                        val = str(payload[prov] or '').strip()[:200]
                        if val:
                            keys[prov] = val
                        else:
                            keys.pop(prov, None)
                root.mkdir(parents=True, exist_ok=True)
                (root / 'stock_keys.json').write_text(json.dumps(keys, ensure_ascii=False), encoding='utf-8')
            return jsonify(pexels=bool(keys.get('pexels')), pixabay=bool(keys.get('pixabay')))

    @bp.post('/api/captions/stock/search')
    def stock_search():
        payload = request.get_json() or {}
        if not isinstance(payload, dict):
            raise ValueError('Invalid stock search request.')
        provider = str(payload.get('provider', 'pexels')).strip().lower()
        keys = read_stock_keys()
        api_key = str(payload.get('api_key') or keys.get(provider, '')).strip()
        if payload.get('api_key') and api_key:
            with lock:
                keys[provider] = api_key[:200]
                root.mkdir(parents=True, exist_ok=True)
                (root / 'stock_keys.json').write_text(json.dumps(keys, ensure_ascii=False), encoding='utf-8')
        results = composition_model.search_stock(
            provider=provider,
            query=str(payload.get('query', '')),
            kind=str(payload.get('kind', 'video')),
            orientation=str(payload.get('orientation', 'portrait')),
            max_duration=float(payload.get('max_duration') or 0),
            api_key=api_key
        )
        return jsonify(results=results)

    @bp.post('/api/captions/stock/download')
    def stock_download():
        payload = request.get_json() or {}
        if not isinstance(payload, dict):
            raise ValueError('Invalid stock download request.')
        prov = composition_model.validate_provenance(payload)
        provider = prov['provider']
        kind = str(payload.get('kind', 'video')).strip().lower()
        if kind not in {'video', 'image'}:
            raise ValueError('Choose a stock video or image.')
        dl_url = composition_model.validate_stock_url(str(payload.get('download_url', '')), provider)
        url_path = urllib.parse.urlsplit(dl_url).path
        ext = Path(url_path).suffix.lower()
        if kind == 'video':
            ext = ext if ext in {'.mp4', '.mov', '.webm'} else '.mp4'
        else:
            ext = ext if ext in {'.jpg', '.jpeg', '.png', '.webp'} else '.jpg'
        safe_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(payload.get('id', '')))[:24] or uuid.uuid4().hex[:8]
        stock_dir.mkdir(parents=True, exist_ok=True)
        dest = stock_dir / f'{provider}_{safe_id}_{uuid.uuid4().hex[:6]}{ext}'
        process.begin_job()
        try:
            composition_model.download_stock_asset(dl_url, provider, kind, dest, check_cancel=process.check_cancelled)
        finally:
            process.end_job()
        refresh_gallery()
        return jsonify(path=str(dest), name=dest.name, kind=kind, provenance=prov)

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
