"""Versioned local composition model and shared FFmpeg render specification.

All timeline values use seconds from output zero. Assets are immutable local
basenames. Caption edits remain in the enclosing project for backwards reading.
"""
import copy, html
import json
import math
import os
import re
import time
import sys
import job_process as process
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LANGUAGES = {'en':'English', 'fr':'French', 'ko':'Korean', 'el':'Greek', 'es':'Spanish',
             'de':'German', 'it':'Italian', 'pt':'Portuguese', 'ja':'Japanese',
             'zh':'Chinese', 'ar':'Arabic', 'hi':'Hindi', 'ru':'Russian', 'tr':'Turkish'}
MIXED = {'en-fr':('en','fr'), 'en-ko':('en','ko'), 'en-fr-ko':('en','fr','ko')}
SHAPES = {'portrait':(1080,1920), 'square':(1080,1080), 'landscape':(1920,1080)}
IMAGES = {'.png','.jpg','.jpeg','.webp'}
VIDEOS = {'.mp4','.mov','.mkv','.webm','.avi','.m4v'}
AUDIO = {'.mp3','.wav','.m4a','.flac','.ogg'}
VISUALIZER_STYLES = {'waveform', 'spectrum'}
VISUALIZER_POSITIONS = {'bottom', 'center', 'top'}
RENDER_QUALITIES = {
    'draft': dict(preset='veryfast', crf='24', audio_bitrate='160k', max_side=720, fps=0),
    'standard': dict(preset='fast', crf='18', audio_bitrate='256k', max_side=0, fps=0),
    'high': dict(preset='medium', crf='15', audio_bitrate='320k', max_side=0, fps=0),
    '60fps': dict(preset='fast', crf='17', audio_bitrate='320k', max_side=0, fps=60),
    '4k': dict(preset='medium', crf='15', audio_bitrate='320k', max_side=2160, fps=0),
}
VIDEO_FILTERS = {
    'none': '',
    'bw': 'hue=s=0',
    'sepia': 'colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131',
    'vintage': 'curves=vintage,vignette=PI/4',
    'cyberpunk': 'eq=contrast=1.25:saturation=1.6,colorbalance=rs=-0.15:gs=-0.05:bs=0.25:rh=0.2:gh=-0.1:bh=0.25',
    'warm': 'colorbalance=rs=0.12:gs=0.04:bs=-0.12:rm=0.1:gm=0.03:bm=-0.1,eq=saturation=1.15',
    'cool': 'colorbalance=rs=-0.12:gs=0.02:bs=0.16:rm=-0.08:gm=0.02:bm=0.12,eq=contrast=1.08',
    'dramatic': 'eq=contrast=1.35:brightness=-0.04:saturation=0.85,vignette=PI/4',
    'dreamy': 'gblur=sigma=1.2,eq=brightness=0.06:contrast=0.95:saturation=1.2',
}
CAPTION_ANIMATIONS = {'none', 'fade', 'pop', 'slide_up', 'typewriter', 'zoom_in'}
SEQUENCE_TRANSITIONS = {'none', 'fade', 'dissolve', 'fadeblack', 'fadewhite', 'slideleft', 'slideright', 'circlecrop', 'wipeleft', 'wiperight'}
AUDIO_EFFECTS = {
    'none': '',
    'echo': 'aecho=0.8:0.88:220:0.4',
    'concert_hall': 'aecho=0.8:0.9:500|1000:0.3|0.2',
    'studio_vocal': 'highpass=f=80,afftdn=nf=-22,acompressor=threshold=-16dB:ratio=3:makeup=2,equalizer=f=4500:t=q:w=1.2:g=3,aecho=0.8:0.88:90:0.18',
    'lofi_radio': 'highpass=f=400,lowpass=f=3200,acompressor=threshold=-15dB:ratio=4,afftdn=nf=-20',
    'bass_boost': 'bass=g=8:f=110:w=0.6,acompressor=threshold=-14dB:ratio=2',
    'chorus': 'chorus=0.7:0.9:55:0.4:0.25:2',
    'slowed_reverb': 'aresample=44100,asetrate=38808,aresample=44100,atempo=1.13636,aecho=0.8:0.88:350|700:0.35|0.25',
    'nightcore': 'aresample=44100,asetrate=50715,aresample=44100,atempo=0.86957',
    'vocal_remover': 'stereotools=mlev=0.015625',
}
DEFAULTS = dict(shape='portrait', color='#141526', fit='fill', x=50, y=50,
                blur=0, dim=0, overlay='#000000', opacity=0, zoom=0,
                brightness=0, contrast=1, saturation=1, background_speed=1,
                video_filter='none', vignette=False, film_grain=0, sharpen=0, chromatic=0,
                transition_in=0, transition_out=0, keyframe_end_x=50, keyframe_end_y=50,
                title_text='', title_duration=0,
                broll_start=0, broll_duration=0, broll_x=50, broll_y=50,
                broll_scale=100, broll_opacity=1, broll_fade=0,
                start=0, end=0, offset=0, volume=1, fade_in=0, fade_out=0,
                noise_cancel=False, voice_isolation=False, audio_effect='none',
                background_volume=0, ducking=False, loop=True, background_start=0, background_duration=0,
                visualizer=False, visualizer_style='waveform', visualizer_position='bottom',
                visualizer_height=20, visualizer_sensitivity=1, visualizer_color='#bba6ff',
                sequence=[], sequence_transition='none', sequence_transition_duration=0.5)


def video_fx_chain(cfg: dict) -> list[str]:
    """Return FFmpeg video filter expressions for CapCut-style color filters and visual FX."""
    chain: list[str] = []
    preset = VIDEO_FILTERS.get(str(cfg.get('video_filter') or 'none'), '')
    if preset:
        chain.append(preset)
    sharpen = float(cfg.get('sharpen') or 0)
    if sharpen > 0:
        chain.append(f'unsharp=5:5:{sharpen:.2f}:5:5:0.0')
    chromatic = int(round(float(cfg.get('chromatic') or 0)))
    if chromatic > 0:
        chain.append(f'rgbashift=rh=-{chromatic}:bh={chromatic}')
    grain = int(round(float(cfg.get('film_grain') or 0)))
    if grain > 0:
        chain.append(f'noise=alls={grain}:allf=t+u')
    if cfg.get('vignette'):
        chain.append('vignette=PI/4')
    return chain


def audio_fx_chain(cfg: dict) -> list[str]:
    """Return FFmpeg audio filter expressions for noise cancellation, voice isolation, and audio FX."""
    chain: list[str] = []
    if cfg.get('voice_isolation'):
        chain.append('highpass=f=100,lowpass=f=7500,afftdn=nf=-25,equalizer=f=3000:t=q:w=1:g=4,acompressor=threshold=-18dB:ratio=3:makeup=2')
    elif cfg.get('noise_cancel'):
        chain.append('afftdn=nf=-25')
    fx = AUDIO_EFFECTS.get(str(cfg.get('audio_effect') or 'none'), '')
    if fx:
        chain.append(fx)
    return chain


def finite(value, low, high):
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Composition value must be between {low} and {high}.')
    return value


def local_asset(folder, asset):
    name = asset['file']
    if not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name:
        raise ValueError('Invalid media asset path.')
    path = folder / name
    if path.resolve().parent != folder.resolve():
        raise ValueError('Media must stay inside its project.')
    return path


def migrate(project, folder):
    """Derive a new schema without changing the old render or original assets."""
    if 'studio' in project:
        if project['studio'].get('version') != 1:
            raise ValueError('This project needs a newer Creator Studio version.')
        project['studio']['settings'] = {**DEFAULTS, **project['studio'].get('settings', {})}
        return project['studio']
    duration = project['duration']
    old = project.get('composition', {})
    song = next((p for p in sorted(folder.glob('song.*')) if p.suffix.lower() in AUDIO), None)
    bg = next((p for p in sorted(folder.glob('background.*')) if p.suffix.lower() in IMAGES | VIDEOS), None)
    assets = {}
    settings = {**DEFAULTS, **old, 'end':duration}
    settings['shape'] = old.get('shape', 'portrait' if project['height'] > project['width'] else 'square' if project['height'] == project['width'] else 'landscape')
    if song:
        assets['audio'] = dict(file=song.name, kind='audio', duration=duration)
        if bg:
            assets['background'] = dict(file=bg.name, kind='image' if bg.suffix.lower() in IMAGES else 'video')
            if isinstance(old.get('provenance'), dict):
                assets['background']['provenance'] = copy.deepcopy(old['provenance'])
    else:
        # Legacy uploaded videos retain their video/audio as independent track references.
        assets['audio'] = dict(file=project['source'], kind='video', duration=duration)
        assets['background'] = dict(file=project['source'], kind='video')
        settings['loop'] = False
    return schema(assets, settings, project['style'])


def validate_sequence(seq) -> list[dict]:
    if not seq:
        return []
    if not isinstance(seq, list) or len(seq) > 30:
        raise ValueError('A video sequence can contain at most 30 clips.')
    cleaned = []
    for item in seq:
        if not isinstance(item, dict):
            raise ValueError('Invalid clip sequence entry.')
        asset = str(item.get('asset') or '').strip()
        if not re.fullmatch(r'(background|clip_[a-zA-Z0-9_]+)', asset):
            raise ValueError('Invalid clip asset reference.')
        dur = finite(item.get('duration', 0), 0, 1200)
        name = re.sub(r'[\r\n\t]+', ' ', str(item.get('name') or asset)).strip()[:120]
        cleaned.append(dict(asset=asset, name=name, duration=dur))
    return cleaned


def schedule_sequence(seq: list, assets: dict, total_duration: float, loop: bool = True) -> list[dict]:
    valid = [item for item in (seq or []) if isinstance(item, dict) and item.get('asset') in assets and assets[item['asset']].get('kind') in {'video', 'image'}]
    if not valid or (len(valid) == 1 and float(valid[0].get('duration') or 0) <= 0):
        if len(valid) == 1:
            a_key = valid[0]['asset']
            return [dict(asset=a_key, name=str(valid[0].get('name') or assets[a_key]['file'])[:120], start=0.0, duration=round(total_duration, 3))]
        return []
    fixed_sum = sum(float(item['duration']) for item in valid if float(item.get('duration') or 0) > 0)
    auto_count = sum(1 for item in valid if float(item.get('duration') or 0) <= 0)
    if auto_count > 0:
        auto_dur = max(0.2, (total_duration - fixed_sum) / auto_count) if total_duration > fixed_sum else max(0.2, total_duration / len(valid))
    else:
        auto_dur = 5.0
    base = [(item, float(item['duration']) if float(item.get('duration') or 0) > 0 else auto_dur) for item in valid]
    if any(not math.isfinite(d) or d < 0.05 for _, d in base):
        raise ValueError('Each clip duration must be at least 0.05 seconds, or 0 for automatic timing.')
    segments: list[dict] = []
    t = 0.0
    while t < total_duration - 0.05:
        for item, b_dur in base:
            if t >= total_duration - 0.05:
                break
            if len(segments) >= 600:
                raise ValueError('This sequence needs more than 600 cuts. Increase clip durations or shorten the song range.')
            seg_d = min(b_dur, total_duration - t)
            if seg_d < 0.05:
                break
            a_key = item['asset']
            segments.append(dict(
                asset=a_key,
                name=str(item.get('name') or assets[a_key].get('name') or assets[a_key]['file'])[:120],
                start=round(t, 3),
                duration=round(seg_d, 3),
            ))
            t += seg_d
        if not loop or auto_count > 0:
            break
    if segments and t < total_duration - 0.05:
        segments[-1]['duration'] = round(segments[-1]['duration'] + (total_duration - t), 3)
    return segments


def schema(assets, settings, style):
    s = {**DEFAULTS, **settings}
    length = s['end'] - s['start'] + s['offset']
    overlay_clips = []
    if s.get('title_text') and s.get('title_duration', 0) > 0:
        overlay_clips.append(dict(kind='title', text=s['title_text'], start=0, duration=s['title_duration']))
    if 'broll' in assets and s.get('broll_duration', 0) > 0:
        overlay_clips.append(dict(kind='broll', asset='broll', start=s['broll_start'], duration=s['broll_duration'],
                                  transform={k: s[k] for k in ('broll_x','broll_y','broll_scale','broll_opacity','broll_fade')}))
    tf = {k: s[k] for k in ('fit','x','y','blur','dim','overlay','opacity','zoom',
                            'brightness','contrast','saturation','transition_in','transition_out',
                            'keyframe_end_x','keyframe_end_y')}
    seq_segments = schedule_sequence(s.get('sequence') or [], assets, length, loop=s['loop'])
    if len(seq_segments) >= 2:
        bg_clips = [dict(asset=seg['asset'], name=seg['name'], start=seg['start'], duration=seg['duration'],
                         source_offset=0, speed=s['background_speed'], transform=tf) for seg in seq_segments]
    else:
        bg_clips = [dict(asset='background', start=0, duration=length,
                         source_offset=s['background_start'], speed=s['background_speed'], transform=tf)]
    tracks = [
        dict(kind='background', clips=bg_clips),
        dict(kind='audio', clips=[dict(asset='audio', start=s['offset'],
             duration=s['end']-s['start'], source_offset=s['start'], ducking=s['ducking'])]),
        dict(kind='captions', cue_source='cues', style=copy.deepcopy(style)),
        dict(kind='overlays', clips=overlay_clips)
    ]
    return dict(version=1, timebase='seconds', assets=copy.deepcopy(assets), settings=copy.deepcopy(s), tracks=tracks)


def validate(settings, source_duration):
    s = {**DEFAULTS, **{k:v for k,v in settings.items() if k in DEFAULTS}}
    s['sequence'] = validate_sequence(settings.get('sequence', []))
    if s['shape'] not in SHAPES or s['fit'] not in {'fit','fill'}:
        raise ValueError('Choose a supported canvas format and fit mode.')
    if s['visualizer_style'] not in VISUALIZER_STYLES or s['visualizer_position'] not in VISUALIZER_POSITIONS:
        raise ValueError('Choose a supported visualizer style and position.')
    if s['video_filter'] not in VIDEO_FILTERS or s['audio_effect'] not in AUDIO_EFFECTS:
        raise ValueError('Choose a supported video filter and audio effect.')
    if s.get('sequence_transition', 'none') not in SEQUENCE_TRANSITIONS:
        raise ValueError('Choose a supported clip transition.')
    s['sequence_transition_duration'] = finite(s.get('sequence_transition_duration') or 0.5, 0.1, 2.0)
    for key in ('color','overlay','visualizer_color'):
        if not re.fullmatch('#[0-9a-fA-F]{6}', str(s[key])):
            raise ValueError('Choose a valid composition color.')
    s['title_text'] = re.sub(r'[\r\n\t]+', ' ', str(s.get('title_text') or '')).strip()[:120]
    bounds = dict(x=(0,100),y=(0,100),blur=(0,30),dim=(0,1),opacity=(0,1),zoom=(0,.2),
                  brightness=(-.5,.5),contrast=(.5,2),saturation=(0,3),background_speed=(.25,2),
                  film_grain=(0,30),sharpen=(0,2),chromatic=(0,10),
                  transition_in=(0,10),transition_out=(0,10),keyframe_end_x=(0,100),keyframe_end_y=(0,100),
                  title_duration=(0,15),broll_start=(0,7200),broll_duration=(0,7200),
                  broll_x=(0,100),broll_y=(0,100),broll_scale=(20,100),broll_opacity=(.1,1),broll_fade=(0,5),
                  start=(0,source_duration),end=(0,source_duration),offset=(0,120),volume=(0,2),
                  fade_in=(0,60),fade_out=(0,60),background_volume=(0,2),
                  background_start=(0,7200),background_duration=(0,7200),
                  visualizer_height=(10,40),visualizer_sensitivity=(.5,3))
    for key, (lo,hi) in bounds.items(): s[key] = finite(s[key],lo,hi)
    length = s['end']-s['start']
    if length < .1 or length+s['offset'] > 1200:
        raise ValueError('Choose a song range of at least 0.1 seconds and an output up to 20 minutes.')
    if max(s['fade_in'],s['fade_out']) > length:
        raise ValueError('Audio fades must fit inside the selected song range.')
    for key in ('loop','visualizer','ducking','vignette','noise_cancel','voice_isolation'):
        if type(s[key]) is not bool: raise ValueError('Invalid composition checkbox value.')
    return s


def shift_cues(cues, delta, duration, speed=1.0):
    """Keep lyrics attached to the same source audio; trim edge cues and re-evaluate on speed changes."""
    speed = finite(speed, .25, 4.0)
    result = []
    for original in cues:
        c = copy.deepcopy(original)
        a = (c['start'] * (1.0 / speed)) + delta
        b = (c['end'] * (1.0 / speed)) + delta
        if b <= 0 or a >= duration: continue
        c['start'],c['end'] = max(0,a),min(duration,b)
        if a < 0 or b > duration:
            c['words'] = []
            c['karaoke'] = dict(state='review',note='Line crosses the song trim. Review its text and timing.')
        else:
            c['words'] = [{**w,'start':(w['start']*(1.0/speed))+delta,'end':(w['end']*(1.0/speed))+delta} for w in c.get('words',[])]
            if abs(speed - 1.0) > 1e-4:
                c['karaoke'] = dict(state='review',note='Playback speed changed. Review lyric synchronization.')
        result.append(c)
    return result


def render_args(studio, folder, output, background_has_audio=False, bake_fx=True):
    s = {**DEFAULTS, **studio['settings']}
    assets = studio['assets']
    w,h = SHAPES[s['shape']]
    duration = s['end']-s['start']+s['offset']
    args = ['-i',local_asset(folder,assets['audio']).name]
    seq_segments = schedule_sequence(s.get('sequence') or [], assets, duration, loop=s['loop'])
    multi_clip = len(seq_segments) >= 2
    sequence_assets = list(dict.fromkeys(seg['asset'] for seg in seq_segments))
    if multi_clip:
        for key in sequence_assets:
            c_asset = assets[key]
            c_path = local_asset(folder, c_asset)
            longest = max(seg['duration'] for seg in seq_segments if seg['asset'] == key)
            in_dur = round(longest * max(1.0, s['background_speed']) + 0.5, 3)
            if c_asset['kind'] == 'image':
                args += ['-loop', '1', '-framerate', '30', '-t', str(in_dur), '-i', c_path.name]
            else:
                args += (['-stream_loop', '-1'] if s['loop'] else []) + ['-t', str(in_dur), '-i', c_path.name]
    else:
        bg_key = seq_segments[0]['asset'] if len(seq_segments) == 1 else 'background'
        bg = assets.get(bg_key) or assets.get('background')
        if bg:
            path = local_asset(folder,bg)
            if bg['kind']=='image': args += ['-loop','1','-framerate','30']
            elif s['loop']: args += ['-stream_loop','-1']
            args += ['-ss',str(s['background_start'])] if bg['kind']=='video' else []
            args += ['-i',path.name]
        else:
            args += ['-f','lavfi','-i',f"color=c={s['color']}:s={w}x{h}:r=30"]
    broll = assets.get('broll')
    has_broll = bool(broll and s['broll_duration'] > 0)
    broll_idx = (1 + len(sequence_assets)) if multi_clip else 2
    if has_broll and broll is not None:
        bpath = local_asset(folder, broll)
        if broll['kind'] == 'image':
            args += ['-loop', '1', '-framerate', '30', '-i', bpath.name]
        else:
            args += ['-stream_loop', '-1', '-i', bpath.name]
    graph=[]
    length=s['end']-s['start']
    af=f"[0:a]atrim=start={s['start']}:end={s['end']},asetpts=PTS-STARTPTS,volume={s['volume']}"
    if bake_fx:
        for a_fx in audio_fx_chain(s):
            af+=f",{a_fx}"
    if s['fade_in']: af+=f",afade=t=in:st=0:d={s['fade_in']}"
    if s['fade_out']: af+=f",afade=t=out:st={length-s['fade_out']}:d={s['fade_out']}"
    af+=f",adelay={round(s['offset']*1000)}:all=1,apad,atrim=duration={duration}[song]"
    graph.append(af)
    pts_expr = f"{1.0/s['background_speed']:.4f}*(PTS-STARTPTS)" if abs(s['background_speed'] - 1.0) > 1e-4 else 'PTS-STARTPTS'
    atempo_filter = f"atempo={s['background_speed']:.4f}," if abs(s['background_speed'] - 1.0) > 1e-4 else ""
    if background_has_audio and s['background_volume']:
        bg_vol = f"volume='if(between(t,{s['offset']},{duration}),{round(s['background_volume']*0.3,4)},{s['background_volume']})':eval=frame" if s['ducking'] else f"volume={s['background_volume']}"
        if multi_clip:
            for k, seg in enumerate(seq_segments):
                c_asset = assets[seg['asset']]
                idx = sequence_assets.index(seg['asset']) + 1
                if c_asset['kind'] == 'video' and c_asset.get('has_audio', True):
                    graph.append(f"[{idx}:a]{atempo_filter}asetpts=PTS-STARTPTS,atrim=duration={seg['duration']},asetpts=PTS-STARTPTS,aformat=sample_rates=44100:channel_layouts=stereo[aseg{k}]")
                else:
                    graph.append(f"anullsrc=r=44100:cl=stereo,atrim=duration={seg['duration']}[aseg{k}]")
            a_concat_in = ''.join(f'[aseg{k}]' for k in range(len(seq_segments)))
            graph.append(f"{a_concat_in}concat=n={len(seq_segments)}:v=0:a=1[bg_audio_raw]")
            graph.append(f"[bg_audio_raw]asetpts=PTS-STARTPTS,{bg_vol},apad,atrim=duration={duration}[ba]")
            graph.append('[song][ba]amix=inputs=2:duration=first:normalize=0[mix]')
        else:
            graph.append(f"[1:a]{atempo_filter}asetpts=PTS-STARTPTS,{bg_vol},apad,atrim=duration={duration}[ba]")
            graph.append('[song][ba]amix=inputs=2:duration=first:normalize=0[mix]')
    else: graph.append('[song]anull[mix]')
    scale_crop = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}:(iw-ow)*{s['x']/100}:(ih-oh)*{s['y']/100}"
        if s['fit']=='fill' else
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)*{s['x']/100}:(oh-ih)*{s['y']/100}:color={s['color']}"
    )
    trans = str(s.get('sequence_transition') or 'none')
    trans_dur = finite(float(s.get('sequence_transition_duration') or 0.5), 0.1, 2.0)
    td = min(trans_dur, min(seg['duration'] for seg in seq_segments) * 0.4) if (multi_clip and len(seq_segments) >= 2) else 0.0

    if multi_clip:
        for idx, key in enumerate(sequence_assets, start=1):
            uses = [k for k, seg in enumerate(seq_segments) if seg['asset'] == key]
            outputs = ''.join(f'[seqinput{k}]' for k in uses)
            graph.append(f'[{idx}:v]split={len(uses)}{outputs}')

        xfade_active = trans in {'fade', 'dissolve', 'wipeleft', 'wiperight', 'slideleft', 'slideright', 'circlecrop', 'smoothleft', 'smoothright'} and td >= 0.05

        for k, seg in enumerate(seq_segments):
            seg_trim_dur = round(seq_segments[0]['duration'] if (xfade_active and k == 0) else (seg['duration'] + (td if xfade_active else 0.0)), 3)
            seg_vf = f"[seqinput{k}]setpts={pts_expr},fps=30,tpad=stop_mode=clone:stop_duration={seg_trim_dur},trim=duration={seg_trim_dur},setpts=PTS-STARTPTS,{scale_crop},setsar=1,format=yuv420p"
            if trans in ('fadeblack', 'fadewhite') and td >= 0.05:
                fcol = 'black' if trans == 'fadeblack' else 'white'
                seg_vf += f",fade=t=in:st=0:d={td:.2f}:color={fcol},fade=t=out:st={round(seg['duration']-td, 3):.2f}:d={td:.2f}:color={fcol}"
            seg_vf += f"[vseg{k}]"
            graph.append(seg_vf)

        if xfade_active:
            cur_out = 'vseg0'
            accum_offset = max(0.01, round(seq_segments[0]['duration'] - td, 3))
            for k in range(1, len(seq_segments)):
                next_out = f'xf{k}'
                graph.append(f"[{cur_out}][vseg{k}]xfade=transition={trans}:duration={td:.2f}:offset={accum_offset}[{next_out}]")
                cur_out = next_out
                accum_offset = round(accum_offset + seq_segments[k]['duration'], 3)
            vf = f"[{cur_out}]setsar=1"
        else:
            concat_in = ''.join(f'[vseg{k}]' for k in range(len(seq_segments)))
            vf = f"{concat_in}concat=n={len(seq_segments)}:v=1:a=0,setsar=1"
    else:
        vf=f'[1:v]setpts={pts_expr},fps=30'
        if s['background_duration']: vf+=f",trim=duration={s['background_duration']}"
        vf+=f",tpad=stop_mode=clone:stop_duration={duration},trim=duration={duration},{scale_crop},setsar=1"
    if s['zoom'] or s['keyframe_end_x'] != s['x'] or s['keyframe_end_y'] != s['y']:
        frames = max(1, round(duration * 30) - 1)
        z_amt = max(s['zoom'], 0.04 if (s['keyframe_end_x'] != s['x'] or s['keyframe_end_y'] != s['y']) else 0)
        px = f"({s['x']/100}+({(s['keyframe_end_x']-s['x'])/100})*on/{frames})"
        py = f"({s['y']/100}+({(s['keyframe_end_y']-s['y'])/100})*on/{frames})"
        vf+=f",zoompan=z='1+{z_amt}*on/{frames}':x='(iw-iw/zoom)*{px}':y='(ih-ih/zoom)*{py}':d=1:s={w}x{h}:fps=30"
    if s['brightness'] != 0 or s['contrast'] != 1 or s['saturation'] != 1:
        vf+=f",eq=brightness={s['brightness']}:contrast={s['contrast']}:saturation={s['saturation']}"
    if bake_fx:
        for v_fx in video_fx_chain(s):
            vf+=f",{v_fx}"
    if s['blur']: vf+=f",gblur=sigma={s['blur']}"
    if s['dim']: vf+=f",drawbox=c=black@{s['dim']}:t=fill"
    if s['opacity']: vf+=f",drawbox=c={s['overlay']}@{s['opacity']}:t=fill"
    if s['transition_in'] > 0:
        vf+=f",fade=t=in:st=0:d={min(duration, s['transition_in'])}"
    if s['transition_out'] > 0:
        vf+=f",fade=t=out:st={max(0, duration - s['transition_out'])}:d={min(duration, s['transition_out'])}"
    bg_label = '[bg0]' if has_broll else '[bg]'
    graph.append(vf + bg_label)
    if has_broll:
        bw = max(2, round(w * (s['broll_scale'] / 100) / 2) * 2)
        bh = max(2, round(h * (s['broll_scale'] / 100) / 2) * 2)
        bvf = f"[{broll_idx}:v]setpts=PTS-STARTPTS,fps=30,scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},setsar=1,format=rgba"
        if s['broll_opacity'] < 1:
            bvf += f",colorchannelmixer=aa={s['broll_opacity']}"
        if s['broll_fade'] > 0:
            bf = min(s['broll_duration'] / 2, s['broll_fade'])
            bvf += f",fade=t=in:st=0:d={bf}:alpha=1,fade=t=out:st={max(0, s['broll_duration'] - bf)}:alpha=1:d={bf}"
        bvf += f",trim=duration={s['broll_duration']},setpts=PTS+{s['broll_start']}/TB[broll]"
        ox = f"(W-w)*{s['broll_x']/100}"
        oy = f"(H-h)*{s['broll_y']/100}"
        b_end = round(s['broll_start'] + s['broll_duration'], 3)
        graph += [bvf, f"[bg0][broll]overlay=x='{ox}':y='{oy}':enable='between(t,{s['broll_start']},{b_end})':eof_action=pass[bg]"]
    if s['visualizer']:
        vh = max(2, round(h * (s['visualizer_height'] / 100) / 2) * 2)
        vy = '0' if s['visualizer_position'] == 'top' else '(H-h)/2' if s['visualizer_position'] == 'center' else 'H-h'
        vcol = '0x' + str(s['visualizer_color'])[1:]
        sens = s['visualizer_sensitivity']
        if s['visualizer_style'] == 'spectrum':
            vfilter = f"[vis]volume={sens},showfreqs=s={w}x{vh}:mode=bar:ascale=sqrt:fscale=log:win_size=2048:rate=30:colors={vcol}[wave]"
        else:
            vfilter = f"[vis]volume={sens},showwaves=s={w}x{vh}:mode=cline:rate=30:colors={vcol}:scale=sqrt[wave]"
        graph += ['[mix]asplit=2[aout][vis]', vfilter, f'[bg][wave]overlay=0:{vy}:shortest=1[out]']
    else: graph += ['[mix]anull[aout]','[bg]null[out]']
    return [*args,'-filter_complex',';'.join(graph),'-map','[out]','-map','[aout]',
            '-t',str(duration),'-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p',
            '-c:a','aac','-b:a','256k','-movflags','+faststart',output]


# --- Phase 4: Integrated Stock Background Browser (Pexels & Pixabay) ---

STOCK_PROVIDERS = {'pexels', 'pixabay', 'mixkit', 'youtube'}
STOCK_HOSTS = {
    'pexels': ('pexels.com', 'akamaized.net', 'vimeo.com'),
    'pixabay': ('pixabay.com', 'vimeocdn.com'),
    'mixkit': ('mixkit.co', 'envatousercontent.com'),
    'youtube': ('youtube.com', 'youtu.be', 'ytimg.com', 'ggpht.com'),
}
STOCK_LICENSES = {
    'pexels': 'Pexels License',
    'pixabay': 'Pixabay Content License',
    'mixkit': 'Mixkit Stock Video Free License',
    'youtube': 'YouTube / Google Video',
}
MAX_STOCK_BYTES = 80 * 1024 * 1024
_STOCK_CACHE: dict[tuple, tuple[float, list[dict]]] = {}


def validate_stock_url(url: str, provider: str) -> str:
    """Validate that a remote stock URL uses HTTPS and belongs to the provider's official domains."""
    if provider not in STOCK_PROVIDERS:
        raise ValueError('Choose Pexels, Pixabay, Mixkit, or YouTube.')
    url = str(url or '').strip()
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not host or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Blocked untrusted stock media URL.')
    allowed_domains = STOCK_HOSTS[provider]
    if not any(host == d or host.endswith('.' + d) for d in allowed_domains):
        raise ValueError('Blocked remote host outside the approved stock provider.')
    return url


def validate_provenance(prov: dict) -> dict:
    """Validate and sanitize stock asset attribution and licensing metadata."""
    if not isinstance(prov, dict):
        raise ValueError('Invalid stock provenance metadata.')
    provider = str(prov.get('provider', '')).strip().lower()
    if provider not in STOCK_PROVIDERS:
        raise ValueError('Invalid stock provider in provenance.')
    source_url = validate_stock_url(prov.get('source_url', ''), provider)
    creator = str(prov.get('creator', 'Unknown Creator')).strip()[:120] or 'Unknown Creator'
    license_name = STOCK_LICENSES.get(provider, 'Pixabay Content License')
    attribution = str(prov.get('attribution', '')).strip()[:240] or f'Media by {creator} on {provider.capitalize()}'
    return dict(provider=provider, creator=creator, source_url=source_url,
                license=license_name, attribution=attribution)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, provider: str):
        super().__init__()
        self.provider = provider

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        validate_stock_url(target, self.provider)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _stock_opener(provider: str, opener=None):
    if opener is not None:
        return opener
    return urllib.request.build_opener(_SafeRedirectHandler(provider))


_MIXKIT_CARD_RE = re.compile(
    r'data-item-grid--video-player-item-id-value="(\d+)".*?'
    r'<img\s+src="(https://assets\.mixkit\.co/videos/[^"]+\.jpg)"[^>]*alt="([^"]*)"[^>]*width="(\d+)"[^>]*height="(\d+)".*?'
    r'<video\s+src="(https://assets\.mixkit\.co/videos/[^"]+\.mp4)"',
    re.S
)


def _search_mixkit(query: str, orientation: str, opener=None) -> list[dict]:
    """Search Mixkit free HD stock video catalog without requiring any API key."""
    slug = re.sub(r'[^a-z0-9]+', '-', query.lower()).strip('-') or 'dance'
    slugs = [slug]
    if orientation == 'portrait' and not slug.startswith('vertical'):
        slugs = [f'vertical-{slug}', slug]
    client = _stock_opener('mixkit', opener)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    seen: set[str] = set()
    results: list[dict] = []
    for s in slugs:
        url = f'https://mixkit.co/free-stock-video/discover/{s}/'
        validate_stock_url(url, 'mixkit')
        req = urllib.request.Request(url, headers=headers)
        try:
            with client.open(req, timeout=10) as resp:
                page = resp.read(4 * 1024 * 1024).decode('utf-8', errors='replace')
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
        for vid_id, thumb_raw, alt_raw, w_str, h_str, video_360 in _MIXKIT_CARD_RE.findall(page):
            if vid_id in seen:
                continue
            seen.add(vid_id)
            dl_raw = re.sub(r'-360\.mp4$', '-720.mp4', video_360)
            try:
                dl_url = validate_stock_url(dl_raw, 'mixkit')
                prev_url = validate_stock_url(thumb_raw, 'mixkit')
            except ValueError:
                continue
            vw, vh = int(w_str or 460), int(h_str or 259)
            title = html.unescape(alt_raw or '').strip('. ')[:100] or f'Mixkit clip #{vid_id}'
            results.append(dict(
                id=str(vid_id),
                provider='mixkit',
                kind='video',
                title=title,
                duration=15.0,
                width=1080 if vh >= vw else 1280,
                height=1920 if vh >= vw else 720,
                preview_url=prev_url,
                download_url=dl_url,
                creator='Mixkit Studio',
                source_url='https://mixkit.co/free-stock-video/',
                license='Mixkit Stock Video Free License',
                attribution='Free HD Stock Video on Mixkit'
            ))
    if orientation == 'portrait':
        results.sort(key=lambda r: (1 if r['height'] >= r['width'] else 0), reverse=True)
    return results[:24]


def _search_youtube(query: str, orientation: str, max_duration: float) -> list[dict]:
    """Search YouTube Shorts / Google Video via yt-dlp without requiring any API key."""
    search_q = query
    if orientation == 'portrait' and '#shorts' not in query.lower():
        search_q = f'{query} #shorts vertical'
    try:
        result = process.run([sys.executable, str(Path(__file__).with_name('social_worker.py')), '--ignore-config',
                              '--proxy', '',
                              '--flat-playlist', '--skip-download', '--dump-single-json',
                              '--no-warnings', '--socket-timeout', '10', '--retries', '1',
                              '--', f'ytsearch24:{search_q}'], capture_output=True, timeout=45)
        process.check_cancelled()
        if result.returncode:
            raise ValueError('Search provider unavailable. Please try again.')
        info = json.loads(result.stdout)
    except Exception as exc:
        raise ValueError(f'YouTube Shorts search failed: {exc}') from None
    entries = (info or {}).get('entries') or []
    results: list[dict] = []
    dur_cap = max_duration if max_duration > 0 else 180.0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        vid_id = str(entry.get('id') or '').strip()
        if not re.match(r'^[a-zA-Z0-9_-]{6,20}$', vid_id):
            continue
        dur = float(entry.get('duration') or 0)
        if dur > dur_cap:
            continue
        if dur <= 0:
            dur = 15.0
        dl_url = f'https://www.youtube.com/watch?v={vid_id}'
        prev_url = f'https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg'
        creator = str(entry.get('channel') or entry.get('uploader') or 'YouTube Creator').strip()[:120]
        raw_title = str(entry.get('title') or f'YouTube Short #{vid_id}').strip()[:90]
        results.append(dict(
            id=vid_id,
            provider='youtube',
            kind='video',
            title=f'{raw_title} ({int(dur)}s)',
            duration=round(dur, 1),
            width=1080 if orientation == 'portrait' else 1920,
            height=1920 if orientation == 'portrait' else 1080,
            preview_url=prev_url,
            download_url=dl_url,
            creator=creator,
            source_url=dl_url,
            license='YouTube / Google Video',
            attribution=f'Video by {creator} on YouTube'
        ))
        if len(results) >= 24:
            break
    return results


def search_stock(provider: str, query: str, kind: str = 'video', orientation: str = 'portrait',
                 max_duration: float = 0, api_key: str = '', opener=None) -> list[dict]:
    """Search Pexels, Pixabay, Mixkit (no key), or YouTube Shorts (no key) with filtering and provenance."""
    provider = str(provider or '').strip().lower()
    if provider not in STOCK_PROVIDERS:
        raise ValueError('Choose Pexels, Pixabay, Mixkit, or YouTube.')
    kind = str(kind or 'video').strip().lower()
    if kind not in {'video', 'image'}:
        raise ValueError('Choose video or image search.')
    orientation = str(orientation or 'portrait').strip().lower()
    if orientation not in {'portrait', 'landscape', 'square', 'all'}:
        raise ValueError('Choose a valid orientation filter.')
    max_duration = finite(max_duration or 0, 0, 600)
    query = re.sub(r'\s+', ' ', str(query or '').strip())[:100]
    if not query:
        raise ValueError('Enter a search term for stock backgrounds.')

    cache_key = (provider, query.lower(), kind, orientation, max_duration)
    cached = _STOCK_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < 300 and opener is None:
        return copy.deepcopy(cached[1])

    if provider == 'mixkit':
        results = _search_mixkit(query, orientation, opener=opener)
        if opener is None:
            _STOCK_CACHE[cache_key] = (time.time(), copy.deepcopy(results))
        return results

    if provider == 'youtube':
        results = _search_youtube(query, orientation, max_duration)
        if opener is None:
            _STOCK_CACHE[cache_key] = (time.time(), copy.deepcopy(results))
        return results

    api_key = str(api_key or '').strip()
    if not api_key:
        raise ValueError(f'Enter your free {provider.capitalize()} API key to search {provider.capitalize()} inside the app. Local uploads and library backgrounds work without a key.')

    q_enc = urllib.parse.quote(query)
    headers = {'User-Agent': 'AI-Influencer-Media-Grabber/2.5'}
    if provider == 'pexels':
        headers['Authorization'] = api_key
        orient_param = f'&orientation={orientation}' if orientation != 'all' else ''
        if kind == 'video':
            url = f'https://api.pexels.com/videos/search?query={q_enc}{orient_param}&per_page=18'
        else:
            url = f'https://api.pexels.com/v1/search?query={q_enc}{orient_param}&per_page=18'
    else:
        key_enc = urllib.parse.quote(api_key)
        if kind == 'video':
            url = f'https://pixabay.com/api/videos/?key={key_enc}&q={q_enc}&per_page=40&safesearch=true'
        else:
            px_orient = 'vertical' if orientation == 'portrait' else 'horizontal' if orientation == 'landscape' else 'all'
            url = f'https://pixabay.com/api/?key={key_enc}&q={q_enc}&orientation={px_orient}&image_type=photo&per_page=18&safesearch=true'

    validate_stock_url(url, provider)
    req = urllib.request.Request(url, headers=headers)
    client = _stock_opener(provider, opener)
    try:
        with client.open(req, timeout=12) as resp:
            payload = json.loads(resp.read(5 * 1024 * 1024).decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ValueError(f'{provider.capitalize()} rejected the API key (HTTP {exc.code}). Check your key in Stock Backgrounds.') from None
        if exc.code == 429:
            raise ValueError(f'{provider.capitalize()} rate limit reached (HTTP 429). Wait a moment or use a local background.') from None
        raise ValueError(f'{provider.capitalize()} search failed (HTTP {exc.code}).') from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError(f'Could not reach {provider.capitalize()}. Check your internet connection or use a local file.') from None

    results: list[dict] = []
    if provider == 'pexels':
        if kind == 'video':
            for item in payload.get('videos', []):
                dur = float(item.get('duration') or 0)
                if max_duration > 0 and dur > max_duration:
                    continue
                files = [f for f in item.get('video_files', []) if str(f.get('file_type', '')).endswith('mp4') and f.get('link')]
                if not files:
                    continue
                # Prefer HD (<= 1920px max side) to keep downloads fast and bounded
                files.sort(key=lambda f: (max(int(f.get('width') or 0), int(f.get('height') or 0)) <= 1920,
                                          min(1920, max(int(f.get('width') or 0), int(f.get('height') or 0)))), reverse=True)
                chosen = files[0]
                try:
                    dl_url = validate_stock_url(chosen['link'], 'pexels')
                    prev_url = validate_stock_url(item.get('image') or chosen['link'], 'pexels')
                    src_url = validate_stock_url(item.get('url') or 'https://www.pexels.com', 'pexels')
                except ValueError:
                    continue
                creator = str((item.get('user') or {}).get('name') or 'Pexels Creator').strip()[:120]
                results.append(dict(
                    id=str(item.get('id')),
                    provider='pexels',
                    kind='video',
                    title=f'Pexels video #{item.get("id")} ({int(dur)}s)',
                    duration=round(dur, 1),
                    width=int(chosen.get('width') or 0),
                    height=int(chosen.get('height') or 0),
                    preview_url=prev_url,
                    download_url=dl_url,
                    creator=creator,
                    source_url=src_url,
                    license='Pexels License',
                    attribution=f'Video by {creator} on Pexels'
                ))
        else:
            for item in payload.get('photos', []):
                src = item.get('src') or {}
                dl_raw = src.get('large2x') or src.get('large') or src.get('original')
                prev_raw = src.get('medium') or src.get('small') or dl_raw
                if not dl_raw:
                    continue
                try:
                    dl_url = validate_stock_url(dl_raw, 'pexels')
                    prev_url = validate_stock_url(prev_raw, 'pexels')
                    src_url = validate_stock_url(item.get('url') or 'https://www.pexels.com', 'pexels')
                except ValueError:
                    continue
                creator = str(item.get('photographer') or 'Pexels Photographer').strip()[:120]
                title = str(item.get('alt') or f'Pexels photo #{item.get("id")}').strip()[:100]
                results.append(dict(
                    id=str(item.get('id')),
                    provider='pexels',
                    kind='image',
                    title=title,
                    duration=0,
                    width=int(item.get('width') or 0),
                    height=int(item.get('height') or 0),
                    preview_url=prev_url,
                    download_url=dl_url,
                    creator=creator,
                    source_url=src_url,
                    license='Pexels License',
                    attribution=f'Photo by {creator} on Pexels'
                ))
    else:
        for item in payload.get('hits', []):
            creator = str(item.get('user') or 'Pixabay Creator').strip()[:120]
            tags = str(item.get('tags') or f'Pixabay #{item.get("id")}').strip()[:100]
            if kind == 'video':
                dur = float(item.get('duration') or 0)
                if max_duration > 0 and dur > max_duration:
                    continue
                vids = item.get('videos') or {}
                chosen = vids.get('medium') or vids.get('large') or vids.get('small') or {}
                if not chosen.get('url'):
                    continue
                vw, vh = int(chosen.get('width') or 0), int(chosen.get('height') or 0)
                if False and orientation == 'portrait' and vw > vh > 0:
                    continue
                if False and orientation == 'landscape' and vh > vw > 0:
                    continue
                try:
                    dl_url = validate_stock_url(chosen['url'], 'pixabay')
                    thumb = chosen.get('thumbnail') or ''
                    prev_url = validate_stock_url(thumb, 'pixabay') if thumb else dl_url
                    src_url = validate_stock_url(item.get('pageURL') or 'https://pixabay.com', 'pixabay')
                except ValueError:
                    continue
                results.append(dict(
                    id=str(item.get('id')),
                    provider='pixabay',
                    kind='video',
                    title=f'{tags} ({int(dur)}s)',
                    duration=round(dur, 1),
                    width=vw,
                    height=vh,
                    preview_url=prev_url,
                    download_url=dl_url,
                    creator=creator,
                    source_url=src_url,
                    license='Pixabay Content License',
                    attribution=f'Video by {creator} on Pixabay'
                ))
            else:
                dl_raw = item.get('largeImageURL') or item.get('webformatURL')
                prev_raw = item.get('webformatURL') or item.get('previewURL') or dl_raw
                if not dl_raw:
                    continue
                try:
                    dl_url = validate_stock_url(dl_raw, 'pixabay')
                    prev_url = validate_stock_url(prev_raw, 'pixabay')
                    src_url = validate_stock_url(item.get('pageURL') or 'https://pixabay.com', 'pixabay')
                except ValueError:
                    continue
                results.append(dict(
                    id=str(item.get('id')),
                    provider='pixabay',
                    kind='image',
                    title=tags,
                    duration=0,
                    width=int(item.get('imageWidth') or 0),
                    height=int(item.get('imageHeight') or 0),
                    preview_url=prev_url,
                    download_url=dl_url,
                    creator=creator,
                    source_url=src_url,
                    license='Pixabay Content License',
                    attribution=f'Photo by {creator} on Pixabay'
                ))

    if provider == 'pixabay' and kind == 'video':
        if orientation == 'portrait':
            results.sort(key=lambda r: (1 if r['height'] >= r['width'] > 0 else 0), reverse=True)
        elif orientation == 'landscape':
            results.sort(key=lambda r: (1 if r['width'] >= r['height'] > 0 else 0), reverse=True)
        results = results[:24]
    if opener is None:
        _STOCK_CACHE[cache_key] = (time.time(), copy.deepcopy(results))
    return results


def download_stock_asset(url: str, provider: str, kind: str, destination: Path,
                         check_cancel=None, opener=None, max_bytes: int = MAX_STOCK_BYTES) -> Path:
    """Download a validated stock video or image with redirect validation, size bounds, and magic-byte verification."""
    validate_stock_url(url, provider)
    if kind not in {'video', 'image'}:
        raise ValueError('Invalid stock media kind.')
    req = urllib.request.Request(url, headers={'User-Agent': 'AI-Influencer-Media-Grabber/2.5'})
    client = _stock_opener(provider, opener)
    temp_path = destination.with_suffix(destination.suffix + '.part')
    try:
        with client.open(req, timeout=20) as resp:
            validate_stock_url(resp.geturl(), provider)
            length_hdr = resp.headers.get('Content-Length')
            if length_hdr and length_hdr.isdigit() and int(length_hdr) > max_bytes:
                raise ValueError('Stock media file exceeds the maximum allowed download size (80 MB).')
            ctype = (resp.headers.get('Content-Type') or '').lower()
            if ctype and not any(ctype.startswith(p) for p in ('video/', 'image/', 'application/octet-stream', 'binary/')):
                raise ValueError('Remote server did not return a valid media file.')
            total = 0
            header_bytes = b''
            with open(temp_path, 'wb') as out:
                while True:
                    if check_cancel is not None:
                        check_cancel()
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    if len(header_bytes) < 32:
                        header_bytes += chunk[:32 - len(header_bytes)]
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError('Stock media file exceeds the maximum allowed download size (80 MB).')
                    out.write(chunk)
        if total < 64:
            raise ValueError('Downloaded stock media file is empty or incomplete.')
        if kind == 'video':
            if b'ftyp' not in header_bytes[:16] and not header_bytes.startswith(b'\x1a\x45\xdf\xa3'):
                raise ValueError('Downloaded file is not a supported video container.')
        else:
            is_img = (header_bytes.startswith(b'\x89PNG\r\n\x1a\n') or
                      header_bytes.startswith(b'\xff\xd8\xff') or
                      (header_bytes.startswith(b'RIFF') and header_bytes[8:12] == b'WEBP'))
            if not is_img:
                raise ValueError('Downloaded file is not a supported image format.')
        os.replace(temp_path, destination)
        return destination
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
