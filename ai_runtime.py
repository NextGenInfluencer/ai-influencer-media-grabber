"""Serialize model loading, inference, and idle unloading across worker threads."""
from functools import wraps
import threading
import re
from job_process import check_cancelled

model_lock = threading.RLock()

def serialized(function):
    @wraps(function)
    def call(*args, **kwargs):
        with model_lock:
            check_cancelled()
            result = function(*args, **kwargs)
            check_cancelled()
            return result
    return call

@serialized
def transcribe(model, *args, **kwargs):
    return model.transcribe(*args, **kwargs)

@serialized
def align_caption_words(model, audio, text, language):
    try:
        from stable_whisper.alignment import align_words
    except ImportError as exc:
        raise RuntimeError('Install the updated AI Pack in the Studio, then restart to enable karaoke timing.') from exc
    result = align_words(model, audio, [dict(start=0, end=len(audio)/16000, text=text)],
                         language=language, normalize_text=False, regroup=False, verbose=None,
                         progress_callback=lambda *_: check_cancelled())
    return result.to_dict()

@serialized
def align_lyrics(model, audio, text, language):
    """Use the shared Whisper model without changing its transcription methods."""
    try:
        from stable_whisper.alignment import align
    except ImportError as exc:
        raise ValueError('Lyric timing needs the updated AI Pack. Install it from the Studio, then restart the app.') from exc
    result = align(model, audio, text, language=language, original_split=True,
                   regroup=False, verbose=None, remove_instant_words=False,
                   progress_callback=lambda *_: check_cancelled())
    if result is None:
        raise ValueError('Could not align these lyrics. Check the words, language and selected audio range.')
    return result.to_dict()

def translate_srt(text, generate, model_id, language='English'):
    """Translate bounded cue groups; keep original cue IDs and times outside the model."""
    cues = re.split(r'\n\s*\n', text.strip())
    output = []
    for cue in cues:
        lines = cue.splitlines()
        if len(lines) < 3 or '-->' not in lines[1]:
            raise ValueError('Invalid subtitle cue')
        original = '\n'.join(lines[2:])
        if len(original) > 3000:
            raise ValueError('Subtitle cue is too long to translate safely')
        translated = generate(original, f'Translate this subtitle to {language}. Return only the translated text, without timestamps or commentary.', model_id)
        if not translated or '-->' in translated or translated.startswith(('Error:', 'AI Engine')):
            raise RuntimeError('Subtitle translation failed; original subtitles were preserved')
        output.append('\n'.join(lines[:2] + [translated.strip()]))
    return '\n\n'.join(output) + '\n\n'
