"""Local reference-image/video preparation and carousel/still-image studio. No external AI service is contacted."""
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import job_process as subprocess
import threading
import uuid
import zipfile

import cv2
from flask import Blueprint, jsonify, request, send_file
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from media_safety import safe_media_name

FONT_DIR = Path(__file__).resolve().parent / 'static' / 'fonts'
CAROUSEL_PRESETS = {
    'portrait': (1080, 1350),   # 4:5 Instagram / LinkedIn carousel standard
    'square': (1080, 1080),     # 1:1 Square carousel
    'story': (1080, 1920),      # 9:16 Reels / Stories / TikTok photo mode
    'landscape': (1920, 1080),  # 16:9 YouTube / X post
}
CAROUSEL_FONTS = {
    'Montserrat': 'Montserrat[wght].ttf',
    'Roboto': 'Roboto[wdth,wght].ttf',
    'Noto Sans KR': 'NotoSansKR[wght].ttf',
    'Oswald': 'Oswald[wght].ttf',
    'Lobster': 'Lobster-Regular.ttf',
    'Bangers': 'Bangers-Regular.ttf',
}
CAROUSEL_FILTERS = {'none', 'bw', 'sepia', 'vintage', 'warm', 'cool', 'dramatic'}
CAROUSEL_DEFAULTS = dict(
    aspect='portrait',
    fit='fill',
    background='#141526',
    margin=0,
    rotate=0,
    filter='none',
    font='Montserrat',
    shared_caption='',
    text_color='#ffffff',
    text_bg=True,
    font_size=4.5,
)


def _apply_photo_filter(im: Image.Image, flt: str) -> Image.Image:
    if flt == 'bw':
        return ImageOps.grayscale(im).convert('RGB')
    if flt == 'sepia':
        return ImageOps.colorize(ImageOps.grayscale(im), '#2b1d0e', '#f5e1c0').convert('RGB')
    if flt == 'vintage':
        sep = ImageOps.colorize(ImageOps.grayscale(im), '#241911', '#f2dec2').convert('RGB')
        blended = Image.blend(im, sep, 0.45)
        return ImageEnhance.Contrast(blended).enhance(1.12)
    if flt == 'warm':
        warm_layer = ImageOps.colorize(ImageOps.grayscale(im), '#2e1808', '#ffe4b5').convert('RGB')
        blended = Image.blend(im, warm_layer, 0.22)
        return ImageEnhance.Color(blended).enhance(1.2)
    if flt == 'cool':
        cool_layer = ImageOps.colorize(ImageOps.grayscale(im), '#0c1b2e', '#d6ecff').convert('RGB')
        blended = Image.blend(im, cool_layer, 0.24)
        return ImageEnhance.Contrast(blended).enhance(1.08)
    if flt == 'dramatic':
        desat = ImageEnhance.Color(im).enhance(0.82)
        return ImageEnhance.Contrast(desat).enhance(1.38)
    return im


def _pick_carousel_font(text: str, pixel_size: int, font_name: str = 'Montserrat'):
    has_kr = bool(re.search(r'[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]', text))
    chosen = 'NotoSansKR[wght].ttf' if has_kr else CAROUSEL_FONTS.get(font_name, 'Montserrat[wght].ttf')
    font_file = FONT_DIR / chosen
    try:
        if font_file.is_file():
            return ImageFont.truetype(str(font_file), max(14, pixel_size))
    except OSError:
        pass
    return ImageFont.load_default()


def render_carousel_slide(orig_path: Path, dest_path: Path, settings: dict, slide: dict) -> list[int]:
    """Non-destructively render a carousel slide from its untouched original image."""
    s = {**CAROUSEL_DEFAULTS, **settings}
    aspect = s['aspect'] if s['aspect'] in CAROUSEL_PRESETS else 'portrait'
    canvas_w, canvas_h = CAROUSEL_PRESETS[aspect]
    bg_color = str(s.get('background') or '#141526')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', bg_color):
        bg_color = '#141526'
    margin_pct = max(0.0, min(15.0, float(s.get('margin') or 0)))
    pad_x = round(canvas_w * margin_pct / 100.0)
    pad_y = round(canvas_h * margin_pct / 100.0)
    inner_w = max(64, canvas_w - 2 * pad_x)
    inner_h = max(64, canvas_h - 2 * pad_y)
    rotate_deg = int(slide.get('rotate', s.get('rotate', 0)) or 0) % 360
    crop_x = max(0.0, min(1.0, float(slide.get('crop_x', 50)) / 100.0))
    crop_y = max(0.0, min(1.0, float(slide.get('crop_y', 50)) / 100.0))

    with Image.open(orig_path) as raw:
        im = ImageOps.exif_transpose(raw).convert('RGB')
        if rotate_deg in (90, 180, 270):
            im = im.rotate(-rotate_deg, expand=True)
        flt = str(slide.get('filter') or s.get('filter') or 'none')
        if flt in CAROUSEL_FILTERS and flt != 'none':
            im = _apply_photo_filter(im, flt)
        canvas = Image.new('RGB', (canvas_w, canvas_h), bg_color)
        if s.get('fit') == 'fit':
            contained = ImageOps.contain(im, (inner_w, inner_h), Image.Resampling.LANCZOS)
            ox = pad_x + (inner_w - contained.width) // 2
            oy = pad_y + (inner_h - contained.height) // 2
            canvas.paste(contained, (ox, oy))
        else:
            fitted = ImageOps.fit(im, (inner_w, inner_h), method=Image.Resampling.LANCZOS, centering=(crop_x, crop_y))
            canvas.paste(fitted, (pad_x, pad_y))

    caption = str(slide.get('caption') if slide.get('caption') is not None else s.get('shared_caption') or '').strip()[:300]
    if caption:
        rgba = canvas.convert('RGBA')
        overlay = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        px_size = round(canvas_h * max(2.0, min(10.0, float(s.get('font_size') or 4.5))) / 100.0)
        font = _pick_carousel_font(caption, px_size, str(s.get('font') or 'Montserrat'))
        bbox = draw.multiline_textbbox((0, 0), caption, font=font, align='center', spacing=8)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = (canvas_w - tw) / 2
        ty = canvas_h * 0.84 - th
        if s.get('text_bg', True):
            pad_b = max(14, round(px_size * 0.4))
            draw.rounded_rectangle(
                (tx - pad_b, ty - pad_b, tx + tw + pad_b, ty + th + pad_b),
                radius=max(10, round(px_size * 0.3)),
                fill=(10, 12, 20, 200)
            )
        t_col = str(s.get('text_color') or '#ffffff')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', t_col):
            t_col = '#ffffff'
        draw.multiline_text((tx, ty), caption, font=font, fill=t_col, align='center',
                            spacing=8, stroke_width=max(1, round(px_size * 0.06)), stroke_fill='#000000')
        canvas = Image.alpha_composite(rgba, overlay).convert('RGB')

    canvas.save(dest_path, 'PNG')
    return [canvas_w, canvas_h]


def _build_contact_sheet(folder: Path, source: Path) -> tuple[float, list[dict], str | None]:
    """Extract up to 6 evenly spaced candidate frames and compose a 3x2 contact sheet."""
    cap = cv2.VideoCapture(str(source))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        duration = float(frames / fps) if fps > 0 and frames > 0 else 0.0
    finally:
        cap.release()
    if duration <= 0:
        return 0.0, [], None

    count = 6 if duration >= 1.2 else max(1, int(duration * 4))
    candidates: list[dict] = []
    thumbs: list[Image.Image] = []
    for i in range(count):
        sec = round(min(max(0.0, duration - 0.05), duration * i / max(1, count)), 2)
        fname = f'candidate_{i}.png'
        fpath = folder / fname
        res = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-ss', str(sec), '-i', str(source),
             '-map', '0:v:0', '-frames:v', '1', str(fpath)],
            capture_output=True
        )
        if res.returncode == 0 and fpath.is_file():
            candidates.append(dict(index=i, file=fname, seconds=sec))
            try:
                with Image.open(fpath) as im:
                    thumbs.append(ImageOps.fit(im.convert('RGB'), (320, 180), Image.Resampling.LANCZOS))
            except OSError:
                pass
    if not thumbs:
        return round(duration, 2), candidates, None
    cols = min(3, len(thumbs))
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new('RGB', (cols * 320, rows * 180), (14, 15, 22))
    for idx, thumb in enumerate(thumbs):
        r, c = divmod(idx, cols)
        sheet.paste(thumb, (c * 320, r * 180))
    sheet_name = 'contact_sheet.png'
    sheet.save(folder / sheet_name, 'PNG')
    return round(duration, 2), candidates, sheet_name


def register_reference_prep(app, save_dir, job_started, job_finished, refresh_gallery):
    bp = Blueprint('reference_prep', __name__)
    root = Path(save_dir) / 'Kling References'
    carousel_root = Path(save_dir) / 'Carousels'
    lock = threading.Lock()

    def project_path(project_id):
        if len(project_id) != 32 or any(c not in '0123456789abcdef' for c in project_id):
            raise ValueError('Invalid project ID')
        return root / project_id

    def carousel_path(cid):
        if len(cid) != 32 or any(c not in '0123456789abcdef' for c in cid):
            raise ValueError('Invalid carousel ID')
        return carousel_root / cid

    def read_project(project_id):
        with lock:
            return json.loads((project_path(project_id) / 'project.json').read_text(encoding='utf-8'))

    def save_project(folder, data):
        with lock:
            temporary = folder / (uuid.uuid4().hex + '.json.tmp')
            temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
            os.replace(temporary, folder / 'project.json')

    def run_ffmpeg(args):
        result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-y', *args], capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            raise RuntimeError('Could not prepare this media: ' + result.stderr[-1000:])

    def prepare(folder, data, source):
        subprocess.begin_job()
        try:
            start = data['start_seconds']
            reference = folder / ('reference_video' + ('.mp4' if start > 0 else source.suffix))
            if start > 0:
                data['status'] = 'Preparing the video from your selected start…'
                save_project(folder, data)
                # Decode and re-encode for accurate seeking; never stream-copy a later cut.
                run_ffmpeg(['-ss', str(start), '-i', str(source), '-map', '0:v:0', '-map', '0:a?', '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', '-c:v', 'libx264', '-crf', '14', '-preset', 'medium', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', str(reference)])
            else:
                shutil.copy2(source, reference)
            frame = folder / 'first_frame.png'
            # Always extract from the exported reference so both start at the same frame.
            run_ffmpeg(['-i', str(reference), '-map', '0:v:0', '-frames:v', '1', str(frame)])
            with Image.open(frame) as image:
                dimensions = list(image.size)
            duration, candidates, contact_sheet = _build_contact_sheet(folder, source)
            data.update(state='ready', status='Reference set ready. Send first_frame.png to Nano Banana.',
                        video=reference.name, frame=frame.name, dimensions=dimensions,
                        duration=duration, candidates=candidates, contact_sheet=contact_sheet)
            save_project(folder, data)
            refresh_gallery()
        except Exception as e:
            data.update(state='error', status=str(e))
            save_project(folder, data)
        finally:
            job_finished()

    @bp.post('/api/reference/prepare')
    def start_project():
        video = request.files.get('video')
        if not video or not video.filename:
            return jsonify(error='Choose a reference video.'), 400
        ext = Path(video.filename).suffix.lower()
        if ext not in {'.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi'}:
            return jsonify(error='Choose an MP4, MOV, M4V, WebM, MKV, or AVI video.'), 400
        try:
            start = float(request.form.get('start_seconds', '0'))
            if not math.isfinite(start) or start < 0:
                raise ValueError()
        except ValueError:
            return jsonify(error='Choose a valid start time.'), 400
        project_id = uuid.uuid4().hex
        folder = project_path(project_id)
        folder.mkdir(parents=True, exist_ok=False)
        source = folder / ('original_video' + ext)
        data = dict(id=project_id, name=safe_media_name(video.filename), state='processing', status='Preparing reference set…', start_seconds=start, folder=str(folder), edited_image=None)
        try:
            video.save(source)
            save_project(folder, data)
            job_started()
            try:
                threading.Thread(target=prepare, args=(folder, data, source), daemon=True).start()
            except Exception:
                job_finished()
                raise
        except Exception as e:
            data.update(state='error', status=str(e))
            save_project(folder, data)
            return jsonify(error='Could not start reference preparation.'), 500
        return jsonify(id=project_id), 202

    @bp.post('/api/reference/<project_id>/select-frame')
    def select_reference_frame(project_id):
        try:
            data = read_project(project_id)
            folder = project_path(project_id)
        except (ValueError, OSError):
            return jsonify(error='Reference project not found.'), 404
        if data.get('state') == 'processing':
            return jsonify(error='Wait for current reference preparation to finish.'), 409
        payload = request.get_json(silent=True) or request.form or {}
        try:
            start = float(payload.get('start_seconds', 0))
            max_dur = float(data.get('duration') or 7200)
            if not math.isfinite(start) or start < 0 or (max_dur > 0 and start > max_dur):
                raise ValueError()
        except (ValueError, TypeError):
            return jsonify(error='Choose a valid frame timestamp within the video.'), 400
        source = next(folder.glob('original_video.*'), None)
        if source is None or not source.is_file():
            return jsonify(error='Original reference video not found.'), 404
        data.update(state='processing', status=f'Updating reference frame at {start:.2f}s…', start_seconds=start)
        save_project(folder, data)
        job_started()
        threading.Thread(target=prepare, args=(folder, data, source), daemon=True).start()
        return jsonify(data), 202

    @bp.get('/api/reference/projects')
    def list_projects():
        projects = []
        if root.exists():
            for path in sorted(root.glob('*/project.json'), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    projects.append(read_project(path.parent.name))
                except (ValueError, OSError):
                    continue
        return jsonify(projects)

    @bp.get('/api/reference/<project_id>')
    def get_project(project_id):
        try:
            return jsonify(read_project(project_id))
        except (ValueError, OSError):
            return jsonify(error='Reference project not found.'), 404

    @bp.post('/api/reference/<project_id>/image')
    def add_image(project_id):
        try:
            data = read_project(project_id)
            folder = project_path(project_id)
        except (ValueError, OSError):
            return jsonify(error='Reference project not found.'), 404
        if data['state'] != 'ready':
            return jsonify(error='Wait for reference preparation to finish.'), 409
        upload = request.files.get('image')
        if not upload:
            return jsonify(error='Choose your edited image.'), 400
        name = 'influencer_image_' + uuid.uuid4().hex[:10] + '.png'
        try:
            with Image.open(upload.stream) as raw:
                if getattr(raw, 'n_frames', 1) != 1:
                    return jsonify(error='Choose a still image.'), 400
                im = ImageOps.exif_transpose(raw)
                size = list(im.size)
                expected = data['dimensions']
                if size != expected and request.form.get('resize') == 'true':
                    if abs((size[0] / size[1]) / (expected[0] / expected[1]) - 1) > 0.01:
                        return jsonify(error='The aspect ratios differ. Crop your edited image to match the reference before adding it.'), 400
                    im = im.resize(tuple(expected), Image.Resampling.LANCZOS)
                    size = list(im.size)
                if size != data['dimensions']:
                    return jsonify(error=f"The edited image is {size[0]}×{size[1]}; use {data['dimensions'][0]}×{data['dimensions'][1]} to match the reference. No resizing was applied."), 400
                im.convert('RGB').save(folder / name, 'PNG')
        except (OSError, ValueError, Image.DecompressionBombError):
            return jsonify(error='Could not read that image. Choose a PNG, JPEG, or WebP.'), 400
        data['edited_image'] = name
        save_project(folder, data)
        refresh_gallery()
        return jsonify(data)

    @bp.get('/api/reference/<project_id>/export')
    def export_project(project_id):
        try:
            data = read_project(project_id)
            folder = project_path(project_id)
        except (ValueError, OSError):
            return jsonify(error='Reference project not found.'), 404
        if data['state'] != 'ready' or not data.get('edited_image'):
            return jsonify(error='Prepare the reference and add your edited image before exporting.'), 409
        archive = folder / ('reference_set_' + data['edited_image'] + '.zip')
        if archive.exists():
            return send_file(archive, as_attachment=True, download_name='Kling_reference_set.zip')
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as z:
            z.write(folder / data['video'], data['video'])
            z.write(folder / data['frame'], 'first_frame.png')
            z.write(folder / data['edited_image'], 'influencer_image.png')
            z.writestr('README.txt', 'Reference preparation for Kling motion control\n\nUse reference_video with influencer_image.png.\nfirst_frame.png is the original matching frame for comparison.\nThe edited image was supplied by you; no AI service was contacted by this app.\n\nSelected source start: ' + str(data['start_seconds']) + ' seconds.\n')
        return send_file(archive, as_attachment=True, download_name='Kling_reference_set.zip')

    # --- Phase 6: Carousel & Still Image Workspace ---

    @bp.post('/api/carousel/create')
    def create_carousel():
        uploads = [u for u in request.files.getlist('images') if u and u.filename]
        if not uploads or len(uploads) > 30:
            return jsonify(error='Choose between 1 and 30 still images (PNG, JPEG, or WebP) for a carousel.'), 400
        cid = uuid.uuid4().hex
        folder = carousel_path(cid)
        folder.mkdir(parents=True, exist_ok=False)
        settings = {**CAROUSEL_DEFAULTS}
        aspect = request.form.get('aspect', 'portrait')
        if aspect in CAROUSEL_PRESETS:
            settings['aspect'] = aspect
        slides = []
        try:
            for idx, up in enumerate(uploads, start=1):
                ext = Path(up.filename or '').suffix.lower()
                if ext not in {'.png', '.jpg', '.jpeg', '.webp'}:
                    raise ValueError('Choose PNG, JPEG, or WebP images.')
                sid = f's{idx:02d}_{uuid.uuid4().hex[:6]}'
                orig_name = f'orig_{idx:02d}{ext}'
                render_name = f'slide_{idx:02d}.png'
                orig_file = folder / orig_name
                up.save(orig_file)
                with Image.open(orig_file) as raw:
                    if getattr(raw, 'n_frames', 1) != 1:
                        raise ValueError('Choose still images only.')
                slide = dict(id=sid, original=orig_name, file=render_name, caption='', rotate=0, crop_x=50, crop_y=50)
                dims = render_carousel_slide(orig_file, folder / render_name, settings, slide)
                slide['dimensions'] = dims
                slides.append(slide)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            shutil.rmtree(folder, ignore_errors=True)
            return jsonify(error=str(exc) or 'Could not create carousel.'), 400
        name = safe_media_name(request.form.get('name') or uploads[0].filename or 'Carousel')
        data = dict(id=cid, name=name, state='ready', settings=settings, slides=slides)
        save_project(folder, data)
        refresh_gallery()
        return jsonify(data), 201

    @bp.get('/api/carousel/projects')
    def list_carousels():
        items = []
        if carousel_root.exists():
            for path in sorted(carousel_root.glob('*/project.json'), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    items.append(json.loads(path.read_text(encoding='utf-8')))
                except (ValueError, OSError):
                    continue
        return jsonify(items)

    @bp.get('/api/carousel/<cid>')
    def get_carousel(cid):
        try:
            folder = carousel_path(cid)
            return jsonify(json.loads((folder / 'project.json').read_text(encoding='utf-8')))
        except (ValueError, OSError):
            return jsonify(error='Carousel project not found.'), 404

    @bp.post('/api/carousel/<cid>/update')
    def update_carousel(cid):
        try:
            folder = carousel_path(cid)
            data = json.loads((folder / 'project.json').read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return jsonify(error='Carousel project not found.'), 404
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify(error='Invalid carousel update payload.'), 400
        settings = {**CAROUSEL_DEFAULTS, **data.get('settings', {}), **(payload.get('settings') or {})}
        if settings['aspect'] not in CAROUSEL_PRESETS or settings['fit'] not in {'fill', 'fit'}:
            return jsonify(error='Choose a supported carousel aspect ratio and fit mode.'), 400

        slide_map = {s['id']: s for s in data['slides']}
        for patch_item in payload.get('slides') or []:
            if isinstance(patch_item, dict) and patch_item.get('id') in slide_map:
                target = slide_map[patch_item['id']]
                if 'caption' in patch_item:
                    target['caption'] = str(patch_item['caption'] or '').strip()[:300]
                if 'rotate' in patch_item:
                    target['rotate'] = int(patch_item['rotate'] or 0) % 360
                if 'crop_x' in patch_item:
                    target['crop_x'] = max(0.0, min(100.0, float(patch_item['crop_x'])))
                if 'crop_y' in patch_item:
                    target['crop_y'] = max(0.0, min(100.0, float(patch_item['crop_y'])))

        order = payload.get('order')
        if isinstance(order, list) and len(order) == len(slide_map) and set(order) == set(slide_map):
            ordered_slides = [slide_map[sid] for sid in order]
        else:
            ordered_slides = data['slides']

        for idx, slide in enumerate(ordered_slides, start=1):
            slide['file'] = f'slide_{idx:02d}.png'
            orig_file = folder / slide['original']
            slide['dimensions'] = render_carousel_slide(orig_file, folder / slide['file'], settings, slide)

        data.update(settings=settings, slides=ordered_slides)
        save_project(folder, data)
        refresh_gallery()
        return jsonify(data)

    @bp.get('/api/carousel/<cid>/media/<name>')
    def carousel_media(cid, name):
        try:
            folder = carousel_path(cid)
            data = json.loads((folder / 'project.json').read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return jsonify(error='Carousel not found.'), 404
        allowed = {s['file'] for s in data.get('slides', [])} | {s['original'] for s in data.get('slides', [])}
        if name not in allowed or not (folder / name).is_file():
            return jsonify(error='Slide image not found.'), 404
        return send_file(folder / name, conditional=True)

    @bp.get('/api/carousel/<cid>/export')
    def export_carousel(cid):
        try:
            folder = carousel_path(cid)
            data = json.loads((folder / 'project.json').read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return jsonify(error='Carousel not found.'), 404
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_STORED) as z:
            for idx, slide in enumerate(data.get('slides', []), start=1):
                z.write(folder / slide['file'], f'{idx:02d}_{slide["file"]}')
        buf.seek(0)
        return send_file(buf, mimetype='application/zip', as_attachment=True, download_name=f'carousel_{cid[:8]}.zip')

    app.register_blueprint(bp)
