"""App-level AI helpers shared by the downloader and media tools (models live in ``ai_core``)."""
import re

MAX_CUE_CHARS = 3000


def segments_to_srt(segments, timestamp):
    """SRT text from Whisper-style ``segments``; ``timestamp`` formats seconds as HH:MM:SS,mmm."""
    blocks = []
    for segment in segments if isinstance(segments, list) else []:
        if not isinstance(segment, dict):
            continue
        text = str(segment.get('text', '')).strip()
        if not text:
            continue
        start, end = float(segment.get('start', 0.0)), float(segment.get('end', 0.0))
        blocks.append(f'{len(blocks) + 1}\n{timestamp(start)} --> {timestamp(end)}\n{text}')
    return '\n\n'.join(blocks) + ('\n\n' if blocks else '')


def translate_srt(text, language='English'):
    """Translate SRT cue text with the local translator; cue numbers and times never reach the model."""
    from ai_core import translate
    cues = re.split(r'\n\s*\n', text.strip())
    parsed = []
    for index, cue in enumerate(cues):
        lines = cue.splitlines()
        if len(lines) < 3 or '-->' not in lines[1]:
            raise ValueError('Invalid subtitle cue')
        original = '\n'.join(lines[2:])
        if len(original) > MAX_CUE_CHARS:
            raise ValueError('Subtitle cue is too long to translate safely')
        parsed.append((str(index), lines[:2], original))
    context = '\n'.join(original for _, _, original in parsed)[:12000]
    answer = translate.translate_lines([{'id': cue_id, 'text': original} for cue_id, _, original in parsed],
                                       language, context=context)
    output = []
    for cue_id, header, _ in parsed:
        translated = str(answer.get(cue_id, {}).get('text', '')).strip()
        if not translated or '-->' in translated:
            raise RuntimeError('Subtitle translation failed; original subtitles were preserved')
        output.append('\n'.join(header + [translated]))
    return '\n\n'.join(output) + '\n\n'
