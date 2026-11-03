"""Face swap: InsightFace detection/recognition + InSwapper + GFPGAN (ONNX), images and videos.

Models are loaded from verified local files only. Missing faces raise
``AIUnavailable``; nothing is reported as swapped unless it really was.
"""
import logging
import shutil
import tempfile
import threading
from pathlib import Path

import job_process
from job_process import check_cancelled

from . import gpu, models
from .errors import AIUnavailable, ModelMissing

log = logging.getLogger(__name__)
SIMILARITY_THRESHOLD = 0.30
KPS_SMOOTHING = 0.4
SAMPLE_FRAMES = 16
RESTORE_BLEND = 0.85
FFHQ_512 = ((0.37691676, 0.46864664), (0.62285697, 0.46912813), (0.50123859, 0.61331904),
            (0.39308822, 0.72541100), (0.61150205, 0.72490465))
_state = {'providers': None, 'analyzer': None, 'swapper': None, 'restorer': None}
_lock = threading.RLock()


def select_providers():
    """CUDA (after torch loads its DLLs) → DirectML → CPU, based on the installed onnxruntime build."""
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise AIUnavailable('Face swap needs the AI pack (onnxruntime). Install it from AI Setup.', setup_hint='ai_pack') from exc
    available = set(ort.get_available_providers())
    if 'CUDAExecutionProvider' in available:
        try:
            import torch  # noqa: F401  (loads the CUDA/cuDNN DLLs onnxruntime-gpu links against)
        except ImportError:
            pass
        if hasattr(ort, 'preload_dlls'):
            try:
                ort.preload_dlls()
            except Exception as exc:  # missing optional DLLs must not block CPU fallback
                log.warning('onnxruntime.preload_dlls failed: %s', exc)
        return ['CUDAExecutionProvider', 'CPUExecutionProvider']
    if 'DmlExecutionProvider' in available:
        return ['DmlExecutionProvider', 'CPUExecutionProvider']
    return ['CPUExecutionProvider']


def _release():
    with _lock:
        _state.update(analyzer=None, swapper=None, restorer=None, providers=None)


gpu.register_evictor('face', _release)


def _load(restore):
    with _lock:
        detector = models.ensure('insightface-buffalo-l')
        swapper_path = models.ensure('inswapper-128')
        restorer_path = models.ensure('gfpgan-1.4') if restore else None
        if _state['providers'] is None:
            _state['providers'] = select_providers()
        providers = _state['providers']
        if _state['analyzer'] is None:
            from insightface.app import FaceAnalysis
            root = detector.parents[2]  # <root>/models/buffalo_l/det_10g.onnx
            analyzer = FaceAnalysis(name='buffalo_l', root=str(root), allowed_modules=['detection', 'recognition'],
                                    providers=providers)
            analyzer.prepare(ctx_id=0 if providers[0] != 'CPUExecutionProvider' else -1, det_size=(640, 640))
            _state['analyzer'] = analyzer
        if _state['swapper'] is None:
            from insightface import model_zoo
            _state['swapper'] = model_zoo.get_model(str(swapper_path), providers=providers)
        if restore and _state['restorer'] is None:
            import onnxruntime as ort
            _state['restorer'] = ort.InferenceSession(str(restorer_path), providers=providers)
        return _state['analyzer'], _state['swapper'], (_state['restorer'] if restore else None)


def _vram():
    return 2.5 if (_state['providers'] or ['CPU'])[0] == 'CUDAExecutionProvider' else 0.0


def _largest(faces):
    return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])) if faces else None


def _similarity(a, b):
    import numpy as np
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


def restore_face(frame, face, session, blend=RESTORE_BLEND):
    """GFPGAN on the 512 aligned crop, pasted back with a feathered mask."""
    import cv2
    import numpy as np
    template = np.array(FFHQ_512, dtype=np.float32) * 512
    matrix, _ = cv2.estimateAffinePartial2D(np.asarray(face.kps, dtype=np.float32), template, method=cv2.LMEDS)
    if matrix is None:
        return frame
    crop = cv2.warpAffine(frame, matrix, (512, 512), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_AREA)
    tensor = (crop[:, :, ::-1].astype(np.float32) / 255.0 - 0.5) / 0.5
    tensor = np.expand_dims(tensor.transpose(2, 0, 1), 0)
    output = session.run(None, {session.get_inputs()[0].name: tensor})[0][0]
    restored = ((np.clip(output, -1, 1) + 1) / 2 * 255).transpose(1, 2, 0)[:, :, ::-1].round().astype(np.uint8)
    mask = np.zeros((512, 512), dtype=np.float32)
    border = 512 // 10
    mask[border:-border, border:-border] = 1.0
    mask = cv2.GaussianBlur(mask, (0, 0), border / 2)
    inverse = cv2.invertAffineTransform(matrix)
    height, width = frame.shape[:2]
    pasted = cv2.warpAffine(restored, inverse, (width, height), borderMode=cv2.BORDER_REPLICATE)
    weight = cv2.warpAffine(mask, inverse, (width, height))[:, :, None] * blend
    return (pasted.astype(np.float32) * weight + frame.astype(np.float32) * (1 - weight)).astype(np.uint8)


def _swap_face(frame, target_face, source_face, swapper, restorer):
    result = swapper.get(frame, target_face, source_face, paste_back=True)
    if restorer is not None:
        result = restore_face(result, target_face, restorer)
    return result


def _source_face(analyzer, source_image):
    import cv2
    image = cv2.imread(str(source_image), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('The reference image could not be read.')
    face = _largest(analyzer.get(image))
    if face is None:
        raise AIUnavailable('No face was found in the reference image. Use a clear, front-facing photo.')
    return face


def _check_restore(restore):
    if restore and not models.installed('gfpgan-1.4'):
        raise ModelMissing('Face restoration (GFPGAN) is not installed. Install it, or turn restoration off.',
                           setup_hint='gfpgan-1.4')


def swap_image(target, source, output, *, restore=True):
    import cv2
    _check_restore(restore)
    analyzer, swapper, restorer = _load(restore)
    with gpu.lease('face', _vram()), gpu.model_lock('face'):
        source_face = _source_face(analyzer, source)
        frame = cv2.imread(str(target), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError('The target image could not be read.')
        faces = analyzer.get(frame)
        target_face = _largest(faces)
        if target_face is None:
            raise AIUnavailable('No face was found in the target image.')
        check_cancelled()
        result = _swap_face(frame, target_face, source_face, swapper, restorer)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), result):
        raise ValueError('Could not write the output image.')
    gpu.touch('face')
    return {'output': str(output), 'faces_found': len(faces), 'faces_swapped': 1,
            'provider': _state['providers'][0], 'restored': bool(restorer)}


def _sample_reference(analyzer, video):
    """Largest face in the earliest sampled frame that has one, else None."""
    import cv2
    capture = cv2.VideoCapture(str(video))
    try:
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        positions = sorted({int(i * max(total - 1, 0) / max(SAMPLE_FRAMES - 1, 1)) for i in range(SAMPLE_FRAMES)}) if total else [0]
        for position in positions:
            check_cancelled()
            capture.set(cv2.CAP_PROP_POS_FRAMES, position)
            ok, frame = capture.read()
            if not ok:
                continue
            face = _largest(analyzer.get(frame))
            if face is not None:
                return face
    finally:
        capture.release()
    return None


def _match(faces, reference_embedding):
    best, score = None, -1.0
    for face in faces:
        similarity = _similarity(face.normed_embedding, reference_embedding)
        if similarity > score:
            best, score = face, similarity
    return (best, score) if best is not None and score >= SIMILARITY_THRESHOLD else (None, score)


def _remux(video_only, original, output):
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    base = [ffmpeg, '-y', '-v', 'error', '-i', str(video_only), '-i', str(original), '-map', '0:v:0', '-map', '1:a?',
            '-c:v', 'copy']
    for audio in (['-c:a', 'copy'], ['-c:a', 'aac', '-b:a', '192k']):
        result = job_process.run(base + audio + ['-shortest', str(output)], capture_output=True, timeout=3600)
        if result.returncode == 0:
            return True
    raise AIUnavailable('Could not add the original audio to the swapped video.')


def swap_video(target_video, source_image, output, *, restore=True, progress=None):
    """Swap one identity through the whole video: no frame cap, source size kept, audio remuxed."""
    import imageio_ffmpeg
    import numpy as np
    _check_restore(restore)
    analyzer, swapper, restorer = _load(restore)
    source_face = _source_face(analyzer, source_image)
    reference = _sample_reference(analyzer, target_video)
    if reference is None:
        raise AIUnavailable('No face was found in the video. Choose a clip where the face is clearly visible.')
    reference_embedding = reference.normed_embedding
    total, _ = imageio_ffmpeg.count_frames_and_secs(str(target_video))
    reader = imageio_ffmpeg.read_frames(str(target_video), pix_fmt='bgr24')
    meta = next(reader)
    width, height = meta['size']
    fps = meta.get('fps') or 30
    work = Path(tempfile.mkdtemp(prefix='faceswap-', dir=Path(output).parent if Path(output).parent.exists() else None))
    video_only = work / 'video.mp4'
    params = ['-crf', '18', '-preset', 'medium']
    if width % 2 or height % 2:
        params[:0] = ['-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2']
    writer = imageio_ffmpeg.write_frames(str(video_only), (width, height), fps=fps, codec='libx264', pix_fmt_in='bgr24',
                                         quality=None, macro_block_size=1, output_params=params)
    writer.send(None)
    done = swapped = 0
    previous_kps = None
    try:
        with gpu.lease('face', _vram()), gpu.model_lock('face'):
            for raw in reader:
                check_cancelled()
                frame = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3).copy()
                face, _ = _match(analyzer.get(frame), reference_embedding)
                if face is not None:
                    if previous_kps is not None:
                        face['kps'] = (1 - KPS_SMOOTHING) * face.kps + KPS_SMOOTHING * previous_kps
                    previous_kps = face.kps
                    frame = _swap_face(frame, face, source_face, swapper, restorer)
                    swapped += 1
                else:
                    previous_kps = None
                writer.send(np.ascontiguousarray(frame).tobytes())
                done += 1
                if progress and (done % 10 == 0 or done == total):
                    progress(done, total)
        writer.close()
        if not swapped:
            raise AIUnavailable('The chosen face was not found in any frame. Nothing was swapped.')
        check_cancelled()
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        _remux(video_only, target_video, output)
    finally:
        reader.close()
        writer.close()
        shutil.rmtree(work, ignore_errors=True)
    gpu.touch('face')
    return {'output': str(output), 'frames_total': done, 'frames_swapped': swapped, 'fps': fps, 'width': width,
            'height': height, 'provider': _state['providers'][0], 'restored': bool(restorer)}


__all__ = ['select_providers', 'swap_image', 'swap_video', 'restore_face']
