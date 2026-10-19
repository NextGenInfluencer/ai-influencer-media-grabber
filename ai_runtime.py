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
