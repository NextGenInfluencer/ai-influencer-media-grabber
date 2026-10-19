"""Local reference-image/video preparation. No generation service is contacted."""
import json
import math
import os
from pathlib import Path
import shutil
import job_process as subprocess
import threading
import uuid
import zipfile

from flask import Blueprint, jsonify, request, send_file
import imageio_ffmpeg
from PIL import Image, ImageOps

from media_safety import safe_media_name


def register_reference_prep(app, save_dir, job_started, job_finished, refresh_gallery):
    bp = Blueprint('reference_prep', __name__)
    root = Path(save_dir) / 'Kling References'
    lock = threading.Lock()

    def project_path(project_id):
        if len(project_id) != 32 or any(c not in '0123456789abcdef' for c in project_id):
            raise ValueError('Invalid project ID')
        return root / project_id

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
            data.update(state='ready', status='Reference set ready. Send first_frame.png to Nano Banana.', video=reference.name, frame=frame.name, dimensions=dimensions)
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

    app.register_blueprint(bp)
