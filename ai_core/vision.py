"""Vision: local VLM via the role router, BLIP-base captions on CPU, frame ranking."""
import base64
import json
import threading
from pathlib import Path

from job_process import check_cancelled

from . import gpu, llm, models
from .errors import AIUnavailable

MAX_SIDE = 1024
SCENE_SCHEMA = {'type': 'object', 'properties': {
    'summary': {'type': 'string'}, 'subject': {'type': 'string'}, 'setting': {'type': 'string'},
    'lighting': {'type': 'string'}, 'camera': {'type': 'string'}, 'mood': {'type': 'string'},
    'colors': {'type': 'array', 'items': {'type': 'string'}}, 'wardrobe': {'type': 'string'},
    'action': {'type': 'string'}},
    'required': ['summary', 'subject', 'setting', 'lighting', 'camera', 'mood', 'colors', 'wardrobe', 'action']}
PORTRAIT_SCHEMA = {'type': 'object', 'properties': {
    'summary': {'type': 'string'}, 'apparent_age_range': {'type': 'string'}, 'hair': {'type': 'string'},
    'eyes': {'type': 'string'}, 'skin_tone': {'type': 'string'}, 'style': {'type': 'string'},
    'expression': {'type': 'string'}, 'distinctive_features': {'type': 'array', 'items': {'type': 'string'}}},
    'required': ['summary', 'apparent_age_range', 'hair', 'eyes', 'skin_tone', 'style', 'expression',
                 'distinctive_features']}
FRAME_SCHEMA = {'type': 'object', 'properties': {
    'score': {'type': 'number', 'minimum': 0, 'maximum': 10}, 'has_clear_face': {'type': 'boolean'},
    'reason': {'type': 'string'}}, 'required': ['score', 'has_clear_face', 'reason']}
_blip = {'processor': None, 'model': None}
_blip_lock = threading.RLock()


def _encode(image):
    """Base64 JPEG/PNG of an image path, downscaled to keep VLM prompts small."""
    import cv2
    path = Path(image)
    if not path.is_file():
        raise ValueError(f'Image not found: {path.name}')
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f'Unsupported image: {path.name}')
    height, width = frame.shape[:2]
    scale = MAX_SIDE / max(height, width)
    if scale < 1:
        frame = cv2.resize(frame, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError(f'Could not encode image: {path.name}')
    return base64.b64encode(buffer.tobytes()).decode('ascii')


def _vlm_available():
    try:
        llm.resolve('vision')
        return True
    except AIUnavailable:
        return False


def _vlm_json(prompt, image, schema):
    answer = llm.chat('vision', [{'role': 'user', 'content': prompt}], images=[_encode(image)], schema=schema,
                      temperature=0.2, max_tokens=600)
    data = json.loads(answer['content'])
    if not isinstance(data, dict):
        raise AIUnavailable('The vision model returned invalid data.')
    data['source'] = answer['model']
    return data


def _release_blip():
    with _blip_lock:
        _blip.update(processor=None, model=None)


gpu.register_evictor('blip', _release_blip)


def _blip_caption(image):
    from PIL import Image
    folder = models.ensure('blip-base').parent
    with _blip_lock:
        if _blip['model'] is None:
            try:
                from transformers import BlipForConditionalGeneration, BlipProcessor
            except ImportError as exc:
                raise AIUnavailable('Image captions need the AI pack. Install it from AI Setup.', setup_hint='ai_pack') from exc
            _blip['processor'] = BlipProcessor.from_pretrained(str(folder), local_files_only=True)
            _blip['model'] = BlipForConditionalGeneration.from_pretrained(str(folder), local_files_only=True,
                                                                           use_safetensors=True)
        check_cancelled()
        with Image.open(image) as source:
            inputs = _blip['processor'](images=source.convert('RGB'), return_tensors='pt')
        output = _blip['model'].generate(**inputs, max_new_tokens=40)
        text = _blip['processor'].decode(output[0], skip_special_tokens=True).strip()
    gpu.touch('blip')
    if not text:
        raise AIUnavailable('The caption model returned no text.')
    return text


def caption(image):
    if _vlm_available():
        answer = llm.chat('vision', [{'role': 'user', 'content':
                                      'Describe this image in one concise sentence suitable as an image prompt.'}],
                          images=[_encode(image)], temperature=0.2, max_tokens=120)
        return answer['content'].strip()
    return _blip_caption(image)


def describe_scene(image):
    """Structured scene description (VLM), or a BLIP summary with other fields left empty."""
    if _vlm_available():
        return _vlm_json('Describe this frame for a video prompt. Be factual; do not guess identities.', image,
                         SCENE_SCHEMA)
    summary = _blip_caption(image)
    return {**{key: None for key in SCENE_SCHEMA['properties']}, 'summary': summary, 'colors': [],
            'source': 'blip-base'}


def profile_from_portrait(image):
    if _vlm_available():
        return _vlm_json('Describe the visible appearance of the person in this portrait for a character '
                         'profile. Describe only what is visible; never guess identity, ethnicity or names.',
                         image, PORTRAIT_SCHEMA)
    summary = _blip_caption(image)
    return {**{key: None for key in PORTRAIT_SCHEMA['properties']}, 'summary': summary, 'distinctive_features': [],
            'source': 'blip-base'}


def sharpness_and_face(path):
    """(Laplacian variance, has_face) using OpenCV's bundled Haar cascade (offline)."""
    import cv2
    frame = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if frame is None:
        return 0.0, False
    sharpness = float(cv2.Laplacian(frame, cv2.CV_64F).var())
    cascade = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / 'haarcascade_frontalface_default.xml'))
    faces = cascade.detectMultiScale(frame, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)) if not cascade.empty() else ()
    return sharpness, len(faces) > 0


def rank_frames(paths):
    """Indices of ``paths`` from best to worst first frame."""
    if not paths:
        return []
    measures = [sharpness_and_face(p) for p in paths]
    top = max(m[0] for m in measures) or 1.0
    scores = [(m[0] / top) * 5 + (5 if m[1] else 0) for m in measures]
    if _vlm_available():
        shortlist = sorted(range(len(paths)), key=lambda i: -scores[i])[:8]
        for index in shortlist:
            check_cancelled()
            data = _vlm_json('Rate this frame from 0 to 10 as the first frame of a short vertical video of the '
                             'person: sharp, well lit, eyes open, face clearly visible, natural pose.',
                             paths[index], FRAME_SCHEMA)
            scores[index] = float(data.get('score', 0)) * 2 + scores[index] * 0.2
    return sorted(range(len(paths)), key=lambda i: -scores[i])
