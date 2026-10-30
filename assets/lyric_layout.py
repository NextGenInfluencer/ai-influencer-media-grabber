"""Shared pixel layout for browser preview and ASS output."""
import copy
import os
import re
from pathlib import Path
from PIL import ImageFont
from .lyric_tracks import clean_translations


def font_file(name, bundled, custom_dir, custom):
    if name in bundled:
        return Path(__file__).resolve().parents[1]/'static/fonts'/bundled[name]
    if name in custom:
        return Path(custom_dir)/custom[name]
    system = {'Arial':'arial.ttf','Verdana':'verdana.ttf','Georgia':'georgia.ttf',
              'Impact':'impact.ttf','Trebuchet MS':'trebuc.ttf'}
    return Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/system.get(name,'arial.ttf')


def rows(cue, style, width, height, font_path, resolve_runs=None, locate_font=None):
    max_width = width*style['box_width']/100 - 2*height*style['box_padding']/100
    if max_width < 1:
        raise ValueError('Reduce background padding or increase text box width to leave room for captions.')

    def load_font(size, path=font_path):
        try:
            return ImageFont.truetype(str(path), max(1, round(size)))
        except OSError:
            return ImageFont.load_default(size=max(1, round(size)))

    def measure(text, size, spacing):
        runs=resolve_runs(text) if resolve_runs else [dict(text=text,font=style['font'])]
        length=sum(load_font(size,locate_font(run['font']) if locate_font else font_path).getlength(run['text']) for run in runs)
        return length + max(0, len(text)-1)*spacing

    def wrap(text, size):
        spacing = height*style['letter_spacing']/100
        lines=[]
        for paragraph in text.split('\n'):
            current=''
            for token in re.findall(r'\S+\s*',paragraph):
                candidate=(current+token).rstrip()
                measured=measure(candidate,size,spacing)
                if current and measured>max_width:
                    lines.append(current.rstrip());current=token
                else: current+=token
            lines.append(current.rstrip())
        return lines
    entry=clean_translations(cue).get(style['translation_language'])
    translation=entry['text'] if entry and entry['status']=='approved' else ''
    mode=style['track_mode']
    if mode=='translation' and not translation:
        raise ValueError('Approve a translation for this line before using translation-only display.')
    groups=[]
    if mode!='translation': groups.append(('original',cue['text'],style['size'],style['color']))
    if mode!='original' and translation and (mode=='translation' or not style['hide_duplicate_translation'] or translation!=cue['text']):
        groups.append(('translation',translation,style['translation_size'],style['translation_color']))
    result=[]
    for index,(kind,text,percent,color) in enumerate(groups):
        size=height*percent/100
        for line_index,line in enumerate(wrap(text,size)):
            # Fit unbreakable words without changing their spelling or timing tokens.
            # Scale letter spacing too, otherwise spacing alone can exceed the box.
            spacing = height*style['letter_spacing']/100
            factor = 1.0
            measured = measure(line, size, spacing)
            if measured > max_width:
                low, high = 0.0, 1.0
                for _ in range(24):
                    trial = (low+high)/2
                    if measure(line, size*trial, spacing*trial) <= max_width:
                        low = trial
                    else:
                        high = trial
                factor = low
                if factor <= 0 or measure(line, size*factor, spacing*factor) > max_width:
                    raise ValueError('This text box is too narrow. Increase its width or shorten the caption.')
            result.append(dict(text=line,track=kind,size=percent*factor,color=color,
                               letter_spacing=style['letter_spacing']*factor,fitted=factor<1,
                               advance=size*factor*style['line_spacing'],
                               gap=height*style['translation_gap']/100 if index and line_index==0 else 0))
    # Anchor the bottom of the whole block; rows have explicit line breaks in both renderers.
    y=height*style['position']/100
    for row in reversed(result):
        row['y']=y;y-=row['advance']+row['gap']
        row['x']=width*style['horizontal']/100
        row['alignment']=style['alignment']
    for row in result:
        row['runs']=resolve_runs(row['text']) if resolve_runs else [dict(text=row['text'],font=style['font'])]
        size=height*row['size']/100
        row['width']=measure(row['text'],size,height*row['letter_spacing']/100)
        row['height']=size
    words=iter(cue.get('words',[]))
    for row in result:
        row['words']=[]
        if row['track']=='original':
            for token in row['text'].split():
                word=next(words,None)
                if word is not None:
                    if word['text']!=token: raise ValueError('Word timing text differs from layout text.')
                    row['words'].append(copy.deepcopy(word))
    return result
