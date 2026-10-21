"""Versioned local composition model and shared FFmpeg render specification.

All timeline values use seconds from output zero. Assets are immutable local
basenames. Caption edits remain in the enclosing project for backwards reading.
"""
import copy
import math
import re
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
DEFAULTS = dict(shape='portrait', color='#141526', fit='fill', x=50, y=50,
                blur=0, dim=0, overlay='#000000', opacity=0, zoom=0,
                start=0, end=0, offset=0, volume=1, fade_in=0, fade_out=0,
                background_volume=0, loop=True, background_start=0, background_duration=0,
                visualizer=False, visualizer_style='waveform', visualizer_position='bottom',
                visualizer_height=20, visualizer_sensitivity=1, visualizer_color='#bba6ff')


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
    else:
        # Legacy uploaded videos retain their video/audio as independent track references.
        assets['audio'] = dict(file=project['source'], kind='video', duration=duration)
        assets['background'] = dict(file=project['source'], kind='video')
        settings['loop'] = False
    return schema(assets, settings, project['style'])


def schema(assets, settings, style):
    length = settings['end'] - settings['start'] + settings['offset']
    return dict(version=1, timebase='seconds', assets=copy.deepcopy(assets), settings=copy.deepcopy(settings),
                tracks=[dict(kind='background', clips=[dict(asset='background', start=0, duration=length,
                           source_offset=settings['background_start'], transform={k:settings[k] for k in ('fit','x','y','blur','dim','overlay','opacity','zoom')})]),
                        dict(kind='audio', clips=[dict(asset='audio', start=settings['offset'],
                             duration=settings['end']-settings['start'], source_offset=settings['start'])]),
                        dict(kind='captions', cue_source='cues', style=copy.deepcopy(style))])


def validate(settings, source_duration):
    s = {**DEFAULTS, **{k:v for k,v in settings.items() if k in DEFAULTS}}
    if s['shape'] not in SHAPES or s['fit'] not in {'fit','fill'}:
        raise ValueError('Choose a supported canvas format and fit mode.')
    if s['visualizer_style'] not in VISUALIZER_STYLES or s['visualizer_position'] not in VISUALIZER_POSITIONS:
        raise ValueError('Choose a supported visualizer style and position.')
    for key in ('color','overlay','visualizer_color'):
        if not re.fullmatch('#[0-9a-fA-F]{6}', str(s[key])):
            raise ValueError('Choose a valid composition color.')
    bounds = dict(x=(0,100),y=(0,100),blur=(0,30),dim=(0,1),opacity=(0,1),zoom=(0,.2),
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
    for key in ('loop','visualizer'):
        if type(s[key]) is not bool: raise ValueError('Invalid composition checkbox value.')
    return s


def shift_cues(cues, delta, duration):
    """Keep lyrics attached to the same source audio; trim edge cues explicitly."""
    result = []
    for original in cues:
        c = copy.deepcopy(original)
        a,b = c['start']+delta,c['end']+delta
        if b <= 0 or a >= duration: continue
        c['start'],c['end'] = max(0,a),min(duration,b)
        if a < 0 or b > duration:
            c['words'] = []
            c['karaoke'] = dict(state='review',note='Line crosses the song trim. Review its text and timing.')
        else:
            c['words'] = [{**w,'start':w['start']+delta,'end':w['end']+delta} for w in c.get('words',[])]
        result.append(c)
    return result


def render_args(studio, folder, output, background_has_audio=False):
    s, assets = studio['settings'], studio['assets']
    w,h = SHAPES[s['shape']]
    duration = s['end']-s['start']+s['offset']
    args = ['-i',local_asset(folder,assets['audio']).name]
    bg = assets.get('background')
    if bg:
        path = local_asset(folder,bg)
        if bg['kind']=='image': args += ['-loop','1','-framerate','30']
        elif s['loop']: args += ['-stream_loop','-1']
        args += ['-ss',str(s['background_start'])] if bg['kind']=='video' else []
        args += ['-i',path.name]
    else:
        args += ['-f','lavfi','-i',f"color=c={s['color']}:s={w}x{h}:r=30"]
    graph=[]
    length=s['end']-s['start']
    af=f"[0:a]atrim=start={s['start']}:end={s['end']},asetpts=PTS-STARTPTS,volume={s['volume']}"
    if s['fade_in']: af+=f",afade=t=in:st=0:d={s['fade_in']}"
    if s['fade_out']: af+=f",afade=t=out:st={length-s['fade_out']}:d={s['fade_out']}"
    af+=f",adelay={round(s['offset']*1000)}:all=1,apad,atrim=duration={duration}[song]"
    graph.append(af)
    if background_has_audio and s['background_volume']:
        graph.append(f"[1:a]asetpts=PTS-STARTPTS,volume={s['background_volume']},apad,atrim=duration={duration}[ba]")
        graph.append('[song][ba]amix=inputs=2:duration=first:normalize=0[mix]')
    else: graph.append('[song]anull[mix]')
    vf='[1:v]setpts=PTS-STARTPTS,fps=30'
    if s['background_duration']: vf+=f",trim=duration={s['background_duration']}"
    vf+=f",tpad=stop_mode=clone:stop_duration={duration},trim=duration={duration}"
    if s['fit']=='fill':
        vf+=f",scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}:(iw-ow)*{s['x']/100}:(ih-oh)*{s['y']/100}"
    else:
        vf+=f",scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)*{s['x']/100}:(oh-ih)*{s['y']/100}:color={s['color']}"
    vf+=',setsar=1'
    if s['zoom']:
        vf+=f",zoompan=z='1+{s['zoom']}*on/{max(1,round(duration*30)-1)}':x='(iw-iw/zoom)*{s['x']/100}':y='(ih-ih/zoom)*{s['y']/100}':d=1:s={w}x{h}:fps=30"
    if s['blur']: vf+=f",gblur=sigma={s['blur']}"
    if s['dim']: vf+=f",drawbox=c=black@{s['dim']}:t=fill"
    if s['opacity']: vf+=f",drawbox=c={s['overlay']}@{s['opacity']}:t=fill"
    graph.append(vf+'[bg]')
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
