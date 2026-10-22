import os
import json
import sys
import job_process as subprocess
import shutil
import re
import numpy as np
from PIL import Image, ImageOps
import uuid
import hashlib
import threading

_registry_lock = threading.Lock()

# Import imageio_ffmpeg for internal ffmpeg exe
try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tiff', '.heic', '.heif'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm', '.avi', '.mkv'}
NUM_PATTERN = re.compile(r'^photo_(\d+)', re.IGNORECASE)

def should_skip_dir(dir_path):
    parts = dir_path.split(os.sep)
    for part in parts:
        if part.startswith('.') or part == 'desktop.ini':
            return True
    return False

def clean_video(file_path, ffmpeg_exe=None, inject_exif=False):
    if not ffmpeg_exe:
        if imageio_ffmpeg:
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        else:
            ffmpeg_exe = "ffmpeg"
            
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        return False, 'Unsupported video format; original preserved.'
    temp_output = file_path + f".tmp_clean_{uuid.uuid4().hex}{ext}"
    cmd = [
        ffmpeg_exe, "-y", "-i", file_path,
        "-vf", "crop=max(2\\,trunc(in_w*0.995/2)*2):max(2\\,trunc(in_h*0.995/2)*2),noise=alls=1.2:allf=t+u",
        "-map_chapters", "-1",
        "-pix_fmt", "yuv420p", "-map_metadata", "-1"
    ]
    if ext == '.webm':
        cmd.extend(['-c:v', 'libvpx-vp9', '-crf', '17', '-b:v', '0', '-c:a', 'libopus'])
    else:
        try:
            import hwaccel
            enc_args = hwaccel.get_video_encoder_args(codec='h264', quality='high')
            cmd.extend([*enc_args, '-c:a', 'aac'])
        except Exception:
            cmd.extend(['-c:v', 'libx264', '-crf', '17', '-preset', 'fast', '-c:a', 'aac'])
    if ext in {'.mp4', '.mov', '.m4v'}:
        cmd.extend(['-movflags', '+faststart'])
    
    if inject_exif:
        cmd.extend([
            "-metadata", "creation_time=now",
            "-metadata", "make=Apple",
            "-metadata", "model=iPhone 15 Pro",
            "-metadata", "software=iOS 17.5"
        ])
    else:
        cmd.extend(["-map_metadata", "-1"])
        
    cmd.append(temp_output)
    
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        if result.returncode == 0 and os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
            os.replace(temp_output, file_path)
            return True, "Success"
        else:
            err = result.stderr[-200:] if result.stderr else "Unknown FFmpeg error"
            if os.path.exists(temp_output):
                os.remove(temp_output)
            return False, f"FFmpeg failed: {err}"
    except Exception as e:
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except Exception:
                pass
        return False, str(e)

def get_fake_exif():
    try:
        import piexif
        from datetime import datetime
        zeroth_ifd = {
            piexif.ImageIFD.Make: u"Apple",
            piexif.ImageIFD.Model: u"iPhone 15 Pro",
            piexif.ImageIFD.Software: u"iOS 17.5",
            piexif.ImageIFD.DateTime: datetime.now().strftime("%Y:%m:%d %H:%M:%S")
        }
        exif_ifd = {
            piexif.ExifIFD.LensMake: u"Apple",
            piexif.ExifIFD.LensModel: u"iPhone 15 Pro back camera 24mm f/1.78",
            piexif.ExifIFD.ISOSpeedRatings: 64,
            piexif.ExifIFD.FocalLength: (24, 1),
            piexif.ExifIFD.FNumber: (178, 100)
        }
        return piexif.dump({"0th": zeroth_ifd, "Exif": exif_ifd})
    except ImportError:
        return None

def backup_file(file_path, save_dir):
    # A failed backup must stop the caller before it changes the source.
    backup_dir = os.path.join(save_dir, "AI Cleaned", "Original Backups", uuid.uuid4().hex)
    os.makedirs(backup_dir, exist_ok=False)
    backup_path = os.path.join(backup_dir, os.path.basename(file_path))
    shutil.copy2(file_path, backup_path)
    if os.path.getsize(backup_path) != os.path.getsize(file_path):
        raise OSError('Backup verification failed; original was not processed.')
    return backup_path

def clean_photo(file_path, inject_exif=False):
    ext = os.path.splitext(file_path)[1].lower()
    temp_output = file_path + f'.tmp_{uuid.uuid4().hex}{ext}'
    try:
        with Image.open(file_path) as img:
            # Do not silently flatten animation or multipage images.
            if getattr(img, 'n_frames', 1) > 1:
                return False, 'Animated/multipage images are not supported by the cleaner; original preserved.'
            icc_profile = img.info.get('icc_profile')
            img = ImageOps.exif_transpose(img)
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
                
            width, height = img.size
            crop_w = min(max(int(width * 0.005), 2), (width - 1) // 2)
            crop_h = min(max(int(height * 0.005), 2), (height - 1) // 2)
            cropped_img = img.crop((crop_w, crop_h, width - crop_w, height - crop_h))
            
            arr = np.array(cropped_img, dtype=np.float32)
            h, w, c = arr.shape
            noise = np.random.normal(0, 1.2, (h, w))
            
            for i in range(min(c, 3)):
                arr[:, :, i] += noise
                
            clean_arr = np.clip(arr, 0, 255).astype(np.uint8)
            scrambled_img = Image.fromarray(clean_arr)
            
            exif_bytes = get_fake_exif() if inject_exif else None
            save_options = {'icc_profile': icc_profile} if icc_profile else {}
            
            if ext in ('.jpg', '.jpeg'):
                if exif_bytes:
                    scrambled_img.save(temp_output, 'JPEG', quality=98, exif=exif_bytes, **save_options)
                else:
                    scrambled_img.save(temp_output, 'JPEG', quality=98, **save_options)
            elif ext == '.png':
                scrambled_img.save(temp_output, 'PNG', **save_options)
            else:
                scrambled_img.save(temp_output, **save_options)
        os.replace(temp_output, file_path)
        return True, 'Success'
    except Exception as e:
        return False, str(e)
    finally:
        if os.path.exists(temp_output):
            os.remove(temp_output)

def make_sse(status_msg, done=False):
    data = {"status": status_msg}
    if done:
        data["done"] = True
    return "data: " + json.dumps(data) + "\n\n"

def run_batch_cleaner(target_dirs, output_dir, is_upload=False, inject_exif=False):
    """Create a separate output per source; never modify selected originals."""
    from media_safety import contained_path, safe_media_name
    output_dir = os.path.realpath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    batch_dir = os.path.join(output_dir, 'Batch_' + uuid.uuid4().hex[:12])
    os.makedirs(batch_dir, exist_ok=False)
    yield make_sse('Starting batch; originals will be preserved.')
    sources = []
    seen = set()
    for selected in target_dirs:
        selected = os.path.realpath(selected)
        if not is_upload and contained_path(selected, output_dir):
            yield make_sse('Skipping cleaner output: ' + selected)
            continue
        if os.path.isfile(selected):
            candidates = [selected]
        else:
            candidates = []
            for root, dirs, names in os.walk(selected):
                dirs[:] = [d for d in dirs if not d.startswith('.') and not contained_path(os.path.join(root, d), output_dir)]
                candidates.extend(os.path.join(root, name) for name in names)
        for source in candidates:
            key = os.path.normcase(os.path.realpath(source))
            if key in seen or os.path.splitext(source)[1].lower() not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
                continue
            seen.add(key)
            sources.append(source)
    registry_path = os.path.join(output_dir, '.cleaner_registry.json')
    def read_registry():
        try:
            with open(registry_path, encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    succeeded = failed = skipped = 0
    for index, source in enumerate(sources, 1):
        subprocess.check_cancelled()
        name = safe_media_name(os.path.basename(source))
        stem, ext = os.path.splitext(name)
        target = os.path.join(batch_dir, f'{stem}_{uuid.uuid4().hex[:10]}{ext}')
        yield make_sse(f'[{index}/{len(sources)}] Processing {name}...')
        try:
            digest = hashlib.sha256()
            with open(source, 'rb') as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b''):
                    digest.update(chunk)
            key = f'v2:{ext}:{bool(inject_exif)}:{digest.hexdigest()}'
            with _registry_lock:
                previous = read_registry().get(key)
            if isinstance(previous, str):
                previous = os.path.join(output_dir, previous)
                if contained_path(previous, output_dir) and os.path.isfile(previous):
                    skipped += 1
                    yield make_sse('Already processed; existing output: ' + previous)
                    continue
            shutil.copy2(source, target)
            if ext in IMAGE_EXTENSIONS:
                ok, message = clean_photo(target, inject_exif)
            else:
                ok, message = clean_video(target, inject_exif=inject_exif)
            if not ok:
                os.remove(target)
                raise RuntimeError(message)
            succeeded += 1
            with _registry_lock:
                registry = read_registry()
                registry[key] = os.path.relpath(target, output_dir)
                temp_registry = registry_path + '.' + uuid.uuid4().hex
                with open(temp_registry, 'w', encoding='utf-8') as f:
                    json.dump(registry, f)
                os.replace(temp_registry, registry_path)
            yield make_sse('Saved: ' + target)
        except Exception as e:
            failed += 1
            yield make_sse(f'[Error] {name}: {e}')
    if not sources:
        yield 'data: ' + json.dumps({'error': 'No supported source media found.', 'done': True}) + '\n\n'
    else:
        yield 'data: ' + json.dumps({'status': f'Finished: {succeeded} saved, {skipped} already processed, {failed} failed. Originals preserved.', 'done': True, 'failed_count': failed, **({'error': f'{failed} item(s) failed. Originals preserved.'} if failed else {}), 'output_path': batch_dir}) + '\n\n'
