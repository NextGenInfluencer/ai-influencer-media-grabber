"""Speech: stable-ts Whisper from local files only, VAD, language detection, alignment."""
import importlib.util
import logging
import sys
import threading
import uuid
from pathlib import Path

from job_process import check_cancelled

from . import catalog, gpu, hardware, models, paths, settings
from .errors import AIUnavailable, ModelMissing

log = logging.getLogger(__name__)
SAMPLE_RATE = 16000
WINDOW_SECONDS = 30
PREFERENCE = ('whisper-large-v3', 'whisper-large-v3-turbo', 'whisper-small', 'whisper-base')
_state = {'name': None, 'model': None, 'device': None}
_lock = threading.RLock()


def speech_item():
    override = settings.get_role_override('speech')
    if override:
        item_id = override if override.startswith('whisper-') else f'whisper-{override}'
        if not catalog.exists(item_id):
            raise ModelMissing(f'Unknown speech model "{override}".', setup_hint='ai_setup')
        if not models.installed(item_id):
            raise ModelMissing(f'{catalog.get(item_id)["name"]} is not installed.', setup_hint=item_id)
        return catalog.get(item_id)
    profile = hardware.current_profile()
    recommended = catalog.recommended(profile, 'speech', hardware.detect())
    for item_id in [i for i in recommended if i.startswith('whisper-')] + list(PREFERENCE):
        if models.installed(item_id):
            return catalog.get(item_id)
    hint = next((i for i in recommended if i.startswith('whisper-')), 'whisper-base')
    raise ModelMissing('No speech model is installed. Install one from AI Setup to transcribe and time lyrics.',
                       setup_hint=hint)


def whisper_model_name():
    return speech_item()['source']['model_name']


def _device():
    try:
        import torch
        return 'cuda' if torch.cuda.is_available() and hardware.current_profile().startswith('gpu') else 'cpu'
    except ImportError:
        return 'cpu'


def get_model():
    """Load the role's Whisper model from its verified local file (never downloads)."""
    item = speech_item()
    name = item['source']['model_name']
    with _lock:
        if _state['model'] is not None and _state['name'] == name:
            gpu.touch('whisper')
            return _state['model']
        release()
        path = models.ensure(item['id'])
        try:
            import stable_whisper
        except ImportError as exc:
            raise AIUnavailable('Speech recognition needs the AI pack. Install it from AI Setup.', setup_hint='ai_pack') from exc
        device = _device()
        # download_root holds the verified "<name>.pt"; whisper then finds it and skips downloading.
        model = stable_whisper.load_model(name, device=device, download_root=str(path.parent))
        _state.update(name=name, model=model, device=device)
        gpu.touch('whisper')
        return model


def release():
    with _lock:
        if _state['model'] is None:
            return
        _state.update(name=None, model=None, device=None)
        torch = sys.modules.get('torch')  # loaded with the model; never imported just to release
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()


gpu.register_evictor('whisper', release)


def _vram():
    try:
        return float(speech_item().get('vram_gb') or 0) if _state['device'] == 'cuda' else 0.0
    except AIUnavailable:
        return 0.0


def _silero_cached():
    """stable-ts VAD loads Silero through torch.hub; only use it when cached locally."""
    try:
        import torch
        hub = Path(torch.hub.get_dir())
    except (ImportError, AttributeError):
        return False
    return any(hub.glob('snakers4_silero-vad*'))


def _progress(*_):
    check_cancelled()


def _load_audio(audio):
    """Decode existing audio files to 16 kHz mono float32 via imageio-ffmpeg so system ffmpeg is not required."""
    if not isinstance(audio, (str, Path)):
        return audio
    path = Path(audio)
    if not path.is_file():
        return audio
    import imageio_ffmpeg
    import job_process
    import numpy as np
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-threads', '0',
        '-i', str(path), '-f', 's16le', '-ac', '1', '-acodec', 'pcm_s16le',
        '-ar', str(SAMPLE_RATE), '-'
    ]
    result = job_process.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise AIUnavailable('Could not decode audio for speech recognition.')
    return np.frombuffer(result.stdout, np.int16).flatten().astype(np.float32) / 32768.0


def transcribe(audio, *, language=None, word_timestamps=True, vad=True):
    model = get_model()
    audio = _load_audio(audio)
    use_vad = bool(vad) and _silero_cached()
    meta = {'model': _state['name'], 'device': _state['device'], 'vad': use_vad,
            'condition_on_previous_text': False}
    if vad and not use_vad:
        meta['vad_note'] = 'Voice activity detection is unavailable offline (Silero VAD not cached); ran without it.'
    with gpu.lease('whisper', _vram()), _lock:
        check_cancelled()
        result = model.transcribe(audio, language=language, word_timestamps=word_timestamps, vad=use_vad,
                                  condition_on_previous_text=False, progress_callback=_progress, verbose=None)
        check_cancelled()
    data = result.to_dict()
    data['meta'] = meta
    return data


def most_voiced_window(samples, seconds=WINDOW_SECONDS, rate=SAMPLE_RATE):
    """Start index of the ``seconds`` window with the highest RMS energy (1 s resolution)."""
    import numpy as np
    samples = np.asarray(samples, dtype=np.float32)
    window = int(seconds * rate)
    if samples.size <= window:
        return 0
    frames = samples[: samples.size // rate * rate].reshape(-1, rate)
    energy = np.sqrt(np.mean(frames ** 2, axis=1))
    span = min(int(seconds), energy.size)
    sums = np.convolve(energy, np.ones(span), mode='valid')
    return int(np.argmax(sums)) * rate


def detect_language(samples, candidates=None):
    """Language code from the most-voiced 30 s, restricted to ``candidates`` when given."""
    import numpy as np
    import whisper
    model = get_model()
    samples = np.asarray(samples, dtype=np.float32)
    start = most_voiced_window(samples)
    clip = samples[start:start + WINDOW_SECONDS * SAMPLE_RATE]
    with gpu.lease('whisper', _vram()), _lock:
        check_cancelled()
        mel = whisper.log_mel_spectrogram(whisper.pad_or_trim(clip), n_mels=model.dims.n_mels).to(model.device)
        _, probabilities = model.detect_language(mel)
    if isinstance(probabilities, list):
        probabilities = probabilities[0]
    choices = {code: p for code, p in probabilities.items() if not candidates or code in candidates}
    if not choices:
        raise AIUnavailable('None of the requested languages is supported by the speech model.')
    return max(choices, key=choices.get)


def _alignment(function_name):
    try:
        from stable_whisper import alignment
    except ImportError as exc:
        raise AIUnavailable('Lyric timing needs the AI pack. Install it from AI Setup.', setup_hint='ai_pack') from exc
    return getattr(alignment, function_name)


def align(audio, text, language):
    align_fn = _alignment('align')
    model = get_model()
    audio = _load_audio(audio)
    with gpu.lease('whisper', _vram()), _lock:
        result = align_fn(model, audio, text, language=language, original_split=True, regroup=False, verbose=None,
                          remove_instant_words=False, progress_callback=_progress)
    check_cancelled()
    if result is None:
        raise AIUnavailable('Could not align these lyrics. Check the words, language and audio range.')
    return result.to_dict()


def align_words(audio, text, language):
    align_fn = _alignment('align_words')
    model = get_model()
    audio = _load_audio(audio)
    duration = len(audio) / SAMPLE_RATE if hasattr(audio, '__len__') else None
    segments = [dict(start=0, end=duration, text=text)]
    with gpu.lease('whisper', _vram()), _lock:
        result = align_fn(model, audio, segments, language=language, normalize_text=False, regroup=False,
                          verbose=None, progress_callback=_progress)
    check_cancelled()
    return result.to_dict()


def isolate_vocals(path):
    """Separate the vocal stem with audio-separator and the catalog's UVR model."""
    if importlib.util.find_spec('audio_separator') is None:
        raise AIUnavailable('Vocal isolation needs the GPU AI pack (audio-separator).', setup_hint='ai_pack')
    model_path = models.ensure('uvr-kim-vocal-2')
    from audio_separator.separator import Separator
    output_dir = paths.DATA_DIR / 'cache' / 'vocals' / uuid.uuid4().hex
    output_dir.mkdir(parents=True, exist_ok=True)
    with gpu.lease('separator', catalog.get('uvr-kim-vocal-2').get('vram_gb', 2)):
        check_cancelled()
        separator = Separator(model_file_dir=str(model_path.parent), output_dir=str(output_dir),
                              output_single_stem='Vocals')
        separator.load_model(model_filename=model_path.name)
        outputs = separator.separate(str(path))
        check_cancelled()
    for output in outputs or []:
        candidate = Path(output)
        candidate = candidate if candidate.is_absolute() else output_dir / candidate
        if candidate.is_file():
            return candidate
    raise AIUnavailable('Vocal isolation produced no output file.')
