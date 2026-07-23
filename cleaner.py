import os
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
        if part.startswith('.') or part == 'desktop.ini' or part == 'backup_unscrambled':
            return True
    return False

def backup_file(file_path, base_backup_dir):
    try:
        backup_dir = os.path.join(base_backup_dir, "backup_unscrambled")
        rel_path = os.path.relpath(file_path, base_backup_dir)
        backup_path = os.path.join(backup_dir, rel_path)
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        shutil.copy2(file_path, backup_path)
        return True
    except Exception as e:
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
            except:
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

def run_batch_cleaner(target_dirs, base_backup_dir):
    """
    Generator function that yields log messages to stream via SSE.
    """
    total_renamed = 0
    total_scrambled = 0
    total_videos = 0
    
    yield f"data: {{\\"status\\": \\"Starting Batch Cleaner...\\"}}\n\n"
    
    registry_file = os.path.join(base_backup_dir, "scramble_registry.txt")
    video_registry_file = os.path.join(base_backup_dir, "video_scramble_registry.txt")
    
    def load_registry(path):
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    return set(line.strip() for line in f if line.strip())
            except:
                pass
        return set()

    def save_registry(path, item):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'a', encoding='utf-8', errors='replace') as f:
                f.write(item + '\n')
        except:
            pass

    photo_registry = load_registry(registry_file)
    video_registry = load_registry(video_registry_file)
    
    dirs_to_process = []
    
    for root_dir in target_dirs:
        if os.path.isfile(root_dir):
            dirname = os.path.dirname(root_dir)
            fname = os.path.basename(root_dir)
            ext = os.path.splitext(fname)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                if fname.lower().startswith('photo_'):
                    dirs_to_process.append((dirname, [fname], [], []))
                else:
                    dirs_to_process.append((dirname, [], [(fname, ext)], []))
            elif ext in VIDEO_EXTENSIONS:
                dirs_to_process.append((dirname, [], [], [(fname, ext)]))
            continue
            
        if not os.path.isdir(root_dir):
            yield f"data: {{\\"status\\": \\"Skipping {root_dir} (not found)\\"}}\n\n"
            continue
            
        for dirpath, dirnames, filenames in os.walk(root_dir):
            if should_skip_dir(dirpath):
                continue
                
            existing_photos = []
            files_to_rename = []
            videos_to_process = []
            
            for f in filenames:
                ext = os.path.splitext(f)[1].lower()
                if ext in IMAGE_EXTENSIONS:
                    if f.lower().startswith('photo_'):
                        existing_photos.append(f)
                    else:
                        files_to_rename.append((f, ext))
                elif ext in VIDEO_EXTENSIONS:
                    videos_to_process.append((f, ext))
            
            if existing_photos or files_to_rename or videos_to_process:
                dirs_to_process.append((dirpath, existing_photos, files_to_rename, videos_to_process))
            
    for subdir, existing_photos, files_to_rename, videos_to_process in sorted(dirs_to_process, key=lambda x: x[0].lower()):
        yield f"data: {{\\"status\\": \\"Processing folder: {subdir}\\"}}\n\n"
        
        # 1. Rename Photos
        used_numbers = set()
        for f in existing_photos:
            match = NUM_PATTERN.match(f)
            if match:
                used_numbers.add(int(match.group(1)))
                
        next_number = max(used_numbers) + 1 if used_numbers else 1
        
        if files_to_rename:
            files_to_rename.sort(key=lambda x: x[0].lower())
            
            temp_renames = []
            for idx, (original_name, ext) in enumerate(files_to_rename):
                original_path = os.path.join(subdir, original_name)
                temp_name = f"__temp_rename_new_{idx}__{ext}"
                temp_path = os.path.join(subdir, temp_name)
                try:
                    os.rename(original_path, temp_path)
                    temp_renames.append((temp_path, ext, original_name))
                except Exception as e:
                    yield f"data: {{\\"status\\": \\"  [Error] Failed to rename {original_name}: {str(e)}\\"}}\n\n"
            
            if temp_renames:
                for idx, (temp_path, ext, original_name) in enumerate(temp_renames):
                    num = next_number + idx
                    final_name = f"photo_{num}{ext}"
                    final_path = os.path.join(subdir, final_name)
                    try:
                        os.rename(temp_path, final_path)
                        yield f"data: {{\\"status\\": \\"  [Renamed] {original_name} -> {final_name}\\"}}\n\n"
                        total_renamed += 1
                        existing_photos.append(final_name)
                    except Exception as e:
                        yield f"data: {{\\"status\\": \\"  [Error] Final rename failed for {final_name}: {str(e)}\\"}}\n\n"
                        
        # 2. Scramble Photos
        for f in existing_photos:
            file_path = os.path.join(subdir, f)
            norm_path = os.path.normpath(file_path)
            
            if norm_path not in photo_registry:
                if backup_file(norm_path, base_backup_dir):
                    success, msg = clean_photo(norm_path)
                    if success:
                        yield f"data: {{\\"status\\": \\"  [Cleaned Photo] {f}\\"}}\n\n"
                        save_registry(registry_file, norm_path)
                        photo_registry.add(norm_path)
                        total_scrambled += 1
                    else:
                        yield f"data: {{\\"status\\": \\"  [Error] Photo clean failed on {f}: {msg}\\"}}\n\n"
                        
        # 3. Process Videos
        for f, ext in videos_to_process:
            file_path = os.path.join(subdir, f)
            norm_path = os.path.normpath(file_path)
            
            if norm_path not in video_registry:
                if backup_file(norm_path, base_music_dir):
                    yield f"data: {{\\"status\\": \\"  [Processing Video] {f}...\\"}}\n\n"
                    success, msg = clean_video(norm_path)
                    if success:
                        yield f"data: {{\\"status\\": \\"  [Cleaned Video] {f}\\"}}\n\n"
                        save_registry(video_registry_file, norm_path)
                        video_registry.add(norm_path)
                        total_videos += 1
                    else:
                        yield f"data: {{\\"status\\": \\"  [Error] Video clean failed on {f}: {msg}\\"}}\n\n"

    yield f"data: {{\\"status\\": \\"Batch Cleaner Completed! Renamed: {total_renamed}, Cleaned Photos: {total_scrambled}, Cleaned Videos: {total_videos}.\\", \\"done\\": true}}\n\n"
