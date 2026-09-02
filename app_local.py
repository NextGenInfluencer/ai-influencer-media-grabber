import os
import re
import sys
import string
import subprocess
import threading
import uuid
from flask import Flask, render_template, request, jsonify, Response, send_file, send_from_directory
import queue
import json
import imageio_ffmpeg
import asyncio
import tempfile
import shutil
from shazamio import Shazam
import time
import numpy as np
import yt_dlp

# Global dict to store cancel flags for download tasks
cancel_flags = {}

# Ensure the Documents/Media Grabber folder exists immediately on startup
DEFAULT_SAVE_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Media Grabber")
os.makedirs(DEFAULT_SAVE_DIR, exist_ok=True)
for sub in ['YouTube', 'Instagram', 'TikTok', 'Twitter', 'Other', 'Conversions']:
    os.makedirs(os.path.join(DEFAULT_SAVE_DIR, sub), exist_ok=True)

HISTORY_FILE = os.path.join(DEFAULT_SAVE_DIR, "history.json")
history_lock = threading.RLock()

def load_history():
    with history_lock:
        if not os.path.exists(HISTORY_FILE): return []
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception: return []

def save_history(data):
    with history_lock:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
    
def add_history_entry(url, title, uploader, file_path, platform):
    with history_lock:
        h = load_history()
        h.insert(0, {
            "id": str(uuid.uuid4()),
            "url": url,
            "title": title,
            "uploader": uploader,
            "file_path": file_path,
            "platform": platform,
            "timestamp": time.time()
        })
        save_history(h)

# Ensure ffmpeg is in PATH for whisper
os.environ["PATH"] += os.pathsep + os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())

import gc
whisper_model = None
_whisper_timer = None

def unload_whisper():
    global whisper_model, _whisper_timer
    if whisper_model is not None:
        print("Unloading Whisper model to free memory...")
        whisper_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception: pass
        gc.collect()
    _whisper_timer = None

def get_whisper():
    global whisper_model, _whisper_timer
    if _whisper_timer is not None:
        _whisper_timer.cancel()
    if whisper_model is None:
        import whisper
        print("Loading Whisper model (this may take a moment)...")
        whisper_model = whisper.load_model("base")
    _whisper_timer = threading.Timer(600, unload_whisper)
    _whisper_timer.daemon = True
    _whisper_timer.start()
    return whisper_model

llm_model = None
_llm_timer = None
_current_llm_id = None

def unload_llm():
    global llm_model, _llm_timer, _current_llm_id
    if llm_model is not None:
        del llm_model
        llm_model = None
        _current_llm_id = None
        gc.collect()
    _llm_timer = None

def get_llm(model_id="llama-3.2-1b"):
    global llm_model, _llm_timer, _current_llm_id
    if _llm_timer is not None:
        _llm_timer.cancel()
        
    if llm_model is None or _current_llm_id != model_id:
        if llm_model is not None: unload_llm()
        
        from llama_cpp import Llama
        from huggingface_hub import hf_hub_download
        
        models_dir = os.path.join(app.root_path, "ai_models")
        os.makedirs(models_dir, exist_ok=True)
        
        print(f"Loading Local LLM ({model_id})...")
        if model_id == "llama-3-8b":
            repo_id = "QuantFactory/Meta-Llama-3-8B-Instruct-GGUF"
            filename = "Meta-Llama-3-8B-Instruct.Q4_K_M.gguf"
        else: # Default: Llama 3.2 1B
            repo_id = "bartowski/Llama-3.2-1B-Instruct-GGUF"
            filename = "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
            
        model_path = os.path.join(models_dir, filename)
        if not os.path.exists(model_path):
            print(f"Downloading {filename} from HuggingFace (First time only)...")
            hf_hub_download(repo_id=repo_id, filename=filename, local_dir=models_dir)
            
        # Initialize Llama model
        llm_model = Llama(
            model_path=model_path,
            n_gpu_layers=-1, # Auto-detect GPU if possible
            n_ctx=4096,
            verbose=False
        )
        _current_llm_id = model_id
        
    _llm_timer = threading.Timer(600, unload_llm)
    _llm_timer.daemon = True
    _llm_timer.start()
    return llm_model

def llm_generate(prompt, system_prompt="You are a helpful AI assistant.", model_id="llama-3.2-1b"):
    llm = get_llm(model_id)
    response = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=1024
    )
    return response['choices'][0]['message']['content'].strip()

# Cache the face detection cascade globally but initialize lazily
_face_cascade = None

def dynamic_auto_crop(input_path, output_path, q=None, prefix=""):
    import cv2
    import cv2.data # type: ignore
    global _face_cascade
    if _face_cascade is None:
        _face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml') # type: ignore
        
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        return False
        
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0: fps = 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    target_width = int(height * (9 / 16))
    if target_width > width: target_width = width
    if width <= height:
        cap.release()
        return False
        
    face_cascade = _face_cascade
    
    if q: q.put({"status": f"{prefix}Scanning video for face tracking..."})
    
    keyframe_interval = max(1, int(fps / 2)) # Twice a second
    frame_centers = []
    frame_idx = 0
    last_center = width // 2
    
    while cap.isOpened() and frame_idx < total_frames:
        ret, frame = cap.read()
        if not ret: break
        
        if frame_idx % keyframe_interval == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (0,0), fx=0.5, fy=0.5)
            faces = face_cascade.detectMultiScale(small, 1.1, 4)
            if len(faces) > 0:
                faces = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)
                (x, y, w, h) = faces[0]
                last_center = (x + w//2) * 2
            frame_centers.append((frame_idx, last_center))
        frame_idx += 1
    cap.release()
    
    if not frame_centers: return False
    
    smoothed_centers = []
    all_centers = [width//2] * frame_idx
    for i in range(len(frame_centers) - 1):
        idx1, c1 = frame_centers[i]
        idx2, c2 = frame_centers[i+1]
        for j in range(idx1, idx2):
            all_centers[j] = int(c1 + (c2 - c1) * (j - idx1) / (idx2 - idx1))
    if frame_centers:
        idx_last, c_last = frame_centers[-1]
        for j in range(idx_last, frame_idx): all_centers[j] = c_last
        
    alpha = 0.05
    current_smooth = all_centers[0]
    for c in all_centers:
        current_smooth = alpha * c + (1 - alpha) * current_smooth
        clamped = max(target_width // 2, min(width - target_width // 2, int(current_smooth)))
        smoothed_centers.append(clamped)
        
    if q: q.put({"status": f"{prefix}Rendering dynamic face-tracked video..."})
    
    cap = cv2.VideoCapture(input_path)
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe() if imageio_ffmpeg else "ffmpeg"
    
    cmd = [
        ffmpeg_exe, '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{target_width}x{height}', '-pix_fmt', 'bgr24', '-r', str(fps),
        '-i', '-', '-i', input_path, '-map', '0:v', '-map', '1:a?', 
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '17', '-c:a', 'copy',
        output_path
    ]
    
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        
        c = smoothed_centers[frame_idx] if frame_idx < len(smoothed_centers) else smoothed_centers[-1]
        x_start = c - target_width // 2
        cropped = frame[:, x_start:x_start+target_width]
        
        try: process.stdin.write(cropped.tobytes())
        except Exception: break
        frame_idx += 1
        if q and frame_idx % int(fps * 2) == 0 and total_frames > 0:
            pct = int(frame_idx/total_frames*100)
            q.put({"status": f"{prefix}Rendering face-tracked video... ({pct}%)"})
            
    cap.release()
    try: 
        process.stdin.close()
        process.wait()
    except Exception: pass
    
    return os.path.exists(output_path) and os.path.getsize(output_path) > 0

app = Flask(__name__)
# Allow large file uploads (500MB max)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

# Auto-update yt-dlp once per day
update_flag_file = os.path.join(DEFAULT_SAVE_DIR, ".last_update")
should_update = True
if os.path.exists(update_flag_file):
    last_update = os.path.getmtime(update_flag_file)
    if time.time() - last_update < 86400: # 24 hours
        should_update = False

if should_update:
    print("Checking for yt-dlp updates...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp", "-q"])
    with open(update_flag_file, 'w') as f:
        f.write(str(time.time()))
else:
    print("yt-dlp update check skipped (already checked today).")

def sanitize_filename(name):
    # Remove illegal characters for Windows/Linux/Mac
    return re.sub(r'[\\/*?:"<>|]', "", name)

def is_safe_path(path):
    try:
        abs_path = os.path.abspath(path)
        return abs_path.startswith(os.path.abspath(DEFAULT_SAVE_DIR))
    except Exception:
        return False

def shazam_file(audio_path):
    async def recognize():
        shazam = Shazam()
        return await shazam.recognize(audio_path)
    try:
        return asyncio.run(recognize())
    except Exception as e:
        print("Shazam error:", e)
        return None

APP_VERSION = "1.8"

@app.route('/')
def index():
    return render_template('index.html', version=APP_VERSION)


@app.route('/api/list_drives', methods=['GET'])
def list_drives():
    """List available drive letters on Windows, or root on Unix."""
    drives = []
    if os.name == 'nt':
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                drives.append(drive)
    else:
        drives = ['/']
    return jsonify({"drives": drives})

@app.route('/api/list_dirs', methods=['POST'])
def list_dirs():
    """List subdirectories of a given path."""
    data = request.get_json() or {}
    path = data.get('path', '')
    if not path:
        path = os.path.expanduser('~')
    
    try:
        entries = []
        for entry in sorted(os.scandir(path), key=lambda e: e.name.lower()):
            if entry.is_dir() and not entry.name.startswith('.'):
                try:
                    # Check if we can access it
                    os.listdir(entry.path)
                    entries.append({"name": entry.name, "path": entry.path.replace('\\', '/')})
                except PermissionError:
                    pass
        return jsonify({"path": path.replace('\\', '/'), "dirs": entries})
    except Exception as e:
        return jsonify({"error": str(e), "path": path, "dirs": []}), 200

@app.route('/api/list_files', methods=['POST'])
def list_files_endpoint():
    """List media files in a given path."""
    data = request.get_json() or {}
    path = data.get('path', '')
    if not path:
        path = os.path.expanduser('~')
    
    media_exts = {'.mp4', '.mov', '.m4v', '.webm', '.avi', '.mkv', '.jpg', '.png', '.jpeg', '.webp'}
    try:
        files = []
        dirs = []
        for entry in sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.is_dir() and not entry.name.startswith('.'):
                try:
                    os.listdir(entry.path)
                    dirs.append({"name": entry.name, "path": entry.path.replace('\\', '/'), "is_dir": True})
                except PermissionError:
                    pass
            elif entry.is_file():
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in media_exts:
                    files.append({"name": entry.name, "path": entry.path.replace('\\', '/'), "is_dir": False})
        return jsonify({"path": path.replace('\\', '/'), "entries": dirs + files})
    except Exception as e:
        return jsonify({"error": str(e), "path": path, "entries": []}), 200

@app.route('/api/convert', methods=['POST'])
def convert_media():
    if 'files' not in request.files:
        return jsonify({"error": "No files provided"}), 400
        
    files = request.files.getlist('files')
    resize = request.form.get('resize')
    format_opt = request.form.get('format')
    autocrop = request.form.get('autocrop') == 'true'
    burn_subtitles = request.form.get('burn_subtitles') == 'true'
    export_subtitles = request.form.get('export_subtitles') == 'true'
    translate_lang = request.form.get('translate_lang', 'none')
    llm_model = request.form.get('llmModel', 'none')
    trim_start = request.form.get('trimStart')
    trim_end = request.form.get('trimEnd')
    compress_opt = request.form.get('compress')
    
    if not files or files[0].filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    output_dir = os.path.join(os.path.expanduser("~"), "Documents", "Media Grabber", "Conversions")
    os.makedirs(output_dir, exist_ok=True)
    
    # Save files synchronously before background thread
    saved_files = []
    # uuid is imported at the top of the file
    shared_temp_dir = tempfile.mkdtemp()
    for f in files:
        if f.filename:
            input_ext = os.path.splitext(f.filename)[1].lower()
            base_name = os.path.splitext(f.filename)[0]
            input_path = os.path.join(shared_temp_dir, f"{uuid.uuid4().hex}{input_ext}")
            f.save(input_path)
            saved_files.append({
                "original_name": f.filename,
                "base_name": base_name,
                "input_ext": input_ext,
                "path": input_path
            })
    
    def generate():
        yield f"data: {json.dumps({'status': 'Starting conversion...'})}\n\n"
        q = queue.Queue()
        
        def run_conv():
            total = len(saved_files)
            failed_count = 0
            
            for idx, file_data in enumerate(saved_files, 1):
                prefix = f"[{idx}/{total}] " if total > 1 else ""
                q.put({"status": f"{prefix}Processing {file_data['original_name']}..."})
                
                input_ext = file_data['input_ext']
                base_name = file_data['base_name']
                input_path = file_data['path']
                
                output_name = f"{base_name}_converted.{format_opt}"
                output_path = os.path.join(output_dir, output_name)
                
                # Prevent overwriting existing files in bulk directory
                counter = 1
                while os.path.exists(output_path):
                    output_name = f"{base_name}_converted_{counter}.{format_opt}"
                    output_path = os.path.join(output_dir, output_name)
                    counter += 1
                
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                cmd = [ffmpeg_exe, "-y"]
                
                if trim_start and trim_start.strip() and total == 1:
                    cmd.extend(["-ss", trim_start.strip()])
                    
                cmd.extend(["-i", input_path])
                
                if trim_end and trim_end.strip() and total == 1:
                    cmd.extend(["-to", trim_end.strip()])
                
                try:
                    vf_filters = []
                    crf_val = "23" # Default standard quality
                    
                    # 1. Smart Auto-Crop or Aspect Ratio Crop/Pad
                    if autocrop and format_opt not in ["mp3", "wav"] and input_ext not in [".mp3", ".wav", ".jpg", ".png", ".webp"]:
                        temp_crop_path = os.path.join(shared_temp_dir, f"{uuid.uuid4().hex}_precrop.mp4")
                        if dynamic_auto_crop(input_path, temp_crop_path, q, prefix):
                            input_path = temp_crop_path
                            # dynamic_auto_crop already crops to 9:16
                        else:
                            vf_filters.append("crop=ih*9/16:ih")
                    elif resize and resize != "none" and format_opt not in ["mp3", "wav"]:
                        if resize == "crop_9_16":
                            vf_filters.append("crop=ih*9/16:ih")
                        elif resize == "pad_9_16":
                            vf_filters.append("scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2")
                        elif resize == "crop_16_9":
                            vf_filters.append("crop=iw:iw*9/16")
                        elif resize == "pad_16_9":
                            vf_filters.append("scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2")
                        elif resize == "crop_1_1":
                            vf_filters.append("crop=min(iw\\,ih):min(iw\\,ih)")
                        elif resize == "crop_4_5":
                            vf_filters.append("crop=ih*4/5:ih")
                        elif resize == "pad_blur_9_16":
                            vf_filters.append("split[original][copy];[copy]scale=-1:1920,crop=1080:1920,boxblur=20:5[bg];[original]scale=1080:1920:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")

                    # 2. File Size & Resolution Scaling (MB Reduction)
                    if compress_opt and compress_opt != "none" and format_opt not in ["mp3", "wav"]:
                        if compress_opt == "scale_1080p":
                            vf_filters.append("scale='min(1080,iw)':'min(1920,ih)':force_original_aspect_ratio=decrease")
                        elif compress_opt == "scale_720p":
                            vf_filters.append("scale='min(720,iw)':'min(1280,ih)':force_original_aspect_ratio=decrease")
                            crf_val = "26"
                        elif compress_opt == "scale_480p":
                            vf_filters.append("scale='min(480,iw)':'min(854,ih)':force_original_aspect_ratio=decrease")
                            crf_val = "28"
                        elif compress_opt == "scale_50":
                            vf_filters.append("scale=iw*0.5:ih*0.5")
                            crf_val = "26"
                        elif compress_opt == "scale_25":
                            vf_filters.append("scale=iw*0.25:ih*0.25")
                            crf_val = "28"
                        elif compress_opt == "compress_high":
                            crf_val = "28" # ~50% MB size reduction
                            if format_opt == "gif":
                                vf_filters.append("scale=iw*0.5:ih*0.5")
                        elif compress_opt == "compress_web":
                            crf_val = "32" # ~75% MB size reduction (Web/Discord)
                            if format_opt == "gif":
                                vf_filters.append("scale=iw*0.33:ih*0.33")
                        elif compress_opt == "compress_80":
                            crf_val = "33" # ~80% MB size reduction
                            if format_opt == "gif":
                                vf_filters.append("scale=iw*0.27:ih*0.27")
                        elif compress_opt == "compress_85":
                            crf_val = "34" # ~85% MB size reduction
                            if format_opt == "gif":
                                vf_filters.append("scale=iw*0.21:ih*0.21")
                        elif compress_opt == "compress_extreme":
                            crf_val = "36" # ~90% MB size reduction
                            if format_opt == "gif":
                                vf_filters.append("scale=iw*0.15:ih*0.15")
                    
                    # Audio formats (ignore video filters)
                    if format_opt in ["mp3", "wav"]:
                        if format_opt == "mp3":
                            cmd.extend(["-vn", "-acodec", "libmp3lame", "-q:a", "2"])
                        else:
                            cmd.extend(["-vn", "-acodec", "pcm_s16le"])
                    else:
                        # Video or Image formats
                        if burn_subtitles or export_subtitles:
                            q.put({"status": f"{prefix}Generating Subtitles..."})
                            temp_audio = os.path.join(shared_temp_dir, f"{uuid.uuid4().hex}.mp3")
                            
                            # For export, we should place the SRT next to the output video
                            final_srt_path = os.path.splitext(output_path)[0] + "_subtitles.srt"
                            temp_srt = final_srt_path if export_subtitles else os.path.join(shared_temp_dir, f"{uuid.uuid4().hex}.srt")
                            
                            audio_cmd = [ffmpeg_exe, "-y", "-i", input_path, "-vn", "-acodec", "libmp3lame", temp_audio]
                            subprocess.run(audio_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            
                            if os.path.exists(temp_audio):
                                try:
                                    model = get_whisper()
                                    result = model.transcribe(temp_audio, verbose=False)
                                    
                                    def format_time(seconds):
                                        m, s = divmod(seconds, 60)
                                        h, m = divmod(m, 60)
                                        ms = int((s - int(s)) * 1000)
                                        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"
                                    
                                    with open(temp_srt, 'w', encoding='utf-8') as f:
                                        for i, segment in enumerate(result.get('segments', [])):
                                            f.write(f"{i + 1}\n")
                                            f.write(f"{format_time(segment['start'])} --> {format_time(segment['end'])}\n")
                                            f.write(f"{segment['text'].strip()}\n\n")
                                            
                                    if translate_lang and translate_lang != 'none' and llm_model and llm_model != 'none':
                                        q.put({"status": f"{prefix}Translating Subtitles to {translate_lang}..."})
                                        try:
                                            with open(temp_srt, 'r', encoding='utf-8') as tf:
                                                srt_content = tf.read()
                                            sys_p = f"You are a professional subtitle translator. Translate the following .srt file to {translate_lang}. Maintain the exact SRT formatting and timestamps. Output ONLY the translated SRT text."
                                            translated_srt = llm_generate(srt_content, sys_p, llm_model)
                                            with open(temp_srt, 'w', encoding='utf-8') as tf:
                                                tf.write(translated_srt)
                                        except Exception as e:
                                            print(f"Translation Error: {e}")
                                            
                                    if burn_subtitles:
                                        srt_escaped = temp_srt.replace('\\', '\\\\').replace(':', '\\:')
                                        vf_filters.append(f"subtitles='{srt_escaped}':force_style='FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2'")
                                except Exception as e:
                                    print("Subtitle error:", e)

                        if vf_filters:
                            cmd.extend(["-vf", ",".join(vf_filters)])
                            
                        if format_opt in ["mp4", "mkv", "mov", "avi"]:
                            cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", crf_val, "-c:a", "aac", "-pix_fmt", "yuv420p"])
                        elif format_opt == "webm":
                            cmd.extend(["-c:v", "libvpx", "-c:a", "libvorbis", "-crf", crf_val])
                        elif format_opt == "gif":
                            cmd.extend(["-r", "15"]) 
                        elif format_opt in ["jpg", "png", "webp"]:
                            if input_ext in ['.mp4', '.mov', '.mkv', '.webm', '.avi']:
                                cmd.extend(["-vframes", "1"])
                        else:
                            raise Exception("Invalid format")
                            
                    cmd.append(output_path)
                    
                    q.put({"status": f"{prefix}Encoding..."})
                    try:
                        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                    except subprocess.CalledProcessError as e:
                        print(f"FFmpeg Error:\n{e.stderr}")
                        raise e
                    
                    # Cleanup temp for this file immediately
                    try: os.remove(input_path) 
                    except Exception: pass
                    
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    failed_count += 1
                    err_msg = str(e)
                    q.put({"status": f"{prefix}Error converting file."})
                    with open(os.path.join(DEFAULT_SAVE_DIR, "converter_debug.log"), "a") as f:
                        f.write(f"Conversion Error:\n{traceback.format_exc()}\n")
                    time.sleep(3)
                    
            if failed_count == 0:
                q.put({"status": f"Successfully saved to {output_dir}", "done": True})
            else:
                q.put({"error": f"{failed_count} file(s) failed to convert. Check console logs."})
            
            import shutil
            try: shutil.rmtree(shared_temp_dir)
            except Exception: pass

        t = threading.Thread(target=run_conv, daemon=True)
        t.start()
        
        while True:
            try:
                msg = q.get(timeout=120)
            except queue.Empty:
                yield f"data: {json.dumps({'error': 'Task timed out.'})}\n\n"
                break
            yield f"data: {json.dumps(msg)}\n\n"
            if msg.get("done") or msg.get("error"):
                break
                
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/cancel/<task_id>', methods=['POST'])
def cancel_task(task_id):
    cancel_flags[task_id] = True
    return jsonify({"success": True})

@app.route('/api/preview', methods=['POST'])
def preview_url():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        return jsonify({"error": "Invalid URL scheme"}), 400
        
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'dump_single_json': True,
            'skip_download': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            return jsonify({
                "title": info.get('title', 'Unknown Title'),
                "uploader": info.get('uploader', 'Unknown Creator'),
                "thumbnail": info.get('thumbnail', ''),
                "duration": info.get('duration', 0)
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download_video():
    data = request.json
    urls_raw = data.get('url', '')
    output_path = data.get('path')
    custom_name = data.get('filename')
    browser = data.get('browser')
    task_id = data.get('task_id', 'unknown')
    processing_options = data.get('processing_options', {})

    # Ensure task is not cancelled before starting
    cancel_flags[task_id] = False

    urls = [u.strip() for u in urls_raw.split('\n') if u.strip().startswith(('http://', 'https://'))]

    if not urls:
        return jsonify({"error": "Valid URL(s) required"}), 400
        
    url = urls[0] # keeping url for downstream variable references, but loop uses urls
    if not output_path or not output_path.strip():
        output_path = os.path.join(os.path.expanduser("~"), "Documents", "Media Grabber")
        
    url_lower = url.lower()
    if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        output_path = os.path.join(output_path, 'YouTube')
    elif 'instagram.com' in url_lower:
        output_path = os.path.join(output_path, 'Instagram')
    elif 'tiktok.com' in url_lower:
        output_path = os.path.join(output_path, 'TikTok')
    elif 'twitter.com' in url_lower or 'x.com' in url_lower:
        output_path = os.path.join(output_path, 'Twitter')
    else:
        output_path = os.path.join(output_path, 'Other')
        
    os.makedirs(output_path, exist_ok=True)

    def generate():
        yield f"data: {json.dumps({'status': 'Fetching metadata...'})}\n\n"
        
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best' if processing_options.get('forceH264') else 'bestvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
            'merge_output_format': 'mp4',
            'outtmpl': os.path.join(output_path, '%(playlist_title,uploader)s', '%(playlist_index|)s%(playlist_index& - |)s%(title)s_%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe(),
            'retries': 10,
            'fragment_retries': 10,
            'socket_timeout': 30,
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'android', 'web']
                }
            }
        }

        if custom_name:
            clean_name = sanitize_filename(custom_name)
            if clean_name:
                ydl_opts['outtmpl'] = os.path.join(output_path, '%(playlist_title,uploader)s', f'%(playlist_index|)s%(playlist_index& - |)s{clean_name}_%(id)s.%(ext)s')
                
        if browser and browser != 'none':
            if browser == 'cookies.txt':
                ydl_opts['cookiefile'] = 'cookies.txt'
            else:
                ydl_opts['cookiesfrombrowser'] = (browser, None, None, None)
                
            # Add a random 5 to 15 second delay between downloads to simulate human behavior and prevent bans
            ydl_opts['sleep_interval'] = 5
            ydl_opts['max_sleep_interval'] = 15

        q = queue.Queue()

        def hook(d):
            if cancel_flags.get(task_id):
                raise Exception("Cancelled by user")
                
            if d['status'] == 'downloading':
                percent = d.get('_percent_str', '0%').strip()
                percent = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', percent)
                speed = d.get('_speed_str', '').strip()
                speed = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', speed)
                speed_text = f" at {speed}" if speed else ""
                q.put({"status": f"Downloading: {percent}{speed_text}"})
            elif d['status'] == 'finished':
                q.put({"status": "Merging files..."})
            elif d['status'] == 'error':
                q.put({"error": "Download failed inside hook"})

        ydl_opts['progress_hooks'] = [hook]

        def run_dl():
            total = len(urls)
            failed_count = 0
            last_final_path = None
            for idx, url in enumerate(urls, 1):
                prefix = f"[{idx}/{total}] " if total > 1 else ""
                q.put({"status": f"{prefix}Starting download..."})
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        try:
                            # Pre-flight check for file collisions to add (1) to filename
                            info_dict = ydl.extract_info(url, download=False)
                            if info_dict:
                                temp_final = ydl.prepare_filename(info_dict)
                                base, ext = os.path.splitext(temp_final)
                                if os.path.exists(temp_final) or os.path.exists(base + ".mp4"):
                                    orig_base = base
                                    c = 1
                                    while os.path.exists(f"{orig_base} ({c}){ext}") or os.path.exists(f"{orig_base} ({c}).mp4"):
                                        c += 1
                                    
                                    local_opts = ydl_opts.copy()
                                    local_opts['outtmpl'] = f"{orig_base} ({c}).%(ext)s"
                                    with yt_dlp.YoutubeDL(local_opts) as local_ydl:
                                        info = local_ydl.extract_info(url, download=True)
                                else:
                                    info = ydl.extract_info(url, download=True)
                            else:
                                info = ydl.extract_info(url, download=True)
                        except Exception as e:
                            err_msg = str(e)
                            err_msg = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', err_msg)
                            
                            if "Could not copy Chrome cookie database" in err_msg or "database is locked" in err_msg:
                                q.put({"status": f"{prefix}Error: Close Chrome entirely to use its cookies!"})
                                failed_count += 1
                                time.sleep(4)
                                continue
                            
                            if "No video formats found" in err_msg or "Unable to extract data" in err_msg or "HTTP Error 400" in err_msg or "Video info extraction failed" in err_msg:
                                q.put({"status": f"{prefix}Unsupported by yt-dlp. Downloading via gallery-dl..."})
                                
                                gdl_cmd = [sys.executable, "-m", "gallery_dl", "-d", output_path]
                                if browser and browser != 'none':
                                    if browser == 'cookies.txt':
                                        gdl_cmd.extend(["--cookies", "cookies.txt"])
                                    else:
                                        gdl_cmd.extend(["--cookies-from-browser", browser])
                                gdl_cmd.append(url)
                                
                                try:
                                    process = subprocess.Popen(gdl_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                                    for line in iter(process.stdout.readline, ''):
                                        if cancel_flags.get(task_id):
                                            process.terminate()
                                            q.put({"status": f"{prefix}Cancelled by user"})
                                            break
                                        
                                        line = line.strip()
                                        if line:
                                            short_line = line if len(line) < 60 else "..." + line[-57:]
                                            q.put({"status": f"gallery-dl: {short_line}"})
                                            
                                    process.stdout.close()
                                    return_code = process.wait()
                                    
                                    if return_code == 0:
                                        q.put({"status": f"{prefix}Successfully downloaded images/profile!"})
                                        add_history_entry(url, url, "Unknown", output_path, "Other")
                                        time.sleep(2)
                                        continue
                                    else:
                                        q.put({"status": f"{prefix}Gallery-DL failed."})
                                        failed_count += 1
                                        time.sleep(4)
                                        continue
                                except Exception as gdl_err:
                                    q.put({"status": f"{prefix}Gallery-DL Error: {str(gdl_err)}"})
                                    failed_count += 1
                                    time.sleep(4)
                                    continue

                            q.put({"status": f"{prefix}Error: {err_msg}"})
                            failed_count += 1
                            time.sleep(4)
                            continue
                            
                        if not info:
                            q.put({"status": f"{prefix}Failed. No video found."})
                            failed_count += 1
                            time.sleep(4)
                            continue
                            
                        if info.get('_type') == 'playlist' or info.get('_type') == 'multi_video':
                            continue
                            
                        # Determine the final file path
                        final_path = None
                        if 'requested_downloads' in info and info['requested_downloads']:
                            final_path = info['requested_downloads'][0].get('filepath')
                        if not final_path:
                            final_path = info.get('_filename') or ydl.prepare_filename(info)
                            
                        # Handle edge case where file was merged to .mp4 but info holds original extension
                        if final_path:
                            base, _ = os.path.splitext(final_path)
                            if not os.path.exists(final_path) and os.path.exists(base + ".mp4"):
                                final_path = base + ".mp4"
                            last_final_path = final_path
                                
                            # Extract first frame
                            if os.path.exists(final_path) and processing_options.get('extractFrame', True):
                                q.put({"status": f"{prefix}Extracting frame..."})
                                frame_path = base + "_first_frame.jpg"
                                ffmpeg_cmd = [
                                    imageio_ffmpeg.get_ffmpeg_exe(),
                                    "-y", 
                                    "-i", final_path,
                                    "-vframes", "1",
                                    "-q:v", "2",
                                    frame_path
                                ]
                                subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                
                                if processing_options.get('autoExtractPrompt'):
                                    q.put({"status": f"{prefix}Extracting AI Prompt (BLIP)..."})
                                    try:
                                        from ai_prompter import extract_prompt_from_image
                                        target_image = frame_path if os.path.exists(frame_path) else final_path
                                        if os.path.exists(target_image):
                                            prompt_text = extract_prompt_from_image(target_image)
                                            
                                            llm_model_choice = processing_options.get('llmModel', 'none')
                                            if llm_model_choice and llm_model_choice != 'none':
                                                q.put({"status": f"{prefix}Enhancing prompt with Local LLM..."})
                                                sys_p = "You are an expert AI prompt engineer. Take the basic image description and rewrite it into a highly detailed, professional prompt optimized for Nano Banana Pro and Nano Banana 2 image generation models. Focus on lighting, mood, camera angles, and high quality keywords. Output ONLY the prompt text, nothing else."
                                                try:
                                                    prompt_text = llm_generate(prompt_text, sys_p, llm_model_choice)
                                                except Exception as e:
                                                    print(f"LLM Enhancement Error: {e}")
                                            
                                            prompt_txt_path = base + "_prompt.txt"
                                            with open(prompt_txt_path, "w", encoding="utf-8") as f:
                                                f.write(prompt_text)
                                    except Exception as e:
                                        q.put({"status": f"{prefix}Prompt Extraction Error: {str(e)}"})
                                
                                # Audio Recognition & Metadata
                                if processing_options.get('identifySong', True):
                                    q.put({"status": f"{prefix}Identifying song & metadata..."})
                                    song_txt_path = base + "_song.txt"
                                    temp_audio = base + "_temp_audio.mp3"
                                    
                                    # Extract 15 seconds of audio
                                    ffmpeg_audio_cmd = [
                                        imageio_ffmpeg.get_ffmpeg_exe(),
                                        "-y",
                                        "-i", final_path,
                                        "-t", "15",
                                        "-vn",
                                        "-acodec", "libmp3lame",
                                        temp_audio
                                    ]
                                    subprocess.run(ffmpeg_audio_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                    
                                    shazam_track = None
                                    shazam_artist = None
                                    
                                    if os.path.exists(temp_audio):
                                        shazam_res = shazam_file(temp_audio)
                                        if shazam_res and 'track' in shazam_res:
                                            shazam_track = shazam_res['track'].get('title')
                                            shazam_artist = shazam_res['track'].get('subtitle')
                                        try:
                                            os.remove(temp_audio)
                                        except Exception:
                                            pass
                                            
                                    # Write metadata to files
                                    yt_track = info.get('track') or info.get('alt_title')
                                    yt_artist = info.get('artist') or info.get('creator')
                                    yt_desc = info.get('description', '')
                                    
                                    with open(song_txt_path, "w", encoding="utf-8") as f:
                                        f.write("--- VIDEO AUDIO INFO ---\n\n")
                                        if shazam_track:
                                            f.write(f" Shazam Match:\n")
                                            f.write(f"Song: {shazam_track}\n")
                                            f.write(f"Artist: {shazam_artist}\n\n")
                                        else:
                                            f.write(f" Shazam Match: No match found.\n\n")
                                            
                                        f.write(f" Original Upload Metadata (yt-dlp):\n")
                                        f.write(f"Track: {yt_track or 'Unknown'}\n")
                                        f.write(f"Artist/Creator: {yt_artist or 'Unknown'}\n")

                                    if yt_desc:
                                        caption_txt_path = base + "_caption.txt"
                                        with open(caption_txt_path, "w", encoding="utf-8") as f:
                                            f.write(yt_desc)
                                        
                                # Transcribe Video (Whisper)
                                if processing_options.get('transcribeAudio', True):
                                    q.put({"status": f"{prefix}Transcribing speech..."})
                                    transcript_path = base + "_transcript.txt"
                                    full_audio = base + "_full_audio.mp3"
                                    
                                    ffmpeg_full_audio = [
                                        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", final_path,
                                        "-vn", "-acodec", "libmp3lame", full_audio
                                    ]
                                    subprocess.run(ffmpeg_full_audio, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                    
                                    if os.path.exists(full_audio):
                                        try:
                                            model = get_whisper()
                                            result = model.transcribe(full_audio, verbose=False)
                                            transcript_text = result.get("text", "").strip()
                                            with open(transcript_path, "w", encoding="utf-8") as f:
                                                f.write(transcript_text)
                                                
                                            if processing_options.get('aiSummarize') and transcript_text:
                                                llm_model_choice = processing_options.get('llmModel', 'none')
                                                if llm_model_choice and llm_model_choice != 'none':
                                                    q.put({"status": f"{prefix}Generating AI Summary & SEO Tags..."})
                                                    sys_p = "You are an expert social media manager. Read the video transcript and output: 1) A clean, bulleted summary of key points. 2) 3 viral TikTok/Reels captions. 3) SEO-optimized hashtags."
                                                    try:
                                                        summary_text = llm_generate(transcript_text, sys_p, llm_model_choice)
                                                        summary_path = base + "_AI_Summary.txt"
                                                        with open(summary_path, "w", encoding="utf-8") as sf:
                                                            sf.write(summary_text)
                                                    except Exception as e:
                                                        print(f"LLM Summarize Error: {e}")
                                                
                                            want_burn = processing_options.get('burn_subtitles')
                                            want_export = processing_options.get('export_subtitles')
                                            
                                            if (want_burn or want_export) and final_path.endswith(('.mp4', '.mkv', '.mov')):
                                                srt_path = base + "_subtitles.srt"
                                                def format_timestamp(seconds):
                                                    ms = int((seconds - int(seconds)) * 1000)
                                                    s = int(seconds) % 60
                                                    m = int(seconds / 60) % 60
                                                    h = int(seconds / 3600)
                                                    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
                                                    
                                                with open(srt_path, "w", encoding="utf-8") as srt_f:
                                                    for i, segment in enumerate(result.get("segments", []), start=1):
                                                        srt_f.write(f"{i}\n")
                                                        srt_f.write(f"{format_timestamp(segment['start'])} --> {format_timestamp(segment['end'])}\n")
                                                        srt_f.write(f"{segment['text'].strip()}\n\n")
                                                        
                                                if want_burn:
                                                    q.put({"status": f"{prefix}Burning subtitles into video..."})
                                                    temp_sub = base + "_subbed.mp4"
                                                    rel_srt = os.path.relpath(srt_path).replace('\\', '/')
                                                    rel_srt = rel_srt.replace(':', '\\:').replace(',', '\\,').replace("'", "\\'")
                                                    
                                                    ffmpeg_sub = [
                                                        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", final_path,
                                                        "-vf", f"subtitles='{rel_srt}'", "-c:a", "copy", temp_sub
                                                    ]
                                                    subprocess.run(ffmpeg_sub, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                                    if os.path.exists(temp_sub):
                                                        os.replace(temp_sub, final_path)
                                                
                                                if not want_export and os.path.exists(srt_path):
                                                    try: os.remove(srt_path)
                                                    except: pass
                                                    
                                        except Exception as e:
                                            print("Whisper error:", e)
                                        try:
                                            os.remove(full_audio)
                                        except Exception:
                                            pass
                                            
                                # Force H.264 Encoding (Fixes AI tool compatibility)
                                if processing_options.get('forceH264') and final_path.endswith('.mp4'):
                                    q.put({"status": f"{prefix}Forcing Standard Encoding (H.264)..."})
                                    temp_h264 = base + "_h264_temp.mp4"
                                    ffmpeg_h264_cmd = [
                                        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", final_path,
                                        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                                        "-c:a", "aac", "-pix_fmt", "yuv420p", "-movflags", "+faststart", temp_h264
                                    ]
                                    subprocess.run(ffmpeg_h264_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                    if os.path.exists(temp_h264):
                                        os.replace(temp_h264, final_path)
                                        
                                # AI Bypass (Clean & Scramble)
                                if processing_options.get('aiBypass'):
                                    q.put({"status": f"{prefix}Applying AI Bypass (Scramble & Clean)..."})
                                    from cleaner import clean_video, clean_photo, backup_file
                                    
                                    # Backup first
                                    backup_file(final_path, DEFAULT_SAVE_DIR)
                                    
                                    ext = final_path.split('.')[-1].lower()
                                    is_vid = ext in ['mp4', 'mov', 'm4v', 'webm', 'avi', 'mkv']
                                    
                                    if is_vid:
                                        success, msg = clean_video(final_path, imageio_ffmpeg.get_ffmpeg_exe())
                                    else:
                                        success, msg = clean_photo(final_path)
                                        
                                    if not success:
                                        q.put({"status": f"{prefix}AI Bypass Failed: {msg}"})
                                
                                # Add to history
                                title = info.get('title', 'Unknown Title')
                                uploader = info.get('uploader', 'Unknown')
                                platform = info.get('extractor_key', 'Other')
                                add_history_entry(url, title, uploader, final_path, platform)
                except Exception as e:
                    error_msg = str(e)
                    error_msg = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', error_msg)
                    q.put({"status": f"{prefix}Error: {error_msg}"})
                    
            
            if failed_count == 0:
                q.put({"status": "All Downloads Complete!", "done": True, "file_path": last_final_path, "output_path": output_path})
            else:
                q.put({"status": f"Complete! ({failed_count} failed)", "done": True, "file_path": last_final_path, "output_path": output_path})

        t = threading.Thread(target=run_dl, daemon=True)
        t.start()

        try:
            while True:
                try:
                    msg = q.get(timeout=120)
                except queue.Empty:
                    yield f"data: {json.dumps({'error': 'Task timed out.'})}\n\n"
                    break
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("done") or msg.get("error") or msg.get("action_required"):
                    break
        finally:
            if task_id in cancel_flags:
                del cancel_flags[task_id]

    return Response(generate(), mimetype='text/event-stream')




_gallery_cache = {"time": 0, "data": []}

@app.route('/api/gallery', methods=['GET'])
def list_gallery():
    global _gallery_cache
    if time.time() - _gallery_cache["time"] < 2:
        return jsonify(_gallery_cache["data"])
        
    base_dir = os.path.join(os.path.expanduser("~"), "Documents", "Media Grabber")
    folders = ['YouTube', 'Instagram', 'TikTok', 'Twitter', 'Other', 'Conversions']
    
    media = []
    
    for folder in folders:
        folder_path = os.path.join(base_dir, folder)
        if os.path.exists(folder_path):
            for root, _, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    if os.path.isfile(file_path):
                        ext = os.path.splitext(file)[1].lower()
                        if ext in ['.mp4', '.mov', '.mkv', '.webm', '.avi', '.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp3']:
                            rel_dir = os.path.relpath(root, folder_path)
                            if rel_dir == '.':
                                item_path = file
                            else:
                                item_path = f"{rel_dir}/{file}".replace('\\', '/')
                            
                            media.append({
                                "name": file,
                                "folder": folder,
                                "path": f"{folder}/{item_path}",
                                "full_path": file_path,
                                "type": "video" if ext in ['.mp4', '.mov', '.mkv', '.webm', '.avi'] else "audio" if ext == ".mp3" else "image",
                                "timestamp": os.path.getmtime(file_path),
                                "size": os.path.getsize(file_path)
                            })
                        
    media.sort(key=lambda x: x['timestamp'], reverse=True)
    _gallery_cache["time"] = time.time()
    _gallery_cache["data"] = media
    return jsonify(media)

@app.route('/api/media/<folder>/<path:filename>')
def serve_media(folder, filename):
    base_dir = os.path.join(os.path.expanduser("~"), "Documents", "Media Grabber")
    safe_folder = os.path.basename(folder)
    return send_from_directory(os.path.join(base_dir, safe_folder), filename)

@app.route('/api/open_folder', methods=['POST'])
def open_folder():
    path = request.json.get('path')
    if not path or not os.path.exists(path) or not is_safe_path(path):
        return jsonify({"error": "Path not found or forbidden"}), 403
    
    abs_path = os.path.abspath(path)
    if sys.platform == 'win32':
        if os.path.isfile(abs_path):
            subprocess.run(['explorer', '/select,', abs_path])
        else:
            os.startfile(abs_path)
    elif sys.platform == 'darwin':
        if os.path.isfile(abs_path):
            subprocess.run(['open', '-R', abs_path])
        else:
            subprocess.run(['open', abs_path])
    else:
        # Linux
        dir_to_open = os.path.dirname(abs_path) if os.path.isfile(abs_path) else abs_path
        subprocess.run(['xdg-open', dir_to_open])
        
    return jsonify({"success": True})

@app.route('/api/extract_prompt', methods=['POST'])
def extract_prompt():
    data = request.json
    path = data.get('path')
    if not path or not os.path.exists(path) or not is_safe_path(path):
        return jsonify({"error": "File not found or forbidden"}), 404
        
    ext = os.path.splitext(path)[1].lower()
    is_video = ext in ['.mp4', '.mov', '.mkv', '.webm', '.avi']
    
    target_image = path
    temp_frame = None
    
    if is_video:
        temp_frame = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}.jpg")
        try:
            # Extract middle frame
            subprocess.run([
                imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", path, 
                "-vf", "select=eq(n\\,0)", "-vframes", "1", temp_frame
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(temp_frame):
                target_image = temp_frame
            else:
                return jsonify({"error": "Failed to extract frame from video"}), 500
        except Exception as e:
            return jsonify({"error": f"Video extraction error: {str(e)}"}), 500
            
    try:
        from ai_prompter import extract_prompt_from_image
        prompt = extract_prompt_from_image(target_image)
        return jsonify({"prompt": prompt})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if temp_frame and os.path.exists(temp_frame):
            try:
                os.remove(temp_frame)
            except Exception:
                pass

@app.route('/api/preview_file')
def preview_file():
    # send_file is imported at the top of the file
    path = request.args.get('path')
    if not path or not os.path.exists(path) or not os.path.isfile(path) or not is_safe_path(path):
        return "Not found or forbidden", 403
    return send_file(path)

@app.route('/api/batch_clean', methods=['POST'])
def batch_clean():
    data = request.json
    target_dirs = data.get('target_dirs', [])
    inject_exif = data.get('inject_exif', False)
    
    output_dir = os.path.join(DEFAULT_SAVE_DIR, "AI Cleaned")
    
    try:
        from cleaner import run_batch_cleaner
        return Response(run_batch_cleaner(target_dirs, output_dir, is_upload=False, inject_exif=inject_exif), mimetype='text/event-stream')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/batch_clean_upload', methods=['POST'])
def batch_clean_upload():
    if 'files' not in request.files:
        return jsonify({"error": "No files uploaded"}), 400
        
    files = request.files.getlist('files')
    if not files or not files[0].filename:
        return jsonify({"error": "No selected files"}), 400
        
    inject_exif = request.form.get('inject_exif', 'false').lower() == 'true'
        
    from werkzeug.utils import secure_filename
    upload_folder = os.path.join(DEFAULT_SAVE_DIR, "AI Cleaned", f"Uploaded_{int(time.time())}")
    os.makedirs(upload_folder, exist_ok=True)
    
    uploaded_paths = []
    for file in files:
        if file and file.filename:
            filename = secure_filename(file.filename)
            file_path = os.path.join(upload_folder, filename)
            file.save(file_path)
            uploaded_paths.append(file_path)
            
    try:
        from cleaner import run_batch_cleaner
        return Response(run_batch_cleaner(uploaded_paths, upload_folder, is_upload=True, inject_exif=inject_exif), mimetype='text/event-stream')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/history', methods=['GET'])
def get_history():
    return jsonify(load_history())

@app.route('/api/history', methods=['DELETE'])
def clear_history():
    save_history([])
    return jsonify({"success": True})

@app.route('/api/history/<history_id>', methods=['DELETE'])
def delete_history_item(history_id):
    h = load_history()
    h = [item for item in h if item.get('id') != history_id]
    save_history(h)
    return jsonify({"success": True})

@app.route('/api/gallery/delete', methods=['POST'])
def delete_gallery_item():
    path = request.json.get('path')
    if not path or not os.path.exists(path) or not is_safe_path(path):
        return jsonify({"error": "File not found or forbidden"}), 403
        
    try:
        from send2trash import send2trash
        send2trash(path)
    except Exception:
        try:
            os.remove(path)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    return jsonify({"success": True})

@app.route('/api/restart', methods=['POST'])
def restart_server():
    def restart_task():
        time.sleep(1.5)
        print("Restarting server from UI...", flush=True)
        os._exit(42) # Exits Python with code 42, which run.bat catches to loop and restart
    
    threading.Thread(target=restart_task).start()
    return jsonify({"status": "Restarting server..."})

if __name__ == '__main__':
    import webbrowser
    import threading
    from waitress import serve
    print("\n" + "="*50, flush=True)
    print(" SERVER ONLINE AND READY! http://127.0.0.1:5000 ", flush=True)
    print("="*50 + "\n", flush=True)
    # Launch browser precisely after the server is ready
    threading.Timer(1.25, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    serve(app, host='127.0.0.1', port=5000, threads=8)
