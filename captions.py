from assets import lyric_tracks, lyric_translation, lyric_layout, lyric_fonts
"""Local caption projects, validated subtitle data and non-destructive rendering."""
import io
import hashlib
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
import sys
import tempfile
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
                     layout_enabled=False, line_spacing=1.2, letter_spacing=0, box_width=88, horizontal=50, alignment='center',
                     box_padding=1.2, box_radius=.3, track_mode='original', translation_language='en',
                     translation_size=3.5, translation_color='#dddddd', translation_gap=1.5, hide_duplicate_translation=True,
                     visualizer=False, visualizer_style='spectrum', visualizer_position='bottom',
                     visualizer_height=18, visualizer_sensitivity=1, visualizer_color='#bba6ff',
                     animation='none', glow=0,
                     video_filter='none', vignette=False, film_grain=0, sharpen=0, chromatic=0,
                     noise_cancel=False, voice_isolation=False, audio_effect='none')
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
CUSTOM_FONT_DIR = Path(os.environ.get('MEDIA_GRABBER_DATA_DIR') or Path.home() / 'Documents' / 'Media Grabber') / 'Fonts'
CUSTOM_FONTS = {}


def refresh_custom_fonts():
    CUSTOM_FONTS.clear()
    legacy = FONT_DIR / 'custom'
    if legacy.is_dir():
        for old in legacy.glob('*.*'):
            if old.suffix.lower() in ('.ttf', '.otf'):
                CUSTOM_FONT_DIR.mkdir(parents=True, exist_ok=True)
                target = CUSTOM_FONT_DIR / old.name
                if not target.exists():
                    shutil.copy2(old, target)
    if CUSTOM_FONT_DIR.is_dir():
        for font_file in CUSTOM_FONT_DIR.glob('*.*'):
            if font_file.suffix.lower() in ('.ttf', '.otf'):
                family = None
                try:
                    f = ImageFont.truetype(str(font_file), 32)
                    name_tuple = f.getname()
                    if name_tuple and name_tuple[0]:
                        family = str(name_tuple[0]).strip()
                except Exception:
                    pass
                if not family:
                    stem = font_file.stem
                    family = re.sub(r'[_\-]+', ' ', stem).strip()
                if family:
                    CUSTOM_FONTS[family] = font_file.name
                    FONTS.add(family)


refresh_custom_fonts()


WORD_TIME_TOLERANCE = 0.01  # seconds of edge drift absorbed when validating word timings


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
            if not isinstance(word, dict):
                raise ValueError('Invalid word timing data.')
            raw_a, raw_b = float(word['start']), float(word['end'])
            # Absorb only floating-point/rounding drift at the caption edges; real errors are still rejected.
            if start - WORD_TIME_TOLERANCE <= raw_a < start:
                raw_a = start
            if end < raw_b <= end + WORD_TIME_TOLERANCE:
                raw_b = end
            if previous - WORD_TIME_TOLERANCE <= raw_a < previous:
                raw_a = previous
            a, b = number(raw_a, start, end), number(raw_b, start, end)
            t = str(word['text']).strip()
            if b <= a or a < previous or not t or len(t) > 100:
                raise ValueError('Word timings must be ordered and inside their caption.')
            previous = b
            words.append(dict(start=a, end=b, text=t))
        if words and ' '.join(w['text'] for w in words).split() != text.split():
            raise ValueError('Word timing text must match its caption. Rebuild word timings after editing text.')
        item: dict[str, Any] = dict(start=start, end=end, text=text, words=words)
        if 'id' in cue:
            if not isinstance(cue['id'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}',cue['id']):
                raise ValueError('Invalid caption identifier.')
            item['id'] = cue['id']
        if cue.get('style_override'):
            allowed={'font','size','color','highlight','outline','position','background','alignment','horizontal','box_width','line_spacing','letter_spacing','box_padding','box_radius','translation_size','translation_color','translation_gap','animation','glow'}
            override=cue['style_override']
            if not isinstance(override,dict) or not set(override)<=allowed: raise ValueError('Invalid line style override.')
            checked=validate_edit(dict(cues=[],style=override),duration)['style']
            item['style_override']={key:checked[key] for key in override}
        if cue.get('translations'):
            item['translations'] = lyric_tracks.clean_translations({**cue,'text':text})
        if isinstance(cue.get('karaoke'), dict):
            info = cue['karaoke']
            state = info.get('state')
            if state in {'aligned', 'review', 'estimated', 'edited', 'checked'}:
                item['karaoke'] = dict(state=state, note=str(info.get('note', ''))[:300],
                                       language=str(info.get('language', ''))[:3])
        clean.append(item)
    ids = [c['id'] for c in clean if 'id' in c]
    if len(ids) != len(set(ids)):
        raise ValueError('Caption identifiers must be unique.')
    clean.sort(key=lambda c: c['start'])
    for left, right in zip(clean, clean[1:]):
        if left['end'] > right['start'] + .001:
            raise ValueError('Caption lines overlap. Adjust their times before saving.')
    style = {**DEFAULT_STYLE, **data.get('style', {})}
    if style['font'] not in FONTS:
        raise ValueError('Choose a supported font.')
    style = {k: style[k] for k in DEFAULT_STYLE}
    for k in ('color', 'highlight', 'visualizer_color', 'translation_color'):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(style[k])):
            raise ValueError('Invalid caption color.')
    if style['visualizer_style'] not in {'waveform', 'spectrum'} or style['visualizer_position'] not in {'bottom', 'center', 'top'}:
        raise ValueError('Choose a supported visualizer style and position.')
    if style['video_filter'] not in composition_model.VIDEO_FILTERS or style['audio_effect'] not in composition_model.AUDIO_EFFECTS:
        raise ValueError('Choose a supported video filter and audio effect.')
    if style['animation'] not in composition_model.CAPTION_ANIMATIONS:
        raise ValueError('Choose a supported caption animation.')
    if style['alignment'] not in {'left','center','right'} or style['track_mode'] not in {'original','translation','both'}:
        raise ValueError('Invalid text alignment or track mode.')
    if style['translation_language'] not in composition_model.LANGUAGES:
        raise ValueError('Choose a supported translation language.')
    for key,low,high in [('line_spacing',.8,2.5),('letter_spacing',0,1),('box_width',20,96),('horizontal',2,98),('box_padding',0,4),('box_radius',0,2),('translation_size',2,12),('translation_gap',0,10)]:
        style[key] = number(style[key],low,high)
    style['layout_enabled'] = bool(style['layout_enabled'])
    style['hide_duplicate_translation'] = bool(style['hide_duplicate_translation'])
    style['glow'] = number(style['glow'], 0, 10)
    style['size'] = number(style['size'], 2, 12)
    style['outline'] = number(style['outline'], 0, 5)
    style['position'] = number(style['position'], 10, 95)
    style['visualizer_height'] = number(style['visualizer_height'], 10, 40)
    style['visualizer_sensitivity'] = number(style['visualizer_sensitivity'], .5, 3)
    style['film_grain'] = number(style['film_grain'], 0, 30)
    style['sharpen'] = number(style['sharpen'], 0, 2)
    style['chromatic'] = number(style['chromatic'], 0, 10)
    style['background'] = bool(style['background'])
    style['karaoke'] = bool(style['karaoke'])
    style['cumulative'] = bool(style['cumulative'])
    style['word_pop'] = bool(style['word_pop'])
    style['visualizer'] = bool(style['visualizer'])
    style['vignette'] = bool(style['vignette'])
    style['noise_cancel'] = bool(style['noise_cancel'])
    style['voice_isolation'] = bool(style['voice_isolation'])
    return dict(cues=clean, style=style)


def font_scale(name):
    """ASS sizes the font's ascender+descender; CSS sizes its em square."""
    files = {'Arial':'arial.ttf', 'Verdana':'verdana.ttf', 'Georgia':'georgia.ttf',
             'Impact':'impact.ttf', 'Trebuchet MS':'trebuc.ttf'}
    try:
        if name in BUNDLED_FONTS:
            path = FONT_DIR / BUNDLED_FONTS[name]
        elif name in CUSTOM_FONTS:
            path = CUSTOM_FONT_DIR / CUSTOM_FONTS[name]
        else:
            path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / files[name]
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


def layout_rows(cue, style, width, height):
    def locate(name):return lyric_layout.font_file(name,BUNDLED_FONTS,CUSTOM_FONT_DIR,CUSTOM_FONTS)
    return lyric_layout.rows(cue,style,width,height,locate(style['font']),
        lambda text:lyric_fonts.runs(text,style['font'],locate),locate)


def _row_background_events(cue, row, style, height):
    """Keep the rounded plate attached to its row during entrance animation."""
    pad = height*style['box_padding']/100
    anchor = {'left':0,'center':.5,'right':1}[row['alignment']]
    left = row['x']-row['width']*anchor-pad
    top = row['y']-row['height']-pad
    width, box_height = row['width']+2*pad, row['height']+2*pad
    radius = min(box_height/2,width/2,height*style['box_radius']/100)
    animation = style['animation'] if row['track']=='original' else 'none'
    duration = {'pop':.16,'zoom_in':.2,'slide_up':.18}.get(animation,0)
    start, end = cue['start'], cue['end']
    boundaries = {start,end}
    if duration:
        boundaries.add(min(end,start+duration))
        boundaries.update(start+i/60 for i in range(1,math.ceil(duration*60)) if start+i/60<end)
    if animation=='fade':
        boundaries.update(t for t in (start+.18,end-.18,(start+end)/2) if start<t<end)
    points=sorted(boundaries)
    events=[]
    for a,b in zip(points,points[1:]):
        if round(a*100)>=round(b*100):continue
        progress=min(1,(a-start)/duration) if duration else 1
        scale=(.85+.15*progress) if animation=='pop' else (.7+.3*progress) if animation=='zoom_in' else 1
        offset=height*.035*(1-progress) if animation=='slide_up' else 0
        x=row['x']+(left-row['x'])*scale
        y=row['y']+(top-row['y'])*scale+offset
        w,h,r=width*scale,box_height*scale,radius*scale
        path=f'm {x+r} {y} l {x+w-r} {y} b {x+w} {y} {x+w} {y} {x+w} {y+r} l {x+w} {y+h-r} b {x+w} {y+h} {x+w} {y+h} {x+w-r} {y+h} l {x+r} {y+h} b {x} {y+h} {x} {y+h} {x} {y+h-r} l {x} {y+r} b {x} {y} {x} {y} {x+r} {y}'
        def alpha(t):
            opacity=max(0,min(1,(t-start)/.18,(end-t)/.18)) if animation=='fade' else 1
            return round(255-(255-56)*opacity)
        tags=rf'\an7\pos(0,0)\c&H140C0A&\alpha&H{alpha(a):02X}&'
        if alpha(a)!=alpha(b):tags+=rf'\t(0,{round((b-a)*1000)},\alpha&H{alpha(b):02X}&)'
        events.append(f'Dialogue: -1,{timestamp(a,True)},{timestamp(b,True)},Vis,,0,0,0,,{{{tags}\\p1}}{path}{{\\p0}}')
    return events


def ass_text(project):
    style={**DEFAULT_STYLE,**project.get('style',{})}
    if not style['layout_enabled'] and style['track_mode']=='original' and not any(c.get('style_override') for c in project['cues']):
        return _legacy_ass_text(project)
    base=_legacy_ass_text({**project,'cues':[],'style':style})
    definitions=[];events=[]
    for cue in project['cues']:
        cue_style={**style,**cue.get('style_override',{})}
        for row in layout_rows(cue,cue_style,project['width'],project['height']):
            if not row['text']: continue
            name='Row'+str(len(definitions))
            if cue_style['background']:
                events.extend(_row_background_events(cue,row,cue_style,project['height']))
            row_style={**cue_style,'background':False,'size':row['size'],'color':row['color'],'position':row['y']/project['height']*100,
                       'horizontal':row['x']/project['width']*100,'letter_spacing':row['letter_spacing'],'visualizer':False}
            if row['track']=='translation': row_style.update(karaoke=False,cumulative=False,word_pop=False,animation='none')
            piece=_legacy_ass_text({**project,'style':row_style,'studio':{},'composition':{},
                'cues':[{**cue,'text':row['text'],'words':row['words']}]})
            definition=next(line for line in piece.splitlines() if line.startswith('Style: Default,'))
            definitions.append(definition.replace('Style: Default,','Style: '+name+',',1))
            for line in piece.splitlines():
                if line.startswith('Dialogue: 0,'):
                    events.append(line.replace(',Default,',','+name+',',1))
    return base.replace('[Events]','\n'.join(definitions)+'\n[Events]')+'\n'.join(events)+'\n'


def _legacy_ass_text(project):
    style = {**DEFAULT_STYLE, **project.get('style', {})}
    width, height = project['width'], project['height']
    def color(hexcolor, alpha='00'):
        return f'&H{alpha}' + hexcolor[5:7] + hexcolor[3:5] + hexcolor[1:3]
    def escape(text):
        # Fullwidth lookalikes prevent user text becoming ASS override commands.
        def literal(value):
            return value.replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\r', '').replace('\n', r'\N')
        locate=lambda name:lyric_layout.font_file(name,BUNDLED_FONTS,CUSTOM_FONT_DIR,CUSTOM_FONTS)
        pieces=[]
        for run in lyric_fonts.runs(text,style['font'],locate):
            if run['font']==style['font']:
                pieces.append(literal(run['text']))
            else:
                fallback_size=height*style['size']/100*font_scale(run['font'])
                original_size=height*style['size']/100*font_scale(style['font'])
                pieces.append(r'{\fn'+run['font']+rf'\fs{fallback_size:g}'+'}'+literal(run['text'])+
                              r'{\fn'+style['font']+rf'\fs{original_size:g}'+'}')
        return ''.join(pieces)
    font_size = height * style['size'] / 100 * font_scale(style['font'])
    outline = height * style['outline'] / 360
    border_style = 3 if style['background'] else 1
    alignment={'left':1,'center':2,'right':3}[style['alignment']]
    letter_spacing=height*style['letter_spacing']/100
    box_outline = max(outline, height * style['box_padding']/100) if style['background'] else outline
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
Style: Default,{style['font']},{font_size},{color(style['color'])},{color(style['color'])},{outline_col},&H80000000,0,0,0,0,100,100,{letter_spacing},0,{border_style},{box_outline},0,{alignment},{round(width*(1-style['box_width']/100)/2)},{round(width*(1-style['box_width']/100)/2)},0,1
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
        anim = style.get('animation', 'none')
        use_words = bool((style.get('karaoke') or style.get('cumulative') or style.get('word_pop') or anim == 'typewriter') and cue['words'])
        if not use_words and anim == 'typewriter' and len(cue['text']) > 1:
            raw_text = cue['text']
            total_dur = cue['end'] - cue['start']
            type_dur = min(total_dur, max(0.4, len(raw_text) * 0.045))
            num_steps = len(raw_text)
            step_dur = type_dur / num_steps
            pieces = []
            for k in range(1, num_steps):
                p_start = cue['start'] + (k - 1) * step_dur
                p_end = cue['start'] + k * step_dur
                pieces.append((p_start, p_end, raw_text[:k]))
            pieces.append((cue['start'] + (num_steps - 1) * step_dur, cue['end'], raw_text))
            for start, end, t_slice in pieces:
                if round(start*100) >= round(end*100):
                    continue
                body = escape(t_slice)
                cx, cy = width * style['horizontal']/100, height * style['position'] / 100
                glow = float(style.get('glow') or 0)
                tags = [rf'\pos({cx:.1f},{cy:.1f})']
                if glow > 0:
                    tags.append(rf'\blur{glow:.1f}')
                    body = body.replace(r'{\r}', r'{\r\blur' + f'{glow:.1f}' + '}')
                position = '{' + ''.join(tags) + '}'
                output.append(f"Dialogue: 0,{timestamp(start, True)},{timestamp(end, True)},Default,,0,0,0,,{position}{body}")
            continue

        pieces = [(cue['start'], cue['end'], None)]
        if use_words:
            boundaries = sorted({cue['start'], cue['end'], *(w[k] for w in cue['words'] for k in ('start', 'end'))})
            if anim == 'fade':
                ramp = min(.18, (cue['end']-cue['start'])/2)
                boundaries = sorted(set(boundaries) | {cue['start']+ramp, cue['end']-ramp})
            if anim == 'typewriter':
                character_times = set(boundaries)
                for word in cue['words']:
                    reveal_duration = max(.08, word['end']-word['start']) * .85
                    for index in range(1, len(word['text'])):
                        instant = word['start'] + reveal_duration * index / len(word['text'])
                        if instant < word['end']:
                            character_times.add(instant)
                boundaries = sorted(character_times)
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
                    if anim == 'typewriter' and w['start'] > mid:
                        continue
                    sep = escape(separators[i-1]) if i else ''
                    is_active = (i == active)
                    is_lit = (w['start'] <= mid) if style.get('cumulative') else (is_active and bool(style.get('karaoke')))
                    is_pop = is_active and bool(style.get('word_pop'))
                    text = w['text']
                    if anim == 'typewriter' and is_active:
                        count = max(1, min(len(text), math.ceil(len(text)*(mid-w['start'])/(max(.08,w['end']-w['start'])*.85))))
                        text = text[:count]
                    w_esc = escape(text)
                    pop_tags = r'\fscx115\fscy115'
                    if is_pop and anim in ('pop','zoom_in'):
                        initial,duration=(85,.16) if anim=='pop' else (70,.2)
                        elapsed=max(0,start-cue['start'])
                        if elapsed<duration:
                            combined=1.15*(initial+(100-initial)*elapsed/duration)
                            pop_tags=rf'\fscx{combined:g}\fscy{combined:g}\t(0,{round((duration-elapsed)*1000)},\fscx115\fscy115)'
                    if is_lit and is_pop:
                        parts.append(sep + r'{\c' + hl + '&' + pop_tags + '}' + w_esc + r'{\r}')
                    elif is_lit:
                        parts.append(sep + r'{\c' + hl + '&}' + w_esc + r'{\r}')
                    elif is_pop:
                        parts.append(sep + '{' + pop_tags + '}' + w_esc + r'{\r}')
                    else:
                        parts.append(sep + w_esc)
                body = ''.join(parts)
                if not body and anim == 'typewriter':
                    continue
            cx, cy = width * style['horizontal']/100, height * style['position'] / 100
            glow = float(style.get('glow') or 0)
            elapsed = max(0, start-cue['start'])
            tags = []
            if anim == 'slide_up' and elapsed < .18:
                remaining_ms = round((.18-elapsed)*1000)
                initial_y = cy + height*.035*(1-elapsed/.18)
                tags.append(rf'\move({cx:.1f},{initial_y:.1f},{cx:.1f},{cy:.1f},0,{remaining_ms})')
            else:
                tags.append(rf'\pos({cx:.1f},{cy:.1f})')
            if anim == 'fade':
                def alpha_at(instant):
                    opacity=max(0,min(1,(instant-cue['start'])/.18,(cue['end']-instant)/.18))
                    return round(255*(1-opacity))
                tags.append(rf'\alpha&H{alpha_at(start):02X}&')
                points=sorted({start,end,*[t for t in (cue['start']+.18,cue['end']-.18,(cue['start']+cue['end'])/2) if start<t<end]})
                for a,b in zip(points,points[1:]):
                    if alpha_at(a)!=alpha_at(b):
                        tags.append(rf'\t({round((a-start)*1000)},{round((b-start)*1000)},\alpha&H{alpha_at(b):02X}&)')
            elif anim in ('pop','zoom_in'):
                initial,duration=(85,.16) if anim=='pop' else (70,.2)
                if elapsed < duration:
                    scale=initial+(100-initial)*elapsed/duration
                    tags.append(rf'\fscx{scale:g}\fscy{scale:g}\t(0,{round((duration-elapsed)*1000)},\fscx100\fscy100)')
            if glow > 0:
                tags.append(rf'\blur{glow:.1f}')
            position = '{' + ''.join(tags) + '}'
            # Word highlighting resets the style; retain the enclosing cue animation.
            if anim in ('fade','pop','zoom_in','slide_up'):
                body = body.replace(r'{\r}', '{\\r' + ''.join(tags) + '}')
            elif glow > 0:
                body = body.replace(r'{\r}', r'{\r\blur' + f'{glow:.1f}' + '}')
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


def lyric_signature(data):
    """Invalidate proposals/checkpoints when caption content or source timing changes."""
    payload = [data['source'], data['duration'], data['cues']]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def save_lyric_progress(path, signature, cues, completed):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(dict(signature=signature, cues=cues, completed=completed),
                                    ensure_ascii=False), encoding='utf-8')
    for attempt in range(5):
        try:
            os.replace(temporary, path)
            break
        except OSError:
            if attempt == 4:
                raise
            time.sleep(0.02 * (attempt + 1))


def has_mixed_lyric_scripts(text):
    """Flag combinations including Greek/Korean without requiring English."""
    return sum(bool(re.search(pattern, text)) for pattern in (
        r'[\u0370-\u03ff\u1f00-\u1fff]',
        r'[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]',
        r'[a-zA-Z\u00c0-\u024f]',
    )) > 1


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
    for cue in cues:
        if cue.get('words'):
            c_s, c_e = cue['start'], cue['end']
            prev_w = c_s
            n_w = len(cue['words'])
            for idx, w in enumerate(cue['words']):
                w['start'] = max(prev_w, min(c_e - 0.001 * (n_w - idx), float(w['start'])))
                w['end'] = max(w['start'] + 0.001, min(c_e - 0.001 * (n_w - 1 - idx), float(w['end'])))
                prev_w = w['end']
            cue['words'][0]['start'] = c_s
            cue['words'][-1]['end'] = c_e
            if recover and any(w['end'] - w['start'] > 4.0 for w in cue['words']) and cue.get('karaoke', {}).get('state') != 'review':
                cue['karaoke'] = dict(state='review', note='Long stretched word timing detected (sustained note or instrumental gap); listen and check this line.')
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
    cue_start = float(cue_start)
    cue_end = float(cue_end)
    if cue_end <= cue_start:
        cue_end = cue_start + max(0.05, 0.005 * n)
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

        w_start = max(cue_start, min(cue_end - 0.001, w_start))
        w_end = max(w_start + 0.001, min(cue_end, w_end))
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
    if N * M > 1_000_000:
        raise ValueError('Choose a shorter caption range to correct; this selection is too large to match safely.')

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
                'matched': True,
                'original': c
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
        s = round(max(prev, min(duration - 0.05, it['start'])), 3)
        e = round(max(s + 0.05, min(duration, it['end'])), 3)
        it['start'] = s
        it['end'] = e
        prev = e

    # Backwards pass if any cue exceeded duration
    if items and items[-1]['end'] > duration:
        overflow = items[-1]['end'] - duration
        for it in reversed(items):
            it['end'] = round(max(0.05, it['end'] - overflow), 3)
            it['start'] = round(max(0.0, min(it['end'] - 0.05, it['start'] - overflow)), 3)

    for it in items:
        it['start'] = round(it['start'], 3)
        it['end'] = round(it['end'], 3)

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

        original = it.get('original')
        if original and original['text'] == it['text'] and original['start'] == it['start'] and original['end'] == it['end'] and original.get('words'):
            words = copy.deepcopy(original['words'])
            karaoke = copy.deepcopy(original.get('karaoke', dict(state='aligned', note='Existing word timings retained.')))

        final_cues.append(dict(
            start=it['start'],
            end=it['end'],
            text=it['text'],
            words=words,
            karaoke=karaoke
        ))

    return validate_edit(dict(cues=final_cues), duration)['cues']


EMOJI_FONT_CANDIDATES = (
    Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / 'seguiemj.ttf',
    Path('/System/Library/Fonts/Apple Color Emoji.ttc'),
    Path('/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf'),
)
# Colour emoji fonts only rasterise at specific strike sizes (Segoe UI Emoji: 109 for 256px output).
EMOJI_FONT_SIZES = {'seguiemj.ttf': 109, 'Apple Color Emoji.ttc': 160, 'NotoColorEmoji.ttf': 109}


def render_emoji_sticker(emoji: str, size: int = 256):
    """Render one emoji as a transparent colour PNG; fail clearly instead of exporting a missing-glyph box."""
    from PIL import Image, ImageDraw
    for font_path in EMOJI_FONT_CANDIDATES:
        if not font_path.exists():
            continue
        try:
            font = ImageFont.truetype(str(font_path), EMOJI_FONT_SIZES.get(font_path.name, 109))
        except OSError:
            continue
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((size // 2, size // 2), emoji, font=font, anchor='mm', embedded_color=True)
        alpha = np.asarray(img)[..., 3]
        if alpha.any():
            return img.crop(img.getbbox()) if img.getbbox() else img
    raise ValueError('No colour emoji font is available on this system. Upload a PNG sticker instead.')


def detect_face_in_video(video_path: Path, time_sec: float = 0.0, target: str = 'head') -> dict[str, Any]:
    """Detect prominent face at or around time_sec using local OpenCV and return normalized coordinates."""
    if not video_path.exists():
        return dict(found=False, message='Video media not found on disk.')
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return dict(found=False, message='Could not open video file for face tracking.')
    try:
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        face_cascade = cv2.CascadeClassifier(cascade_path)
        if face_cascade.empty():
            return dict(found=False, message='OpenCV face cascade model is unavailable.')

        dur_sec = max(0.1, cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(1.0, cap.get(cv2.CAP_PROP_FPS) or 30.0))
        search_times = [
            time_sec,
            max(0.0, time_sec - 0.25),
            min(dur_sec, time_sec + 0.25),
            max(0.0, time_sec - 0.75),
            min(dur_sec, time_sec + 0.75),
            max(0.0, time_sec - 1.5),
            min(dur_sec, time_sec + 1.5),
        ]

        best_face = None
        frame_w = 0
        frame_h = 0
        best_time = time_sec

        for t in search_times:
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            frame_h, frame_w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=3, minSize=(30, 30))
            if len(faces) > 0:
                faces = sorted(faces, key=lambda b: b[2] * b[3], reverse=True)
                best_face = faces[0]
                best_time = t
                break

        if best_face is None or frame_w <= 0 or frame_h <= 0:
            return dict(found=False, message='No face detected around this timestamp. Seek to a frame showing the face clearly.')

        fx, fy, fw, fh = best_face
        face_center_x = fx + (fw / 2.0)
        face_center_y = fy + (fh / 2.0)

        norm_w = (fw / frame_w) * 100.0

        if target == 'eyes':
            eye_y = fy + 0.38 * fh
            eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')
            if not eye_cascade.empty():
                face_roi = gray[fy:fy + int(fh * 0.65), fx:fx + fw]
                eyes = eye_cascade.detectMultiScale(face_roi, scaleFactor=1.1, minNeighbors=3, minSize=(15, 15))
                if len(eyes) >= 1:
                    avg_ey = sum(e[1] + e[3] / 2.0 for e in eyes) / len(eyes)
                    eye_y = fy + avg_ey
            target_x = round((face_center_x / frame_w) * 100.0)
            target_y = round((eye_y / frame_h) * 100.0)
            scale = round(max(10.0, min(80.0, norm_w * 1.15)))
        elif target == 'head':
            target_x = round((face_center_x / frame_w) * 100.0)
            target_y = round(max(2.0, ((fy - 0.16 * fh) / frame_h) * 100.0))
            scale = round(max(10.0, min(80.0, norm_w * 1.12)))
        else:
            target_x = round((face_center_x / frame_w) * 100.0)
            target_y = round((face_center_y / frame_h) * 100.0)
            scale = round(max(10.0, min(85.0, norm_w * 1.05)))

        return dict(
            found=True,
            x=target_x,
            y=target_y,
            scale=scale,
            time=round(best_time, 2),
            target=target,
            box=dict(x=int(fx), y=int(fy), w=int(fw), h=int(fh))
        )
    finally:
        cap.release()


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
            lyric_tracks.ensure_ids(data.get('cues',[]), data['id'])
            data['style']={**DEFAULT_STYLE,**data.get('style',{})}
            if data.get('duration'):
                data['studio'] = composition_model.migrate(data, folder(pid))
                data['missing_assets'] = [key for key, asset in data['studio']['assets'].items() if not composition_model.local_asset(folder(pid), asset).is_file()]
            return data

    def write(data):
        with lock:
            lyric_tracks.ensure_ids(data.get('cues',[]), data['id'])
            destination = folder(data['id']) / 'project.json'
            if destination.exists() and not (destination.parent / 'pre-translation-project.json').exists():
                shutil.copy2(destination, destination.parent / 'pre-translation-project.json')
            if destination.exists() and not (destination.parent / 'pre-v3.1.4-project.json').exists():
                shutil.copy2(destination, destination.parent / 'pre-v3.1.4-project.json')
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
        from assets import hwaccel
        result = hwaccel.run_render([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-y', *args], cwd=cwd, runner=process.run)
        if result.returncode:
            raise ValueError('Video processing failed: ' + result.stderr.decode('utf-8', errors='replace')[-700:])
        return getattr(result, 'video_encoder', '')

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
            raw_seq = settings.get('sequence') or []
            if not isinstance(raw_seq, list) or len(raw_seq) > 30:
                raise ValueError('A video sequence can contain at most 30 clips.')
            composition_model.validate({**settings, 'sequence': []}, 7200)
            assets = copy.deepcopy(data['studio']['assets'])
            f = folder(pid)
            added = []
            try:
                for key, field in [('audio','audio'),('background','background'),('broll','broll'),('sticker','sticker')]:
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
                emoji_raw = (request.form.get('emoji_sticker') or '').strip()
                if emoji_raw:
                    if len(emoji_raw) > 16:
                        raise ValueError('Choose a single emoji sticker.')
                    e_img = render_emoji_sticker(emoji_raw)
                    e_name = 'asset_' + uuid.uuid4().hex + '.png'
                    e_target = f / e_name
                    e_img.save(e_target, format='PNG')
                    added.append(e_target)
                    assets['sticker'] = dict(file=e_name, kind='image', name=f'Emoji {emoji_raw}')
                clip_uploads = request.files.getlist('clip_files')
                resolved_seq = []
                for item in raw_seq:
                    if not isinstance(item, dict):
                        raise ValueError('Invalid clip sequence entry.')
                    dur = composition_model.finite(item.get('duration', 0), 0, 1200)
                    spd = composition_model.finite(item.get('speed', 1.0), 0.25, 4.0)
                    source_start = composition_model.finite(item.get('source_start', 0), 0, 7200)
                    if item.get('asset'):
                        a_key = str(item['asset']).strip()
                        if a_key not in assets:
                            raise ValueError(f'Missing clip asset: {a_key}')
                        c_name = str(item.get('name') or assets[a_key].get('name') or assets[a_key]['file'])[:120]
                        resolved_seq.append(dict(asset=a_key, name=c_name, duration=dur, speed=spd, source_start=source_start))
                    elif item.get('upload_index') is not None:
                        idx = int(item['upload_index'])
                        if idx < 0 or idx >= len(clip_uploads) or not clip_uploads[idx] or not clip_uploads[idx].filename:
                            raise ValueError('Uploaded clip file is missing.')
                        up = clip_uploads[idx]
                        up_name = str(up.filename or 'clip.mp4')
                        ext = Path(up_name).suffix.lower()
                        if ext not in (composition_model.IMAGES | composition_model.VIDEOS):
                            raise ValueError('Unsupported clip media type.')
                        fname = 'asset_'+uuid.uuid4().hex+ext
                        target = f/fname
                        up.save(target)
                        added.append(target)
                        c_key = 'clip_'+uuid.uuid4().hex[:8]
                        c_name = str(item.get('name') or Path(up_name).name)[:120]
                        assets[c_key] = dict(file=fname, kind='image' if ext in composition_model.IMAGES else 'video', name=c_name)
                        resolved_seq.append(dict(asset=c_key, name=c_name, duration=dur, speed=spd, source_start=source_start))
                    elif item.get('path'):
                        lib_path = str(item['path'])
                        if not is_allowed_media(lib_path) or not Path(lib_path).is_file():
                            raise ValueError('Choose clip media from your library or upload it.')
                        ext = Path(lib_path).suffix.lower()
                        if ext not in (composition_model.IMAGES | composition_model.VIDEOS):
                            raise ValueError('Unsupported clip media type.')
                        fname = 'asset_'+uuid.uuid4().hex+ext
                        target = f/fname
                        shutil.copy2(lib_path, target)
                        added.append(target)
                        c_key = 'clip_'+uuid.uuid4().hex[:8]
                        c_name = str(item.get('name') or Path(lib_path).name)[:120]
                        c_entry: dict[str, Any] = dict(file=fname, kind='image' if ext in composition_model.IMAGES else 'video', name=c_name)
                        if isinstance(item.get('provenance'), dict):
                            c_entry['provenance'] = composition_model.validate_provenance(item['provenance'])
                        assets[c_key] = c_entry
                        resolved_seq.append(dict(asset=c_key, name=c_name, duration=dur, speed=spd, source_start=source_start))
                    else:
                        raise ValueError('Clip entry must reference an asset, library path, or upload.')
                if request.form.get('clear_background') == 'true':
                    assets.pop('background', None)
                    resolved_seq = []
                elif resolved_seq and not request.files.get('background') and not request.form.get('background_path'):
                    assets['background'] = copy.deepcopy(assets[resolved_seq[0]['asset']])
                used_clips = {c['asset'] for c in resolved_seq}
                for k in [k for k in list(assets.keys()) if k.startswith('clip_') and k not in used_clips]:
                    assets.pop(k, None)
                settings['sequence'] = resolved_seq
                composition_model.validate(settings, 7200)
                if request.form.get('clear_broll') == 'true': assets.pop('broll',None)
                if request.form.get('clear_sticker') == 'true': assets.pop('sticker',None)
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
                    bg = assets.get('background')
                    has_audio = False
                    if clean['background_volume']:
                        video_assets = [a for a in assets.values() if isinstance(a, dict) and a.get('kind') == 'video' and a.get('file')]
                        for va in video_assets:
                            v_file = f / va['file']
                            if v_file.is_file():
                                probe = process.run([imageio_ffmpeg.get_ffmpeg_exe(), '-i', str(v_file)], capture_output=True)
                                va['has_audio'] = b'Audio:' in probe.stderr
                                has_audio = has_audio or va['has_audio']
                    studio = composition_model.schema(assets,clean,d['style'])
                    d['status'] = 'Applying background and audio settings…'
                    write(d)
                    ffmpeg(composition_model.render_args(studio,f,output,has_audio,False,include_sticker=False,quality='draft'),f)
                    preview_and_peaks(d,f,output,preview)
                    process.check_cancelled()
                    old_settings = d['studio']['settings']
                    duration = clean['end']-clean['start']+clean['offset']
                    delta = old_settings['start']-clean['start']+clean['offset']-old_settings['offset']
                    cues = composition_model.shift_cues(d['cues'],delta,duration)
                    for fx_key in ('video_filter', 'vignette', 'film_grain', 'sharpen', 'chromatic',
                                   'noise_cancel', 'voice_isolation', 'audio_effect'):
                        d['style'][fx_key] = clean[fx_key]
                    validate_edit(dict(cues=cues,style=d['style']),duration)
                    # Read the saved pre-job peaks: preview generation only modified the worker copy.
                    backup = composition_snapshot(read(pid))
                    d.update(studio=studio,source=output,preview=preview,duration=duration,
                             width=composition_model.SHAPES[clean['shape']][0],height=composition_model.SHAPES[clean['shape']][1],
                             cues=cues,composition={**clean, 'fx_baked': False, 'sticker_baked': False},composition_backup=backup,missing_assets=[])
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

    @bp.post('/api/captions/<pid>/track-face')
    def track_face(pid):
        incoming = request.get_json() or {}
        time_sec = float(incoming.get('time', 0.0))
        target = str(incoming.get('target', 'head')).lower()
        if target not in {'head', 'eyes', 'center'}:
            target = 'head'
        with lock:
            data = read(pid)
            f = folder(pid)
            candidates = [
                f / data.get('preview', 'preview.mp4'),
                f / 'preview.mp4',
                f / data.get('source', 'original.mp4'),
                f / 'original.mp4'
            ]
            if data.get('studio', {}).get('assets', {}).get('background', {}).get('file'):
                candidates.append(f / data['studio']['assets']['background']['file'])
            video_file = next((p for p in candidates if p.exists() and p.is_file()), None)
            if not video_file:
                return jsonify(found=False, message='No video file found in this project to track.')
        result = detect_face_in_video(video_file, time_sec=time_sec, target=target)
        return jsonify(result)

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
            settings = incoming.get('translation_settings',data.get('translation_settings',{}))
            if not isinstance(settings,dict): raise ValueError('Invalid translation settings.')
            data['translation_settings'] = {key:str(settings.get(key,''))[:limit] for key,limit in [('notes',4000),('glossary',4000),('model',200)]}
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
            if options.get('only_review'):
                indices = [i for i in indices if not data['cues'][i].get('words') or data['cues'][i].get('karaoke',{}).get('state') in {'review','estimated','edited'}]
            if not indices:
                raise ValueError('No lines need another timing pass.')
            def work(d, f):
                model = get_whisper()
                if model is None:
                    raise ValueError('Install the AI Pack in the Studio to add karaoke timing.')
                # Decode once, then read bounded cue slices rather than loading a full song into RAM.
                audio_file = f / 'karaoke.wav'
                pending = copy.deepcopy(d['cues'])
                progress_file = f / 'karaoke-progress.json'
                signature = hashlib.sha256(json.dumps([d['source'], language, pending],ensure_ascii=False).encode()).hexdigest()
                completed = set()
                if options.get('resume'):
                    if not progress_file.exists():
                        raise ValueError('No interrupted karaoke job to resume. Use Add Karaoke or Retry uncertain lines.')
                    progress = json.loads(progress_file.read_text(encoding='utf-8'))
                    if progress.get('signature') != signature:
                        raise ValueError('Lyrics, timing, audio or language changed. Start a new karaoke pass.')
                    recovered = validate_edit(dict(cues=progress['cues']),d['duration'])['cues']
                    completed = {i for i in progress['completed'] if type(i) is int and 0 <= i < len(pending)}
                    for i in completed:
                        pending[i] = recovered[i]
                try:
                    ffmpeg(['-i', d['source'], '-t', str(d['duration']), '-vn', '-ac', '1',
                            '-ar', '16000', '-c:a', 'pcm_s16le', audio_file.name], f)
                    with wave.open(str(audio_file), 'rb') as audio:
                        for count, i in enumerate(indices):
                            process.check_cancelled()
                            if i in completed:
                                continue
                            cue = pending[i]
                            greek = bool(re.search(r'[\u0370-\u03ff\u1f00-\u1fff]', cue['text']))
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
                                process.check_cancelled()
                                aligned = aligned_cues(result, [cue['text']], cue['start'], d['duration'], cue['end']-cue['start'], recover=True)[0]
                                words = aligned['words']
                                notes = [aligned['karaoke']['note']] if aligned.get('karaoke',{}).get('state') == 'review' else []
                                if any(w['end']-w['start'] < .06 for w in words):
                                    notes.append('Very short word timings; check against the vocals.')
                                if any(w['end']-w['start'] > 4.0 for w in words) and not any('stretched' in n for n in notes):
                                    notes.append('Long stretched word timing detected (sustained note or instrumental gap); listen and check this line.')
                                if has_mixed_lyric_scripts(cue['text']) or language in composition_model.MIXED:
                                    notes.append('Mixed-language selection; check timing or retry this line with a language override.')
                                if words:
                                    c_s, c_e = float(cue['start']), float(cue['end'])
                                    prev_w = c_s
                                    n_w = len(words)
                                    for idx, w in enumerate(words):
                                        w['start'] = max(prev_w, min(c_e - 0.001 * (n_w - idx), float(w['start'])))
                                        w['end'] = max(w['start'] + 0.001, min(c_e - 0.001 * (n_w - 1 - idx), float(w['end'])))
                                        prev_w = w['end']
                                cue['words'] = words
                                cue['karaoke'] = dict(state='review' if notes else 'aligned', note=' '.join(notes), language=chosen)
                            except (ValueError, KeyError, TypeError) as exc:
                                process.check_cancelled()
                                note = str(exc)[:220] + (' Existing word timings were kept.' if cue['words'] else ' No word timings were added.')
                                cue['karaoke'] = dict(state='review', note=note, language=chosen)
                            completed.add(i)
                            progress_temp = progress_file.with_suffix('.tmp')
                            progress_temp.write_text(json.dumps(dict(signature=signature,cues=pending,completed=sorted(completed)),ensure_ascii=False),encoding='utf-8')
                            os.replace(progress_temp,progress_file)
                            d['status'] = f'Adding karaoke timing: {count+1}/{len(indices)} lines. Changes apply when the job finishes.'
                            write(d)
                    pending = validate_edit(dict(cues=pending, style=d['style']), d['duration'])['cues']
                    process.check_cancelled()
                    d['karaoke_backup'] = dict(cues=copy.deepcopy(d['cues']), timing=d['timing'])
                    d['cues'] = pending
                    progress_file.unlink(missing_ok=True)
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

    def propose_lyrics(data, cues, options):
        lyric_tracks.ensure_ids(cues,data['id'])
        validate_edit(dict(cues=cues), data['duration'])
        if options.get('review'):
            data['lyric_proposal'] = dict(id=uuid.uuid4().hex, signature=lyric_signature(data),
                                         cues=cues, start=options.get('start', 0),
                                         end=options.get('end', data['duration']))
            data['_completion_notice'] = 'Lyrics are ready to review. Saved captions have not changed.'
        else:
            data['karaoke_backup'] = dict(cues=copy.deepcopy(data['cues']), timing=data['timing'])
            data.update(cues=cues, timing='aligned')
            data.pop('lyric_proposal', None)

    @bp.post('/api/captions/<pid>/lyric-proposal')
    def accept_lyrics(pid):
        with lock:
            data = read(pid)
            options = request.get_json() or {}
            proposal = data.get('lyric_proposal')
            if data['state'] == 'busy' or options.get('revision') != data['revision']:
                return jsonify(error='Project changed. Reload before reviewing lyrics.'), 409
            if not proposal or options.get('id') != proposal['id']:
                return jsonify(error='This lyric proposal is no longer available.'), 409
            if options.get('action') not in {'apply', 'discard'}:
                raise ValueError('Choose Apply or Discard.')
            if options['action'] == 'apply':
                if proposal['signature'] != lyric_signature(data):
                    return jsonify(error='Captions or audio changed. Discard this proposal and sync again.'), 409
                cues = validate_edit(dict(cues=proposal['cues']), data['duration'])['cues']
                data['karaoke_backup'] = dict(cues=copy.deepcopy(data['cues']), timing=data['timing'])
                data.update(cues=cues, timing='aligned')
            data.pop('lyric_proposal')
            data.update(revision=data['revision'] + 1, state='ready',
                        status='Lyrics applied' if options['action'] == 'apply' else 'Proposal discarded; saved captions kept')
            write(data)
            return jsonify(data)

    @bp.post('/api/captions/<pid>/align')
    def align(pid):
        with lock:
            data = read(pid)
            if data['state'] == 'busy':
                return jsonify(error='Wait for the current task.'), 409
            options = request.get_json()
            if 'revision' in options and options['revision'] != data['revision']:
                return jsonify(error='Project changed. Reload before syncing lyrics.'), 409
            lines = lyric_lines(options.get('text', ''))
            language = options.get('language', '')
            if language not in {'auto', *composition_model.LANGUAGES, *composition_model.MIXED}:
                raise ValueError('Choose a supported lyric language or mixed-language pair.')
            start = number(options.get('start', 0), 0, data['duration'])
            end = number(options.get('end', data['duration']), 0, data['duration'])
            if end - start < .1 or end - start > 1200:
                raise ValueError('Select an audio range between 0.1 seconds and 20 minutes.')
            if any(c['start'] < start < c['end'] or c['start'] < end < c['end'] for c in data['cues']):
                raise ValueError('Choose range boundaries between caption lines so existing captions can be preserved.')
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
                    progress_file = f / 'lyric-sync-progress.json'
                    signature = hashlib.sha256(json.dumps([lyric_signature(d), lines, language, start, end]).encode()).hexdigest()
                    completed = 0
                    if options.get('resume'):
                        if not progress_file.exists():
                            raise ValueError('No interrupted lyric sync is available. Start a new sync.')
                        saved = json.loads(progress_file.read_text(encoding='utf-8'))
                        if saved.get('signature') != signature:
                            raise ValueError('Lyrics, language, range or project changed. Start a new sync.')
                        cues = validate_edit(dict(cues=saved['cues']), d['duration'])['cues']
                        if [c['text'] for c in cues] != lines:
                            raise ValueError('Lyric checkpoint text differs. Start a new sync.')
                        completed = saved['completed']
                        if type(completed) is not int or not 0 <= completed <= len(cues):
                            raise ValueError('Invalid lyric checkpoint. Start a new sync.')
                    else:
                        coarse_language=language if language in composition_model.LANGUAGES else detect_caption_language(model,samples[:480000],composition_model.MIXED.get(language))
                        try:
                            result = align_lyrics(model, samples, '\n'.join(lines), coarse_language)
                            cues = aligned_cues(result, lines, start, d['duration'], end-start, recover=True)
                        except ValueError:
                            if not options.get('sections'): raise
                            # Speech timestamps can provide approximate section anchors when forced alignment fails.
                            # These remain explicitly reviewable; an LLM never invents timestamps.
                            process.check_cancelled()
                            transcript=transcribe(model,samples,word_timestamps=True,language=coarse_language)
                            anchors=[]
                            for seg in transcript.get('segments',[]):
                                a=max(anchors[-1]['end'] if anchors else 0,float(seg['start']))
                                b=min(end-start,float(seg['end']))
                                if b>a and str(seg['text']).strip(): anchors.append(dict(start=a,end=b,text=str(seg['text']).strip(),words=[]))
                            if not anchors: raise ValueError('No reliable vocal sections found. Choose a shorter matching range; saved captions are unchanged.')
                            cues=match_lyrics_to_transcription(anchors,lines,end-start,language=coarse_language)
                            cues=composition_model.shift_cues(cues,start,d['duration'])
                            for cue in cues: cue['karaoke']=dict(state='review',note='Recovered section from transcription; verify its placement against the song.')
                        process.check_cancelled()
                        if options.get('sections'):
                            save_lyric_progress(progress_file, signature, cues, 0)
                    if options.get('sections'):
                        for i in range(completed, len(cues)):
                            process.check_cancelled()
                            cue = cues[i]
                            # The first pass supplies audio anchors; never divide a song evenly.
                            length = cue['end'] - cue['start']
                            try:
                                if length > 60:
                                    raise ValueError('Long section: split this line before retrying karaoke timing.')
                                chunk = samples[max(0, round((cue['start']-start)*16000)):
                                                min(len(samples), round((cue['end']-start)*16000))]
                                if not chunk.size or np.max(np.abs(chunk)) < .0001:
                                    raise ValueError('No audible audio inside this section.')
                                chosen=language
                                if language=='auto' or language in composition_model.MIXED:
                                    if re.search(r'[\u0370-\u03ff\u1f00-\u1fff]',cue['text']): chosen='el'
                                    elif re.search(r'[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]',cue['text']): chosen='ko'
                                    else: chosen=detect_caption_language(model,chunk,composition_model.MIXED.get(language))
                                result = align_caption_words(model, chunk, cue['text'], chosen)
                                process.check_cancelled()
                                refined = aligned_cues(result, [cue['text']], cue['start'], d['duration'], length, recover=True)[0]
                                validate_edit(dict(cues=[refined]), d['duration'])
                                # Refining uncertain anchors cannot certify the original placement.
                                if any(w['end']-w['start'] < .06 for w in refined['words']):
                                    refined['karaoke'] = dict(state='review', note='Very short word timings; check against the vocals.')
                                if any(w['end']-w['start'] > 4.0 for w in refined['words']):
                                    refined['karaoke'] = dict(state='review', note='Long stretched word timing detected (sustained note or instrumental gap); listen and check this line.')
                                if has_mixed_lyric_scripts(cue['text']):
                                    refined['karaoke'] = dict(state='review', note='Mixed-language line; check timing or retry this line with a language override.')
                                if cue.get('karaoke', {}).get('state') == 'review' and 'stretched' not in cue.get('karaoke', {}).get('note', ''):
                                    refined['karaoke'] = dict(state='review', note='First-pass placement was uncertain; listen and check this line.')
                                cues[i] = refined
                            except (ValueError, KeyError, TypeError) as exc:
                                process.check_cancelled()
                                cue['karaoke'] = dict(state='review', note='First-pass timing retained. ' + str(exc)[:180])
                            process.check_cancelled()
                            save_lyric_progress(progress_file, signature, cues, i+1)
                            d['status'] = f'Refining lyric sections: {i+1}/{len(cues)}. Saved captions are kept until review.'
                            write(d)
                    process.check_cancelled()
                    outside = [c for c in d['cues'] if c['end'] <= start or c['start'] >= end]
                    combined = sorted(outside + cues, key=lambda c:c['start'])
                    propose_lyrics(d, combined, options)
                    if not options.get('review'):
                        flagged = sum(c.get('karaoke',{}).get('state') == 'review' for c in cues)
                        d['_completion_notice'] = f'Lyrics updated. {flagged} lines need timing review.'
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
            if 'revision' in options and options['revision'] != data['revision']:
                return jsonify(error='Project changed. Reload before syncing lyrics.'), 409
            lines = lyric_lines(options.get('text', ''))
            language = options.get('language', '')
            start = number(options.get('start', 0), 0, data['duration'])
            end = number(options.get('end', data['duration']), start, data['duration'])
            selected_cues = [c for c in data['cues'] if c['start'] >= start and c['end'] <= end]
            if not selected_cues:
                raise ValueError('Choose a range containing complete caption lines.')
            if any(c['start'] < start < c['end'] or c['start'] < end < c['end'] for c in data['cues']):
                raise ValueError('Choose range boundaries between caption lines.')
            def work(d, f):
                process.check_cancelled()
                shifted = composition_model.shift_cues(selected_cues, -start, end-start)
                matched = match_lyrics_to_transcription(shifted, lines, end-start, language=language)
                matched = composition_model.shift_cues(matched, start, d['duration'])
                outside = [c for c in d['cues'] if c['end'] <= start or c['start'] >= end]
                matched = sorted(outside + matched,key=lambda c:c['start'])
                validate_edit(dict(cues=matched),d['duration'])
                process.check_cancelled()
                propose_lyrics(d, matched, options)
                if not options.get('review'):
                    flagged = sum(c.get('karaoke', {}).get('state') == 'review' for c in matched)
                    d['_completion_notice'] = f'Transcription updated with your lyrics ({len(matched)} lines). {flagged} lines need timing review.'
            return launch(data, 'Matching your lyrics to the existing transcription timings…', work)

    @bp.post('/api/captions/<pid>/render')
    def render(pid):
        with lock:
            data = read(pid)
            options = request.get_json()
            if data['state'] == 'busy':
                return jsonify(error='Wait for the current task.'), 409
            fx_keys = ('video_filter', 'vignette', 'film_grain', 'sharpen', 'chromatic',
                       'noise_cancel', 'voice_isolation', 'audio_effect', 'visualizer')
            has_fx = any(data.get('style', {}).get(k, DEFAULT_STYLE[k]) != DEFAULT_STYLE[k] for k in fx_keys)
            if not data['cues'] and not data.get('composition') and not has_fx:
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
                    for filename in CUSTOM_FONTS.values():
                        cf = CUSTOM_FONT_DIR / filename
                        if cf.is_file():
                            shutil.copy2(cf, fonts / filename)
                    style_cfg = {**DEFAULT_STYLE, **d.get('style', {})}
                    baked = d.get('composition') if isinstance(d.get('composition'), dict) else {}
                    fx_already_baked = baked.get('fx_baked', True)
                    render_fx = {
                        k: (DEFAULT_STYLE[k] if (fx_already_baked and style_cfg[k] == baked.get(k, DEFAULT_STYLE[k])) else style_cfg[k])
                        for k in ('video_filter', 'vignette', 'film_grain', 'sharpen', 'chromatic',
                                  'noise_cancel', 'voice_isolation', 'audio_effect')
                    }
                    if q_spec.get('max_side') == 720:
                        scale_vf = "scale=w='min(720,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
                    elif q_spec.get('max_side') == 2160:
                        scale_vf = "scale=w='if(gt(iw,ih),3840,2160)':h='if(gte(iw,ih),2160,3840)':force_original_aspect_ratio=increase:force_divisible_by=2"
                    else:
                        scale_vf = 'scale=trunc(iw/2)*2:trunc(ih/2)*2'
                    if q_spec.get('fps'):
                        scale_vf += f",fps={q_spec['fps']}"
                    vf_chain = [*composition_model.video_fx_chain(render_fx), f'ass={ass.name}:fontsdir=caption_fonts', scale_vf]
                    af_chain = composition_model.audio_fx_chain(render_fx)
                    args = ['-i', d['source'], '-map', '0:v:0', '-map', '0:a:0?', '-vf', ','.join(vf_chain)]
                    if af_chain:
                        args += ['-af', ','.join(af_chain)]
                    if d.get('composition') and d.get('studio'):
                        # Render original assets in one pass, avoiding another encode of the preview.
                        studio = copy.deepcopy(d['studio'])
                        for key in ('video_filter', 'vignette', 'film_grain', 'sharpen', 'chromatic',
                                    'noise_cancel', 'voice_isolation', 'audio_effect'):
                            studio['settings'][key] = style_cfg[key]
                        has_audio = False
                        for asset in studio['assets'].values():
                            if asset.get('kind') == 'video' and 'has_audio' not in asset:
                                probe = process.run([imageio_ffmpeg.get_ffmpeg_exe(), '-i', str(composition_model.local_asset(f,asset))],capture_output=True)
                                asset['has_audio'] = b'Audio:' in probe.stderr
                            has_audio = has_audio or bool(asset.get('has_audio'))
                        size = composition_model.SHAPES[studio['settings']['shape']]
                        if quality == '4k':
                            size = tuple(x*2 for x in size)
                        fps = 60 if quality == '60fps' else 30
                        composed = composition_model.render_args(studio,f,temporary.name,has_audio,True,fps=fps,output_size=size)
                        # Keep inputs, graph and maps; apply the chosen encoder below.
                        args = composed[:composed.index('-c:v')]
                        gi = args.index('-filter_complex')+1
                        args[gi] = args[gi].replace('[out]', '[composed]') + f';[composed]ass={ass.name}:fontsdir=caption_fonts,{scale_vf}[out]'
                        if preview:
                            ti = args.index('-t', args.index('-filter_complex'))
                            args[ti+1] = str(min(5,d['duration']-start))
                    if preview:
                        args += ['-ss', str(start), '-t', str(min(5, d['duration']-start))]
                    try:
                        from assets import hwaccel
                        enc_args = hwaccel.get_video_encoder_args(codec='h264', quality=quality, force_cpu=bool(options.get('force_cpu')))
                    except Exception:
                        enc_args = ['-c:v', 'libx264', '-preset', q_spec['preset'], '-crf', q_spec['crf']]
                    completed_encoder = ffmpeg([*args, *enc_args, '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', q_spec['audio_bitrate'], '-movflags', '+faststart', temporary.name], f)
                    os.replace(temporary, f / output)
                    d['exports'].append(output)
                    d['last_render'] = output
                    d['_completion_notice'] = f'Export ready ({completed_encoder or "CPU"}).'
                finally:
                    ass.unlink(missing_ok=True)
                    temporary.unlink(missing_ok=True)
            return launch(data, 'Rendering five-second check…' if preview else 'Exporting captioned video…', work)

    @bp.post('/api/captions/<pid>/layout')
    def caption_layout(pid):
        data=read(pid);incoming=request.get_json() or {}
        cleaned=validate_edit(dict(cues=[incoming['cue']],style=incoming.get('style',data['style'])),data['duration'])
        return jsonify(rows=layout_rows(cleaned['cues'][0],{**cleaned['style'],**cleaned['cues'][0].get('style_override',{})},data['width'],data['height']))

    @bp.get('/api/captions/translation-models')
    def translation_models():
        return jsonify(models=lyric_translation.models())

    @bp.post('/api/captions/<pid>/translation-setup')
    def setup_translation_model(pid):
        with lock:
            data = read(pid)
            options = request.get_json() or {}
            if data['state'] == 'busy' or options.get('revision') != data['revision']:
                return jsonify(error='Project changed or is processing. Save and reload first.'), 409
            lyric_translation.require_local_runtime()
            def work(d, f):
                def progress(message):
                    d['status'] = message
                    write(d)
                lyric_translation.install_model(progress)
                d.setdefault('translation_settings', {})['model'] = 'qwen3-4b-local'
                d['_completion_notice'] = 'Translation model ready. Choose Translate unlocked lines to create a reviewable proposal.'
            return launch(data, 'Setting up local translation…', work)

    @bp.post('/api/captions/<pid>/translate')
    def translate_project(pid):
        with lock:
            data = read(pid)
            options = request.get_json() or {}
            if data['state']=='busy' or options.get('revision') != data['revision']:
                return jsonify(error='Project changed or is processing. Save and reload first.'),409
            language = options.get('language','en')
            if language not in composition_model.LANGUAGES: raise ValueError('Choose a supported target language.')
            selected = options.get('ids')
            if selected is not None and (not isinstance(selected,list) or any(i not in {c['id'] for c in data['cues']} for i in selected)):
                raise ValueError('Choose valid lyric lines.')
            settings = data.get('translation_settings',{})
            model = settings.get('model','')
            if not model: raise ValueError('Select an installed local model, or enter translations manually.')
            def work(d,f):
                originals = d['cues']
                pending = [c for c in originals if (selected is None or c['id'] in selected)
                           and not c.get('translations',{}).get(language,{}).get('locked')]
                if not pending: raise ValueError('No unlocked lines selected for translation.')
                signature = hashlib.sha256(json.dumps([lyric_signature(d),settings,language,selected],sort_keys=True).encode()).hexdigest()
                path = f/'translation-progress.json'
                done = {}
                if options.get('resume'):
                    if not path.exists(): raise ValueError('No interrupted translation is available.')
                    saved = json.loads(path.read_text(encoding='utf-8'))
                    if saved.get('signature') != signature: raise ValueError('Lyrics or translation settings changed. Start a new translation.')
                    done = saved['done']
                # Carry user-approved chorus choices into identical repeated lines.
                chorus = {c['text']:t for c in originals if (t:=c.get('translations',{}).get(language))
                          and t.get('status')=='approved' and t.get('source')==lyric_tracks.source_hash(c['text'])}
                for c in pending:
                    if c['id'] in done:
                        chorus.setdefault(c['text'], done[c['id']])
                for offset in range(0,len(pending),8):
                    process.check_cancelled()
                    group = [c for c in pending[offset:offset+8] if c['id'] not in done]
                    request_lines = []
                    representatives = {}
                    for c in group:
                        if c['text'] in chorus:
                            done[c['id']] = copy.deepcopy(chorus[c['text']])
                        elif c['text'] not in representatives:
                            representatives[c['text']] = c['id']
                            request_lines.append(dict(id=c['id'],text=c['text']))
                    if request_lines:
                        first = originals.index(group[0]);last = originals.index(group[-1])
                        context = '\n'.join(c['text'] for c in originals[max(0,first-3):last+4])[:12000]
                        d['status']=f'Translating: {len(done)}/{len(pending)} lines (translating lines {offset+1}–{min(offset+8,len(pending))}…)'
                        write(d)
                        answer = lyric_translation.translate(request_lines,context,composition_model.LANGUAGES[language],model,
                                                              settings.get('notes',''),settings.get('glossary',''))
                        process.check_cancelled()
                        done.update(answer)
                        for text, cue_id in representatives.items():
                            chorus[text] = copy.deepcopy(answer[cue_id])
                        for c in group:
                            done[c['id']] = copy.deepcopy(chorus[c['text']])
                    temporary=path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(dict(signature=signature,done=done),ensure_ascii=False),encoding='utf-8')
                    os.replace(temporary,path)
                    d['status']=f'Translating: {min(offset+8,len(pending))}/{len(pending)} lines. Saved translations are unchanged.'
                    write(d)
                d['translation_proposal']=dict(id=uuid.uuid4().hex,signature=lyric_signature(d),language=language,lines=done)
                d['_completion_notice']='Translation ready to review. Original lyrics and accepted translations are unchanged.'
            return launch(data,'Translating locally…',work)

    @bp.post('/api/captions/<pid>/translation-proposal')
    def apply_translation(pid):
        with lock:
            d=read(pid);options=request.get_json() or {};proposal=d.get('translation_proposal')
            if d['state']=='busy' or options.get('revision')!=d['revision'] or not proposal or proposal['id']!=options.get('id'):
                return jsonify(error='Project or proposal changed. Reload before applying.'),409
            if options.get('action') not in {'apply','discard'}: raise ValueError('Choose Apply or Discard.')
            if options['action']=='apply':
                if proposal['signature']!=lyric_signature(d): return jsonify(error='Lyrics changed. Regenerate this translation.'),409
                edits=options.get('lines',proposal['lines'])
                if not isinstance(edits,dict) or set(edits)!=set(proposal['lines']): raise ValueError('Translation lines must match the proposal.')
                updated=copy.deepcopy(d['cues']);language=proposal['language']
                for c in updated:
                    if c['id'] in edits:
                        entry=edits[c['id']]
                        if not isinstance(entry,dict): raise ValueError('Invalid translation.')
                        if c.get('translations',{}).get(language,{}).get('locked'): continue
                        c.setdefault('translations',{})[language]=dict(text=entry.get('text',''),source=lyric_tracks.source_hash(c['text']),
                            status='approved',locked=bool(entry.get('locked',False)),note=entry.get('note',''))
                updated=validate_edit(dict(cues=updated),d['duration'])['cues']
                d['karaoke_backup']=dict(cues=copy.deepcopy(d['cues']),timing=d['timing'])
                d['cues']=updated
            d.pop('translation_proposal');d['revision']+=1;d.update(state='ready',status='Translation applied' if options['action']=='apply' else 'Translation proposal discarded')
            write(d);return jsonify(d)

    @bp.get('/api/captions/<pid>/ass')
    def export_ass(pid):
        data=read(pid)
        return send_file(io.BytesIO(ass_text(data).encode('utf-8-sig')),mimetype='text/plain',as_attachment=True,download_name='captions.ass')

    @bp.get('/api/captions/<pid>/srt')
    def export_srt(pid):
        data = read(pid)
        cues=lyric_tracks.export_cues(data['cues'],request.args.get('language','en'),request.args.get('mode','original'))
        return send_file(io.BytesIO(srt_text(cues).encode('utf-8-sig')), mimetype='application/x-subrip', as_attachment=True, download_name='captions.srt')

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
        process.begin_job()
        job_started()
        try:
            results = composition_model.search_stock(
                provider=provider,
                query=str(payload.get('query', '')),
                kind=str(payload.get('kind', 'video')),
                orientation=str(payload.get('orientation', 'portrait')),
                max_duration=float(payload.get('max_duration') or 0),
                api_key=api_key
            )
            process.check_cancelled()
        finally:
            process.end_job()
            job_finished()
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
        if provider == 'youtube':
            found, _ = _grab_social_video(dl_url, prefix='youtube')
            return jsonify(path=str(found), name=found.name, kind='video', provenance=prov)
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
        job_started()
        try:
            composition_model.download_stock_asset(dl_url, provider, kind, dest, check_cancel=process.check_cancelled)
        finally:
            process.end_job()
            job_finished()
        refresh_gallery()
        return jsonify(path=str(dest), name=dest.name, kind=kind, provenance=prov)

    def _grab_social_video(raw_url: str, prefix: str = 'social') -> tuple[Path, str]:
        parsed = urllib.parse.urlsplit(raw_url)
        host = (parsed.hostname or '').lower()
        platforms = ('youtube.com', 'youtu.be', 'tiktok.com', 'instagram.com')
        if (parsed.scheme != 'https' or parsed.username or parsed.password
                or parsed.port not in (None, 443)
                or not any(host == domain or host.endswith('.' + domain) for domain in platforms)):
            raise ValueError('Use an HTTPS TikTok, Instagram, or YouTube video link.')
        stock_dir.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex[:8]
        node_exe = Path(__file__).resolve().parent / 'node_runtime' / 'node.exe'
        process.begin_job()
        job_started()
        try:
            with tempfile.TemporaryDirectory(prefix='.grab-', dir=stock_dir) as scratch:
                args = [sys.executable, str(Path(__file__).with_name('social_worker.py')), '--ignore-config', '--no-playlist',
                        '--proxy', '',
                        '--use-extractors', 'youtube.*,tiktok.*,instagram.*',
                        '--no-progress', '--no-warnings', '--socket-timeout', '10',
                        '--retries', '2', '--fragment-retries', '2',
                        '--max-filesize', '80M', '--match-filter', '!is_live & duration <= 1200',
                        '--format', 'bestvideo[height<=1920]+bestaudio/best[height<=1920]',
                        '--merge-output-format', 'mp4', '--ffmpeg-location', imageio_ffmpeg.get_ffmpeg_exe(),
                        '--print', 'after_move:%(title)j',
                        '--js-runtimes', ('node:' + str(node_exe)) if node_exe.is_file() else 'node',
                        '-o', str(Path(scratch) / 'clip.%(ext)s'), '--', raw_url]
                result = process.run(args, capture_output=True, timeout=180)
                process.check_cancelled()
                if result.returncode:
                    raise ValueError((result.stderr or b'').decode('utf-8', errors='replace')[-500:])
                videos = [p for p in Path(scratch).iterdir() if p.suffix.lower() in composition_model.VIDEOS]
                if len(videos) != 1:
                    raise ValueError('No supported video downloaded. Choose a non-live clip under 20 minutes and 80 MB.')
                if videos[0].stat().st_size > 80 * 1024 * 1024:
                    raise ValueError('The downloaded clip exceeds 80 MB.')
                found = stock_dir / f'{prefix}_{token}{videos[0].suffix.lower()}'
                videos[0].replace(found)
                try:
                    title = str(json.loads(result.stdout.decode('utf-8').strip().splitlines()[-1]))[:80]
                except (ValueError, IndexError, UnicodeError):
                    title = found.stem
        except Exception as exc:
            msg = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', str(exc))
            raise ValueError(f'Could not grab video from URL: {msg[:200]}') from None
        finally:
            process.end_job()
            job_finished()
        refresh_gallery()
        return found, title

    @bp.post('/api/captions/stock/grab-url')
    def stock_grab_url():
        payload = request.get_json() or {}
        if not isinstance(payload, dict):
            raise ValueError('Invalid clip URL request.')
        raw_url = str(payload.get('url') or '').strip()
        parsed = urllib.parse.urlsplit(raw_url)
        host = (parsed.hostname or '').lower()
        if parsed.scheme not in {'http', 'https'} or not host or host in {'localhost', '127.0.0.1', '0.0.0.0', '::1'}:
            raise ValueError('Paste a valid TikTok, Instagram, or YouTube video URL.')
        found, title = _grab_social_video(raw_url, prefix='social')
        return jsonify(path=str(found), name=found.name, title=title, kind='video')

    @bp.get('/api/captions/fonts')
    def get_available_fonts():
        refresh_custom_fonts()
        return jsonify(
            bundled=list(BUNDLED_FONTS.keys()),
            custom=[{'family': k, 'filename': v, 'url': f'/api/captions/fonts/file/{v}'} for k, v in CUSTOM_FONTS.items()],
            all=sorted(FONTS)
        )

    @bp.get('/api/captions/fonts/file/<name>')
    def custom_font_file(name):
        if name not in CUSTOM_FONTS.values() or Path(name).name != name:
            return jsonify(error='Font not found.'), 404
        return send_file(CUSTOM_FONT_DIR / name)

    @bp.post('/api/captions/fonts/upload')
    def upload_custom_font():
        if 'font_file' not in request.files:
            raise ValueError('No font file provided.')
        file = request.files['font_file']
        if not file or not file.filename:
            raise ValueError('No file selected.')
        ext = Path(file.filename).suffix.lower()
        if ext not in ('.ttf', '.otf'):
            raise ValueError('Only .ttf and .otf font files are supported.')
        raw_bytes = file.read(26 * 1024 * 1024)
        if len(raw_bytes) > 25 * 1024 * 1024:
            raise ValueError('Font file exceeds maximum size of 25MB.')
        if not (raw_bytes.startswith(b'\x00\x01\x00\x00') or
                raw_bytes.startswith(b'OTTO') or
                raw_bytes.startswith(b'true') or
                raw_bytes.startswith(b'typ1') or
                raw_bytes.startswith(b'ttcf')):
            raise ValueError('Invalid font file format. Please upload a valid TrueType or OpenType font.')

        safe_stem = re.sub(r'[^a-zA-Z0-9_\-\s]', '', Path(file.filename).stem).strip()
        fallback_family = re.sub(r'[_\-]+', ' ', safe_stem).strip() or 'Custom Font'
        family_name = fallback_family

        try:
            f = ImageFont.truetype(io.BytesIO(raw_bytes), 32)
            name_tuple = f.getname()
            if name_tuple and name_tuple[0]:
                extracted = str(name_tuple[0]).strip()
                if extracted:
                    family_name = extracted
        except Exception as e:
            raise ValueError(f'Could not parse font: {e}')

        CUSTOM_FONT_DIR.mkdir(parents=True, exist_ok=True)
        if family_name in BUNDLED_FONTS and (FONT_DIR / BUNDLED_FONTS[family_name]).read_bytes() != raw_bytes:
            raise ValueError('This family is bundled with the app. Choose a different family to preserve existing projects.')
        if family_name in {'Arial', 'Verdana', 'Georgia', 'Impact', 'Trebuchet MS'}:
            raise ValueError('This family is a system font used by existing projects. Choose a different family.')
        safe_filename = hashlib.sha256(raw_bytes).hexdigest() + ext
        existing = CUSTOM_FONTS.get(family_name)
        if existing and (CUSTOM_FONT_DIR / existing).read_bytes() != raw_bytes:
            raise ValueError("A different font with this family name is already installed. Existing projects have been preserved.")
        dest_path = CUSTOM_FONT_DIR / safe_filename
        dest_path.write_bytes(raw_bytes)

        CUSTOM_FONTS[family_name] = safe_filename
        FONTS.add(family_name)
        return jsonify(
            success=True,
            family=family_name,
            filename=safe_filename,
            url=f'/api/captions/fonts/file/{safe_filename}'
        )

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
