import os
import json
import sys
import subprocess
import shutil
import re
import numpy as np
from PIL import Image

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

def clean_video(file_path, ffmpeg_exe=None):
    if not ffmpeg_exe:
        if imageio_ffmpeg:
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        else:
            ffmpeg_exe = "ffmpeg"
            
    temp_output = file_path + ".tmp_clean.mp4"
    cmd = [
        ffmpeg_exe, "-y", "-i", file_path,
        "-vf", "crop=in_w*0.995:in_h*0.995,noise=alls=1.2:allf=t+u",
        "-map_metadata", "-1", "-map_chapters", "-1",
        "-c:v", "libx264", "-crf", "17", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-c:a", "copy",
        "-movflags", "+faststart",
        temp_output
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        if result.returncode == 0 and os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
            shutil.move(temp_output, file_path)
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

def clean_photo(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    try:
        with Image.open(file_path) as img:
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
                
            width, height = img.size
            crop_w = max(int(width * 0.005), 2)
            crop_h = max(int(height * 0.005), 2)
            cropped_img = img.crop((crop_w, crop_h, width - crop_w, height - crop_h))
            
            arr = np.array(cropped_img, dtype=np.float32)
            h, w, c = arr.shape
            noise = np.random.normal(0, 1.2, (h, w))
            
            for i in range(min(c, 3)):
                arr[:, :, i] += noise
                
            clean_arr = np.clip(arr, 0, 255).astype(np.uint8)
            scrambled_img = Image.fromarray(clean_arr)
            
            if ext in ('.jpg', '.jpeg'):
                scrambled_img.save(file_path, 'JPEG', quality=98)
            elif ext == '.png':
                scrambled_img.save(file_path, 'PNG')
            else:
                scrambled_img.save(file_path)
            return True, "Success"
    except Exception as e:
        return False, str(e)

def make_sse(status_msg, done=False):
    data = {"status": status_msg}
    if done:
        data["done"] = True
    return "data: " + json.dumps(data) + "\n\n"

def run_batch_cleaner(target_dirs, output_dir, is_upload=False):
    """
    Generator function that yields log messages to stream via SSE.
    If is_upload=False, copies original files into output_dir and processes them there.
    If is_upload=True, target_dirs are already inside output_dir, process them in-place.
    """
    total_copied = 0
    total_renamed = 0
    total_scrambled = 0
    total_videos = 0
    
    yield make_sse("Starting Batch Cleaner...")
    
    registry_file = os.path.join(output_dir, "scramble_registry.txt")
    video_registry_file = os.path.join(output_dir, "video_scramble_registry.txt")
    
    def load_registry(path):
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    return set(line.strip() for line in f if line.strip())
            except Exception:
                pass
        return set()

    def save_registry(path, item):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'a', encoding='utf-8', errors='replace') as f:
                f.write(item + '\n')
        except Exception:
            pass

    photo_registry = load_registry(registry_file)
    video_registry = load_registry(video_registry_file)
    
    files_to_process = [] # list of (original_path, target_path, is_photo)

    for root_dir in target_dirs:
        if os.path.isfile(root_dir):
            ext = os.path.splitext(root_dir)[1].lower()
            if ext in IMAGE_EXTENSIONS or ext in VIDEO_EXTENSIONS:
                target_path = root_dir if is_upload else os.path.join(output_dir, os.path.basename(root_dir))
                files_to_process.append((root_dir, target_path, ext in IMAGE_EXTENSIONS))
            continue
            
        if not os.path.isdir(root_dir):
            yield make_sse(f"Skipping {root_dir} (not found)")
            continue
            
        for dirpath, dirnames, filenames in os.walk(root_dir):
            if should_skip_dir(dirpath):
                continue
                
            for f in filenames:
                ext = os.path.splitext(f)[1].lower()
                if ext in IMAGE_EXTENSIONS or ext in VIDEO_EXTENSIONS:
                    file_path = os.path.join(dirpath, f)
                    if is_upload:
                        target_path = file_path
                    else:
                        rel_path = os.path.relpath(file_path, root_dir)
                        folder_name = os.path.basename(os.path.normpath(root_dir))
                        target_path = os.path.join(output_dir, folder_name, rel_path)
                    
                    files_to_process.append((file_path, target_path, ext in IMAGE_EXTENSIONS))

    # Sort files so photos are together
    files_to_process.sort(key=lambda x: x[1])

    # 1. Copy Files if not uploaded
    if not is_upload:
        for orig, target, is_photo in files_to_process:
            norm_orig = os.path.normpath(orig)
            registry_set = photo_registry if is_photo else video_registry
            if norm_orig in registry_set:
                yield make_sse(f"Skipping already processed file: {orig}")
                continue
            
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(orig, target)
                total_copied += 1
            except Exception as e:
                yield make_sse(f"[Error] Failed to copy {orig}: {str(e)}")

    # Group by directory for renaming logic
    dirs_to_process = {}
    for orig, target, is_photo in files_to_process:
        norm_orig = os.path.normpath(orig)
        registry_set = photo_registry if is_photo else video_registry
        if not is_upload and norm_orig in registry_set:
            continue
            
        d = os.path.dirname(target)
        if d not in dirs_to_process:
            dirs_to_process[d] = {'photos': [], 'videos': []}
        
        if is_photo:
            dirs_to_process[d]['photos'].append((orig, target))
        else:
            dirs_to_process[d]['videos'].append((orig, target))

    for subdir, files in dirs_to_process.items():
        yield make_sse(f"Processing folder: {subdir}")
        
        photos = files['photos']
        videos = files['videos']
        
        # Rename logic
        existing_photo_names = [os.path.basename(t) for o, t in photos if os.path.basename(t).lower().startswith('photo_')]
        used_numbers = set()
        for f in existing_photo_names:
            match = NUM_PATTERN.match(f)
            if match:
                used_numbers.add(int(match.group(1)))
                
        next_number = max(used_numbers) + 1 if used_numbers else 1
        
        photos_to_rename = [(o, t) for o, t in photos if not os.path.basename(t).lower().startswith('photo_')]
        final_photos = [(o, t) for o, t in photos if os.path.basename(t).lower().startswith('photo_')]
        
        if photos_to_rename:
            for orig, target in photos_to_rename:
                ext = os.path.splitext(target)[1].lower()
                final_name = f"photo_{next_number}{ext}"
                final_path = os.path.join(subdir, final_name)
                try:
                    os.rename(target, final_path)
                    yield make_sse(f"  [Renamed] {os.path.basename(orig)} -> {final_name}")
                    total_renamed += 1
                    final_photos.append((orig, final_path))
                    next_number += 1
                except Exception as e:
                    yield make_sse(f"  [Error] Rename failed for {target}: {str(e)}")
                    final_photos.append((orig, target))
        
        # Scramble photos
        for orig, target in final_photos:
            if is_upload or os.path.normpath(orig) not in photo_registry:
                success, msg = clean_photo(target)
                if success:
                    yield make_sse(f"  [Cleaned Photo] {os.path.basename(target)}")
                    if not is_upload:
                        save_registry(registry_file, os.path.normpath(orig))
                        photo_registry.add(os.path.normpath(orig))
                    total_scrambled += 1
                else:
                    yield make_sse(f"  [Error] Photo clean failed on {target}: {msg}")
                    
        # Scramble videos
        for orig, target in videos:
            if is_upload or os.path.normpath(orig) not in video_registry:
                yield make_sse(f"  [Processing Video] {os.path.basename(target)}...")
                success, msg = clean_video(target)
                if success:
                    yield make_sse(f"  [Cleaned Video] {os.path.basename(target)}")
                    if not is_upload:
                        save_registry(video_registry_file, os.path.normpath(orig))
                        video_registry.add(os.path.normpath(orig))
                    total_videos += 1
                else:
                    yield make_sse(f"  [Error] Video clean failed on {target}: {msg}")

    yield make_sse(f"Batch Cleaner Completed! Copied: {total_copied}, Renamed: {total_renamed}, Cleaned Photos: {total_scrambled}, Cleaned Videos: {total_videos}.", done=True)
